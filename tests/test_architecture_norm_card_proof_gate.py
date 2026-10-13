"""Gate regressions for the norm-card proof seam (build 929 blocker § 3, 930 live hole).

One seam, four links, each with the mutation that would silently return the old behaviour: an
inventory pointer, a guessed шифр, no verdict for a row that cited nothing, and money in the
delivered ЛСР for a card nobody read.
"""

from pathlib import Path

from tools.architecture_contract_gate import scan_architecture


CHAT_MODULE = "proxy/services/chat_evidence_application_service.py"
PROOF_MODULE = "proxy/services/norm_card_proof_service.py"
FACTS_MODULE = "proxy/services/model_rag_grouped_evidence_service.py"
CODE = "NORM_CHOICE_PRICED_WITHOUT_CARD_PROOF"


def _codes(root: Path, relative: str, body: str) -> set[str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("import re\n\n" + body, encoding="utf-8")
    return {item.code for item in scan_architecture(root)}


VERDICT_SEAM = '''
def bind_row_evidence_ids(rows, chunks):
    delivered_cipher_keys = set()
    for row in rows:
        evidence_check = {}
        evidence_check["card_body_shown"] = qualified_norm_key(row) in delivered_cipher_keys
    return evidence_check


async def _execute_chat_evidence_application(request, runtime, boundary):
    pass_rows = bind_row_evidence_ids(rows, chunks, binding_phase="first")
    proof_refs = norm_card_proof_reads_needed(pass_rows, chunks=chunks)
    unread = norm_card_unread_rows(pass_rows)
    if unread:
        message = norm_card_proof_request_message(proof_refs, pass_rows)
        record_norm_card_proof_request(trace, sheet=sheet, packet=packet, refs=proof_refs,
                                       receipts=(), attempt=1)
    admission = admit_model_result_packet(pass_rows, packet_locators=packet)
    return admission
'''


def test_admitting_model_decisions_without_the_proof_ask_is_a_violation(tmp_path: Path) -> None:
    codes = _codes(tmp_path, CHAT_MODULE, '''
async def _execute_chat_evidence_application(request, runtime, boundary):
    pass_rows = bind_row_evidence_ids(rows, chunks, binding_phase="first")
    admission = admit_model_result_packet(pass_rows, packet_locators=packet)
    return admission
''')
    assert CODE in codes


def test_the_same_seam_with_the_proof_ask_is_clean(tmp_path: Path) -> None:
    assert CODE not in _codes(tmp_path, CHAT_MODULE, VERDICT_SEAM)


def test_a_seam_that_asks_only_for_cited_refs_is_a_violation(tmp_path: Path) -> None:
    """The installed 930 shipped exactly this shape and priced 15 rows with no verdict."""

    codes = _codes(tmp_path, CHAT_MODULE, VERDICT_SEAM.replace(
        "    unread = norm_card_unread_rows(pass_rows)\n    if unread:",
        "    if proof_refs:"))
    assert CODE in codes


def test_a_verdict_built_only_from_deferred_identities_is_a_violation(tmp_path: Path) -> None:
    codes = _codes(tmp_path, CHAT_MODULE, VERDICT_SEAM.replace(
        'evidence_check["card_body_shown"] = qualified_norm_key(row) in delivered_cipher_keys',
        'evidence_check["card_body_shown"] = selected_deferred_ids <= delivered_norm_identities'))
    assert CODE in codes


def test_a_proof_request_that_names_no_read_operation_is_a_violation(tmp_path: Path) -> None:
    codes = _codes(tmp_path, PROOF_MODULE, '''
def proof_request_message(refs, rows):
    return "Пересмотри выбор нормы."


def unread_chosen_norm_refs(rows, *, chunks=()):
    return []
''')
    assert CODE in codes


def test_a_proof_request_that_offers_the_way_out_without_choosing_a_norm_is_clean(
        tmp_path: Path) -> None:
    codes = _codes(tmp_path, PROOF_MODULE, '''
READ_TOOL = "read_norm_card"


def unread_chosen_norm_rows(rows):
    if check.get("card_body_shown") is False:
        return []
    return []


def proof_request_message(refs, rows):
    unread = unread_chosen_norm_rows(rows)
    return "Без прочитанной карточки цена не начисляется; вызови read_norm_card для ref." + str(unread)


def unread_chosen_norm_refs(rows, *, chunks=()):
    return list(unread_chosen_norm_rows(rows))
''')
    assert CODE not in codes


def test_a_proof_request_that_only_walks_cited_rows_is_a_violation(tmp_path: Path) -> None:
    codes = _codes(tmp_path, PROOF_MODULE, '''
READ_TOOL = "read_norm_card"


def unread_chosen_norm_rows(rows):
    if check.get("card_body_shown") is False:
        return []
    return []


def proof_request_message(refs, rows):
    for row in rows:
        if not row.get("evidence_refs"):
            continue
    return "вызови read_norm_card"


def unread_chosen_norm_refs(rows, *, chunks=()):
    return list(unread_chosen_norm_rows(rows))
''')
    assert CODE in codes


def test_a_ref_reader_detached_from_the_row_verdict_is_a_violation(tmp_path: Path) -> None:
    codes = _codes(tmp_path, PROOF_MODULE, '''
READ_TOOL = "read_norm_card"


def unread_chosen_norm_rows(rows):
    if check.get("card_body_shown") is False:
        return []
    return []


def proof_request_message(refs, rows):
    return unread_chosen_norm_rows(rows) + "вызови read_norm_card"


def unread_chosen_norm_refs(rows, *, chunks=()):
    return [row.get("ref") for row in rows]
''')
    assert CODE in codes


def test_delivery_facts_that_echo_the_caller_instead_of_the_rendered_text_are_a_violation(
        tmp_path: Path) -> None:
    codes = _codes(tmp_path, FACTS_MODULE, '''
def card_delivery_facts(meta, *, raw_body_shown, displayed_body):
    return {"card_body_shown": raw_body_shown,
            "normative_composition_shown": raw_body_shown}
''')
    assert CODE in codes


def test_delivery_facts_read_from_the_delivered_text_are_clean(tmp_path: Path) -> None:
    codes = _codes(tmp_path, FACTS_MODULE, '''
def _pointer_body(displayed_body):
    return False


def card_delivery_facts(meta, *, raw_body_shown, displayed_body):
    composition = "Состав работы: " + "; ".join(steps)
    steps_shown = raw_body_shown and ("\\n" + composition + "\\n" in displayed_body)
    return {"card_body_shown": bool(raw_body_shown and not _pointer_body(displayed_body)),
            "body_claim_disagrees_with_delivery": bool(raw_body_shown) and pointer_only,
            "normative_composition_shown": bool(steps_shown)}
''')
    assert CODE not in codes
