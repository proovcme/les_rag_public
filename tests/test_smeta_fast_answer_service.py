import pytest

from proxy.services.smeta_fast_answer_service import smeta_fast_fallback_answer


def test_smeta_fast_fallback_sks_line_item_rim_scenario():
    text = """
    СКС: Cat.5e = 36 600 м; Cat.6A = 2 000 м; ВОЛС OM4: 400 м.
    шкафы: 2 шт; патч-панели Cat.6A - 2 шт; патч-панели Cat.5e - 12 шт.
    Keystone Cat.5e - 494 шт; кабель-канал: 400 м; лотки всего 426 м.
    ПВХ 25 мм 1200 м; ПНД 25 мм 600 м; КДЗС - 48 шт.
    """

    answer = smeta_fast_fallback_answer(text)

    assert "спецификация СКС" in answer
    assert "Прокладка медного кабеля U/UTP" in answer
    assert "Оконцевание, маркировка и измерение" in answer
    assert "Сценарная РИМ-оценка работ" in answer
    assert "предварительная РИМ-оценка" in answer
    assert "финальная ЛСР" in answer


def test_smeta_fast_fallback_sks_xlsx_rows_package_lengths():
    text = """
    Раздел 6.21. "МОНТАЖ СИСТЕМЫ СТРУКТУРИРОВАННОЙ КАБЕЛЬНОЙ СЕТИ (СКС)"
    Hyperline UUTP4-C5E-S24-IN-LSZH-GY-305 (305 м) Кабель витая пара, U/UTP, категория 5e | шт. | 120
    Hyperline UUTP4-C6A-S23-IN-LSZH-GY-500 (500 м) Кабель витая пара, U/UTP, категория 6A | шт. | 4
    Hyperline KJ9-8P8C-C5e-90-WH Вставка Keystone Jack RJ-45 | шт. | 494
    TA-GN 100x60 Короб с крышкой DKC | м.п | 400
    Листовой неперфорированный кабельный лоток 100х50 | м.п | 426
    Труба гофрированная ПВХ 25 мм с протяжкой легкая серая (50м) | м.п. | 1200
    Труба гофрированная ПНД 25 мм с протяжкой тяжелая оранжевая (50м) | м.п. | 600
    """

    answer = smeta_fast_fallback_answer(text)

    assert "38 600 м" in answer
    assert "826 м" in answer
    assert "1 800 м" in answer
    assert "spb_2kv2026" in answer
    assert "предварительная РИМ-оценка" in answer


def test_smeta_fast_fallback_stolp_quantity_split_blocks_final():
    text = """
    Оценить столп: 11 ярусов, давальческое сырье 0 руб, гусеничный кран.
    текст ТЗ: 664,71112 т; итог таблицы / строки 1-10: 664,71172 т;
    сумма всех 11 строк: 696,89172 т. Этап 3 перевозка 0 руб.
    """

    answer = smeta_fast_fallback_answer(text)

    assert "Форма развилки исходных объёмов" in answer
    assert "664,71112 т" in answer
    assert "664,71172 т" in answer
    assert "696,89172 т" in answer
    assert "РИМ-сценарий работ по вариантам" in answer
    assert "ГЭСНм 38-01-001-01" in answer
    assert "предварительная РИМ-оценка" in answer
    assert "priced_final" not in answer


def test_smeta_direct_model_answer_uses_fast_fallback_on_timeout(monkeypatch):
    from proxy.routers.chat import _smeta_direct_model_answer

    class TimeoutClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise TimeoutError("simulated timeout")

    monkeypatch.setattr("proxy.routers.chat.httpx.Client", TimeoutClient)
    answer = _smeta_direct_model_answer(
        "Дай оценку СКС: Cat.5e = 36 600 м; Cat.6A = 2 000 м; ВОЛС OM4: 400 м; "
        "Keystone Cat.5e - 494 шт; лотки всего 426 м."
    )

    assert "Сценарная РИМ-оценка работ" in answer
    assert "scenario_estimate" not in answer
