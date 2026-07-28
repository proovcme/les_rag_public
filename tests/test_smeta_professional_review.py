import json
from pathlib import Path
import pytest
import asyncio
from types import SimpleNamespace

from proxy.smeta_core.professional_review import (
    EvidenceBudget,
    MappingRevision,
    ModelScopePlan,
    create_user_lock_revision,
    detect_professional_conflicts,
    load_mapping_revision,
    mapping_quality_metrics,
    save_mapping_revision,
)


def test_conflict_validator_flags_contradictions_without_changing_selection():
    rows = [
        {"work_id": "w1", "title": "Демонтаж светильника"},
        {"work_id": "w2", "title": "Пусконаладка шкафа"},
    ]
    selections = {
        "w1": {
            "norm_code": "ГЭСНм08-01-001-01",
            "selection_kind": "exact",
            "applicability": "close_analog",
            "analog_limitations": ["требуется проверка"],
            "technology_check": {
                "missing_operations": ["демонтаж"],
                "unresolved_conditions": [],
                "conclusion": "applicable_with_limitations",
            },
            "resource_bindings": [
                {"action": "replace", "target_resource_code": "01.1"},
                {"action": "exclude", "target_resource_code": "01.1"},
            ],
            "k_ozp": 1.15,
        },
        "w2": {"covered_by_work_id": "missing", "reason": "комплекс"},
    }
    snapshot = json.loads(json.dumps(selections, ensure_ascii=False))

    conflicts = detect_professional_conflicts(
        rows,
        selections,
        opened_cards={
            "w1": [{
                "norm_code": "ГЭСНм08-01-001-01",
                "title": "Установка светильника",
                "work_steps": ["Монтаж и крепление светильника"],
            }],
        },
    )

    assert selections == snapshot
    assert {item["code"] for item in conflicts} >= {
        "analog_declared_exact",
        "technology_check_contradicts_bind",
        "operation_direction_conflict",
        "resource_action_collision",
        "coefficient_source_missing",
        "coverage_provider_invalid",
    }
    assert all(item["requires_model_review"] for item in conflicts)


def test_conflict_validator_flags_possible_cross_row_double_count_without_rewriting():
    rows = [
        {
            "work_id": "w1",
            "title": "Шпатлевка поверхности потолков ГКЛ в два слоя",
            "unit": "м²",
            "section": "Потолки",
        },
        {
            "work_id": "w2",
            "title": "Шпатлевка финишная потолков ГКЛ",
            "unit": "м²",
            "section": "Потолки",
        },
    ]
    selections = {
        "w1": {"norm_code": "ГЭСН15-04-027-06"},
        "w2": {"norm_code": "ГЭСН15-04-027-06"},
    }
    snapshot = json.loads(json.dumps(selections, ensure_ascii=False))

    conflicts = detect_professional_conflicts(rows, selections)

    assert selections == snapshot
    duplicate = next(item for item in conflicts if item["code"] == "possible_duplicate_norm_binding")
    assert duplicate["work_ids"] == ["w1", "w2"]
    assert duplicate["severity"] == "warning"


def test_mapping_revisions_are_append_only_and_explicitly_typed(tmp_path):
    initial = MappingRevision(
        mapping_run_id="run-1",
        revision_kind="row_mapping",
        decisions={"w1": {"norm_code": ""}},
        source_rows=({"work_id": "w1", "title": "Работа"},),
    )
    initial_path = save_mapping_revision(initial, root=tmp_path)
    reviewed = MappingRevision(
        mapping_run_id="run-1",
        revision_kind="global_review",
        decisions={"w1": {"norm_code": "ГЭСН01-01-001-01"}},
        source_rows=({"work_id": "w1", "title": "Работа"},),
        parent_revision_id=initial.revision_id,
        mapping_status="mapping_globally_reviewed",
    )
    reviewed_path = save_mapping_revision(reviewed, root=tmp_path)

    assert initial_path != reviewed_path
    assert load_mapping_revision(initial.revision_id, root=tmp_path)["revision_kind"] == "row_mapping"
    payload = load_mapping_revision(reviewed.revision_id, root=tmp_path)
    assert payload["parent_revision_id"] == initial.revision_id
    assert payload["mapping_status"] == "mapping_globally_reviewed"


