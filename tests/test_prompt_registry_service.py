import json
from pathlib import Path

from proxy.services.prompt_registry_service import (
    build_mode_system_prompt,
    build_smeta_batch_system_prompt,
    mode_tools,
    normcontrol_role_pack,
    prompt_registry_snapshot,
    rag_search_role_pack,
    reset_prompt_override,
    smeta_estimator_role_pack,
    smeta_native_skill_prompt,
    update_prompt_override,
)


def test_native_smeta_agent_loads_canonical_skill():
    skill = smeta_native_skill_prompt()

    assert "# Сметный агент ЛЕС" in skill
    assert "единственным профессиональным контрактом" in skill
    assert "technology_check" in skill
    assert "unbound_evidence" in skill
    assert "runtime-agent.md" not in skill


def test_prompt_registry_exposes_common_tone_modes_and_tools():
    snap = prompt_registry_snapshot()

    assert snap["schema"] == "prompt_registry_v2"
    assert "модель связывает" in snap["common"].lower()
    assert "skills/smeta/SKILL.md" in snap["common"]
    assert "ирони" in snap["tone"].lower()
    assert "smeta" in snap["modes"]
    assert "price_gap_summary" in snap["modes"]["smeta"]["tools"]
    assert "retrieval" in snap["modes"]["rag"]["tools"]
    assert snap["role_packs"]["smeta_harness"]["id"] == "smeta_agent_v2"
    assert snap["role_packs"]["smeta_harness"]["planning_output_contract"]["schema"] == "smeta_mapping_plan_v1"
    assert snap["role_packs"]["smeta_harness"]["execution_result_contract"]["schema"] == "smeta_execution_result_v1"
    assert snap["role_packs"]["rag_search"]["id"] == "rag_search_researcher_v1"
    assert snap["role_packs"]["normcontrol"]["id"] == "normcontrol_reviewer_v1"


def test_mode_system_prompt_includes_mode_tone_without_tool_contracts():
    prompt = build_mode_system_prompt("rag")

    assert "evidence" in prompt.lower()
    assert "бардак" in prompt.lower()
    assert "Доступные инструменты режима" not in prompt
    assert "Не показывай наружу" in prompt


def test_local_normative_style_keeps_voice_without_balagaan():
    prompt = build_mode_system_prompt("rag")

    assert "бардак" in prompt.lower()
    assert "короткие едкие реплики" in prompt
    assert "ЛСР/КС/таблицы пиши сухо" in prompt


def test_prompt_overrides_change_effective_prompts(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "proxy.services.prompt_registry_service._PROMPT_OVERRIDES_PATH",
        tmp_path / "prompt_overrides.json",
    )

    update_prompt_override("tone", "Говори живо, но считай строго.")
    update_prompt_override("modes.rag", "Режим RAG: сначала думай, потом ищи.")
    snap = prompt_registry_snapshot()

    assert snap["tone"] == "Говори живо, но считай строго."
    assert snap["modes"]["rag"]["prompt"] == "Режим RAG: сначала думай, потом ищи."
    assert any(item["key"] == "tone" and item["overridden"] for item in snap["editable"])
    prompt = build_mode_system_prompt("rag")
    assert "Говори живо, но считай строго." in prompt
    assert "Режим RAG: сначала думай, потом ищи." in prompt

    reset_prompt_override("tone")
    snap = prompt_registry_snapshot()
    assert snap["tone"] != "Говори живо, но считай строго."
    assert any(item["key"] == "tone" and not item["overridden"] for item in snap["editable"])


def test_smeta_prompt_keeps_only_native_agent_boundary():
    prompt = build_smeta_batch_system_prompt("Верни JSON.")
    low = prompt.lower()

    assert not prompt.startswith("/no_think")
    assert "Контракт сметного агента" in prompt
    assert "smeta_agent_v2" in prompt
    assert "smeta_mapping_plan_v1" in prompt
    assert "smeta_execution_result_v1" in prompt
    assert '"user_modes":["estimate","candidate_review","continue_reviewed"]' in prompt
    assert '"candidate_relationship_types":["alternative","complementary","partial_coverage","covered_by"]' in prompt
    assert '"applicability_statuses":["exact","close_analog","weak_analog","not_applicable"]' in prompt
    assert '"candidate_decisions":["triaged","opened","selected","rejected","conflict"]' in prompt
    assert "candidate_combinations_are_model_reasoned_not_cartesian_products" in prompt
    assert '"mapping_statuses":["candidates_ready","mapping_selected","mapping_user_reviewed","mapping_locked"]' in prompt
    assert '"pricing_statuses":["unpriced","priced_partial","priced_draft","priced_final"]' in prompt
    assert '"pricing_basis":["norm","analog_norm","commercial_offer","calculation"]' in prompt
    assert '"resolution_statuses":["priced","covered_by","partially_resolved","unresolved","excluded"]' in prompt
    assert '"priced_draft"' in prompt
    assert '"tool_contract_schema":"schema/smeta_agent_trace.schema.json"' in prompt
    assert '"applicability_checks"' not in prompt
    assert '"trace_required"' not in prompt
    assert '"coefficient_trace_required"' not in prompt
    assert '"result_statuses"' not in prompt
    assert "norm_search_must_walk" not in prompt
    assert "candidate_norm_table_before" not in prompt
    assert "two_estimates_require" not in prompt
    assert "comparison_table_columns" not in prompt
    assert "required_answer_capabilities" not in prompt
    assert "hard_rules" not in prompt
    assert "les_local_smeta_sources" not in prompt
    assert "data/gesn_base/gesn2022.parquet" not in prompt
    assert "control_cases_policy" not in prompt
    assert "minimal_example" not in prompt
    assert '"example"' not in prompt
    assert len(prompt) < 7000
    assert "object_templates" not in prompt
    assert "шаблон" not in low


