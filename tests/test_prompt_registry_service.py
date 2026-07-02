import json

from proxy.services.prompt_registry_service import (
    build_mode_system_prompt,
    build_smeta_batch_system_prompt,
    mode_tools,
    prompt_registry_snapshot,
    reset_prompt_override,
    smeta_estimator_role_pack,
    update_prompt_override,
)


def test_prompt_registry_exposes_common_tone_modes_and_tools():
    snap = prompt_registry_snapshot()

    assert snap["schema"] == "prompt_registry_v2"
    assert "модель связывает" in snap["common"].lower()
    assert "ирони" in snap["tone"].lower()
    assert "smeta" in snap["modes"]
    assert "price_gap_summary" in snap["modes"]["smeta"]["tools"]
    assert "retrieval" in snap["modes"]["rag"]["tools"]
    assert snap["role_packs"]["smeta_harness"]["id"] == "experienced_estimator_v1"
    assert snap["role_packs"]["smeta_harness"]["output_contract"]["schema"] == "smeta_work_plan_v1"


def test_mode_system_prompt_includes_mode_tone_without_tool_contracts():
    prompt = build_mode_system_prompt("rag")

    assert "evidence" in prompt.lower()
    assert "бардак" in prompt.lower()
    assert "Доступные инструменты режима" not in prompt
    assert "Не показывай наружу" in prompt


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


def test_smeta_prompt_is_model_first_and_has_no_object_templates():
    prompt = build_smeta_batch_system_prompt("Верни JSON.")
    low = prompt.lower()

    assert "code_does_not_select_works" in prompt
    assert "model_selects_normative_route" in prompt
    assert "Компактный машинный контракт сметчика" in prompt
    assert "experienced_estimator_v1" in prompt
    assert "smeta_work_plan_v1" in prompt
    assert "price_source_types" in prompt
    assert "required_answer_capabilities" in prompt
    assert "answer_sections" in prompt
    assert "hard_rules" in prompt
    assert "specification_to_bor" in prompt
    assert "bor_to_norm_candidate_table" in prompt
    assert "norm_candidate_table" in prompt
    assert "rim_scenario_estimate" in prompt
    assert "rim_requested_requires_rim_based_estimate" in prompt
    assert "generic_cost_estimate_defaults_to_rim_when_normative_data_available" in prompt
    assert "wide_market_range_is_not_rim_estimate" in prompt
    assert "one_bor_line_may_split_to_many_norms" in prompt
    assert "candidate_norm_table_before_confirmed_rim" in prompt
    assert "draft_zero_is_not_price" in prompt
    assert "long_sums_require_calculator_or_trace" in prompt
    assert "quantity_conflict_blocks_priced_final" in prompt
    assert "measurable_bor_requires_cost_attempt" in prompt
    assert "two_estimates_require_comparison_table" in prompt
    assert "case_specific_constants_forbidden" in prompt
    assert "comparison_table_columns" in prompt
    assert "Раздел работ" in prompt
    assert "Рыночная сумма с НДС" in prompt
    assert "split_form_policy" not in prompt
    assert "144*20%*10=288" not in prompt
    assert "control_cases_policy" not in prompt
    assert "minimal_example" not in prompt
    assert '"example"' not in prompt
    assert len(prompt) < 9000
    assert "object_templates" not in prompt
    assert "шаблон" not in low


