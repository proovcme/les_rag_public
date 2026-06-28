import json
import sqlite3
from pathlib import Path

from proxy.routers.chat import save_chat_history
from proxy.services.lexical_index_service import LexicalIndex
from proxy.services.context_memory_service import (
    DATASET_PROFILE_FILE,
    benchmark_dataset_profile_warmup,
    build_context_memory_block,
    build_dataset_profile,
    get_chat_profile,
    warmup_dataset_profiles,
)
from proxy.services.notebook_service import (
    build_dataset_notebook,
    build_gesn_notebook,
    service_source_notebooks,
    warmup_dataset_notebooks,
)


def _seed_meta_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE datasets (
                id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT,
                chunk_count INTEGER DEFAULT 0,
                group_name TEXT DEFAULT '',
                sensitivity TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_mtime REAL DEFAULT 0,
                file_size INTEGER DEFAULT 0,
                chunk_count INTEGER DEFAULT 0,
                doc_type TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                route_dataset TEXT DEFAULT '',
                source_path TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO datasets(id, name, status, chunk_count, group_name, sensitivity) "
            "VALUES('ds-1', 'Проект ПД', 'IDLE', 12, 'project', 'P0')"
        )
        conn.execute(
            "INSERT INTO documents(id, dataset_id, file_name, status, chunk_count, doc_type, domain, route_dataset) "
            "VALUES('doc-1', 'ds-1', '01-ПЗ.pdf', 'INDEXED', 7, 'PDF', 'PD', 'NTD_PROJECT')"
        )
        conn.execute(
            "INSERT INTO documents(id, dataset_id, file_name, status, chunk_count, doc_type, domain, route_dataset) "
            "VALUES('doc-2', 'ds-1', '02-Спецификация.xlsx', 'INDEXED', 5, 'TABLE', 'SPEC', 'SMETA')"
        )
        conn.commit()


def _seed_lexical(path: Path) -> None:
    index = LexicalIndex(str(path))
    index.upsert_chunks(
        "les_rag_test",
        [
            {
                "point_id": "p1",
                "dataset_id": "ds-1",
                "doc_id": "doc-1",
                "doc_name": "01-ПЗ.pdf",
                "text": "ГОСТ Р 21.101-2026 задаёт требования к проектной документации и нормоконтролю.",
                "chunk_ord": 1,
                "section_heading": "Общие требования",
            },
            {
                "point_id": "p2",
                "dataset_id": "ds-1",
                "doc_id": "doc-2",
                "doc_name": "02-Спецификация.xlsx",
                "text": "| Наименование | Ед. изм | Количество | Цена | Сумма |",
                "chunk_ord": 1,
                "section_heading": "Спецификация",
            },
        ],
    )


