"""Blocker § 2 (29.09): one declared-query contract, shared by prompt and reader.

The rule these tests hold is that reading a model's query list is a *structural*
problem, not a vocabulary problem: an ordinary text answer, a numbered list and a
bulleted list from any provider are queries; the accompanying answer is separated
with a reason and kept; and a call cut by ``finish_reason=length`` has its unread
last line addressed instead of being executed as if the list were complete.
"""
from __future__ import annotations

from proxy.services import chat_evidence_application_service as service


def _query_texts(raw: str) -> list[str]:
    return [item.text for item in service.read_declared_query_list(raw)["queries"]]


def test_declaration_prompt_and_reader_agree() -> None:
    """The format the prompt promises is the format the reader implements.

    A marker the prompt names but the reader does not strip would make the model
    write queries that are silently dropped, so the shared tuple is checked from
    both ends.
    """

    for marker in service._DECLARED_QUERY_MARKER_EXAMPLES:
        assert marker in service._MODEL_RAG_QUERY_FORMAT_CONTRACT
        stripped, form = service._strip_declared_query_markers(f"{marker} Монтаж кабеля")
        assert stripped == "Монтаж кабеля"
        assert form in {"numbered", "bulleted"}
    assert "Сопровождающий ответ" in service._MODEL_RAG_QUERY_FORMAT_CONTRACT
    assert service._MODEL_RAG_QUERY_FORMAT_CONTRACT in service.model_rag_query_instruction(
        {"mode": "estimator"}
    )
    assert service._MODEL_RAG_QUERY_FORMAT_CONTRACT in service.sheet_pass_query_instruction(
        {"mode": "estimator"}, sheet="СКС", sheet_index=1, sheet_count=2
    )


def test_ordinary_numbered_and_bulleted_output_all_read_as_queries() -> None:
    """Support the provider's plain text answer without a phrase list."""

    raw = (
        "1. Прокладка кабеля NYM 3x2.5 в трубе ПНД\n"
        "2) Монтаж шкафа управления\n"
        "3- Установка розетки двойной\n"
        "- Сборка щита щитового\n"
        "* Крепление лотка металлического\n"
        "• Демонтаж трубопровода чугунного\n"
    )
    assert _query_texts(raw) == [
        "Прокладка кабеля NYM 3x2.5 в трубе ПНД",
        "Монтаж шкафа управления",
        "Установка розетки двойной",
        "Сборка щита щитового",
        "Крепление лотка металлического",
        "Демонтаж трубопровода чугунного",
    ]
    forms = [item.marker_form for item in service.read_declared_query_list(raw)["queries"]]
    assert forms == ["numbered", "numbered", "numbered", "bulleted", "bulleted", "bulleted"]


def test_a_query_that_starts_with_a_size_is_not_read_as_a_list_number() -> None:
    """"2.5 мм2" is a characteristic; stripping its "2." would rewrite the query."""

    assert _query_texts("2.5 мм2 кабель силовой\n13,5 м трубы стальной") == [
        "2.5 мм2 кабель силовой",
        "13,5 м трубы стальной",
    ]


def test_accompanying_answer_is_separated_and_carries_its_reason() -> None:
    """A preamble is not a norm question, but it is also not thrown away."""

    raw = (
        "Коллега, сейчас сформирую список запросов:\n"
        "Монтаж кабельной канализации\n"
        "Демонтаж существующих конструкций\n"
        "Ок"
    )
    declared = service.read_declared_query_list(raw)
    assert [item.text for item in declared["queries"]] == [
        "Монтаж кабельной канализации",
        "Демонтаж существующих конструкций",
    ]
    reasons = {row["line"]: row["reason"] for row in declared["accompanying_answer"]}
    assert reasons == {
        "Коллега, сейчас сформирую список запросов:": "label_line_without_query",
        "Ок": "conversational_acknowledgement",
    }


def test_a_narrative_line_the_frozen_list_never_know_is_still_not_a_query() -> None:
    """The growth § 2 forbade: a new wording of the accompanying answer.

    The frozen prefix list stays as it is; this line is separated because it is a
    heading label, which is a structural fact about the line rather than a phrase
    this module has to recognise.
    """

    before = service._NARRATIVE_QUERY_PREFIXES
    raw = "Дальнейший порядок моих действий выглядит так:\nПрокладка троса стального"
    assert _query_texts(raw) == ["Прокладка троса стального"]
    assert service._NARRATIVE_QUERY_PREFIXES is before