def test_user_lock_requires_global_review_and_explicit_conflict_acceptance(tmp_path):
    reviewed = MappingRevision(
        mapping_run_id="run-1",
        revision_kind="global_review",
        decisions={"w1": {"decision": "bind", "norm_code": "ГЭСН01"}},
        source_rows=({"work_id": "w1", "title": "Работа"},),
        professional_conflicts=({"conflict_id": "c1", "code": "check"},),
        mapping_status="mapping_globally_reviewed",
    )
    save_mapping_revision(reviewed, root=tmp_path)

    with pytest.raises(ValueError, match="explicitly accepted"):
        create_user_lock_revision(
            reviewed.revision_id,
            root=tmp_path,
            reviewed_by="estimator",
            review_note="Проверено",
        )
    locked = create_user_lock_revision(
        reviewed.revision_id,
        root=tmp_path,
        reviewed_by="estimator",
        review_note="Проверено по карточке",
        accepted_conflict_ids=("c1",),
    )

    assert locked.created_by == "user"
    assert locked.mapping_status == "mapping_locked"
    assert locked.parent_revision_id == reviewed.revision_id
    assert locked.accepted_conflict_ids == ("c1",)


def test_quality_metrics_prioritize_wrong_confident_bind():
    metrics = mapping_quality_metrics(
        {
            "w1": {"norm_code": "ГЭСН01"},
            "w2": {},
            "w3": {"covered_by_work_id": "w1"},
        },
        {
            "w1": {
                "norm_code": "ГЭСН99",
                "opened_norm_codes": ["ГЭСН01"],
                "price_complete": True,
            },
            "w2": {
                "norm_code": "ГЭСН02",
                "opened_norm_codes": ["ГЭСН02"],
                "unit_conflict": True,
                "resource_double_count": True,
                "price_complete": False,
            },
            "w3": {"covered_by_work_id": "w1"},
        },
    )

    assert metrics["wrong_bind"] == 2
    assert metrics["wrong_bind_rate"] == 1.0
    assert metrics["hallucinated_norm"] == 1
    assert metrics["covered_by_precision"] == 1.0
    assert metrics["unopened_card_bind_rate"] == 0.5
    assert metrics["unit_conflict_rate"] == 0.3333
    assert metrics["resource_double_count_rate"] == 0.3333
    assert metrics["price_completeness"] == 0.5


def test_golden_prepare_keeps_model_proposal_separate_from_expert_truth():
    from tools.smeta_mapping_quality import _assert_expert_labels_complete, prepare_expert_template

    template = prepare_expert_template({
        "source_rows": [{
            "work_id": "w1", "title": "Монтаж линии", "unit": "м", "quantity": 10,
        }],
        "decisions": {
            "w1": {"norm_code": "ГЭСН01-01-001-01", "reason": "решение модели"},
        },
    })

    row = template["selections"]["w1"]
    assert template["schema"] == "smeta_expert_golden_v1"
    assert row["expert_status"] == "needs_expert_review"
    assert row["norm_code"] == ""
    assert row["model_proposal"]["norm_code"] == "ГЭСН01-01-001-01"
    with pytest.raises(ValueError, match="unreviewed rows: w1"):
        _assert_expert_labels_complete(template["selections"])

    row["expert_status"] = "approved"
    row["expected_decision"] = "bind"
    row["norm_code"] = "ГЭСН01-01-001-02"
    _assert_expert_labels_complete(template["selections"])


def test_evidence_budget_has_independent_dimensions():
    budget = EvidenceBudget(search_calls=4, read_calls=3, opened_cards=9, elapsed_seconds=120)

    assert budget.search_calls == 4
    assert budget.read_calls == 3
    assert budget.opened_cards == 9
    assert budget.elapsed_seconds == 120


