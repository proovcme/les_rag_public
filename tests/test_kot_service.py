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
