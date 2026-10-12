"""ADR-16 § 6 / § 11: a written cipher is a choice, not a substantiated choice.

Mechanical proof for three mandatory regressions:

* «norm_code с evidence другого шифра не даёт подтверждённой применимости» —
  the citation the model itself wrote can contradict the cipher it authored, and
  readiness plus the XLSX trace must both say so;
* «ANALOGUE_CANDIDATE без обоснования не закрывает готовность» — an analogue
  stays a question until the five match facts the model was asked for are all
  answered, because prose in ``extra_ops`` is not evidence;
* task 2026-09-29 § 3 «не извлекать „подтверждение" из одной метки EXACT» — a
  cipher the model named without any cited card carrying it is an open choice,
  while a row from a route that showed no cards at all is not accused of one.

Nothing here asks the model for anything: the inputs are the row payloads the
application already persists.
"""

from proxy.services.chat_evidence_application_service import row_evidence_provenance_check
from proxy.services.lsr_norm_quality_gate_service import (
    applicability_gap_kind,
    citation_record_present,
    cited_cipher_matches_evidence,
    ciphers_compatible,
    exact_citation_ungrounded,
    looks_like_cipher,
    norm_applicability_substantiated,
    open_analogue_match_fields,
)
from proxy.services.lsr_result_readiness_service import (
    build_lsr_result_readiness,
    classify_norm_gap,
)
from proxy.services.rim_lsr_trace_service import _row_readiness
import pytest

MATCH_YES = {
    "action_match": "yes",
    "object_match": "yes",
    "condition_match": "yes",
    "unit_compatible": "yes",
    "composition_covers": "yes",
}


@pytest.mark.parametrize("status", ["EXACT", "EXACT_VERIFIED"])
@pytest.mark.parametrize("flag", ["unknown", "no"])
def test_exact_token_does_not_confirm_a_condition_the_same_model_left_open(status, flag):
    row = {"source_row": "Other!R18", "row_role": "work", "norm_code": "ГЭСН01-02-003-04",
           "norm_status": status, **MATCH_YES, "condition_match": flag,
           "_evidence_check": {"citation_checkable": True, "cited_ciphers": ["ГЭСН01-02-003-04"]}}
    before = dict(row)
    assert applicability_gap_kind(row) == "exact_match_unresolved"
    assert norm_applicability_substantiated(row) is False
    readiness = build_lsr_result_readiness(packaged=True, rows=[row], pricing_status="priced_final",
                                          calculated_positions=1, catalog_work_count=1,
                                          catalog_locators=["Other!R18"])
    assert readiness["dimensions"]["norms"]["complete"] is False
    assert readiness["gap_states"]["norm_unsubstantiated"]["count"] == 1
    assert "условиям" in readiness["dimensions"]["norms"]["gaps"][0]["action"]
    assert _row_readiness({"code": row["norm_code"], "norm_status": status, "row_role": "work",
                           "status": "bound", "position": {"op_key": "operation"}}, row)["applicability_substantiated"] is False
    assert row == before  # report the contradiction; never rewrite the authored decision


def _check(norm_code: str, cards: dict[str, str]) -> dict:
    """Run the real citation check over alias -> card ciphers.

    ``alias_to_card`` carries what ``_card_code_from_body`` produces in the
    application: the bare cipher, or the document name when the card has none.
    """

    row = {"norm_code": norm_code, "evidence_refs": sorted(cards)}
    bindings = {alias: index for index, alias in enumerate(sorted(cards), 1)}
    result = row_evidence_provenance_check(
        row, bindings, dict(cards), {alias: "запрос" for alias in cards}
    )
    assert result is not None
    return result


