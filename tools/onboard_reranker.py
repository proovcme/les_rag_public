"""Pre-download the native cross-encoder used by Windows production RAG."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
EXPECTED_WEIGHTS = {
    DEFAULT_MODEL: {
        "model.safetensors": "d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286",
    }
}
VERIFICATION_MARKER = ".les-reranker-verified.json"


class ModelIntegrityError(RuntimeError):
    pass


def configured_model() -> str:
    return os.getenv("RERANK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def download_model(snapshot_download, model: str, *, force_download: bool = False) -> str:
    """Use the official Hub first and a configurable mirror as bounded fallback."""
    common = {"repo_id": model, "etag_timeout": 20}
    if force_download:
        common["force_download"] = True
    try:
        return str(snapshot_download(**common))
    except Exception as first_error:
        mirror = os.getenv("HF_MIRROR_ENDPOINT", "https://hf-mirror.com").strip()
        if not mirror:
            raise
        print(
            f"[onboard] official Hugging Face failed ({type(first_error).__name__}); "
            f"retrying via {mirror}",
            file=sys.stderr,
        )
        return str(snapshot_download(**common, endpoint=mirror))


def sha256_file(path: Path, *, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def verify_snapshot(snapshot_path: str | Path, model: str) -> dict[str, str]:
    snapshot = Path(snapshot_path)
    if not snapshot.is_dir():
        raise ModelIntegrityError(f"snapshot directory is missing: {snapshot}")
    expected = EXPECTED_WEIGHTS.get(model, {})
    checked: dict[str, str] = {}
    for relative, expected_sha in expected.items():
        path = snapshot / relative
        if not path.is_file():
            raise ModelIntegrityError(f"required reranker weight is missing: {path}")
        actual = sha256_file(path)
        checked[relative] = actual
        if actual.casefold() != expected_sha.casefold():
            raise ModelIntegrityError(
                f"checksum mismatch for {path}: expected {expected_sha}, got {actual}"
            )
    if not (snapshot / "config.json").is_file():
        raise ModelIntegrityError(f"reranker config is missing: {snapshot / 'config.json'}")
    return checked


def quarantine_corrupt_weights(snapshot_path: str | Path, model: str) -> list[Path]:
    """Remove a bad cache entry from the published name without deleting evidence."""
    snapshot = Path(snapshot_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantined: list[Path] = []
    for relative in EXPECTED_WEIGHTS.get(model, {}):
        published = snapshot / relative
        if not (published.exists() or published.is_symlink()):
            continue
        resolved = published.resolve(strict=False)
        target = resolved.with_name(f"{resolved.name}.corrupt-{stamp}")
        if resolved.exists():
            resolved.replace(target)
            quarantined.append(target)
        if published.is_symlink():
            published.unlink(missing_ok=True)
    return quarantined


def model_load_probe(snapshot_path: str | Path) -> list[float]:
    """Load the exact local snapshot and prove it separates a relevant pair."""
    from sentence_transformers import CrossEncoder

    encoder = CrossEncoder(str(snapshot_path), device="cpu")
    raw = encoder.predict(
        [
            ("монтаж кабеля", "В документе описан монтаж кабеля."),
            ("монтаж кабеля", "Температура наружного воздуха."),
        ],
        batch_size=2,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    scores = [float(value) for value in raw]
    if len(scores) != 2 or scores[0] <= scores[1]:
        raise ModelIntegrityError(f"reranker load probe returned invalid semantic order: {scores}")
    return scores


def verification_marker_valid(snapshot_path: str | Path, model: str) -> bool:
    snapshot = Path(snapshot_path)
    marker_path = snapshot / VERIFICATION_MARKER
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if payload.get("model") != model:
        return False
    for relative, expected_sha in EXPECTED_WEIGHTS.get(model, {}).items():
        path = snapshot / relative
        try:
            stat = path.stat()
        except OSError:
            return False
        recorded = (payload.get("files") or {}).get(relative) or {}
        if (
            recorded.get("sha256") != expected_sha
            or int(recorded.get("size") or -1) != stat.st_size
            or int(recorded.get("mtime_ns") or -1) != stat.st_mtime_ns
        ):
            return False
    return True


def write_verification_marker(snapshot_path: str | Path, model: str, checked: dict[str, str]) -> Path:
    snapshot = Path(snapshot_path)
    files = {}
    for relative, sha in checked.items():
        stat = (snapshot / relative).stat()
        files[relative] = {"sha256": sha, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    marker = snapshot / VERIFICATION_MARKER
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema": "les.reranker-verification.v1",
                "model": model,
                "files": files,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(marker)
    return marker


def main() -> int:
    backend = os.getenv("RERANKER_BACKEND", "sentence_transformers").strip().lower()
    if backend != "sentence_transformers":
        print(f"[onboard] reranker backend {backend} does not use Hugging Face weights — skipping")
        return 0
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        print(f"[onboard] huggingface_hub unavailable: {exc}", file=sys.stderr)
        return 1
    model = configured_model()
    print(f"[onboard] ensuring reranker {model} …")
    try:
        try:
            cached = str(snapshot_download(repo_id=model, local_files_only=True))
        except Exception:
            cached = ""
        if cached and verification_marker_valid(cached, model):
            print(f"[onboard] ok {model}; verified cache marker")
            return 0
        snapshot = download_model(snapshot_download, model)
        try:
            checked = verify_snapshot(snapshot, model)
        except ModelIntegrityError as integrity_error:
            quarantined = quarantine_corrupt_weights(snapshot, model)
            print(
                f"[onboard] corrupt cache quarantined ({quarantined}): {integrity_error}",
                file=sys.stderr,
            )
            # The published blob/link is gone now. A normal Hub download can
            # resume its ``.incomplete`` file; force_download would discard it.
            snapshot = download_model(snapshot_download, model)
            checked = verify_snapshot(snapshot, model)
        scores = model_load_probe(snapshot)
        write_verification_marker(snapshot, model, checked)
    except Exception as exc:
        print(f"[onboard] FAILED {model}: {exc}", file=sys.stderr)
        return 1
    print(f"[onboard] ok {model}; weights={checked}; probe={scores}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
