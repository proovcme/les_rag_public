from proxy.services.skill_snippet_registry import (
    render_snippets,
    select_skill_snippets,
    snippet_registry_snapshot,
)


def test_skill_snippet_selected_by_mode():
    snippets = select_skill_snippets("smeta", user_input="Есть спецификация кабелей, сделай смету")
    ids = [s.snippet_id for s in snippets]
    assert "smeta.specification_to_bor" in ids
    assert "smeta.rim_scenario_estimate" in ids


def test_full_skill_not_injected_in_default_snippet():
    text = render_snippets(select_skill_snippets("smeta", user_input="смета", limit=2))
    assert len(text) < 1200
    assert "skills/smeta/SKILL.md" not in text
    assert "role-pack" not in text.lower()


def test_skill_snippet_registry_has_cross_module_entries():
    snap = snippet_registry_snapshot()
    assert "smeta.specification_to_bor" in snap
    assert "normcontrol.findings" in snap
    assert "bim_qto.quantities" in snap
    assert "contracts.risk_review" in snap
