"""ADR-16 § 6 / § 11: a written cipher is a choice, not a substantiated choice.

Mechanical proof for two mandatory regressions:

* «norm_code с evidence другого шифра не даёт подтверждённой применимости» —
  the citation the model itself wrote can contradict the cipher it authored, and
  readiness plus the XLSX trace must both say so;
* «ANALOGUE_CANDIDATE без обоснования не закрывает готовность» — an analogue
  stays a question until the five match facts the model was asked for are all
  answered, because prose in ``extra_ops`` is not evidence.

Nothing here asks the model for anything: the inputs are the row payloads the
application already persists.
"""

from proxy.services.chat_evidence_application_service import row_evidence_provenance_check
from proxy.services.lsr_norm_quality_gate_service import (
    cited_cipher_matches_evidence,
    ciphers_compatible,
    looks_like_cipher,
    norm_applicability_substantiated,
    open_analogue_match_fields,
)
from proxy.services.lsr_result_readiness_service import (
    build_lsr_result_readiness,
    classify_norm_gap,
)
from proxy.services.rim_lsr_trace_service import _row_readiness

MATCH_YES = {
    "action_match": "yes",
    "object_match": "yes",
    "condition_match": "yes",
    "unit_compatible": "yes",
    "composition_covers": "yes",
}


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
            "_evidence_check": _check("ГЭСН 10-01-001-06", {"Q1.H3": "10-01-001-06"}),
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
    assert readiness["counts"]["norms_selected"] == 1
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
    """§ 10: the XLSX trace column and the readiness card cannot disagree."""

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
            "card": not classify_norm_gap(model_row),
        }

    assert readiness_for("ANALOGUE_CANDIDATE") == {"trace": False, "card": False}
    assert readiness_for("ANALOGUE_CANDIDATE", **MATCH_YES) == {"trace": True, "card": True}
    assert readiness_for("EXACT") == {"trace": True, "card": True}
    contradicted = {
        "_evidence_check": {
            "code_not_in_refs": True, "citation_checkable": True, "cited_ciphers": ["10-02-000-01"],
        }
    }
    assert readiness_for("EXACT", **contradicted) == {"trace": False, "card": False}
