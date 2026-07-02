from proxy.services.smeta_artifact_service import (
    build_smeta_artifact,
    compact_smeta_answer,
    extract_smeta_tables,
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
