"""Offline tests for the icon builder (Pillow fallback path)."""

from __future__ import annotations

import importlib.util

import pytest

from tools import build_icons

_HAS_PIL = importlib.util.find_spec("PIL") is not None
pytestmark = pytest.mark.skipif(not _HAS_PIL, reason="Pillow not installed")


def test_pick_renderer_returns_callable():
    render, label = build_icons.pick_renderer()
    assert render is not None
    assert label in {"cairosvg", "pillow"}


def test_pillow_renderer_rasterizes_les_svg(tmp_path):
    from PIL import Image

    out = tmp_path / "icon.png"
    build_icons._render_pillow(build_icons.SVG, 128, out)
    img = Image.open(out)
    assert img.size == (128, 128)
    assert img.mode == "RGBA"
    # Background corner is the dark rounded-rect fill; centre has the green spruce.
    centre = img.convert("RGB").getpixel((64, 90))
    assert centre != (0, 0, 0)  # something was drawn, not transparent/blank


def test_build_ico_writes_multi_size(tmp_path, monkeypatch):
    render, _ = build_icons.pick_renderer()
    ico = tmp_path / "LES.ico"
    monkeypatch.setattr(build_icons, "ICO", ico)
    assert build_icons.build_ico(render) is True
    assert ico.exists() and ico.stat().st_size > 0


def test_hex_parses_color():
    assert build_icons._hex("#4c8bf5") == (0x4C, 0x8B, 0xF5)
