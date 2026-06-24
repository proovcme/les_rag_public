"""Evidence contract — инварианты (Construction RAG Harness v0.1)."""

import pytest

from proxy.services.evidence_contract import (
    ConstructionHarnessResult,
    EvidenceError,
    EvidenceItem,
    EvidenceType,
    numbers_in_answer_have_provenance,
)


def test_evidence_contract_retrieved_block_requires_source():
    # RETRIEVED без source_refs — нарушение инварианта
    with pytest.raises(EvidenceError):
        EvidenceItem(EvidenceType.RETRIEVED, "норма СП", value=None)
    ok = EvidenceItem(EvidenceType.RETRIEVED, "норма СП", source_refs=["СП 1.13130#п.5.4"])
    assert ok.source_refs


def test_evidence_contract_computed_requires_provenance():
    # COMPUTED с числом без формулы/входов/источника — нарушение
    with pytest.raises(EvidenceError):
        EvidenceItem(EvidenceType.COMPUTED, "итог", value=1000.0)
    ok = EvidenceItem(EvidenceType.COMPUTED, "итог", value=1000.0, formula="qty×цена")
    assert ok.value == 1000.0


def test_missing_and_blocked_cannot_carry_number():
    with pytest.raises(EvidenceError):
        EvidenceItem(EvidenceType.MISSING, "плита", value=720.0)
    with pytest.raises(EvidenceError):
        EvidenceItem(EvidenceType.BLOCKED, "стены", value=10.0)


def test_numbers_in_answer_have_provenance_holds():
    from proxy.services.evidence_contract import EvidenceBlock
    items = [EvidenceItem(EvidenceType.COMPUTED, "x", value=5.0, formula="a*b"),
             EvidenceItem(EvidenceType.RETRIEVED, "y", value=7.0, source_refs=["doc#1"])]
    r = ConstructionHarnessResult(answer_data={}, evidence_blocks=[EvidenceBlock(EvidenceType.COMPUTED, "b", items)])
    assert numbers_in_answer_have_provenance(r) is True
