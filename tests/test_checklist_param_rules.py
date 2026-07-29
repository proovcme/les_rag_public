"""Тесты реестра параметрических правил (T3.1, TDD red->green).

АРХИТЕКТУРА (implementation_plan.md §3.3, промпт T3.1): реестр `config/checklists/glorax_param_rules.yaml`
курируется вручную по РЕАЛЬНЫМ формулировкам критериев glorax_pd_2026.json (kind=parametric и
кандидаты в cross_section/manual_required с готовым числом/маркой в тексте). Экстракция значения —
regex по extract_patterns (никакого LLM); сравнение — код (`compare`). LLM не участвует нигде в этом
модуле.

Три публичные функции:
  - load_param_rules(path=None) -> list[ParamRule]   — грузит + валидирует YAML (fail-closed, паттерн
    normcontrol_review_map_service.load_review_map);
  - extract_value(text, rule) -> ExtractedValue | None — по extract_patterns находит значение+unit,
    нормализует единицы (мм/см/м -> mm);
  - compare(extracted, rule) -> ComparisonResult(status, message) — ok|issue, сравнивает КОДОМ.
"""

from __future__ import annotations

import pytest

from proxy.services.checklist_param_rules import (
    ComparisonResult,
    ExtractedValue,
    ParamRule,
    compare,
    extract_value,
    load_param_rules,
)


# ── load_param_rules: грузит боевой YAML ────────────────────────────────────────────────


def test_load_param_rules_reads_real_registry():
    rules = load_param_rules()
    assert len(rules) >= 8
    ids = {r.rule_id for r in rules}
    assert len(ids) == len(rules), "rule_id должны быть уникальны"
    for r in rules:
        assert isinstance(r, ParamRule)
        assert r.item_ids, f"{r.rule_id}: item_ids не должен быть пустым"
        assert r.operator in (">=", "<=", "==", "contains", "not_contains")
        assert r.extract_patterns, f"{r.rule_id}: extract_patterns не должен быть пустым"


def test_load_param_rules_covers_pd_ar_047_and_pd_kr_020():
    rules = load_param_rules()
    by_item: dict[str, list[ParamRule]] = {}
    for r in rules:
        for item_id in r.item_ids:
            by_item.setdefault(item_id, []).append(r)
    assert "PD-AR-047" in by_item, "стяжка >=80мм — обязательное правило из промпта"
    assert "PD-KR-020" in by_item, "W12 ростверк — обязательное правило из промпта"


def test_load_param_rules_rejects_bad_operator(tmp_path):
    bad = tmp_path / "bad_rules.yaml"
    bad.write_text(
        """
rules:
  - rule_id: bad_op_test
    item_ids: [PD-XX-001]
    parameter: test
    operator: "~~"
    value: 1
    unit: mm
    synonyms: []
    extract_patterns: ["(\\\\d+)\\\\s*мм"]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="operator"):
        load_param_rules(bad)


def test_load_param_rules_rejects_missing_item_ids(tmp_path):
    bad = tmp_path / "bad_rules2.yaml"
    bad.write_text(
        """
rules:
  - rule_id: no_items_test
    item_ids: []
    parameter: test
    operator: ">="
    value: 1
    unit: mm
    synonyms: []
    extract_patterns: ["(\\\\d+)\\\\s*мм"]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="item_ids"):
        load_param_rules(bad)


