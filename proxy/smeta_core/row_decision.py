"""Что именно решено по строке ведомости.

ЗАЧЕМ. В прогоне `sks-unit-20260911-0806` из 70 строк 8 закрылись фразой вида «входит в
стоимость монтажа», и проверить их было нечем: ни работы, в которую материал входит, ни
количества, ни основания. В книге такая строка не появляется вовсе, и отличить «учтено
ресурсом» от «забыли» невозможно — обе выглядят как пустое место (ревью Codex 11.09).

ЧТО ЗДЕСЬ. Взаимоисключающие виды решения и проверка полноты каждого. Вид —
утверждение сметчика о том, как строка попадает в смету:

    работа       строка считается по норме — есть шифр, количество и единица;
    материал     самостоятельная позиция сметы, нормой не считается;
    ресурс       материал входит в конкретную работу — нужны ссылка на эту работу,
                 количество и основание, иначе утверждение непроверяемо;
    уточнение    решение не принято, названа причина.
    раздел       модель явно признала строку заголовком и объяснила это; строка
                 сохраняется в реестре, но не становится рассчитанной работой.

ЧЕГО ЗДЕСЬ НЕТ. Суждения о правильности: модуль отвечает, полно ли решение, а не верно
ли оно. Строка с шифром и количеством считается полной, даже если норма выбрана неудачно.

ПОЧЕМУ НЕПОЛНОЕ РЕШЕНИЕ НЕ СТАНОВИТСЯ «УТОЧНЕНИЕМ» МОЛЧА. Подмена вида скрыла бы разницу
между «сметчик не смог решить» и «сметчик решил, но не обосновал»: первое — вопрос к
исходным данным, второе — к ответу. Вид сохраняется, а пробелы перечисляются отдельно.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


SCHEMA = "les.smeta.row-decision.v1"

WORK = "работа"
MATERIAL = "материал"
RESOURCE = "ресурс"
UNCLEAR = "уточнение"
SECTION = "раздел"

KINDS = (WORK, MATERIAL, RESOURCE, UNCLEAR, SECTION)


def operation_rows(decision: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Unpack stored authored operations; legacy single-row decisions stay valid."""
    operations = decision.get("operations")
    if isinstance(operations, list):
        return [dict(row) for row in operations if isinstance(row, Mapping)]
    return [dict(decision)]


# Операция, которая сама учитывает исходную строку: работа по норме, самостоятельный
# материал или количество, распределённое в ресурс работы.
ACCOUNTED_STATUSES = frozenset({"bound", "resource_bound", "material_bound"})
# Исполненное изменение состава, которое строку НЕ учитывает. Снятие материала нормы
# выполнено, но изделие и работа учитываются другими операциями (аудит Codex 17.09):
# одно снятие не может закрыть исходную строку.
# `material_not_supplied` — поставка, от которой модель отказалась с обоснованием
# (демонтаж): решение исполнено, строку учитывает работа.
EXECUTED_MODIFIER_STATUSES = frozenset({"resource_excluded", "material_not_supplied"})


def row_accounted(status: Any) -> bool:
    """Исходная строка учтена расчётом."""
    return str(status or "") in ACCOUNTED_STATUSES


def operation_executed(status: Any) -> bool:
    """Операция выполнена: учитывает строку либо исполнила изменение состава."""
    return str(status or "") in ACCOUNTED_STATUSES or str(status or "") in EXECUTED_MODIFIER_STATUSES


def source_resolved(status: Any) -> bool:
    """A model-recognized section is resolved without becoming a calculated work."""
    return row_accounted(status) or str(status or "") == "section_recognized"


def decision_resolved(status: Any) -> bool:
    """An executed modifier resolves its decision, but not its source by itself."""
    return operation_executed(status) or str(status or "") == "section_recognized"


