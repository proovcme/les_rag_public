# -*- coding: utf-8
"""§2 (23.09): a large multi-sheet ВОР stalled forever because completion re-queued every
locator that failed a *quality* gap.  A material/equipment row that the model already
adjudicated but that has no work_row link (and a legitimately norm-less equipment item)
is flagged incomplete by build_source_coverage, so structurally_complete_source_keys never
closes it and every resume re-swept the same rows.  The fix separates "adjudicated"
(terminal role given) from "structurally complete"; completion keys on the union so such
rows finalize a partial file instead of blocking forever."""
from __future__ import annotations

from types import SimpleNamespace

from proxy.services.chat_evidence_application_service import (
    adjudicated_source_keys,
    structurally_complete_source_keys,
)


class _Catalog:
    """Minimal duck-typed source catalog: stable locators, locator == raw row id."""

    def __init__(self, locators):
        self._locators = [str(x).strip() for x in locators]

    def work_locators(self):
        return list(self._locators)

    def lookup(self, raw):
        s = str(raw).strip()
        return SimpleNamespace(locator=s) if s in self._locators else None


def _rows():
    return [
        # a real work with a norm: structurally complete AND adjudicated
        {"source_row": "Спецификация!R3", "row_role": "work", "norm_code": "ГЭСН-2020-01-01"},
        # material the model already decided but with no work_row link:
        # a quality gap, yet terminal — must NOT block completion any more
        {"source_row": "Спецификация!R5", "row_role": "material"},
        # equipment in a specification that legitimately has no applicable norm
        {"source_row": "Спецификация!R6", "row_role": "equipment"},
    ]


def test_material_and_equipment_are_not_structurally_complete():
    catalog = _Catalog(["Спецификация!R3", "Спецификация!R5", "Спецификация!R6"])
    complete = structurally_complete_source_keys(_rows(), catalog)
    assert "Спецификация!R3" in complete
    # the whole stall defect: these decided rows were treated as unfinished
    assert "Спецификация!R5" not in complete
    assert "Спецификация!R6" not in complete


def test_adjudicated_keys_close_decided_rows():
    catalog = _Catalog(["Спецификация!R3", "Спецификация!R5", "Спецификация!R6"])
    adjudicated = adjudicated_source_keys(_rows(), catalog)
    assert adjudicated == {"Спецификация!R3", "Спецификация!R5", "Спецификация!R6"}


def test_completion_union_leaves_only_undecided_rows_unfinished():
    locators = ["Спецификация!R3", "Спецификация!R5", "Спецификация!R6",
                "Спецификация!R7"]
    catalog = _Catalog(locators)
    rows = _rows()  # R7 never received any decision
    complete_keys = structurally_complete_source_keys(rows, catalog)
    adjudicated_keys = adjudicated_source_keys(rows, catalog)
    unfinished = [
        loc for loc in catalog.work_locators()
        if loc not in complete_keys and loc not in adjudicated_keys
    ]
    # only the genuinely untouched position remains; the decided-but-imperfect rows close
    assert unfinished == ["Спецификация!R7"]


def test_row_without_source_is_not_adjudicated():
    catalog = _Catalog(["Спецификация!R3"])
    assert adjudicated_source_keys([{"row_role": "work"}], catalog) == set()