def test_a_query_with_a_source_address_is_attributed_to_that_address() -> None:
    """§ 2: «указывать запросам операции/адреса, к которым они относятся»."""

    declared = service.read_declared_query_list(
        "СКС!R12 — Прокладка кабеля в гофре\nПрокладка кабеля в трубе ПНД",
        packet_locators=["СКС!R12", "СКС!R13"],
        row_literals={"СКС!R13": "Прокладка кабеля в трубе ПНД"},
    )
    first, second = declared["queries"]
    assert first.addresses == ("СКС!R12",)
    assert first.attribution == "address_written"
    assert first.text.startswith("СКС!R12")  # the line is kept verbatim
    assert second.addresses == ("СКС!R13",)
    assert second.attribution == "literal_matches_row"


def test_an_address_outside_the_packet_is_recorded_not_silently_rewritten() -> None:
    """A pointer to a row this packet does not contain stays visible as itself."""

    declared = service.read_declared_query_list(
        "АР!R9 — Монтаж радиатора отопления", packet_locators=["СКС!R12"]
    )
    query = declared["queries"][0]
    assert query.addresses == ("АР!R9",)
    assert query.attribution == "address_outside_packet"
    assert query.text == "АР!R9 — Монтаж радиатора отопления"
    inside = service.read_declared_query_list(
        "СКС!R12 — Монтаж радиатора отопления", packet_locators=["СКС!R12"]
    )
    assert inside["queries"][0].attribution == "address_written"


def test_a_cut_query_list_hands_its_unread_line_back_instead_of_executing_it() -> None:
    """finish_reason=length: the tail is addressed, never taken for a decision."""

    raw = (
        "1. Монтаж шкафа управления\n"
        "2. Прокладка кабеля NYM 3x2.5 в т"
    )
    declared = service.read_declared_query_list(raw, finish_reason="length")
    assert [item.text for item in declared["queries"]] == ["Монтаж шкафа управления"]
    assert declared["unread_tail"] == "2. Прокладка кабеля NYM 3x2.5 в т"
    assert declared["answer_cut"] is True

    same_text_without_the_cut = service.read_declared_query_list(raw)
    assert len(same_text_without_the_cut["queries"]) == 2
    assert same_text_without_the_cut["unread_tail"] == ""

    continuation = service.declared_query_continuation_instruction(
        ["Монтаж шкафа управления"], declared["unread_tail"]
    )
    assert "Прокладка кабеля NYM 3x2.5 в т" in continuation
    assert "Монтаж шкафа управления" in continuation
    assert "Не повторяй" in continuation


def test_a_repeated_query_line_is_executed_once() -> None:
    assert _query_texts("Монтаж шкафа\n1. Монтаж шкафа\n2. Монтаж щита") == [
        "Монтаж шкафа",
        "Монтаж щита",
    ]


def test_the_historical_helper_and_the_contract_never_disagree_a_line() -> None:
    lines = [
        "Прокладка кабеля",
        "1. Прокладка кабеля",
        "ок",
        "Коллега",
        "Сейчас сформирую запросы",
        "|---|---|",
        "и",
    ]
    declared = service.read_declared_query_list("\n".join(lines))
    accepted = {item.text for item in declared["queries"]}
    rejected = {row["line"] for row in declared["accompanying_answer"]}
    for line in lines:
        stripped, _form = service._strip_declared_query_markers(line)
        assert service.is_model_rag_search_query_line(line) is (stripped in accepted)
        assert (stripped in accepted) != (stripped in rejected)


def test_json_protocol_lines_are_still_not_read_as_queries() -> None:
    assert service.parse_model_rag_queries('{"queries": ["a b c d"]}') == []


# ---------------------------------------------------------------- adapter seams
#
# The contract above is only worth having if the adapter really uses it: the
# header the model sees, the retry the cut list gets, and the numbers that say
# what happened to each query all come from the same reading.


def _stub_hit(text: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        content=text,
        doc_id="card-1",
        doc_name="les_smeta_norm_cards.v1",
        score=0.9,
        meta={"dataset_id": "smeta"},
    )


