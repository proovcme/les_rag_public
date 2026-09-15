from proxy.services.lsr_source_coverage_service import (
    apply_confirmed_data,
    build_source_coverage,
    inferred_row_role,
)


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
