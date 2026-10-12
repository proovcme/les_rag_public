"""Поиск нормы по наименованию изделия: разбор наименования, порядок, границы.

Основание — замер 11.09.2026 по 56 нерешённым строкам прогона
`sks-unit-20260911-0806`. Поиск норм ищет изделие среди названий работ и попал в
профильный сборник 11 раз; поиск по наименованиям изделий из готовых смет — 53 раза.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proxy.smeta_core.material_practice import (
    SCHEMA,
    load_index,
    similar_applications,
    tokens,
)


def entry(material: str, norm_code: str, **extra: object) -> dict[str, object]:
    base = {
        "material": material,
        "norm_code": norm_code,
        "count": 1,
        "norm_title": "Работа",
        "norm_unit": "100 м",
        "material_unit": "м",
        "in_base": True,
        "demolition": False,
        "equipment": False,
    }
    base.update(extra)
    return base


@pytest.fixture()
def index_file(tmp_path: Path) -> str:
    payload = {
        "schema": SCHEMA,
        "source": "E:/Сметы",
        "pairs_total": 5,
        "entries": [
            entry(
                "Кабель витая пара, неэкранированная U/UTP, категория 5e",
                "ГЭСНм08-02-398-01",
                count=34,
                norm_title="Провод в лотках, сечением: до 6 мм2",
            ),
            entry(
                "Кабель BC5E-4-LSHF",
                "ГЭСНр67-03-001-01",
                count=9,
                norm_title="Демонтаж кабеля",
                demolition=True,
            ),
            entry(
                "Шпилька М8х2000 CM200802",
                "ГЭСНм08-02-395-01",
                count=13,
                norm_title="Лоток металлический штампованный",
                norm_unit="1 т",
            ),
            entry(
                "Норма снята с базы",
                "ГЭСНм99-99-999-99",
                count=99,
                in_base=False,
            ),
        ],
    }
    target = tmp_path / "material_norm_index.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(target)


def test_russian_words_are_cut_to_a_stem_and_latin_is_kept_whole() -> None:
    """«Ответвитель» и «ответвителя» — одно изделие; «CM200802» указывает на одно."""
    assert tokens("Ответвитель") == tokens("ответвителя")
    assert "л:cm200802" in tokens("Шпилька М8х2000 CM200802")


def test_russian_and_latin_tokens_do_not_merge() -> None:
    """Без разных префиксов совпадение русского «м» с латинским «m» считалось бы близостью."""
    assert tokens("PC") & tokens("пс") == frozenset()


def test_common_words_are_dropped() -> None:
    """«Для» и «серый» есть почти в каждом наименовании и ничего не различают."""
    assert tokens("для серый") == frozenset()


def test_missing_index_means_no_hints_rather_than_a_failure(tmp_path: Path) -> None:
    """Индекс могли не собрать: отсутствие файла — это «подсказок нет», не сбой."""
    absent = str(tmp_path / "nothing.json")
    assert load_index(absent)["materials"] == []
    assert similar_applications("Кабель витая пара", path=absent) == []


def test_a_product_finds_the_norm_it_was_counted_by(index_file: str) -> None:
    """Строка ведомости именует изделие — и попадает в изделие, а не в название работы."""
    found = similar_applications(
        "Hyperline UUTP4-C5E-S24-IN-LSZH-GY-305 Кабель витая пара неэкранированная U/UTP",
        path=index_file,
    )
    assert found
    assert found[0]["norm_code"] == "ГЭСНм08-02-398-01"
    assert found[0]["material"].startswith("Кабель витая пара")


def test_demolition_norms_are_marked_and_can_be_left_out(index_file: str) -> None:
    """Без пометки «Кабель BC5E-4-LSHF» тянул бы за собой «Демонтаж кабеля» молча."""
    found = similar_applications("Кабель BC5E-4-LSHF", path=index_file)
    assert [item["demolition"] for item in found if item["norm_code"].startswith("ГЭСНр")] == [True]

    without = similar_applications(
        "Кабель BC5E-4-LSHF", path=index_file, include_demolition=False
    )
    assert all(not item["demolition"] for item in without)


def test_norm_absent_from_the_base_is_not_offered(index_file: str) -> None:
    """Модель сошлётся на карточку, которой нет, и расчёт её отвергнет."""
    found = similar_applications("Норма снята с базы", path=index_file)
    assert [item["norm_code"] for item in found] == []


def test_confidence_separates_a_name_match_from_a_shared_word(index_file: str) -> None:
    """Совпадение по слову «кабель» и совпадение наименования — разные утверждения."""
    exact = similar_applications("Шпилька М8х2000 CM200802", path=index_file)
    assert exact[0]["confidence"] == "совпадение наименований"

    vague = similar_applications("Кабель силовой ВВГнг 3х2,5", path=index_file)
    assert all(item["confidence"] != "совпадение наименований" for item in vague)


def test_a_title_without_meaningful_words_returns_nothing(index_file: str) -> None:
    """«ИБП» и «АКБ» короче порога: сказать по ним нечего, и выдумывать нельзя."""
    assert similar_applications("ИБП", path=index_file) == []


def test_the_same_norm_is_not_repeated_across_products(index_file: str) -> None:
    """Одна норма под несколькими похожими изделиями заняла бы весь показ собой."""
    found = similar_applications("Кабель витая пара U/UTP категория 5e", path=index_file)
    assert len({item["norm_code"] for item in found}) == len(found)


# --- Живая проверка 17.09: практика подсказала норму, применённую один раз ---------------
# Витую пару в готовых сметах 50 раз считали нормой ГЭСНм08-02-148-01, но первой модель
# увидела «Затягивание проводов в плинтус» (одно применение): у того изделия в названии
# совпал бренд Cabeus. Среди изделий, близких по названию, частая практика весит больше;
# слабое совпадение с частой нормой чужого изделия точное совпадение не обгоняет.

def _practice(tmp_path: Path, *entries: dict[str, object]) -> str:
    target = tmp_path / "practice.json"
    target.write_text(json.dumps({"schema": SCHEMA, "source": "E:/Сметы", "pairs_total": len(entries),
                                  "entries": list(entries)}, ensure_ascii=False), encoding="utf-8")
    return str(target)


def test_established_practice_outranks_a_one_off_norm_of_a_similar_product(tmp_path: Path) -> None:
    path = _practice(
        tmp_path,
        entry("Кабель Cabeus UTP-4P-CAT.6-SOLID-LSZH, Cat.6, 4 витые пары, оранжевый", "ГЭСНм08-02-422-01",
              count=1, norm_title="Затягивание проводов в электротехнический плинтус"),
        entry("Кабель витая пара SF/UTP, категория 5e, 4 пары, бухта 305 м SFUTP4-C5E-S24-IN-LSZH-GY-305 Hyperline",
              "ГЭСНм08-02-148-01", count=50, norm_title="Кабель до 35 кВ в проложенных трубах, блоках и коробах"),
        *[entry(f"Светильник светодиодный {n}", f"ГЭСНм08-03-{n:03d}-01", count=2) for n in range(20)],
    )
    found = similar_applications("Витая пара кат.5Е 4 пары серая, HF UTP-4P-Cat.5e-SOLID-LSZH-GY Cabeus", path=path)
    assert found[0]["norm_code"] == "ГЭСНм08-02-148-01", found


def test_frequent_norm_of_a_weakly_similar_product_does_not_outrank_an_exact_match(tmp_path: Path) -> None:
    path = _practice(
        tmp_path,
        entry("Шпилька М8х2000 CM200802", "ГЭСНм08-02-395-01", count=13),
        entry("Шпилька резьбовая соединительная 8х1000мм", "ГЭСН09-05-003-01", count=446,
              norm_title="Постановка болтов"),
        *[entry(f"Светильник светодиодный {n}", f"ГЭСНм08-03-{n:03d}-01", count=2) for n in range(20)],
    )
    found = similar_applications("Шпилька М8х2000 CM200802", path=path)
    assert found[0]["norm_code"] == "ГЭСНм08-02-395-01", found


def test_card_note_names_the_practice_of_similar_products() -> None:
    from proxy.services.chat_evidence_application_service import material_application_note

    note = material_application_note({"material": "Кабель витая пара SF/UTP", "applications": 50,
                                      "similar_applications": 93, "confidence": "частичное совпадение"})
    assert "применений 50" in note and "93 применений" in note
    single = material_application_note({"material": "Шпилька", "applications": 13, "similar_applications": 13,
                                        "confidence": "совпадение наименований"})
    assert "близкими" not in single
