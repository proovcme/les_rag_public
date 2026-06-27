"""W11.7 — мультикласс через диалог (ADR-12). Pure-детектор + чипы, без LLM."""

from __future__ import annotations

from proxy.services.class_router_service import build_class_suggestions, detect_classes


def _ids(hits):
    return [h.class_id for h in hits]


def test_monoclass_normative():
    hits = detect_classes("Какие требования СП 13130 к эвакуации?")
    assert hits[0].class_id == "normative"
    assert build_class_suggestions("Какие требования СП 13130 к эвакуации?") == []


def test_monoclass_mail():
    hits = detect_classes("Найди письмо от подрядчика про задержку")
    assert hits[0].class_id == "mail"


def test_multiclass_detects_both():
    q = "Сколько кабеля в смете и что требует ГОСТ по его прокладке?"
    ids = _ids(detect_classes(q))
    assert "table" in ids and "normative" in ids


def test_multiclass_suggestions_exclude_primary():
    q = "Сколько кабеля в смете и что требует ГОСТ по его прокладке?"
    hits = detect_classes(q)
    primary = hits[0].class_id
    sugg = build_class_suggestions(q)
    assert sugg, "мультикласс → должны быть чипы"
    assert all(s["class"] != primary for s in sugg)


def test_suggestion_payload_shape():
    q = "Письмо про смету и нормативные требования"
    sugg = build_class_suggestions(q)
    assert sugg
    s = sugg[0]
    assert set(s) == {"class", "label", "dataset_filter", "query"}
    assert s["query"] == q
    assert s["label"]  # есть человекочитаемый ярлык


def test_primary_filter_excluded_from_suggestions():
    # если уже выбран фильтр смет, чип «смета» не повторяем
    q = "Сколько кабеля в смете и что требует ГОСТ?"
    sugg = build_class_suggestions(q, primary_filter="TABLE_SMETA")
    assert all(s["dataset_filter"] != "TABLE_SMETA" for s in sugg)


def test_max_suggestions_respected():
    q = "Письмо про смету, нормативы ГОСТ и раздел проекта ЭОМ"
    sugg = build_class_suggestions(q, max_suggestions=2)
    assert len(sugg) <= 2


def test_no_duplicate_classes_in_suggestions():
    q = "смета смета ведомость расценка ГОСТ СП норматив"
    sugg = build_class_suggestions(q)
    classes = [s["class"] for s in sugg]
    assert len(classes) == len(set(classes))


def test_higher_score_ranks_first():
    # больше нормативных токенов, чем табличных → норматив верхний
    q = "ГОСТ СП СНиП норматив требования; и где-то смета"
    assert detect_classes(q)[0].class_id == "normative"


def test_uses_no_llm():
    import inspect

    import proxy.services.class_router_service as cr

    src = inspect.getsource(cr)
    for marker in ("import httpx", "import openai", "/api/chat", "completions"):
        assert marker not in src