def aggregate_operation_statuses(items: list[Mapping[str, Any]]) -> dict[str, str] | None:
    """A source is calculated only when every named operation is calculated.

    An executed modifier (resource exclusion) neither accounts for the source nor hides
    a failure of another operation: it does not overwrite a status, and a source made
    only of modifiers keeps the modifier status, which is not accounted.
    """
    result: dict[str, str] = {}
    operations: dict[str, set[str]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            return None
        key = str(item.get("source_row") or "").strip()
        status = str(item.get("status") or "").strip()
        work_id = str(item.get("work_id") or "").strip()
        previous = operations.setdefault(key, set())
        if not key or not status or (key in result and (not work_id or "" in previous or work_id in previous)):
            return None
        previous.add(work_id)
        if key in result and "section_recognized" in {result[key], status}:
            result[key] = "source_role_conflict"
            continue
        if status in EXECUTED_MODIFIER_STATUSES:
            result.setdefault(key, status)
            continue
        if key not in result or result[key] in ACCOUNTED_STATUSES or result[key] in EXECUTED_MODIFIER_STATUSES:
            result[key] = status
    return result

# Как модель называет вид решения. Ключи приводятся к нижнему регистру без точек.
KIND_WORDS: dict[str, str] = {
    "раздел": SECTION,
    "section": SECTION,
    "работа": WORK,
    "работа по норме": WORK,
    "норма": WORK,
    "work": WORK,
    "материал": MATERIAL,
    "самостоятельный материал": MATERIAL,
    "отдельный материал": MATERIAL,
    "material": MATERIAL,
    "ресурс": RESOURCE,
    "ресурс работы": RESOURCE,
    "входит в работу": RESOURCE,
    "входит в норму": RESOURCE,
    "учтён ресурсом": RESOURCE,
    "учтен ресурсом": RESOURCE,
    "resource": RESOURCE,
    "уточнение": UNCLEAR,
    "требуется уточнение": UNCLEAR,
    "не решено": UNCLEAR,
    "unclear": UNCLEAR,
}

# Фраза «входит в стоимость монтажа» без названного вида. Отрицание переворачивает смысл,
# поэтому «не входит в стоимость монтажа» сюда не попадает и остаётся самостоятельным
# материалом — проверено на строках прогона 11.09.
_INCLUDED = re.compile(
    r"(?<!не )(?<!не\s)(?:вход(?:ит|ят)|учт(?:ен|ена|ено|ены|ён|ёна|ёно|ёны)|включ(?:ен|ена|ено|ены|ён))"
    r"[^.;]{0,40}?(?:в\s+(?:стоимост|состав|работ|норм|монтаж|расцен)|ресурс)",
    re.IGNORECASE,
)
_DENIED = re.compile(r"\bне\s+(?:вход|учт|включ)", re.IGNORECASE)

# Ссылка на работу, в которую входит материал: якорь строки или шифр нормы.
# Якорь пишется и как «лист!позиция», и как «лист!R‹номер строки листа›» — обе формы
# встречаются в тексте ведомости и обе адресуют строку.
_NORM_CODE = re.compile(r"(?:ГЭСН|ТЕР|ФЕР)[а-яА-Я]{0,2}\d{2}-\d{2}-\d{3}-\d{2}")
_ROW_ANCHOR = re.compile(
    r"[^\s!]+![A-ZА-Я]?\d+|\bстрок[аиуе]?\s*№?\s*\d+", re.IGNORECASE
)


def _text(row: Mapping[str, Any], *names: str) -> str:
    parts = [str(row.get(name) or "").strip() for name in names]
    return " ".join(part for part in parts if part)


def _has_quantity(row: Mapping[str, Any]) -> bool:
    raw = str(row.get("quantity") or "").strip()
    if not raw:
        return False
    # Количество приходит текстом и может нести запятую как разделитель дробной части.
    return bool(re.search(r"\d", raw)) and raw not in {"0", "0,0", "0.0"}


def included_reference(row: Mapping[str, Any]) -> str:
    """Работа, в которую входит материал: явное поле, иначе шифр или якорь из текста.

    Без ссылки утверждение «входит в монтаж» не проверить: в книге не видно, к какой
    работе отнесён материал, и совпадение количеств проверить не с чем.
    """
    direct = str(row.get("included_in") or "").strip()
    if direct:
        return direct
    text = _text(row, "analogue", "coverage", "note")
    # Шифр в поле нормы при заявленном включении указывает на работу-хозяина: модель
    # кладёт его туда, потому что другого места для шифра в строке ответа нет.
    code = str(row.get("norm_code") or "").strip()
    if code and not explicit_absence(code) and _NORM_CODE.fullmatch(code):
        return code
    found = _NORM_CODE.search(text) or _ROW_ANCHOR.search(text)
    return found.group(0) if found else ""


def claims_inclusion(row: Mapping[str, Any]) -> bool:
    """Сказано ли, что материал учтён в составе работы."""
    text = _text(row, "analogue", "coverage", "note")
    if not text or _DENIED.search(text):
        return False
    return bool(_INCLUDED.search(text))


def decision_kind(row: Mapping[str, Any]) -> str:
    """Вид решения по строке.

    Явно названный вид имеет приоритет над разбором текста: это утверждение сметчика,
    а текст — его пересказ.
    """
    named = str(row.get("decision_kind") or row.get("kind") or "").strip().casefold().rstrip(".")
    if named in KIND_WORDS:
        return KIND_WORDS[named]
    # Заявление о включении проверяется раньше шифра. Сказав «входит в работу
    # ГЭСНм08-02-395-01», модель называет шифр той работы, а не норму этой строки: в
    # живом прогоне 11.09 так закрылись восемь строк крепежа, и по шифру они прошли бы
    # как самостоятельные работы по норме на лоток — каждая со своим количеством,
    # то есть лоток был бы посчитан девять раз.
    if claims_inclusion(row):
        return RESOURCE
    code = str(row.get("norm_code") or "").strip()
    if code and not explicit_absence(code):
        return WORK
    if str(row.get("analogue") or row.get("coverage") or "").strip():
        return MATERIAL if _looks_like_material(row) else UNCLEAR
    return UNCLEAR


def explicit_absence(code: str) -> bool:
    """Шифр, которым модель сообщает об отсутствии нормы, а не называет её."""
    clean = str(code or "").strip().casefold()
    return clean in {"", "-", "—", "нет", "не найдена", "норма не найдена", "отсутствует"}


def _looks_like_material(row: Mapping[str, Any]) -> bool:
    text = _text(row, "analogue", "coverage", "note").casefold()
    return any(
        word in text
        for word in ("материал", "оборудование", "поставка", "изделие", "прайс", "фссц")
    )


def section_reason(row: Mapping[str, Any]) -> str:
    """Read either authored explanation; an empty marker cannot hide the other field."""
    return next((str(row.get(key) or '').strip() for key in ('analogue', 'coverage')
                 if not explicit_absence(str(row.get(key) or ''))), '')


def section_conflicting_fields(row: Mapping[str, Any]) -> list[str]:
    """Report authored calculation instructions; never silently ignore them as a heading."""
    fields = [key for key in (
        "norm_code", "resource_code", "resource_action", "resource_quantity", "resource_unit",
        "included_in", "target_resource_code", "target_resource_id", "replaced_by",
        "price_source_ref", "material_review_status", "resource_review_status", "resource_review_ref",
        "coefficient_basis", "coefficient_target", "conversion_factor", "conversion_unit",
        "conversion_source", "nr_sp_rule_id",
    ) if not explicit_absence(str(row[key]) if row.get(key) is not None else "")]
    coefficient = row.get('coefficient')
    if not explicit_absence(str(coefficient) if coefficient is not None else ''):
        try:
            neutral = not isinstance(coefficient, bool) and float(str(coefficient).replace(',', '.')) == 1.0
        except (ValueError, TypeError):
            neutral = False
        if not neutral:
            fields.append('coefficient')
    return fields


def decision_gaps(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Чего не хватает, чтобы решение можно было проверить.

    Пустой кортеж означает полноту решения, а не его правильность.
    """
    kind = decision_kind(row)
    gaps: list[str] = []
    if kind == SECTION:
        if not section_reason(row):
            gaps.append('не названа причина')
        if section_conflicting_fields(row):
            gaps.append('раздел содержит расчётные указания')
    elif kind == WORK:
        if not _has_quantity(row):
            gaps.append("нет количества")
        if not str(row.get("unit") or "").strip():
            gaps.append("нет единицы измерения")
    elif kind == RESOURCE:
        # Три условия из ревью Codex 11.09: ссылка на работу, количество, основание.
        if not included_reference(row):
            gaps.append("не названа работа, в которую входит материал")
        if not _has_quantity(row):
            gaps.append("нет количества")
        if not str(row.get("analogue") or row.get("coverage") or "").strip():
            gaps.append("нет основания")
    elif kind == MATERIAL:
        if not _has_quantity(row):
            gaps.append("нет количества")
        if not str(row.get("unit") or "").strip():
            gaps.append("нет единицы измерения")
    else:
        if not str(row.get("analogue") or row.get("coverage") or "").strip():
            gaps.append("не названа причина")
    return tuple(gaps)


def describe_decision(row: Mapping[str, Any]) -> dict[str, Any]:
    """Вид решения, его полнота и ссылка на работу — в одном виде для отчёта и книги."""
    kind = decision_kind(row)
    gaps = decision_gaps(row)
    return {
        "schema": SCHEMA,
        "kind": kind,
        "complete": not gaps,
        "gaps": list(gaps),
        "included_in": included_reference(row) if kind == RESOURCE else "",
    }
