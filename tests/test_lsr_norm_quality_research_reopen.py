"""CONFLICT/MISSING reject a cipher; the work row stays open for model search."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from proxy.services.lsr_norm_quality_gate_service import (
    LsrResearchRoundResult,
    apply_verifier_row,
    authored_norm_code,
    build_blind_review_evidence_items,
    carry_prior_norm_code,
    default_lookup_authored_norm_card,
    prepare_selection_row,
    rejected_norm_codes,
    row_is_quality_terminal,
    row_needs_research,
    row_needs_verifier,
    run_lsr_norm_quality_loop,
    lsr_verifier_instruction,
    split_rows_missing_selected_card,
    store_code_variants,
)


def _conflict_table(locator: str, code: str) -> str:
    return (
        "| source_row | title | unit | norm_code | verdict | action_match | "
        "object_match | condition_match | unit_compatible | composition_covers | "
        "extra_ops | missing_ops | contradictions |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        f"| {locator} | work | шт | {code} | CONFLICT | no | no | unknown | "
        "unknown | unknown | | | |\n"
    )


def _verified_table(locator: str, code: str) -> str:
    return (
        "| source_row | title | unit | norm_code | verdict | action_match | "
        "object_match | condition_match | unit_compatible | composition_covers | "
        "extra_ops | missing_ops | contradictions |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        f"| {locator} | work | шт | {code} | EXACT_VERIFIED | yes | yes | yes | "
        "yes | yes | | | |\n"
    )


def test_first_pass_conflict_opens_research_and_remembers_code() -> None:
    row = prepare_selection_row(
        {
            "source_row": "15",
            "title": "Монтаж блока аварийного питания",
            "norm_code": "ГЭСНм08-02-409-09",
            "norm_status": "CONFLICT",
        }
    )
    assert row["norm_status"] == "NEEDS_RESEARCH"
    assert row["_quality_gate"] == "research"
    assert row_needs_research(row) is True
    assert row_is_quality_terminal(row) is False
    assert "ГЭСНм08-02-409-09" in rejected_norm_codes(row)


def test_verifier_conflict_does_not_terminate_the_row() -> None:
    selection = prepare_selection_row(
        {
            "source_row": "2",
            "title": "Демонтаж кабеля",
            "norm_code": "ГЭСНм08-02-409-09",
            "norm_status": "EXACT",
        }
    )
    assert row_needs_verifier(selection) is True
    updated = apply_verifier_row(
        selection,
        {
            "source_row": "2",
            "norm_code": "ГЭСНм08-02-409-09",
            "norm_status": "CONFLICT",
            "action_match": "no",
            "object_match": "no",
        },
    )
    assert updated["norm_status"] == "NEEDS_RESEARCH"
    assert updated["_quality_gate"] == "research"
    assert row_is_quality_terminal(updated) is False
    assert "ГЭСНм08-02-409-09" in rejected_norm_codes(updated)


def test_unparsed_verifier_does_not_open_research_on_exact() -> None:
    row = prepare_selection_row(
        {
            "source_row": "1",
            "title": "work",
            "norm_code": "ГЭСНм10-02-016-06",
            "norm_status": "EXACT",
        }
    )
    assert row_needs_research(row) is False
    assert row["norm_status"] == "EXACT"


@pytest.mark.asyncio
async def test_conflict_then_research_can_bind_a_new_model_code() -> None:
    verify_n = {"n": 0}

    async def verify(packet):
        verify_n["n"] += 1
        row = packet[0]
        if verify_n["n"] == 1:
            return _conflict_table("15", str(row.get("norm_code") or ""))
        return _verified_table("15", str(row.get("norm_code") or ""))

    async def research(open_rows, round_index):
        assert round_index == 1
        assert rejected_norm_codes(open_rows[0])
        return LsrResearchRoundResult(
            rows=[
                {
                    "source_row": "15",
                    "title": "Монтаж блока аварийного питания",
                    "unit": "шт",
                    "norm_code": "ГЭСНм10-02-016-06",
                    "norm_status": "EXACT",
                    "evidence_refs": ["Q1.H1"],
                }
            ],
            queries=("монтаж блока питания светильника",),
            card_ids=("ГЭСНм10-02-016-06",),
        )

    gate = await run_lsr_norm_quality_loop(
        [
            {
                "source_row": "15",
                "title": "Монтаж блока аварийного питания",
                "unit": "шт",
                "norm_code": "ГЭСНм08-02-409-09",
                "norm_status": "EXACT",
            }
        ],
        verify=verify,
        research=research,
        source_locators=["15"],
    )
    bound = gate.rows[0]
    assert bound["norm_code"] == "ГЭСНм10-02-016-06"
    assert bound["norm_status"] == "EXACT_VERIFIED"
    assert bound["_quality_gate"] == "verified"
    assert gate.norms_status == "norms_verified"
    assert any(event.get("stage") == "research" for event in gate.events)


@pytest.mark.asyncio
async def test_repeated_conflict_exhausts_as_conflict_without_code_choosing_a_norm() -> None:
    async def verify(packet):
        row = packet[0]
        return _conflict_table(str(row.get("source_row")), str(row.get("norm_code") or ""))

    async def research(open_rows, round_index):
        return LsrResearchRoundResult(
            rows=[
                {
                    "source_row": "1",
                    "title": "work",
                    "norm_code": f"ГЭСН00-00-000-0{round_index}",
                    "norm_status": "EXACT",
                }
            ],
            queries=(f"query-{round_index}",),
            card_ids=(f"ГЭСН00-00-000-0{round_index}",),
        )

    gate = await run_lsr_norm_quality_loop(
        [{"source_row": "1", "title": "work", "norm_code": "ГЭСН99-99-999-99", "norm_status": "EXACT"}],
        max_research_rounds=2,
        verify=verify,
        research=research,
        source_locators=["1"],
    )
    row = gate.rows[0]
    assert row["_quality_gate"] == "rejected"
    assert row.get("_research_exhausted") is True
    assert row["norm_status"] == "CONFLICT"
    assert row["norm_code"] == "ГЭСН00-00-000-01"
    assert "исчерпаны" in row["quality_message"]
    assert rejected_norm_codes(row)
    assert gate.norms_status == "norms_unverified"


def test_missing_without_rejected_candidate_exhausts_as_missing() -> None:
    from proxy.services.lsr_norm_quality_gate_service import mark_research_exhausted

    row = mark_research_exhausted({
        "source_row": "7",
        "title": "Не найденная работа",
        "norm_status": "NEEDS_RESEARCH",
        "_quality_gate": "research",
    })
    assert row["norm_status"] == "MISSING"
    assert row["_quality_gate"] == "missing"
    assert row["_research_exhausted"] is True


def test_verifier_instruction_is_neutral_and_normalizes_scaled_units() -> None:
    instruction = lsr_verifier_instruction()
    assert "Найди противоречие" not in instruction
    assert "Независимо определи применимость" in instruction
    assert "м² и 100 м2" in instruction


def test_result_instruction_separates_missing_norm_from_missing_price() -> None:
    from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction

    instruction = lsr_result_table_instruction()
    assert "MISSING означает, что norm_code не выбран" in instruction
    assert "Отсутствие цены здесь не оценивай" in instruction


def test_result_instruction_preserves_gapped_pdf_locators() -> None:
    from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction

    instruction = lsr_result_table_instruction()
    assert "строки-раздела" in instruction
    assert "locator работ могут идти с пропусками" in instruction
    assert "не сдвигай следующие работы" in instruction


def test_store_code_variants_insert_colon_for_same_family() -> None:
    variants = store_code_variants("`ГЭСНм10-02-016-06`")
    assert "ГЭСНм:10-02-016-06" in variants
    assert "ГЭСНм10-02-016-06" in variants
    assert authored_norm_code("`ГЭСНм10-02-016-06`") == "ГЭСНм10-02-016-06"
    assert authored_norm_code("—") == ""


def test_prepare_selection_row_strips_backticks() -> None:
    row = prepare_selection_row(
        {"source_row": "15", "norm_code": "`ГЭСНм10-02-016-06`", "norm_status": "EXACT"}
    )
    assert row["norm_code"] == "ГЭСНм10-02-016-06"
    assert row["norm_status"] == "EXACT"


def test_carry_prior_norm_code_restores_unrejected_cipher() -> None:
    prior = {"norm_code": "ГЭСНм10-02-016-06", "_rejected_codes": []}
    incoming = prepare_selection_row({"norm_code": "—", "norm_status": "MISSING"})
    restored = carry_prior_norm_code(prior, incoming)
    assert restored["norm_code"] == "ГЭСНм10-02-016-06"
    assert restored["norm_status"] == "EXACT"


def test_carry_prior_norm_code_does_not_restore_rejected_cipher() -> None:
    prior = {
        "norm_code": "ГЭСНм08-02-409-09",
        "_rejected_codes": ["ГЭСНм08-02-409-09"],
    }
    incoming = prepare_selection_row({"norm_code": "—", "norm_status": "MISSING"})
    restored = carry_prior_norm_code(prior, incoming)
    assert authored_norm_code(restored.get("norm_code")) == ""


def _bap_store_card() -> dict[str, str]:
    return {
        "ref": "STORE:ГЭСНм:10-02-016-06",
        "code": "ГЭСНм:10-02-016-06",
        "title": "Блок аварийного питания",
        "body": "шифр: ГЭСНм:10-02-016-06\nнаименование: Блок аварийного питания",
        "global_evidence_id": "store:ГЭСНм:10-02-016-06",
    }


def test_rag_window_without_selected_code_still_verifies_store_card() -> None:
    chunks = [
        SimpleNamespace(
            content="грунтовка",
            meta={"model_evidence_ref": "Q1.H1", "norm_code": "ГЭСН15-04-006-02"},
        )
    ]
    row = {
        "source_row": "15",
        "title": "Монтаж блока аварийного питания",
        "unit": "шт",
        "norm_code": "`ГЭСНм10-02-016-06`",
        "norm_status": "EXACT",
        "evidence_refs": ["Q1.H1"],
    }

    def lookup(code: str):
        assert "10-02-016-06" in store_code_variants(code)[0] or "10-02-016-06" in code
        return _bap_store_card()

    to_verify, missing = split_rows_missing_selected_card(
        [row], chunks, lookup_norm_card=lookup
    )
    assert missing == []
    assert to_verify[0]["_selected_card_ref"] == "STORE:ГЭСНм:10-02-016-06"
    items = build_blind_review_evidence_items(
        to_verify, chunks, lookup_norm_card=lookup
    )
    joined = "\n".join(items)
    assert "Блок аварийного питания" in joined
    assert "не передана" not in joined


def test_unknown_cipher_still_skips_verify() -> None:
    chunks = [
        SimpleNamespace(
            content="other",
            meta={"model_evidence_ref": "Q1.H1", "norm_code": "ГЭСН15-04-006-02"},
        )
    ]
    row = {
        "source_row": "2",
        "norm_code": "ГЭСН26-01-055-03",
        "norm_status": "EXACT",
        "evidence_refs": ["Q1.H1"],
    }
    to_verify, missing = split_rows_missing_selected_card(
        [row], chunks, lookup_norm_card=lambda _code: None
    )
    assert to_verify == []
    assert missing[0]["norm_status"] == "NEEDS_RESEARCH"
    assert "карточка выбранного шифра" in str(missing[0].get("quality_message") or "")


@pytest.mark.asyncio
async def test_store_hydrate_confirms_authored_code_outside_rag_window() -> None:
    chunk = SimpleNamespace(
        content="грунтовка",
        meta={"model_evidence_ref": "Q1.H1", "norm_code": "ГЭСН15-04-006-02"},
    )

    def lookup(code: str):
        if "10-02-016-06" in str(code):
            return _bap_store_card()
        return None

    async def verify(packet):
        items = build_blind_review_evidence_items(
            packet, [chunk], lookup_norm_card=lookup
        )
        assert any("Блок аварийного питания" in item for item in items)
        assert all("не передана" not in item for item in items)
        return _verified_table("15", "ГЭСНм10-02-016-06")

    async def research(*_args):
        raise AssertionError("research must not run after store-card verify")

    gate = await run_lsr_norm_quality_loop(
        [
            {
                "source_row": "15",
                "title": "Монтаж блока аварийного питания",
                "unit": "шт",
                "norm_code": "`ГЭСНм10-02-016-06`",
                "norm_status": "EXACT",
                "evidence_refs": ["Q1.H1"],
            }
        ],
        verify=verify,
        research=research,
        evidence_chunks=[chunk],
        source_locators=["15"],
        lookup_norm_card=lookup,
    )
    bound = gate.rows[0]
    assert bound["norm_code"] == "ГЭСНм10-02-016-06"
    assert bound["norm_status"] == "EXACT_VERIFIED"
    assert bound["_quality_gate"] == "verified"
    assert any(event.get("stage") == "verify" for event in gate.events)
    assert all(event.get("stage") != "research" for event in gate.events)
    assert all(event.get("stage") != "missing_selected_card" for event in gate.events)


def test_default_lookup_reads_same_family_without_colon() -> None:
    card = default_lookup_authored_norm_card("ГЭСНм10-02-016-06")
    if card is None:
        pytest.skip("smeta catalog unavailable")
    assert "10-02-016-06" in str(card.get("code") or "")
    assert str(card.get("body") or "").startswith("шифр:")
