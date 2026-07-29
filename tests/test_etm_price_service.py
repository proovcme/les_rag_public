import httpx

from proxy.services.etm_price_service import (
    EtmConfig,
    EtmPriceClient,
    configuration_status,
)


def test_configuration_status_never_exposes_credentials():
    status = configuration_status({
        "LES_ETM_LOGIN": "operator",
        "LES_ETM_PASSWORD": "top-secret",
        "LES_ETM_BASE_URL": "https://itest2.etm.ru/api/v1",
    })

    assert status["configured"] is True
    assert status["read_only"] is True
    assert "operator" not in str(status)
    assert "top-secret" not in str(status)


def test_etm_client_reuses_session_and_builds_provenance_quotes():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/user/login"):
            return httpx.Response(
                200,
                json={"status": {"code": 200}, "data": {"session": "secret-session"}},
            )
        assert request.url.params["session-id"] == "secret-session"
        return httpx.Response(200, json={
            "status": {"code": 200},
            "data": {"rows": [
                {"gdscode": 9536092, "price": 100, "pricewnds": 122},
                {
                    "gdscode": 1037375,
                    "price": 0,
                    "pricewnds": 0,
                    "price_tarif": 0,
                    "price_retail": 0,
                },
            ]},
        })

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://itest2.etm.ru/api/v1",
    )
    client = EtmPriceClient(
        EtmConfig(
            "operator",
            "top-secret",
            "https://itest2.etm.ru/api/v1",
            vat_pct=22,
        ),
        http_client=http,
        price_interval_sec=0,
    )

    result = client.collect_quotes([
        {"code": "9536092", "material": "Кнопочный пост", "unit": "шт"},
        {"code": "1037375", "material": "Кабель", "unit": "м"},
    ])
    client.lookup_prices(["9536092"])

    assert result["found"] == 1
    assert result["rows"][1]["reason"] == "individual_quote_required"
    assert result["quotes"][0]["price"] == 122
    assert result["quotes"][0]["price_includes_vat"] is True
    assert result["quotes"][0]["source_kind"] == "supplier_api"
    assert "session" not in result["quotes"][0]["source"]
    assert sum(request.url.path.endswith("/user/login") for request in calls) == 1


def test_etm_client_chunks_requests_at_fifty_codes():
    price_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/user/login"):
            return httpx.Response(
                200,
                json={"status": {"code": 200}, "data": {"session": "s"}},
            )
        price_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={"status": {"code": 200}, "data": {"rows": []}},
        )

    client = EtmPriceClient(
        EtmConfig("operator", "password", "https://itest2.etm.ru/api/v1"),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://itest2.etm.ru/api/v1",
        ),
        price_interval_sec=0,
    )
    client.lookup_prices([str(index) for index in range(51)])

    assert len(price_paths) == 2
