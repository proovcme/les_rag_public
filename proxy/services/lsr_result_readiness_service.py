"""Operator-visible LSR readiness: coverage vs norms vs prices, plus file packaging."""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from proxy.services.lsr_source_coverage_service import (
    build_source_coverage,
    canonicalize_row_role,
    inferred_row_role,
)
from proxy.services.lsr_norm_quality_gate_service import (
    MODEL_GAP_REASONS,
    applicability_gap_kind,
    gap_reason_of,
)
from proxy.services.rim_lsr_trace_service import (
    BOOK_UNIT_CONFLICT_ACTION,
    RESOURCE_GROUP_ACTION,
    format_ruble_amount,
)

SCHEMA = "les.lsr-result-readiness.v1"

# What the durable packaging projection of a terminal job can assert about its
# document.  ``"none"`` is deliberately absent: it means "nothing was claimed",
# so the live file status keeps the wording in that case.
_DURABLE_DOCUMENT_STATES = frozenset({"ready", "draft_only", "pending"})

# A research job in one of these states will not process another packet, so no
# readiness line may send the operator to «Продолжить» to close a row.  The open
# rows of such a job are declared gaps that a person decides on.
FINISHED_RESEARCH_JOB_STATUSES = frozenset({"complete", "failed"})

_ABSENT_CODES = frozenset(
    {"", "-", "–", "—", "missing", "нет", "н/д", "n/a", "не найдено"}
)
_CIPHER_CELL_RE = re.compile(
    r"(?:гэсн|фер|тер)(?:мр|м|п|р)?[:\s]*\d{1,3}[-–]\d{1,2}[-–]\d{1,3}[-–]\d{1,2}[а-яё]?"
    r"|\d{1,3}[-–]\d{1,2}[-–]\d{1,3}[-–]\d{1,2}[а-яё]?",
    re.IGNORECASE,
)


def _selected_cipher(row: Mapping[str, Any]) -> str:
    """The authored cipher cell only: '-', MISSING and explanations are not norms."""

    raw = _text(row.get("norm_code") or row.get("code")).strip().strip("`* ")
    if not raw or raw.casefold() in _ABSENT_CODES:
        return ""
    return raw if _CIPHER_CELL_RE.fullmatch(raw) else ""
