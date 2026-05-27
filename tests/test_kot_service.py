from proxy.services.kot_service import analyze_question, extract_norm_refs


def test_kot_routes_fire_domain():
    decision = analyze_question("Каким нормативом регулируется пожарная сигнализация СПС?")

    assert decision.dataset_filter == "NTD_FIRE"
    assert decision.confidence >= 0.62
    assert "пожар" in decision.matched_terms


def test_kot_routes_gkrf_domain():
    decision = analyze_question("Какие разделы проектной документации по постановлению 87?")

    assert decision.dataset_filter == "GKRF"
    assert decision.reason == "kot_gkrf"


def test_kot_extracts_exact_norm_refs():
    refs = extract_norm_refs("Проверь по СП 1.13130 и ГОСТ Р 59638-2021")

    assert "сп 1.13130" in refs
    assert "гост р 59638-2021" in refs


def test_kot_routes_engineering_abbreviations():
    assert analyze_question("Какие требования по ЭОМ?").dataset_filter == "NTD_ELECTRICAL"
    assert analyze_question("Нормы по ОВ для вентиляции").dataset_filter == "NTD_HVAC"
    assert analyze_question("Что проверить по ВК и канализации?").dataset_filter == "NTD_WATER"
    assert analyze_question("Армирование плиты КЖ").dataset_filter == "NTD_STRUCTURAL"


def test_kot_routes_mail_queries():
    decision = analyze_question("Найди письма про Dropbox")

    assert decision.dataset_filter == "MAIL"
    assert decision.confidence >= 0.62


def test_kot_short_terms_do_not_match_inside_words():
    decision = analyze_question("посчитай общую стоимость по всем строкам сметы")

    assert decision.ambiguous is False
    assert decision.matched_domains[0].dataset_filter == "TABLE"
    assert "мост" not in decision.matched_terms
    assert "пос" not in decision.matched_terms
