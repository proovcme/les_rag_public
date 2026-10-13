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


GROUP_CODE = "GROUP_RESOURCE_PRICED_WITHOUT_A_MEMBER_CHOICE"
GROUP_CHAT_MODULE = CHAT_MODULE
GROUP_SERVICE_MODULE = "proxy/services/lsr_resource_group_proof_service.py"


def _group_seam(answer: str) -> str:
    return f'''
async def _execute_chat_evidence_application(request, runtime, boundary):
    pass_rows = bind_row_evidence_ids(rows, chunks, binding_phase="first")
    groups = resource_group_proof_reads_needed(pass_rows, chunks, pricebook=book)
    if groups:
        message = resource_group_proof_request_message(groups)
        record_resource_group_proof_request(trace, sheet=sheet, packet=packet,
                                           groups=groups, answered=True, attempt=1)
    admission = admit_model_result_packet(pass_rows, packet_locators=packet)
    return admission
{answer}'''


def test_admitting_a_family_priced_row_without_asking_for_a_member_is_a_violation(tmp_path):
    codes = _codes(tmp_path, GROUP_CHAT_MODULE, '''
async def _execute_chat_evidence_application(request, runtime, boundary):
    pass_rows = bind_row_evidence_ids(rows, chunks, binding_phase="first")
    admission = admit_model_result_packet(pass_rows, packet_locators=packet)
    return admission
''')
    assert GROUP_CODE in codes


def test_the_same_seam_with_the_group_ask_is_clean(tmp_path):
    assert GROUP_CODE not in _codes(tmp_path, GROUP_CHAT_MODULE, _group_seam(""))


def test_a_group_message_without_the_price_operations_is_a_violation(tmp_path):
    codes = _codes(tmp_path, GROUP_SERVICE_MODULE, '''
def proof_request_message(groups):
    return "Перезполни строку ресурса. первая строка группы не является ценой группы"
''')
    assert GROUP_CODE in codes


def test_a_group_message_that_priced_the_family_itself_is_a_violation(tmp_path):
    codes = _codes(tmp_path, GROUP_SERVICE_MODULE, '''
SEARCH_TOOL = "search_pricebook_resources"
PRICE_TOOL = "read_resource_price"


def proof_request_message(groups):
    return "нужна цена" + SEARCH_TOOL + PRICE_TOOL
''')
    assert GROUP_CODE in codes


def test_a_group_message_that_names_the_tools_and_denies_a_family_price_is_clean(tmp_path):
    codes = _codes(tmp_path, GROUP_SERVICE_MODULE, '''
SEARCH_TOOL = "search_pricebook_resources"
PRICE_TOOL = "read_resource_price"


def proof_request_message(groups):
    return ("выбери конкретный ресурс: " + SEARCH_TOOL + " / " + PRICE_TOOL
            + "; первая строка группы не является ценой группы")
''')
    assert GROUP_CODE not in codes


ROUND_CODE = "PROOF_ROUND_ERASES_PACKET_ROWS"

# The shape installed 932 actually ran: the round parsed its own answer and wrote it over the
# packet without asking whether the answer carried a table at all.
ERASING_SEAM = '''
def rows_after_proof_round(*, parsed_rows, previous_rows, chunks):
    if not parsed_rows:
        return [dict(row) for row in previous_rows], False
    return bind_row_evidence_ids(parsed_rows, chunks, binding_phase="first"), True


async def _execute_chat_evidence_application(request, runtime, boundary):
    pass_rows = bind_row_evidence_ids(rows, chunks, binding_phase="first")
    pass_rows = bind_row_evidence_ids(proved_rows, chunks, binding_phase="first")
    record_norm_card_proof_request(trace, sheet=sheet, packet=packet, refs=refs,
                                   receipts=(), attempt=1)
    record_resource_group_proof_request(trace, sheet=sheet, packet=packet, groups=groups,
                                        answered=True, attempt=1)
    return pass_rows
'''

GUARDED_SEAM = '''
def rows_after_proof_round(*, parsed_rows, previous_rows, chunks):
    if not parsed_rows:
        return [dict(row) for row in previous_rows], False
    return bind_row_evidence_ids(parsed_rows, chunks, binding_phase="first"), True


async def _execute_chat_evidence_application(request, runtime, boundary):
    pass_rows = bind_row_evidence_ids(rows, chunks, binding_phase="first")
    pass_rows, answer_parsed = rows_after_proof_round(
        parsed_rows=proved_rows, previous_rows=pass_rows, chunks=chunks)
    record_norm_card_proof_request(trace, sheet=sheet, packet=packet, refs=refs,
                                   receipts=(), attempt=1, answer_parsed=answer_parsed)
    pass_rows, group_parsed = rows_after_proof_round(
        parsed_rows=group_rows, previous_rows=pass_rows, chunks=chunks)
    record_resource_group_proof_request(trace, sheet=sheet, packet=packet, groups=groups,
                                        answered=True, attempt=1, answer_parsed=group_parsed)
    return pass_rows
'''


def test_a_proof_round_that_writes_its_own_parse_over_the_packet_is_a_violation(tmp_path):
    """This is what made the 932 БАП cell come back with work_rows 0 and a 0.00 amount."""

    assert ROUND_CODE in _codes(tmp_path, CHAT_MODULE, ERASING_SEAM)


def test_both_rounds_rebinding_through_the_helper_are_clean(tmp_path):
    assert ROUND_CODE not in _codes(tmp_path, CHAT_MODULE, GUARDED_SEAM)


def test_one_round_left_unguarded_is_a_violation(tmp_path):
    codes = _codes(tmp_path, CHAT_MODULE, GUARDED_SEAM.replace(
        """    pass_rows, group_parsed = rows_after_proof_round(
        parsed_rows=group_rows, previous_rows=pass_rows, chunks=chunks)
""",
        """    pass_rows = bind_row_evidence_ids(group_rows, chunks, binding_phase="first")
"""))
    assert ROUND_CODE in codes


def test_a_record_without_the_answer_parse_flag_is_a_violation(tmp_path):
    codes = _codes(tmp_path, CHAT_MODULE, GUARDED_SEAM.replace(
        "attempt=1, answer_parsed=group_parsed)", "attempt=1)"))
    assert ROUND_CODE in codes


def test_a_helper_with_no_branch_back_to_the_previous_rows_is_a_violation(tmp_path):
    codes = _codes(tmp_path, CHAT_MODULE, GUARDED_SEAM.replace(
        """    if not parsed_rows:
        return [dict(row) for row in previous_rows], False
""",
        """    if not parsed_rows:
        return [], False
"""))
    assert ROUND_CODE in codes


def test_a_helper_that_stopped_rebinding_through_the_binder_is_a_violation(tmp_path):
    codes = _codes(tmp_path, CHAT_MODULE, GUARDED_SEAM.replace(
        "    return bind_row_evidence_ids(parsed_rows, chunks, binding_phase=\"first\"), True",
        "    return [dict(row) for row in parsed_rows], True"))
    assert ROUND_CODE in codes