def _shown_chunk(query_index: int, query_text: str, hit_index: int):
    return service._ModelRagEvidenceChunk(
        content=f"Шифр: ГЭСН04-12-00{query_index}-{hit_index:02d} Наименование: монтаж",
        doc_id=f"card-{query_index}-{hit_index}",
        doc_name="les_smeta_norm_cards.v1",
        score=0.9,
        meta={
            "model_query_index": query_index,
            "model_query_text": query_text,
            "model_evidence_ref": f"Q{query_index}.H{hit_index}",
        },
    )


def test_a_query_that_names_its_row_shows_that_row_to_the_model() -> None:
    """Blocker § 2: «указывать запросам операции/адреса, к которым они относятся»."""

    query = "Прокладка кабеля NYM 3x2.5"
    addresses = {query: ["СКС!R12"]}
    query_hits = [(query, (_stub_hit("Шифр: ГЭСН04-12-001-01 " + "состав " * 40),))]

    groups, _chunks, _omitted = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=20_000,
        hits_per_query=4,
        query_addresses=addresses,
    )
    assert "[Поисковый запрос Q1] Прокладка кабеля NYM 3x2.5 [строки: СКС!R12]" in groups[0]

    # An unattributed query gets no address invented for it.
    plain_groups, _plain_chunks, _plain_omitted = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=20_000,
        hits_per_query=4,
    )
    assert "[строки:" not in plain_groups[0]

    # The prompt states the same convention the adapter reads.
    assert "адрес" in service._MODEL_RAG_QUERY_FORMAT_CONTRACT


def test_a_written_address_costs_the_same_chars_it_renders() -> None:
    """The budget cannot drift from the header it pays for."""

    query = "Монтаж шкафа управления"
    addresses = {query: ["АР!R7"]}
    hit = _stub_hit("Шифр: ГЭСН04-12-002-01 " + "состав " * 40)
    query_hits = [(query, (hit,))]

    with_address = service.model_rag_evidence_header_chars(
        query_hits, hits_per_query=1, query_addresses=addresses
    )
    without_address = service.model_rag_evidence_header_chars(query_hits, hits_per_query=1)
    assert with_address > without_address

    rendered_query_header = service._model_rag_query_header(1, query, "model", ["АР!R7"])
    unattributed_header = service._model_rag_query_header(1, query, "model")
    # The address costs exactly the characters it renders: the same header builder
    # pays the budget and writes the group, so the two cannot drift apart.
    assert with_address - without_address == len(rendered_query_header) - len(
        unattributed_header
    )

    groups, _chunks, _omitted = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=with_address + 4_000,
        hits_per_query=1,
        query_addresses=addresses,
    )
    assert rendered_query_header in groups[0]


def test_a_cut_list_is_asked_for_once_and_a_declared_list_is_never_reasked() -> None:
    """The two follow-ups are bounded, so a cut answer cannot start a retry loop."""

    cut = {"unread_tail": "Прокладка кабеля NYM 3x2", "queries": [{"text": "Монтаж шкафа"}]}
    phase, suffix = service.declared_query_attempt_plan(
        declared=cut, already_declared=["Монтаж шкафа"], phase="declare", attempts_remaining=2
    )
    assert phase == "continuation"
    assert "Прокладка кабеля NYM 3x2" in suffix

    # A second cut on the same packet does not buy a third continuation call.
    assert service.declared_query_attempt_plan(
        declared=cut, already_declared=["Монтаж шкафа"], phase="continuation",
        attempts_remaining=1,
    ) == ("", "")

    # Nothing declared at all is a format problem, answered once.
    empty = {"unread_tail": "", "queries": []}
    phase, suffix = service.declared_query_attempt_plan(
        declared=empty, already_declared=[], phase="declare", attempts_remaining=2
    )
    assert phase == "repair"
    assert suffix == service._MODEL_RAG_QUERY_REPAIR_INSTRUCTION
    assert service.declared_query_attempt_plan(
        declared=empty, already_declared=[], phase="repair", attempts_remaining=1
    ) == ("", "")

    # A healthy list stops the loop, and an exhausted budget stops everything.
    assert service.declared_query_attempt_plan(
        declared={"unread_tail": "", "queries": [{"text": "Монтаж шкафа"}]},
        already_declared=["Монтаж шкафа"],
        phase="declare",
        attempts_remaining=2,
    ) == ("", "")
    assert service.declared_query_attempt_plan(
        declared=cut, already_declared=[], phase="declare", attempts_remaining=0
    ) == ("", "")
    assert service._MAX_SHEET_PASS_QUERY_CALLS == 3


