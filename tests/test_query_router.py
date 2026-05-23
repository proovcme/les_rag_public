from proxy.services.query_router import route_query
from proxy.services.retrieval_service import classify_query, infer_dataset_filter


def test_table_quantity_question_routes_to_table_channel():
    intent = route_query("Сколько кабеля в проекте?")

    assert intent.channel == "table"
    assert intent.dataset_filter == "TABLE"
    assert intent.reason == "table_aggregate_context"
    assert infer_dataset_filter("Сколько кабеля в проекте?") == "TABLE"


def test_normative_cable_question_routes_to_rag_electrical():
    intent = route_query("Какие требования к кабелю по НТД?")
    route = classify_query("Какие требования к кабелю по НТД?")

    assert intent.channel == "rag"
    assert intent.reason == "normative_question"
    assert route.dataset_filter == "NTD_ELECTRICAL"
    assert route.reason == "electrical_keyword"


def test_table_document_keywords_route_to_table():
    intent = route_query("Покажи позиции из спецификации по светильникам")

    assert intent.channel == "table"
    assert intent.dataset_filter == "TABLE"


def test_explicit_filters_override_heuristics():
    table_intent = route_query("Какие требования к кабелю?", dataset_filter="TABLE_SMETA")
    rag_intent = route_query("Сколько кабеля в проекте?", dataset_filter="NTD_ELECTRICAL")

    assert table_intent.channel == "table"
    assert table_intent.dataset_filter == "TABLE_SMETA"
    assert rag_intent.channel == "rag"
    assert rag_intent.dataset_filter == "NTD_ELECTRICAL"


def test_explicit_dataset_ids_keep_rag_path():
    intent = route_query("Сколько кабеля в проекте?", dataset_ids=["ds-1"])

    assert intent.channel == "rag"
    assert intent.reason == "explicit_dataset_ids"
