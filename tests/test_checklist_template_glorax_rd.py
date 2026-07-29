"""Снапшот-тест боевого ChecklistTemplate РД Glorax (Phase 7, T7.1).

Читает ТОЛЬКО закоммиченный `config/checklists/glorax_rd_2026.json` — офлайн, не зависит
от исходного XLSX (который лежит в OneDrive вне git и может быть открыт/заблокирован
Excel). JSON сгенерирован `tools/build_checklist_template.py` из
`Чек_лист_входного_контроля_РД_ГИПы_БУП.xlsx` и зафиксирован как боевой template.

Эталонные счётчики — docs/checklist_review/SNAPSHOT_RD.md (T0.1/T0.2, решение оператора
2026-07-04): 692 критерия, 26 дисциплин, по-листовые числа сверены построчно при генерации
(T7.1, SESSION_LOG запись 15) — совпадение достигнуто с первого прогона генератора, без
доработок importer'а (в отличие от ПД, где потребовался фикс приоритета заливки над DV,
T1.3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from collections import Counter

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "config" / "checklists" / "glorax_rd_2026.json"

EXPECTED_TOTAL = 692
EXPECTED_DISCIPLINE_COUNT = 26
EXPECTED_DISCIPLINES = [
    "АР", "ГП", "КЖ", "КМ", "ЭОМ", "НС", "ВК", "ОВ1", "ОВ2", "ОВ3", "ИТП", "ТС",
    "СППЗ", "ОС", "СКУД", "СОТ", "СКС", "СКПТ", "ПВ", "РАСЦО", "КНС", "АСКУ",
    "Wi-Fi", "МТ", "УД", "НСС",
]
EXPECTED_PER_SHEET = {
    "АР": 53, "ГП": 30, "КЖ": 42, "КМ": 14, "ЭОМ": 25, "НС": 21, "ВК": 29,
    "ОВ1": 50, "ОВ2": 42, "ОВ3": 49, "ИТП": 53, "ТС": 19, "СППЗ": 23, "ОС": 23,
    "СКУД": 20, "СОТ": 22, "СКС": 17, "СКПТ": 18, "ПВ": 19, "РАСЦО": 20,
    "КНС": 16, "АСКУ": 18, "Wi-Fi": 18, "МТ": 16, "УД": 15, "НСС": 20,
}

ID_PATTERN = re.compile(r"^RD-[A-Z0-9]+-\d{3}$")


def _load_template() -> dict:
    with TEMPLATE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_template_file_exists():
    assert TEMPLATE_PATH.is_file(), f"боевой template не найден: {TEMPLATE_PATH}"


def test_template_total_items_692():
    template = _load_template()
    assert len(template["items"]) == EXPECTED_TOTAL


def test_template_disciplines_count_and_list():
    template = _load_template()
    assert len(template["disciplines"]) == EXPECTED_DISCIPLINE_COUNT
    assert template["disciplines"] == EXPECTED_DISCIPLINES


def test_template_per_sheet_counts_match_snapshot():
    template = _load_template()
    counts = Counter(item["discipline"] for item in template["items"])
    for discipline, expected in EXPECTED_PER_SHEET.items():
        assert counts.get(discipline, 0) == expected, (
            f"лист {discipline!r}: ожидалось {expected}, получено {counts.get(discipline, 0)}"
        )
    assert sum(counts.values()) == EXPECTED_TOTAL


def test_template_ids_unique_and_match_format():
    template = _load_template()
    ids = [item["id"] for item in template["items"]]
    assert len(ids) == len(set(ids)), "id должны быть уникальны"
    bad = [i for i in ids if not ID_PATTERN.match(i)]
    assert not bad, f"id не матчат формат RD-[A-Z0-9]+-\\d{{3}}: {bad}"


def test_template_ids_stable_disc_codes_no_collision():
    """26 РД-дисциплин транслитерируются в 26 РАЗНЫХ латинских кодов (в т.ч. 'Wi-Fi' ->
    непустой код 'WI' через generic-фолбэк, не пустую строку/коллизию с другой дисциплиной)."""
    template = _load_template()
    disc_to_code: dict[str, str] = {}
    for item in template["items"]:
        code_match = re.match(r"^RD-([A-Z0-9]+)-\d{3}$", item["id"])
        assert code_match, f"не удалось извлечь код дисциплины из id {item['id']!r}"
        code = code_match.group(1)
        disc = item["discipline"]
        assert code, f"пустой код дисциплины для {disc!r}"
        disc_to_code.setdefault(disc, code)
        assert disc_to_code[disc] == code, (
            f"дисциплина {disc!r} даёт разные коды в разных items: {disc_to_code[disc]!r} vs {code!r}"
        )
    codes = list(disc_to_code.values())
    assert len(codes) == len(set(codes)), (
        f"коллизия кодов дисциплин: {disc_to_code}"
    )
    assert disc_to_code.get("Wi-Fi"), "Wi-Fi должен транслитерироваться в непустой код"


def test_template_items_have_required_nonempty_fields():
    template = _load_template()
    assert template["items"], "template должен содержать хотя бы один item"
    for item in template["items"]:
        assert item.get("criterion"), f"{item.get('id')}: пустой criterion"
        assert item.get("allowed_answers"), f"{item.get('id')}: пустой allowed_answers"
        assert item.get("kind"), f"{item.get('id')}: пустой kind"


# Точное распределение kind РД (боевой прогон T7.1, без overrides — построчная сверка
# счётчиков совпала с эталоном с первого прогона, дополнительных ручных правок kind не
# потребовалось). В отличие от ПД (spds_formal=0), в РД эвристика `_SPDS_FORMAL_PATTERN`
# реально ловит массовые формальные пункты каждого листа ("Общие данные комплекта
# приложены", "Содержание комплекта приложено", "Ведомость... приложена", "Листы комплекта
# читаемы") — по 5-6 таких пунктов почти на каждом из 26 листов, что и даёт заметно
# отличное от ПД распределение (spds_formal — второй по величине класс после
# manual_required, а не 0).
EXPECTED_KIND_DISTRIBUTION = {
    "manual_required": 321,
    "spds_formal": 170,
    "presence": 81,
    "cross_section": 47,
    "calculation": 46,
    "spatial_visual": 25,
    "parametric": 2,
}


def test_template_kind_distribution_exact():
    template = _load_template()
    kinds = Counter(item["kind"] for item in template["items"])
    for kind, expected in EXPECTED_KIND_DISTRIBUTION.items():
        assert kinds.get(kind, 0) == expected, (
            f"kind={kind!r}: ожидалось {expected}, получено {kinds.get(kind, 0)}"
        )
    assert sum(kinds.values()) == EXPECTED_TOTAL


def test_template_spds_formal_is_populated_unlike_pd():
    """Регрессия ожидания из ПД (Записи 5-6): spds_formal=0 там был честным фактом данных
    ПД-чек-листа, а НЕ багом эвристики/паттерна. На РД тот же паттерн обязан реально
    сработать (ведомости/штампы/общие данные — массовые формальные пункты РД-профиля) —
    если бы spds_formal остался 0 и на РД, это означало бы баг паттерна, а не факт данных."""
    template = _load_template()
    kinds = Counter(item["kind"] for item in template["items"])
    assert kinds.get("spds_formal", 0) > 0, (
        "spds_formal должен быть >0 на РД — паттерн обязан ловить "
        "'ведомость/штамп/общие данные/ГОСТ 21.101' в реальных РД-формулировках"
    )


def test_checklist_template_glorax_rd_section_path_is_clean_text():
    """Регрессия T1.4 (openpyxl formula repr в section_path), проверена и на РД-файле."""
    template = _load_template()
    for item in template["items"]:
        for part in item.get("section_path", []):
            assert "openpyxl" not in part, f"{item['id']}: section_path содержит repr объекта: {part}"
            assert not part.startswith("="), f"{item['id']}: section_path содержит формулу: {part}"
            assert part.strip(), f"{item['id']}: пустой элемент section_path"


def test_template_stage_is_rd_for_all_items():
    template = _load_template()
    assert template["stage"] == "RD"
    for item in template["items"]:
        assert item["stage"] == "RD", f"{item['id']}: stage != RD"
