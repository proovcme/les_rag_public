"""Анти-дрейф плистов (Ц3, AUDIT_CORE §0): home из LES_HOME/плиста, не клобберить рабочий."""

from __future__ import annotations

import plistlib
from pathlib import Path

from tools import les_runtime_control as rc

SVC = rc.SERVICES["mlx"]   # реальный шаблон mlx_launchd.plist лежит в ROOT


def test_render_substitutes_home(tmp_path: Path):
    t = tmp_path / "x.plist"
    t.write_text("dir __LES_ROOT__ and /Users/ovc/Projects/LES_v2 end", encoding="utf-8")
    out = rc._render_plist_template(t, "/Users/ovc/LES")
    assert "/Users/ovc/LES" in out
    assert "__LES_ROOT__" not in out and "Projects/LES_v2" not in out


def test_resolve_home_prefers_les_home(monkeypatch):
    monkeypatch.setattr(rc, "LES_HOME", "/Users/ovc/LES")
    assert rc._resolve_home(SVC) == "/Users/ovc/LES"


def test_resolve_home_from_existing_plist(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rc, "LES_HOME", "")
    monkeypatch.setattr(rc, "LAUNCH_AGENTS", tmp_path)
    (tmp_path / SVC.agent_plist).write_bytes(plistlib.dumps({"WorkingDirectory": "/Users/ovc/LES"}))
    assert rc._resolve_home(SVC) == "/Users/ovc/LES"   # уважаем рабочий плист, не папку скрипта


def test_install_does_not_overwrite_existing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rc, "LAUNCH_AGENTS", tmp_path)
    monkeypatch.setattr(rc, "_PLIST_FORCE", False)
    dst = tmp_path / SVC.agent_plist
    dst.write_bytes(b"WORKING PLIST")
    rc._install(SVC)                                    # без force → не трогаем
    assert dst.read_bytes() == b"WORKING PLIST"


def test_install_writes_when_absent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rc, "LAUNCH_AGENTS", tmp_path)
    monkeypatch.setattr(rc, "LES_HOME", "/Users/ovc/LES")
    monkeypatch.setattr(rc, "_PLIST_FORCE", False)
    rc._install(SVC)
    txt = (tmp_path / SVC.agent_plist).read_text(encoding="utf-8")
    assert "/Users/ovc/LES" in txt and "Projects/LES_v2" not in txt


def test_install_force_overwrites(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rc, "LAUNCH_AGENTS", tmp_path)
    monkeypatch.setattr(rc, "LES_HOME", "/Users/ovc/LES")
    dst = tmp_path / SVC.agent_plist
    dst.write_bytes(b"OLD")
    assert rc._install(SVC, force=True) is True
    assert dst.read_bytes() != b"OLD" and "/Users/ovc/LES" in dst.read_text(encoding="utf-8")


def test_install_force_requests_launchd_reload_when_rendered_plist_is_unchanged(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rc, "LAUNCH_AGENTS", tmp_path)
    monkeypatch.setattr(rc, "LES_HOME", "/Users/ovc/LES")
    rc._install(SVC, force=True)

    assert rc._install(SVC, force=True) is True


def test_mlx_template_pins_the_qwen_embedding_contract():
    data = plistlib.loads((rc.ROOT / SVC.repo_plist).read_bytes())
    env = data["EnvironmentVariables"]

    assert env["LES_EMBED_PROFILE"] == "qwen"
    assert env["EMBEDDING_MODEL"] == "Qwen/Qwen3-Embedding-0.6B"
    assert env["EMBED_MODEL"] == "qwen3-embedding-0.6b"
    assert env["EMBED_BACKEND"] == "coreml"
    assert env["COREML_EMBED_FALLBACK"] == "false"
    assert env["VALIDATOR_BACKEND"] == "rules"
    assert env["MLX_MAIN_TTL_SEC"] == "3600"
    assert env["MLX_RAM_WARN_FREE_GB"] == "6"
    assert env["MLX_RAM_KILL_FREE_GB"] == "4"
    assert env["MLX_SWAP_RELIEF_FREE_GB"] == "5"
    assert env["MLX_SWAP_STALE_MAX_USED_GB"] == "12"
    # Выбор генеративной модели живёт в едином реестре/.env и остаётся доступен GUI;
    # plist не должен молча возвращать модель после рестарта.
    assert "MLX_MODEL" not in env
    assert "LLM_MODEL" not in env
