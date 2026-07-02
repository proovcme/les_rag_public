from proxy.services.smeta_artifact_service import (
    build_smeta_artifact,
    build_lsr_form,
    compact_smeta_answer,
    extract_smeta_tables,
    persist_smeta_artifact_exports,
)


def test_smeta_artifact_extracts_work_cost_table_and_totals():
    answer = """
**ВОР и стоимость работ**
| Работа | Объём | Ставка сценария | Сумма | Комментарий |
|---|---:|---:|---:|---|
| Прокладка медного кабеля U/UTP | 38 600 м | 120 руб./м | 4 632 000 руб. | без поставки |
| Оконцевание портов RJ-45 | 518 порт | 1 250 руб./порт | 647 500 руб. | измерения отдельно |
| Итого |  |  | 5 279 500 руб. |  |

**Итог**
Предварительная оценка работ.
"""

    tables = extract_smeta_tables(answer)
    artifact = build_smeta_artifact(answer, question="Оцени СКС")

    assert len(tables) == 1
    assert tables[0].kind == "work_cost"
    assert tables[0].amount_total == 5_279_500
    assert artifact is not None
    assert artifact["mode"] == "markdown"
    assert "Сметный артефакт" in artifact["content"]
    assert "5 279 500 руб." in artifact["content"]
    assert artifact["tables"][0]["rows"] == 3


def test_compact_smeta_answer_moves_long_tables_to_artifact_marker():
    rows = "\n".join(
        f"| Работа {idx} | {idx} шт | {idx * 1000} руб. |"
        for idx in range(1, 7)
    )
    answer = (
        "**Что понял**\n"
        "Даю сметную оценку работ.\n\n"
        "**Стоимость работ**\n"
        "| Работа | Объём | Сумма |\n"
        "|---|---:|---:|\n"
        f"{rows}\n\n"
        "**Итог**\n"
        "Сумма предварительная."
    )

    artifact = build_smeta_artifact(answer, question="смета")
    compact = compact_smeta_answer(answer, artifact)

    assert artifact is not None
    assert "Работа 6" in artifact["content"]
    assert "Таблица вынесена в артефакт" in compact
    assert "6 строк" in compact
    assert "Работа 6" not in compact
    assert "Сумма предварительная" in compact


def test_smeta_artifact_persists_xlsx_and_csv_downloads(tmp_path):
    answer = """
**ВОР**
| № | Раздел | Работа | Ед. | Кол-во | Основание | Статус |
|---:|---|---|---:|---:|---|---|
| 1 | СКС | Прокладка кабеля | м | 100 | спецификация | измеримо |

**Оценка стоимости работ**
| № | Работа | Кол-во | Ед. | Норма/источник | Ставка/допущение | Сумма | Комментарий |
|---:|---|---:|---:|---|---:|---:|---|
| 1 | Прокладка кабеля | 100 | м | ГЭСНм10, кандидат по кабелям связи | 120 руб./м | 12 000 руб. | сценарно |
"""

    artifact = build_smeta_artifact(answer, question="Дай ВОР")
    exported = persist_smeta_artifact_exports(artifact, output_dir=tmp_path, prefix="unit")

    assert exported is not None
    assert exported["downloads"]["xlsx"].endswith(".xlsx")
    assert exported["downloads"]["csv"].endswith(".csv")
    xlsx_path = tmp_path / exported["downloads"]["xlsx"].split("path=")[1]
    csv_path = tmp_path / exported["downloads"]["csv"].split("path=")[1]
    assert xlsx_path.is_file()
    assert csv_path.is_file()

    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    assert "Свод" in wb.sheetnames
    assert any("Оценка стоимости" in name for name in wb.sheetnames)
    assert "ГЭСНм10" in csv_path.read_text(encoding="utf-8-sig")


def test_smeta_artifact_adds_lsr_form_without_replacing_tables(tmp_path):
    answer = """
**Оценка стоимости работ**
| № | Работа | Кол-во | Ед. | Норма/источник | Ставка/допущение | Сумма | Комментарий |
|---:|---|---:|---:|---|---:|---:|---|
| 1 | Прокладка кабеля | 100 | м | ГЭСНм 10-06-037-01, аналог | 120 руб./м | 12 000 руб. | scenario_assumption |
| 2 | Оконцевание портов | 24 | порт | ГЭСНм 10, кандидат | 1 250 руб./порт | 30 000 руб. | scenario_assumption |
| Итого |  |  |  |  |  | 42 000 руб. |  |
"""

    tables = extract_smeta_tables(answer)
    lsr_form = build_lsr_form(tables)
    artifact = build_smeta_artifact(answer, question="Дай ВОР и оценку")
    exported = persist_smeta_artifact_exports(artifact, output_dir=tmp_path, prefix="lsr")

    assert lsr_form is not None
    assert lsr_form["schema"] == "lsr_display_form_v1"
    assert lsr_form["rows"][0]["basis"] == "ГЭСНм 10-06-037-01"
    assert artifact is not None
    assert "## 1. Оценка стоимости работ" in artifact["content"]
    assert "## Форма ЛСР" in artifact["content"]
    assert "Итого по форме ЛСР" in artifact["content"]
    assert artifact["lsr_form"]["amount_total"] == 42_000

    import openpyxl

    xlsx_path = tmp_path / exported["downloads"]["xlsx"].split("path=")[1]
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    assert "ЛСР" in wb.sheetnames
    ws = wb["ЛСР"]
    assert ws.cell(row=2, column=3).value == "Прокладка кабеля"
    assert ws.cell(row=3, column=7).value == 30_000
