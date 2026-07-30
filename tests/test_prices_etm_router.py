import pytest

from proxy.routers import prices


class _FakeEtmClient:
    def collect_quotes(self, items, **kwargs):
        return {
            "schema": "etm_price_quotes_v1",
            "items": items,
            "options": kwargs,
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
