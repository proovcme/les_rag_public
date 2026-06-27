import asyncio
import sqlite3
from collections import deque
from dataclasses import dataclass
from io import BytesIO

import pytest
from fastapi import UploadFile

from proxy.routers import datasets


@dataclass
class Dataset:
    id: str
    name: str
    status: str = "IDLE"
    doc_count: int = 0
    chunk_count: int = 0


@dataclass
class Chunk:
    content: str
    doc_id: str
    doc_name: str
    score: float
    meta: dict


class FakeBackend:
    def __init__(self):
        self.datasets = [Dataset("ds-1", "NTD_Index", doc_count=3, chunk_count=7)]
        self.uploads = []
        self.parses = []
        self.pending_files = {}

    async def list_datasets(self):
        return self.datasets

    async def create_dataset(self, name):
        dataset_id = f"ds-{len(self.datasets) + 1}"
        self.datasets.append(Dataset(dataset_id, name))
        return dataset_id

    async def upload_file(self, dataset_id, file_path, relative_path=None):
        self.uploads.append((dataset_id, file_path.name, relative_path))
        return f"doc-{len(self.uploads)}"

    async def parse_dataset(self, dataset_id, limit=None):
        self.parses.append((dataset_id, limit))
        pending = max(0, int(self.pending_files.get(dataset_id, 0)) - int(limit or 0))
        self.pending_files[dataset_id] = pending
        return {"status": "completed", "chunks": 0, "remaining_pending": pending, "errors": 0}

    async def health(self):
        return True

    async def health_snapshot(self):
        return {
            "datasets": [
                {
                    "id": dataset.id,
                    "name": dataset.name,
                    "pending_files": self.pending_files.get(dataset.id, 0),
                }
                for dataset in self.datasets
            ]
        }

    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        return [
            Chunk(
                content=f"{question} result",
                doc_id="doc-1",
                doc_name="СП 3.13130.docx",
                score=0.73,
                meta={"doc_type": "NORMATIVE", "content_type": "text"},
            )
        ][:top_k]


class FakeJobService:
    def create(self, *args, **kwargs):
        return {"id": "job-1", "started_at": "2026-05-21T00:00:00"}

    def update(self, *args, **kwargs):
        return {}


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename)


@pytest.fixture()
def dataset_state(monkeypatch):
    previous = datasets._state
    backend = FakeBackend()
    datasets.set_dataset_state(
        datasets.DatasetRouterState(
            rag_backend=backend,
            job_service=FakeJobService(),
            job_tracker={},
            log_history=deque(maxlen=10),
            parse_semaphore=asyncio.Semaphore(1),
            sync_parse_semaphore=asyncio.Semaphore(1),
        )
    )
    yield backend
    datasets._state = previous


@pytest.mark.asyncio
async def test_dataset_list_and_create_use_configured_state(dataset_state):
    assert await datasets.list_datasets(_user=object()) == [Dataset("ds-1", "NTD_Index", doc_count=3, chunk_count=7)]

    created = await datasets.create_dataset("Mail_Index", _admin=object())

    assert created == {"id": "ds-2", "name": "Mail_Index"}


@pytest.mark.asyncio
async def test_list_documents_returns_file_status_rows(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with sqlite3.connect(data_dir / "les_meta.db") as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT, status TEXT, chunk_count INTEGER DEFAULT 0)")
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                domain TEXT DEFAULT '',
                route_dataset TEXT DEFAULT '',
                doc_type TEXT DEFAULT '',
                content_type TEXT DEFAULT '',
                complexity TEXT DEFAULT '',
                pipeline TEXT DEFAULT '',
                source_path TEXT DEFAULT '',
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO datasets (id, name, status) VALUES ('ds-1', 'NTD_FIRE_Index', 'IDLE')")
        conn.execute(
            """
            INSERT INTO documents
            (id, dataset_id, file_name, status, file_size, chunk_count, domain, route_dataset, doc_type, content_type, complexity, pipeline, source_path)
            VALUES ('doc-1', 'ds-1', 'NTD/SP.docx', 'INDEXED', 2048, 12, 'NTD_FIRE', 'NTD_FIRE_Index', 'NORMATIVE', 'text', 'simple', 'markdown', '/ext/NTD/SP.docx')
            """
        )

    result = await datasets.list_documents(status="INDEXED", q="fire", _user=object())

    assert result["total"] == 1
    assert result["summary"]["INDEXED"] == {"files": 1, "chunks": 12}
    assert result["documents"][0]["dataset_name"] == "NTD_FIRE_Index"
    assert result["documents"][0]["file_name"] == "NTD/SP.docx"
    assert result["documents"][0]["route_dataset"] == "NTD_FIRE_Index"
    assert result["documents"][0]["chunk_count"] == 12
    assert result["documents"][0]["source_path"] == "/ext/NTD/SP.docx"


