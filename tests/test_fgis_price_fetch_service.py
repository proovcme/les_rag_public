"""ФГИС ЦС наполнение: метаданные/файл-выгрузка → локальный Parquet, локаль-первый lookup.

Сеть мокается (канал недоверенный, в офлайн-гейте его нет). Проверяем:
* slug stem из субъекта/квартала;
* import_region: метаданные-чейн → файл → Parquet (через мок-загрузчик, реальный парс);
* lookup_local_first: локаль первой; refresh_on_miss off → КАЦ-сигнал; добор по промаху;
* graceful: сбой канала → ok=False / needs_kac (не падаем).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proxy.services import fgis_price_fetch_service as pf
from proxy.services import fgis_price_service as fps
from tools.fgis_price_bulk_import import _slug

# Мини-«Сплит-форма» (как в test_fgis_price_service): шапка + нумерация + данные.
HEADERS = [
    "Код ресурса, услуги",
    "Наименование строительного ресурса, услуги",
    "Единица измерения",
    "Отпускная цена в уровне цен по состоянию на 01.01.2022",
    "Сметная цена в уровне цен по состоянию на 01.01.2022",
    "Номер группы однородных строительных ресурсов",
    "Наименование группы однородных строительных ресурсов",
    "Сметная цена в текущем уровне цен, руб.",
    "Индекс изменения сметной стоимости к группе",
]
DATA = [
    ("07.2.07.04-0007", "Конструкции стальные индив. изготовления", "т", 100000.0, 115282.0, "700", "Сталь", "-", 1.39),
    ("01.7.15.06-0111", "Гвозди строительные", "т", 68000.0, 70296.2, "511", "Метизы", "-", 1.3),
]


def _make_split_form(path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Сплит-форма индексов и сметных цен"])
    ws.append(["Наименование субъекта Российской Федерации", "Санкт-Петербург"])
    ws.append(HEADERS)
    ws.append([str(i) for i in range(1, 10)])
    for rec in DATA:
        ws.append(list(rec))
    wb.save(path)


def test_slug_from_subject_quarter():
    assert _slug("Санкт-Петербург", "2 квартал 2025 г.") == "sankt-peterburg_2kv2025"
    assert _slug("Москва", "1 квартал 2026") == "moskva_1kv2026"


def _patch_channel(monkeypatch, *, split_src: Path | None):
    """Заглушить сетевой чейн ФГИС ЦС детерминированными метаданными + локальным файлом."""
    monkeypatch.setattr(pf, "list_subjects",
                        lambda: [{"id": 316, "name": "город Санкт-Петербург"}])
    monkeypatch.setattr(pf, "price_zones",
                        lambda sid: [{"id": 206, "name": "город Санкт-Петербург"}])
    monkeypatch.setattr(pf, "periods",
                        lambda zid: [{"id": 422, "name": "2 квартал 2025 г."}])

    def _fake_fetch(zone_id, period_id, dest):
        if split_src is None:
            raise RuntimeError("канал недоступен")
        Path(dest).write_bytes(split_src.read_bytes())
        return split_src.stat().st_size

    monkeypatch.setattr(pf, "fetch_split_form", _fake_fetch)


def test_import_region_builds_parquet(tmp_path, monkeypatch):
    src = tmp_path / "split.xlsx"
    _make_split_form(src)
    _patch_channel(monkeypatch, split_src=src)

    out_root = tmp_path / "price_base"
    res = pf.import_region(subject="Петербург", quarter="2 квартал 2025",
                           name="spb_test", out_root=out_root)
    assert res["ok"] is True
    assert res["rows"] == 2
    assert res["period_id"] == 422 and res["price_zone_id"] == 206
    pb = fps.PriceBook.from_parquet(res["parquet"])
    assert pb.lookup("07.2.07.04-0007")["price_current_eff"] == round(115282.0 * 1.39, 2)


def test_import_region_graceful_on_channel_failure(tmp_path, monkeypatch):
    _patch_channel(monkeypatch, split_src=None)  # fetch бросает
    res = pf.import_region(subject="Петербург", quarter="2 квартал 2025",
                           name="spb_test", out_root=tmp_path / "pb")
    assert res["ok"] is False and res["stage"] == "download"


def test_import_region_period_not_found(tmp_path, monkeypatch):
    _patch_channel(monkeypatch, split_src=None)
    res = pf.import_region(subject="Петербург", quarter="9 квартал 1999",
                           name="x", out_root=tmp_path / "pb")
    assert res["ok"] is False and res["stage"] == "period"


def test_lookup_local_first_hits_local(tmp_path, monkeypatch):
    src = tmp_path / "split.xlsx"
    _make_split_form(src)
    out = tmp_path / "pb" / "spb.parquet"
    fps.build_price_parquet(src, out)
    monkeypatch.setattr(fps, "available_pricebooks", lambda *a, **k: [str(out)])
    fps.get_pricebook.cache_clear()

    r = pf.lookup_local_first("01.7.15.06-0111")
    assert r["found"] is True and r["source"] == "local" and r["needs_kac"] is False
    assert r["price"] == round(70296.2 * 1.3, 2)


def test_lookup_local_first_miss_no_refresh_is_kac(tmp_path, monkeypatch):
    src = tmp_path / "split.xlsx"
    _make_split_form(src)
    out = tmp_path / "pb" / "spb.parquet"
    fps.build_price_parquet(src, out)
    monkeypatch.setattr(fps, "available_pricebooks", lambda *a, **k: [str(out)])
    fps.get_pricebook.cache_clear()

    # код не из выгрузки, добор отключён → корректный КАЦ-сигнал, канал не дёргается
    r = pf.lookup_local_first("99.99.99-9999", refresh_on_miss=False)
    assert r["found"] is False and r["needs_kac"] is True and r["source"] == "none"


def test_lookup_local_first_refresh_then_absent_is_kac(tmp_path, monkeypatch):
    # Локальная книга пуста; добор приносит выгрузку без искомого кода → корректный КАЦ.
    src = tmp_path / "split.xlsx"
    _make_split_form(src)
    _patch_channel(monkeypatch, split_src=src)
    out_root = tmp_path / "price_base"
    monkeypatch.setattr(fps, "DEFAULT_PRICE_ROOT", out_root)
    monkeypatch.setattr(fps, "available_pricebooks",
                        lambda root=out_root: [str(p) for p in Path(root).glob("*.parquet")] if Path(root).exists() else [])
    fps.get_pricebook.cache_clear()

    r = pf.lookup_local_first("08.3.11.01-0091", refresh_on_miss=True, name="spb_refresh")
    assert r["found"] is False and r["needs_kac"] is True and r["source"] == "fgis"
    assert r["refresh"]["ok"] is True


def test_lookup_local_first_refresh_finds_code(tmp_path, monkeypatch):
    # Добор приносит выгрузку, где код ЕСТЬ → ценится (source=fgis).
    src = tmp_path / "split.xlsx"
    _make_split_form(src)
    _patch_channel(monkeypatch, split_src=src)
    out_root = tmp_path / "price_base"
    monkeypatch.setattr(fps, "DEFAULT_PRICE_ROOT", out_root)
    monkeypatch.setattr(fps, "available_pricebooks",
                        lambda root=out_root: [str(p) for p in Path(root).glob("*.parquet")] if Path(root).exists() else [])
    fps.get_pricebook.cache_clear()

    r = pf.lookup_local_first("07.2.07.04-0007", refresh_on_miss=True, name="spb_refresh")
    assert r["found"] is True and r["source"] == "fgis" and r["needs_kac"] is False
