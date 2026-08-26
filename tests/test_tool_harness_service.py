import hashlib
import os
import sqlite3
import time
from types import SimpleNamespace

import pytest

from proxy.routers import tools as tools_router
from proxy.services import tool_harness_service
from proxy.services.document_explorer_service import DocumentExplorer
from proxy.services.lexical_index_service import LexicalIndex, content_hash
from proxy.services.tool_harness_service import ToolHarness


def _seed_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        LexicalIndex.ensure_schema(conn)
        conn.execute(
            """
            CREATE TABLE datasets (
                id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT,
                chunk_count INTEGER DEFAULT 0
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
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                doc_type TEXT DEFAULT '',
                content_type TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                source_path TEXT DEFAULT '',
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO datasets VALUES (?, ?, ?, ?)", ("bai", "BAI", "IDLE", 3))
        docs = [
            ("doc-pdf", "bai", "IOS/ИОС 5.2 пожарная сигнализация.pdf", "INDEXED", 1000, 2, "project", "pdf", "BAI", "/src/fire.pdf", ""),
            ("doc-xlsx", "bai", "Smeta/Ведомость.xlsx", "INDEXED", 900, 1, "table", "xlsx", "BAI", "/src/ved.xlsx", ""),
        ]
        conn.executemany("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", docs)
        chunks = [
            ("p1", "bai", "doc-pdf", "IOS/ИОС 5.2 пожарная сигнализация.pdf", "Система пожарной сигнализации выполняется адресной.", 1),
            ("p2", "bai", "doc-pdf", "IOS/ИОС 5.2 пожарная сигнализация.pdf", "Автоматика управляет оповещением и инженерными системами.", 2),
            ("x1", "bai", "doc-xlsx", "Smeta/Ведомость.xlsx", "Лист 1. Кабель КПСЭнг 120 м.", 1),
        ]
        conn.executemany(
            """
            INSERT INTO lexical_chunks
                (collection, point_id, dataset_id, doc_id, doc_name, text, content_hash, chunk_ord, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("les_test", point, dataset_id, doc_id, doc_name, text, content_hash(text), ord_, time.time())
                for point, dataset_id, doc_id, doc_name, text, ord_ in chunks
            ],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def explorer(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)
    return DocumentExplorer(db_path=str(db), collection="les_test")


def test_tool_registry_is_typed_and_read_only_first():
    registry = ToolHarness().registry()

    names = {tool["name"] for tool in registry["tools"]}
    assert {
        "dataset_map", "search_sources", "read_source", "filesystem_list", "filesystem_read_text",
        "search_project_tables", "read_project_table", "assemble_project_volume", "look_at_pdf_page",
    } <= names
    assert all(tool["side_effects"] == "none" for tool in registry["tools"])
    assert all(tool["effect"] == "read" for tool in registry["tools"])
    assert all(tool["result_schema"] == "les_tool_result_v1" for tool in registry["tools"])
    assert all(tool["input_schema"]["type"] == "object" for tool in registry["tools"])
    search_schema = next(tool for tool in registry["tools"] if tool["name"] == "search_sources")["input_schema"]
    assert search_schema["properties"]["dataset_ids"]["type"] == "array"
    assert search_schema["properties"]["limit"]["type"] == "integer"
    assert search_schema["additionalProperties"] is False
    assert registry["policy"]["tools_return_evidence_not_final_domain_answers"] is True


def test_tool_shortlist_delegates_policy_without_domain_word_routing():
    harness = ToolHarness()
    allowed = ["dataset_map", "web_search", "filesystem_search"]

    first = harness.shortlist("котельная", allowed_tools=allowed, limit=5)
    second = harness.shortlist("пожарная сигнализация", allowed_tools=allowed, limit=5)

    assert [item["name"] for item in first["tools"]] == allowed
    assert [item["name"] for item in second["tools"]] == allowed
    assert first["omitted_by_reason"] == second["omitted_by_reason"]
    assert first["preset"] == "qwen-9b"
    assert first["budget"]["calls"] == 5


def test_tool_search_sources_returns_evidence_packet(monkeypatch, explorer):
    monkeypatch.setattr(tool_harness_service, "explorer", lambda: explorer)

    payload = ToolHarness().call("search_sources", {"q": "пожарной сигнализации", "dataset_ids": ["bai"]})

    assert payload["schema"] == "les_tool_result_v1"
    assert payload["status"] == "ok"
    assert payload["contract_check"]["ok"] is True
    assert payload["sources"][0]["doc_name"] == "IOS/ИОС 5.2 пожарная сигнализация.pdf"
    assert payload["decision_required_from_model"] is True
    assert payload["spec"]["name"] == "search_sources"
    assert payload["execution"]["schema"] == "les_tool_execution_v1"


def test_tool_read_pdf_and_excel_are_indexed_readers_with_limits(monkeypatch, explorer):
    monkeypatch.setattr(tool_harness_service, "explorer", lambda: explorer)
    h = ToolHarness()

    pdf_payload = h.call("read_pdf_source", {"doc_id": "doc-pdf"})
    xlsx_payload = h.call("read_excel_source", {"doc_id": "doc-xlsx"})

    assert pdf_payload["status"] == "ok"
    assert any("raw PDF" in warning for warning in pdf_payload["warnings"])
    assert xlsx_payload["status"] == "ok"
    assert any("sheet/range" in warning for warning in xlsx_payload["warnings"])


def test_look_at_pdf_page_resolves_visible_basename_and_uses_vision_model(monkeypatch, explorer, tmp_path):
    import fitz
    import httpx

    pdf_path = tmp_path / "ИОС 5.2 пожарная сигнализация.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "VISUAL PAGE")
        pdf.save(pdf_path)
    with sqlite3.connect(explorer.db_path) as conn:
        conn.execute("UPDATE documents SET source_path=? WHERE id='doc-pdf'", (str(pdf_path),))
        conn.commit()

    monkeypatch.setattr(tool_harness_service, "explorer", lambda: explorer)
    monkeypatch.setenv("RAG_OCR_MODEL", "gemma4:12b")

    def fake_post(url, *, json, timeout):
        assert url.endswith("/api/chat")
        assert json["model"] == "gemma4:12b"
        assert json["messages"][0]["images"]
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"message": {"content": "На листе видна надпись VISUAL PAGE."}},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    payload = ToolHarness().call(
        "look_at_pdf_page",
        {"dataset_id": "bai", "doc_name": pdf_path.name, "page": 1, "question": "Что видно?"},
    )

    assert payload["status"] == "ok"
    assert "На листе видна надпись VISUAL PAGE." in payload["result"]["observation"]
    assert payload["result"]["source_ref"].endswith("#page=1")