def test_model_scope_plan_separates_scoped_and_global_search():
    scoped = ModelScopePlan(
        work_id="w1",
        scope_mode="scoped",
        queries=("монтаж блока",),
        search_intents=("fsnb_technology",),
        base_types=("ГЭСНм",),
        collections=("10",),
    )
    assert scoped.as_dict()["base_types"] == ["ГЭСНм"]
    assert scoped.as_dict()["collections"] == ["10"]

    with pytest.raises(ValueError, match="requires model-selected"):
        ModelScopePlan(
            work_id="w1",
            scope_mode="scoped",
            queries=("монтаж блока",),
            search_intents=("fsnb_technology",),
        )
    with pytest.raises(ValueError, match="cannot contain"):
        ModelScopePlan(
            work_id="w1",
            scope_mode="global",
            queries=("монтаж блока",),
            search_intents=("fsnb_technology",),
            base_types=("ГЭСНм",),
            collections=("10",),
        )


def test_elapsed_evidence_budget_never_blocks_terminal_mapping():
    from proxy.smeta_core import document_workflow as workflow

    session = workflow.SmetaNormToolSession(
        [{"work_id": "w1", "title": "Работа", "unit": "шт", "quantity": 1}],
        candidate_limit=4,
        evidence_budget=EvidenceBudget(elapsed_seconds=0.001),
    )
    session.query_trace.append({
        "work_id": "w1",
        "queries": ["исходная работа", "нормативная операция"],
    })
    session.started_at -= 10

    result = session.execute(
        "submit_lsr_mapping",
        {
            "rows": [{
                "work_id": "w1",
                "decision": "unbound",
                "reason": "защищаемая норма не найдена",
                "unbound_evidence": {
                    "queries_used": ["исходная работа", "нормативная операция"],
                    "opened_norm_codes": [],
                    "rejection_reasons": ["нет применимого состава работ"],
                    "coverage_checked": "покрытие отсутствует",
                },
            }],
        },
        turn=7,
    )

    assert result == {"ok": True, "rows": 1}
    assert session.complete is True


def test_numeric_coefficient_without_source_cannot_be_final():
    from proxy.smeta_core.calculator import calculate_scenario

    scenario = calculate_scenario([], [], k_ozp=1.15)

    assert {item["code"] for item in scenario.blockers} == {"coefficient_source_missing"}
    assert scenario.trace["summary"]["result_status"] != "priced_final"


