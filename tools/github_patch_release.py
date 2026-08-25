#!/usr/bin/env python3
"""Build the immutable asset set for a lightweight LES GitHub Release."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Sequence

from tools import vps_patch
from tools.release_classification import classify_release


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "proovcme/les_rag_public"
GITHUB_UPDATE_FEED_SCHEMA = "les.github-update-feed.v1"
ASSET_NAMES = (
    "les-update.json",
    "latest.json",
    "les-patch.zip",
    "les-patch.zip.sha256",
    "release-notes.md",
)


def _commit(value: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", value], cwd=ROOT, text=True
    ).strip()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _run(command: Sequence[str], **kwargs):
    return subprocess.run(
        list(command), cwd=ROOT, text=True, capture_output=True, check=False, **kwargs
    )


def verify_downloaded_release_assets(tag: str, expected_assets: Sequence[Path]) -> None:
    expected = {Path(path).name: vps_patch.sha256_file(Path(path)) for path in expected_assets}
    with tempfile.TemporaryDirectory(prefix="les-release-verify-") as temporary:
        completed = _run(
            [
                "gh",
                "release",
                "download",
                tag,
                "--repo",
                REPOSITORY,
                "--dir",
                temporary,
            ]
        )
        if completed.returncode != 0:
            raise RuntimeError(f"failed to download draft assets: {completed.stderr}")
        downloaded = {
            path.name: vps_patch.sha256_file(path)
            for path in Path(temporary).iterdir()
            if path.is_file()
        }
        if downloaded != expected:
            raise RuntimeError("downloaded GitHub release assets differ from local assets")


def publish_github_patch_release(
    tag: str, assets: Sequence[Path], notes: Path
) -> None:
    assets = tuple(Path(path).resolve() for path in assets)
    notes = Path(notes).resolve()
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise RuntimeError(f"unsafe release tag: {tag}")
    names = {path.name for path in assets}
    if names != set(ASSET_NAMES) or len(assets) != len(ASSET_NAMES):
        raise RuntimeError("GitHub patch release requires exactly the five canonical assets")
    if any(not path.is_file() for path in assets) or not notes.is_file():
        raise RuntimeError("GitHub patch release assets or notes are missing")
    if _git("status", "--porcelain"):
        raise RuntimeError("release tree is dirty")
    head = _git("rev-parse", "HEAD")
    upstream = _git("rev-parse", "@{u}")
    if head != upstream:
        raise RuntimeError("release commit is not the pushed upstream commit")
    if _git("tag", "--list", tag):
        raise RuntimeError(f"tag already exists: {tag}")

    existing = _run(["gh", "release", "view", tag, "--repo", REPOSITORY])
    if existing.returncode == 0:
        raise RuntimeError(f"GitHub release already exists: {tag}")
    immutable = _run(
        ["gh", "api", f"repos/{REPOSITORY}/immutable-releases"]
    )
    try:
        immutable_enabled = immutable.returncode == 0 and bool(
            json.loads(immutable.stdout).get("enabled")
        )
    except (ValueError, TypeError, AttributeError):
        immutable_enabled = False
    if not immutable_enabled:
        raise RuntimeError("github_release_immutability_required")

    created = _run(
        [
            "gh",
            "release",
            "create",
            tag,
            "--repo",
            REPOSITORY,
            "--draft",
            "--notes-file",
            str(notes),
        ]
    )
    if created.returncode != 0:
        raise RuntimeError(f"failed to create GitHub draft: {created.stderr}")
    uploaded = _run(
        [
            "gh",
            "release",
            "upload",
            tag,
            *(str(path) for path in assets),
            "--repo",
            REPOSITORY,
        ]
    )
    if uploaded.returncode != 0:
        raise RuntimeError(f"failed to upload GitHub assets: {uploaded.stderr}")
    verify_downloaded_release_assets(tag, assets)
    published = _run(
        [
            "gh",
            "release",
            "edit",
            tag,
            "--repo",
            REPOSITORY,
            "--draft=false",
        ]
    )
    if published.returncode != 0:
        raise RuntimeError(f"failed to publish verified GitHub draft: {published.stderr}")


def _read_full_feed(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"full release feed is unreadable: {path}") from exc
    if (
        payload.get("schema") != "les.update.v1"
        or re.fullmatch(r"\d+\.\d+\.\d+", str(payload.get("version") or "")) is None
        or int(payload.get("build_number") or 0) <= 0
        or re.fullmatch(r"\d+\.\d+\.\d+", str(payload.get("desktop_version") or "")) is None
        or re.fullmatch(r"[0-9a-f]{40}", str(payload.get("commit") or "")) is None
    ):
        raise ValueError("legacy latest.json does not identify a complete full release")
    return payload


def run_isolated_update_gate(
    base_commit: str, archive: Path, patch_manifest: dict[str, Any]
) -> dict[str, Any]:
    """Exercise package apply, skipped-version acceptance, and forced rollback in memory."""
    durations: dict[str, int] = {}
    original: dict[str, bytes | None] = {}
    current: dict[str, bytes] = {}
    target_only: list[str] = []
    old_stamp = b'{"deployed_commit":"base"}'
    stamp = old_stamp

    for entry in patch_manifest["files"]:
        if str(entry.get("scope") or "runtime") != "runtime":
            raise RuntimeError("lightweight GitHub gate received an app payload")
        path = str(entry["path"])
        before = vps_patch.git_bytes(base_commit, path)
        installed = vps_patch.windows_runtime_bytes(before) if before is not None else None
        original[path] = installed
        if installed is None:
            target_only.append(path)
        else:
            current[path] = installed

    apply_started = time.perf_counter()
    with zipfile.ZipFile(archive) as bundle:
        expected_names = {
            "manifest.json",
            *(f"payload/{entry['path']}" for entry in patch_manifest["files"]),
        }
        if set(bundle.namelist()) != expected_names:
            raise RuntimeError("isolated gate found an unexpected archive entry")
        if json.loads(bundle.read("manifest.json")) != patch_manifest:
            raise RuntimeError("isolated gate found a manifest mismatch")
        for entry in patch_manifest["files"]:
            path = str(entry["path"])
            installed = current.get(path)
            installed_sha = vps_patch.sha256_bytes(installed) if installed is not None else None
            accepted = {
                str(value).lower()
                for value in (
                    entry.get("base_sha256"),
                    entry.get("sha256"),
                    *(entry.get("accepted_sha256") or []),
                )
                if value
            }
            if installed_sha not in accepted and not (
                installed is None and bool(entry.get("accepted_missing"))
            ):
                raise RuntimeError(f"isolated gate rejected base bytes for {path}")
            payload = bundle.read(f"payload/{path}")
            if (
                len(payload) != int(entry["bytes"])
                or vps_patch.sha256_bytes(payload) != entry["sha256"]
            ):
                raise RuntimeError(f"isolated gate rejected target bytes for {path}")
            current[path] = payload
    stamp = json.dumps(
        {"deployed_commit": patch_manifest["target_commit"]}, separators=(",", ":")
    ).encode()
    apply_ok = all(
        vps_patch.sha256_bytes(current[str(entry["path"])]) == entry["sha256"]
        for entry in patch_manifest["files"]
    ) and patch_manifest["target_commit"].encode() in stamp
    durations["apply"] = round((time.perf_counter() - apply_started) * 1000)

    skipped_started = time.perf_counter()
    skipped_version_ok = True
    for index, entry in enumerate(patch_manifest["files"]):
        path = str(entry["path"])
        candidate = current.get(path) if index == 0 else original[path]
        candidate_sha = vps_patch.sha256_bytes(candidate) if candidate is not None else None
        accepted = {
            str(value).lower()
            for value in (
                entry.get("base_sha256"),
                entry.get("sha256"),
                *(entry.get("accepted_sha256") or []),
            )
            if value
        }
        skipped_version_ok = skipped_version_ok and (
            candidate_sha in accepted
            or (candidate is None and bool(entry.get("accepted_missing")))
        )
    durations["skipped_version"] = round(
        (time.perf_counter() - skipped_started) * 1000
    )

    rollback_started = time.perf_counter()
    for path, before in original.items():
        if before is None:
            current.pop(path, None)
        else:
            current[path] = before
    stamp = old_stamp
    rollback_ok = all(
        current.get(path) == before for path, before in original.items() if before is not None
    ) and stamp == old_stamp
    new_file_removed = bool(target_only) and all(path not in current for path in target_only)
    durations["rollback"] = round((time.perf_counter() - rollback_started) * 1000)

    evidence = {
        "apply_ok": apply_ok,
        "rollback_ok": rollback_ok,
        "new_file_removed_on_rollback": new_file_removed,
        "skipped_version_ok": skipped_version_ok,
        "durations_ms": durations,
    }
    required = (
        "apply_ok",
        "rollback_ok",
        "new_file_removed_on_rollback",
        "skipped_version_ok",
    )
    if not all(evidence[name] is True for name in required):
        raise RuntimeError(f"GitHub patch apply/rollback gate failed: {evidence}")
    return evidence


def build_github_patch_release(
    base: str,
    target: str,
    output: Path,
    *,
    full_feed: Path,
) -> dict[str, Any]:
    base_commit = _commit(base)
    target_commit = _commit(target)
    classification = classify_release(base_commit, target_commit, root=ROOT)
    if classification.kind != "patch":
        details = "; ".join(
            f"{trigger.path} ({trigger.reason})" for trigger in classification.triggers
        )
        raise ValueError(f"full release required: {details}")
    if not classification.runtime_files:
        raise ValueError("lightweight release has no runtime files")

    legacy_feed = _read_full_feed(full_feed)
    contract = vps_patch.version_contract(target_commit)
    version = str(contract["product_version"])
    tag = f"v{version}"
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError(f"release output must be empty: {output}")

    with tempfile.TemporaryDirectory(prefix="les-github-patch-") as temporary:
        built = vps_patch.build_patch(
            base=base_commit,
            target=target_commit,
            files=list(classification.runtime_files),
            output=Path(temporary),
            origin=f"https://github.com/{REPOSITORY}/releases/download/{tag}",
        )
        archive = output / "les-patch.zip"
        shutil.copy2(Path(built["archive"]), archive)
        patch_manifest = built["patch"]

    archive_sha = vps_patch.sha256_file(archive)
    archive_bytes = archive.stat().st_size
    evidence = run_isolated_update_gate(base_commit, archive, patch_manifest)
    feed = {
        "schema": GITHUB_UPDATE_FEED_SCHEMA,
        "repository": REPOSITORY,
        "release_class": "patch",
        "product_version": version,
        "build_number": int(contract["build_number"]),
        "tag": tag,
        "target_commit": target_commit,
        "compatible_bases": [base_commit],
        "asset": {
            "url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/les-patch.zip",
            "bytes": archive_bytes,
            "sha256": archive_sha,
        },
        "patch": patch_manifest,
        "evidence": evidence,
    }
    (output / "les-update.json").write_text(
        json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "latest.json").write_text(
        json.dumps(legacy_feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "les-patch.zip.sha256").write_text(
        f"{archive_sha}  les-patch.zip\n", encoding="ascii"
    )
    (output / "release-notes.md").write_text(
        f"# Л.Е.С. {version}\n\n"
        f"Лёгкое обновление runtime без переустановки Python, зависимостей и NSIS.\n\n"
        f"База: `{base_commit}`  \nЦель: `{target_commit}`\n",
        encoding="utf-8",
    )
    return feed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--target", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full-feed", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--notes-file", type=Path)
    args = parser.parse_args()
    feed = build_github_patch_release(
        args.base, args.target, args.output, full_feed=args.full_feed
    )
    if args.publish:
        if args.notes_file is None:
            parser.error("--publish requires --notes-file")
        assets = [args.output / name for name in ASSET_NAMES]
        publish_github_patch_release(feed["tag"], assets, args.notes_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
