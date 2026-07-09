from proxy.services.electrical_evidence_summary_service import build_electrical_evidence_summary


def test_electrical_evidence_summary_aggregates_loads_and_matches_cable_materials():
    schematic = {
        "schema": "electrical_schematic_manifest_v1",
        "file_name": "loads.pdf",
        "pages": [
            {
                "load_tables": [
                    {
                        "rows": [
                            {
                                "source_ref": "loads.pdf#page=1#table=1#row=2",
                                "panel": "ГРЩ1",
                                "consumer": "ЩО1",
                                "line_id": "Л1",
                                "p_installed_kw": 10.0,
                                "p_calc_kw": 7.5,
                                "s_calc_kva": 8.0,
                                "i_calc_a": 12.0,
                                "cable": "ВВГнг-LS 3х2,5",
                                "cable_length_m": 35.0,
                                "protection": "QF1 16А",
                            },
                            {
                                "source_ref": "loads.pdf#page=1#table=1#row=3",
                                "panel": "ГРЩ1",
                                "consumer": "ЩО2",
                                "p_installed_kw": 5.0,
                                "p_calc_kw": 4.0,
                                "cable": "",
                            },
                        ]
                    }
                ],
                "candidate_circuits": [
                    {
                        "source_ref": "scheme.pdf#page=4",
                        "from_node": "ГРЩ1",
                        "to_node": "ЩО1",
                        "line_id": "Л1",
                        "cable": "ВВГнг-LS 3х2,5",
                        "protection": "QF1 16А",
                    }
                ],
            }
        ],
    }
    materials = {
        "schema": "electrical_material_manifest_v1",
        "file_name": "so.pdf",
        "pages": [
            {
                "material_rows": [
                    {
                        "source_ref": "so.pdf#page=2#row=5",
                        "doc_role": "so",
                        "item_kind": "cable",
                        "name": "Кабель ВВГнг-LS 3х2,5",
                        "unit": "м",
                        "quantity": 40.0,
                        "cable_mark": "ВВГнг-LS 3х2,5",
                        "quantity_m": 40.0,
                    },
                    {
                        "source_ref": "so.pdf#page=1#row=1",
                        "doc_role": "so",
                        "item_kind": "panel",
                        "name": "Щит освещения ЩО1",
                        "unit": "компл.",
                        "quantity": 1.0,
                        "ip_rating": "IP31",
                    },
                ]
            }
        ],
    }

    result = build_electrical_evidence_summary([schematic], [materials])

    assert result["schema"] == "electrical_evidence_summary_v1"
    assert result["summary"]["load_rows"] == 2
    assert result["load_aggregates_by_panel"][0]["panel"] == "ГРЩ1"
    assert result["load_aggregates_by_panel"][0]["p_installed_kw"] == 15.0
    assert result["load_aggregates_by_panel"][0]["p_calc_kw"] == 11.5
    assert result["cable_inventory"][0]["identity"] == "ВВГнг-LS 3х2,5"
    assert result["load_to_material_cable_matches"][0]["matched"] is True
    assert result["so_to_vor_seeds"][0]["source_ref"] == "so.pdf#page=2#row=5"
    assert any(issue["type"] == "load_row_missing_cable" for issue in result["issues"])


def test_electrical_evidence_summary_reports_material_cable_without_mark():
    materials = {
        "schema": "electrical_material_manifest_v1",
        "file_name": "vor.pdf",
        "pages": [
            {
                "material_rows": [
                    {
                        "source_ref": "vor.pdf#page=1#row=2",
                        "doc_role": "vor",
                        "item_kind": "cable",
                        "name": "Монтаж греющего кабеля",
                        "unit": "м",
                        "quantity": 12.0,
                        "quantity_m": 12.0,
                    }
                ]
            }
        ],
    }

    result = build_electrical_evidence_summary([], [materials])

    assert result["summary"]["cable_material_rows"] == 1
    assert any(issue["type"] == "material_cable_missing_mark" for issue in result["issues"])


def test_electrical_evidence_summary_uses_load_table_file_name_as_panel_hint():
    schematic = {
        "schema": "electrical_schematic_manifest_v1",
        "file_name": "Таблица расчета нагрузок ГРЩ2.pdf",
        "pages": [
            {
                "load_tables": [
                    {
                        "rows": [
                            {
                                "source_ref": "loads.pdf#page=1#table=1#row=2",
                                "consumer": "Освещение",
                                "p_installed_kw": 3.0,
                                "p_calc_kw": 2.0,
                            }
                        ]
                    }
                ],
                "candidate_circuits": [],
            }
        ],
    }

    result = build_electrical_evidence_summary([schematic], [])

    assert result["load_aggregates_by_panel"][0]["panel"] == "ГРЩ2"
    assert not any(issue["type"] == "load_row_missing_panel" for issue in result["issues"])


def test_electrical_evidence_summary_does_not_flood_model_with_gap_rows():
    rows = [
        {
            "source_ref": f"loads.pdf#page=1#table=1#row={idx}",
            "panel": "ГРЩ1",
            "consumer": f"Потребитель {idx}",
            "p_calc_kw": 1.0,
        }
        for idx in range(20)
    ]
    schematic = {
        "schema": "electrical_schematic_manifest_v1",
        "file_name": "395.01-B481.120100.6.4-ИОС.ЭС Таблица расчета нагрузок ГРЩ1.pdf",
        "pages": [{"load_tables": [{"rows": rows}], "candidate_circuits": []}],
        "summary": {"load_rows": len(rows), "candidate_circuits": 0},
    }

    result = build_electrical_evidence_summary([schematic], [])

    assert result["summary"]["issue_count"] == 40
    assert result["issue_counts"] == {
        "load_row_missing_cable": 20,
        "load_row_missing_protection": 20,
    }
    assert len([issue for issue in result["issues"] if issue["type"] == "load_row_missing_cable"]) == 5
    assert all(issue["semantics"] == "extractor_gap_example_not_design_verdict" for issue in result["issues"])
    assert result["model_reading_contract"]["role"] == "navigation_context_for_model"
    assert result["source_navigation"][0]["discipline_hint"] == "electrical_power"
    assert result["source_navigation"][0]["role_hint"] == "load_calculation"
