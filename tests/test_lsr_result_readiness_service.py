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


def test_material_only_source_cannot_claim_complete_work_estimate():
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[{"source_row": "СКС!R6", "row_role": "material", "title": "Cabinet"}],
        catalog_work_count=1,
        catalog_locators=["СКС!R6"],
        pricing_status="priced_final",
        price_basis={"match": "exact"},
    )

    assert readiness["counts"]["works"] == 0
    assert readiness["dimensions"]["norms"]["complete"] is False
    assert readiness["estimate_complete"] is False
    assert any(gap["kind"] == "missing_work_layer" for gap in readiness["dimensions"]["norms"]["gaps"])


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


def test_unspecified_basis_blocks_complete_result_until_operator_selects_period() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[],
        pricing_status="priced_final",
        price_basis={
            "match": "unspecified",
            "note": "База не указана; применён 2 квартал 2026.",
        },
    )
    assert readiness["dimensions"]["prices"]["complete"] is False
    assert readiness["estimate_complete"] is False
    assert "город" in readiness["dimensions"]["prices"]["action"]
    notice = format_lsr_readiness_notice(readiness, filename="LSR.xlsx")
    assert notice.startswith("ЛСР собрана частично.")
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


def test_durable_draft_only_document_is_never_announced_as_ready() -> None:
    # The panel may hold a draft of a finished research; that is not the
    # estimate, and calling it ready would hide the only available repair.
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[
            {
                "source_row": "АР!R11",
                "norm_code": "ГЭСНр1-01-001",
                "norm_status": "EXACT",
                "row_role": "work",
            }
        ],
        pricing_status="priced_final",
        catalog_work_count=1,
        document_state="draft_only",
    )

    assert readiness["dimensions"]["file"]["ready"] is False
    assert "repack" in {item["id"] for item in readiness["actions"]}
    assert "DRAFT_ONLY_DOCUMENT" in readiness["dimensions"]["file"]["action"]


def test_durable_pending_document_keeps_the_repair_offered() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[
            {
                "source_row": "АР!R11",
                "norm_code": "ГЭСНр1-01-001",
                "norm_status": "EXACT",
                "row_role": "work",
            }
        ],
        pricing_status="priced_final",
        catalog_work_count=1,
        document_state="pending",
    )

    assert readiness["dimensions"]["file"]["ready"] is False
    assert readiness["actions"][0]["kind"] == "repack"
    document = readiness["document"]
    assert document["state"] == "pending"
    assert document["durable_state"] == "pending"
    # The operator is told the model decisions survived, which is what makes
    # the rebuild an obvious move instead of a fresh research.
    assert "не сохранён" in document["note"]
    assert "без повторного расчёта" in document["note"]
    assert document["download_url"] == ""


def test_ready_document_is_reported_separately_from_outstanding_actions() -> None:
    """A closed estimate stays "nothing outstanding"; the file is its own field."""

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[
            {
                "source_row": "АР!R11",
                "norm_code": "ГЭСНр1-01-001",
                "norm_status": "EXACT",
                "row_role": "work",
            }
        ],
        pricing_status="priced_final",
        catalog_work_count=1,
        document_state="ready",
        download_url="/api/artifacts/rev_final/download",
    )

    assert readiness["actions"] == []
    assert readiness["document"]["state"] == "ready"
    assert readiness["document"]["download_url"] == "/api/artifacts/rev_final/download"
    # Re-entering a finished research must not read as an invitation to start
    # another one.
    assert "завершено" in readiness["continue_action"]


def _vor_rows() -> list[dict]:
    return [
        {
            "source_row": "АР!R11",
            "norm_code": "ГЭСНр1-01-001",
            "norm_status": "EXACT",
            "row_role": "work",
        },
        {
            "source_row": "АР!R23",
            "norm_code": "",
            "norm_status": "NEEDS_RESEARCH",
            "row_role": "work",
        },
    ]


def test_finished_research_never_offers_the_continue_gesture() -> None:
    """A terminal job cannot take another packet, so «Продолжить» must not appear."""

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=_vor_rows(),
        missing=["price_missing:ГЭСНр1-01-001"],
        pricing_status="priced_partial",
        remaining_locators=["АР!R81", "АР!R86"],
        catalog_work_count=3,
        document_state="ready",
        download_url="/api/artifacts/rev_final/download",
        job_status="complete",
    )

    ids = {item["id"] for item in readiness["actions"]}
    assert "resume" not in ids
    assert "document" in ids
    # The advice now names where the open rows already live instead of sending
    # the operator to a gesture that cannot close them.
    assert "Проверка" in readiness["dimensions"]["norms"]["action"]
    assert "Продолжите" not in readiness["dimensions"]["norms"]["action"]
    assert [gap["action"] for gap in readiness["dimensions"]["norms"]["gaps"]]
    assert all("Продолжите" not in gap["action"] for gap in readiness["dimensions"]["norms"]["gaps"])
    assert "объявлен" in readiness["dimensions"]["norms"]["gaps"][0]["action"]
    # The coverage service writes its own gap actions: they are reworded too.
    assert all(
        "Продолжите" not in str(gap.get("action") or "")
        for gap in readiness["dimensions"]["coverage"]["gaps"]
    )
    assert "завершено" in readiness["continue_action"]


def test_open_research_still_offers_the_continue_gesture() -> None:
    """Only a finished job loses the gesture: an open one keeps the old wording."""

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=_vor_rows(),
        missing=["price_missing:ГЭСНр1-01-001"],
        pricing_status="priced_partial",
        remaining_locators=["АР!R81", "АР!R86"],
        catalog_work_count=3,
        document_state="draft_only",
        job_status="running",
    )

    ids = {item["id"] for item in readiness["actions"]}
    assert "resume" in ids
    assert "document" not in ids
    assert "Продолжите незакрытые строки" in readiness["dimensions"]["norms"]["action"]


def test_failed_research_is_finished_too() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=_vor_rows(),
        remaining_locators=["АР!R81"],
        catalog_work_count=2,
        document_state="ready",
        download_url="/api/artifacts/rev_final/download",
        job_status="failed",
    )

    ids = {item["id"] for item in readiness["actions"]}
    assert "resume" not in ids
    assert "document" in ids


def test_readiness_notice_of_a_finished_job_does_not_point_at_continue() -> None:
    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=_vor_rows(),
        missing=["price_missing:ГЭСНр1-01-001"],
        pricing_status="priced_partial",
        remaining_locators=["АР!R81", "АР!R86"],
        catalog_work_count=3,
        document_state="ready",
        download_url="/api/artifacts/rev_final/download",
        job_status="complete",
    )

    notice = format_lsr_readiness_notice(readiness, filename="LSR_ВОР.xlsx")
    assert "Продолжите" not in notice
    assert "Проверка" in notice


def test_finished_and_fully_closed_job_offers_no_action_at_all() -> None:
    """"Nothing outstanding" must keep meaning exactly that: an empty action list."""

    readiness = build_lsr_result_readiness(
        packaged=True,
        rows=[
            {
                "source_row": "АР!R11",
                "norm_code": "ГЭСНр1-01-001",
                "norm_status": "EXACT",
                "row_role": "work",
            }
        ],
        pricing_status="priced_final",
        catalog_work_count=1,
        document_state="ready",
        download_url="/api/artifacts/rev_final/download",
        job_status="complete",
    )

    assert readiness["actions"] == []
    assert readiness["document"]["state"] == "ready"
    assert readiness["document"]["download_url"] == "/api/artifacts/rev_final/download"
