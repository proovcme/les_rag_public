"""One shared estimator skill keeps document formation separate from pricing."""
import hashlib
import inspect
import json
from pathlib import Path
from copy import deepcopy

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.chat_profile_service import _factory_contracts


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/smeta/references/rag-estimator.md"


def _skill():
    return SKILL_PATH.read_text(encoding="utf-8").strip()


def _point(number):
    return next(line for line in _skill().splitlines() if line.startswith(f"{number}. "))


def test_search_and_nrsp_requirements_have_document_scope_in_the_shared_skill():
    search = _point(2)
    assert search.startswith("2. Если для текущего документа нужен внешний поиск")
    assert "Для ВОР достаточный исходник не требует поиска норм и цен" in search
    assert "Для подбираемой нормы" in search
    nrsp = _point(8)
    assert nrsp.startswith("8. Для ЛСР или добровольно выбранной для ВОР нормы:")
    assert "В ВОР без выбранной нормы отсутствие НР/СП не является открытым вопросом" in nrsp
    assert "nr_sp_rule_id" in nrsp and "не подставляй процент или правило по памяти" in nrsp


def test_confirmed_zero_and_unknown_have_distinct_meanings_without_role_forcing():
    instruction = _point(7)
    assert "Подтверждённый нулевой объём сохраняй как 0" in instruction
    assert "сам по себе он не делает строку unresolved" in instruction
    assert "пояснение о невыполнении укажи в coverage" in instruction
    assert "неизвестный объём остаётся null" in instruction
    assert "open_gap — только нерешённый вопрос" in instruction


@pytest.mark.parametrize("artifact_kind", ["vor", "lsr", ""])
def test_factory_and_bound_result_prompts_use_the_same_scoped_professional_skill(artifact_kind):
    skill = _skill()
    assert _factory_contracts()["estimator"]["skill"].strip() == skill
    snapshot = {"mode": "estimator", "prompt_text": "Literal role Ω", "skill_text": skill,
                "model_policy": {"temperature": 0.15}, "tools": ["read_source"]}
    before = deepcopy(snapshot)
    bound = app.overlay_tabular_estimator_snapshot(snapshot)
    prompt = app.profile_system_prompt(bound, strict=False, purpose="workbook_result",
                                       artifact_kind=artifact_kind)
    assert prompt.count(skill) == 1
    assert "Literal role Ω" in prompt
    assert bound["model_policy"] == snapshot["model_policy"]
    assert snapshot == before
    assert bound["effective_skill_modules"][0]["sha256"] == hashlib.sha256(skill.encode()).hexdigest()


def test_instruction_keeps_model_authorship_no_automatic_installation_and_source_basis():
    skill = _skill()
    for rule in ("Не назначай автоматически отдельный монтаж каждому изделию",
                 "Один исходный locator может обосновывать несколько операций и изделие",
                 "с реальными связями", "Количество из исходника сохраняй",
                 "производный объём требует формулы и источника",
                 "Для выбранной нормы явно верни action_match, object_match, condition_match"):
        assert rule in skill


def test_exact_factory_managed_skill_is_replaced_only_for_the_turn_with_truthful_provenance():
    previous = "Bound historical factory skill Ω\nNo custom text."
    previous_sha = hashlib.sha256(previous.encode()).hexdigest()
    snapshot = {"mode": "estimator", "prompt_text": "Bound role Ω",
                "skill_revision_id": "factory:skill:estimator:base",
                "skill_text": previous, "skill_sha256": previous_sha,
                "model_policy": {"temperature": 0.2}, "tools": ["read_source"]}
    before = deepcopy(snapshot)
    effective = app.overlay_tabular_estimator_snapshot(snapshot)
    assert effective["skill_text"] == _skill()
    assert previous not in effective["skill_text"]
    assert snapshot == before
    assert effective["skill_revision_id"] == snapshot["skill_revision_id"]
    assert effective["skill_sha256"] == previous_sha, "the saved binding was not republished"
    assert effective["model_policy"] == snapshot["model_policy"]
    module = effective["effective_skill_modules"][0]
    assert module["source"] == "factory_managed_turn_overlay"
    assert module["sha256"] == hashlib.sha256(_skill().encode()).hexdigest()
    assert module["replaced_managed_skill_revision_id"] == snapshot["skill_revision_id"]
    assert module["replaced_managed_skill_sha256"] == previous_sha
    assert module["saved_snapshot_modified"] is False


