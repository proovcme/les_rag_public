from __future__ import annotations

from pathlib import Path

from tools.documentation_contract import CANONICAL_PATHS, audit_documentation


ROOT = Path(__file__).resolve().parents[1]
CURRENT_RELEASE_DOCS = (
    ROOT / "SKILL.md",
    ROOT / "docs" / "RELEASE_PROCEDURE.md",
    ROOT / "docs" / "VERSIONING.md",
    ROOT / "docs" / "INSTALL_RUNBOOK.md",
    ROOT / "docs" / "GUARDRAILS.md",
)


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


def test_real_roadmap_has_product_contract_and_four_workstreams():
    text = (ROOT / "ROADMAP_TO_V1.md").read_text(encoding="utf-8")

    assert "помощник ГИП/РП" in text
    assert "## 1. RAG и evidence" in text
    assert "## 2. Работа ГИП/РП" in text
    assert "## 3. Агент" in text
    assert "## 4. Надёжность" in text
    assert "## v0.19" not in text


def test_active_root_has_no_superseded_narratives():
    forbidden = {"RAG_MODERNIZATION_PLAN.md", "LES_SIMPLE_OVERVIEW.md"}

    assert forbidden.isdisjoint(path.name for path in ROOT.glob("*.md"))


def test_archive_has_an_indexed_manual_review_queue():
    text = (ROOT / "docs/archive/README.md").read_text(encoding="utf-8")

    assert "Оставлены активными до ручного решения" in text


def test_current_docs_advertise_only_the_acceptance_orchestrator_for_public_release():
    for path in CURRENT_RELEASE_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "make patch-release PATCH_RELEASE_ARGS='--publish" not in text
        assert "make release-multiplatform MULTIPLATFORM_RELEASE_ARGS=" not in text
    procedure = (ROOT / "docs" / "RELEASE_PROCEDURE.md").read_text(encoding="utf-8")
    assert "make release RELEASE_ARGS=" in procedure
    assert "Legion" in procedure
    assert "rollback" in procedure


def test_locia_stability_policy_requires_user_path_and_atomic_updates():
    guardrails = (ROOT / "docs" / "GUARDRAILS.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for required in (
        "baseline → candidate → rollback",
        "одни и те же immutable bytes",
        "индекс/схема/конфиг",
        "автоматическая миграция",
        "installed user journey",
        "тесты не являются доказательством релиза",
    ):
        assert required in guardrails
    assert "baseline → candidate → rollback" in agents
    assert "не объявлять исправление готовым до installed user journey" in agents
