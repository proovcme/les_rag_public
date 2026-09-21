from proxy.services.lsr_source_coverage_service import (
    apply_confirmed_data,
    build_source_coverage,
    inferred_row_role,
    work_row_key,
)


def test_relative_work_link_is_scoped_to_its_source_sheet():
    row = {"source_row": "Sheet two!R4", "row_role": "work", "work_row": "R4"}
    assert work_row_key(row) == "Sheet two!R4"
    assert row["work_row"] == "R4"
    assert build_source_coverage(catalog_locators=["Sheet two!R4"], rows=[row])["complete"]
    assert work_row_key({**row, "work_row": "Other!R4"}) == "Other!R4"
    assert work_row_key({**row, "work_row": "10-01-001-01"}) == "10-01-001-01"


def test_coverage_requires_every_locator_and_work_row_link() -> None:
    coverage = build_source_coverage(
        catalog_locators=["A!R2", "A!R3", "A!R4"],
        rows=[
            {"source_row": "A!R2", "row_role": "work", "norm_code": "10-01-001-01"},
            {"source_row": "A!R3", "row_role": "resource", "work_row": "A!R2"},
        ],
        remaining_locators=["A!R4"],
    )

    kinds = {item["kind"] for item in coverage["gaps"]}
    assert coverage["accounted"] == 2
    assert coverage["complete"] is False
    assert "unprocessed" in kinds


def test_confirmed_overlay_never_replaces_norm_code() -> None:
    rows = apply_confirmed_data(
        [{"source_row": "A!R2", "norm_code": "10-01-001-01", "quantity": 1}],
        {
            "A!R2": {
                "norm_code": "99-99-999-99",
                "conversion_factor": 12,
                "conversion_source": "упаковка",
            }
        },
    )

    assert rows[0]["norm_code"] == "10-01-001-01"
    assert rows[0]["conversion_factor"] == 12
    assert inferred_row_role(rows[0]) == "work"


def test_unresolved_row_needs_an_open_gap() -> None:
    coverage = build_source_coverage(
        catalog_locators=["A!R2"],
        rows=[{"source_row": "A!R2", "row_role": "unresolved"}],
    )

    kinds = {item["kind"] for item in coverage["gaps"]}
    assert "open_gap" in kinds
    assert coverage["complete"] is False


def test_resource_parent_must_be_an_actual_work_decision():
    rows = [
        {"source_row": "A!R2", "row_role": "material", "work_row": "R2"},
        {"source_row": "A!R3", "row_role": "equipment", "work_row": "R2"},
        {"source_row": "A!R4", "row_role": "resource", "work_row": "R5"},
    ]
    coverage = build_source_coverage(
        catalog_locators=["A!R2", "A!R3", "A!R4", "A!R5"], rows=rows,
    )
    assert {g["locator"] for g in coverage["gaps"] if g["kind"] == "parent_not_work"} == {
        "A!R2", "A!R3", "A!R4",
    }
    assert rows[0]["row_role"] == "material"
    assert rows[0]["work_row"] == "R2"


def test_material_and_work_on_same_locator_are_structurally_complete():
    coverage = build_source_coverage(
        catalog_locators=["PDF!R9"],
        rows=[
            {
                "source_row": "PDF!R9",
                "row_role": "work",
                "norm_code": "ГЭСН17-01-010-02",
            },
            {
                "source_row": "PDF!R9",
                "row_role": "material",
                "work_row": "R9",
                "title": "Люк ревизионный",
            },
        ],
    )
    assert coverage["complete"] is True
    assert coverage["gap_count"] == 0
    assert coverage["roles"][0]["role"] == "work"


def test_coverage_keeps_all_incomplete_locators_beyond_display_limit():
    locators = [f"A!R{i}" for i in range(1, 102)]
    coverage = build_source_coverage(
        catalog_locators=locators,
        rows=[{"source_row": key, "row_role": "material", "work_row": key} for key in locators],
    )
    assert coverage["gap_count"] == 101
    assert len(coverage["gaps"]) == 80
    assert set(coverage["incomplete_locators"]) == set(locators)
