"""Снапшот-тест боевого ChecklistTemplate ПД Glorax (Phase 1, T1.3).

Читает ТОЛЬКО закоммиченный `config/checklists/glorax_pd_2026.json` — офлайн, не зависит
от исходного XLSX (который лежит в OneDrive вне git и может быть открыт/заблокирован
Excel). JSON сгенерирован `tools/build_checklist_template.py` из
`Чек_лист_входного_контроля_ПД_ГИПы_БУП.xlsx` и зафиксирован как боевой template.

Эталонные счётчики — docs/checklist_review/SNAPSHOT_PD.md /
docs/ALGO-glorax-checklist-review.md (решение оператора 2026-07-04): 335 критериев,
10 дисциплин. По-листовые числа сверены построчно при генерации (T1.3, SESSION_LOG запись 5).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from collections import Counter

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "config" / "checklists" / "glorax_pd_2026.json"

EXPECTED_TOTAL = 335
EXPECTED_DISCIPLINE_COUNT = 10
EXPECTED_DISCIPLINES = [
    "Общее",
    "СПОЗУ",
    "АР",
    "КР",
    "ЭОМ",
    "ЭН",
    " ВК и НВК",
    "ОВиК",
    "СС",
    "ПБ2 (АППЗ)",
]
EXPECTED_PER_SHEET = {
    "Общее": 5,
    "СПОЗУ": 17,
    "АР": 66,
    "КР": 31,
    "ЭОМ": 26,
    "ЭН": 11,
    " ВК и НВК": 49,
    "ОВиК": 59,
    "СС": 47,
    "ПБ2 (АППЗ)": 24,
}

ID_PATTERN = re.compile(r"^PD-[A-Z0-9]+-\d{3}$")


def _load_template() -> dict:
    with TEMPLATE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_template_file_exists():
    assert TEMPLATE_PATH.is_file(), f"боевой template не найден: {TEMPLATE_PATH}"


def test_template_total_items_335():
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
    assert not bad, f"id не матчат формат PD-[A-Z0-9]+-\\d{{3}}: {bad}"


def test_template_items_have_required_nonempty_fields():
    template = _load_template()
    assert template["items"], "template должен содержать хотя бы один item"
    for item in template["items"]:
        assert item.get("criterion"), f"{item.get('id')}: пустой criterion"
        assert item.get("allowed_answers"), f"{item.get('id')}: пустой allowed_answers"
        assert item.get("kind"), f"{item.get('id')}: пустой kind"


def test_template_kind_distribution_nonempty_presence_and_calculation():
    template = _load_template()
    kinds = Counter(item["kind"] for item in template["items"])
    assert kinds, "распределение kind не должно быть пустым"
    assert kinds.get("presence", 0) > 0, "должен быть хотя бы один item с kind=presence"
    assert kinds.get("calculation", 0) > 0, "должен быть хотя бы один item с kind=calculation"


# Точное распределение kind после T1.4 (расширенная эвристика _classify_kind + 1 ручной
# override PD-OB-007, config/checklists/glorax_pd_2026_overrides.json). Зафиксировано по
# факту прогона `tools/build_checklist_template.py` с overrides на реальном XLSX
# (SESSION_LOG запись 6). spds_formal=0 для ПД — честный результат: в ПД-чек-листе Glorax
# нет ни одного критерия с СПДС-маркерами (ведомость/штамп/основная надпись/ГОСТ 21.101/
# общие данные/состав проекта) — они появятся в РД-профиле (Phase 7). parametric=2 —
# ровно те 2 критерия, где в тексте пункта есть явная числовая величина/марка-код
# (PD-AR-047 "не менее 80 мм", PD-KR-020 "W12"); остальные "расчётные" пункты не содержат
# готового значения в самом тексте (значение появляется в результате расчёта) — это
# calculation, не parametric.
EXPECTED_KIND_DISTRIBUTION = {
    "manual_required": 150,
    "calculation": 59,
    "presence": 48,
    "cross_section": 40,
    "spatial_visual": 36,
    "parametric": 2,
    "spds_formal": 0,
}


def test_template_kind_distribution_exact_after_t1_4():
    template = _load_template()
    kinds = Counter(item["kind"] for item in template["items"])
    for kind, expected in EXPECTED_KIND_DISTRIBUTION.items():
        assert kinds.get(kind, 0) == expected, (
            f"kind={kind!r}: ожидалось {expected}, получено {kinds.get(kind, 0)}"
        )
    assert sum(kinds.values()) == EXPECTED_TOTAL


def test_template_manual_required_stays_majority_but_not_all():
    """Инвариант T1.4: классификация НЕ должна загонять всё в авто-kind ради красивых цифр.
    Экспертные критерии ("соответствует концепции", качество архитектурных/инженерных
    решений) обязаны оставаться manual_required — это честная граница автоматизации
    (implementation_plan.md §3.5), не пробел эвристики. Одновременно manual_required должен
    заметно уменьшиться относительно состояния до T1.4 (218 из 335, см. SESSION_LOG запись 5)
    — иначе расширение эвристики не дало эффекта.
    """
    template = _load_template()
    kinds = Counter(item["kind"] for item in template["items"])
    manual_count = kinds.get("manual_required", 0)

    assert manual_count > 0, "manual_required не должен исчезнуть полностью"
    assert manual_count < 218, (
        "manual_required должен заметно уменьшиться относительно до-T1.4 состояния (218/335)"
    )
    # "заметно" — не косметическая правка на несколько items: минимум на четверть корпуса
    assert manual_count <= 218 - 40, "уменьшение manual_required должно быть заметным (>=40 items)"


def test_checklist_template_glorax_pd_section_path_is_clean_text():
    """Регрессия T1.4: repr formul-объектов openpyxl не должен утекать в section_path."""
    template = _load_template()
    for item in template["items"]:
        for part in item.get("section_path", []):
            assert "openpyxl" not in part, f"{item['id']}: section_path содержит repr объекта: {part}"
            assert not part.startswith("="), f"{item['id']}: section_path содержит формулу: {part}"
            assert part.strip(), f"{item['id']}: пустой элемент section_path"
