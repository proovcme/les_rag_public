from __future__ import annotations

from pathlib import Path

from tools.documentation_contract import CANONICAL_PATHS, audit_documentation


ROOT = Path(__file__).resolve().parents[1]


def _write_complete_canonical_fixture(root: Path) -> None:
    for relative in (*CANONICAL_PATHS, "README.md", "docs/index.md", "docs/archive/README.md"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")


def test_documentation_contract_accepts_existing_canonical_chain(tmp_path):
    _write_complete_canonical_fixture(tmp_path)

    assert audit_documentation(tmp_path) == []


def test_documentation_contract_reports_missing_local_target(tmp_path):
    _write_complete_canonical_fixture(tmp_path)
    (tmp_path / "AGENTS.md").write_text(
        "[broken](docs/missing.md)\n", encoding="utf-8"
    )

    assert audit_documentation(tmp_path) == ["AGENTS.md -> docs/missing.md: missing"]


def test_documentation_contract_rejects_talmud_roadmap(tmp_path):
    _write_complete_canonical_fixture(tmp_path)
    (tmp_path / "ROADMAP_TO_V1.md").write_text(
        "\n".join(["line"] * 301), encoding="utf-8"
    )

    assert "ROADMAP_TO_V1.md: exceeds 300 lines" in audit_documentation(tmp_path)


def test_documentation_contract_ignores_external_anchors_and_code_fences(tmp_path):
    _write_complete_canonical_fixture(tmp_path)
    (tmp_path / "AGENTS.md").write_text(
        "[web](https://example.com) [mail](mailto:test@example.com) [section](#section)\n"
        "```markdown\n[historical](missing.md)\n```\n",
        encoding="utf-8",
    )

    assert audit_documentation(tmp_path) == []

