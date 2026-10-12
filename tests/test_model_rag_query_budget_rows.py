"""Бюджет поисковых запросов считается по строкам с измеримым содержанием.

Живой контроль .199 (10.10): в порции три работы и семь заголовков разделов. Бюджет
считался по всем десяти строкам — 40 запросов и 1600 токенов на их список. Модель
ушла в повтор: 126 строк, из них 20 разных, обрыв по пределу генерации; цену кабеля
она запросить не успела. Заголовок без единицы и количества нормы не требует.
"""
from __future__ import annotations

import pytest

from proxy.services import chat_evidence_application_service as chat

# Буквальный текст вложения контрольного прогона .199.
PROBE = """Файл: probe-vor.xlsx
Тип данных: таблица/спецификация. Строки ниже сохранены с номерами листов/строк.
Формат ячеек: les.tabular.cells.v2

## Лист: АР
АР!R8: № п/п | Наименование работ | Ед.изм. | Кол-во | Материал (ед.), руб. без НДС | Работа (ед.), руб. без НДС | Материал (итого), руб. без НДС | Работа (итого), руб. без НДС | Стоимость (итого), руб. без НДС | Примечание
АР!R9: 1 | Архитектурные решения
АР!R10: 1.1 | Демонтажные работы |  |  |  |  | 0 | 0 | 0
АР!R11: 1.29 | Напольные покрытия |  |  |  |  | 0 | 0 | 0
АР!R12: 1.31 | Тип 2. Ковровая плитка 500х500мм. Atlas 05 ( темно серая ) в проходах . 4,0 мм | м2 | 66.7 |  |  | 0 | 0 | 0
Итого непустых строк на листе «АР»: 5
## Лист: СКС
СКС!R8: № п/п | Наименование работ | Ед.изм. | Кол-во | Материал (ед.), руб. без НДС | Работа (ед.), руб. без НДС | Материал (итого), руб. без НДС | Работа (итого), руб. без НДС | Стоимость (итого), руб. без НДС | Примечание
СКС!R9: 5 | Структурированная кабельная система (СКС)
СКС!R10:  | Офис №19
СКС!R11: 5.5 | Кабельная продукция |  |  |  |  | 0 | 0 | 0
СКС!R12: 5.6 | Витая пара кат.5Е 4 пары серая, HF UTP-4P-Cat.5e-SOLID-LSZH-GY Cabeus | м | 8500 |  |  | 0 | 0 | 0
Итого непустых строк на листе «СКС»: 5
## Лист: СОУЭ
СОУЭ!R8: № п/п | Наименование работ | Ед.изм. | Кол-во | Материал (ед.), руб. без НДС | Работа (ед.), руб. без НДС | Материал (итого), руб. без НДС | Работа (итого), руб. без НДС | Стоимость (итого), руб. без НДС | Примечание
СОУЭ!R9: 7 | Система оповещения и управления эвакуацией (СОУЭ)
СОУЭ!R10:  | Офис №19
СОУЭ!R11: 7.1 | Оборудование |  |  |  |  | 0 | 0 | 0
СОУЭ!R12: 7.2 | Демонтаж оповещателя настенного Глагол-Н1-1 | шт | 7 |  |  | 0 | 0 | 0
Итого непустых строк на листе «СОУЭ»: 5
"""


def test_headings_stay_in_the_portion_but_do_not_buy_queries():
    _text, plan = chat.smeta_portion_context(PROBE, session_id="s1", limit=50, cursors=None)

    # Исходные строки не теряются: все десять показаны модели.
    assert plan["rows_in_pass"] == 10
    # Запросы отводятся трём строкам с единицей и количеством.
    assert plan["query_rows_in_pass"] == 3
    assert chat.model_rag_query_rows(plan) == 3
    assert chat.plan_model_rag_queries((), rows_in_pass=chat.model_rag_query_rows(plan))["budget"] == 12


def test_row_with_a_unit_but_unknown_quantity_still_buys_queries():
    text = PROBE.replace("| шт | 7 |", "| шт |  |")
    _text, plan = chat.smeta_portion_context(text, session_id="s1", limit=50, cursors=None)

    assert plan["query_rows_in_pass"] == 3


def test_portion_of_only_unmeasured_rows_keeps_the_previous_budget():
    plan = {"rows_in_pass": 4, "query_rows_in_pass": 0}

    assert chat.model_rag_query_rows(plan) == 4
    assert chat.model_rag_query_rows({"rows_in_pass": 5}) == 5


@pytest.mark.parametrize("budget, ceiling, expected", [
    (12, 1600, 576),    # три работы: списку незачем расти до 1600 токенов
    (8, 1600, 384),
    (40, 1600, 1600),   # длинная порция: прежний потолок
    (12, 400, 400),     # настроенный потолок ниже расчёта соблюдается
    (1, 1600, 256),     # нижняя граница прежняя
])
def test_query_list_output_is_bounded_by_the_executor_budget(budget, ceiling, expected):
    assert chat.model_rag_query_max_tokens(query_budget=budget, ceiling=ceiling) == expected


def test_estimator_query_guidance_keeps_headings_as_context_not_search_targets():
    profile = {'mode': 'estimator', 'rag_policy': {'system_datasets': ['smeta']}}
    instruction = chat.model_rag_query_instruction(profile, rows_in_pass=3)
    assert 'Заголовки разделов используй как контекст' in instruction
    assert 'Пустое количество само по себе не означает заголовок' in instruction
    assert 'по всем фактическим строкам' not in instruction
    assert 'Сначала охвати все строки порции' not in instruction
    assert 'для работ и материалов' in instruction
    # Authoring stays with the model: parser/executor may not suppress a returned
    # heading-like query, append prices or rewrite its professional terminology.
    authored = ['Архитектурные решения', 'Монтаж шкафа связи', 'цена: шкаф связи']
    parsed = chat.parse_model_rag_queries('\n'.join(authored))
    assert parsed == authored
    assert chat.plan_model_rag_queries(parsed, rows_in_pass=3)['executed'] == authored


def test_heading_query_guidance_does_not_change_generic_document_search():
    instruction = chat.model_rag_query_instruction({'mode': 'rag'}, rows_in_pass=3)
    assert 'Заголовки разделов используй как контекст' not in instruction