def test_smeta_estimator_role_pack_is_json_contract():
    pack = smeta_estimator_role_pack()

    assert pack["schema"] == "les.prompt.role_pack.v1"
    assert pack["id"] == "experienced_estimator_v1"
    assert pack["output_contract"]["response_format"] == "json_object"
    assert "works" in pack["output_contract"]["top_level_required"]
    assert "mass_t" in pack["direct_quantity_policy"]["slots"]
    assert "calculation_trace" in pack["price_source_types"]
    assert pack["hard_rules"]["missing_price_is_not_zero"] is True
    assert "priced_final" in pack["result_statuses"]
    assert "rim_scenario_estimate" in pack["result_statuses"]
    assert "market_scenario_estimate" in pack["result_statuses"]
    assert "scenario_estimate" in pack["result_statuses"]
    assert "numeric_audit" in pack["required_answer_capabilities"]
    assert "quantity_conflict_form" in pack["required_answer_capabilities"]
    assert "quantity_trace" in pack["required_answer_capabilities"]
    assert "normable_bor" in pack["required_answer_capabilities"]
    assert "norm_candidate_table" in pack["required_answer_capabilities"]
    assert "artifact_ready_tables" in pack["required_answer_capabilities"]
    assert "bor_markdown_table" in pack["required_answer_capabilities"]
    assert "work_cost_markdown_table" in pack["required_answer_capabilities"]
    assert "norm_or_source_per_cost_row" in pack["required_answer_capabilities"]
    assert "rim_scenario_estimate" in pack["required_answer_capabilities"]
    assert "normative_analogue_basis" in pack["required_answer_capabilities"]
    assert "tolerance_basis" in pack["required_answer_capabilities"]
    assert "excel_roundtrip_review" in pack["required_answer_capabilities"]
    assert "method_comparison_table" in pack["required_answer_capabilities"]
    assert "specification_to_bor" in pack["chain_modes"]
    assert "bor_to_norm_candidate_table" in pack["chain_modes"]
    assert pack["chain_modes"]["specification_to_bor"]["hard_rules"]["build_bor_before_norm_selection"] is True
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["hard_rules"]["one_source_work_can_split_to_many_norms"] is True
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["hard_rules"]["candidate_norm_is_not_final_selection"] is True
    assert "confirmed_by_user" in pack["chain_modes"]["bor_to_norm_candidate_table"]["applicability_statuses"]
    assert "missing_quantity" in pack["chain_modes"]["specification_to_bor"]["trace_statuses"]
    assert "understood" in pack["answer_sections"]
    assert "numeric_audit" in pack["answer_sections"]
    assert pack["hard_rules"]["quantity_conflict_blocks_priced_final"] is True
    assert pack["hard_rules"]["long_sums_require_calculator_or_trace"] is True
    assert pack["hard_rules"]["measurable_bor_requires_cost_attempt"] is True
    assert pack["hard_rules"]["two_estimates_require_comparison_table"] is True
    assert pack["hard_rules"]["bor_to_normable_bor_before_norm_selection"] is True
    assert pack["hard_rules"]["one_bor_line_may_split_to_many_norms"] is True
    assert pack["hard_rules"]["candidate_norm_table_before_confirmed_rim"] is True
    assert pack["hard_rules"]["rim_requested_requires_rim_based_estimate"] is True
    assert pack["hard_rules"]["generic_cost_estimate_defaults_to_rim_when_normative_data_available"] is True
    assert pack["hard_rules"]["rim_scenario_uses_normative_analogs"] is True
    assert pack["hard_rules"]["wide_market_range_is_not_rim_estimate"] is True
    assert pack["hard_rules"]["draft_zero_is_not_price"] is True
    assert pack["hard_rules"]["check_les_sources_before_asking_user"] is True
    assert pack["hard_rules"]["do_not_deny_available_les_sources"] is True
    assert pack["hard_rules"]["empty_price_columns_do_not_block_work_cost"] is True
    assert pack["hard_rules"]["long_tables_can_be_artifact_payload"] is True
    assert pack["hard_rules"]["direct_bor_request_requires_markdown_table"] is True
    assert pack["hard_rules"]["direct_work_cost_request_requires_markdown_table"] is True
    assert pack["hard_rules"]["do_not_expose_task_classification"] is True
    assert pack["hard_rules"]["work_cost_rows_require_norm_or_source"] is True
    assert pack["hard_rules"]["scenario_rate_must_be_labeled"] is True
    assert pack["hard_rules"]["code_does_not_select_works"] is True
    assert pack["hard_rules"]["model_selects_normative_route"] is True
    assert pack["hard_rules"]["case_specific_constants_forbidden"] is True
    assert "comparison_table_columns" in pack
    assert "quantity_conflict_form_columns" in pack
    assert "norm_candidate_table_columns" in pack
    assert "rim_scenario_table_columns" in pack
    assert "split_form_policy" not in pack
    assert "control_cases_policy" not in pack
    assert "regression_cases" not in pack
    assert "minimal_example" not in pack["output_contract"]
    assert "Раздел работ" in pack["comparison_table_columns"]
    assert "Статус для расчёта" in pack["quantity_conflict_form_columns"]
    assert "Код ГЭСН" in pack["norm_candidate_table_columns"]
    assert "Статус применимости" in pack["norm_candidate_table_columns"]
    assert "Нормативный ход / аналог" in pack["rim_scenario_table_columns"]
    assert "Допуск" in pack["rim_scenario_table_columns"]
    assert "rim_scenario_estimate" in pack["chain_modes"]
    assert pack["chain_modes"]["rim_scenario_estimate"]["hard_rules"]["rim_request_cannot_be_answered_by_market_range_only"] is True
    assert not any("144*20%*10=288" in str(item) for item in pack.values())


def test_mode_tools_unknown_is_empty():
    assert mode_tools("unknown") == []
