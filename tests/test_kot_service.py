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
    assert analyze_question("Найди требования СП 60.13330").dataset_filter == "NTD_HVAC"
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


def test_kot_layout_and_typo_preprocessing():
    from proxy.services.kot_service import transform_query

    # 1. Keyboard Layout corrections
    assert transform_query("cj 60") == "сп 60"
    assert transform_query("ujcn 12.1.019") == "гост 12.1.019"
    assert transform_query("требования jdb") == "требования ов"
    assert transform_query("проектирование dr") == "проектирование вк"
    assert transform_query("монтаж \'jv") == "монтаж эом"
    assert transform_query("расчет rj") == "расчет кж"
    assert transform_query("система feu") == "система аупт"
    assert transform_query("динамики cnye") == "динамики соуэ"
    assert transform_query("правила gmt") == "правила пуэ"

    # 2. Typo Corrections (Cyrillic words >= 4 chars, distance <= 2)
    assert transform_query("пожарнй") == "пожарный"
    assert transform_query("вентиляцыя") == "вентиляция"
    assert transform_query("эвакуацы") == "эвакуация"
    assert transform_query("армировани") == "армирование"
    assert transform_query("электроосвещен") == "электроосвещение"
    assert transform_query("отоплене") == "отопление"
    assert transform_query("кондицеонирование") == "кондиционирование"
    assert transform_query("воздухообменн") == "воздухообмен"
    assert transform_query("нагрузк") == "нагрузка"
    assert transform_query("фундаминт") == "фундамент"
    assert transform_query("оснавание") == "основание"
    assert transform_query("железобитон") == "железобетон"
    assert transform_query("перекрыте") == "перекрытие"

    # 3. Preserves English terms
    assert transform_query("модели BIM") == "модели BIM"
    assert transform_query("отправь email") == "отправь email"
    assert transform_query("папка Dropbox") == "папка Dropbox"
    assert transform_query("проектирование HVAC") == "проектирование HVAC"

    # 4. Mixed integration queries
    assert analyze_question("Какие требования по cj 60.13330?").dataset_filter == "NTD_HVAC"
    assert analyze_question("Какие требования по \'jv?").dataset_filter == "NTD_ELECTRICAL"
    assert "пожар" in analyze_question("пожарнй вентиляцыя").matched_terms



# ── W2.7: словарная ступень — префиксное сопоставление словоформ ──

def test_expand_synonyms_matches_word_forms():
    from proxy.services.kot_service import expand_query_synonyms

    expanded = expand_query_synonyms("Требования к дымоудалению в коридорах")
    assert "противодымная" in expanded


def test_expand_synonyms_no_false_expansion():
    from proxy.services.kot_service import expand_query_synonyms

    q = "Сколько стоит молоко"
    assert expand_query_synonyms(q) == q
