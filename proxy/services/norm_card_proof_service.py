"""Norm-card proof: a chosen шифр must be backed by the card the model was shown.

Why this module exists (measured, not assumed).  Installed build 929, both БАП cells
(`artifacts/live_929/installed929_bap_b0|b1/final.json`, reproduced by
`.test-tmp/repro_929_card_read_blocker.py`):

* B0_DIRECT: 19 work rows, 7 name a шифр, **0** of those chosen cards had
  `_evidence_check.card_body_shown = true`, and 6 of the 7 still carry money in the
  delivered XLSX (PDF!R4 → 151 446,11 руб. при исходном «Защитное укрытие», 116 м²).
* B1_CANDIDATE: 11 rows name a шифр, 0 shown, 10 of their cited refs sit in
  `grouped_model_evidence_pages[*].deferred_body_refs`; across the whole run the model
  was delivered 125 inventory pointers, 18 body entries and **3** complete cards, while
  `canonical_native_tools` offered `read_norm_card` on every answer call and
  `native_tool_call_identities` stayed empty.

So the model decided from the short pointer line (`[ref, status, norm_key, norm_code,
title, unit, source]`), never asked for the composition, and the application priced the
guess anyway.  The existing verdict `norm_card_body_unread`
(`lsr_norm_quality_gate_service.applicability_gap_kind`) only downgrades the readiness
report; nothing on the path parse → durable → calculator required the card to have been
read, and the architecture contract forbids the app from substituting the model's
professional decision.

The rule implemented here keeps both halves:

1. **Proof, not prose.**  A chosen norm counts as read only when the body of exactly that
   card identity was delivered (`card_body_shown is True`).  Presence in the search result
   and a short shown description are recorded separately by
   `model_rag_grouped_evidence_service.card_delivery_facts`; a parent cipher, another
   edition or another card never discharges the obligation.
2. **The read stays the model's own action.**  Nothing here calls `read_norm_card`: the
   architecture requires that an evidence read is requested by the model that owns the
   decision (`model_evidence_read_service.run_model_evidence_read_turn`, "Finish a turn only
   when the same model requests an evidence operation"), and the canon forbids substituting
   the model's professional choice.  When a packet comes back naming шифры whose cards were
   never shown, this module produces one bounded, visible *proof request* — the cited refs,
   the fact that only pointers were delivered, and the instruction to read them before the
   answer is final.  The answer is then taken again from the model on the same governed
   messages; if the model reads, the existing read machinery executes its calls, records
   receipts and re-renders the bodies; if it answers again without proof, the row keeps
   `norm_card_body_unread` and the acceptance control fails honestly.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

READ_TOOL = "read_norm_card"
WORK_ROLE = "work"
MAX_PROOF_REFS_PER_PACKET = 6
PROOF_REQUEST_TRACE = "norm_card_proof_requests"
TRACE_SCHEMA = "les.norm-card-proof-request.v1"
PROOF_PURPOSE = "sheet_pass_norm_proof"


def _txt(value: object) -> str:
    return " ".join(str(value if value is not None else "").replace("\xa0", " ").split())


def _cipher(value: object) -> str:
    code = _txt(value).upper().replace("Ё", "Е")
    for dash in ("–", "—", "‑", "−"):
        code = code.replace(dash, "-")
    return " ".join(code.split())


def is_work_row(row: Mapping[str, Any]) -> bool:
    """Only a row the product counts as a work can owe a norm card.

    Headers, notes and structure lines carry no шифр obligation; treating them as debtors
    would manufacture gaps and steal the repair budget from real works.
    """
    role = _txt(row.get("row_role")).casefold()
    if role == WORK_ROLE:
        return True
    if role and role != WORK_ROLE:
        return False
    # Rows parsed before the role column existed are judged by their content: a шифр plus
    # an addressed source row is a work, anything else is not.
    return bool(_txt(row.get("norm_code"))) and bool(_txt(row.get("source_row")))


def unread_candidates(row: Mapping[str, Any], shown_by_ref: set[str]) -> list[str]:
    """The refs this row itself cited that still owe a card body."""
    cited = [str(ref).strip().upper() for ref in (row.get("evidence_refs") or [])
             if str(ref).strip()]
    check = row.get("_evidence_check")
    deferred = [str(ref).strip().upper()
                for ref in ((check.get("deferred_card_refs") if isinstance(check, Mapping)
                             else []) or [])
                if str(ref).strip()]
    return [ref for ref in deferred or cited if ref not in shown_by_ref]


def unread_chosen_norm_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Every work row that names a шифр whose card body was not delivered.

    The installed 930 measured why the debt must be counted from the row, not from its refs:
    15 of the 17 БАП rows that named a шифр cited no card at all, so a refs-only view of the
    same run saw one debt while the other fourteen were paid for unseen.
    """
    unread: list[Mapping[str, Any]] = []
    for row in rows or ():
        if not isinstance(row, Mapping) or not _cipher(row.get("norm_code")):
            continue
        if not is_work_row(row):
            continue
        check = row.get("_evidence_check")
        if not isinstance(check, Mapping):
            continue
        if check.get("card_body_shown") is False:
            unread.append(row)
    return unread


