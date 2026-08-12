import pytest

from proxy.routers import prices


class _FakeEtmClient:
    def collect_quotes(self, items, **kwargs):
        return {
            "schema": "etm_price_quotes_v1",
            "items": items,
            "options": kwargs,
            "quotes": [{
                "material": items[0]["material"],
                "product_code": items[0]["code"],
                "price": 122.0,
                "price_includes_vat": True,
                "vat_pct": 22.0,
            }],
            "missing": 0,
        }

    def browse_goods(self, query, **kwargs):
        return {
            "schema": "etm_goods_browse_v1",
            "selection_owner": "model_or_user",
            "query": query,
            "options": kwargs,
            "count": 1,
            "candidates": [{"gdscode": query, "name": "Пост"}],
        }


@pytest.mark.asyncio
async def test_etm_lookup_routes_validated_items_to_read_only_client(monkeypatch):
    monkeypatch.setattr(prices.etm, "get_client", lambda: _FakeEtmClient())
    request = prices.EtmPriceLookupBatch(
        items=[{
            "code": "9536092",
            "material": "Кнопочный пост",
            "unit": "шт",
        }],
    )

    result = await prices.prices_etm_lookup_batch(request, _user=object())

    assert result["schema"] == "etm_price_quotes_v1"
    assert result["items"][0]["code"] == "9536092"
    assert result["options"]["price_field"] == "pricewnds"


@pytest.mark.asyncio
async def test_etm_lookup_fails_closed_without_credentials(monkeypatch):
    def missing_client():
        raise prices.etm.EtmNotConfiguredError("ETM API is not configured")

    monkeypatch.setattr(prices.etm, "get_client", missing_client)
    request = prices.EtmPriceLookupBatch(
        items=[{"code": "9536092", "material": "Кнопочный пост", "unit": "шт"}],
    )

    with pytest.raises(prices.HTTPException) as error:
        await prices.prices_etm_lookup_batch(request, _user=object())

    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_etm_browse_routes_to_goods_client(monkeypatch):
    monkeypatch.setattr(prices.etm, "get_client", lambda: _FakeEtmClient())
    request = prices.EtmGoodsBrowse(query="9536092", limit=5)

    result = await prices.prices_etm_browse(request, _user=object())

    assert result["schema"] == "etm_goods_browse_v1"
    assert result["selection_owner"] == "model_or_user"
    assert result["query"] == "9536092"


@pytest.mark.asyncio
async def test_etm_browse_fails_closed_without_credentials(monkeypatch):
    def missing_client():
        raise prices.etm.EtmNotConfiguredError("ETM API is not configured")

    monkeypatch.setattr(prices.etm, "get_client", missing_client)

    with pytest.raises(prices.HTTPException) as error:
        await prices.prices_etm_browse(
            prices.EtmGoodsBrowse(query="9536092"),
            _user=object(),
        )

    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_etm_kac_map_endpoint_builds_net_map(monkeypatch):
    monkeypatch.setattr(prices.etm, "get_client", lambda: _FakeEtmClient())
    request = prices.EtmKacMapRequest(
        items=[{"code": "9536092", "material": "Кнопочный пост", "unit": "шт"}],
        resource_codes={"9536092": "01.7.15.01-0011"},
    )

    result = await prices.prices_etm_kac_map(request, _user=object())

    assert result["schema"] == "etm_kac_map_v1"
    assert result["applied"] == 1
    assert result["kac_map"]["01.7.15.01-0011"] == round(122.0 / 1.22, 6)
