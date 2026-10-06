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


def test_coverage_resolves_a_work_even_when_its_locator_also_has_resource_decisions():
    from proxy.services.lsr_source_coverage_service import resolve_work_coverage
    rows = [{"source_row": "S!R2", "row_role": "work"},
            {"source_row": "S!R3", "row_role": "work", "covered_by_work_id": "S!R2"},
            {"source_row": "S!R2", "row_role": "resource", "work_row": "S!R2"}]
    resolved = resolve_work_coverage(rows)
    assert resolved[1] == {"target_index": 0, "direct_target_index": 0}


def test_coverage_does_not_choose_between_two_actual_works_at_one_locator():
    from proxy.services.lsr_source_coverage_service import resolve_work_coverage
    rows = [{"source_row": "S!R2", "row_role": "work", "operation_id": "first"},
            {"source_row": "S!R2", "row_role": "work", "operation_id": "second"},
            {"source_row": "S!R3", "row_role": "work", "covered_by_work_id": "S!R2"}]
    assert resolve_work_coverage(rows)[2]["error"] == "coverage_target_ambiguous"


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


def _identity_catalog():
    from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog, CatalogRow
    rows = tuple(CatalogRow(
        locator=f"PDF!R{number}", sheet="PDF", excel_row=number,
        values=("Literal item",), line=f"PDF!R{number}: Literal item", numbers=(),
        row_classification="ambiguous",
    ) for number in (2, 3, 4))
    return AttachmentSourceCatalog(original_name="source.pdf", sheets=(("PDF", 3),),
                                   rows=rows, source_file_id="src_catalog_identity")


def test_coverage_uses_only_catalog_verified_aliases_and_preserves_model_identity():
    import json
    from proxy.services.lsr_source_coverage_service import operation_identity

    catalog = _identity_catalog()
    rows = [
        {"source_row": f"{catalog.source_file_id}!R2", "row_role": "work", "evidence_refs": "Q2.H1"},
        {"source_row": "PDF!R3", "row_role": "material", "work_row": f"{catalog.source_file_id}!R2"},
        {"source_row": f"{catalog.source_file_id}!R4", "row_role": "resource", "work_row": "R2"},
    ]
    before = json.dumps(rows, sort_keys=True)
    identities = [operation_identity(row) for row in rows]
    coverage = build_source_coverage(catalog_locators=catalog.work_locators(), rows=rows,
                                     source_catalog=catalog)
    assert coverage["complete"] is True
    assert coverage["accounted"] == 3
    assert [row["locator"] for row in coverage["roles"]] == catalog.work_locators()
    assert coverage["roles"][1]["work_row"] == "PDF!R2"
    assert coverage["roles"][2]["work_row"] == "PDF!R2"
    assert coverage["supply_parents"] == ["PDF!R2"]
    assert json.dumps(rows, sort_keys=True) == before
    assert [operation_identity(row) for row in rows] == identities


def test_foreign_source_alias_and_forged_catalog_field_do_not_close_coverage_or_parent():
    catalog = _identity_catalog()
    rows = [
        {"source_row": "src_foreign!R2", "row_role": "work", "_catalog_source_locator": "PDF!R2"},
        {"source_row": "PDF!R3", "row_role": "material", "work_row": "src_foreign!R4",
         "_catalog_source_locator": "PDF!R4"},
    ]
    coverage = build_source_coverage(catalog_locators=catalog.work_locators(), rows=rows,
                                     source_catalog=catalog)
    assert coverage["accounted"] == 1
    assert coverage["complete"] is False
    assert {item["kind"] for item in coverage["gaps"]} == {"unexplained", "lost_work_link"}
    assert set(coverage["incomplete_locators"]) == set(catalog.work_locators())


def test_explicit_covered_work_can_reference_catalog_alias_without_changing_fallback_identity():
    import json
    from proxy.services.lsr_source_coverage_service import operation_identity, resolve_work_coverage

    catalog = _identity_catalog()
    rows = [
        {"source_row": "PDF!R2", "row_role": "work", "evidence_refs": "Q1.H1"},
        {"source_row": f"{catalog.source_file_id}!R3", "row_role": "work",
         "covered_by_work_id": f"{catalog.source_file_id}!R2", "evidence_refs": "Q1.H1"},
    ]
    before = json.dumps(rows, sort_keys=True)
    identities = [operation_identity(row) for row in rows]
    assert resolve_work_coverage(rows, source_catalog=catalog)[1] == {
        "target_index": 0, "direct_target_index": 0,
    }
    # A fallback operation identity remains an original-row identity, never a
    # digest of a canonicalised copy.
    rows[1]["covered_by_work_id"] = identities[0]
    assert resolve_work_coverage(rows, source_catalog=catalog)[1]["target_index"] == 0
    rows[1]["covered_by_work_id"] = f"{catalog.source_file_id}!R2"
    assert json.dumps(rows, sort_keys=True) == before
    assert [operation_identity(row) for row in rows] == identities


def test_alias_covered_work_does_not_choose_between_multiple_original_operations():
    from proxy.services.lsr_source_coverage_service import resolve_work_coverage

    catalog = _identity_catalog()
    rows = [
        {"source_row": "PDF!R2", "row_role": "work", "operation_id": "first"},
        {"source_row": f"{catalog.source_file_id}!R2", "row_role": "work", "operation_id": "second"},
        {"source_row": "PDF!R3", "row_role": "work", "covered_by_work_id": "PDF!R2"},
    ]
    assert resolve_work_coverage(rows, source_catalog=catalog)[2]["error"] == "coverage_target_ambiguous"
    rows[2]["covered_by_work_id"] = "second"
    assert resolve_work_coverage(rows, source_catalog=catalog)[2]["target_index"] == 1
    rows[2]["covered_by_work_id"] = "src_foreign!R2"
    assert resolve_work_coverage(rows, source_catalog=catalog)[2]["error"] == "coverage_target_missing"
