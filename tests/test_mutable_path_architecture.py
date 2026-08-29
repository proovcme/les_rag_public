from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (ROOT / "backend", ROOT / "proxy", ROOT / "sovushka")
MUTABLE_PREFIXES = ("data/", "storage/", "logs/", "artifacts/", "RAG_Content/")
ALLOWLIST_PREFIXES = ("proxy/smeta_core/",)
ALLOWLIST_READ_ONLY = {
    "backend/mail_ingest.py",
    "proxy/services/native_open_service.py",
}


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _violations() -> list[str]:
    violations: list[str] = []
    for scan_root in SCAN_ROOTS:
        for path in sorted(scan_root.rglob("*.py")):
            relative = _relative(path)
            if relative in ALLOWLIST_READ_ONLY or relative.startswith(ALLOWLIST_PREFIXES):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                if not isinstance(node.func, ast.Name) or node.func.id != "Path":
                    continue
                literal = node.args[0]
                if not isinstance(literal, ast.Constant) or not isinstance(literal.value, str):
                    continue
                normalized = literal.value.replace("\\", "/").lstrip("./")
                if normalized.startswith(MUTABLE_PREFIXES):
                    violations.append(f"{relative}:{node.lineno}:{literal.value}")
    return violations


def test_product_mutable_literals_use_runtime_path_boundary():
    violations = _violations()

    assert violations == [], "relative mutable paths bypass state ownership:\n" + "\n".join(
        violations
    )
