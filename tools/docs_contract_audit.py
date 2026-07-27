"""Audit the living LES documentation contract without network access.

``docs/archive`` is inventoried but is not treated as current operational
guidance, so historical links and commands do not block the living-doc gate.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path


REQUIRED_FILES = (
    "AGENTS.md",
    "SKILL.md",
    "README.md",
    "INSTALL.md",
    "ROADMAP_TO_V1.md",
    "config/version.json",
    "docs/MODULE_INDEX.md",
    "docs/CODE_MAP.md",
    "docs/SOFTWARE_VERSIONS.md",
    "docs/RELEASE_LEDGER.md",
    "docs/TEST_INVENTORY.md",
    "docs/DOCUMENTATION_PLAYBOOK.md",
    "docs/DOCUMENTATION_AUDIT_2026-07-23.md",
    "docs/PUBLICATION_CHECKLIST.md",
    "docs/ALGORITHM_INDEX.md",
    "docs/SKILL_INDEX.md",
    "docs/ALGO-rag-best-practices.md",
    "docs/ALGO-smeta.md",
    "docs/ALGO-normcontrol.md",
)
PUBLIC_CLONE_RE = re.compile(
    r"git\s+clone[^\n]*github\.com[:/]proovcme/les_rag\.git",
    re.IGNORECASE,
)
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*]\(([^)]+)\)")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
URL_SCHEMES = ("http://", "https://", "mailto:", "file://", "app://")


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    line: int
    detail: str


def _git_files(root: Path, *patterns: str) -> list[str]:
    command = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    if patterns:
        command.extend(["--", *patterns])
    result = subprocess.run(
        command,
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return [line for line in result.stdout.splitlines() if line]


def documentation_files(root: Path) -> list[Path]:
    """Return git-visible Markdown, including initialized product submodules."""
    files = [root / rel for rel in _git_files(root, "*.md", "**/*.md")]
    gitmodules = root / ".gitmodules"
    if gitmodules.is_file():
        paths = re.findall(
            r"^\s*path\s*=\s*(.+?)\s*$",
            gitmodules.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        for rel_path in paths:
            submodule = root / rel_path
            if not (submodule / ".git").exists():
                continue
            try:
                tracked = _git_files(submodule, "*.md", "**/*.md")
            except (OSError, subprocess.SubprocessError):
                continue
            files.extend(submodule / rel for rel in tracked)
    return sorted({path for path in files if path.is_file()})


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_living(path: str) -> bool:
    parts = Path(path).parts
    return (
        "archive" not in parts
        and "knowledge" not in parts
        and not path.startswith("docs/audits/")
        and path not in {"CHANGELOG.md", "docs/RELEASE_LEDGER.md"}
    )


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _link_issues(root: Path, path: Path, text: str) -> list[Issue]:
    rel = _relative(root, path)
    if not _is_living(rel):
        return []
    issues: list[Issue] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        for raw_target in MARKDOWN_LINK_RE.findall(line):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith("#") or target.startswith(URL_SCHEMES):
                continue
            decoded = urllib.parse.unquote(target.split("#", 1)[0])
            if decoded and not (path.parent / decoded).exists():
                issues.append(Issue("broken-link", rel, number, raw_target))
    return issues


def _version_issues(root: Path) -> list[Issue]:
    issues: list[Issue] = []
    version_path = root / "config/version.json"
    if not version_path.is_file():
        return issues
    contract = json.loads(version_path.read_text(encoding="utf-8"))
    version = str(contract.get("product_version") or "")
    if not SEMVER_RE.fullmatch(version):
        issues.append(Issue("version", "config/version.json", 1, f"invalid product_version {version!r}"))
        return issues

    checks = {
        "pyproject.toml": re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE),
        "uv.lock": re.compile(
            r'\[\[package]]\s+name\s*=\s*"les-v2"\s+version\s*=\s*"([^"]+)"',
            re.MULTILINE,
        ),
        "docs/SOFTWARE_VERSIONS.md": re.compile(r"\| Версия продукта \| `([^`]+)`"),
        "README.md": re.compile(r"img\.shields\.io/badge/LES-([0-9.]+)-"),
    }
    for rel, pattern in checks.items():
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        match = pattern.search(text)
        actual = match.group(1) if match else "MISSING"
        if actual != version:
            line = _line_number(text, match.start()) if match else 1
            issues.append(Issue("version-drift", rel, line, f"{actual} != {version}"))
    return issues


def audit(root: Path) -> tuple[list[Issue], dict[str, int]]:
    root = root.resolve()
    issues: list[Issue] = []
    for rel in REQUIRED_FILES:
        if not (root / rel).is_file():
            issues.append(Issue("required-file", rel, 1, "missing"))

    files = documentation_files(root)
    algorithm_index = (root / "docs/ALGORITHM_INDEX.md").read_text(encoding="utf-8")
    skill_index = (root / "docs/SKILL_INDEX.md").read_text(encoding="utf-8")
    living_count = historical_count = algo_count = skill_count = 0
    for path in files:
        rel = _relative(root, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        living = _is_living(rel)
        living_count += int(living)
        historical_count += int(not living)
        algo_count += int(path.name.startswith("ALGO-") and path.parent.name == "docs")
        skill_count += int(path.name == "SKILL.md")

        if path.name.startswith("ALGO-") and path.parent.name == "docs" and path.name not in algorithm_index:
            issues.append(Issue("algorithm-index", rel, 1, "missing from docs/ALGORITHM_INDEX.md"))
        if path.name == "SKILL.md" and rel not in skill_index:
            issues.append(Issue("skill-index", rel, 1, "missing from docs/SKILL_INDEX.md"))

        if living and text.strip() and not re.search(r"^#\s+\S", text, re.MULTILINE):
            issues.append(Issue("missing-title", rel, 1, "living Markdown has no H1"))
        issues.extend(_link_issues(root, path, text))
        if living:
            for match in PUBLIC_CLONE_RE.finditer(text):
                issues.append(
                    Issue(
                        "private-clone",
                        rel,
                        _line_number(text, match.start()),
                        "current instructions must clone proovcme/les_rag_public",
                    )
                )

    issues.extend(_version_issues(root))
    stats = {
        "markdown_total": len(files),
        "living_markdown": living_count,
        "historical_or_generated_markdown": historical_count,
        "algorithm_docs": algo_count,
        "skills": skill_count,
    }
    return sorted(issues, key=lambda item: (item.path, item.line, item.code)), stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    issues, stats = audit(args.root)
    if args.json:
        print(
            json.dumps(
                {"ok": not issues, "stats": stats, "issues": [asdict(issue) for issue in issues]},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            "docs-contract: "
            f"{stats['markdown_total']} markdown, {stats['algorithm_docs']} algorithms, "
            f"{stats['skills']} skills"
        )
        for issue in issues:
            print(f"{issue.path}:{issue.line}: {issue.code}: {issue.detail}")
        print("docs-contract OK" if not issues else f"docs-contract FAIL: {len(issues)} issue(s)")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
