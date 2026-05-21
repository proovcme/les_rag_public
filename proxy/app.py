"""FastAPI application factory for LES Proxy v3."""

from __future__ import annotations

from proxy.legacy_app import app


def create_app():
    return app