def test_cited_card_of_another_cipher_is_a_structural_contradiction() -> None:
    check = _check("ГЭСН 10-01-001-05", {"Q1.H2": "10-01-002-09"})

    assert check["code_not_in_refs"] is True
    assert check["citation_checkable"] is True
    row = {"norm_code": "ГЭСН 10-01-001-05", "norm_status": "EXACT",
           "row_role": "work", "source_row": "ВОР!R7", "_evidence_check": check}
    assert cited_cipher_matches_evidence(row) is False
    assert norm_applicability_substantiated(row) is False
    assert classify_norm_gap(row) == "cipher_not_in_cited_evidence"


@pytest.mark.parametrize("selected,cited", [
    ("10-01-001-05", "10-01-001-05"),
    ("ГЭСН10-01-001-05", "10-01-001-05"),
    ("ГЭСН10-01-001-05", "ГЭСНм10-01-001-05"),
    ("ГЭСН10-01-001-05", "ГЭСН10-01-001"),
])
def test_partial_or_foreign_family_citation_never_identifies_selected_item(selected, cited):
    check = _check(selected, {"Q1.H1": cited})
    row = {"norm_code": selected, "norm_status": "EXACT", "_evidence_check": check}
    assert check["code_not_in_refs"] is True
    assert check["citation_checkable"] is True
    assert cited_cipher_matches_evidence(row) is False
    assert applicability_gap_kind(row) == "cipher_not_in_cited_evidence"
    assert norm_applicability_substantiated(row) is False


def test_cipher_spelling_alone_is_not_read_as_a_contradiction() -> None:
    # The catalog stores «ГЭСНм:10-02-016-06», the model writes «ГЭСНм10-02-016-06».
    assert ciphers_compatible("ГЭСН 10-01-001-05", "ГЭСН10-01-001-05") is True
    assert ciphers_compatible("10-01-001-05", "10-01-002-05") is False
    check = _check("ГЭСНм10-02-016-06", {"Q1.H1": "ГЭСНм:10-02-016-06"})

    assert check["code_not_in_refs"] is False
    assert check["citation_checkable"] is True


def test_a_cited_card_without_a_cipher_leaves_the_citation_unchecked() -> None:
    # A card body with no «Шифр:» line reports its document name.  A name neither
    # supports nor contradicts the authored cipher, so readiness must not claim a
    # contradiction and must not claim substantiation from it either.
    row = {"norm_code": "ГЭСН 10-01-001-05", "evidence_refs": ["Q1.H1"]}
    check = row_evidence_provenance_check(
        row, {"Q1.H1": 1}, {"Q1.H1": "Сборник 10. Земляные работы"}, {"Q1.H1": "запрос"}
    )

    assert check is not None
    assert check["citation_checkable"] is False
    assert check["code_not_in_refs"] is False
    assert looks_like_cipher("Сборник 10. Земляные работы") is False
    assert cited_cipher_matches_evidence({**row, "_evidence_check": check}) is None


def test_readiness_keeps_a_mismatched_citation_out_of_the_finished_document() -> None:
    rows = [
        {
            "source_row": "ВОР!R7",
            "row_role": "work",
            "norm_code": "ГЭСН 10-01-001-05",
            "norm_status": "EXACT",
            "_evidence_check": _check("ГЭСН 10-01-001-05", {"Q1.H2": "10-01-002-09"}),
        },
        {
            "source_row": "ВОР!R8",
            "row_role": "work",
            "norm_code": "ГЭСН 10-01-001-06",
            "norm_status": "EXACT",
            "_evidence_check": _check("ГЭСН 10-01-001-06", {"Q1.H3": "ГЭСН10-01-001-06"}),
        },
    ]
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=rows,
        pricing_status="priced_final",
        calculated_positions=2,
        catalog_work_count=2,
        catalog_locators=["ВОР!R7", "ВОР!R8"],
    )

    gaps = readiness["dimensions"]["norms"]["gaps"]
    assert [gap["locator"] for gap in gaps] == ["ВОР!R7"]
    assert gaps[0]["kind"] == "cipher_not_in_cited_evidence"
    assert "не совпадает с шифром приведённых карточек" in gaps[0]["action"]
    assert readiness["dimensions"]["norms"]["complete"] is False
    assert readiness["estimate_complete"] is False
    assert readiness["counts"]["norms_selected"] == 2
    assert readiness["counts"]["norms_applicability_substantiated"] == 1
    assert readiness["gap_states"]["norm_unsubstantiated"]["count"] == 1
    assert readiness["gap_states"]["norm_missing"]["count"] == 0


