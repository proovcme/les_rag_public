import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PWA = ROOT / "frontend" / "pwa"


def test_pwa_manifest_has_stable_sovushka_identity():
    manifest = json.loads((PWA / "manifest.webmanifest").read_text(encoding="utf-8"))

    assert manifest["name"] == "С.О.В.У.Ш.К.А. · Л.Е.С."
    assert manifest["short_name"] == "Совушка"
    assert manifest["start_url"] == "/classic?source=pwa"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#176b46"
    assert manifest["background_color"] == "#f4f6f2"
    assert any(icon["src"] == "/pwa-icons/icon.png" for icon in manifest["icons"])


def test_shared_shell_mounts_and_registers_pwa_assets():
    shell = (ROOT / "sovushka_ng.py").read_text(encoding="utf-8")

    assert 'app.add_static_files("/pwa", str(pwa_dir))' in shell
    assert 'app.add_static_files("/pwa-icons", str(pwa_icon_dir))' in shell
    assert '@app.get("/service-worker.js", include_in_schema=False)' in shell
    assert '"Service-Worker-Allowed": "/"' in shell
    assert 'rel="manifest" href="/pwa/manifest.webmanifest"' in shell
    assert 'rel="apple-touch-icon" href="/pwa-icons/icon.png"' in shell
    assert 'name="theme-color" content="#176b46"' in shell
    assert "navigator.serviceWorker.register('/service-worker.js', {scope: '/'})" in shell


def test_service_worker_is_deny_by_default_for_runtime_content():
    worker = (PWA / "service-worker.js").read_text(encoding="utf-8")

    for forbidden in (
        "/api/",
        "/lite-api/",
        "/stream",
        "/events",
        "/documents",
        "/files",
        "text/event-stream",
    ):
        assert forbidden in worker
    assert "request.method !== 'GET'" in worker
    assert "NEVER_CACHE_PREFIXES.some" in worker
    assert "PRECACHE_URLS.includes(url.pathname)" in worker
    assert "cache.put(request" not in worker
    assert "fetch(request).catch" in worker
    assert "caches.match(OFFLINE_URL)" in worker


def test_offline_shell_keeps_only_an_unsent_local_draft():
    offline = (PWA / "offline.html").read_text(encoding="utf-8")

    assert "Узел Л.Е.С. сейчас недоступен" in offline
    assert "Черновик сохранён только на этом устройстве" in offline
    assert "localStorage" in offline
    assert "fetch(" not in offline
    assert "serviceWorker" not in offline
    assert "replay" not in offline.casefold()
