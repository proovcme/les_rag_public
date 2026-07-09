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
    update_prompt_override,
)


def test_prompt_registry_exposes_common_tone_modes_and_tools():
    snap = prompt_registry_snapshot()

    assert snap["schema"] == "prompt_registry_v2"
    assert "модель связывает" in snap["common"].lower()
    assert "skills/smeta/SKILL.md" in snap["common"]
    assert "ирони" in snap["tone"].lower()
    assert "бардак" in snap["tone"].lower()
    assert "оператору — уважение" in snap["tone"].lower()
    assert "пластикового техподдержечного голоса" in snap["tone"].lower()
    assert "smeta" in snap["modes"]
    assert "price_gap_summary" in snap["modes"]["smeta"]["tools"]
    assert "retrieval" in snap["modes"]["rag"]["tools"]
    assert snap["role_packs"]["smeta_harness"]["id"] == "experienced_estimator_v1"
    assert snap["role_packs"]["smeta_harness"]["output_contract"]["schema"] == "smeta_work_plan_v1"
    assert snap["role_packs"]["rag_search"]["id"] == "rag_search_researcher_v1"
    assert snap["role_packs"]["normcontrol"]["id"] == "normcontrol_reviewer_v1"


def test_mode_system_prompt_includes_mode_tone_without_tool_contracts():
    prompt = build_mode_system_prompt("rag")

    assert "evidence" in prompt.lower()
    assert "бардак" in prompt.lower()
    assert "короткие едкие реплики" in prompt
    assert "Официальные письма" in prompt
    assert "Доступные инструменты режима" not in prompt
    assert "Не показывай наружу" in prompt


