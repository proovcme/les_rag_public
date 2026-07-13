from __future__ import annotations

from pathlib import Path

import pytest

from proxy.routers import prices


class _FakePriceBook:
    region = "Санкт-Петербург"
    quarter = "2 квартал 2026"

    def __init__(self):
        self.calls: list[list[str]] = []

    def lookup_many(self, codes):
        values = list(codes)
        self.calls.append(values)
        return {
            code: (
                {"code": code, "price_current_eff": 123.45, "price_base": 100.0}
                if code == "01.1"
                else None
            )
            for code in values
        }


@pytest.mark.asyncio
async def test_price_lookup_batch_loads_book_once_and_preserves_missing(monkeypatch):
    book = _FakePriceBook()
    loaded: list[str] = []
    monkeypatch.setattr(prices, "_resolve_book", lambda _name: Path("data/price_base/spb.parquet"))

    def fake_get_pricebook(path: str):
        loaded.append(path)
        return book

    monkeypatch.setattr(prices.fps, "get_pricebook", fake_get_pricebook)
    response = await prices.prices_lookup_batch(
        prices.PriceLookupBatch(codes=["01.1", "missing", "01.1"]),
        _user=object(),
    )

    assert loaded == ["data/price_base/spb.parquet"]
    assert book.calls == [["01.1", "missing"]]
    assert response["requested"] == 2
    assert response["found"] == 1
    assert response["missing"] == 1
    assert response["rows"][0]["price"] == 123.45
    assert response["rows"][1] == {"found": False, "code": "missing"}
