"""Детерминированная ценовая книга для тестов, которые считают деньги.

Some tests sit above the calculator and cannot hand it a pricebook directly: an endpoint
resolves the book from the request, a chat route resolves the system default, an artifact
resolves it from the question text.  Left alone, all three read whatever ценовая база happens
to be installed on the operator's machine, so a pinned sum silently becomes a machine fact.

This module stubs the single lower seam both ``lsr_assembly_service._resolve_book`` and
``smeta_core.calculator._pricebook`` call through (``fgis_price_service.resolve_pricebook_path``
+ ``get_pricebook``), and answers with the deterministic gold book of
``tests/test_rim_lsr_trace_service.py`` — the measured rows of ``sankt-peterburg_2kv2026``
recorded in ``stage_b/live_830/gold_rebaseline_830.json``.  A test that needs the honest
no-basis outcome asks for the ``"none"`` variant and gets ``None``, the same answer a machine
with no installed book would give.
"""

from __future__ import annotations

import pytest

from proxy.services import fgis_price_service as fps
from tests import test_rim_lsr_trace_service as gold

GOLD_BOOK_STEM = "sankt-peterburg_2kv2026"


@pytest.fixture
def gold_pricebook(monkeypatch, request):
    """Return the gold book (or ``None`` for the ``"none"`` variant) on every resolution."""

    book = None if getattr(request, "param", "spb") == "none" else gold._Book()

    def _resolve(_book=None, **_kw):
        return GOLD_BOOK_STEM

    def _load(_path, *_a, **_kw):
        return book

    monkeypatch.setattr(fps, "resolve_pricebook_path", _resolve)
    monkeypatch.setattr(fps, "get_pricebook", _load)
    return book