@pytest.mark.parametrize("revision", ["user:skill:estimator:custom", "factory:skill:agent:base",
                                      "factory:skill:estimator:base:copy", "", None])
def test_custom_or_other_skill_provenance_never_triggers_a_factory_replacement(revision):
    custom = "Literal custom Ω: factory:skill:estimator:base\n# Сметчик: исходник → работы → ЛСР"
    snapshot = {"mode": "estimator", "prompt_text": "Custom role",
                "skill_revision_id": revision, "skill_text": custom,
                "skill_sha256": hashlib.sha256(custom.encode()).hexdigest()}
    before = deepcopy(snapshot)
    effective = app.overlay_tabular_estimator_snapshot(snapshot)
    assert effective["skill_text"] == custom + "\n\n" + _skill()
    assert snapshot == before
    module = effective["effective_skill_modules"][0]
    assert module["source"] == "tabular_attachment_estimator_path_v1"
    assert "replaced_managed_skill_revision_id" not in module
    assert "replaced_managed_skill_sha256" not in module


def test_custom_skill_that_already_contains_current_contract_is_preserved_literally():
    custom = "\tCustom before Ω\n\n" + _skill() + "\n\nCustom after Ω\t"
    snapshot = {"mode": "estimator", "skill_revision_id": "user:skill:custom", "skill_text": custom}
    before = deepcopy(snapshot)
    effective = app.overlay_tabular_estimator_snapshot(snapshot)
    assert effective["skill_text"] == custom
    assert effective["skill_text"].count(_skill()) == 1
    assert snapshot == before


@pytest.mark.asyncio
async def test_admitted_review_resolves_pending_before_the_packet_stall_guard(tmp_path, monkeypatch):
    """The real durable merge, rather than a retained baseline, decides progress."""
    from proxy.services.openai_compatible_transport_service import InferenceResponse
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    from tests import test_model_rag_sheet_evidence_reads as fixture

    original_rows = [{"source_row": locator, "row_role": "work", "title": title,
                      "unit": "m", "quantity": quantity, "open_gap": ""}
                     for locator, title, quantity in [("S!R2", "Cable A", 12), ("S!R3", "Cable B", 3)]]
    query = json.dumps({"artifact_kind": "vor", "queries": []})
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False,
        query_declaration=query, final_answer=json.dumps({"artifact_kind": "vor", "rows": original_rows}))
    store = WorkbookResearchJobService()
    original_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    original = store.get(original_id)
    before = deepcopy(original["accepted_rows"])
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Учти замечание инженера и перепроверь документ"
    reviewed_rows = [{**{key: row[key] for key in (
        "source_row", "row_role", "title", "unit", "quantity", "operation_id")},
        "expected_revision": row["revision"]} for row in before]
    run.responses.extend([
        InferenceResponse(text=query, tool_calls=(), finish_reason="stop", usage={}),
        InferenceResponse(text=json.dumps({"artifact_kind": "vor", "rows": reviewed_rows}),
                          tool_calls=(), finish_reason="stop", usage={}),
    ])
    monkeypatch.setattr(app, "_ROW_PACKET_MAX_ATTEMPTS", 1)
    deferred = []
    original_defer = WorkbookResearchJobService.defer_locators

    def record_deferral(self, *args, **kwargs):
        deferred.append(kwargs)
        return original_defer(self, *args, **kwargs)

    monkeypatch.setattr(WorkbookResearchJobService, "defer_locators", record_deferral)
    result = await run.resume_same_request()
    trace = result["retrieval_trace"]
    reviewed = store.get(trace["workbook_research_job"]["job_id"])
    assert WorkbookResearchJobService.pending_research_locators(reviewed) == set()
    assert reviewed["remaining"] == []
    assert not deferred, "a durable admitted review must not be deferred as no progress"
    assert trace["tool_loop"]["passes"][-1]["newly_decided"] == 2
    assert not run.responses, "resolving the review must not buy another model cycle"
    assert store.get(original_id)["accepted_rows"] == before
