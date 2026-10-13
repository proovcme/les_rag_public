"""Ask the model to name a concrete book resource when the read card cites a group.

Measured on the installed 931 (``artifacts/live_931/installed931_big_b1/``): the customer's big
ВОР produced 12 position blocks, 7 of them priced, and the cipher behind every priced block had
its card read — the norm-card hole from 929/930 is closed.  All seven blocks nevertheless stayed
uncalculated: ``calculated_positions = 0`` and ``confirmed_amount = 0.00``, because each carries
``open_reasons = ["price_missing:<код>"]`` with ``price_action = "unresolved_resource_group"``.
The codes are real groups of the chosen book, verified read-only against the installed
``sankt-peterburg_3kv2026``: ``11.2.11.01`` has no row but 10 members (``11.2.11.01-0001``,
``…-0027``, …) and ``04.3.01.12`` has 7.  The card names the family, the book prices the members,
and nothing between the read and the calculator asks anyone to pick a member — so the row is
drafted, priced partially, and never closes.

This module owns that ask, and only the ask:

1. the group is detected with the same helper the calculator uses
   (``rim_lsr_trace_service.resource_group_state``), so both engines stop on the same row instead
   of producing two sums (ADR-16 § 10);
2. the message lists concrete members of the *chosen* price book with their units and prices and
   names the model's own operations (``search_pricebook_resources``, ``read_resource_price``).
   It never picks a member: the first row of a family is not the family's price, and an amount
   built on it would be a sum the document never asked for;
3. one bounded round per packet, inside the same research stage as the norm-card proof — the
   application does not open a new cycle after the terminal answer and does not substitute the
   model's professional decision;
4. whatever the model leaves unresolved keeps its existing ``price_missing:<код>`` gap and stays
   out of the confirmed money.  Nothing here promotes a status.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

SEARCH_TOOL = "search_pricebook_resources"
PRICE_TOOL = "read_resource_price"
# The target identifies the original norm slot; resource_code carries the authored replacement.
# Confusing the two makes a valid member fail lookup against the unchanged norm resources.
BINDING_FIELD = "resource_bindings"
BINDING_TARGET_FIELD = "target_resource_code"
BINDING_SELECTION_FIELD = "resource_code"
MAX_GROUPS_PER_PACKET = 4
MAX_MEMBERS_SHOWN = 6
PROOF_REQUEST_TRACE = "resource_group_proof_requests"
TRACE_SCHEMA = "les.resource-group-proof-request.v1"
PROOF_PURPOSE = "sheet_pass_resource_group_proof"


def _txt(value: object) -> str:
    return " ".join(str("" if value is None else value).replace("\xa0", " ").split())


def _cipher(value: object) -> str:
    return _txt(value).upper().replace("Ё", "Е")


def read_card_resources(chunks: Sequence[Any]) -> list[dict[str, Any]]:
    """Resources of the cards the model actually read in this attempt.

    Only an ``exact_card_read`` body counts: a pointer or a preview line does not carry the
    composition, and asking about a resource the model never saw would be the application
    inventing debt.
    """
    found: list[dict[str, Any]] = []
    for chunk in chunks or ():
        meta = getattr(chunk, "meta", None)
        if not isinstance(meta, Mapping) or meta.get("exact_card_read") is not True:
            continue
        cipher = _cipher(meta.get("norm_code"))
        if not cipher:
            continue
        for resource in meta.get("resources") or ():
            if not isinstance(resource, Mapping) or not _txt(resource.get("code")):
                continue
            found.append({
                "cipher": cipher,
                "ref": _txt(meta.get("model_evidence_ref")),
                "code": _txt(resource.get("code")),
                "name": _txt(resource.get("name")),
                "unit": _txt(resource.get("unit")),
                "kind": _txt(resource.get("kind")),
            })
    return found


def unresolved_groups(rows: Sequence[Mapping[str, Any]], chunks: Sequence[Any], *,
                      pricebook: Any, max_groups: int = MAX_GROUPS_PER_PACKET,
                      member_limit: int = MAX_MEMBERS_SHOWN) -> list[dict[str, Any]]:
    """Card resources the chosen book prices only as a family, with their concrete members.

    A row must name the cipher and be a work row; the code must be a family the book does price
    (``unresolved_resource_group``) — a code that is neither a book row nor a family is a
    different hole and stays with the existing ``needs_*`` ladder.
    """
    from proxy.services.rim_lsr_trace_service import resource_group_state

    if pricebook is None:
        return []
    chosen = {row_cipher for row in (rows or ()) if isinstance(row, Mapping)
              and (row_cipher := _cipher(row.get("norm_code")))
              and _txt(row.get("row_role")).casefold() in ("", "work")}
    locators: dict[str, str] = {}
    for row in (rows or ()):
        if isinstance(row, Mapping):
            cipher = _cipher(row.get("norm_code"))
            if cipher and cipher not in locators:
                locators[cipher] = _txt(row.get("source_row"))
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for resource in read_card_resources(chunks):
        if resource["cipher"] not in chosen:
            continue
        state = resource_group_state(dict(resource), pricebook)
        if str((state or {}).get("state") or "") != "unresolved_resource_group":
            continue
        key = (resource["cipher"], resource["code"])
        if key in seen:
            continue
        seen.add(key)
        members = [member for member in (state.get("members") or []) if isinstance(member, Mapping)]
        items.append({
            "locator": locators.get(resource["cipher"], ""),
            "cipher": resource["cipher"],
            "ref": resource["ref"],
            "group": _txt(state.get("group")) or resource["code"],
            "code": resource["code"],
            "name": resource["name"],
            "unit": resource["unit"],
            "total": int(state.get("total") or 0),
            "members": members[:max(1, int(member_limit))],
            "truncated": bool(state.get("truncated")),
        })
    return items[:max(0, int(max_groups))]


def proof_request_message(groups: Sequence[Mapping[str, Any]]) -> str:
    """The bounded, visible reason why a read card still cannot become a calculated position.

    Facts only: this cipher was read, its card cites this group, the chosen book prices this many
    concrete members of it, and here they are with their own units and prices.  Choosing a member
    belongs to the model; the application neither picks one nor accepts a family price.

    The message also names the **field** the choice has to land in, because that is what installed
    935 measured (``artifacts/live_935/installed935_bap_b1/``, row ``PDF!R4``): the model did pick
    a concrete member (``01.7.07.12-0024``) but wrote it on a separate material row, while the work
    row kept ``resource_bindings[].target_resource_code = 01.7.07.12`` — correctly naming the old
    slot, but without ``resource_code``, unit or a quantity basis for the replacement. Build 936
    then incorrectly asked to change the target to the selected member. The real binding contract
    matches the target against the original norm and builds the replacement from resource_code;
    naming these roles correctly is transport, not a professional choice. The application never
    copies a code from a separate material row or selects a member itself.
    """
    if not groups:
        return ""
    blocks: list[str] = []
    for group in groups:
        rows = [_txt(member.get("code")) + " — " + _txt(member.get("name")) + ", "
                + _txt(member.get("unit")) + ", " + _txt(member.get("price_current_eff"))
                for member in (group.get("members") or []) if isinstance(member, Mapping)]
        members = "\n".join("    · " + row for row in rows)
        rest = max(0, int(group.get("total") or 0) - len(rows))
        tail = (f"\n    · ещё {rest}; полный список даёт {SEARCH_TOOL} по этому коду"
                if group.get("truncated") and rest > 0 else "")
        blocks.append(
            f"- {group.get('cipher')} (строка {group.get('locator') or '?'}): ресурс "
            f"{group.get('code')} «{group.get('name')}», {group.get('unit')} — в выбранной "
            f"книге это группа из {group.get('total')} конкретных ресурсов:\n{members}{tail}")
    return (
        "Карточки ты прочитал, но позиция всё равно не становится рассчитанной: норма ссылается "
        "на групповой код ресурса, а ценовая книга считает конкретный ресурс этой группы. Цены у "
        "группы не существует — первая строка группы не является ценой группы, и сумма, собранная "
        "на ней, была бы суммой, которую документ никогда не просил. Выбери сам конкретный ресурс "
        f"из выбранной книги и проверь цену через {PRICE_TOOL}, а список группы — через "
        f"{SEARCH_TOOL}. Перезаполняй только те строки, где состав прочитанной карточки "
        "действительно отсылает к группе. Если замена обоснована, оформи action=replace в "
        f"{BINDING_FIELD} самой строки работы: {BINDING_TARGET_FIELD} — исходный групповой код "
        "ресурса нормы (либо точный target_resource_ref из прочитанной карточки); "
        f"{BINDING_SELECTION_FIELD} — код выбранного конкретного ресурса; resource_name и unit — "
        "его название и единица из показанного источника. Для обоснованного сохранения расхода "
        "исходного ресурса при совместимых единицах явно задай quantity_basis=target_norm: "
        "код пересчитает расход и масштаб измерителя нормы. Если требуется иной расход, "
        "quantity_basis=explicit и quantity задают полный физический расход числом с основанием; "
        "не записывай арифметическое выражение вместо числового JSON-значения. В reason объясни "
        "выбор и расход; source_refs должны ссылаться на прочитанную карточку исходного ресурса "
        "и показанный выбранный ресурс, basis_ref — на исходную строку или показанное основание. "
        "Отдельная строка материала с этим кодом замену в ресурсах строки работы не закрывает. "
        "При неподтверждённом выборе, расходе или несовместимых единицах сохрани конкретный "
        "open_gap; не подставляй произвольный ресурс или количество:\n"
        + "\n".join(blocks)
    )


def record_proof_request(trace: dict[str, Any], *, sheet: str, packet: Sequence[str],
                         groups: Sequence[Mapping[str, Any]], answered: bool,
                         attempt: int, answer_parsed: bool = True,
                         receipts: Sequence[Mapping[str, Any]] = ()) -> None:
    """Write the visible fact that the application refused a family price.

    ``model_answered`` and ``answer_parsed`` are different facts: a round can come back with text
    the application cannot read as a table, and that has to stay visible instead of looking like
    the model never answered.  ``receipts`` counts the model's own price-lookup calls executed
    after the request — installed 934 measured that the round's first answer was a native
    ``read_resource_price`` call, and a round that only reads text loses it.
    """
    entry = {
        "schema": TRACE_SCHEMA,
        "sheet": _txt(sheet),
        "packet_locators": [str(item) for item in packet],
        "reason": "unresolved_resource_group",
        "groups": [{"cipher": group.get("cipher"), "group": group.get("group"),
                    "locator": group.get("locator"),
                    "members_offered": len(group.get("members") or [])}
                   for group in groups],
        "requested": len(groups),
        "model_answered": bool(answered),
        "answer_parsed": bool(answer_parsed),
        "model_calls_after_request": len(receipts),
        "call_statuses": sorted({str(receipt.get("status") or "") for receipt in receipts}),
        "packet_attempt": int(attempt),
    }
    trace.setdefault(PROOF_REQUEST_TRACE, []).append(entry)


def proof_budget(*, configured: int | None = None, env_value: str | None = None) -> int:
    """Bounded groups per request: the cap is measured, not implied."""
    if configured is not None:
        return max(0, min(int(configured), MAX_GROUPS_PER_PACKET))
    raw = _txt(env_value)
    if raw.isdigit():
        return max(0, min(int(raw), MAX_GROUPS_PER_PACKET))
    return MAX_GROUPS_PER_PACKET