def test_filesystem_tool_is_whitelisted_read_only(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    file_path = root / "guide.md"
    file_path.write_text("BAI fire automation source guide", encoding="utf-8")
    monkeypatch.setenv("LES_TOOL_FS_EXTRA_ROOTS", f"fixture={root}")

    h = ToolHarness()
    listed = h.call("filesystem_list", {"root": "fixture", "depth": 1})
    read = h.call("filesystem_read_text", {"root": "fixture", "path": "guide.md"})
    found = h.call("filesystem_search", {"root": "fixture", "q": "automation", "content": True})
    hashed = h.call("filesystem_hash", {"root": "fixture", "path": "guide.md"})
    escaped = h.call("filesystem_stat", {"root": "fixture", "path": "../guide.md"})

    assert listed["status"] == "ok"
    assert listed["result"]["children"][0]["name"] == "guide.md"
    assert read["result"]["text"] == "BAI fire automation source guide"
    assert found["result"]["hits"][0]["match"] == "content"
    assert hashed["result"]["sha256"] == hashlib.sha256(file_path.read_bytes()).hexdigest()
    assert escaped["status"] == "error"


@pytest.mark.asyncio
async def test_tools_router_calls_harness(monkeypatch, explorer):
    monkeypatch.setattr(tool_harness_service, "explorer", lambda: explorer)
    monkeypatch.setattr(tools_router, "_executor", lambda: ToolHarness()._executor)

    result = await tools_router.tool_call(
        tools_router.ToolCallRequest(tool="search_sources", args={"q": "автоматика", "dataset_ids": ["bai"]}),
        _admin=object(),
    )

    assert result["status"] == "ok"
    assert result["tool"] == "search_sources"
