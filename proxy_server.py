"""Thin ASGI entrypoint for LES Proxy v3."""

from proxy.app import create_app

app = create_app()
