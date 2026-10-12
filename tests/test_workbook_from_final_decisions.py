"""Книга собирается из финального решения модели, а не из промежуточного черновика.

Ревью Codex 10.09 верно отметило: связь «финальное решение → скачиваемый XLSX» не была
подтверждена тестом. Разбор кода показал, что в рабочей ветке книга строится из
`model_result_rows` — строк разобранного ответа модели, — а подсказка о готовности
стояла в другой ветке и до этого места не доходила вовсе.

Здесь закреплено само правило: в книгу уходят те строки, которые модель назвала в
финальном ответе, с теми нормами, которые она выбрала.
"""

from __future__ import annotations

from proxy.services.chat_evidence_application_service import compact_estimator_draft_rows


def test_draft_rows_keep_the_model_choice():
    rows = compact_estimator_draft_rows([
        {"source_row": 984, "section": "6.21", "title": "Шкаф напольный 42U",
         "quantity": 2, "unit": "шт", "norm_code": "ГЭСНм10-03-001-02"},
        {"source_row": 985, "section": "6.21", "title": "Кабельный организатор",
         "quantity": 8, "unit": "шт", "norm_code": ""},
    ])
    assert [row["source_row"] for row in rows] == [984, 985]
    assert rows[0]["norm_code"] == "ГЭСНм10-03-001-02"
    # Пустой код сохраняется как есть: строку закроет следующий проход, выдумывать нечего.
    assert rows[1]["norm_code"] == ""


def test_rows_without_source_row_are_dropped():
    """Без номера исходной строки решение некуда положить — такая строка не наша."""
    rows = compact_estimator_draft_rows([
        {"title": "Без номера", "norm_code": "ГЭСНм10-03-001-02"},
        {"source_row": "", "title": "Пустой номер"},
        {"source_row": 990, "title": "С номером", "norm_code": "ГЭСНм10-01-055-02"},
    ])
    assert [row["source_row"] for row in rows] == [990]
