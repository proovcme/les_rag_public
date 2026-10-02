import inspect

import pytest

from sovushka.pages import documents as documents_module
from sovushka.pages.documents import build_documents


def test_data_detail_accepts_explicit_dataset_and_hides_duplicate_picker():
    signature = inspect.signature(build_documents)
    assert "initial_dataset_id" in signature.parameters
    assert "show_dataset_picker" in signature.parameters
    assert "can_manage" in signature.parameters

    source = inspect.getsource(build_documents)
    assert 'surface not in {"documents", "data", "studio", "cad_bim"}' in source
    assert "initial_dataset = str(initial_dataset_id or \"\").strip()" in source
    assert "datasets_column.set_visibility(show_dataset_picker" in source
    assert '"Назад ко всем данным"' in source
    assert "sov-data-detail--focused" in source


def test_data_detail_keeps_chat_scope_exact_and_mutations_role_gated():
    source = inspect.getsource(build_documents)
    assert '"scope": f"ds:{dataset_id}"' in source
    assert '"target_file": file_name' in source
    assert "_is_system_dataset() and can_manage" in source
    assert "if can_manage and not _is_system_dataset(row):" in source


@pytest.mark.parametrize(
    ("status", "chunk_count", "availability"),
    [
        ("INDEXED", 2, "есть в RAG"),
        ("INDEXED", 0, "не готов для RAG"),
        ("INDEXED", None, "не готов для RAG"),
        ("ERROR", 2, "не готов для RAG"),
        ("PENDING", 2, "не готов для RAG"),
    ],
)
def test_document_rag_availability_requires_indexed_searchable_chunks(monkeypatch, status, chunk_count, availability):
    rendered = []

    class Label:
        def classes(self, value):
            assert value == "sov-document-meta-text"

    def label(text, **_kwargs):
        rendered.append(text)
        return Label()

    monkeypatch.setattr(documents_module, "render_feedback_state", lambda *_args, **_kwargs: pytest.fail("Unexpected error"))

    documents_module._render_document_rag_metadata(
        {"status": status, "chunk_count": chunk_count},
        ["PDF", "12 КБ"],
        label,
    )

    assert rendered == [f"PDF  ·  12 КБ  ·  {availability}"]


@pytest.mark.parametrize(
    ("last_error", "error_code", "detail"),
    [
        (
            "Не найден текст для поиска. Проверьте исходный файл и преобразование документа.",
            "NO_SEARCHABLE_CONTENT",
            "Не найден текст для поиска. Проверьте исходный файл и преобразование документа.",
        ),
        ("Не удалось прочитать файл.", "", "Не удалось прочитать файл."),
        (
            "",
            "NO_SEARCHABLE_CONTENT",
            "Индексация документа не завершена. Проверьте исходный файл и технический код ошибки.",
        ),
    ],
)
def test_document_rag_metadata_shows_recorded_nonretryable_indexing_reason(monkeypatch, last_error, error_code, detail):
    feedback = []
    rendered = []

    class Label:
        def classes(self, _value):
            return self

    def label(text, **_kwargs):
        rendered.append(text)
        return Label()

    monkeypatch.setattr(
        documents_module,
        "render_feedback_state",
        lambda kind, **kwargs: feedback.append({"kind": kind, **kwargs}),
    )
    documents_module._render_document_rag_metadata(
        {"status": "ERROR", "chunk_count": 0, "last_error": last_error, "error_code": error_code},
        ["PDF", "12 КБ"],
        label,
    )

    assert rendered == ["PDF  ·  12 КБ  ·  не готов для RAG"]
    assert feedback == [{"kind": "error", "detail": detail, "error_code": error_code}]


@pytest.mark.parametrize(
    ("status", "chunk_count", "ready"),
    [("INDEXED", 0, False), ("INDEXED", 2, True), ("ERROR", 0, False)],
)
def test_fallback_composition_preserves_availability_and_renders_failure(monkeypatch, status, chunk_count, ready):
    reason = "Проверьте исходный файл и текстовый слой вручную." if status == "ERROR" else ""
    error_code = "NO_SEARCHABLE_CONTENT" if reason else ""
    row = {
        "id": "doc-1", "file_name": "Вход с пробелом.pdf", "status": status,
        "chunk_count": chunk_count, "last_error": reason, "error_code": error_code,
    }
    item = documents_module._composition_file(row)
    assert item == documents_module._composition_file(row, documents_module._document_source_map_file(row))
    assert item["status"] == ("ok" if ready else status)
    assert item["rag_ready"] is ready
    assert item["chunk_count"] == chunk_count
    assert item["last_error"] == reason
    assert item["error_code"] == error_code
    assert documents_module._source_map_file_ready(item) is ready

    rendered, feedback, classes = [], [], []

    class Label:
        def classes(self, value):
            classes.append(value)
            return self

    def label(text, **_kwargs):
        rendered.append(text)
        return Label()

    monkeypatch.setattr(
        documents_module, "render_feedback_state",
        lambda kind, **kwargs: feedback.append({"kind": kind, **kwargs}),
    )

    documents_module._render_document_rag_metadata(item, ["PDF", "12 КБ"], label, classes="sov-composition-file-path")

    availability = "есть в RAG" if ready else "не готов для RAG"
    assert rendered == [f"PDF  ·  12 КБ  ·  {availability}"]
    assert classes == ["sov-composition-file-path"]
    assert feedback == ([{"kind": "error", "detail": reason, "error_code": error_code}] if reason else [])


@pytest.mark.parametrize("status", ["ok", "IDLE"])
def test_pdf_sidecar_readiness_keeps_its_existing_status_semantics(status):
    sidecar = {"status": status, "chunk_count": 0}
    item = documents_module._composition_file({"status": "INDEXED", "chunk_count": 0}, sidecar)

    assert documents_module._source_map_file_ready(item) is True
    assert "rag_ready" not in item


def test_composition_readiness_honors_explicit_false_even_for_ok_status():
    assert documents_module._source_map_file_ready({"status": "ok", "chunk_count": 2, "rag_ready": False}) is False


@pytest.mark.parametrize("sidecar_status", ["ok", "IDLE"])
def test_existing_pdf_sidecar_preserves_current_ingest_failure(monkeypatch, sidecar_status):
    row = {"file_name": "Чертёж.pdf", "status": "ERROR", "chunk_count": 0,
           "last_error": "Нет извлечённого текста: проверьте документ",
           "error_code": "NO_SEARCHABLE_CONTENT"}
    item = documents_module._composition_file(row, {"status": sidecar_status, "chunk_count": 0})
    assert item["status"] == sidecar_status
    assert "rag_ready" not in item
    assert documents_module._source_map_file_ready(item) is True
    feedback = []
    monkeypatch.setattr(documents_module, "render_feedback_state",
                        lambda kind, **kwargs: feedback.append({"kind": kind, **kwargs}))
    documents_module._render_document_ingest_error(item["document_ingest_error"])
    assert feedback == [{"kind": "error", "detail": row["last_error"], "error_code": row["error_code"]}]