def test_analogue_candidate_without_match_facts_is_a_question_not_a_result() -> None:
    row = {
        "source_row": "ВОР!R9",
        "row_role": "work",
        "norm_code": "ГЭСН 10-01-001-05",
        "norm_status": "ANALOGUE_CANDIDATE",
        "extra_ops": "подходит по сути",
    }

    assert open_analogue_match_fields(row) == (
        "action_match", "object_match", "condition_match", "unit_compatible",
        "composition_covers",
    )
    assert norm_applicability_substantiated(row) is False
    assert classify_norm_gap(row) == "analogue_needs_confirmation"


def test_analogue_candidate_with_all_match_facts_closes_the_row() -> None:
    row = {
        "source_row": "ВОР!R9",
        "row_role": "work",
        "norm_code": "ГЭСН 10-01-001-05",
        "norm_status": "ANALOGUE_CANDIDATE",
        **MATCH_YES,
    }

    assert norm_applicability_substantiated(row) is True
    assert classify_norm_gap(row) == ""


def test_analogue_candidate_with_an_unproven_match_field_stays_open() -> None:
    row = {
        "source_row": "ВОР!R9",
        "row_role": "work",
        "norm_code": "ГЭСН 10-01-001-05",
        "norm_status": "ANALOGUE_CANDIDATE",
        **{**MATCH_YES, "unit_compatible": "unknown"},
    }

    assert open_analogue_match_fields(row) == ("unit_compatible",)
    assert classify_norm_gap(row) == "analogue_needs_confirmation"


def test_readiness_reports_an_unsubstantiated_analogue_to_the_operator() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[{
            "source_row": "ВОР!R9",
            "row_role": "work",
            "norm_code": "ГЭСН 10-01-001-05",
            "norm_status": "ANALOGUE_CANDIDATE",
        }],
        pricing_status="priced_final",
        calculated_positions=1,
        catalog_work_count=1,
        catalog_locators=["ВОР!R9"],
    )

    gaps = readiness["dimensions"]["norms"]["gaps"]
    assert gaps[0]["kind"] == "analogue_needs_confirmation"
    assert "аналогом" in gaps[0]["action"]
    assert "не подтверждено" in gaps[0]["action"]
    assert readiness["dimensions"]["norms"]["complete"] is False
    assert readiness["gap_states"]["norm_unsubstantiated"]["count"] == 1


def test_trace_and_readiness_give_one_verdict_for_one_row() -> None:
    """§ 10: the XLSX trace column and the readiness card cannot disagree.

    § 3 (2026-09-29) is what the three EXACT shapes below pin: a row that cites a
    card naming its cipher is a grounded decision, a row that cites a card naming
    another one is a wrong link, and a bare «EXACT» with no citation is neither —
    it is the label, and the label is not the confirmation.
    """

    def readiness_for(status: str, **fields: str) -> dict:
        model_row = {
            "source_row": "ВОР!R9",
            "row_role": "work",
            "norm_code": "ГЭСН 10-01-001-05",
            "norm_status": status,
            **fields,
        }
        binding = {
            "code": "ГЭСН 10-01-001-05",
            "norm_status": status,
            "row_role": "work",
            "status": "bound",
            "position": {"op_key": "x"},
        }
        return {
            "trace": _row_readiness(binding, model_row)["applicability_substantiated"],
            "card": classify_norm_gap(model_row),
        }

    def verdicts(status: str, gap_kind: str, **fields: str) -> None:
        """One row, one verdict: the trace boolean is False exactly for a gap kind."""

        assert readiness_for(status, **fields) == {"trace": not gap_kind, "card": gap_kind}

    verdicts("ANALOGUE_CANDIDATE", "analogue_needs_confirmation")
    verdicts("ANALOGUE_CANDIDATE", "", **MATCH_YES)
    # The model named a cipher and cited a card, but no cited card names it.
    verdicts("EXACT", "cipher_without_cited_card", **{
        "_evidence_check": _check("ГЭСН 10-01-001-05", {"Q1.H1": ""})
    })
    verdicts("EXACT", "cipher_not_in_cited_evidence", **{
        "_evidence_check": {
            "code_not_in_refs": True, "citation_checkable": True, "cited_ciphers": ["10-02-000-01"],
        }
    })
    # The positive case: the model cited the card whose body names that cipher.
    verdicts("EXACT", "", **{
        "_evidence_check": _check("ГЭСН 10-01-001-05", {"Q1.H1": "ГЭСН 10-01-001-05"})
    })
    # A row from a route that showed no cards at all has no citation to be grounded
    # in; asking for one would be the «скрытое поле» § 3 forbids.
    assert readiness_for("EXACT") == {"trace": True, "card": ""}


