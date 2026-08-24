"""Ordinary profiles do not let deterministic spec_to_bor hijack the model."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from proxy.routers import chat as chat_router
from proxy.services.chat_attachment_service import preserve_read_attachment


def _mock_chat_state() -> None:
    class _Backend:
        async def list_datasets(self):
            raise AssertionError("retrieval must not run for spec_to_bor")

        async def retrieve(self, *a, **k):
            raise AssertionError("retrieve must not run for spec_to_bor")

    chat_router.set_chat_state(
        chat_router.ChatRouterState(
            rag_backend=_Backend(),
            llm_semaphore=SimpleNamespace(_value=1),
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            chat_metrics={
                "latency_search": [],
                "latency_gen": [],
                "tokens": [],
                "crag_pass": 0,
                "crag_fail": 0,
            },
            reranker_available=False,
            reranker_cls=None,
            current_mode={"mode": "chat"},
        )
    )


def _write_spec_xlsx(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Раздел", "Наименование", "Артикул", "Ед. изм.", "Кол-во ФАКТ"])
    ws.append(["ЛВЖ", "Кабель КПСнг(А)-FRLS", "x", "м.", 100])
    ws.append(["Компрессор", "Лоток глухой 200*50*3000", "35024", "м.", 33])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


@pytest.mark.asyncio
async def test_chat_vor_from_attachment_stays_in_selected_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta_qwen.db"))
    attach_root = tmp_path / "storage" / "chat_attachments"
    artifact_dir = tmp_path / "storage" / "smeta_artifacts"
    artifact_dir.mkdir(parents=True)
    monkeypatch.setattr(chat_router, "_SMETA_ARTIFACT_DIR", artifact_dir)

    src = tmp_path / "kamenka.xlsx"
    _write_spec_xlsx(src)
    meta = preserve_read_attachment(
        src,
        attachment_id="read_abcdef123456",
        original_name="Общая по Каменке.xlsx",
        root=attach_root,
    )
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attach_root))

    async def fail_attachment_mode(*_a, **_k):
        raise AssertionError("attachment LLM must not run for VOR-from-spec")

    _mock_chat_state()
    monkeypatch.setattr(chat_router, "_run_attachment_mode", fail_attachment_mode)

    resp = await chat_router.chat(
        chat_router.ChatRequest(
            question="сделай ВОР из спецификации",
            mode="auto",
            attachment_id=meta["attachment_id"],
            attachment_context=f"Файл: {meta['original_name']}\n\nРаздел|Наименование|...",
        ),
        _user=object(),
    )

    assert resp["crag_status"] != "DETERMINISTIC"
    assert resp["query_route"]["channel"] != "spec_to_bor"
    assert resp["query_route"]["profile"]["profile_id"] == "agent"


@pytest.mark.asyncio
async def test_chat_vor_without_attachment_id_is_not_claimed_by_spec_handler(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta_qwen.db"))
    _mock_chat_state()

    async def fail_attachment_mode(*_a, **_k):
        raise AssertionError("must not fall through to attachment LLM")

    monkeypatch.setattr(chat_router, "_run_attachment_mode", fail_attachment_mode)
    resp = await chat_router.chat(
        chat_router.ChatRequest(
            question="Собери ВОР в разрезе ЛВЖ",
            mode="auto",
            attachment_context="Файл: Общая по Каменке.xlsx\n\nстроки...",
        ),
        _user=object(),
    )
    assert resp["query_route"]["channel"] != "spec_to_bor"
    assert resp["query_route"]["profile"]["profile_id"] == "agent"
