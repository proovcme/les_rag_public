from proxy.services.kac_web_service import collect_quotes, strong_identifiers


def _result(domain: str, title: str, snippet: str) -> str:
    return (
        '<div class="result">'
        f'<a class="result__a" href="https://{domain}/product">{title}</a>'
        f'<a class="result__snippet">{snippet}</a>'
        "</div>"
    )


def test_kac_web_requires_strong_product_identifier():
    result = collect_quotes(
        "кабель огнестойкий",
        material="Кабель",
        unit="м",
        html_text="",
    )
    assert result["status"] == "identifier_required"
    assert result["quotes"] == []


def test_kac_web_accepts_three_distinct_exact_suppliers_and_normalizes_vat():
    html = "".join([
        _result("one.example", "DKC 91920", "Цена 122,00 руб/шт"),
        _result("two.example", "Купить DKC-91920", "100 руб. за шт"),
        _result("three.example", "Артикул DKC 91920", "110 ₽/шт"),
        _result("noise.example", "DKC 99999", "1 руб/шт"),
    ])
    result = collect_quotes(
        "DKC 91920",
        material="Изделие DKC 91920",
        unit="шт",
        vat_pct=22,
        html_text=html,
    )

    assert result["status"] == "sufficient"
    assert len(result["quotes"]) == 3
    material = result["kac"]["materials"][0]
    assert material["sufficient"] is True
    assert round(material["chosen_price"], 2) == 81.97
    assert "91920" in strong_identifiers("DKC 91920")
