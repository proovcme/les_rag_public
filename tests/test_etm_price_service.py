import httpx

from proxy.services.etm_price_service import (
    EtmConfig,
    EtmPriceClient,
    EtmPriceError,
    build_kac_map_from_quotes,
    configuration_status,
    enrich_requirements_kac_map,
    fetch_kac_map_for_materials,
)


def test_configuration_status_never_exposes_credentials():
    status = configuration_status({
        "LES_ETM_LOGIN": "operator",
        "LES_ETM_PASSWORD": "top-secret",
        "LES_ETM_BASE_URL": "https://itest2.etm.ru/api/v1",
    })

    assert status["configured"] is True
    assert status["read_only"] is True
    assert status["capabilities"]["goods_browse"] is True
    assert status["capabilities"]["orders"] is False
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


def test_etm_browse_goods_returns_candidates_only():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/user/login"):
            return httpx.Response(
                200,
                json={"status": {"code": 200}, "data": {"session": "s"}},
            )
        assert "/api/v2/goods/9536092" in str(request.url)
        assert request.url.params["type"] == "etm"
        return httpx.Response(200, json={
            "status": {"code": 200},
            "data": {
                "rows": [{
                    "code": "ETM9536092",
                    "gdscode": 9536092,
                    "name": "Пост кнопочный",
                    "art": "ET054487",
                    "mnf_name": "Электротехник",
                    "edizm": "шт",
                }],
                "result_text": "Результаты поиска по коду ЭТМ/артикулу:",
            },
        })

    client = EtmPriceClient(
        EtmConfig("operator", "password", "https://itest2.etm.ru/api/v1"),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://itest2.etm.ru/api/v1",
        ),
        price_interval_sec=0,
    )
    result = client.browse_goods("9536092")

    assert result["schema"] == "etm_goods_browse_v1"
    assert result["selection_owner"] == "model_or_user"
    assert result["count"] == 1
    assert result["candidates"][0]["gdscode"] == "9536092"
    assert result["candidates"][0]["art"] == "ET054487"


def test_build_kac_map_from_quotes_uses_net_price_and_skips_zero():
    quotes = {
        "quotes": [{
            "material": "Кнопочный пост",
            "product_code": "9536092",
            "price": 122.0,
            "price_includes_vat": True,
            "vat_pct": 22.0,
        }],
        "rows": [{"found": False, "reason": "individual_quote_required"}],
    }
    kac_map = build_kac_map_from_quotes(
        quotes,
        resource_codes={"9536092": "01.7.15.01-0011"},
    )
    assert kac_map["01.7.15.01-0011"] == round(122.0 / 1.22, 6)
    assert kac_map["Кнопочный пост"] == round(122.0 / 1.22, 6)
    assert kac_map["кнопочный пост"] == round(122.0 / 1.22, 6)


def test_fetch_kac_map_for_materials_wires_quotes_without_pricing_misses():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/user/login"):
            return httpx.Response(
                200,
                json={"status": {"code": 200}, "data": {"session": "s"}},
            )
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

    client = EtmPriceClient(
        EtmConfig("operator", "password", "https://itest2.etm.ru/api/v1", vat_pct=22),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://itest2.etm.ru/api/v1",
        ),
        price_interval_sec=0,
    )
    result = fetch_kac_map_for_materials(
        [
            {
                "code": "9536092",
                "material": "Кнопочный пост",
                "unit": "шт",
                "resource_code": "01.7.15.01-0011",
            },
            {
                "code": "1037375",
                "material": "Кабель",
                "unit": "м",
                "resource_code": "missing-code",
            },
        ],
        client=client,
    )

    assert result["applied"] == 1
    assert result["missing"] == 1
    assert "01.7.15.01-0011" in result["kac_map"]
    assert "missing-code" not in result["kac_map"]
    assert result["kac_map"]["01.7.15.01-0011"] == round(122.0 / 1.22, 6)


def test_enrich_requirements_fail_closed_without_credentials(monkeypatch):
    monkeypatch.delenv("LES_ETM_LOGIN", raising=False)
    monkeypatch.delenv("LES_ETM_PASSWORD", raising=False)

    result = enrich_requirements_kac_map([
        {
            "kind": "kac",
            "status": "open",
            "resource_code": "01.7.15.01-0011",
            "material": "Кнопочный пост",
            "unit": "шт",
            "resolution": {"etm_code": "9536092"},
        }
    ])

    assert result["configured"] is False
    assert result["kac_map"] == {}
    assert result["reason"] == "etm_not_configured"


def test_etm_client_authenticate_returns_bool_without_session():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": {"code": 200}, "data": {"session": "secret-session"}},
        )

    client = EtmPriceClient(
        EtmConfig("operator", "password", "https://itest2.etm.ru/api/v1"),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://itest2.etm.ru/api/v1",
        ),
        price_interval_sec=0,
    )

    assert client.authenticate() is True
    assert client._session == "secret-session"


def test_etm_login_http_403_json_surfaces_safe_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "status": {
                    "code": 403,
                    "message": "Неверный логин или пароль! operator",
                },
                "data": {"session": ""},
            },
        )

    client = EtmPriceClient(
        EtmConfig("operator", "password", "https://itest2.etm.ru/api/v1"),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://itest2.etm.ru/api/v1",
        ),
        price_interval_sec=0,
    )

    try:
        client.authenticate()
    except EtmPriceError as error:
        text = str(error)
    else:
        raise AssertionError("expected authentication failure")

    assert "Неверный логин или пароль" in text
    assert "operator" not in text
    assert "password" not in text
