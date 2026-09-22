from proxy.services.lsr_result_readiness_service import (
    build_lsr_result_readiness,
    format_lsr_readiness_notice,
)


def test_readiness_splits_file_norms_and_prices() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[
            {"source_row": "СКС!R2", "norm_code": "10-06-024-01", "norm_status": "EXACT"},
            {"source_row": "СКС!R3", "norm_code": "", "norm_status": "MISSING"},
        ],
        missing=["price_missing:10-06-024-01"],
        pricing_status="priced_partial",
        remaining_locators=["СКС!R4"],
        catalog_work_count=3,
    )

    assert readiness["dimensions"]["file"]["ready"] is True
    assert readiness["dimensions"]["norms"]["complete"] is False
    assert readiness["dimensions"]["prices"]["complete"] is False
    actions = {item["id"] for item in readiness["actions"]}
    assert actions == {"repack", "resume", "refine", "enter_data"}
    notice = format_lsr_readiness_notice(readiness, filename="LSR.xlsx")
    assert "Файл: файл готов" in notice
    assert "Покрытие исходника: не полное" in notice
    assert "Нормы: не полные" in notice
    assert "Цены: не полные" in notice
    assert "СКС!R3" in notice
    assert "СКС!R4" in notice
    assert "10-06-024-01" in notice


def test_readiness_failed_file_asks_repack_without_model() -> None:
    readiness = build_lsr_result_readiness(
        packaged=False,
        packaging_failed=True,
        packaging_code="WORKBOOK_GENERATION_FAILED",
        rows=[{"source_row": "PDF!R2", "norm_code": "ГЭСНм10-01-001-01", "norm_status": "EXACT"}],
    )

    assert readiness["dimensions"]["file"]["status"] == "failed"
    assert "без модели" in readiness["dimensions"]["file"]["action"]
    assert any(item["id"] == "repack" for item in readiness["actions"])


def test_complete_result_has_no_operator_gap_actions() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[{
            "source_row": "PDF!R2",
            "norm_code": "ГЭСНм10-01-001-01",
            "norm_status": "EXACT",
            "row_role": "work",
        }],
        pricing_status="priced_final",
        catalog_work_count=1,
    )

    assert readiness["dimensions"]["file"]["ready"] is True
    assert readiness["dimensions"]["coverage"]["complete"] is True
    assert readiness["dimensions"]["norms"]["complete"] is True
    assert readiness["dimensions"]["prices"]["complete"] is True
    assert readiness["technical_complete"] is True
    assert readiness["estimate_complete"] is True
    assert readiness["actions"] == []
    assert format_lsr_readiness_notice(readiness, filename="LSR.xlsx") == "ЛСР собрана. Файл: LSR.xlsx."


def test_saved_material_does_not_disappear_from_resume_readiness():
    locators = [f"A!R{i}" for i in range(1, 102)]
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[{"source_row": key, "row_role": "material", "work_row": key} for key in locators],
        remaining_locators=locators,
        catalog_locators=locators,
        paused=True,
    )
    assert readiness["remaining_locators"] == locators
    assert readiness["estimate_complete"] is False
    assert readiness["technical_complete"] is True


def test_stage_v_readiness_reports_composition_and_amounts() -> None:
    """§6: works / materials / equipment / norms / calculated counts are shown separately."""
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[
            {"source_row": "СКС!R1", "row_role": "header", "title": "Раздел"},
            {
                "source_row": "СКС!R2",
                "row_role": "work",
                "norm_code": "ГЭСН12-01-034-02",
                "norm_status": "EXACT",
            },
            {"source_row": "СКС!R3", "row_role": "material", "work_row": "СКС!R2"},
        ],
        pricing_status="priced_partial",
        calculated_positions=2,
        confirmed_amount=1000.0,
        preliminary_amount=500.0,
    )
    counts = readiness["counts"]
    assert counts["works"] == 1
    assert counts["materials"] == 1
    assert counts["headers"] == 1
    assert counts["norms_selected"] == 1
    assert counts["calculated_positions"] == 2
    notice = format_lsr_readiness_notice(readiness, filename="LSR.xlsx")
    assert "Состав: работ 1, материалов 1" in notice
    assert "норм выбрано 1" in notice
    assert "позиций рассчитано 2" in notice
    assert "Подтверждённая сумма 1000" in notice
def test_stage_d_price_basis_mismatch_blocks_price_dimension() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[{
            "source_row": "СКС!R2",
            "row_role": "work",
            "norm_code": "ГЭСН10-01-001-01",
            "norm_status": "EXACT",
        }],
        pricing_status="priced_final",
        catalog_work_count=1,
        price_basis={
            "requested": "3 квартал 2026",
            "actual_quarter": "2 квартал 2026 г.",
            "match": "mismatch",
            "note": "Запрошена база «3 квартал 2026», фактически применена «2 квартал 2026 г.».",
        },
    )
    assert readiness["dimensions"]["prices"]["complete"] is False
    assert readiness["dimensions"]["prices"]["basis"]["match"] == "mismatch"
    assert readiness["estimate_complete"] is False
    notice = format_lsr_readiness_notice(readiness, filename="LSR.xlsx")
    assert "Ценовая база не совпадает" in notice
    assert "2 квартал 2026" in notice


def test_stage_d_unspecified_basis_stays_visible_on_complete_result() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[],
        pricing_status="priced_final",
        price_basis={
            "match": "unspecified",
            "note": "База не указана; применён 2 квартал 2026.",
        },
    )
    assert readiness["dimensions"]["prices"]["complete"] is True
    notice = format_lsr_readiness_notice(readiness, filename="LSR.xlsx")
    assert notice.startswith("ЛСР собрана.")
    assert "Ценовая база: База не указана" in notice


def test_stage_d_gap_fields_survive_readiness_projection() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[{"source_row": "СКС!R2", "row_role": "work"}],
        price_gaps=[{
            "resource": "Лоток",
            "code": "R-1",
            "quantity": 30,
            "unit": "м",
            "position_code": "ГЭСН08-02-395-01",
            "dependent_calculations": ["итог позиции ГЭСН08-02-395-01"],
            "checked_basis": "2 квартал 2026 г.; Санкт-Петербург",
            "action": "Задайте цену для Лоток.",
        }],
    )
    gap = readiness["dimensions"]["prices"]["gaps"][0]
    assert gap["unit"] == "м"
    assert gap["position_code"] == "ГЭСН08-02-395-01"
    assert gap["dependent_calculations"] == ["итог позиции ГЭСН08-02-395-01"]
    assert gap["checked_basis"].startswith("2 квартал")
