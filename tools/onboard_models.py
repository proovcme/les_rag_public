"""First-run model onboarding: pre-download local model weights.

The Mac installer (LES.app bootstrap) calls this once so the first chat does not
hang on a lazy download. Weights are fetched into the standard Hugging Face cache
via ``snapshot_download`` — idempotent (cached repos are skipped) and resumable.

Model ids are read from ``.env`` (falling back to ``env.example``), so this stays
in sync with whatever models the runtime is configured to use. Cloud-only setups
(no local MLX) can skip everything with ``--skip-if-cloud``.

Usage:
    uv run python tools/onboard_models.py            # download configured weights
    uv run python tools/onboard_models.py --list     # show what would be fetched
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Env keys that name a Hugging Face repo we want present locally on first run.
# Order matters only for display; duplicates are collapsed.
MODEL_ENV_KEYS = ("MLX_MODEL", "LLM_MODEL", "EMBEDDING_MODEL")

# Fallbacks if the key is absent from both .env and env.example.
DEFAULTS = {
    "MLX_MODEL": "mlx-community/Qwen3.5-4B-OptiQ-4bit",
    "EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-0.6B",
}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip inline comments and surrounding quotes/whitespace.
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        if value:
            values[key.strip()] = value
    return values


def resolve_models() -> list[str]:
    env = _read_env_file(ROOT / "env.example")
    env.update(_read_env_file(ROOT / ".env"))  # .env wins
    repos: list[str] = []
    for key in MODEL_ENV_KEYS:
        repo = env.get(key) or DEFAULTS.get(key, "")
        # Skip non-HF references (local paths, ollama tags like "gemma4:12b").
        if not repo or repo.startswith(("/", ".")) or ":" in repo or "/" not in repo:
            continue
        if repo not in repos:
            repos.append(repo)
    return repos


def is_cloud_only() -> bool:
    env = _read_env_file(ROOT / ".env")
    provider = (env.get("LES_PROVIDER") or env.get("PROVIDER") or "").lower()
    return provider in {"openai", "openrouter", "cloud"}


def download(repo_id: str) -> bool:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # pragma: no cover - depends on install extra
        print(f"[onboard] huggingface_hub unavailable: {exc}", file=sys.stderr)
        return False
    print(f"[onboard] ensuring {repo_id} …")
    try:
        snapshot_download(repo_id=repo_id)
    except Exception as exc:
        print(f"[onboard] FAILED {repo_id}: {exc}", file=sys.stderr)
        return False
    print(f"[onboard] ok {repo_id}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-download LES local model weights.")
    parser.add_argument("--list", action="store_true", help="print resolved models and exit")
    parser.add_argument(
        "--skip-if-cloud",
        action="store_true",
        help="do nothing when the active provider is cloud (openai/openrouter)",
    )
    args = parser.parse_args(argv)

    models = resolve_models()
    if args.list:
        for repo in models:
            print(repo)
        return 0

    if args.skip_if_cloud and is_cloud_only():
        print("[onboard] cloud provider active — skipping local weight download")
        return 0

    if not models:
        print("[onboard] no local HF models configured — nothing to download")
        return 0

    ok = all(download(repo) for repo in models)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
