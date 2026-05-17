"""
С.О.В.У.Ш.К.А. v5.0 — Вспомогательные HTML-компоненты
"""
from __future__ import annotations

from nicegui import ui


def _html(content: str) -> "ui.html":
    """Безопасный рендер HTML без скриптов."""
    return ui.html(content, sanitize=False)


def pct_bar_html(segments: list, height: int = 16) -> str:
    """Генерирует HTML полосы прогресса из сегментов [(pct, color), ...]."""
    segs = "".join(
        f'<div class="hbar-seg" style="width:{p:.1f}%;background:{c};"></div>'
        for p, c in segments
    )
    return f'<div class="hbar" style="height:{height}px;">{segs}</div>'


def dot_html(status: str = "ok") -> str:
    cls = {"ok": "", "warn": " dot-warn", "err": " dot-err", "idle": " dot-idle"}.get(status, "")
    return f'<span class="dot{cls}"></span>'


def _status_color(s: str) -> str:
    s = (s or "").upper()
    if s in ("INDEXED", "READY", "COMPLETED"):
        return "ok"
    if s in ("PARSING", "SCANNING", "RUNNING"):
        return "warn"
    if s in ("FAILED", "ERROR"):
        return "err"
    return "idle"


def format_bytes(n: float) -> str:
    if n < 1:
        return f"{n*1024:.0f} MB"
    return f"{n:.1f} GB"
