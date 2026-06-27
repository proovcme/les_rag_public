"""Public repository guardrail for LES.

Checks tracked and untracked-not-ignored files. It deliberately avoids reading
ignored runtime data and private local archives.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


FORBIDDEN_PREFIXES = (
    ".venv/",
    "artifacts/",
    "data/",
    "logs/",
    "local_private_archive/",
    "RAG_Content/",
    "storage/",
)
FORBIDDEN_EXACT = {".env"}
REQUIRED_PUBLIC_FILES = ("README.md", "LICENSE", "SECURITY.md")
HIGH_SIGNAL_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b"),
)
ASSIGNMENT_SECRET_PATTERNS = (
    re.compile(
        r"\b[A-Z0-9_]*(?:API_KEY|ADMIN_KEY|SECRET|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN)[A-Z0-9_]*\b\s*=\s*"
        r"(?!$|[\"']?$|_|change_me|your_|example|placeholder|none|null|false|true|old-|.*-secret)"
        r"[\"']?[^\"'\s#]{12,}"
    ),
)
ASSIGNMENT_SKIP_PREFIXES = ("tests/", "docs/archive/", "legacy/")
SKIP_SCAN_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".xlsx", ".docx", ".parquet"}


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=10,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "git ls-files failed")
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def forbidden_tracked(paths: list[str]) -> list[str]:
    bad: list[str] = []
    for rel in paths:
        if rel in FORBIDDEN_EXACT or any(rel.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            bad.append(rel)
    return bad


def missing_required(root: Path) -> list[str]:
    return [rel for rel in REQUIRED_PUBLIC_FILES if not (root / rel).is_file()]


def secret_hits(root: Path, paths: list[str]) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for rel in paths:
        p = root / rel
        if p.suffix.lower() in SKIP_SCAN_SUFFIXES or not p.is_file():
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in HIGH_SIGNAL_SECRET_PATTERNS:
                if pat.search(line):
                    hits.append((rel, lineno, line.strip()[:160]))
                    break
            else:
                if rel.startswith(ASSIGNMENT_SKIP_PREFIXES):
                    continue
                for pat in ASSIGNMENT_SECRET_PATTERNS:
                    if pat.search(line):
                        hits.append((rel, lineno, line.strip()[:160]))
                        break
    return hits


def run(root: Path) -> tuple[bool, list[str]]:
    messages: list[str] = []
    paths = tracked_files(root)
    bad_paths = forbidden_tracked(paths)
    missing = missing_required(root)
    secrets = secret_hits(root, paths)
    if bad_paths:
        messages.append("Forbidden tracked paths:\n" + "\n".join(f"  - {p}" for p in bad_paths[:80]))
    if missing:
        messages.append("Missing public files:\n" + "\n".join(f"  - {p}" for p in missing))
    if secrets:
        messages.append(
            "Potential secrets in tracked files:\n"
            + "\n".join(f"  - {p}:{n}: {line}" for p, n, line in secrets[:80])
        )
    return not (bad_paths or missing or secrets), messages


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ok, messages = run(root)
    if ok:
        print("public-check OK: git-visible files contain no forbidden runtime paths or high-signal secrets.")
        return 0
    print("public-check FAIL", file=sys.stderr)
    for msg in messages:
        print(msg, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
