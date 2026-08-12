"""Chat routes VOR-from-spec through deterministic spec_to_bor, not attachment LLM."""

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
async def test_chat_vor_from_attachment_is_deterministic(tmp_path, monkeypatch):
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

    assert resp["crag_status"] == "DETERMINISTIC"
    assert resp["query_route"]["channel"] == "spec_to_bor"
    assert "ВОР из спецификации" in resp["answer"]
    assert "работ" in resp["answer"]
    artifact = resp.get("artifact") or {}
    assert artifact.get("stage") == "vor_from_spec"
    assert "xlsx" in (artifact.get("downloads") or {})
    assert "цена" not in resp["answer"].lower()
    assert "отгрузки" not in resp["answer"].lower()


@pytest.mark.asyncio
async def test_chat_vor_without_attachment_id_errors(tmp_path, monkeypatch):
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
    assert resp["crag_status"] == "ERROR"
    assert resp["query_route"]["channel"] == "spec_to_bor"
    assert "read_" in resp["answer"] or "В чат" in resp["answer"]


@pytest.mark.asyncio
async def test_chat_lsr_from_vor_pdf_does_not_hijack_spec_to_bor(tmp_path, monkeypatch):
    """«Собери ЛСР по ВОР.pdf» → document LSR, not XLSX-only spec→VOR."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta_qwen.db"))
    artifact_dir = tmp_path / "storage" / "smeta_artifacts"
    artifact_dir.mkdir(parents=True)
    monkeypatch.setattr(chat_router, "_SMETA_ARTIFACT_DIR", artifact_dir)
    _mock_chat_state()

    async def fail_attachment_mode(*_a, **_k):
        raise AssertionError("attachment LLM must not run for document LSR")

    async def fake_document_lsr(**kwargs):
        assert kwargs.get("attachment_id") == "read_abcdef123456"
        assert "ЛСР" in str(kwargs.get("user_request") or "")
        return SimpleNamespace(
            answer="ЛСР по PDF-ВОР запущена",
            operation="smeta_document_lsr",
            channel="smeta_mode",
            crag="OK",
            extra={"retrieval_trace": {"mode": "smeta_document", "source": "pdf"}},
        )

    monkeypatch.setattr(chat_router, "_run_attachment_mode", fail_attachment_mode)
    monkeypatch.setattr(chat_router, "run_smeta_document_application", fake_document_lsr)

    resp = await chat_router.chat(
        chat_router.ChatRequest(
            question="Собери первую ЛСР по приложенной ВОР",
            mode="auto",
            attachment_id="read_abcdef123456",
            attachment_context="Файл: ВОР монтаж БАП П1 13.05 (2).pdf\n\n[document attachment preserved]",
        ),
        _user=object(),
    )

    assert resp["answer"] == "ЛСР по PDF-ВОР запущена"
    assert resp["query_route"]["channel"] == "smeta_mode"
    assert resp["query_route"]["operation"] == "smeta_document_lsr"
    assert "XLSX" not in resp["answer"]
    assert "спецификац" not in resp["answer"].lower()


@pytest.mark.asyncio
async def test_chat_vor_from_pdf_spec_is_deterministic(tmp_path, monkeypatch):
    """«ВОР из спецификации» accepts PDF the same as XLSX."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta_qwen.db"))
    attach_root = tmp_path / "storage" / "chat_attachments"
    artifact_dir = tmp_path / "storage" / "smeta_artifacts"
    artifact_dir.mkdir(parents=True)
    monkeypatch.setattr(chat_router, "_SMETA_ARTIFACT_DIR", artifact_dir)

    src = tmp_path / "spec.pdf"
    src.write_bytes(b"%PDF-1.4 placeholder")
    meta = preserve_read_attachment(
        src,
        attachment_id="read_abcdef123456",
        original_name="Спецификация Ф9.pdf",
        root=attach_root,
    )
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attach_root))

    async def fail_attachment_mode(*_a, **_k):
        raise AssertionError("attachment LLM must not run for VOR-from-spec PDF")

    def fake_rows(path, *, source_label=""):
        assert Path(path).suffix.lower() == ".pdf"
        return [
            {
                "doc_type": "SPEC",
                "name": "Кабель КПСнг(А)-FRLS",
                "unit": "м",
                "qty": 100.0,
                "section": "ЛВЖ",
                "code": "",
                "mark": "",
                "pos": "1",
                "source_file": source_label,
            }
        ]

    _mock_chat_state()
    monkeypatch.setattr(chat_router, "_run_attachment_mode", fail_attachment_mode)
    import proxy.services.spec_to_bor_service as bor_svc

    monkeypatch.setattr(bor_svc, "rows_from_spec_document", fake_rows)

    resp = await chat_router.chat(
        chat_router.ChatRequest(
            question="сделай ВОР из спецификации",
            mode="auto",
            attachment_id=meta["attachment_id"],
            attachment_context=f"Файл: {meta['original_name']}\n\n",
        ),
        _user=object(),
    )

    assert resp["crag_status"] == "DETERMINISTIC"
    assert resp["query_route"]["channel"] == "spec_to_bor"
    assert "unsupported" not in (resp.get("retrieval_trace") or {}).get("error", "")
    assert "XLSX/XLSM, сейчас вложение .pdf" not in resp["answer"]
    assert "работ" in resp["answer"].lower() or "вор" in resp["answer"].lower()
