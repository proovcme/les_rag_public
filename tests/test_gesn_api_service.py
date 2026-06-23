"""ГЭСН API (cs.smetnoedelo): маппинг JSON→норма + кеш в parquet + чтение через gesn_service."""

from __future__ import annotations

from pathlib import Path

from proxy.services.gesn_api_service import cache_norms, map_norm
from proxy.services import gesn_service

# Пример из доки API (стяжки) — без обращения к сети/квоте.
SAMPLE = {
    "CODE": "ГЭСН 11-01-011-01",
    "NAME": "Устройство стяжек: цементных толщиной 20 мм — 100 м2",
    "COMPOSITION": {"RESOURCES": [
        {"CODE": "1-100-22", "NAME": "Затраты труда рабочих (Средний разряд - 2,2)", "QUAN": "35.6", "UNIT": "чел.-ч"},
        {"CODE": "2", "NAME": "Затраты труда машинистов", "QUAN": "1.27", "UNIT": "чел.-ч"},
        {"CODE": "91.06.06-048", "NAME": "Подъемники одномачтовые", "QUAN": "1.27", "UNIT": "маш.-ч"},
        {"CODE": "91.07.04-002", "NAME": "Вибраторы поверхностные", "QUAN": "7.82", "UNIT": "маш.-ч"},
        {"CODE": "01.7.03.01-0001", "NAME": "Вода", "QUAN": "3.5", "UNIT": "м3"},
        {"CODE": "04.3.01.09", "NAME": "Раствор готовый кладочный", "QUAN": "2.04", "UNIT": "м3"},
    ]},
    "REQUESTS": {"USED": 64, "BALANCE": 436},
}


def test_map_norm_classifies_and_parses():
    n = map_norm(SAMPLE)
    assert n["code"] == "11-01-011-01"          # префикс «ГЭСН» снят
    assert n["unit"] == "100 м2"                  # из «— 100 м2»
    kinds = [r["kind"] for r in n["resources"]]
    assert kinds == ["labor", "machinist", "machine", "machine", "material", "material"]
    labor = n["resources"][0]
    assert labor["per_unit"] == 35.6 and labor["code"] == "1-100-22"
    water = n["resources"][4]
    assert water["kind"] == "material" and water["per_unit"] == 3.5


def test_cache_then_read_via_gesn_service(tmp_path: Path):
    pq = tmp_path / "gesn.parquet"
    n = cache_norms([map_norm(SAMPLE)], parquet_path=pq)
    assert n == 6                                 # 6 строк-ресурсов
    # gesn_service читает из базы (тот же контракт нормы)
    norm = gesn_service.get_norm("11-01-011-01", base_path=str(pq))
    assert norm is not None and norm["unit"] == "100 м2"
    lines = gesn_service.expand_position("ГЭСН11-01-011-01", 2, base_path=str(pq))  # префикс ≡
    assert lines is not None
    labor = next(l for l in lines if l["kind"] == "labor")
    assert round(labor["qty"], 2) == 71.2         # 35.6 × 2
