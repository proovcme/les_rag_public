from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.routers.rim import router
from proxy.security import RequestUser, require_user
from proxy.smeta_core.application import get_rim_session_store, set_rim_session_store
from proxy.smeta_core.rim_session import RimSessionStore


def _client(tmp_path):
    set_rim_session_store(RimSessionStore(tmp_path / "rim"))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_user] = lambda: RequestUser(
        role="user", holder="api-tester", source="api_key"
    )
    return TestClient(app)


def test_rim_api_runs_vor_mapping_and_two_lock_flow(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/rim/sessions",
        json={"project_id": "p-1", "region_code": "77", "price_period": "2026-Q2"},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    head = created.json()["revision_id"]

    imported = client.post(
        f"/api/rim/sessions/{session_id}/vor/import",
        files={"file": ("vor.csv", "Раздел;Наименование;Ед. изм.;Количество\nСКС;Прокладка кабеля;м;400\n")},
        data={"source_kind": "vor", "expected_parent_revision_id": head},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["status"] == "awaiting_vor_approval"
    head = imported.json()["revision_id"]

    mapping_row = {
        "mapping_row_id": "map-1",
        "work_id": "vor-0001",
        "norm_key": "ГЭСНм:10-06-001-01",
        "norm_code": "10-06-001-01",
        "norm_title": "Прокладка кабеля",
        "norm_unit": "100 м",
        "norm_quantity": 4,
        "candidate_rank": 1,
        "selection_status": "selected",
        "selection_kind": "direct",
        "is_analog": False,
        "card_opened": True,
        "reason": "Модель прочитала карточку",
        "source_refs": ["vor.csv#row=2"],
        "edited_by": "model",
    }
    mapping = client.post(
        f"/api/rim/sessions/{session_id}/mapping/candidates",
        json={"mapping_rows": [mapping_row], "expected_parent_revision_id": head},
    )
    assert mapping.status_code == 200, mapping.text
    head = mapping.json()["revision_id"]

    reviewed = client.post(
        f"/api/rim/sessions/{session_id}/mapping/global-review",
        json={
            "mapping_rows": [mapping_row],
            "professional_conflicts": [],
            "expected_parent_revision_id": head,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    head = reviewed.json()["revision_id"]
    locked = client.post(
        f"/api/rim/sessions/{session_id}/mapping/lock",
        json={"review_note": "Проверено", "expected_parent_revision_id": head},
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["session"]["pricing_status"] == "unpriced"
    mapping_lock_id = locked.json()["revision_id"]

    priced = client.post(
        f"/api/rim/sessions/{session_id}/pricing/revisions",
        json={
            "trace": {"summary": {"total": 1000}},
            "requirements": [],
            "expected_parent_revision_id": mapping_lock_id,
        },
    )
    assert priced.status_code == 200, priced.text
    assert priced.json()["session"]["pricing_status"] == "priced_draft"
    final = client.post(
        f"/api/rim/sessions/{session_id}/finalize",
        json={
            "review_note": "Финальная проверка",
            "expected_parent_revision_id": priced.json()["revision_id"],
        },
    )
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "priced_final"
    assert final.json()["session"]["mapping_lock_revision_id"] == mapping_lock_id

    audit = client.get(f"/api/rim/sessions/{session_id}/audit")
    assert audit.status_code == 200
    assert [item["revision_kind"] for item in audit.json()["revisions"]] == [
        "session_created",
        "source_intake",
        "vor_revision",
        "mapping_revision",
        "mapping_global_review",
        "mapping_lock",
        "pricing_revision",
        "final_lock",
    ]


def test_rim_api_rejects_stale_parent(tmp_path):
    client = _client(tmp_path)
    created = client.post("/api/rim/sessions", json={}).json()
    session_id = created["session_id"]
    first = client.post(
        f"/api/rim/sessions/{session_id}/questions",
        json={
            "text": "Как выполнить монтаж?",
            "expected_parent_revision_id": created["revision_id"],
        },
    )
    assert first.status_code == 200
    stale = client.post(
        f"/api/rim/sessions/{session_id}/questions/answer",
        json={
            "answer": {"value": "в лотке"},
            "expected_parent_revision_id": created["revision_id"],
        },
    )
    assert stale.status_code == 409
    assert "session head changed" in stale.text


def test_rim_api_exposes_active_mapping_checkpoint_progress(tmp_path):
    client = _client(tmp_path)
    created = client.post("/api/rim/sessions", json={}).json()
    session_id = created["session_id"]
    vor = client.post(
        f"/api/rim/sessions/{session_id}/vor/revisions",
        json={
            "expected_parent_revision_id": created["revision_id"],
            "created_by": "user",
            "rows": [
                {
                    "work_id": "vor-001",
                    "section_name": "СКС",
                    "work_name": "Монтаж шкафа",
                    "unit": "шт",
                    "quantity": 2,
                    "source_ref": "/tmp/СКС.xlsx#sheet=СКС;row=6",
                }
            ],
        },
    ).json()
    store = get_rim_session_store()
    store.save_agent_checkpoint(
        session_id,
        owner_id="api-tester",
        checkpoint_kind="norm_mapping",
        base_revision_id=vor["revision_id"],
        payload={
            "resume_state": {
                "validation_contract_version": "grounded-terminal-unbound-v4",
                "tool_session": {
                    "candidates": {
                        "vor-001": {
                            "ГЭСНм10-06-001-01": {
                                "norm_code": "ГЭСНм10-06-001-01",
                                "title": "Монтаж шкафа",
                                "measure_unit": "1 шт.",
                            }
                        }
                    },
                    "opened": {"vor-001": {}},
                    "accepted_rows": {},
                    "query_trace": [
                        {
                            "work_id": "vor-001",
                            "queries": ["монтаж шкафа"],
                            "filters": {
                                "base_types": ["ГЭСНм"],
                                "collections": ["10"],
                            },
                        }
                    ],
                },
            }
        },
    )

    response = client.get(f"/api/rim/sessions/{session_id}/mapping/progress")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["active"] is True
    assert payload["summary"]["total_rows"] == 1
    assert payload["rows"][0]["stage"] == "candidates_found"
    assert payload["rows"][0]["source_display"] == "СКС.xlsx · лист «СКС» · строка 6"


def test_rim_api_calculates_only_an_authored_scenario(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/rim/sessions",
        json={"region_code": "77", "price_period": "2026-Q2"},
    ).json()
    session_id = created["session_id"]
    vor = client.post(
        f"/api/rim/sessions/{session_id}/vor/revisions",
        json={
            "expected_parent_revision_id": created["revision_id"],
            "created_by": "user",
            "rows": [
                {
                    "work_id": "vor-001",
                    "section_name": "Кровля",
                    "work_name": "Устройство обрешетки",
                    "unit": "м2",
                    "quantity": 61,
                    "source_ref": "vor.xlsx#row=2",
                }
            ],
        },
    ).json()
    mapping_row = {
        "mapping_row_id": "map-1",
        "work_id": "vor-001",
        "norm_key": "ГЭСН:12-01-034-02",
        "norm_code": "12-01-034-02",
        "norm_title": "Устройство обрешетки",
        "norm_unit": "100 м2",
        "selection_status": "accepted",
        "selection_kind": "direct",
        "is_analog": False,
        "card_opened": True,
        "reason": "Карточка прочитана",
        "edited_by": "model",
    }
    mapping = client.post(
        f"/api/rim/sessions/{session_id}/mapping/global-review",
        json={
            "mapping_rows": [mapping_row],
            "professional_conflicts": [],
            "expected_parent_revision_id": vor["revision_id"],
        },
    ).json()
    locked = client.post(
        f"/api/rim/sessions/{session_id}/mapping/lock",
        json={
            "review_note": "Проверено",
            "expected_parent_revision_id": mapping["revision_id"],
        },
    ).json()
    scenarios = client.post(
        f"/api/rim/sessions/{session_id}/combinations/generate",
        json={
            "expected_parent_revision_id": locked["revision_id"],
            "scenarios": [
                {
                    "scenario_id": "scenario-1",
                    "title": "Основной",
                    "authored_by": "model",
                    "compatibility_reason": "Единственная работа и прочитанная норма",
                    "selections": [{"mapping_row_id": "map-1"}],
                }
            ],
        },
    )
    assert scenarios.status_code == 200, scenarios.text
    assert scenarios.json()["status"] == "combinations_ready"
    calculated = client.post(
        f"/api/rim/sessions/{session_id}/combinations/calculate",
        json={
            "scenario_id": "scenario-1",
            "expected_parent_revision_id": scenarios.json()["revision_id"],
        },
    )
    assert calculated.status_code == 200, calculated.text
    assert calculated.json()["trace"]["summary"]["bound_rows"] == 1
    assert calculated.json()["trace"]["coverage"][0]["validation"]["norm_quantity"] == 0.61