def test_local_normative_style_keeps_voice_without_balagaan():
    source = Path("proxy/routers/chat.py").read_text(encoding="utf-8")

    assert "без балагана" in source.lower()
    assert "короткая живая реплика допустима" in source
    assert "без шуток и постскриптумов" not in source


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
    assert "code_does_not_select_norms" in prompt
    assert "code_arithmetic_only_after_visible_model_choice" in prompt
    assert "model_selects_normative_route" in prompt
    assert "no_global_stop_cranes_for_incomplete_estimates" in prompt
    assert "partial_estimate_keeps_calculated_rows" in prompt
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
    assert "les_local_smeta_sources" not in prompt
    assert "data/gesn_base/gesn2022.parquet" not in prompt
    assert "data/price_base/*.parquet" not in prompt
    assert "model_gesn_skill_prompt" not in prompt
    assert "Ценообразование строки" not in prompt
    assert "comparison_table_columns" in prompt
    assert "Раздел работ" in prompt
    assert "Рыночная сумма с НДС" in prompt
    assert "split_form_policy" not in prompt
    assert "144*20%*10=288" not in prompt
    assert "control_cases_policy" not in prompt
    assert "minimal_example" not in prompt
    assert '"example"' not in prompt
    assert len(prompt) < 12000
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
    assert pack["hard_rules"]["missing_price_is_row_zero_placeholder"] is True
    assert "priced_final" in pack["result_statuses"]
    assert "rim_scenario_estimate" in pack["result_statuses"]
    assert "market_scenario_estimate" in pack["result_statuses"]
    assert "scenario_estimate" in pack["result_statuses"]
    assert "numeric_audit" in pack["required_answer_capabilities"]
    assert "quantity_conflict_form" in pack["required_answer_capabilities"]
    assert "quantity_trace" in pack["required_answer_capabilities"]
    assert "normable_bor" in pack["required_answer_capabilities"]
    assert "norm_candidate_table" in pack["required_answer_capabilities"]
    assert "norm_search_route" in pack["required_answer_capabilities"]
    assert "many_to_one_norm_mapping" in pack["required_answer_capabilities"]
    assert "artifact_ready_tables" in pack["required_answer_capabilities"]
    assert "bor_markdown_table" in pack["required_answer_capabilities"]
    assert "work_cost_markdown_table" in pack["required_answer_capabilities"]
    assert "norm_or_source_per_cost_row" in pack["required_answer_capabilities"]
    assert "rim_scenario_estimate" in pack["required_answer_capabilities"]
    assert "rim_lsr_form_order" in pack["required_answer_capabilities"]
    assert "normative_analogue_basis" in pack["required_answer_capabilities"]
    assert "tolerance_basis" in pack["required_answer_capabilities"]
    assert "excel_roundtrip_review" in pack["required_answer_capabilities"]
    assert "method_comparison_table" in pack["required_answer_capabilities"]
    assert "source_reading_inventory" in pack["required_answer_capabilities"]
    assert "coefficient_kac_roundtrip" in pack["required_answer_capabilities"]
    assert "resource_gap_register" in pack["required_answer_capabilities"]
    assert "estimate_quality_mode" in pack["required_answer_capabilities"]
    assert pack["supported_norm_families"] == ["ГЭСН", "ГЭСНм", "ГЭСНп", "ГЭСНр", "ГЭСНмр"]
    assert pack["estimate_quality_modes"] == ["rough_cost", "stage_p", "stage_rd"]
    assert pack["norm_search_route"] == [
        "work_family",
        "collection_group",
        "collection",
        "collection_section_or_table",
        "specific_norm",
    ]
    assert "specification_to_bor" in pack["chain_modes"]
    assert "live_estimator_workflow" in pack["chain_modes"]
    assert "bor_to_norm_candidate_table" in pack["chain_modes"]
    live_workflow = pack["chain_modes"]["live_estimator_workflow"]
    assert live_workflow["states"] == [
        "SOURCE_READING",
        "BOR_DRAFT",
        "NORM_CANDIDATE_TABLE",
        "USER_VARIANT_SELECTION",
        "RESOURCE_EXPANSION",
        "FIRST_LSR_DRAFT",
        "COEFFICIENT_AND_KAC_PASS",
        "PRICED_FINAL",
    ]
    assert live_workflow["hard_rules"]["read_attached_sources_before_total"] is True
    assert live_workflow["hard_rules"]["many_bor_rows_can_share_one_candidate_norm"] is True
    assert live_workflow["hard_rules"]["candidate_table_is_excel_filterable"] is True
    assert live_workflow["hard_rules"]["zero_placeholder_is_not_fact_price"] is True
    assert live_workflow["hard_rules"]["resource_gap_register_is_separate_from_normative_gaps"] is True
    assert live_workflow["hard_rules"]["priced_final_requires_closed_norm_resource_price_coefficient_region_period_trace"] is True
    assert pack["chain_modes"]["specification_to_bor"]["hard_rules"]["build_bor_before_norm_selection"] is True
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["hard_rules"]["one_source_work_can_split_to_many_norms"] is True
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["hard_rules"]["many_source_works_can_share_one_norm"] is True
    assert "many_bor_to_one_norm" in pack["chain_modes"]["bor_to_norm_candidate_table"]["mapping_cardinalities"]
    assert "source_row_ids" in pack["chain_modes"]["bor_to_norm_candidate_table"]["required_fields"]
    assert "mapping_cardinality" in pack["chain_modes"]["bor_to_norm_candidate_table"]["required_fields"]
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["hard_rules"]["candidate_norm_is_not_final_selection"] is True
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["hard_rules"]["norm_search_route_is_family_group_collection_section_norm"] is True
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["hard_rules"]["all_norm_families_must_be_considered_when_relevant"] is True
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["hard_rules"]["stable_vor_row_id_survives_renumbering"] is True
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["hard_rules"]["new_or_changed_rows_get_new_candidates_only"] is True
    assert pack["chain_modes"]["bor_to_norm_candidate_table"]["excel_roundtrip_policy"]["rules"]["calculation_uses_selected_variant"] is True
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
    assert pack["hard_rules"]["many_bor_lines_may_map_to_one_norm"] is True
    assert pack["hard_rules"]["norm_search_must_walk_family_group_collection_section_norm"] is True
    assert pack["hard_rules"]["norm_families_include_gesn_gesnm_gesnp_gesnr_gesnmr"] is True
    assert pack["hard_rules"]["candidate_norm_table_before_confirmed_rim"] is True
    assert pack["hard_rules"]["read_all_user_sources_before_estimating"] is True
    assert pack["hard_rules"]["zero_placeholders_require_notes"] is True
    assert pack["hard_rules"]["resource_gap_register_is_for_priced_resources_not_unrecognized_work"] is True
    assert pack["hard_rules"]["estimate_quality_mode_must_be_explicit"] is True
    assert pack["hard_rules"]["coefficients_and_kac_roundtrip_before_priced_final"] is True
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
    assert pack["hard_rules"]["generic_norm_family_is_not_enough_source"] is True
    assert pack["hard_rules"]["code_does_not_select_works"] is True
    assert pack["hard_rules"]["code_does_not_select_norms"] is True
    assert pack["hard_rules"]["code_does_not_build_norm_shortlist_as_decision"] is True
    assert pack["hard_rules"]["code_arithmetic_only_after_visible_model_choice"] is True
    assert pack["hard_rules"]["model_selects_normative_route"] is True
    assert pack["hard_rules"]["no_global_stop_cranes_for_incomplete_estimates"] is True
    assert pack["hard_rules"]["partial_estimate_keeps_calculated_rows"] is True
    assert pack["hard_rules"]["missing_data_stays_in_lsr_row_as_zero_or_blank"] is True
    assert pack["hard_rules"]["case_specific_constants_forbidden"] is True
    assert pack["les_local_smeta_sources"]["norms_primary"] == [
        "data/gesn_base/gesn2022.parquet",
        "data/gesn_base/gesn2022_v2.parquet",
    ]
    assert pack["les_local_smeta_sources"]["norm_index"]["service"] == "smeta_norm_store_v5"
    assert pack["les_local_smeta_sources"]["norm_index"]["count"] == 42572
    assert "data/price_base/*.parquet" in pack["les_local_smeta_sources"]["pricebooks"]
    assert any("Ценообразование строки" in item for item in pack["model_gesn_skill_prompt"])
    assert any("Код не выбирает нормы" in item for item in pack["model_gesn_skill_prompt"])
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
    assert "rim_lsr_form" in pack["chain_modes"]
    rim_lsr = pack["chain_modes"]["rim_lsr_form"]
    assert "direct_total" in rim_lsr["row_types_order"]
    assert "machinist_resource" in rim_lsr["row_types_order"]
    assert "kac_or_missing_resource" in rim_lsr["row_types_order"]
    assert rim_lsr["hard_rules"]["labor_workers_are_not_machinists"] is True
    assert rim_lsr["hard_rules"]["machine_cost_excludes_machinist_labor"] is True
    assert rim_lsr["hard_rules"]["material_missing_price_goes_to_kac_or_missing_not_zero_fact"] is True
    assert rim_lsr["hard_rules"]["position_total_equals_direct_total_plus_nr_plus_sp"] is True
    assert not any("144*20%*10=288" in str(item) for item in pack.values())


