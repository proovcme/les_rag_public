"""Реестр параметрических правил checklist-review (T3.1, implementation_plan.md §3.3).

АРХИТЕКТУРА (промпт T3.1, ADR-11): «значение находит ретрив/regex, число сравнивает КОД». Этот
модуль — детерминированный компаратор поверх курируемого YAML-реестра
``config/checklists/glorax_param_rules.yaml``. Никакого LLM: extract_value работает regex'ами из
``extract_patterns`` правила, compare — обычная арифметика/строковое сравнение в Python.

Три публичные функции:
  - ``load_param_rules(path=None) -> list[ParamRule]`` — грузит + валидирует YAML (fail-closed,
    паттерн ``normcontrol_review_map_service.load_review_map``: любая кривизна схемы -> ValueError,
    не молчаливый дефолт);
  - ``extract_value(text, rule) -> ExtractedValue | None`` — первый regex-матч из
    ``rule.extract_patterns``, нормализация единиц (мм/см/м -> mm); нет матча -> None (честно,
    "значение не найдено" — не 0 и не ошибка);
  - ``compare(extracted, rule) -> ComparisonResult`` — сравнение кодом по ``rule.operator``:
    >=/<=  — числовое; == — числовое или строковое (нормализованное); contains/not_contains —
    подстрочное вхождение уже извлечённого значения.

Конфликт двух значений в разных RAG-хитах (W12 в одном источнике, W8 в другом) — НЕ решается
здесь: extract_value/compare чистые функции на одном тексте, разруливание конфликта — задача
вызывающего кода (``checklist_review_service._run_parametric``, T3.1 п.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_VALID_OPERATORS = {">=", "<=", "==", "contains", "not_contains"}
_NUMERIC_OPERATORS = {">=", "<="}

_PARAM_RULES_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "checklists" / "glorax_param_rules.yaml"
)

# Нормализация единиц длины в мм (regex `extract_patterns` может захватывать вторую группу — саму
# единицу — тогда extract_value нормализует; если единица не захвачена (паттерн без второй группы),
# берётся unit правила как есть, без пересчёта).
_LENGTH_TO_MM = {"мм": 1.0, "см": 10.0, "м": 1000.0}


@dataclass(frozen=True)
class ParamRule:
    """Одно параметрическое правило реестра. Поля — 1:1 со схемой YAML (см. модульный докстринг)."""

    rule_id: str
    item_ids: list[str]
    parameter: str
    operator: str
    value: object  # float для числовых операторов, str для ==/contains/not_contains на тексте
    unit: str
    synonyms: list[str]
    extract_patterns: list[str]


@dataclass(frozen=True)
class ExtractedValue:
    """Результат extract_value: найденное значение + unit + сырой матч + исходный текст (для evidence)."""

    value: object  # float (нормализовано в unit) либо str (марки/классы/подстроки)
    unit: str
    raw_match: str
    source_snippet: str


@dataclass(frozen=True)
class ComparisonResult:
    """Результат compare: статус ok|issue + человекочитаемое объяснение (для model_note/evidence)."""

    status: str  # "ok" | "issue"
    message: str


# ── load_param_rules ─────────────────────────────────────────────────────────────────────


def _need(rule: dict, key: str, ctx: str):
    value = rule.get(key)
    if value in (None, ""):
        raise ValueError(f"glorax_param_rules {ctx}: пустое/отсутствует обязательное поле '{key}'")
    return value


def load_param_rules(path: str | Path | None = None) -> list[ParamRule]:
    """Грузит и валидирует ``glorax_param_rules.yaml`` (fail-closed — любая кривизна схемы поднимает
    ``ValueError``, а не молча пропускает битую запись). ``path`` — переопределение файла (тесты)."""
    yaml_path = Path(path) if path is not None else _PARAM_RULES_PATH
    if not yaml_path.exists():
        raise FileNotFoundError(f"glorax_param_rules: файл не найден: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    raw_rules = data.get("rules") or []
    if not raw_rules:
        raise ValueError(f"glorax_param_rules {yaml_path}: пустой список rules")

    rules: list[ParamRule] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_rules):
        ctx = f"rules[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"glorax_param_rules {ctx}: правило должно быть словарём")

        rule_id = str(_need(raw, "rule_id", ctx))
        if rule_id in seen_ids:
            raise ValueError(f"glorax_param_rules: дублирующийся rule_id '{rule_id}'")
        seen_ids.add(rule_id)

        item_ids = raw.get("item_ids") or []
        if not isinstance(item_ids, list) or not item_ids:
            raise ValueError(f"glorax_param_rules {rule_id}: item_ids не должен быть пустым")

        operator = str(_need(raw, "operator", rule_id))
        if operator not in _VALID_OPERATORS:
            raise ValueError(
                f"glorax_param_rules {rule_id}: неизвестный operator '{operator}', "
                f"допустимые: {sorted(_VALID_OPERATORS)}"
            )

        value = raw.get("value")
        if value in (None, ""):
            raise ValueError(f"glorax_param_rules {rule_id}: value обязателен")

        extract_patterns = raw.get("extract_patterns") or []
        if not isinstance(extract_patterns, list) or not extract_patterns:
            raise ValueError(f"glorax_param_rules {rule_id}: extract_patterns не должен быть пустым")
        for pat in extract_patterns:
            try:
                re.compile(pat, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"glorax_param_rules {rule_id}: неверный regex '{pat}': {exc}") from exc

        rules.append(
            ParamRule(
                rule_id=rule_id,
                item_ids=[str(x) for x in item_ids],
                parameter=str(_need(raw, "parameter", rule_id)),
                operator=operator,
                value=value,
                unit=str(raw.get("unit") or ""),
                synonyms=[str(x) for x in (raw.get("synonyms") or [])],
                extract_patterns=[str(p) for p in extract_patterns],
            )
        )

    return rules


# ── extract_value ────────────────────────────────────────────────────────────────────────


def _normalize_length(raw_number: str, raw_unit: str | None) -> tuple[float, str]:
    """Приводит числовое значение длины к мм. ``raw_unit`` может быть None (паттерн без второй
    захватывающей группы) — тогда единица не пересчитывается, возвращается как есть (unit=mm по
    умолчанию для голого числа, т.к. все числовые length-правила реестра заданы в mm)."""
    num = float(raw_number.replace(",", "."))
    if raw_unit is None:
        return num, "mm"
    unit_key = raw_unit.strip().lower()
    factor = _LENGTH_TO_MM.get(unit_key)
    if factor is None:
        return num, unit_key
    return num * factor, "mm"


def extract_value(text: str, rule: ParamRule) -> ExtractedValue | None:
    """Ищет значение параметра в ``text`` по ``rule.extract_patterns`` (первый совпавший паттерн
    решает). Числовые правила (``operator`` в {>=, <=} либо ``==`` с числовым ``value``) —
    нормализуют единицу длины в mm. Строковые правила (марки W/EI/категории, contains/not_contains)
    — возвращают найденную подстроку как есть (без изменения регистра — обрезка/сравнение в
    ``compare``). Нет совпадения ни с одним паттерном -> ``None`` (значение не найдено, НЕ ошибка)."""
    if not text:
        return None

    is_numeric_rule = isinstance(rule.value, (int, float))

    for pattern in rule.extract_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        groups = match.groups()
        raw_match = match.group(0)

        if is_numeric_rule:
            if not groups or groups[0] is None:
                continue
            raw_unit = groups[1] if len(groups) > 1 else None
            value, unit = _normalize_length(groups[0], raw_unit)
            return ExtractedValue(value=value, unit=unit, raw_match=raw_match, source_snippet=text)

        # Строковый параметр (марка/класс/contains): группа 1, если есть, иначе весь матч.
        str_value = groups[0] if groups and groups[0] is not None else raw_match
        return ExtractedValue(
            value=str_value.strip(), unit=rule.unit, raw_match=raw_match, source_snippet=text
        )

    return None


# ── compare ───────────────────────────────────────────────────────────────────────────────


# По design (review 2026-07-07): operator=not_contains НИКОГДА не даёт автоматический yes —
# отсутствие упоминания в найденных снипетах не доказывает отсутствие в проекте
# (анти-галлюцинация); максимум review_needed с evidence, финал за инженером.
def compare(extracted: ExtractedValue, rule: ParamRule) -> ComparisonResult:
    """Сравнивает ``extracted.value`` с ``rule.value`` по ``rule.operator``. ЧИСЛА СРАВНИВАЕТ ТОЛЬКО
    ЭТОТ КОД — никакого LLM. Возвращает ``ComparisonResult(status, message)`` — человекочитаемое
    объяснение годится и для ``model_note``, и для ``computed_check``/evidence."""
    op = rule.operator
    unit_suffix = f" {rule.unit}" if rule.unit and rule.unit not in ("класс", "категория", "степень") else ""

    if op == ">=":
        ok = float(extracted.value) >= float(rule.value)
        msg = (
            f"{rule.parameter}: найдено {extracted.value:g}{unit_suffix}, "
            f"требуется >= {rule.value:g}{unit_suffix}."
        )
        return ComparisonResult("ok" if ok else "issue", msg)

    if op == "<=":
        ok = float(extracted.value) <= float(rule.value)
        msg = (
            f"{rule.parameter}: найдено {extracted.value:g}{unit_suffix}, "
            f"требуется <= {rule.value:g}{unit_suffix}."
        )
        return ComparisonResult("ok" if ok else "issue", msg)

    if op == "==":
        if isinstance(rule.value, (int, float)):
            ok = float(extracted.value) == float(rule.value)
        else:
            ok = str(extracted.value).strip().upper() == str(rule.value).strip().upper()
        msg = (
            f"{rule.parameter}: найдено «{extracted.value}», требуется «{rule.value}»."
            if not ok
            else f"{rule.parameter}: найдено «{extracted.value}», соответствует требуемому «{rule.value}»."
        )
        return ComparisonResult("ok" if ok else "issue", msg)

    if op == "contains":
        # extract_value уже нашла подстроку, содержащую rule.value (иначе паттерн бы не сматчился) —
        # compare здесь подтверждает найденное значение как соответствие требованию "должно быть".
        ok = str(rule.value).lower() in str(extracted.value).lower() or str(rule.value).lower() in extracted.raw_match.lower()
        msg = (
            f"{rule.parameter}: найдено «{extracted.raw_match}», подтверждает наличие «{rule.value}»."
            if ok
            else f"{rule.parameter}: найдено «{extracted.raw_match}», но «{rule.value}» не подтверждено."
        )
        return ComparisonResult("ok" if ok else "issue", msg)

    if op == "not_contains":
        # Если extract_value() что-то нашла — значит запрещённая подстрока ПРИСУТСТВУЕТ в тексте
        # (иначе паттерн, ищущий именно rule.value, не сматчился бы) -> issue. Ветка "не найдено"
        # (extracted is None) в этот compare никогда не приходит вызывающим кодом по контракту
        # extract_value/compare (см. checklist_review_service._run_parametric) — там отсутствие
        # extract_value() трактуется отдельно (не найдено -> review_needed, не автоматический ok).
        msg = (
            f"{rule.parameter}: найдено запрещённое «{extracted.raw_match}» — требование "
            f"«не содержит {rule.value}» нарушено."
        )
        return ComparisonResult("issue", msg)

    raise ValueError(f"compare: неизвестный operator '{op}'")  # недостижимо после load_param_rules