def unread_chosen_norm_refs(rows: Sequence[Mapping[str, Any]],
                            *, chunks: Sequence[Any] = ()) -> list[str]:
    """Cited refs of chosen norms whose card body was not delivered.

    Only a row that names a шифр counts, and only a ref that the row itself cited.  A row
    without `_evidence_check` proves nothing either way, so it is not repaired here — the
    reader that builds the check owns that case.
    """
    shown_by_ref = delivered_refs_from_chunks(chunks)
    refs: list[str] = []
    for row in unread_chosen_norm_rows(rows):
        for ref in unread_candidates(row, shown_by_ref):
            if ref not in refs:
                refs.append(ref)
    return refs


def delivered_refs_from_chunks(chunks: Sequence[Any]) -> set[str]:
    """Refs whose full body is already in the delivered context of this attempt."""
    delivered: set[str] = set()
    for chunk in chunks or ():
        meta = getattr(chunk, "meta", None)
        if not isinstance(meta, Mapping):
            continue
        ref = str(meta.get("model_evidence_ref") or "").strip().upper()
        if not ref:
            continue
        if (meta.get("body_status") == "full"
                and meta.get("model_delivery_status") in (None, "", "delivered")):
            delivered.add(ref)
    return delivered


def proof_request_message(refs: Sequence[str], rows: Sequence[Mapping[str, Any]],
                          *, max_refs: int = MAX_PROOF_REFS_PER_PACKET) -> str:
    """The one bounded, visible reason why the answer came back unpriced.

    Names only facts the application owns and measured: these шифры were chosen, their cards
    were delivered as pointers, and the composition/unit/resources of a pointer were never
    shown, so the row cannot become a calculated position.  It states the technical way out
    (`read_norm_card` for that exact `evidence_ref`) without proposing, rejecting or
    replacing any norm — the professional choice remains the model's.

    Two shapes of debt are separated, because the 930 live pair showed they are not the same
    request: a row whose own cited ref still owes a body can be read directly, while a row
    that cited nothing (or only a card of another шифр) has no ref to read and must search
    first.
    """
    limited = [str(ref).strip() for ref in refs if str(ref).strip()][:max(0, int(max_refs))]
    readable: list[str] = []
    searchable: list[str] = []
    for row in unread_chosen_norm_rows(rows):
        locator = str(row.get("source_row") or row.get("work_id") or "?")
        cipher = _cipher(row.get("norm_code"))
        cited = unread_candidates(row, set())
        direct = next((ref for ref in cited if ref in limited), "")
        if direct:
            readable.append(f"- {direct} → {locator} (назван шифр {cipher}): вызови "
                            f"{READ_TOOL} с этим evidence_ref")
            continue
        names = ", ".join(dict.fromkeys(cited)) if cited else "ни одной карточки не цитировано"
        searchable.append(f"- {locator}: шифр {cipher}, ссылки в строке: {names} — найди норму "
                          f"через search_sources и прочитай её карточку через {READ_TOOL} "
                          "целиком")
    if not (readable or searchable):
        return ""
    lines = "\n".join(dict.fromkeys(readable))
    search_lines = "\n".join(dict.fromkeys(searchable))
    head = (
        "Ты назвал нормы, но их карточки тебе не показывали: в доставленном тексте по этим "
        "строкам не было полного тела карточки с названным шифром — только указатель (шифр, "
        "наименование, единица, источник) без состава работ, ресурсов и условий. Без прочитанной "
        "карточки такая строка не может стать рассчитанной позицией, и цена по ней не "
        "начисляется.\n"
    )
    if lines:
        head += f"{lines}\n"
    if search_lines:
        head += f"{search_lines}\n"
    return head + ("Перезполни эти строки по прочитанной карточке. Меняй шифр только если состав "
                   "прочитанной карточки этому противоречит; если карточка не подходит — оставь "
                   "строку с явной причиной, не угадывай.")


def record_proof_request(trace: dict[str, Any], *, sheet: str, packet: Sequence[str],
                         refs: Sequence[str], receipts: Sequence[Mapping[str, Any]],
                         attempt: int, unread_rows: Sequence[Mapping[str, Any]] = ()) -> None:
    """Write the visible fact that the application refused an unproven norm choice."""
    entry = {
        "schema": TRACE_SCHEMA,
        "sheet": _txt(sheet),
        "packet_locators": [str(item) for item in packet],
        "reason": "norm_card_body_unread",
        "refs": [str(ref) for ref in refs],
        "requested_reads": len(refs),
        "unread_norm_rows": len(unread_rows),
        "unread_ciphers": [_cipher(row.get("norm_code")) for row in unread_rows
                           if isinstance(row, Mapping)],
        "model_reads_after_request": len(receipts),
        "read_statuses": sorted({str(receipt.get("status") or "") for receipt in receipts}),
        "packet_attempt": int(attempt),
    }
    trace.setdefault(PROOF_REQUEST_TRACE, []).append(entry)


def proof_budget(*, configured: int | None = None, env_value: str | None = None) -> int:
    """Bounded refs per proof request: the cap is measured, not implied."""
    if configured is not None:
        return max(0, min(int(configured), MAX_PROOF_REFS_PER_PACKET))
    raw = str(env_value or "").strip()
    if raw.isdigit():
        return max(0, min(int(raw), MAX_PROOF_REFS_PER_PACKET))
    return MAX_PROOF_REFS_PER_PACKET

