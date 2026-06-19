"""Режимы local/cloud/mix — пресеты ЛЕС. Без записи в репозиторный .env (ENV_PATH → tmp)."""
from __future__ import annotations

from pathlib import Path

import pytest

from proxy.services import preset_service as ps
from proxy.services import preset_chat_service as pc


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.setattr(ps, "ENV_PATH", tmp_path / ".env")
    for k in ("LES_LLM_PROVIDER", "RAG_OCR_BACKEND", "LES_ASBUILT_OCR_ENGINE"):
        monkeypatch.setenv(k, "x")  # monkeypatch вернёт после теста
    return tmp_path


@pytest.mark.parametrize("alias,canon", [
    ("локальный", "local"), ("офлайн", "local"), ("облако", "cloud"),
    ("микс", "mix"), ("гибрид", "mix"), ("cloud", "cloud"), ("чушь", None),
])
def test_normalize(alias, canon):
    assert ps.normalize_preset(alias) == canon


def test_apply_preset_writes_env_and_environ(isolated_env):
    import os
    res = ps.apply_preset("облако")  # рус-алиас
    assert res["preset"] == "cloud"
    assert os.getenv("LES_LLM_PROVIDER") == "openai"
    assert os.getenv("LES_ASBUILT_OCR_ENGINE") == "cloud"
    assert (isolated_env / ".env").read_text().count("LES_LLM_PROVIDER=openai") == 1


def test_apply_unknown_raises(isolated_env):
    with pytest.raises(ValueError):
        ps.apply_preset("квантовый")


def test_current_preset_detected(isolated_env):
    ps.apply_preset("local")
    assert ps.current_preset() == "local"
    ps.apply_preset("mix")
    assert ps.current_preset() == "mix"


def test_mix_local_chat_cloud_asbuilt():
    assert ps.PRESETS["mix"]["LES_LLM_PROVIDER"] == "mlx"        # чат локально (валидируется)
    assert ps.PRESETS["mix"]["LES_ASBUILT_OCR_ENGINE"] == "cloud"  # плотные таблицы в облако


# ── чат-канал ──

@pytest.mark.parametrize("q,hit", [
    ("режим", True), ("какой сейчас режим?", True), ("переключи на облако режим", True),
    ("/режим микс", True), ("сколько кабеля", False),
])
def test_is_preset_query(q, hit):
    assert pc.is_preset_query(q) is hit


def test_chat_status_no_apply(isolated_env):
    res = pc.maybe_handle_preset_query("какой режим?")
    assert res["operation"] == "preset_status"


def test_chat_apply(isolated_env):
    res = pc.maybe_handle_preset_query("режим локальный")
    assert res["operation"] == "preset_applied" and res["preset"] == "local"