def test_dataset_profile_writes_sidecar(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "les_meta.db"
    storage_root = tmp_path / "storage" / "datasets"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    _seed_meta_db(db_path)

    profile = build_dataset_profile("ds-1", storage_root=storage_root)

    assert profile["dataset_id"] == "ds-1"
    assert profile["document_count"] == 2
    assert profile["chunk_count"] == 12
    assert "coverage_note" in profile
    sidecar = storage_root / "ds-1" / DATASET_PROFILE_FILE
    assert sidecar.exists()
    saved = json.loads(sidecar.read_text())
    assert saved["name"] == "Проект ПД"
    assert saved["sample_files"][0]["file_name"]


def test_deep_dataset_profile_uses_bounded_lexical_index(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "les_meta.db"
    storage_root = tmp_path / "storage" / "datasets"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    _seed_meta_db(db_path)
    _seed_lexical(db_path)

    profile = build_dataset_profile("ds-1", storage_root=storage_root, depth="deep")

    assert profile["depth"] == "deep"
    assert profile["deep"]["available"] is True
    assert profile["deep"]["lexical_chunks"] == 2
    assert "ГОСТ Р 21.101-2026" in profile["deep"]["norm_refs"]
    assert profile["deep"]["table_signal_chunks"] == 1
    assert profile["deep"]["representative_fragments"]
    assert profile["quality"]["status"] == "good"
    assert profile["quality"]["score"] > 0.7
    assert profile["cache_status"] in {"miss", "rebuilt"}
    saved = json.loads((storage_root / "ds-1" / DATASET_PROFILE_FILE).read_text())
    assert saved["deep"]["available"] is True
    assert saved["quality"]["status"] == "good"


def test_dataset_notebook_wraps_profile_as_navigation_not_evidence(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "les_meta.db"
    storage_root = tmp_path / "storage" / "datasets"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    _seed_meta_db(db_path)
    _seed_lexical(db_path)

    notebook = build_dataset_notebook("ds-1", storage_root=storage_root, depth="deep")

    assert notebook["schema"] == "notebook_v1"
    assert notebook["context_role"] == "navigation"
    assert notebook["is_evidence"] is False
    assert notebook["profile"]["dataset_id"] == "ds-1"
    assert notebook["notebook_summary"]["key_terms"]
    assert "НЕ evidence" not in notebook["prompt_excerpt"]
    assert "не evidence" in notebook["prompt_excerpt"].lower()


def test_warmup_dataset_notebooks_uses_profiles_without_reindex(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "les_meta.db"
    storage_root = tmp_path / "storage" / "datasets"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    _seed_meta_db(db_path)
    _seed_lexical(db_path)

    result = warmup_dataset_notebooks(dataset_ids=["ds-1"], storage_root=storage_root, depth="deep", force=True)

    assert result["schema"] == "notebook_v1"
    assert result["built"] == 1
    assert result["notebooks"][0]["summary"]["purpose"]


def test_gesn_notebook_maps_required_collections(monkeypatch):
    from proxy.services import gesn_service
    from proxy.services import notebook_service as nb

    monkeypatch.setattr(gesn_service, "load_base_norms", lambda: {
        "ГЭСН:01-02-063-02": {"code": "ГЭСН01-02-063-02", "name": "Разработка грунта котлована", "unit": "100 м3"},
        "ГЭСН:05-01-028-04": {"code": "ГЭСН05-01-028-04", "name": "Устройство свай", "unit": "м3"},
        "ГЭСН:10-02-017-03": {"code": "ГЭСН10-02-017-03", "name": "Каркасные деревянные стены", "unit": "100 м2"},
        "ГЭСН:12-01-021-01": {"code": "ГЭСН12-01-021-01", "name": "Устройство кровли", "unit": "100 м2"},
        "ГЭСН:15-04-048-05": {"code": "ГЭСН15-04-048-05", "name": "Отделочные работы", "unit": "100 м2"},
        "ГЭСН:21-02-001-01": {"code": "ГЭСН21-02-001-01", "name": "Прокладка кабеля", "unit": "100 м"},
    })
    monkeypatch.setattr(gesn_service, "load_norms", lambda: {})
    nb.build_gesn_notebook.cache_clear()

    notebook = build_gesn_notebook()
    by_code = {c["collection"]: c for c in notebook["collections"]}

    for code in ("01", "05", "10", "12", "15", "16", "17", "18", "20", "21", "22"):
        assert code in by_code
    assert "земляные" in by_code["01"]["area"]
    assert "отдел" in by_code["15"]["area"]
    assert "электро" in by_code["21"]["area"]
    assert notebook["is_evidence"] is False
    assert "Блокнот ГЭСН" in notebook["prompt_excerpt"]


def test_service_source_notebooks_returns_gesn_first(monkeypatch):
    from proxy.services import notebook_service as nb

    nb.build_gesn_notebook.cache_clear()
    monkeypatch.setattr(nb, "build_gesn_notebook", lambda: {
        "name": "ГЭСН: карта сборников",
        "context_role": "navigation",
        "is_evidence": False,
        "notebook_summary": {"purpose": "x"},
        "collections": [],
        "prompt_excerpt": "x",
    })

    result = service_source_notebooks()

    assert result["notebooks"][0]["id"] == "gesn"


def test_warmup_dataset_profiles_builds_all_requested(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "les_meta.db"
    storage_root = tmp_path / "storage" / "datasets"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    _seed_meta_db(db_path)
    _seed_lexical(db_path)

    result = warmup_dataset_profiles(dataset_ids=["ds-1"], storage_root=storage_root, depth="deep", force=True)

    assert result["status"] == "ok"
    assert result["built"] == 1
    assert result["profiles"][0]["lexical_chunks"] == 2
    assert result["profiles"][0]["quality_status"] == "good"
    assert result["profiles"][0]["quality_score"] > 0.7
    assert result["profiles"][0]["elapsed_ms"] >= 0


def test_benchmark_dataset_profile_warmup_reports_speed_delta(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "les_meta.db"
    storage_root = tmp_path / "storage" / "datasets"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    _seed_meta_db(db_path)
    _seed_lexical(db_path)

    result = benchmark_dataset_profile_warmup(dataset_ids=["ds-1"], storage_root=storage_root, depth="deep")

    assert result["status"] == "ok"
    assert result["benchmarked"] == 1
    item = result["profiles"][0]
    assert item["cold_rebuild_ms"] >= 0
    assert item["warm_read_ms"] >= 0
    assert item["speedup_x"] is None or item["speedup_x"] >= 0
    assert item["quality_status"] == "good"
    assert item["profile_path"].endswith(DATASET_PROFILE_FILE)


def test_chat_profile_updates_from_history_and_prompt_block(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "les_meta.db"
    storage_root = tmp_path / "storage" / "datasets"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    _seed_meta_db(db_path)
    _seed_lexical(db_path)

    history_id = save_chat_history(
        question="сделай смету по проекту",
        answer="ASSUME: принята масса по ТЗ.\nMISSING: нужен проектный PDF.",
        sources=["01-ПЗ.pdf"],
        crag_status="UNVALIDATED",
        latency_sec=0.1,
        tokens=0,
        session_id="s-1",
        effective_dataset_filter="SMETA",
        resolved_dataset_ids=["ds-1"],
        resolved_dataset_names=["Проект ПД"],
        source_dataset_ids=["ds-1"],
        source_dataset_names=["Проект ПД"],
        query_route={"channel": "rag", "reason": "test"},
        success=1,
    )

    assert history_id > 0
    profile = get_chat_profile("s-1")
    assert profile["turn_count"] == 1
    assert profile["assumptions"]
    assert profile["blockers"]

    block = build_context_memory_block(
        session_id="s-1",
        dataset_ids=["ds-1"],
        dataset_names=["Проект ПД"],
        storage_root=storage_root,
    )
    assert "Паспорт чата" in block
    assert "Паспорта выбранных датасетов" in block
    assert "ключевые слова по содержанию" in block
    assert "НЕ evidence" in block
