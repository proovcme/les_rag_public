#!/usr/bin/env python3
"""Build the immutable asset set for a lightweight LES GitHub Release."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

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
    args = parser.parse_args()
    build_github_patch_release(
        args.base, args.target, args.output, full_feed=args.full_feed
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
