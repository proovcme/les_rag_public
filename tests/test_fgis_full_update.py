from __future__ import annotations

import json
from pathlib import Path

from proxy.services import fgis_price_fetch_service as price_fetch
from proxy.services import fgis_update_service
from sovushka.pages.instrumenty import _fgis_progress_text
from tools import fgis_full_update
from tools import fgis_update_supervisor


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
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["stage"] == "price_books"
    assert status["activity"] == "downloading"
    assert status["completed"] == 1
    assert status["total"] == 2
    assert status["remaining"] == 1


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
    assert '"Обновить ФСНБ"' in ui
    assert 'api_post("/api/service-sources/fgis/update", {})' in ui
    assert '"Технический журнал"' in ui
    assert 'd.get("message") or d.get("reason")' in ui


def test_dataset_addition_has_no_browser_confirm_and_operator_status_is_human():
    source = (Path(__file__).resolve().parents[1] / "sovushka/pages/samovar.py").read_text(encoding="utf-8")
    add_flow = source.split("async def _do_add():", 1)[1].split("ds = await api_post", 1)[0]

    assert "План загрузки перед Play" not in source
    assert "confirm(" not in add_flow
    assert "ОСТАНОВЛЕНО" in source
    assert "ОЗУ свободно" in source
    assert "активной parse-job нет" not in source


def test_fgis_progress_explains_running_and_interrupted_states():
    raw = {
        "status": "running",
        "stage": "price_books",
        "message": "Скачивается Сплит-форма ФГИС ЦС",
        "completed": 4,
        "total": 10,
        "remaining": 6,
        "percent": 40,
        "eta_seconds": 125,
        "bytes_downloaded": 8 * 1024 * 1024,
        "rate_bytes_per_second": 512 * 1024,
        "current": {"subject": "Москва", "period": "2 квартал 2026"},
    }

    progress = fgis_update_service._progress(raw, running=True)
    summary, detail, percent, running = _fgis_progress_text({"progress": progress})

    assert running is True
    assert percent == 40
    assert "Сплит-формы · 4/10" in summary
    assert "Осталось: 6 книг" in detail
    assert "Примерно: 2 мин 5 с" in detail
    assert "Скачано: 8.0 МБ" in detail
    assert "Средняя скорость: 512.0 КБ/с" in detail

    interrupted = fgis_update_service._progress(raw, running=False)
    assert interrupted["state"] == "interrupted"
    assert "не записал итоговый статус" in interrupted["reason"]


def test_fgis_idle_text_distinguishes_refresh_from_download():
    summary, detail, percent, running = _fgis_progress_text(
        {"progress": {"state": "idle", "reason": "Обновление ещё не запускалось"}}
    )

    assert "ещё не запускалось" in summary
    assert "Обычная кнопка обновления" in detail
    assert percent is None
    assert running is False


def test_price_update_resumes_verified_book_from_checkpoint(tmp_path: Path, monkeypatch):
    import pandas as pd

    parquet = tmp_path / "ready.parquet"
    pd.DataFrame([{"code": "01.1-1"}]).to_parquet(parquet, index=False)
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "schema": "les.fgis.update-checkpoint.v1",
                "books": {
                    "10:102": {"ok": True, "rows": 1, "bytes": 2048, "parquet": str(parquet)},
                    "20:201": {"ok": True, "rows": 1, "bytes": 2048, "parquet": str(parquet)},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(price_fetch, "import_price_zone", lambda **_: (_ for _ in ()).throw(AssertionError("downloaded again")))

    result = fgis_full_update.update_price_books(
        catalog=_catalog(),
        out_root=tmp_path,
        status_out=tmp_path / "status.json",
        checkpoint_out=checkpoint,
        rate=0,
    )

    assert result["done"] == 2
    assert result["failed"] == 0
    assert all(item.get("resumed") for item in result["books"])


def test_operator_start_downloads_prices_when_gesn_is_already_running(tmp_path: Path, monkeypatch):
    from proxy.services import gesn_update_service

    commands: list[list[str]] = []

    class Process:
        pid = 4321

    monkeypatch.setattr(fgis_update_service, "_LOG", tmp_path / "fgis.log")
    monkeypatch.setattr(fgis_update_service, "_PID", tmp_path / "fgis.pid")
    monkeypatch.setattr(fgis_update_service, "DEFAULT_STATUS", tmp_path / "fgis-status.json")
    monkeypatch.setattr(fgis_update_service, "pid_running", lambda pid: pid == 4321)
    monkeypatch.setattr(gesn_update_service, "status", lambda: {"running": True, "progress": {"current_prefix": "12-03"}})
    monkeypatch.setattr(
        fgis_update_service.subprocess,
        "Popen",
        lambda cmd, **_: commands.append(cmd) or Process(),
    )

    result = fgis_update_service.start(include_gesn=True)

    assert result["started"] is True
    assert result["joined_existing_gesn"] is True
    assert "--skip-gesn" in commands[0]


def test_supervisor_restarts_failed_update_from_checkpoint(monkeypatch):
    calls: list[list[str]] = []
    statuses = [
        {"status": "failed", "stage": "failed", "failed_stage": "price_books"},
        {"status": "done", "stage": "done"},
    ]
    writes: list[dict] = []

    class Result:
        def __init__(self, code: int):
            self.returncode = code

    codes = iter([1, 0])
    monkeypatch.setattr(
        fgis_update_supervisor.subprocess,
        "run",
        lambda command, **_: calls.append(command) or Result(next(codes)),
    )
    monkeypatch.setattr(fgis_update_supervisor, "_read_json", lambda _path: statuses.pop(0))
    monkeypatch.setattr(fgis_update_supervisor, "_write_json", lambda _path, payload: writes.append(payload))
    monkeypatch.setattr(fgis_update_supervisor.time, "sleep", lambda _seconds: None)

    code = fgis_update_supervisor.run_supervised(include_gesn=True, all_periods=False, attempts=3)

    assert code == 0
    assert len(calls) == 2
    assert writes[0]["stage"] == "retry"
    assert writes[0]["retry_stage"] == "price_books"
