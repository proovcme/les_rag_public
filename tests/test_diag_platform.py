from sovushka.pages import diag


def test_windows_diagnostics_use_windows_runtime_labels(monkeypatch):
    monkeypatch.setattr(diag.sys, "platform", "win32")

    html = diag._build_diag_map_html([])
    glossary = diag._build_acronym_glossary_html()

    assert "Ресурсы Windows" in html
    assert "Docker Desktop и локальные процессы" in html
    assert "Ollama" in html
    assert "Ресурсы Mac" not in html
    assert "MLX Host" not in html
    assert "Apple MLX" not in glossary


def test_macos_diagnostics_keep_mlx_and_launchagents(monkeypatch):
    monkeypatch.setattr(diag.sys, "platform", "darwin")

    html = diag._build_diag_map_html([])

    assert "Ресурсы Mac" in html
    assert "MLX Host" in html
    assert "LaunchAgents" in html
    assert "Ресурсы Windows" not in html


def test_windows_does_not_mask_missing_docker(monkeypatch):
    monkeypatch.setattr(diag.sys, "platform", "win32")
    payload = {
        "checks": [
            {
                "name": "Docker",
                "status": "err",
                "value": "not running",
                "message": "",
            }
        ]
    }

    normalized = diag._normalize_diag_payload(payload)

    assert normalized["checks"][0]["status"] == "err"
    assert normalized["checks"][0]["name"] == "Docker"
