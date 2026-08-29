from __future__ import annotations

import asyncio
from pathlib import Path
import time

from proxy.routers.status_page import StatusPageState, set_status_page_state, status_page


ROOT = Path(__file__).resolve().parents[1]


def test_status_page_does_not_present_public_forest_site_as_sovushka() -> None:
    set_status_page_state(StatusPageState(crag_stats={}, proxy_start=time.time()))

    response = asyncio.run(status_page())
    html = response.body.decode("utf-8")

    assert "les.ovc.me" not in html
    assert "Совушка UI обычно доступна на порту :8051" in html


def test_user_facing_auth_templates_do_not_claim_public_runtime() -> None:
    paths = (
        ROOT / "backend/auth.py",
        ROOT / "backend/login.html",
        ROOT / "sovushka/auth.py",
    )

    for path in paths:
        assert "les.ovc.me" not in path.read_text(encoding="utf-8"), path
