import json
from pathlib import Path

from proxy.services.estimate_math_service import (
    formula_quantity_audit,
    parse_ru_number,
    percentage_audit,
    quantity_audit_report,
    quantity_sum_audit,
)
from proxy.services.prompt_registry_service import build_mode_system_prompt, build_smeta_batch_system_prompt
from proxy.services.smeta_chat_adapter_service import _smeta_direct_numeric_audit_context


FIXTURE = Path("tests/fixtures/smeta/stolp_quantity_conflict.json")


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _mass_audit() -> dict:
    data = _fixture()
    return quantity_sum_audit(
        name="mass_rows_sum",
        inputs=data["mass_rows"],
        unit="кг",
        compared_to=[data["table_total"], data["text_total"]],
        partial_groups=data["partial_groups"],
    )


def test_smeta_stolp_detects_mass_conflict():
    audit = _mass_audit()

    assert audit["status"] == "conflict"
    assert audit["result"] == {"value": 696891.72, "unit": "кг"}
    assert audit["result_alt_units"] == [{"value": 696.89172, "unit": "т"}]
    assert {item["label"]: item["delta"] for item in audit["compared_to"]} == {
        "table_total": 32180.0,
        "text_total": 32180.6,
    }


def test_smeta_stolp_does_not_accept_wrong_table_total():
    audit = _mass_audit()
    partial = audit["partial_matches"][0]

    assert partial["label"] == "rows_1_10"
    assert partial["value"] == 664711.72
    assert partial["matches"] == "table_total"
    assert audit["result"]["value"] != partial["value"]


def test_smeta_stolp_quantity_conflict_form_blocks_priced_final():
    data = _fixture()
    report = quantity_audit_report([_mass_audit()])
    form = data["quantity_conflict_form"]

    assert report["audits"][0]["status"] == "conflict"
    assert [row["volume"] for row in form] == ["664,71112 т", "664,71172 т", "696,89172 т"]
    assert "priced_final" in data["forbidden_answer_markers"]


def test_smeta_direct_prompt_leaves_estimation_strategy_to_model():
    prompt = build_mode_system_prompt("smeta_direct")

    assert "Модель выбирает работы, нормы, аналоги, покрытия и цены" in prompt
    assert "код только исполняет, проверяет, считает и экспортирует" in prompt
    assert "основной метод оценки" not in prompt
    assert "таблица двух оценок" not in prompt.lower()
    assert "маршрут поиска нормы" not in prompt.lower()


def test_smeta_stolp_bolt_counts_split_correctly():
    data = _fixture()["bolt_inputs"]
    intertier = formula_quantity_audit(
        name="intertier_m20_bolts",
        factors=[
            {"label": "joints", "value": data["intertier_joints"]},
            {"label": "bolts_per_joint", "value": data["bolts_per_intertier_joint_m20"]},
        ],
        unit="шт",
    )
    control = percentage_audit(
        name="control_tightening",
        base=intertier["result"]["value"],
        percent=data["control_tightening_percent"],
        unit="шт",
    )

    assert data["base_anchor_m36"] == 48
    assert data["base_anchor_m24"] == 96
    assert intertier["result"] == {"value": 1440.0, "unit": "шт"}
    assert control["result"] == {"value": 288.0, "unit": "шт"}


def test_smeta_role_pack_has_no_case_specific_constants():
    forbidden = [
        "664711",
        "696891",
        "32180",
        "Пьедестал",
        "барельеф",
        "столп",
        "Liebherr",
    ]
    role_pack_text = Path("config/prompts/smeta_estimator_role.json").read_text(encoding="utf-8")
    prompt_text = build_smeta_batch_system_prompt("Верни JSON.") + "\n" + build_mode_system_prompt("smeta_direct")
    compact = (role_pack_text + "\n" + prompt_text).lower().replace(" ", "")

    for marker in forbidden:
        assert marker.lower().replace(" ", "") not in compact


def test_smeta_quantity_audit_parses_russian_numbers():
    assert parse_ru_number("664 711,12") == 664711.12
    assert parse_ru_number("32\u00a0180,00") == 32180.0
    assert parse_ru_number("72,05258") == 72.05258


def test_smeta_direct_numeric_audit_context_finds_partial_table_total():
    data = _fixture()
    lines = [
        "Общая масса (сталь + бронза) составляет 664 711,12 кг, 11 ярусов.",
        "№ яруса | Условное наименование | Итого масса яруса в сборе, кг | комментарии",
    ]
    for idx, row in enumerate(data["mass_rows"], 1):
        lines.append(f"{idx} | {row['label']} | {row['value']} |")
    lines.append(f"ИТОГО | ИТОГО | {data['table_total']['value']} |")

    ctx = _smeta_direct_numeric_audit_context("\n".join(lines))

    assert "696891.72 кг" in ctx
    assert "696.89172" in ctx
    assert "delta=32180.0 кг" in ctx
    assert "delta=32180.6 кг" in ctx
    assert "source_delta table_total_vs_text_total: 0.6 кг" in ctx
    assert "partial_match rows_1_10" in ctx
    assert "matches table_total" in ctx


def test_smeta_direct_numeric_audit_context_accepts_markdown_edge_pipes():
    data = _fixture()
    lines = [
        "Общая масса (сталь + бронза) составляет 664 711,12 кг, 11 ярусов.",
        "| № яруса | Условное наименование | Итого масса яруса в сборе, кг | комментарии |",
        "| --- | --- | --- | --- |",
    ]
    for idx, row in enumerate(data["mass_rows"], 1):
        lines.append(f"| {idx} | {row['label']} | {row['value']} | |")
    lines.append(f"| ИТОГО | | {data['table_total']['value']} | |")

    ctx = _smeta_direct_numeric_audit_context("\n".join(lines))

    assert "696891.72 кг" in ctx
    assert "delta=32180.0 кг" in ctx
    assert "partial_match rows_1_10" in ctx


def test_smeta_direct_numeric_audit_context_accepts_docx_source_refs():
    data = _fixture()
    lines = [
        "attachments/input.docx#para2: Общая масса (сталь + бронза) составляет 664 711,12 кг, 11 ярусов.",
        (
            "attachments/input.docx#t0r0: № яруса | Условное наименование | "
            "Итого масса яруса в сборе, кг | комментарии"
        ),
    ]
    for idx, row in enumerate(data["mass_rows"], 1):
        lines.append(f"attachments/input.docx#t0r{idx}: {idx} | {row['label']} | {row['value']} |")
    lines.append(f"attachments/input.docx#t0r12: ИТОГО | ИТОГО | {data['table_total']['value']} |")

    ctx = _smeta_direct_numeric_audit_context("\n".join(lines))

    assert "696891.72 кг" in ctx
    assert "delta=32180.0 кг" in ctx
    assert "source_delta table_total_vs_text_total: 0.6 кг" in ctx
    assert "partial_match rows_1_10" in ctx
