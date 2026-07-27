import pytest

from proxy.routers import datasets
from proxy.services.cloud_drive_service import (
    cloud_drive_provider_status,
    discover_cloud_drive_roots,
)


def test_discover_google_and_yandex_sync_roots(tmp_path, monkeypatch):
    monkeypatch.delenv("LES_CLOUD_DRIVE_ROOTS", raising=False)
    monkeypatch.setenv("LES_CLOUD_DRIVE_DISCOVERY", "1")
    google = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-user@example.com" / "My Drive"
    yandex = tmp_path / "Яндекс.Диск"
    google.mkdir(parents=True)
    yandex.mkdir()

    roots = discover_cloud_drive_roots(home=tmp_path)
    by_provider = {item["provider"]: item for item in roots}

    assert by_provider["google_drive"]["path"] == google.resolve().as_posix()
    assert by_provider["yandex_disk"]["path"] == yandex.resolve().as_posix()


def test_cloud_drive_env_roots(tmp_path, monkeypatch):
    custom = tmp_path / "cloud"
    custom.mkdir()
    monkeypatch.setenv("LES_CLOUD_DRIVE_ROOTS", f"Проектный диск={custom}")

    roots = discover_cloud_drive_roots(home=tmp_path)

    assert roots[0]["label"].startswith("Проектный диск")
    assert roots[0]["path"] == custom.resolve().as_posix()


def test_cloud_drive_provider_status_reads_env(monkeypatch):
    monkeypatch.setenv("LES_GOOGLE_DRIVE_ACCESS_TOKEN", "g-token")
    monkeypatch.delenv("LES_YANDEX_DISK_TOKEN", raising=False)
    monkeypatch.delenv("YANDEX_DISK_TOKEN", raising=False)

    status = cloud_drive_provider_status()

    assert status["google_drive"]["configured"] is True
    assert status["yandex_disk"]["configured"] is False


@pytest.mark.asyncio
async def test_cloud_drive_list_requires_token(monkeypatch):
    monkeypatch.delenv("LES_GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_ACCESS_TOKEN", raising=False)

    with pytest.raises(datasets.HTTPException) as exc:
        await datasets.cloud_drive_list(
            datasets.CloudDriveListRequest(provider="google_drive", locator="root"),
            _admin=object(),
        )

    assert exc.value.status_code == 400
    assert "LES_GOOGLE_DRIVE_ACCESS_TOKEN" in str(exc.value.detail)
