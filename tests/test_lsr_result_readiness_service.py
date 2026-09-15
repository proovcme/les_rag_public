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