_CHOSEN_STATUSES = frozenset(
    {
        "EXACT",
        "ANALOGUE",
        "ANALOGUE_CANDIDATE",
        "EXACT_VERIFIED",
        "ANALOGUE_VERIFIED",
    }
)
_OPEN_STATUSES = frozenset(
    {"MISSING", "NEEDS_RESEARCH", "CONFLICT", "UNVERIFIED", ""}
)
# Which chosen status still needs what is kept in one place: the analogue question
# is a candidate the operator has to confirm, so it may appear in a draft but never
# in the closed set without its own substantiation (ADR-16 § 6, § 11 № 4).  That
# rule, and the EXACT citation rule beside it, live in
# ``lsr_norm_quality_gate_service.applicability_gap_kind`` — the same function the
# XLSX trace column reads, so one row cannot get two verdicts (§ 10).
_PRICE_SOURCE_LABEL = {
    "needs_kac": "КАЦ или выбранная ценовая книга",
    "needs_labor_rate": "ставка ОЗП",
    "needs_machinist_rate": "ставка ЗПМ",
    "needs_fgis_price": "цена эксплуатации машины ФГИС ЦС",
    "needs_price": "подтверждённая цена",
    "card_price_without_basis": "цена из карточки нормы, подтвердите базу, КАЦ или свою цену",
    # A book row the code refused to use because it prices the шифр per another
    # unit (task 2026-09-28 § 8, § 11 № 8).  Without this line the readiness card
    # would call the hole "подтверждённая цена" and the operator would confirm a
    # number without noticing that the unit is what is really open.
    BOOK_UNIT_CONFLICT_ACTION: "цена за единицу ресурса в позиции, книга даёт шифр в другой",
    # Task 2026-09-29 § 3: a group resource the book prices but the position has not
    # specified.  Without this line the readiness card would call the hole "подтверждённая
    # цена" and ask for a number, while what is open is which member of the family the
    # document means — and the first price of a group is not the group's price.
    RESOURCE_GROUP_ACTION: "конкретный ресурс группы из выбранной ценовой книги",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm_code(row: Mapping[str, Any]) -> str:
    return _text(row.get("norm_code") or row.get("code") or row.get("basis"))


def _norm_status(row: Mapping[str, Any]) -> str:
    return _text(row.get("norm_status")).upper()


def _locator(row: Mapping[str, Any]) -> str:
    return _text(row.get("source_row"))


def _preview(items: Sequence[str], *, limit: int = 8) -> str:
    values = [_text(item) for item in items if _text(item)]
    if not values:
        return ""
    shown = ", ".join(values[:limit])
    extra = len(values) - limit
    if extra > 0:
        shown += f" и ещё {extra}"
    return shown


def _structured_price_gaps(
    missing: Sequence[str],
    extra: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in extra:
        if not isinstance(item, Mapping):
            continue
        resource = _text(item.get("resource") or item.get("code"))
        key = resource or _text(item.get("action"))
        if not key or key in seen:
            continue
        seen.add(key)
        required = _text(item.get("required_source")) or _PRICE_SOURCE_LABEL.get(
            _text(item.get("price_action")), "подтверждённая цена"
        )
        quantity = item.get("quantity")
        action = _text(item.get("action")) or (
            f"Задайте цену для {resource or 'ресурса'}"
            + (f", количество {quantity}" if quantity not in (None, "") else "")
            + f". Источник: {required}."
        )
        gap = {
            "resource": resource,
            "quantity": quantity,
            "required_source": required,
            "action": action,
        }
        for key in (
            "code",
            "unit",
            "price_action",
            "position_code",
            "position_name",
            "dependent_calculations",
            "checked_basis",
            # § 3: a group question is useless without the members it offers, and the
            # delivered sheet is the only place the operator reads the question.
            "resource_group",
            "resource_candidates",
            "resources",
            "resource_total",
        ):
            if item.get(key) not in (None, "", [], {}):
                gap[key] = item[key]
        gaps.append(gap)
    for item in missing:
        text = _text(item)
        if not text.startswith("price_missing:"):
            continue
        code = text.split(":", 1)[-1].strip()
        if not code or code in seen:
            continue
        seen.add(code)
        gaps.append(
            {
                "resource": code,
                "quantity": None,
                "required_source": "подтверждённая цена или выбранная ценовая книга",
                "action": (
                    f"Задайте цену для ресурса {code}. "
                    "Отсутствие цены не отменяет выбранную норму."
                ),
            }
        )
    return gaps


# ``collect_lsr_workbook_gaps`` encodes an open row as ``row:<locator>:<status>``.
# The status is an internal code, so the readiness notice never prints it: the
# operator sees which professional question keeps the row uncalculated.  Naming
# the row's own status also keeps the prices line from ordering the operator to
# "close the norms" in a document whose norms dimension says "complete"
# (task § 10: one revision, one status, one wording).
_ROW_STATUS_LABEL = {
    "needs_input": "нужен авторский пересчёт единицы в единицу нормы",
    "missing_quantity": "объём не задан",
    "norm_not_found": "шифр не найден в нормативной базе",
    "norm_selection_required": "норма не выбрана",
    "unresolved": "роль строки не определена",
}
_ROW_STATUS_FALLBACK = "строка не рассчитана"


def _unbound_rows(missing: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in missing:
        text = _text(item)
        if not text.startswith("row:"):
            continue
        parts = [part.strip() for part in text.split(":")]
        locator = parts[1] if len(parts) > 1 else ""
        status = parts[2] if len(parts) > 2 else ""
        if not locator or (locator, status) in seen:
            continue
        seen.add((locator, status))
        rows.append(
            {
                "locator": locator,
                "status": status,
                "reason": _ROW_STATUS_LABEL.get(status, _ROW_STATUS_FALLBACK),
            }
        )
    return rows


def classify_norm_gap(row: Mapping[str, Any]) -> str:
    """Why this model row is not a closed professional selection."""

    role = inferred_row_role(row)
    if role in {"material", "equipment", "resource", "unresolved"}:
        return ""
    if canonicalize_row_role(row.get("row_role")) == "header":
        # A heading is accounted as structure; it never requires a mounting norm.
        return ""
    status = _norm_status(row)
    code = _norm_code(row)
    if status in _OPEN_STATUSES or code.casefold() in _ABSENT_CODES:
        if status == "CONFLICT":
            return "conflict"
        # Task 2026-09-29 § 3: an open row is not one kind of hole.  The model may
        # name which of the two causes that live inside its own answer applies —
        # the source line carries too little, or the cards it read all fail to fit.
        # The reason decides whose question the row becomes (the customer's or the
        # estimate engineer's); it never closes the row and code never invents one.
        reason = gap_reason_of(row)
        if reason in MODEL_GAP_REASONS:
            return reason
        if status == "NEEDS_RESEARCH":
            return "needs_research"
        return "missing_norm"
    if status and status not in _CHOSEN_STATUSES:
        return "open_status"
    if not code:
        return "missing_norm"
    # ADR-16 § 6 / task 2026-09-29 § 3: a written cipher is a choice, not yet a
    # substantiated choice.  The causes are distinguished by ``applicability_gap_kind``
    # — the same function the XLSX trace column reads, so one row cannot get two
    # different verdicts (§ 10): a citation naming another cipher, a token with no
    # card behind it, or an analogue whose five match facts were left unproven.
    return applicability_gap_kind(row)


def _own_words(row: Mapping[str, Any], *, limit: int = 180) -> str:
    """The model's own ``open_gap`` sentence, quoted and nothing rewritten.

    § 3 asks that a rejection reason be kept, and § 2 that the professional sense
    not be re-authored by code: the token says which kind of hole this is, the
    operator still reads the model's own explanation of it.
    """

    text = " ".join(_text(row.get("open_gap") or row.get("note")).split())
    if not text:
        return ""
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return f": {text}"


def gap_reason_action(
    kind: str,
    locator: str,
    row: Mapping[str, Any],
    *,
    research_finished: bool,
) -> str:
    """The operator question one declared reason raises (§ 3, § 11).

    The two causes a model may name need different answers, and neither is
    «continue searching»: a line whose own text is too thin is closed by the
    customer adding the characteristic, a line whose candidates were read and
    rejected is closed by the estimate engineer's professional decision.  Once the
    research is finished the second half has to say so, because «Продолжить» no
    longer reopens anything.
    """

    words = _own_words(row)
    finished_tail = (
        " Строка объявлена пробелом в листе «Проверка»; «Продолжить» для "
        "завершённого задания её не считает."
        if research_finished
        else ""
    )
    if kind == "insufficient_source_data":
        return (
            f"Строка {locator}: исходных сведений не хватает, чтобы выбрать норму"
            f"{words}. Их добавляет человек: уточните характеристику строки — "
            "код данных не додумывает и норму не выбирает." + finished_tail
        )
    return (
        f"Строка {locator}: предложенные карточки не подходят"
        f"{words}. Это решение сметчика, а не новый поиск: подтвердите обоснованный "
        "аналог, измените исходную строку или откажитесь от работы; код норму не "
        "подставит." + finished_tail
    )


def build_lsr_result_readiness(
    *,
    packaged: bool,
    packaging_failed: bool = False,
    packaging_code: str = "",
    rows: Sequence[Mapping[str, Any]] = (),
    missing: Sequence[str] = (),
    pricing_status: str = "",
    paused: bool = False,
    remaining_locators: Sequence[str] = (),
    catalog_work_count: int = 0,
    catalog_locators: Sequence[str] = (),
    price_gaps: Sequence[Mapping[str, Any]] = (),
    norm_conflicts: Sequence[Mapping[str, Any]] = (),
    price_basis: Mapping[str, Any] | None = None,
    calculated_positions: int = -1,
    confirmed_amount: float = -1.0,
    preliminary_amount: float = -1.0,
    row_projection: Sequence[Mapping[str, Any]] = (),
    document_state: str = "",
    download_url: str = "",
    job_status: str = "",
) -> dict[str, Any]:
    """Split technical file readiness from coverage, norms, and prices.

    ``row_projection`` is the revision's own per-operation projection (task
    2026-09-29 § 4): the stable identity of each row plus the seven questions the
    calculator answered for it.  When it is passed, "which works are still not
    calculated" is read from those rows; when it is not, the count is reported as
    unknown rather than derived by subtraction, because the subtraction was the
    defect (§ 4: «Нельзя subtract calculated_positions … из works»).
    """

    work_rows = [dict(row) for row in rows if isinstance(row, Mapping) and _locator(row)]
    # ``job_status`` is the durable state of the research, not of this answer:
    # once it is terminal, the advice below has to send the operator to the
    # declared gaps in the file instead of to a gesture that cannot continue.
    research_finished = _text(job_status).casefold() in FINISHED_RESEARCH_JOB_STATUSES
    remaining = [_text(item) for item in remaining_locators if _text(item)]
    cited = {_locator(row) for row in work_rows}
    wanted = [_text(item) for item in catalog_locators if _text(item)]
    if not wanted:
        wanted = list(dict.fromkeys([_locator(row) for row in work_rows] + remaining))
    coverage = build_source_coverage(
        catalog_locators=wanted,
        rows=work_rows,
        remaining_locators=remaining,
    )
    incomplete = set(coverage["incomplete_locators"])
    remaining = list(dict.fromkeys(
        [item for item in remaining if item not in cited or item in incomplete]
        + coverage["incomplete_locators"]
    ))
    if research_finished:
        # Coverage gaps are worded by the coverage service, which has no idea
        # the research is over.  A finished document must not send its operator
        # to a gesture that cannot close a row.
        coverage["gaps"] = [
            {
                **dict(gap),
                "action": (
                    f"Строка {gap.get('locator')} не закрыта и объявлена пробелом в "
                    "листе «Проверка»; «Продолжить» для завершённого задания её не считает."
                    if "Продолжите" in _text(gap.get("action"))
                    else _text(gap.get("action"))
                ),
            }
            for gap in (coverage.get("gaps") or [])
            if isinstance(gap, Mapping)
        ]
    norm_gaps: list[dict[str, str]] = []
    unbound = _unbound_rows(missing)
    # One row, one question (§ 10), asked by the hardest fact available: the
    # calculation layer already proved this cipher is absent from the normative
    # base, which outranks "the label carried no citation" — the citation would not
    # have made an unknown cipher known.
    base_absent_locators = {
        _text(item.get("locator")) for item in unbound if item.get("status") == "norm_not_found"
    }
    for row in work_rows:
        kind = classify_norm_gap(row)
        if not kind:
            continue
        locator = _locator(row)
        if kind == "cipher_without_cited_card" and locator in base_absent_locators:
            continue
        if kind == "conflict":
            action = (
                f"Проверьте применимость выбранного шифра {_norm_code(row) or 'без кода'} "
                f"для строки {locator}; код его не подменяет."
            )
        elif kind == "needs_research":
            if research_finished:
                action = (
                    f"Строка {locator} осталась без нормы и закрыта как объявленный "
                    "пробел в листе «Проверка»; новое исследование по ней не идёт."
                )
            else:
                action = (
                    f"Продолжите поиск нормы для строки {locator}. "
                    "Уже принятые строки повторно не ищутся."
                )
        elif kind == "cipher_not_in_cited_evidence":
            action = (
                f"Шифр {_norm_code(row)} в строке {locator} не совпадает с шифром "
                "приведённых карточек: подтвердите норму или укажите другую "
                "карточку; код шифр не подменяет."
            )
        elif kind == "cipher_without_cited_card":
            action = (
                f"Строка {locator}: шифр {_norm_code(row)} назван, но ни одна "
                "приведённая карточка его не называет — метка EXACT без ссылки на "
                "карточку остаётся необоснованным выбором. Укажите карточку этой "
                "нормы в evidence_refs или измените решение; код ссылку не "
                "дорисовывает и норму не выбирает."
            )
        elif kind == "analogue_needs_confirmation":
            action = (
                f"Строка {locator} выбрана аналогом ({_norm_code(row) or 'шифр не назван'}), "
                "но совпадение по формулировке работы, объекту, условиям, единице "
                "измерения и составу работ не подтверждено: аналог не закрывает "
                "позицию без вашего решения."
            )
        elif kind in MODEL_GAP_REASONS:
            action = gap_reason_action(
                kind, locator, row, research_finished=research_finished
            )
        else:
            action = (
                f"Модель должна выбрать норму для строки {locator} "
                "или явно оставить пропуск. Код шифр не подставляет."
            )
        norm_gaps.append({"locator": locator, "kind": kind, "action": action})
    # Task 2026-09-29 § 3: an unknown cipher is the third cause of an unready norm,
    # and the calculation layer already knows it (``norm_not_found``).  It used to be
    # reported only under «Цены» as an uncalculated row, which asked the operator for
    # a price on a line whose шифр the base does not hold.  One row, one question
    # (§ 10): the norm question is asked here, and the prices line stops repeating it.
    cipher_absent = [item for item in unbound if item.get("status") == "norm_not_found"]
    already_asked = {_text(gap.get("locator")) for gap in norm_gaps}
    for item in cipher_absent:
        locator = _text(item.get("locator"))
        if not locator or locator in already_asked:
            continue
        already_asked.add(locator)
        norm_gaps.append(
            {
                "locator": locator,
                "kind": "cipher_not_in_base",
                "action": (
                    f"Строка {locator}: названный шифр не найден в нормативной базе. "
                    "Это пробел нормы, а не цены: подтвердите шифр по карточке или "
                    "выберите другую норму; код в базу не обращается и шифр не меняет."
                ),
            }
        )
    unbound_priced = [item for item in unbound if item.get("status") != "norm_not_found"]
    for locator in remaining:
        gap_kind = "structure_incomplete" if locator in cited else "unprocessed"
        if research_finished:
            gap_action = (
                f"Строка {locator} не закрыта и объявлена пробелом в листе "
                "«Проверка»; «Продолжить» для завершённого задания её не считает."
            )
        else:
            gap_action = (
                f"Продолжите незакрытую строку {locator}. "
                "Повторный поиск уже обработанных строк не выполняется."
            )
        norm_gaps.append(
            {
                "locator": locator,
                "kind": gap_kind,
                "action": gap_action,
            }
        )
    if catalog_work_count and any(
        inferred_row_role(row) in {"material", "equipment", "resource"} for row in work_rows
    ) and not any(
        inferred_row_role(row) == "work" for row in work_rows
    ):
        norm_gaps.append({
            "locator": _locator(work_rows[0]),
            "kind": "missing_work_layer",
            "action": (
                "В исходнике есть позиции, но модель не выделила ни одной работы. "
                "Определите монтажные операции и их нормы либо подтвердите, что документ "
                "содержит только поставку."
            ),
        })

    # Task § 11 №8: the calculation layer reports a row whose own words name the
    # opposite operation from the chosen norm card.  Readiness asks the question;
    # it never rewrites the cipher the model selected.
    for conflict in norm_conflicts:
        if not isinstance(conflict, Mapping):
            continue
        locator = _text(conflict.get("locator")) or "без адреса строки"
        norm_gaps.append(
            {
                "locator": locator,
                "kind": "reversed_action",
                "action": (
                    f"Строка {locator} названа операцией «{_text(conflict.get('row_action'))}», "
                    f"а норма {_text(conflict.get('code')) or 'без шифра'} — "
                    f"«{_text(conflict.get('norm_action'))}»: подтвердите операцию "
                    "или выберите другую норму; код норму не подменяет."
                ),
            }
        )

    structured_prices = _structured_price_gaps(missing, price_gaps)
    basis_info = dict(price_basis or {})
    basis_match = _text(basis_info.get("match"))
    basis_note = _text(basis_info.get("note"))
    priced_complete = (
        not structured_prices
        and _text(pricing_status) in {"", "priced_final"}
        and not packaging_failed
    )
    if packaged and _text(pricing_status) in {"priced_partial", "norm_selection_required"}:
        priced_complete = False
    if structured_prices:
        priced_complete = False
    if basis_match in {"mismatch", "unspecified", "no_book"}:
        # A default book cannot complete an estimate when the operator never
        # selected a period, and a missing/mismatched book is not a price basis.
        priced_complete = False

    # The durable packaging projection of the job outranks the in-memory file
    # list: an intermediate draft must never be announced as the finished
    # document, and a terminal job without a final revision stays repairable.
    durable_state = _text(document_state).casefold()
    missing_final_document = durable_state in {"pending", "draft_only"}
    if packaged and missing_final_document:
        packaged = False
        packaging_failed = True
        packaging_code = packaging_code or (
            "DRAFT_ONLY_DOCUMENT" if durable_state == "draft_only"
            else "NO_FINAL_DOCUMENT"
        )

    if packaged and not packaging_failed:
        file_status = "ready"
        file_action = "Файл собран из сохранённых решений модели."
    elif packaging_failed:
        file_status = "failed"
        code = _text(packaging_code) or "WORKBOOK_GENERATION_FAILED"
        file_action = (
            f"Пересоберите файл без модели ({code}). "
            "Строки решения не пересматриваются."
        )
    elif work_rows:
        file_status = "missing"
        file_action = (
            "Пересоберите файл без модели по сохранённым строкам. "
            "Новый вызов модели не нужен."
        )
    else:
        file_status = "missing"
        file_action = "Сначала получите таблицу решений модели."

    norms_complete = not norm_gaps and (
        not catalog_work_count or len(cited) >= int(catalog_work_count)
    )
    if remaining:
        norms_complete = False
    coverage_complete = bool(coverage.get("complete"))
    if remaining:
        coverage_complete = False

    if paused and remaining:
        continue_action = (
            "Нажмите «Продолжить незакрытые строки». "
            "Источники и решения сохранены; поиск уже обработанного не повторяется."
        )
    elif paused:
        continue_action = (
            "Сборка остановлена. Можно пересобрать файл без модели "
            "или продолжить, если остались пробелы."
        )
    elif file_status == "ready" and (research_finished or not remaining):
        continue_action = (
            "Задание завершено. Повторный вход показывает эту ревизию; "
            "новое исследование не начинается."
        )
    else:
        continue_action = ""

    if coverage_complete:
        coverage_action = "Все исходные строки учтены как работа, материал, ресурс, заголовок или вопрос."
    else:
        coverage_action = (
            "Закройте покрытие исходника: каждая строка должна иметь роль. "
            f"{_preview([str(item.get('locator') or '') for item in coverage.get('gaps') or []])}."
        ).strip()

    if norms_complete:
        norms_action = "Все работы имеют выбранную норму или явный пропуск."
    elif research_finished and remaining:
        norms_action = (
            "Незакрытые строки объявлены пробелами в листе «Проверка»: "
            f"{_preview(remaining)}. Их закрывает решение человека, а не «Продолжить»."
        )
    elif remaining:
        norms_action = (
            "Продолжите незакрытые строки: "
            f"{_preview(remaining)}. Код нормы не выбирает."
        )
    else:
        norms_action = (
            "Закройте пробелы норм по конкретным строкам ниже. "
            "Код не подтверждает и не заменяет шифр."
        )

    if priced_complete:
        prices_action = "Цены закрыты по выбранным ресурсам."
    elif basis_match == "unspecified":
        prices_action = "Выберите город и уровень цен (квартал и год), затем пересоберите файл."
    elif basis_match == "no_book":
        # The operator chooses from the books that actually exist; a missing
        # basis never becomes a silently applied default (ADR-16 § 7).
        visible_books = [
            str(item).strip()
            for item in (basis_info.get("available_books") or [])
            if str(item or "").strip()
        ]
        listing = f" Доступно: {_preview(visible_books)}." if visible_books else ""
        if basis_info.get("requested_basis_present"):
            prices_action = (
                "Для выбранного города и периода нет ценовой книги, и другую не "
                "подменяют." + (listing or " Добавьте проверенный набор цен.")
            )
        else:
            prices_action = (
                "Выберите город и уровень цен (квартал и год): книга не подставлена "
                "молча, расчёт идёт по подтверждённым ценам и КАЦ."
                + (listing or " Локально нет ни одной ценовой книги.")
            )
    elif structured_prices:
        prices_action = (
            "Задайте подтверждённые цены: "
            f"{_preview([str(item.get('resource') or '') for item in structured_prices])}."
        )
    elif unbound_priced:
        # ``norm_not_found`` rows are asked about once, under «Нормы» (§ 3 / § 10):
        # telling the operator to set a price on a cipher the base does not hold
        # would be a second, wrong question about the same row.
        unbound_labels = [f"{row['locator']} — {row['reason']}" for row in unbound_priced]
        prices_action = (
            "Не рассчитаны строки: "
            f"{_preview(unbound_labels)}. "
            "Пересоберите файл без модели после их закрытия; принятые нормы "
            "и цены повторно не пересматриваются."
        )
    else:
        prices_action = (
            "Пересоберите файл без модели после закрытия норм; "
            "цены подставляются из выбранной книги. Отсутствие цены не обнуляет норму."
        )

    counts = {
        "works": sum(1 for row in work_rows if inferred_row_role(row) == "work"),
        "materials": sum(1 for row in work_rows if inferred_row_role(row) == "material"),
        "equipment": sum(1 for row in work_rows if inferred_row_role(row) == "equipment"),
        "headers": sum(1 for row in work_rows if canonicalize_row_role(row.get("row_role")) == "header"),
        "unresolved": sum(1 for row in work_rows if inferred_row_role(row) == "unresolved"),
        # Rows the application closed on its own bookkeeping because no model
        # offer produced a decision.  Reported apart from the model's own
        # "unresolved" so the customer can never read an application-side
        # stop-loss as a professional verdict.
        "declared_gaps": sum(
            1
            for row in work_rows
            if str(row.get("decision_origin") or "") == "declared_gap"
        ),
        "norms_selected": sum(
            1
            for row in work_rows
            if inferred_row_role(row) == "work" and _selected_cipher(row) and not classify_norm_gap(row)
        ),
        # distinct ciphers are reported apart from the per-operation count
        "norms_unique_ciphers": len(
            {
                _selected_cipher(row).casefold()
                for row in work_rows
                if inferred_row_role(row) == "work" and _selected_cipher(row) and not classify_norm_gap(row)
            }
        ),
    }
    if calculated_positions >= 0:
        counts["calculated_positions"] = int(calculated_positions)
    if confirmed_amount >= 0:
        counts["confirmed_amount"] = round(float(confirmed_amount), 2)
    if preliminary_amount >= 0:
        counts["preliminary_amount"] = round(float(preliminary_amount), 2)

    technical_complete = file_status == "ready"
    # A row the application closed on its own because no model offer produced a
    # decision is an admitted hole in the estimate, so it must block every
    # "complete" claim even though coverage is closed and no norm/price gap is
    # attached to an ``unresolved`` role.
    declared_gap_count = int(counts.get("declared_gaps") or 0)
    estimate_complete = bool(
        coverage_complete
        and norms_complete
        and priced_complete
        and technical_complete
        and declared_gap_count == 0
    )

    dimensions = {
        "file": {
            "ready": file_status == "ready",
            "status": file_status,
            "action": file_action,
        },
        # Task 2026-09-29 § 4: every open row travels in the payload.  A screen may
        # show a page of them, but the API and the delivered file are not cut at 80
        # rows — a truncated list reads as "these are all the gaps" (tracker #56).
        "coverage": {
            "complete": bool(coverage_complete),
            "gap_count": int(coverage.get("gap_count") or 0),
            "accounted": int(coverage.get("accounted") or 0),
            "catalog_count": int(coverage.get("catalog_count") or 0),
            "gaps": list(coverage.get("gaps") or []),
            "action": coverage_action,
        },
        "norms": {
            "complete": bool(norms_complete),
            "gap_count": len(norm_gaps),
            "gaps": norm_gaps,
            "action": norms_action,
        },
        "prices": {
            "complete": bool(priced_complete),
            "gap_count": len(structured_prices),
            "codes": [
                str(item.get("resource") or "")
                for item in structured_prices
                if item.get("resource")
            ],
            "gaps": structured_prices,
            "action": prices_action,
            "basis": basis_info,
        },
    }
    actions: list[dict[str, str]] = []
    # The finished document is reported in ``document`` rather than in the
    # repair-action list: "nothing outstanding" must keep meaning exactly that,
    # while a re-entered client still gets one pointer to the last revision.
    durable_document_notes = {
        "ready": "Последняя ревизия сохранена и доступна для скачивания.",
        "draft_only": (
            "Сохранена только промежуточная ревизия: итоговый документ не собран."
        ),
        "pending": (
            "Задание завершено, но итоговый файл не сохранён. "
            "Решения модели целы, файл пересобирается без повторного расчёта."
        ),
    }
    document_note = durable_document_notes.get(durable_state, "") or file_action
    document_offer = {
        # The durable record names the state the client can actually rely on:
        # "pending" and "draft_only" describe a finished job with no usable
        # document, where "failed" would suggest a packaging run that never
        # happened in this session.
        "state": (
            durable_state if durable_state in _DURABLE_DOCUMENT_STATES
            else file_status
        ),
        "durable_state": durable_state or "unknown",
        "file_status": file_status,
        "download_url": _text(download_url),
        "label": "Файл готов" if file_status == "ready" else "Файл не готов",
        "note": document_note,
    }
    if file_status != "ready" and work_rows:
        actions.append({"id": "repack", "label": "Пересобрать файл", "kind": "repack"})
    if remaining or paused:
        if not research_finished:
            actions.append(
                {"id": "resume", "label": "Продолжить незакрытые строки", "kind": "resume"}
            )
        elif file_status == "ready":
            # A terminal job has no packet left to continue, but its open rows
            # still need the operator's attention: the only gesture that can
            # answer it points at the revision carrying them as declared gaps.
            actions.append(
                {"id": "document", "label": "Скачать последнюю ревизию", "kind": "document"}
            )
    if work_rows and not estimate_complete and (not coverage_complete or not norms_complete):
        actions.append(
            {"id": "refine", "label": "Уточнить выбранные строки", "kind": "refine"}
        )
    if work_rows and not estimate_complete:
        actions.append(
            {
                "id": "enter_data",
                "label": "Внести подтверждённые данные",
                "kind": "enter_data",
            }
        )
    if file_status == "ready" and not estimate_complete:
        actions.append({"id": "repack", "label": "Пересобрать файл", "kind": "repack"})

    unique_actions: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in actions:
        key = item["id"]
        if key in seen:
            continue
        seen.add(key)
        unique_actions.append(item)

    # Four distinct not-ready states, grouped explicitly so an empty XLSX
    # formula cache is never misread as "zero calculated works".
    works_total = int(counts.get("works") or 0)
    projection = [dict(item) for item in row_projection if isinstance(item, Mapping)]
    projection_work = [
        item for item in projection if str(item.get("row_role") or "") == "work"
    ]
    # Task 2026-09-29 § 4: «Нельзя subtract calculated_positions (включает поставки)
    # из works, чтобы получить число нерешённых работ».  calculated_positions counts
    # positions of every role, so works minus it silently absorbs a supply line into
    # a work answer and can even report zero open works.  The revision's own
    # projection answers the question per operation; without one, the number is
    # unknown and is labelled as unknown instead of being guessed.
    if projection:
        calculation_incomplete = sum(
            1
            for item in projection_work
            if item.get("position_calculated") is not True
        )
        counts["works_with_calculated_position"] = sum(
            1
            for item in projection_work
            if item.get("position_calculated") is True
        )
    else:
        calculation_incomplete = None
    calc_known = bool(projection)
    if projection:
        counts["projected_operations"] = len(projection)
        # § 10: the file's own rows and the application's count of works are two
        # measurements of one thing, so both are reported.  A difference is visible to
        # the operator instead of being resolved by whichever number is prettier.
        counts["works_projected"] = len(projection_work)
        counts["works_counted"] = works_total
    gap_states = {
        "norm_missing": {
            "count": sum(
                1 for g in norm_gaps
                if g.get("kind") in {
                    "missing_norm",
                    "needs_research",
                    "conflict",
                    "cipher_not_in_base",
                }
            ),
            "meaning": (
                "Нет подтверждённой нормы: модель не выбрала шифр или норма не найдена."
            ),
        },
        # Kept apart from norm_missing: here a cipher IS written, and the missing
        # thing is the evidence behind it (ADR-16 § 6, § 10).  A first-pass EXACT
        # that cites no card holding that cipher belongs to this group, not to
        # norm_missing — task 2026-09-29 § 3 forbids reading the token alone as a
        # confirmation.
        "norm_unsubstantiated": {
            "count": sum(
                1 for g in norm_gaps
                if g.get("kind") in {
                    "cipher_not_in_cited_evidence",
                    "cipher_without_cited_card",
                    "analogue_needs_confirmation",
                }
            ),
            "meaning": (
                "Шифр выбран, но его применимость не подтверждена: карточки цитат "
                "содержат другой шифр, ссылка на карточку отсутствует, либо аналог "
                "оставлен без проверки совпадений."
            ),
        },
        "price_missing": {
            "count": len(structured_prices),
            "meaning": (
                "Нет подтверждённой цены ресурса; выбранная норма при этом сохраняется."
            ),
        },
        "calculation_incomplete": {
            "count": calculation_incomplete,
            "meaning": (
                "Работы, у которых позиция не посчитана до конца (проекция ревизии по "
                "каждой операции: структура, известная стоимость, полный расчёт)."
                if calc_known else
                "Приложение не передало проекцию операций; число нерешённых работ не "
                "выводится вычитанием рассчитанных позиций — они считают и поставки "
                "тоже (§ 4)."
            ),
        },
        "formula_cache_uncached": {
            "authoritative": "row_projection",
            "meaning": (
                "Итоги в XLSX — живые формулы СУММ без сохранённого кэша значений; "
                "их вычисляет пересчёт в Excel/LibreOffice. Пустой кэш формул НЕ равен "
                "нулю рассчитанных работ — опора на пословную проекцию ревизии и её "
                "расчётные данные."
            ),
        },
    }
    return {
        "schema": SCHEMA,
        "gap_states": gap_states,
        "paused": bool(paused),
        "remaining_locators": remaining,
        "catalog_work_count": int(catalog_work_count or len(wanted) or 0),
        "row_count": len(work_rows),
        "technical_complete": technical_complete,
        "estimate_complete": estimate_complete,
        "counts": counts,
        # § 4: the same per-operation projection the «Проверка» sheet prints, so the
        # chat card, the API and the file answer each of the seven questions the same
        # way for the same row.  Uncut: a screen may paginate it, the payload may not.
        "row_projection": projection,
        "coverage": coverage,
        "dimensions": dimensions,
        "actions": unique_actions,
        "document": document_offer,
        "continue_action": continue_action,
    }


def _lsr_basis_suffix(match: str, note: str, book: str = "") -> str:
    """Explicit price-basis line; the code never silently reconciles periods.

    Task 2026-09-28 § 7 asks *every* result for the basis it was computed in, its
    source and the identifier of the price book, so a basis that was applied
    correctly is stated as plainly as one that was not.  Naming only the broken
    case made build 822 answer «Период «3 квартал 2026 года» … отсутствует, цены не
    рассчитаны» in the same turn in which the code had bound ``sankt-peterburg_3kv2026``
    and printed a preliminary amount: the operator could not see, from the chat
    alone, which book the file was priced in — while the delivered XLSX said so on
    its own header line («Книга цен: …»), which is the § 10 contradiction this closes.
    """

    body = _text(note)
    book_id = _text(book)
    book_bit = f" Книга цен: {book_id}." if book_id and book_id not in body else ""
    if match == "mismatch":
        return " Ценовая база не совпадает с запрошенной." + (
            f" {body}" if body else ""
        ) + book_bit
    if not body:
        return f" Ценовая база: Книга цен: {book_id}." if book_id else ""
    if body.startswith("Ценовая база"):
        # the projection already words itself («Ценовая база совпадает с запросом: …»,
        # «Ценовая база этого документа сохранена …»); repeating the label only
        # made the line harder to read.
        return f" {body}{book_bit}"
    return f" Ценовая база: {body}{book_bit}"


def format_lsr_readiness_notice(
    readiness: Mapping[str, Any] | None,
    *,
    filename: str = "",
) -> str:
    """Visible coverage / norms / prices status next to the workbook link."""

    payload = dict(readiness or {})
    dimensions = payload.get("dimensions") if isinstance(payload.get("dimensions"), Mapping) else {}
    file_dim = dimensions.get("file") if isinstance(dimensions.get("file"), Mapping) else {}
    coverage_dim = (
        dimensions.get("coverage") if isinstance(dimensions.get("coverage"), Mapping) else {}
    )
    norms_dim = dimensions.get("norms") if isinstance(dimensions.get("norms"), Mapping) else {}
    prices_dim = dimensions.get("prices") if isinstance(dimensions.get("prices"), Mapping) else {}
    file_bit = f" Файл: {filename}." if filename else ""
    file_ready = bool(file_dim.get("ready"))
    coverage_complete = bool(coverage_dim.get("complete"))
    norms_complete = bool(norms_dim.get("complete"))
    prices_complete = bool(prices_dim.get("complete"))
    basis_dim = (
        prices_dim.get("basis") if isinstance(prices_dim.get("basis"), Mapping) else {}
    )
    basis_match = _text(basis_dim.get("match"))
    basis_note = _text(basis_dim.get("note"))
    basis_book = _text(basis_dim.get("actual_book"))
    # § 7: the basis is named whether it matched, was inherited, contradicted the
    # request or could not be bound at all — silence about a good basis is still a
    # result that does not show what it was computed in.
    basis_visible = bool(basis_note or basis_book)
    counts = payload.get("counts") if isinstance(payload.get("counts"), Mapping) else {}
    declared_count = int(counts.get("declared_gaps") or 0)
    if (
        file_ready
        and coverage_complete
        and norms_complete
        and prices_complete
        and declared_count == 0
    ):
        done_line = f"ЛСР собрана.{file_bit}".strip()
        if basis_visible:
            done_line += _lsr_basis_suffix(basis_match, basis_note, basis_book)
        return done_line
    parts = [f"ЛСР собрана частично.{file_bit}".strip()]
    if counts:
        composition = (
            f"Состав: работ {int(counts.get('works') or 0)}, материалов "
            f"{int(counts.get('materials') or 0)}, оборудования {int(counts.get('equipment') or 0)}, "
            f"заголовков {int(counts.get('headers') or 0)}, нерешённых {int(counts.get('unresolved') or 0)}; "
            f"норм выбрано {int(counts.get('norms_selected') or 0)}"
        )
        if int(counts.get("declared_gaps") or 0):
            composition += (
                f", из них {int(counts['declared_gaps'])} строк закрыто приложением "
                "как пробел (модель не дала решения)"
            )
        if counts.get("calculated_positions") is not None:
            composition += f", позиций рассчитано {int(counts['calculated_positions'])}"
        if counts.get("confirmed_amount") is not None:
            composition += (
                ". Подтверждённая сумма "
                f"{format_ruble_amount(counts['confirmed_amount'])}, предварительная "
                f"{format_ruble_amount(counts.get('preliminary_amount') or 0)}"
            )
        parts.append(composition + ".")
    file_label = "файл готов" if file_ready else "файл не готов"
    parts.append(f"Файл: {file_label}. {_text(file_dim.get('action'))}".strip())
    if coverage_complete:
        parts.append("Покрытие исходника: полное.")
    else:
        parts.append(
            f"Покрытие исходника: не полное ({int(coverage_dim.get('gap_count') or 0)}). "
            f"{_text(coverage_dim.get('action'))}".strip()
        )
    if norms_complete:
        parts.append("Нормы: полные.")
    else:
        parts.append(
            f"Нормы: не полные ({int(norms_dim.get('gap_count') or 0)}). "
            f"{_text(norms_dim.get('action'))}".strip()
        )
    if prices_complete:
        parts.append("Цены: полные.")
    else:
        parts.append(
            f"Цены: не полные ({int(prices_dim.get('gap_count') or 0)}). "
            f"{_text(prices_dim.get('action'))}".strip()
        )
    if basis_visible:
        parts.append(_lsr_basis_suffix(basis_match, basis_note, basis_book).strip())
    if declared_count:
        parts.append(
            f"Пробелов, закрытых приложением без решения модели: {declared_count}. "
            "Норма и цена для них не подобраны и не выдуманы; строки видны в файле "
            "с явной причиной."
        )
    continue_action = _text(payload.get("continue_action"))
    if continue_action:
        parts.append(continue_action)
    gap_lists = list(coverage_dim.get("gaps") or []) + list(norms_dim.get("gaps") or [])
    gap_lists.extend(list(prices_dim.get("gaps") or []))
    concrete = [
        _text(item.get("action"))
        for item in gap_lists[:6]
        if isinstance(item, Mapping) and _text(item.get("action"))
    ]
    if concrete:
        parts.append("Требуемые действия: " + " ".join(concrete))
    return " ".join(part for part in parts if part)
