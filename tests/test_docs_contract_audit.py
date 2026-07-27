from pathlib import Path

from tools.docs_contract_audit import _link_issues, audit


ROOT = Path(__file__).resolve().parents[1]


def test_repository_documentation_contract_is_clean():
    issues, stats = audit(ROOT)

    assert issues == []
    assert stats["algorithm_docs"] >= 27
    assert stats["skills"] >= 4


def test_link_audit_ignores_code_fences_and_finds_living_broken_link(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text(
        "# Guide\n\n[missing](missing.md)\n\n```md\n[example](also-missing.md)\n```\n",
        encoding="utf-8",
    )

    issues = _link_issues(tmp_path, path, path.read_text(encoding="utf-8"))

    assert [(issue.code, issue.line, issue.detail) for issue in issues] == [
        ("broken-link", 3, "missing.md")
    ]