def test_load_param_rules_rejects_duplicate_rule_id(tmp_path):
    dup = tmp_path / "dup_rules.yaml"
    dup.write_text(
        """
rules:
  - rule_id: same_id
    item_ids: [PD-XX-001]
    parameter: test
    operator: ">="
    value: 1
    unit: mm
    synonyms: []
    extract_patterns: ["(\\\\d+)\\\\s*мм"]
  - rule_id: same_id
    item_ids: [PD-XX-002]
    parameter: test2
    operator: ">="
    value: 2
    unit: mm
    synonyms: []
    extract_patterns: ["(\\\\d+)\\\\s*мм"]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="same_id"):
        load_param_rules(dup)


# ── extract_value: числовые правила (мм) — стяжка ────────────────────────────────────────


def _rule(**kw) -> ParamRule:
    base = dict(
        rule_id="test_rule",
        item_ids=["PD-XX-001"],
        parameter="test_param",
        operator=">=",
        value=80.0,
        unit="mm",
        synonyms=[],
        extract_patterns=[r"(\d+(?:[.,]\d+)?)\s*мм"],
    )
    base.update(kw)
    return ParamRule(**base)


def test_extract_value_finds_thickness_in_mm_positive():
    rule = _rule()
    text = "Толщина стяжки пола выполнена 100 мм по всей площади паркинга."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == pytest.approx(100.0)
    assert extracted.unit == "mm"


def test_extract_value_finds_thickness_in_mm_negative_case():
    rule = _rule()
    text = "Толщина стяжки пола выполнена 50 мм — меньше нормативной."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == pytest.approx(50.0)


def test_extract_value_normalizes_cm_to_mm():
    rule = _rule(extract_patterns=[r"(\d+(?:[.,]\d+)?)\s*(мм|см|м)\b"])
    text = "Стяжка пола толщиной 10 см выполнена согласно проекту."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == pytest.approx(100.0)
    assert extracted.unit == "mm"


def test_extract_value_normalizes_m_to_mm():
    rule = _rule(extract_patterns=[r"(\d+(?:[.,]\d+)?)\s*(мм|см|м)\b"])
    text = "Уровень грунтовых вод ниже подошвы фундамента более чем на 1 м."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == pytest.approx(1000.0)
    assert extracted.unit == "mm"


def test_extract_value_returns_none_when_no_match():
    rule = _rule()
    text = "Стяжка пола запроектирована без указания толщины."
    assert extract_value(text, rule) is None


# ── T2.6 (баг 3, SESSION_LOG Запись 19): extract_patterns стяжки не должны цеплять чужие ──
# ── толщины из пирогов полов — только число в непосредственной связке со словом "стяжк*" ──
#
# Реальный smoke (docs/checklist_review/SMOKE_PD_O_FULL.json, item PD-AR-047) собрал жадным
# паттерном "3.0, 10.0, 30.0, 250.0, 4.0, 100.0" из СОСЕДНИХ материалов пирога пола
# (полимочевина 3мм, плиточный клей 10мм, чистовая отделка 30мм, фальш-пол 100-250мм,
# метилметакрилатное покрытие 4мм, керамогранит 10мм, трубопровод Ду100мм) — ни одно из этих
# чисел не является толщиной САМОЙ стяжки. Снипеты ниже — ДОСЛОВНО из evidence реального бага.


def _real_screed_rule():
    """Боевое правило из реестра (не синтетический `_rule()`) — тест бага именно на конфиге,
    который реально исполняется в проде, а не на изолированном паттерне."""
    rules = load_param_rules()
    return next(r for r in rules if r.rule_id == "screed_thickness_parking_min_80mm")


def test_screed_thickness_real_smoke_snippet_picks_screed_number_not_polimocheviya():
    rule = _real_screed_rule()
    text = (
        "| 441 |\n| Покрытие рамп с системой теплого пола |  |  |\n"
        "| Полимочевина - 3 мм | кв.м. | 1 133 |\n"
        "| Сталефибробетонная стяжка В30 с отопительными элементами - 97 мм | куб.м. | 110 |\n"
        "| Пленка парогидроиз"
    )
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == pytest.approx(97.0), (
        "должно матчиться число рядом со словом «стяжка» (97 мм), а не «Полимочевина - 3 мм»"
    )


def test_screed_thickness_real_smoke_snippet_picks_screed_number_not_plitochny_kley():
    rule = _real_screed_rule()
    text = (
        "ный слой - профилированная мембрана PLANTER geo или PLANTER exra- "
        "2) Плиточный клей - 10 мм 2) Цементно-песчанная стяжка - 30 мм "
        "2) Пластиковые опоры. Размер воздушного зазора, создаваемого опорами - "
    )
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == pytest.approx(30.0), (
        "должно матчиться число рядом со словом «стяжка» (30 мм), а не «Плиточный клей - 10 мм»"
    )


def test_screed_thickness_real_smoke_snippet_no_screed_word_returns_none_chistovaya_otdelka():
    rule = _real_screed_rule()
    text = (
        "менее 300 г/м2 1) Чистовая отделка пола - гранитные плиты - 30 мм каменной ваты, "
        "XPS,ТЕХНОНИКОЛЬ (или аналог) - от 20 11) Железобетонное основание см. раздел КР "
        "5) Кровельный ковер из 1 слоя битумосод"
    )
    assert extract_value(text, rule) is None, "нет слова «стяжка» в снипете — значение не найдено"


def test_screed_thickness_real_smoke_snippet_no_screed_word_returns_none_falsh_pol():
    rule = _real_screed_rule()
    text = (
        "раздел КР 11. Пол технических помещений СС: 12. Пол вестибюля с системой теплого пола: "
        "1. Устройство гидроизоляции фундамента и стен в грунте см. раздел КР. "
        "1) Фальш-пол - от 100 до 250 мм 1) Чистовая"
    )
    assert extract_value(text, rule) is None, "нет слова «стяжка» в снипете — значение не найдено"


def test_screed_thickness_real_smoke_snippet_screed_word_without_nearby_number_returns_none():
    rule = _real_screed_rule()
    text = (
        "раздел КР 7. Пол рампы: 8. Пол технических помещений: "
        "1) Метилметакрилатное шероховатое покрытие с кварцевым песком - 4 мм "
        "1) Чистовая отделка пола - керамогранит - 10 мм 2) Сталефибробетонная стяжка "
    )
    assert extract_value(text, rule) is None, (
        "слово «стяжка» есть, но её собственное число обрезано в снипете — не должно цеплять "
        "чужие «4 мм»/«10 мм» перед словом"
    )


def test_screed_thickness_real_smoke_snippet_number_before_screed_word_returns_none():
    rule = _real_screed_rule()
    text = (
        "предусмотрен \n\nтрубопровод Ду 100мм.) герметично соединенного с приемной воронкой. "
        "Отвод \n\nсбрасываемого теплоносителя от воронок осуществляется через трубопроводы в "
        "стяжке \n\nпола ИТП до сборного прия"
    )
    assert extract_value(text, rule) is None, (
        "«100мм» относится к трубопроводу и стоит ДО слова «стяжке» — не толщина стяжки"
    )


def test_screed_thickness_two_real_conflicting_values_still_conflict():
    """Конфликт двух НАСТОЯЩИХ значений стяжки (не искусственный, не случайное соседнее число)
    должен остаться конфликтом — ужесточение паттерна не должно ломать легитимный кейс."""
    rule = _real_screed_rule()
    snippet_a = "Стяжка пола в паркинге запроектирована толщиной 50 мм согласно спецификации АР."
    snippet_b = "Стяжка пола в паркинге запроектирована толщиной 100 мм согласно спецификации АР (лист 2)."
    val_a = extract_value(snippet_a, rule)
    val_b = extract_value(snippet_b, rule)
    assert val_a is not None and val_b is not None
    assert val_a.value == pytest.approx(50.0)
    assert val_b.value == pytest.approx(100.0)
    assert val_a.value != val_b.value


# ── extract_value: марки W (водонепроницаемость бетона) ─────────────────────────────────


def _w_rule() -> ParamRule:
    return ParamRule(
        rule_id="concrete_w_grade_rostverk",
        item_ids=["PD-KR-020"],
        parameter="concrete_water_resistance",
        operator="==",
        value="W12",
        unit="класс",
        synonyms=["марка бетона", "водонепроницаемость"],
        extract_patterns=[r"\b(W\d{1,2})\b"],
    )


def test_extract_value_finds_w_grade_positive():
    rule = _w_rule()
    text = "Принят бетон класса В30 W12 для ростверка и стен ниже уровня земли."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == "W12"
    assert extracted.unit == "класс"


def test_extract_value_finds_w_grade_negative_case():
    rule = _w_rule()
    text = "Принят бетон класса В30 W8 для ростверка."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == "W8"


# ── compare: числовые операторы ──────────────────────────────────────────────────────────


def test_compare_numeric_ge_ok():
    rule = _rule()
    extracted = ExtractedValue(value=100.0, unit="mm", raw_match="100 мм", source_snippet="...")
    result = compare(extracted, rule)
    assert isinstance(result, ComparisonResult)
    assert result.status == "ok"
    assert "100" in result.message and "80" in result.message


def test_compare_numeric_ge_issue():
    rule = _rule()
    extracted = ExtractedValue(value=50.0, unit="mm", raw_match="50 мм", source_snippet="...")
    result = compare(extracted, rule)
    assert result.status == "issue"
    assert "50" in result.message and "80" in result.message


def test_compare_numeric_le_ok():
    rule = _rule(operator="<=", value=1000.0)
    extracted = ExtractedValue(value=500.0, unit="mm", raw_match="500 мм", source_snippet="...")
    result = compare(extracted, rule)
    assert result.status == "ok"


def test_compare_numeric_le_issue():
    rule = _rule(operator="<=", value=1000.0)
    extracted = ExtractedValue(value=1500.0, unit="mm", raw_match="1500 мм", source_snippet="...")
    result = compare(extracted, rule)
    assert result.status == "issue"


# ── compare: равенство марок (W12 vs W8) ─────────────────────────────────────────────────


def test_compare_equality_w_grade_ok():
    rule = _w_rule()
    extracted = ExtractedValue(value="W12", unit="класс", raw_match="W12", source_snippet="...")
    result = compare(extracted, rule)
    assert result.status == "ok"


def test_compare_equality_w_grade_issue():
    rule = _w_rule()
    extracted = ExtractedValue(value="W8", unit="класс", raw_match="W8", source_snippet="...")
    result = compare(extracted, rule)
    assert result.status == "issue"
    assert "W8" in result.message and "W12" in result.message


# ── compare: contains / not_contains (алюминиевые жилы) ──────────────────────────────────


def _al_rule() -> ParamRule:
    return ParamRule(
        rule_id="aluminium_cores_external_networks",
        item_ids=["PD-EN-016"],
        parameter="cable_core_material",
        operator="contains",
        value="алюминиев",
        unit="",
        synonyms=["алюминиевые жилы", "кабель с алюминиевыми жилами"],
        extract_patterns=[r"(алюминиев\w*\s+жил\w*|кабел\w*\s+.{0,20}алюминиев\w*)"],
    )


def test_extract_value_contains_aluminium_positive():
    rule = _al_rule()
    text = "Для прокладки наружных сетей ЭС применяются кабели с алюминиевыми жилами АВБбШв."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert "алюминиев" in extracted.raw_match.lower()


def test_extract_value_contains_aluminium_negative_case():
    rule = _al_rule()
    text = "Для прокладки наружных сетей ЭС применяются кабели с медными жилами ВВГнг."
    assert extract_value(text, rule) is None


def test_compare_contains_ok():
    rule = _al_rule()
    extracted = ExtractedValue(
        value="алюминиевыми жилами", unit="", raw_match="алюминиевыми жилами", source_snippet="..."
    )
    result = compare(extracted, rule)
    assert result.status == "ok"


def _al_exception_rule() -> ParamRule:
    """PD-EOM-037: алюминиевые жилы допустимы, КРОМЕ классов ЖК Бизнес/Премиум — not_contains
    в разрезе конкретного класса ЖК (правило моделирует запрет для конкретного контекста снипета)."""
    return ParamRule(
        rule_id="aluminium_cores_forbidden_business_premium",
        item_ids=["PD-EOM-037"],
        parameter="cable_core_material_business_premium",
        operator="not_contains",
        value="алюминиев",
        unit="",
        synonyms=["алюминиевые жилы"],
        extract_patterns=[r"(алюминиев\w*\s+жил\w*)"],
    )


def test_compare_not_contains_ok_when_absent():
    """Класс ЖК Бизнес/Премиум, медные жилы — соответствует запрету на алюминий."""
    rule = _al_exception_rule()
    text = "ЖК класса Бизнес: для квартирных стояков применяются кабели с медными жилами ВВГнг-LS."
    extracted = extract_value(text, rule)
    # not_contains: extract_value честно возвращает None, если паттерн (алюминий) не найден —
    # это ОТСУТСТВИЕ найденного значения, а не автоматический "ok". Для not_contains начисление
    # "ok" происходит в compare через отдельный путь диспетчеризации (см. ниже, compare сам
    # решает по extracted is None + rule.operator == "not_contains").
    assert extracted is None


def test_compare_not_contains_issue_when_present():
    rule = _al_exception_rule()
    text = "ЖК класса Премиум: для квартирных стояков применяются кабели с алюминиевыми жилами АВВГ."
    extracted = extract_value(text, rule)
    assert extracted is not None
    result = compare(extracted, rule)
    assert result.status == "issue"
    assert "алюминиев" in result.message.lower()


# ── PD-KR-036: отметка деформационного шва (elevation, нормализация м->mm) ──────────────


def _elevation_rule(rules_by_id) -> ParamRule:
    return rules_by_id["mineral_slab_joint_above_zero_mark"]


def test_elevation_rule_extracts_and_normalizes_meters_to_mm():
    rules = {r.rule_id: r for r in load_param_rules()}
    rule = _elevation_rule(rules)
    text = "Минеральная плита применена в деформационных швах выше отметки +3,300 м."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == pytest.approx(3300.0)
    assert extracted.unit == "mm"
    result = compare(extracted, rule)
    assert result.status == "ok"


def test_elevation_rule_negative_below_zero_mark():
    rules = {r.rule_id: r for r in load_param_rules()}
    rule = _elevation_rule(rules)
    text = "Минеральная плита применена в шве на отметке -0,500 м (ниже нуля)."
    extracted = extract_value(text, rule)
    assert extracted is not None
    result = compare(extracted, rule)
    assert result.status == "issue"


# ── PD-KR-028: категория сложности грунтов III (строковое ==) ──────────────────────────


def test_geotech_category_rule_positive_match():
    rules = {r.rule_id: r for r in load_param_rules()}
    rule = rules["geotech_documentation_category_iii"]
    text = "Категория сложности грунтов участка — III, что подтверждено изысканиями."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == "III"
    result = compare(extracted, rule)
    assert result.status == "ok"


def test_geotech_category_rule_negative_match():
    rules = {r.rule_id: r for r in load_param_rules()}
    rule = rules["geotech_documentation_category_iii"]
    text = "Категория сложности грунтов на участке — II, простая."
    extracted = extract_value(text, rule)
    assert extracted is not None
    assert extracted.value == "II"
    result = compare(extracted, rule)
    assert result.status == "issue"


# ── PD-PB2-019: степень огнестойкости здания (contains) ────────────────────────────────


def test_fire_resistance_degree_rule_positive_match():
    rules = {r.rule_id: r for r in load_param_rules()}
    rule = rules["building_fire_resistance_degree"]
    text = "Указана II степень огнестойкости здания согласно СП 118.13330.2022."
    extracted = extract_value(text, rule)
    assert extracted is not None
    result = compare(extracted, rule)
    assert result.status == "ok"


def test_fire_resistance_degree_rule_no_match_when_absent():
    rules = {r.rule_id: r for r in load_param_rules()}
    rule = rules["building_fire_resistance_degree"]
    text = "Раздел ПБ не содержит указания степени огнестойкости здания."
    # "степень огнестойкости" присутствует текстуально, но без ведущей римской цифры —
    # честно None (нет извлекаемого значения), а не ложный ok.
    extracted = extract_value(text, rule)
    assert extracted is None


# ── conflicting snippets: extract_value должна вызываться дважды (сервис решает конфликт) ─


def test_extract_value_is_pure_per_snippet_conflict_handled_by_caller():
    """extract_value/compare работают на ОДНОМ тексте — конфликт между двумя хитами (W12 vs W8
    в разных документах) обнаруживает вызывающий код (checklist_review_service), не этот модуль."""
    rule = _w_rule()
    snippet_a = "Бетон ростверка В30 W12 согласно спецификации КР."
    snippet_b = "Бетон ростверка В30 W8 согласно спецификации КР (лист 2)."
    val_a = extract_value(snippet_a, rule)
    val_b = extract_value(snippet_b, rule)
    assert val_a is not None and val_b is not None
    assert val_a.value != val_b.value
    result_a = compare(val_a, rule)
    result_b = compare(val_b, rule)
    assert result_a.status == "ok"
    assert result_b.status == "issue"
