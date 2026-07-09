from proxy.services.les_module_service import module_spec
from proxy.services.skill_snippet_registry import select_skill_snippets


def test_specification_is_not_estimate_snippet_available():
    snippets = select_skill_snippets("smeta", user_input="Спецификация оборудования и материалов")
    text = "\n".join(s.text for s in snippets)
    assert "Спецификация не является сметой" in text
    assert "поставка отдельно" in text


def test_measurable_bor_gets_cost_attempt_snippet():
    snippets = select_skill_snippets("smeta", user_input="Дай оценку стоимости по ВОР")
    text = "\n".join(s.text for s in snippets)
    assert "попытку стоимости работ" in text
    assert "РИМ-сценарий" in text


def test_gesn_pricing_workflow_snippet_keeps_model_first_boundary():
    snippets = select_skill_snippets("smeta", user_input="Сделай ЛСР по ГЭСН и РИМ")
    text = "\n".join(s.text for s in snippets)
    assert "Сметчик сам выбирает" in text
    assert "код после этого только" in text
    assert "spb_2kv2026" in text
    assert "неполная база" in text


def test_norm_candidate_is_not_final_selection_in_tool_policy():
    spec = module_spec("smeta")
    assert "after the model decision" in spec.tool_policy
    assert "lookup" in spec.allowed_tools


def test_followup_add_gesn_uses_active_bor_snippet():
    snippets = select_skill_snippets("smeta", turn_type="active_continuation", user_input="добавь номера ГЭСН")
    text = "\n".join(s.text for s in snippets)
    assert "текущей ВОР" in text
    assert "Не начинай заново" in text