@pytest.mark.asyncio
async def test_list_sources_maps_folders_to_existing_datasets(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "RAG_Content" / "NTD" / "sub"
    source.mkdir(parents=True)
    (source / "doc.pdf").write_text("x")
    claude = tmp_path / "RAG_Content" / "CLAUDE"
    claude.mkdir()
    (claude / "conversations.json").write_text("{}", encoding="utf-8")
    uuid_like = tmp_path / "RAG_Content" / "123e4567-e89b-12d3-a456-426614174000"
    uuid_like.mkdir()
    (uuid_like / "skip.pdf").write_text("x")

    sources = await datasets.list_sources(_user=object())

    assert sources == [
        {
            "folder": "NTD",
            "source_files": 1,
            "dataset_id": "ds-1",
            "dataset_status": "IDLE",
            "indexed_files": 3,
            "chunk_count": 7,
        }
    ]


@pytest.mark.asyncio
async def test_retrieve_debug_returns_ranked_chunks_and_inferred_dataset(dataset_state):
    result = await datasets.retrieve_debug(
        datasets.RetrievalDebugRequest(question="ширина путей эвакуации"),
        _user=object(),
    )

    assert result["dataset_ids"] == ["ds-1"]
    assert result["query_route"]["dataset_filter"] == "NTD_FIRE"
    assert result["embedding"]["collection"]
    assert result["embedding"]["meta_db"]
    assert result["chunks"][0]["doc_name"] == "СП 3.13130.docx"
    assert result["chunks"][0]["doc_type"] == "NORMATIVE"


@pytest.mark.asyncio
async def test_search_returns_ranked_chunks_without_generation(dataset_state):
    result = await datasets.search(
        datasets.SearchRequest(query="ширина путей эвакуации", top_k=3, include_trace=True),
        _user=object(),
    )

    assert result["query"] == "ширина путей эвакуации"
    assert result["dataset_filter"] == "NTD_FIRE"
    assert result["dataset_ids"] == ["ds-1"]
    assert result["count"] == 1
    assert result["chunks"][0]["rank"] == 1
    assert result["chunks"][0]["doc_name"] == "СП 3.13130.docx"
    assert result["chunks"][0]["content"].startswith("ширина путей эвакуации")
    assert "СП 1.13130" in result["chunks"][0]["content"]
    assert result["chunks"][0]["metadata"]["doc_type"] == "NORMATIVE"
    assert result["retrieval_trace"]
    assert result["embedding"]["collection"]


@pytest.mark.asyncio
async def test_search_accepts_question_alias(dataset_state):
    result = await datasets.search(
        datasets.SearchRequest(question="ширина путей эвакуации", top_k=3),
        _user=object(),
    )

    assert result["query"] == "ширина путей эвакуации"
    assert result["chunks"][0]["doc_id"] == "doc-1"


@pytest.mark.asyncio
async def test_search_marks_explicit_dataset_filter(dataset_state):
    result = await datasets.search(
        datasets.SearchRequest(query="ширина путей эвакуации", dataset_filter="NTD", top_k=3),
        _user=object(),
    )

    assert result["dataset_filter"] == "NTD"
    assert result["route"]["reason"] == "explicit_filter"


@pytest.mark.asyncio
async def test_search_resolves_artel_filter_to_artel_index(dataset_state):
    dataset_state.datasets = [Dataset("artel", "ARTEL_Index", doc_count=1, chunk_count=1)]

    result = await datasets.search(
        datasets.SearchRequest(query="металлический шкаф управления ADSK_Наименование", dataset_filter="ARTEL", top_k=3),
        _user=object(),
    )

    assert result["dataset_filter"] == "ARTEL"
    assert result["dataset_ids"] == ["artel"]
    assert result["route"]["reason"] == "explicit_filter"


@pytest.mark.asyncio
async def test_search_requires_query_or_question(dataset_state):
    with pytest.raises(datasets.HTTPException) as exc:
        await datasets.search(datasets.SearchRequest(), _user=object())

    assert exc.value.status_code == 400
    assert "query or question" in exc.value.detail


@pytest.mark.asyncio
async def test_pending_parse_datasets_uses_priority_before_pending_count(dataset_state):
    dataset_state.datasets = [
        Dataset("other", "NTD_OTHER_Index"),
        Dataset("fire", "NTD_FIRE_Index"),
        Dataset("electrical", "NTD_ELECTRICAL_Index"),
    ]
    dataset_state.pending_files = {"other": 100, "fire": 1, "electrical": 5}

    queue = await datasets.pending_parse_datasets(datasets.get_dataset_state())

    assert [item["dataset_name"] for item in queue] == [
        "NTD_FIRE_Index",
        "NTD_ELECTRICAL_Index",
        "NTD_OTHER_Index",
    ]


@pytest.mark.asyncio
async def test_smart_plan_groups_files_by_document_route(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    (source / "fire.txt").write_text("СП 1.13130 пожарная безопасность эвакуация", encoding="utf-8")

    result = await datasets.smart_plan(_user=object())

    assert result["total_files"] == 1
    assert result["datasets"][0]["dataset"] == "NTD_FIRE_Index"
    assert result["rejected_total"] == 0


@pytest.mark.asyncio
async def test_sync_smart_registers_files_in_routed_datasets(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    (source / "pp87.txt").write_text("Постановление 87 градостроительный кодекс", encoding="utf-8")

    result = await datasets.sync_smart(datasets.SmartSyncRequest(), _admin=object())

    assert result["files"] == 1
    assert result["datasets"][0]["dataset_name"] == "GKRF_Index"
    assert dataset_state.uploads == [("ds-2", "pp87.txt", "mixed/pp87.txt")]


@pytest.mark.asyncio
async def test_folder_watch_status_reports_new_files(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    (source / "fire.txt").write_text("СП 1.13130 пожарная безопасность эвакуация", encoding="utf-8")

    result = await datasets.folder_watch_status(_user=object())

    assert result["status"] == "ok"
    assert result["counts"]["new"] == 1
    assert result["pending_changes"] == 1
    assert result["samples"][0]["state"] == "new"
    assert result["samples"][0]["relative_path"] == "mixed/fire.txt"
    assert result["samples"][0]["dataset_name"] == "NTD_FIRE_Index"


@pytest.mark.asyncio
async def test_folder_watch_status_marks_known_files_unchanged(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    file_path = source / "fire.txt"
    file_path.write_text("СП 1.13130 пожарная безопасность эвакуация", encoding="utf-8")
    stat = file_path.stat()
    with sqlite3.connect(data_dir / "les_meta.db") as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_mtime REAL,
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO datasets (id, name) VALUES ('ds-fire', 'NTD_FIRE_Index')")
        conn.execute(
            """
            INSERT INTO documents (id, dataset_id, file_name, status, file_mtime, file_size, chunk_count)
            VALUES ('doc-fire', 'ds-fire', 'mixed/fire.txt', 'INDEXED', ?, ?, 12)
            """,
            (stat.st_mtime, stat.st_size),
        )

    result = await datasets.folder_watch_status(_user=object())

    assert result["counts"] == {"new": 0, "changed": 0, "route_changed": 0, "unchanged": 1}
    assert result["pending_changes"] == 0
    assert result["samples"] == []


@pytest.mark.asyncio
async def test_folder_watch_status_accepts_legacy_basename_match(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    file_path = source / "fire.txt"
    file_path.write_text("СП 1.13130 пожарная безопасность эвакуация", encoding="utf-8")
    stat = file_path.stat()
    with sqlite3.connect(data_dir / "les_meta.db") as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_mtime REAL,
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO datasets (id, name) VALUES ('ds-fire', 'NTD_FIRE_Index')")
        conn.execute(
            """
            INSERT INTO documents (id, dataset_id, file_name, status, file_mtime, file_size)
            VALUES ('doc-fire', 'ds-fire', 'fire.txt', 'INDEXED', ?, ?)
            """,
            (stat.st_mtime, stat.st_size),
        )

    result = await datasets.folder_watch_status(_user=object())

    assert result["counts"] == {"new": 0, "changed": 0, "route_changed": 0, "unchanged": 1}
    assert result["samples"] == []


@pytest.mark.asyncio
async def test_folder_watch_status_reports_route_changed_files(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    file_path = source / "fire.txt"
    file_path.write_text("СП 1.13130 пожарная безопасность эвакуация", encoding="utf-8")
    stat = file_path.stat()
    with sqlite3.connect(data_dir / "les_meta.db") as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_mtime REAL,
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO datasets (id, name) VALUES ('ds-old', 'NTD_STRUCTURAL_Index')")
        conn.execute(
            """
            INSERT INTO documents (id, dataset_id, file_name, status, file_mtime, file_size)
            VALUES ('doc-fire', 'ds-old', 'mixed/fire.txt', 'INDEXED', ?, ?)
            """,
            (stat.st_mtime, stat.st_size),
        )

    result = await datasets.folder_watch_status(_user=object())

    assert result["counts"] == {"new": 0, "changed": 0, "route_changed": 1, "unchanged": 0}
    assert result["pending_changes"] == 1
    assert result["samples"][0]["state"] == "route_changed"
    assert result["samples"][0]["dataset_name"] == "NTD_FIRE_Index"
    assert result["samples"][0]["current"]["dataset_name"] == "NTD_STRUCTURAL_Index"


@pytest.mark.asyncio
async def test_folder_reindex_plan_groups_route_changed_files(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    file_path = source / "fire.txt"
    file_path.write_text("СП 1.13130 пожарная безопасность эвакуация", encoding="utf-8")
    stat = file_path.stat()
    with sqlite3.connect(data_dir / "les_meta.db") as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_mtime REAL,
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO datasets (id, name) VALUES ('ds-old', 'NTD_STRUCTURAL_Index')")
        conn.execute(
            """
            INSERT INTO documents (id, dataset_id, file_name, status, file_mtime, file_size, chunk_count)
            VALUES ('doc-fire', 'ds-old', 'mixed/fire.txt', 'INDEXED', ?, ?, 9)
            """,
            (stat.st_mtime, stat.st_size),
        )

    result = await datasets.folder_reindex_plan(_user=object())

    assert result["pending_route_changes"] == 1
    assert result["apply_supported"] is False
    assert result["groups"][0]["current_dataset_name"] == "NTD_STRUCTURAL_Index"
    assert result["groups"][0]["target_dataset_name"] == "NTD_FIRE_Index"
    assert result["groups"][0]["files"] == 1
    assert result["samples"][0]["current_doc_id"] == "doc-fire"
    assert result["samples"][0]["current_chunk_count"] == 9


@pytest.mark.asyncio
async def test_folder_watch_scan_registers_without_parsing(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    (source / "pp87.txt").write_text("Постановление 87 градостроительный кодекс", encoding="utf-8")

    result = await datasets.folder_watch_scan(datasets.FolderWatchRequest(), _admin=object())

    assert result["status"] == "registered"
    assert result["before"]["pending_changes"] == 1
    assert result["sync"]["files"] == 1
    assert result["sync"]["parse_started"] is False
    assert dataset_state.uploads == [("ds-2", "pp87.txt", "mixed/pp87.txt")]
    assert dataset_state.parses == []


@pytest.mark.asyncio
async def test_folder_watch_scan_skips_unchanged_files(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    indexed_file = source / "indexed_fire.txt"
    new_file = source / "new_fire.txt"
    indexed_file.write_text("СП 1.13130 пожарная безопасность эвакуация", encoding="utf-8")
    new_file.write_text("СП 2.13130 пожарная безопасность огнестойкость", encoding="utf-8")
    stat = indexed_file.stat()
    with sqlite3.connect(data_dir / "les_meta.db") as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_mtime REAL,
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO datasets (id, name) VALUES ('ds-fire', 'NTD_FIRE_Index')")
        conn.execute(
            """
            INSERT INTO documents (id, dataset_id, file_name, status, file_mtime, file_size)
            VALUES ('doc-fire', 'ds-fire', 'mixed/indexed_fire.txt', 'INDEXED', ?, ?)
            """,
            (stat.st_mtime, stat.st_size),
        )

    result = await datasets.folder_watch_scan(datasets.FolderWatchRequest(), _admin=object())

    assert result["before"]["counts"] == {"new": 1, "changed": 0, "route_changed": 0, "unchanged": 1}
    assert result["sync"]["files"] == 1
    assert result["sync"]["skipped_route_changed"] == 0
    assert dataset_state.uploads == [("ds-2", "new_fire.txt", "mixed/new_fire.txt")]


@pytest.mark.asyncio
async def test_folder_watch_scan_skips_route_changed_files(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = tmp_path / "RAG_Content" / "mixed"
    source.mkdir(parents=True)
    file_path = source / "fire.txt"
    file_path.write_text("СП 1.13130 пожарная безопасность эвакуация", encoding="utf-8")
    stat = file_path.stat()
    with sqlite3.connect(data_dir / "les_meta.db") as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_mtime REAL,
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO datasets (id, name) VALUES ('ds-old', 'NTD_STRUCTURAL_Index')")
        conn.execute(
            """
            INSERT INTO documents (id, dataset_id, file_name, status, file_mtime, file_size)
            VALUES ('doc-fire', 'ds-old', 'mixed/fire.txt', 'INDEXED', ?, ?)
            """,
            (stat.st_mtime, stat.st_size),
        )

    result = await datasets.folder_watch_scan(datasets.FolderWatchRequest(), _admin=object())

    assert result["before"]["counts"] == {"new": 0, "changed": 0, "route_changed": 1, "unchanged": 0}
    assert result["sync"]["files"] == 0
    assert result["sync"]["skipped_route_changed"] == 1
    assert dataset_state.uploads == []


@pytest.mark.asyncio
async def test_folder_watch_rejects_unsafe_source_root(dataset_state):
    with pytest.raises(datasets.HTTPException) as exc:
        await datasets.folder_watch_status(source_root="../RAG_Content", _user=object())

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_sync_folder_rejects_claude_source(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "RAG_Content" / "CLAUDE"
    source.mkdir(parents=True)
    (source / "conversations.json").write_text("{}", encoding="utf-8")

    with pytest.raises(datasets.HTTPException) as exc:
        await datasets.sync_folder("CLAUDE", _admin=object())

    assert exc.value.status_code == 400
    assert dataset_state.uploads == []


@pytest.mark.asyncio
async def test_sync_folder_filters_unsupported_files(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    async def _admit(state, **kwargs):
        return None

    monkeypatch.setattr(datasets, "assert_parse_admission", _admit)
    source = tmp_path / "RAG_Content" / "NTD"
    source.mkdir(parents=True)
    (source / ".DS_Store").write_text("noise")
    (source / "doc.txt").write_text("СП 1.13130 пожарная безопасность", encoding="utf-8")

    result = await datasets.sync_folder("NTD", _admin=object())

    assert result["new_files"] == 1
    assert result["rejected_files"] == 1
    assert result["rejected_reasons"] == {"unsupported_suffix": 1}
    assert dataset_state.uploads == [("ds-1", "doc.txt", "doc.txt")]


@pytest.mark.asyncio
async def test_upload_smart_routes_file_to_classified_dataset(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "storage" / "datasets").mkdir(parents=True)

    result = await datasets.upload_file_smart(
        file=_upload(
            "local_smeta.csv",
            (
                "№,Наименование работ,Ед.изм.,Кол-во,Цена,Сумма\n"
                "1,Монтаж кабеля,м,12,100,1200\n"
            ).encode("utf-8"),
        ),
        parse=False,
        _admin=object(),
    )

    assert result["status"] == "registered"
    assert result["dataset_name"] == "TABLE_SMETA_Index"
    assert result["dataset_created"] is True
    assert result["route"]["doc_type"] == "SMETA"
    assert result["route"]["pipeline"] == "parquet"
    assert result["intake"]["file_name"] == "local_smeta.csv"
    assert dataset_state.uploads[0][0] == "ds-2"
    assert dataset_state.uploads[0][1].endswith("_local_smeta.csv")
    assert dataset_state.uploads[0][2] == "local_smeta.csv"


@pytest.mark.asyncio
async def test_attach_read_returns_text_context(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)
    result = await datasets.attach_chat_file(
        file=_upload("note.txt", "Прочитай меня как задание".encode("utf-8")),
        mode="read",
        _admin=object(),
    )

    assert result["mode"] == "read"
    assert result["name"] == "note.txt"
    assert "Прочитай меня" in result["text"]
    assert result["attachment_id"].startswith("read_")
    assert dataset_state.uploads == []


@pytest.mark.asyncio
async def test_attach_read_converter_error_is_controlled(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)

    def broken_converter(_path):
        raise ValueError("битый файл")

    import backend.converter

    monkeypatch.setattr(backend.converter, "convert_to_markdown", broken_converter)

    with pytest.raises(datasets.HTTPException) as exc:
        await datasets.attach_chat_file(
            file=_upload("broken.txt", b"not really readable"),
            mode="read",
            _admin=object(),
        )

    assert exc.value.status_code == 422
    assert "Не удалось прочитать файл" in exc.value.detail
    assert "broken.txt" in exc.value.detail
    assert dataset_state.uploads == []


@pytest.mark.asyncio
async def test_upload_smart_rejects_empty_file(tmp_path, monkeypatch, dataset_state):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(datasets.HTTPException) as exc:
        await datasets.upload_file_smart(file=_upload("empty.txt", b""), parse=False, _admin=object())

    assert exc.value.status_code == 400
    assert dataset_state.uploads == []


@pytest.mark.asyncio
async def test_parse_scheduler_runs_pending_batches(monkeypatch, dataset_state):
    dataset_state.pending_files["ds-1"] = 3

    async def _admit(state, **kwargs):
        return None

    unloads = []

    async def _unload():
        unloads.append(True)
        return {"ok": True}

    async def _memory():
        return {"ram_free_gb": 16.0, "swap_pct": 0.0, "raw": {}}

    monkeypatch.setattr(datasets, "assert_parse_admission", _admit)
    monkeypatch.setattr(datasets, "parse_memory_state", _memory)
    monkeypatch.setattr(datasets, "unload_mlx_models", _unload)

    result = await datasets.parse_scheduler(
        datasets.ParseSchedulerRequest(
            batch_limit=2,
            max_batches=3,
            cooldown_sec=0,
            unload_before_start=False,
            background=False,
        ),
        _admin=object(),
    )

    assert result["status"] == "completed"
    assert result["batches_run"] == 2
    assert result["remaining_pending"] == 0
    assert result["stop_reason"] == ""
    assert dataset_state.parses == [("ds-1", 2), ("ds-1", 2)]
    assert len(unloads) == 2


@pytest.mark.asyncio
async def test_parse_scheduler_background_rejects_before_queueing(monkeypatch, dataset_state):
    async def _reject(state, **kwargs):
        raise datasets.HTTPException(status_code=503, detail="Qdrant is not healthy")

    monkeypatch.setattr(datasets, "assert_parse_admission", _reject)

    with pytest.raises(datasets.HTTPException) as exc:
        await datasets.parse_scheduler(
            datasets.ParseSchedulerRequest(background=True),
            _admin=object(),
        )

    assert exc.value.status_code == 503
    assert datasets.get_dataset_state().job_tracker == {}
    assert dataset_state.parses == []


@pytest.mark.asyncio
async def test_parse_scheduler_rejects_duplicate_active_job(monkeypatch, dataset_state):
    state = datasets.get_dataset_state()
    state.job_tracker["active-job"] = {
        "type": "rag_parse_scheduler",
        "status": "PARSING",
        "message": "Batch 1/25: NTD pending=10",
    }

    async def _admit(*args, **kwargs):
        pytest.fail("duplicate scheduler should be rejected before admission")

    monkeypatch.setattr(datasets, "assert_parse_admission", _admit)

    with pytest.raises(datasets.HTTPException) as exc:
        await datasets.parse_scheduler(
            datasets.ParseSchedulerRequest(background=True),
            _admin=object(),
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_parse_scheduler_passes_request_memory_guard(monkeypatch, dataset_state):
    dataset_state.pending_files["ds-1"] = 1
    seen = {}

    async def _admit(state, *, min_free_gb, max_swap_pct):
        seen["min_free_gb"] = min_free_gb
        seen["max_swap_pct"] = max_swap_pct

    async def _memory():
        return {"ram_free_gb": 16.0, "swap_pct": 0.0, "raw": {}}

    monkeypatch.setattr(datasets, "assert_parse_admission", _admit)
    monkeypatch.setattr(datasets, "parse_memory_state", _memory)
    monkeypatch.setattr(datasets, "unload_mlx_models", lambda: None)

    result = await datasets.parse_scheduler(
        datasets.ParseSchedulerRequest(
            batch_limit=1,
            max_batches=1,
            cooldown_sec=0,
            unload_before_start=False,
            min_free_gb=4,
            max_swap_pct=75,
            unload_between_batches=False,
            background=False,
        ),
        _admin=object(),
    )

    assert result["status"] == "completed"
    assert seen == {"min_free_gb": 4.0, "max_swap_pct": 75.0}


@pytest.mark.asyncio
async def test_parse_scheduler_stops_after_batch_when_swap_rises(monkeypatch, dataset_state):
    dataset_state.pending_files["ds-1"] = 3

    async def _admit(state, **kwargs):
        return None

    async def _memory():
        return {"ram_free_gb": 16.0, "swap_pct": 80.0, "raw": {}}

    monkeypatch.setattr(datasets, "assert_parse_admission", _admit)
    monkeypatch.setattr(datasets, "parse_memory_state", _memory)
    monkeypatch.setattr(datasets, "unload_mlx_models", lambda: {"ok": True})

    result = await datasets.parse_scheduler(
        datasets.ParseSchedulerRequest(
            batch_limit=1,
            max_batches=3,
            cooldown_sec=0,
            unload_before_start=False,
            unload_between_batches=False,
            post_batch_max_swap_pct=60,
            background=False,
        ),
        _admin=object(),
    )

    assert result["batches_run"] == 1
    assert result["remaining_pending"] == 2
    assert "post-batch memory guard: swap_pct=80.0 > 60.0" == result["stop_reason"]


@pytest.mark.asyncio
async def test_parse_scheduler_warm_embedder_skips_between_batch_unload(monkeypatch, dataset_state):
    dataset_state.pending_files["ds-1"] = 1
    unloads = []

    async def _admit(state, **kwargs):
        return None

    async def _memory():
        return {"ram_free_gb": 16.0, "swap_pct": 0.0, "raw": {}}

    async def _unload():
        unloads.append(True)
        return {"ok": True}

    monkeypatch.setattr(datasets, "assert_parse_admission", _admit)
    monkeypatch.setattr(datasets, "parse_memory_state", _memory)
    monkeypatch.setattr(datasets, "unload_mlx_models", _unload)

    result = await datasets.parse_scheduler(
        datasets.ParseSchedulerRequest(
            batch_limit=1,
            max_batches=1,
            cooldown_sec=0,
            unload_before_start=False,
            unload_between_batches=True,
            warm_embedder=True,
            unload_after_finish=True,
            background=False,
        ),
        _admin=object(),
    )

    assert result["batches_run"] == 1
    assert "unload" not in result["batches"][0]
    assert result["final_unload"] == {"ok": True}
    assert len(unloads) == 1