def test_lock_route_calculates_only_new_user_revision(tmp_path, monkeypatch):
    from proxy.routers import chat

    locked = MappingRevision(
        mapping_run_id="run-1",
        revision_kind="user_lock",
        decisions={"w1": {"norm_code": "ГЭСН01"}},
        source_rows=({"work_id": "w1", "title": "Работа"},),
        parent_revision_id="review-1",
        created_by="user",
        mapping_status="mapping_locked",
    )
    monkeypatch.setattr(chat, "_SMETA_ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(chat, "SMETA_REVISION_ROOT", tmp_path / "revisions")
    monkeypatch.setattr(chat, "create_user_lock_revision", lambda *args, **kwargs: locked)
    captured = []

    def finalize(revision, **kwargs):
        captured.append((revision, kwargs))
        return {"lsr": {"summary": {"result_status": "priced_final"}}}

    monkeypatch.setattr(chat, "finalize_locked_mapping_revision", finalize)
    result = asyncio.run(chat.lock_smeta_mapping(
        "review-1",
        chat.SmetaMappingLockRequest(review_note="Проверено"),
        SimpleNamespace(holder="estimator", role="user"),
    ))

    assert captured[0][0].revision_kind == "user_lock"
    assert result["status"] == "mapping_locked"
    assert result["calculation_status"] == "priced_final"
    assert "lsr_locked_" in result["artifact"]["downloads"]["xlsx"]


def test_document_workflow_creates_global_review_and_draft_calculation(tmp_path, monkeypatch):
    from proxy.smeta_core import document_workflow as workflow

    rows = [
        {"work_id": "w1", "title": "Испытание линии", "unit": "шт", "quantity": 1},
        {"work_id": "w2", "title": "Монтаж линии", "unit": "шт", "quantity": 1},
    ]
    monkeypatch.setattr(workflow, "intake_vor_document", lambda _path: {"work_items": rows})
    calculated = []
    monkeypatch.setattr(workflow, "calculate_visible_rows_revision", lambda visible, **kwargs: (
        calculated.append((visible, kwargs))
        or {"summary": {"input_rows": 2, "bound_rows": 1, "open_rows": 0, "result_status": "priced_final"}}
    ))
    calls = []

    def batch_runner(work_rows, **_kwargs):
        calls.append(work_rows)
        if work_rows[0].get("review_phase") == "global_cross_row_review":
            assert all("current_decision" in row for row in work_rows)
            compact = work_rows[1]["opened_norm_cards"][0]
            assert "resources" not in compact
            assert compact["resource_count"] == 20
            assert len(compact["resource_preview"]) == 8
            assert compact["full_card_available_via"] == "read_norms_batch"
            return {
                "selections": {
                    "w1": {"covered_by_work_id": "w2", "reason": "входит в комплекс"},
                    "w2": {
                        "norm_code": "ГЭСН01-01-001-02",
                        "reason": "глобальная ревизия выбрала другую комплексную норму",
                    },
                },
                "opened_cards": {"w2": [{
                    "norm_code": "ГЭСН01-01-001-02",
                    "title": "Монтаж и испытание линии",
                    "work_steps": ["Монтаж линии", "Испытание линии"],
                }]},
                "browse_trace": {}, "query_trace": [], "model_trace": [],
                "valid_model_rows": 2, "agent_trace": {"engine": "test-review"},
            }
        return {
            "selections": {
                "w1": {"norm_code": "", "reason": "первичный unbound"},
                "w2": {
                    "norm_code": "ГЭСН01-01-001-01",
                    "reason": "первичный bind",
                    "resource_bindings": [{
                        "action": "exclude",
                        "target_resource_code": "OLD-RESOURCE",
                        "reason": "решение R1",
                        "basis_ref": "R1-card",
                    }],
                    "nr_sp_rule_id": "R1-rule",
                },
            },
            "opened_cards": {"w2": [{
                "norm_code": "ГЭСН01-01-001-01",
                "title": "Монтаж и испытание линии",
                "work_steps": ["Монтаж линии", "Испытание линии"],
                "resources": [
                    {"kind": "material", "code": f"M-{index}", "name": f"Материал {index}", "unit": "шт"}
                    for index in range(20)
                ],
            }]},
            "browse_trace": {}, "query_trace": [], "model_trace": [],
            "valid_model_rows": 2, "agent_trace": {"engine": "test-row"},
        }

    result = workflow.run_vor_document_workflow(
        "source.xlsx",
        exchange=lambda _messages, _tools: {},
        agent_batch_runner=batch_runner,
        require_global_review=True,
        revision_root=str(tmp_path),
    )

    assert len(calls) == 2
    assert result["selections"]["w1"]["covered_by_work_id"] == "w2"
    assert result["selections"]["w2"]["norm_code"] == "ГЭСН01-01-001-02"
    assert "resource_bindings" not in result["selections"]["w2"]
    assert calculated[0][0][1]["resource_bindings"] == []
    assert calculated[0][0][1]["nr_sp_rule_id"] == ""
    assert result["mapping_run"]["row_mapping_revision_id"]
    assert result["mapping_run"]["global_review_revision_id"]
    assert result["mapping_run"]["approval_status"] == "auto_draft"
    assert result["lsr"]["summary"]["calculation_result_status"] == "priced_final"
    assert result["lsr"]["summary"]["result_status"] == "priced_draft"
    assert calculated[0][1]["parent_revision_id"] == result["mapping_run"]["global_review_revision_id"]
    assert len(list(Path(tmp_path).glob("mapping_*.json"))) == 2