def test_found_shown_deferred_and_chosen_are_measured_apart_for_one_packet() -> None:
    """Раздельно измерять найдено/показано/отложено/выбрано — per query, per packet."""

    first, second = "Монтаж шкафа", "Прокладка кабеля"
    measurement = service.model_rag_query_measurement(
        declared_queries=[
            {"query_text": first, "addresses": ["АР!R7"], "attribution": "address_written"}
        ],
        query_provenance={first: "model", second: "original"},
        pass_hits=[(first, (None, None, None)), (second, (None,))],
        leftover_query_hits=[],
        evidence_chunks=[
            _shown_chunk(1, first, 1),
            _shown_chunk(1, first, 2),
            _shown_chunk(2, second, 1),
        ],
        omitted_refs=["Q1.H3"],
        kept_rows=[{"evidence_refs": ["Q1.H1"]}, {"evidence_refs": ["Q2.H1"]}],
    )
    rows = {row["query_text"]: row for row in measurement["queries"]}
    assert rows[first]["found"] == 3
    assert rows[first]["model_visible"] == 2
    assert rows[first]["not_visible"] == 1
    assert rows[first]["cards_omitted"] == 1
    assert rows[first]["chosen_rows"] == 1
    assert rows[first]["addresses"] == ["АР!R7"]
    assert rows[second]["found"] == 1
    assert rows[second]["model_visible"] == 1
    assert rows[second]["not_visible"] == 0
    assert rows[second]["chosen_rows"] == 1
    assert rows[second]["attribution"] == ""

    # The groups keep each figure on its own; nothing collapses into "loss".
    assert measurement["groups"]["model"] == {
        "queries": 1,
        "found": 3,
        "model_visible": 2,
        "not_visible": 1,
        "chosen_rows": 1,
    }
    assert measurement["groups"]["original"]["found"] == 1
    assert measurement["compares_only_within_this_packet"] is True


def test_several_packets_accumulate_their_counts_separately() -> None:
    """A multi-packet found is never subtracted from one packet's model_visible."""

    rollup: dict = {"packets": 0, "groups": {}}
    first_query = "Монтаж шкафа"
    service.merge_query_measurement(
        rollup,
        service.model_rag_query_measurement(
            query_provenance={first_query: "model"},
            pass_hits=[(first_query, (None, None, None))],
            evidence_chunks=[_shown_chunk(1, first_query, 1)],
            kept_rows=[],
        ),
    )
    service.merge_query_measurement(
        rollup,
        service.model_rag_query_measurement(
            query_provenance={first_query: "model"},
            pass_hits=[(first_query, (None,))],
            evidence_chunks=[],
            leftover_query_hits=[(first_query, (None,))],
            kept_rows=[],
        ),
    )

    assert rollup["packets"] == 2
    group = rollup["groups"]["model"]
    assert group["found"] == 4
    assert group["model_visible"] == 1
    assert group["not_visible"] == 3
    assert rollup["deferred_wholly_queries"] == 1
    # Each figure still carries its own name: no single loss number was produced.
    assert not any(key in rollup for key in ("loss", "lost", "missing"))


def test_separated_answer_lines_keep_their_reason_counts() -> None:
    raw = (
        "Вот мои запросы:\n"
        "1. Монтаж шкафа управления\n"
        "|---|---|\n"
        "Готово\n"
    )
    declared = service.read_declared_query_list(raw)
    counts = service.rejected_reason_counts(declared["accompanying_answer"])
    assert counts  # every separated line reported why
    assert sum(counts.values()) == len(declared["accompanying_answer"])
    assert set(counts) <= {
        "empty_after_presentation_markers",
        "table_rule_line",
        "conversational_acknowledgement",
        "shorter_than_a_query",
        "heading_line",
        "label_line_without_query",
        "narrative_answer_line",
    }
    assert [item.text for item in declared["queries"]] == ["Монтаж шкафа управления"]