def test_an_exact_cipher_without_a_cited_card_stays_an_open_choice() -> None:
    """§ 3: «не извлекать подтверждение из одной метки EXACT».

    The label is what the model asserts; the cited card is what grounds it.  When
    the packet was bound and the row's own citation names no card carrying that
    cipher, readiness asks the operator about the choice instead of printing the
    token as a confirmation — and the same row cannot be quietly priced as final.
    """

    ungrounded = {
        "source_row": "ВОР!R5",
        "row_role": "work",
        "norm_code": "ГЭСН 10-01-001-05",
        "norm_status": "EXACT",
        "_evidence_check": _check("ГЭСН 10-01-001-05", {"Q1.H1": ""}),
    }

    assert citation_record_present(ungrounded) is True
    assert exact_citation_ungrounded(ungrounded) is True
    assert applicability_gap_kind(ungrounded) == "cipher_without_cited_card"
    assert norm_applicability_substantiated(ungrounded) is False

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[ungrounded],
        pricing_status="priced_final",
        calculated_positions=1,
        catalog_work_count=1,
        catalog_locators=["ВОР!R5"],
    )

    gaps = readiness["dimensions"]["norms"]["gaps"]
    assert [gap["kind"] for gap in gaps] == ["cipher_without_cited_card"]
    assert "ни одна приведённая карточка его не называет" in gaps[0]["action"]
    assert "код ссылку не дорисовывает" in gaps[0]["action"]
    assert readiness["dimensions"]["norms"]["complete"] is False
    assert readiness["gap_states"]["norm_unsubstantiated"]["count"] == 1
    # The money gate reads the same verdict as the card (§ 10).
    assert _row_readiness(
        {"code": "ГЭСН 10-01-001-05", "norm_status": "EXACT", "row_role": "work",
         "status": "bound", "position": {"op_key": "x"}},
        ungrounded,
    )["applicability_substantiated"] is False


def test_a_row_from_a_route_without_cards_is_not_accused_of_a_wrong_link() -> None:
    """The chat panel of visible rows performs no retrieval, so it has no citation.

    Absence of the record is not evidence of a bad choice, and readiness must not
    turn it into «неправильная ссылка» — but it must also not *say* the norm was
    confirmed by a card.  Measured on the installed store, 1081 of 1082
    cipher-bearing durable ``EXACT`` rows carry the record, so this branch covers
    the route, not a loophole around the citation question.
    """

    row = {
        "source_row": "ВОР!R5",
        "row_role": "work",
        "norm_code": "ГЭСН 10-01-001-05",
        "norm_status": "EXACT",
    }

    assert citation_record_present(row) is False
    assert exact_citation_ungrounded(row) is False
    assert applicability_gap_kind(row) == ""
    assert cited_cipher_matches_evidence(row) is None