def test_mode_tools_unknown_is_empty():
    assert mode_tools("unknown") == []


def test_rag_search_role_pack_is_model_first_contract():
    pack = rag_search_role_pack()

    assert pack["schema"] == "les.prompt.role_pack.v1"
    assert pack["mode"] == "rag"
    assert "active_dataset" in pack["search_scopes"]
    assert "target_file" in pack["search_scopes"]
    assert "confirmed_by_source" in pack["evidence_statuses"]
    assert "source_conflict" in pack["evidence_statuses"]
    assert "missing_evidence" in pack["evidence_statuses"]
    assert "source_table" in pack["required_answer_capabilities"]
    assert "answer_with_sources" in pack["required_answer_capabilities"]
    assert "normative_route" in pack["required_answer_capabilities"]
    assert "clause_level_answer" in pack["required_answer_capabilities"]
    assert "two_sided_norm_table" in pack["required_answer_capabilities"]
    assert pack["hard_rules"]["model_links_sources"] is True
    assert pack["hard_rules"]["code_only_retrieves_reranks_filters_and_calculates"] is True
    assert pack["hard_rules"]["normative_answer_requires_norm_then_clause"] is True
    assert pack["hard_rules"]["two_sided_norm_question_requires_both_sides"] is True
    assert pack["hard_rules"]["target_file_scope_is_strict"] is True
    assert pack["hard_rules"]["missing_evidence_is_not_negative_fact"] is True
    assert pack["hard_rules"]["table_numbers_require_deterministic_path"] is True
    assert pack["hard_rules"]["do_not_show_internal_json_unless_requested"] is True
    assert pack["hard_rules"]["do_not_expose_raw_rag_terms"] is True


def test_normcontrol_role_pack_is_model_first_contract():
    pack = normcontrol_role_pack()

    assert pack["schema"] == "les.prompt.role_pack.v1"
    assert pack["mode"] == "normcontrol"
    assert "pass" in pack["review_statuses"]
    assert "remark" in pack["review_statuses"]
    assert "needs_more_evidence" in pack["review_statuses"]
    assert "rule_or_source" in pack["remark_fields"]
    assert "normalized_remarks" in pack["required_answer_capabilities"]
    assert "computed_checks" in pack["required_answer_capabilities"]
    assert "rag_review_findings" in pack["required_answer_capabilities"]
    assert pack["hard_rules"]["model_formulates_engineering_remarks"] is True
    assert pack["hard_rules"]["computed_checks_are_separate_from_rag_review"] is True
    assert pack["hard_rules"]["defense_contract_required"] is True
    assert pack["hard_rules"]["missing_evidence_is_unknown_not_pass"] is True
    assert pack["hard_rules"]["missing_evidence_is_unknown_not_fail"] is True
    assert pack["hard_rules"]["no_final_legal_verdict_without_complete_scope"] is True
    assert pack["hard_rules"]["remark_requires_rule_or_source"] is True
