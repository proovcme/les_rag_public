from __future__ import annotations

from pathlib import Path

from proxy.services import fgis_price_fetch_service as price_fetch
from tools import fgis_full_update


def _catalog() -> dict:
    return {
        "subjects": [
            {
                "id": 1,
                "name": "Тестовый край",
                "zones": [
                    {
                        "id": 10,
                        "name": "Зона А",
                        "periods": [
                            {"id": 102, "name": "2 квартал 2026 г."},
                            {"id": 101, "name": "1 квартал 2026 г."},
                        ],
                    },
                    {
                        "id": 20,
                        "name": "Зона Б",
                        "periods": [{"id": 201, "name": "4 квартал 2025 г."}],
                    },
                ],
            }
        ]
    }


def test_discover_catalog_keeps_every_zone_and_sorts_periods(monkeypatch):
    monkeypatch.setattr(price_fetch, "list_subjects", lambda: [{"id": 1, "name": "Регион"}])
    monkeypatch.setattr(
        price_fetch,
        "price_zones",
        lambda _subject_id: [{"id": 10, "name": "А"}, {"id": 20, "name": "Б"}],
    )
    monkeypatch.setattr(
        price_fetch,
        "periods",
        lambda zone_id: (
            [{"id": 1, "name": "4 квартал 2025"}, {"id": 2, "name": "1 квартал 2026"}]
            if zone_id == 10
            else [{"id": 3, "name": "2 квартал 2024"}]
        ),
    )

    catalog = fgis_full_update.discover_catalog()

    zones = catalog["subjects"][0]["zones"]
    assert [zone["id"] for zone in zones] == [10, 20]
    assert [period["id"] for period in zones[0]["periods"]] == [2, 1]


def test_price_update_downloads_latest_period_of_every_zone(tmp_path: Path, monkeypatch):
    calls: list[tuple[int, int, str]] = []

    def fake_import(**kwargs):
        calls.append((kwargs["zone"]["id"], kwargs["period"]["id"], kwargs["name"]))
        return {"ok": True, "rows": 12, "parquet": str(tmp_path / f"{kwargs['name']}.parquet")}

    monkeypatch.setattr(price_fetch, "import_price_zone", fake_import)
    result = fgis_full_update.update_price_books(
        catalog=_catalog(), out_root=tmp_path, status_out=tmp_path / "status.json", rate=0
    )

    assert [(zone, period) for zone, period, _ in calls] == [(10, 102), (20, 201)]
    assert all(f"zone-{zone}" in name for zone, _, name in calls)
    assert result["requested"] == 2
    assert result["done"] == 2
    assert result["rows"] == 24


def test_full_update_persists_catalog_and_manifest_without_gesn(tmp_path: Path, monkeypatch):
    catalog = _catalog()
    monkeypatch.setattr(fgis_full_update, "discover_catalog", lambda: catalog)
    monkeypatch.setattr(
        fgis_full_update,
        "update_price_books",
        lambda **_: {"mode": "latest_per_zone", "requested": 2, "done": 2, "failed": 0, "rows": 24, "books": [], "errors": []},
    )

    result = fgis_full_update.run_update(
        include_gesn=False,
        status_out=tmp_path / "status.json",
        catalog_out=tmp_path / "catalog.json",
        manifest_out=tmp_path / "manifest.json",
        price_root=tmp_path / "prices",
    )

    assert result["status"] == "done"
    assert result["scope"] == ["public_catalog", "split_forms"]
    assert (tmp_path / "catalog.json").exists()
    assert (tmp_path / "manifest.json").exists()
    assert "Bearer" in (tmp_path / "manifest.json").read_text(encoding="utf-8")


def test_full_fgis_update_is_wired_to_operator_api_and_gui():
    root = Path(__file__).resolve().parents[1]
    routes = (root / "proxy/routers/service_sources.py").read_text(encoding="utf-8")
    ui = (root / "sovushka/pages/instrumenty.py").read_text(encoding="utf-8")

    assert '@router.post("/fgis/update")' in routes
    assert "fgis_update_service.start(include_gesn=True, all_periods=False)" in routes
    assert "СКАЧАТЬ ФГИС ЦС" in ui
    assert 'api_post("/api/service-sources/fgis/update", {})' in ui
    assert "каталог, Сплит-формы всех ценовых зон и ГЭСН" in ui
    assert 'd.get("message") or d.get("reason")' in ui
