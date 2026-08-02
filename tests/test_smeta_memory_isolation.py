"""Memory observes published estimates without changing the stable smeta core."""

from pathlib import Path

from proxy.memory_core.config import MemoryConfig
from proxy.memory_core.contracts import MemoryMode
from proxy.memory_core.store import MemoryStore
from proxy.services.memory_port import NullMemoryPort, configure_memory_port, get_memory_port
from proxy.services.memory_rag_adapter import ActiveMemoryPort
from proxy.services.memory_smeta_observer import observe_published_smeta
from proxy.smeta_core.document_workflow import SmetaNormToolSession


def test_null_memory_port_isolation():
    configure_memory_port(None)
    assert isinstance(get_memory_port(), NullMemoryPort)


def test_observer_requires_positive_project_and_published_finality():
    workflow = {"lsr": {"summary": {"result_status": "blocked"}}}
    assert observe_published_smeta(
        project_id=1, attachment_id="a", source_sha256="sha", user_request="q", workflow=workflow,
    ) == 0
    workflow["lsr"]["summary"]["result_status"] = "priced_draft"
    assert observe_published_smeta(
        project_id=None, attachment_id="a", source_sha256="sha", user_request="q", workflow=workflow,
    ) == 0


def test_observer_captures_success_but_does_not_invent_route(tmp_path: Path | None = None):
    store = MemoryStore(":memory:")
    configure_memory_port(ActiveMemoryPort(store, MemoryConfig(mode=MemoryMode.SHADOW)))
    workflow = {
        "xlsx_path": "LSR.xlsx", "report_path": "LSR.json",
        "lsr": {"summary": {"result_status": "priced_draft"}},
        "mapping_run": {"current_mapping_revision_id": "rev1"},
        "intake": {"work_items": [{"work_id": "w1", "title": "Монтаж кабеля", "unit": "м"}]},
        "selections": {"w1": {"norm_code": "ГЭСНм10-01-001-01"}},
    }
    try:
        assert observe_published_smeta(
            project_id=5, attachment_id="a1", source_sha256="sha", user_request="смета", workflow=workflow,
        ) == 1
        traces = store.get_smeta_traces(5)
        assert traces[0].selected_norm_refs == ("ГЭСНм10-01-001-01",)
        assert traces[0].typed_catalog_routes == ()
        assert traces[0].knowledge_edition_identity == "unresolved"
    finally:
        configure_memory_port(None)


def test_observer_does_not_capture_calculated_candidate_draft():
    store = MemoryStore(":memory:")
    configure_memory_port(ActiveMemoryPort(store, MemoryConfig(mode=MemoryMode.SHADOW)))
    workflow = {
        "xlsx_path": "LSR.xlsx", "report_path": "LSR.json",
        "lsr": {"summary": {"result_status": "priced_draft"}},
        "mapping_run": {"current_mapping_revision_id": "rev1"},
        "intake": {"work_items": [{"work_id": "w1", "title": "cabinet", "unit": "pcs"}]},
        "selections": {
            "w1": {
                "norm_code": "GESNm37-01-002-05",
                "review_status": "model_batch_candidate",
            }
        },
    }
    try:
        assert observe_published_smeta(
            project_id=5,
            attachment_id="a1",
            source_sha256="sha",
            user_request="estimate",
            workflow=workflow,
        ) == 0
        assert store.get_smeta_traces(5) == []
    finally:
        configure_memory_port(None)


def test_smeta_session_operates_without_memory():
    session = SmetaNormToolSession(
        work_rows=[{"work_id": "vor-0001", "title": "Кабель", "unit": "м"}], candidate_limit=2,
    )
    assert len(session.by_id) == 1
