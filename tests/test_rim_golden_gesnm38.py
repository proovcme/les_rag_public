"""Golden-регрессия RIM-сборки на ОБЕЗЛИЧЕННОЙ реальной позиции из GRAND-ЛСР (handoff Codex, шаг #4).

ГЭСНм38-01-001-01 (металлоконструкции, 2кв2026): 13 ресурсов (труд / 2 машиниста / 6 машин / 4 материала),
НР=93% / СП=62%. Минимальная self-contained fixture (код/объём/ресурсы/цены/ожидаемый свод) — без тяжёлого
XLSX в репо. Пинит агрегацию ОЗП/ЭМ/ОТм/М/прямые/ФОТ/НР/СП/Всего на реальном кейсе: Всего = 118 799 319.94 ₽.
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
    assert trace["summary"]["total"] == 118799319.94  # реальный итог позиции
    res_rows = [r for r in trace["rows"] if str(r.get("type", "")).startswith("resource_")]
    assert len(res_rows) == 13  # все 13 ресурсов разложены в строки трассы


def test_fixture_is_anonymized():
    raw = FIXTURE.read_text(encoding="utf-8")
    assert "Столп" not in raw and "СПб" not in raw  # ни объекта, ни региона-заказчика
