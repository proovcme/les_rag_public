from proxy.services.clause_lookup_service import maybe_answer_clause_lookup
from proxy.services.lexical_index_service import LexicalIndex


def test_clause_lookup_extracts_numbered_clause(tmp_path, monkeypatch):
    db_path = tmp_path / "lexical.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "true")

    index = LexicalIndex(str(db_path))
    index.upsert_chunks(
        "test_collection",
        [
            {
                "point_id": "p1",
                "dataset_id": "ds-fire",
                "doc_id": "node-1",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "7\\.2 Предыдущий пункт.\n\n7\\.3 Требования пункта 7.2 не распространяются:\n\nа) на помещения до 200 м2;",
                "chunk_ord": 10,
                "content_hash": "h1",
            },
            {
                "point_id": "p2",
                "dataset_id": "ds-fire",
                "doc_id": "node-2",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "б) на помещения с газовым пожаротушением;\n\nв) на коридоры с непосредственным удалением продуктов горения;",
                "chunk_ord": 11,
                "content_hash": "h2",
            },
            {
                "point_id": "p3",
                "dataset_id": "ds-fire",
                "doc_id": "node-3",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "7\\.4 Следующий пункт.",
                "chunk_ord": 12,
                "content_hash": "h3",
            },
        ],
    )

    result = maybe_answer_clause_lookup(
        "Найди пункт 7.3 в СП 7.13130",
        collection="test_collection",
        dataset_ids=["ds-fire"],
    )

    assert result is not None
    assert result.sources == ["NTD/СП 7.13130.docx"]
    assert "Пункт 7.3 СП 7.13130" in result.answer
    assert "а) на помещения до 200 м2" in result.answer
    assert "б) на помещения с газовым пожаротушением" in result.answer
    assert "7.4 Следующий пункт" not in result.answer
    assert result.payload()["operation"] == "clause_lookup"


def test_clause_lookup_maps_smoke_control_exceptions_to_sp7_clause(tmp_path, monkeypatch):
    db_path = tmp_path / "lexical.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "true")

    index = LexicalIndex(str(db_path))
    index.upsert_chunks(
        "test_collection",
        [
            {
                "point_id": "p1",
                "dataset_id": "ds-fire",
                "doc_id": "node-1",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "7\\.3 Требования пункта 7.2 не распространяются:\n\nа) на помещения до 200 м2;",
                "chunk_ord": 3,
                "content_hash": "h1",
            },
            {
                "point_id": "p2",
                "dataset_id": "ds-fire",
                "doc_id": "node-2",
                "doc_name": "NTD/СП 7.13130.docx",
                "text": "7\\.4 Следующий пункт.",
                "chunk_ord": 4,
                "content_hash": "h2",
            },
        ],
    )

    result = maybe_answer_clause_lookup(
        "В каких случаях допускается не выполнять систему дымоудаления",
        collection="test_collection",
        dataset_ids=["ds-fire"],
    )

    assert result is not None
    assert result.clause == "7.3"
    assert result.norm_ref == "сп 7.13130"
    assert "а) на помещения до 200 м2" in result.answer


# ── W2.6: разделы, параграфы, римские, приложения ──

from proxy.services.clause_lookup_service import (
    _extract_appendix_text,
    _extract_clause,
    _extract_clause_text,
    _roman_to_int,
)


def _rows(*texts):
    return [{"text": t, "chunk_ord": i} for i, t in enumerate(texts)]


def test_extract_clause_section_word():
    assert _extract_clause("Что сказано в разделе 6 СП 7.13130?") == ("clause", "6")
    assert _extract_clause("параграф 2.1 ГОСТ 21.101") == ("clause", "2.1")
    assert _extract_clause("статья 5 ФЗ-123") == ("clause", "5")


def test_extract_clause_roman_section():
    assert _extract_clause("раздел IV СП 60.13330") == ("clause", "4")
    assert _roman_to_int("XIV") == 14


def test_extract_clause_appendix():
    assert _extract_clause("Что содержит приложение Б СП 7.13130?") == ("appendix", "Б")
    assert _extract_clause("покажи приложения В ГОСТ 21.110") == ("appendix", "В")


def test_extract_clause_still_prefers_explicit_clause():
    assert _extract_clause("пункт 7.2 раздела 6 СП 7.13130") == ("clause", "7.2")


def test_extract_clause_none():
    assert _extract_clause("Какие требования к вентиляции?") == ("", "")


def test_section_extraction_single_number_with_subclauses():
    rows = _rows(
        "5 Отопление\n\nТребования к отоплению.\n\n5.1 Радиаторы\n\nТекст про радиаторы.",
        "6 Вентиляция\n\nОбщие требования.\n\n6.1 Воздуховоды\n\nТекст про воздуховоды.",
        "7 Противодымная защита\n\nДальше другой раздел.",
    )
    extracted = _extract_clause_text(rows, "6", max_chars=8000)
    assert extracted is not None
    text = extracted[0]
    assert text.startswith("6 Вентиляция")
    assert "6.1 Воздуховоды" in text  # подпункты раздела входят
    assert "Противодымная" not in text  # следующий раздел — граница


def test_appendix_extraction_until_next_appendix():
    rows = _rows(
        "Основной текст документа.\n\nПриложение А\n\nСодержимое приложения А.",
        "Приложение Б\n\nТаблица Б.1 — данные приложения Б.\n\nПриложение В\n\nДругое.",
    )
    extracted = _extract_appendix_text(rows, "Б", max_chars=8000)
    assert extracted is not None
    text = extracted[0]
    assert text.startswith("Приложение Б")
    assert "Б.1" in text
    assert "Приложение В" not in text


def test_appendix_missing_returns_none():
    assert _extract_appendix_text(_rows("Просто текст без приложений."), "Б", max_chars=100) is None
