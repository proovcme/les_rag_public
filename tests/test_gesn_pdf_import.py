"""Парсер официального ФСНБ-2022 (ГЭСН) → Parquet: валидация на ЭТАЛОНЕ 12-01-034-02.

Эталон (из API smetnoedelo, известен точно): норма ГЭСН 12-01-034-02 «Устройство обрешётки
с прозорами из брусков», ед. 100 м2 — состав ресурсов:
  труд рабочих разряд 2,5 = 12.94 чел-ч (labor);
  машинисты               = 1.01  чел/маш-ч (machinist);
  краны башенные 8 т (91.05.01-017)   = 0.97 маш-ч (machine);
  краны автоход 16 т (91.05.05-015)   = 0.01;
  автомобили бортовые (91.14.02-001)  = 0.03;
  гвозди (01.7.15.06-0111)            = 0.0015 т (material);
  бруски (11.1.03.01…)                = 0.4 м3 (material).

Два пути парсера (см. tools/gesn_pdf_import):
  • FGIS-JSON — структурированный официальный JSON ФГИС ЦС (SearchEstimatedRates). Точен до
    знака → проверяем ТОЧНОЕ воспроизведение эталона (offline-фикстура, без сети).
  • PDF — официальный PDF ФГИС ЦС (pdfplumber по геометрии). Печатный PDF даёт машинистов
    1.02 (не 1.01 — расхождение источника, см. ALGO-gesn). Тест PDF скипается, если PDF не
    скачан (data/ в gitignore); проверяет все значения, машинистов — по PDF-факту (1.02).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.gesn_pdf_import import build_parquet, parse_fgis_json, parse_pdf

FIXTURE = Path(__file__).parent / "fixtures" / "gesn_fgis_12-01-034.json"
PDF = Path("data/gesn_pdf/gesn_12-01-034.pdf")
CODE = "12-01-034-02"

# Эталон: (kind, resource_code) → per_unit. Машинисты/рабочие — без кода ресурса.
ETALON = {
    ("labor", ""): 12.94,
    ("machinist", ""): 1.01,
    ("machine", "91.05.01-017"): 0.97,
    ("machine", "91.05.05-015"): 0.01,
    ("machine", "91.14.02-001"): 0.03,
    ("material", "01.7.15.06-0111"): 0.0015,
}
ETALON_BRUSKI = 0.4   # бруски (код 11.1.03.01[-00xx]) — м3


def _etalon_map(recs):
    """{(kind, resource_code): per_unit} для строк нормы-эталона (dedup по ключу)."""
    out = {}
    for r in recs:
        if r["norm_code"] == CODE:
            out[(r["kind"], r["resource_code"])] = r["per_unit"]
    return out


def test_fgis_json_reproduces_etalon_exactly():
    """FGIS-JSON путь воспроизводит эталон ТОЧНО (включая машинистов 1.01)."""
    recs = parse_fgis_json(json.loads(FIXTURE.read_text(encoding="utf-8")))
    m = _etalon_map(recs)
    for key, want in ETALON.items():
        assert key in m, f"нет строки {key}"
        assert abs(m[key] - want) < 1e-9, f"{key}: {m[key]} != {want}"
    # бруски — код с вариативным суффиксом (11.1.03.01 / 11.1.03.01-0076)
    bruski = [v for (k, code), v in m.items()
              if k == "material" and code.startswith("11.1.03.01")]
    assert bruski and abs(bruski[0] - ETALON_BRUSKI) < 1e-9


def test_fgis_json_kinds_classified():
    """Классификация kind по категориям (labor/machinist/machine/material)."""
    recs = [r for r in parse_fgis_json(json.loads(FIXTURE.read_text(encoding="utf-8")))
            if r["norm_code"] == CODE]
    kinds = {r["kind"] for r in recs}
    assert kinds == {"labor", "machinist", "machine", "material"}
    # коды ресурсов ФГИС ЦС только у машин/материалов; у труда — пусто
    for r in recs:
        if r["kind"] in ("labor", "machinist"):
            assert r["resource_code"] == ""
        else:
            assert r["resource_code"]


def test_fgis_json_builds_parquet(tmp_path):
    """Сборка Parquet схемы gesn_import из FGIS-JSON (читается gesn_service)."""
    import pandas as pd

    from tools.gesn_import import RESOURCE_FIELDS

    recs = parse_fgis_json(json.loads(FIXTURE.read_text(encoding="utf-8")))
    out = tmp_path / "gesn.parquet"
    summary = build_parquet(recs, out)
    assert summary["norms"] >= 2 and out.exists()
    df = pd.read_parquet(out)
    assert list(df.columns) == list(RESOURCE_FIELDS)


@pytest.mark.skipif(not PDF.exists(), reason="официальный PDF не скачан (data/ в gitignore)")
def test_pdf_reproduces_etalon():
    """PDF путь: все значения эталона; машинисты — по PDF-факту (1.02, не 1.01)."""
    m = _etalon_map(parse_pdf(PDF))
    # все НЕ-машинистские значения совпадают с эталоном
    for key, want in ETALON.items():
        if key[0] == "machinist":
            continue
        assert key in m and abs(m[key] - want) < 1e-9, f"{key}: {m.get(key)} != {want}"
    bruski = [v for (k, code), v in m.items()
              if k == "material" and code.startswith("11.1.03.01")]
    assert bruski and abs(bruski[0] - ETALON_BRUSKI) < 1e-9
    # машинисты: печатный PDF даёт 1.02 (расхождение PDF↔JSON источника)
    assert abs(m[("machinist", "")] - 1.02) < 1e-9
