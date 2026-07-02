"""Golden-регрессия RIM-сборки на обезличенной позиции.

Fixture без тяжёлого XLSX в репо пинит агрегацию ОЗП/ЭМ/ОТм/М/прямые/ФОТ/НР/СП/Всего.
НР/СП не заданы руками в позиции: они берутся системно по шифру сборника через nr_sp_service.
"""

import json
from pathlib import Path

from proxy.services import rim_lsr_trace_service as rim

FIXTURE = Path("tests/fixtures/smeta/golden_gesnm38_01_001_01.json")


def _golden() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_golden_summary_matches_real_lsr():
    g = _golden()
    s = rim.build_position_trace(g["position"], pricebook=None)["summary"]
    for key, want in g["expected_summary"].items():
        assert abs(s[key] - want) < 0.02, f"{key}: получено {s[key]}, ожидание {want}"


def test_golden_total_exact_and_rows():
    g = _golden()
    trace = rim.build_position_trace(g["position"], pricebook=None)
    assert trace["summary"]["total"] == 110519705.74
    res_rows = [r for r in trace["rows"] if str(r.get("type", "")).startswith("resource_")]
    assert len(res_rows) == 13  # все 13 ресурсов разложены в строки трассы


def test_fixture_is_anonymized():
    raw = FIXTURE.read_text(encoding="utf-8")
    assert "Столп" not in raw and "СПб" not in raw  # ни объекта, ни региона-заказчика


def test_missing_material_price_is_marked_as_kac():
    trace = rim.build_position_trace({
        "name": "Материал без цены",
        "qty": 1,
        "unit": "шт",
        "resources": [{"kind": "material", "name": "Нестандартный материал", "unit": "шт", "qty": 1}],
    })
    row = next(r for r in trace["rows"] if r["type"] == "resource_material")
    assert row["source"] == "needs_kac"
    assert row["meta"]["price_action"] == "needs_kac"
    assert "нужен КАЦ" in trace["summary"]["flags"][0]
