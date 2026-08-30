#!/usr/bin/env python3
"""Validate the small canonical LES documentation surface."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PATHS = (
    "AGENTS.md",
    "SKILL.md",
    "docs/MODULE_INDEX.md",
    "docs/CODE_MAP.md",
    "docs/SOFTWARE_VERSIONS.md",
    "ROADMAP_TO_V1.md",
    "docs/RELEASE_LEDGER.md",
    "docs/unified_harness_failure_ledger.md",
    "docs/TEST_INVENTORY.md",
)
ENTRY_PATHS = ("README.md", "docs/index.md", "docs/archive/README.md")
ROADMAP_LINE_LIMIT = 300
_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _without_code_fences(text: str) -> str:
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = _FENCE_RE.match(line)
        if marker:
            current = marker.group(1)
            if fence is None:
                fence = current
            elif current == fence:
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return "\n".join(lines)


def _local_targets(text: str) -> tuple[str, ...]:
    targets: list[str] = []
    for match in _LINK_RE.finditer(_without_code_fences(text)):
        raw = match.group(1).strip()
        if raw.startswith("<") and ">" in raw:
            raw = raw[1 : raw.index(">")]
        else:
            raw = raw.split(maxsplit=1)[0]
        parsed = urlparse(raw)
        if parsed.scheme or raw.startswith("//") or raw.startswith("#"):
            continue
        path = unquote(raw.split("#", 1)[0].split("?", 1)[0]).strip()
        if path:
            targets.append(path)
    return tuple(targets)


def audit_documentation(root: Path) -> list[str]:
    """Return deterministic findings for missing canon, broken links and roadmap bloat."""
    root = Path(root).resolve()
    findings: list[str] = []
    checked = (*CANONICAL_PATHS, *ENTRY_PATHS)
    for relative in checked:
        source = root / relative
        if not source.is_file():
            findings.append(f"{relative}: missing canonical document")
            continue
        text = source.read_text(encoding="utf-8-sig")
        for target in _local_targets(text):
            candidate = (source.parent / target).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                findings.append(f"{relative} -> {target}: outside repository")
                continue
            if not candidate.exists():
                findings.append(f"{relative} -> {target}: missing")
    roadmap = root / "ROADMAP_TO_V1.md"
    if roadmap.is_file():
        line_count = len(roadmap.read_text(encoding="utf-8-sig").splitlines())
        if line_count > ROADMAP_LINE_LIMIT:
            findings.append(
                f"ROADMAP_TO_V1.md: exceeds {ROADMAP_LINE_LIMIT} lines"
            )
    return sorted(set(findings))


def main() -> int:
    findings = audit_documentation(ROOT)
    if findings:
        for finding in findings:
            print(f"FAIL: {finding}")
        return 1
    print("documentation contract: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