def test_smeta_estimator_role_pack_is_minimal_tool_contract():
    pack = smeta_estimator_role_pack()

    assert pack["schema"] == "les.prompt.role_pack.v1"
    assert pack["id"] == "smeta_agent_v2"
    assert pack["planning_output_contract"]["schema"] == "smeta_mapping_plan_v1"
    assert pack["execution_result_contract"]["schema"] == "smeta_execution_result_v1"
    assert pack["pricing_statuses"] == ["unpriced", "priced_partial", "priced_draft", "priced_final"]
    assert "result_statuses" not in pack
    assert pack["user_modes"] == ["estimate", "candidate_review", "continue_reviewed"]
    assert pack["mapping_statuses"] == ["candidates_ready", "mapping_selected", "mapping_user_reviewed", "mapping_locked"]
    assert pack["candidate_relationship_types"] == [
        "alternative",
        "complementary",
        "partial_coverage",
        "covered_by",
    ]
    assert pack["applicability_statuses"] == ["exact", "close_analog", "weak_analog", "not_applicable"]
    assert pack["candidate_decisions"] == ["triaged", "opened", "selected", "rejected", "conflict"]
    assert pack["pricing_basis"] == [
        "norm", "analog_norm", "commercial_offer", "calculation",
    ]
    assert pack["resolution_statuses"] == ["priced", "covered_by", "partially_resolved", "unresolved", "excluded"]
    assert pack["context_policy"]["working_context"] == "one_operation_or_small_related_group"
    assert pack["review_policy"]["all_candidates"] == "triage"
    assert "cumulative_cost_majority" in pack["review_policy"]["full_review_triggers"]
    assert "rejection_changes_coverage_or_cost" in pack["review_policy"]["full_review_triggers"]
    assert pack["tool_contract_schema"] == "schema/smeta_agent_trace.schema.json"
    assert pack["execution_result_contract"]["optional_for_modes"] == ["candidate_review"]
    assert "mapping_status_and_pricing_status_are_independent" in pack["invariants"]
    assert "relationship_applicability_decision_basis_and_resolution_are_separate" in pack["invariants"]
    assert "candidate_combinations_are_model_reasoned_not_cartesian_products" in pack["invariants"]
    assert "continue_reviewed_requires_mapping_locked" in pack["invariants"]
    assert "missing_price_is_null_not_zero" in pack["invariants"]
    assert "inferred_quantity_blocks_priced_final" in pack["invariants"]
    assert "case_specific_steering_is_forbidden" in pack["invariants"]
    assert "required_answer_capabilities" not in pack
    assert "answer_sections" not in pack
    assert "hard_rules" not in pack
    assert "chain_modes" not in pack
    assert "norm_search_route" not in pack
    assert "comparison_table_columns" not in pack
    assert "control_cases_policy" not in pack
    assert "regression_cases" not in pack
    assert "output_contract" not in pack


def test_smeta_role_pack_file_is_valid_json_and_has_no_case_anchors():
    text = Path("config/prompts/smeta_estimator_role.json").read_text(encoding="utf-8")
    skill = Path("skills/smeta/SKILL.md").read_text(encoding="utf-8")
    json.loads(text)

    for marker in ("БАП", "столп", "пьедестал", "башенный кран", "Liebherr"):
        assert marker.casefold() not in text.casefold()
        assert marker.casefold() not in skill.casefold()

    assert "Декартово произведение кандидатов запрещено" in skill
    assert "source_row → technological_operation → estimate_position → resolution_status → pricing_basis → pricing_evidence" in skill
    assert "после завершения моделью mapping он один раз считает и формирует XLSX" in skill
    assert "Отдельного обязательного resource-review, impact-review или повторного допуска нет" in skill
    assert "machinist_labor_per_machine_hour" in skill
    assert "коэффициенты `0.9` к нр и `0.85` к сп" in skill.casefold()
    assert "исключения пункта 26 №812/пр" in skill
    assert "Вместе агент возвращает четыре связанных результата" in skill
    assert "Missing price хранится только как `null`/пусто" in skill
    assert "`missing_evidence→variant_only`" in skill


def test_mode_tools_unknown_is_empty():
    assert mode_tools("unknown") == []


def test_rag_search_role_pack_is_model_first_contract():
    pack = rag_search_role_pack()

    assert pack["schema"] == "les.prompt.role_pack.v1"
    assert pack["mode"] == "rag"
    assert "active_dataset" in pack["search_scopes"]
    assert "target_file" in pack["search_scopes"]
    assert "answer_with_sources" in pack["required_answer_capabilities"]
    assert pack["hard_rules"]["model_links_sources"] is True
    assert pack["hard_rules"]["code_only_retrieves_reranks_filters_and_calculates"] is True
    assert pack["hard_rules"]["target_file_scope_is_strict"] is True


def test_normcontrol_role_pack_is_model_first_contract():
    pack = normcontrol_role_pack()

    assert pack["schema"] == "les.prompt.role_pack.v1"
    assert pack["mode"] == "normcontrol"
    assert "remark" in pack["review_statuses"]
    assert "rule_or_source" in pack["remark_fields"]
    assert "normalized_remarks" in pack["required_answer_capabilities"]
    assert pack["hard_rules"]["model_formulates_engineering_remarks"] is True
    assert pack["hard_rules"]["computed_checks_are_separate_from_rag_review"] is True
