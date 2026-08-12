import hashlib
import json
import sqlite3
from pathlib import Path


def _base(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE norms(
            norm_key TEXT PRIMARY KEY, norm_id TEXT, edition TEXT, display_code TEXT,
            base_type TEXT, bare_code TEXT, norm_name TEXT, norm_unit TEXT,
            work_steps TEXT, source_doc TEXT, source_guid TEXT, resource_count INTEGER,
            resource_kinds TEXT
        );
        CREATE TABLE resources(
            parent_norm_id TEXT, norm_key TEXT, kind TEXT, resource_code TEXT,
            resource_name TEXT, resource_unit TEXT
        );
        CREATE VIRTUAL TABLE norms_fts USING fts5(
            norm_key UNINDEXED, norm_name, work_steps, tokenize='unicode61'
        );
        """
    )
    return conn


def test_sparse_only_manifest_is_explicit_not_hybrid(tmp_path):
    from proxy.smeta_core.norm_browser import _rag_index_mode

    base = tmp_path / "base.sqlite"
    base.write_bytes(b"base")
    base.with_name("les_smeta_norm_rag_manifest.json").write_text(
        json.dumps({"index_mode": "sparse_only"}), encoding="utf-8"
    )

    assert _rag_index_mode(Path(base)) == "sparse_only"


def test_query_variants_translate_user_terms_to_normative_vocabulary():
    from proxy.smeta_core.norm_browser import _query_variants

    assert _query_variants("Монтаж БАП светильника") == [
        "отдельно устанавливаемый преобразователь или блок питания",
        "Монтаж БАП светильника",
    ]
    assert "монтаж кросса кроссировка линий панель коммутации" in _query_variants(
        "Монтаж патч-панели на 24 порта"
    )
    assert "шкаф коммутационный оборудование связи" in _query_variants(
        "Монтаж телекоммуникационного шкафа 42U"
    )
    assert _query_variants(
        "Монтаж телекоммуникационного шкафа СКС",
        stage="collection",
    ) == [
        "шкаф коммутационный оборудование связи",
        "Монтаж телекоммуникационного шкафа СКС",
    ]


def test_unrelated_query_is_not_expanded():
    from proxy.smeta_core.norm_browser import _query_variants

    assert _query_variants("Кладка кирпичной стены") == ["Кладка кирпичной стены"]


def test_collection_catalog_fuses_official_lexical_signal_with_rerank(
    monkeypatch,
):
    from proxy.smeta_core import norm_browser

    items = [
        {
            "key": code,
            "title": title,
            "purpose": f"Официальный сборник ГЭСНм {code}: {title}",
            "typical_scope": [title],
        }
        for code, title in [
            ("10", "Оборудование связи"),
            (
                "32",
                "Оборудование предприятий электронной промышленности "
                "и промышленности средств связи",
            ),
            ("40", "Дополнительное перемещение оборудования и материальных ресурсов"),
            ("37", "Оборудование общего назначения"),
            ("08", "Электротехнические установки"),
            ("36", "Оборудование предприятий бытового обслуживания"),
        ]
    ]
    monkeypatch.setattr(
        norm_browser,
        "browse_norm_catalog",
        lambda **_kwargs: {
            "items": items,
            "source_integrity": {"ok": True},
        },
    )
    wrong_order = ["40", "37", "32", "08", "36", "10"]

    def rerank(_query, cards, **_kwargs):
        by_code = {card["collection"]: card for card in cards}
        return [by_code[code] for code in wrong_order], True, "ok"

    monkeypatch.setattr(norm_browser, "_rerank_cards", rerank)
    monkeypatch.setattr(
        norm_browser,
        "_collections_from_family_norm_hits",
        lambda *_args, **_kwargs: [],
    )

    result = norm_browser.rank_norm_catalog_collections(
        "монтаж телекоммуникационного шкафа 42U",
        family="ГЭСНм",
        limit=6,
    )

    assert result["cards"][0]["collection"] == "10"
    assert result["cards"][0]["catalog_compass_rank"] == 1
    assert result["retrieval_trace"]["fusion"] == (
        "official_lexical_head_coverage_then_rerank"
    )
    assert "official_catalog_lexical" in result["retrieval_trace"]["signals"]
    assert "rerank" in result["retrieval_trace"]["signals"]


def test_variant_coverage_merge_keeps_each_variant_head_visible():
    from proxy.smeta_core.norm_browser import _coverage_merge

    first = [{"norm_key": f"a:{index}"} for index in range(5)]
    second = [{"norm_key": f"b:{index}"} for index in range(5)]

    assert [item["norm_key"] for item in _coverage_merge(first, second, limit=4)] == [
        "a:0", "b:0", "a:1", "b:1",
    ]


def _insert_norm(conn, *, key="ГЭСНм:08-02-001-01", name="Прокладывание кабелей", steps=None):
    steps = steps or ["Разметка трассы", "Прокладывание кабеля"]
    base_type, bare_code = key.split(":", 1)
    norm_id = "n1" if key == "ГЭСНм:08-02-001-01" else "n-" + key
    conn.execute(
        "INSERT INTO norms VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (key, norm_id, "FSNB-2022", key.replace(":", ""), base_type, bare_code,
         name, "100 м", json.dumps(steps, ensure_ascii=False), "source.xml", "guid-1", 0, "[]"),
    )
    conn.execute(
        "INSERT INTO norms_fts VALUES(?,?,?)",
        (key, name, json.dumps(steps, ensure_ascii=False)),
    )


def test_typed_fts_uses_russian_prefix_fallback(tmp_path):
    from proxy.smeta_core.norm_browser import _typed_cards

    path = tmp_path / "base.sqlite"
    conn = _base(path)
    _insert_norm(conn)
    conn.commit()
    conn.close()

    cards = _typed_cards("прокладка кабеля", limit=5, base_path=path)

    assert cards
    assert cards[0]["title"] == "Прокладывание кабелей"


def test_typed_search_can_be_filtered_by_model_selected_family_and_collection(tmp_path):
    from proxy.smeta_core.norm_browser import _typed_cards

    path = tmp_path / "base.sqlite"
    conn = _base(path)
    _insert_norm(conn, key="ГЭСНм:08-02-001-01", name="Прокладывание кабеля внутри здания")
    _insert_norm(conn, key="ГЭСНм:17-02-001-01", name="Прокладывание кабеля специальной установки")
    conn.commit()
    conn.close()

    cards = _typed_cards(
        "прокладывание кабеля",
        limit=10,
        base_path=path,
        base_types=("ГЭСНм",),
        collections=("08",),
    )

    assert [item["norm_code"] for item in cards] == ["ГЭСНм08-02-001-01"]


def test_catalog_family_passports_distinguish_construction_from_equipment_installation(
    tmp_path,
):
    from proxy.smeta_core.norm_browser import browse_norm_catalog

    path = tmp_path / "base.sqlite"
    conn = _base(path)
    _insert_norm(
        conn,
        key="ГЭСН:34-01-001-01",
        name="Устройство опор",
    )
    _insert_norm(
        conn,
        key="ГЭСНм:10-01-001-01",
        name="Монтаж оборудования связи",
    )
    conn.commit()
    conn.close()

    result = browse_norm_catalog(base_path=path)
    by_family = {item["key"]: item for item in result["items"]}

    assert "строительные работы" in by_family["ГЭСН"]["official_name"].casefold()
    assert "монтаж оборудования" in by_family["ГЭСНм"]["official_name"].casefold()
    assert "монтаж оборудования" in by_family["ГЭСНм"]["purpose"].casefold()
    assert "пусконаладочные работы" in by_family["ГЭСН"]["not_for"]
    assert by_family["ГЭСН"]["questions_to_ask"]
    assert by_family["ГЭСНм"]["source_ref"].startswith("ФСНБ-2022")
    assert by_family["ГЭСНм"]["node_id"] == "catalog:family:ГЭСНм"
    assert by_family["ГЭСНм"]["parent_id"] == "catalog:root"
    assert by_family["ГЭСНм"]["node_type"] == "family"
    assert by_family["ГЭСНм"]["approval_basis"].endswith("№ 1046/пр")
    assert by_family["ГЭСНм"]["navigation_url"] == "https://fsnb2022.ru/gesnm/"


def test_catalog_collection_has_compact_human_title_from_typed_source(tmp_path):
    from proxy.smeta_core.norm_browser import browse_norm_catalog

    path = tmp_path / "base.sqlite"
    conn = _base(path)
    _insert_norm(
        conn,
        key="ГЭСНм:10-01-001-01",
        name="Монтаж оборудования связи",
    )
    conn.execute(
        """
        UPDATE norms
        SET source_doc=?
        WHERE norm_key='ГЭСНм:10-01-001-01'
        """,
        (
            "Государственные элементные сметные нормы на монтаж оборудования<br/>"
            "Сборник 10. Оборудование связи<br/>"
            "Отдел 1. Городская телефонная связь",
        ),
    )
    conn.commit()
    conn.close()

    result = browse_norm_catalog(
        family="ГЭСНм",
        base_path=path,
    )

    assert result["level"] == "collection"
    assert result["items"][0]["title"] == "Оборудование связи"
    assert result["items"][0]["purpose"] == (
        "Официальный сборник ГЭСНм 10: Оборудование связи"
    )
    assert result["items"][0]["source_ref"] == (
        "ФСНБ-2022 · ГЭСНм, сборник 10 «Оборудование связи»"
    )
    assert result["items"][0]["node_id"] == "catalog:collection:ГЭСНм:10"
    assert result["items"][0]["parent_id"] == "catalog:family:ГЭСНм"

    scoped = browse_norm_catalog(
        family="ГЭСНм",
        collection="10",
        base_path=path,
    )
    assert scoped["level"] == "section"
    assert scoped["items"][0]["key"] == "10-01"
    assert scoped["items"][0]["official_heading"] == (
        "Отдел 1. Городская телефонная связь"
    )
    assert scoped["items"][0]["node_id"] == "catalog:section:ГЭСНм:10-01"
    assert scoped["items"][0]["parent_id"] == (
        "catalog:collection:ГЭСНм:10"
    )
    passport = scoped["collection_passport"]
    assert passport["schema"] == "smeta_norm_collection_passport_v1"
    assert passport["title"] == "Оборудование связи"
    assert passport["representative_sections"] == [
        "Отдел 1. Городская телефонная связь"
    ]
    assert passport["representative_units"] == ["100 м"]
    assert passport["passport_role"] == "navigation_only"
    assert passport["requires_full_norm_read"] is True


def test_catalog_table_identity_includes_family_and_collection(tmp_path):
    from proxy.smeta_core.norm_browser import browse_norm_catalog

    path = tmp_path / "base.sqlite"
    conn = _base(path)
    _insert_norm(
        conn,
        key="ГЭСН:08-02-001-01",
        name="Конструкция правильного сборника",
    )
    conn.commit()
    conn.close()

    wrong_collection = browse_norm_catalog(
        family="ГЭСН",
        collection="34",
        section="34-02",
        table="08-02-001",
        base_path=path,
    )
    correct_scope = browse_norm_catalog(
        family="ГЭСН",
        collection="08",
        section="08-02",
        table="08-02-001",
        base_path=path,
    )

    assert wrong_collection["items"] == []
    assert [item["norm_key"] for item in correct_scope["items"]] == [
        "ГЭСН:08-02-001-01"
    ]


def test_catalog_requires_section_between_collection_and_table(tmp_path):
    from proxy.smeta_core.norm_browser import browse_norm_catalog

    path = tmp_path / "base.sqlite"
    conn = _base(path)
    _insert_norm(
        conn,
        key="ГЭСНм:10-04-067-04",
        name="Шкаф коммутаторов",
    )
    conn.execute(
        "UPDATE norms SET source_doc=? WHERE norm_key='ГЭСНм:10-04-067-04'",
        (
            "Сборник 10. Оборудование связи<br/>"
            "Отдел 4. Радиосвязь и телевидение<br/>"
            "Раздел 8. Аппаратно-студийное оборудование<br/>"
            "Таблица ГЭСНм 10-04-067 Аппаратура цветного телевидения",
        ),
    )
    conn.commit()
    conn.close()

    sections = browse_norm_catalog(
        family="ГЭСНм",
        collection="10",
        base_path=path,
    )
    tables = browse_norm_catalog(
        family="ГЭСНм",
        collection="10",
        section="10-04",
        base_path=path,
    )
    norms = browse_norm_catalog(
        family="ГЭСНм",
        collection="10",
        section="10-04",
        table="10-04-067",
        base_path=path,
    )

    assert sections["level"] == "section"
    assert sections["items"][0]["key"] == "10-04"
    assert tables["level"] == "table"
    assert tables["items"][0]["key"] == "10-04-067"
    assert tables["items"][0]["hierarchy"] == [
        "Отдел 4. Радиосвязь и телевидение",
        "Раздел 8. Аппаратно-студийное оборудование",
    ]
    assert norms["level"] == "norm"
    assert norms["items"][0]["norm_key"] == "ГЭСНм:10-04-067-04"


def test_norm_card_exposes_resource_names_for_technology_audit(tmp_path):
    from proxy.smeta_core.norm_browser import _typed_cards

    path = tmp_path / "base.sqlite"
    conn = _base(path)
    _insert_norm(conn, name="Монтаж коробки")
    conn.execute(
        "INSERT INTO resources VALUES(?,?,?,?,?,?)",
        ("n1", "ГЭСНм:08-02-001-01", "machine", "91.01.01", "Кран башенный", "маш.-ч"),
    )
    conn.execute(
        "INSERT INTO resources VALUES(?,?,?,?,?,?)",
        ("n1", "ГЭСНм:08-02-001-01", "material", "01.01", "Электроды сварочные", "кг"),
    )
    conn.execute("UPDATE norms SET resource_count=2")
    conn.commit()
    conn.close()

    card = _typed_cards("монтаж коробки", limit=1, base_path=path)[0]

    assert card["resource_kinds"] == {"machine": 1, "material": 1}
    assert [item["name"] for item in card["resource_preview"]] == [
        "Кран башенный", "Электроды сварочные",
    ]


def test_browse_keeps_wide_pool_until_reranker(monkeypatch, tmp_path):
    from proxy.smeta_core import norm_browser

    lexical = [
        {"norm_key": f"l:{i}", "norm_code": f"L-{i}", "title": f"lex {i}"}
        for i in range(20)
    ]
    semantic = [
        {"norm_key": f"s:{i}", "norm_code": f"S-{i}", "title": f"sem {i}"}
        for i in range(20)
    ]
    seen = {}
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_args, **_kwargs: lexical)
    monkeypatch.setattr(
        norm_browser, "_rag_cards_many",
        lambda queries, **_kwargs: {query: semantic for query in queries},
    )

    def rerank(_query, cards, *, limit):
        seen["input"] = len(cards)
        return list(reversed(cards))[:limit], True, "ok"

    monkeypatch.setattr(norm_browser, "_rerank_cards", rerank)
    monkeypatch.setattr(
        norm_browser, "normative_base_integrity",
        lambda **_kwargs: {"status": "trusted", "trusted_for_pricing": True},
    )

    result = norm_browser.browse_norms("обычная работа", limit=5, base_path=tmp_path / "base.sqlite")

    assert seen["input"] == 24
    assert len(result["cards"]) == 5
    assert result["retrieval_trace"]["fusion_candidates"] == 24
    assert result["retrieval_trace"]["reranked"] is True


def test_mass_triage_runs_reranker_for_every_document_row(monkeypatch, tmp_path):
    from proxy.smeta_core import norm_browser

    queries = [f"query {index}" for index in range(5)]
    lexical = [{"norm_key": "l:1", "norm_code": "L-1", "title": "lex"}]
    semantic = [{"norm_key": "s:1", "norm_code": "S-1", "title": "sem"}]
    seen = []
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_args, **_kwargs: lexical)
    monkeypatch.setattr(
        norm_browser, "_rag_cards_many",
        lambda values, **_kwargs: {query: semantic for query in values},
    )
    monkeypatch.setattr(
        norm_browser, "_rerank_cards",
        lambda query, cards, **_kwargs: (seen.append(query) or cards, True, "ok"),
    )
    monkeypatch.setattr(
        norm_browser, "normative_base_integrity",
        lambda **_kwargs: {"status": "trusted", "trusted_for_pricing": True},
    )

    results = norm_browser.browse_norms_many(queries, limit=5, base_path=tmp_path / "base.sqlite")

    assert set(results) == set(queries)
    assert seen == queries
    assert all(item["retrieval_trace"]["reranked"] for item in results.values())
    assert all(item["retrieval_trace"]["rerank_status"] == "ok" for item in results.values())


def test_mass_triage_honors_explicit_rerank_request(monkeypatch, tmp_path):
    from proxy.smeta_core import norm_browser

    queries = [f"query {index}" for index in range(5)]
    lexical = [{"norm_key": "l:1", "norm_code": "L-1", "title": "lex"}]
    semantic = [{"norm_key": "s:1", "norm_code": "S-1", "title": "sem"}]
    seen = []
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_args, **_kwargs: lexical)
    monkeypatch.setattr(
        norm_browser, "_rag_cards_many",
        lambda values, **_kwargs: {query: semantic for query in values},
    )
    monkeypatch.setattr(
        norm_browser, "_rerank_cards",
        lambda query, cards, **_kwargs: (seen.append(query) or cards, True, "ok"),
    )
    monkeypatch.setattr(
        norm_browser, "normative_base_integrity",
        lambda **_kwargs: {"status": "trusted", "trusted_for_pricing": True},
    )

    results = norm_browser.browse_norms_many(
        queries, limit=5, base_path=tmp_path / "base.sqlite", rerank=True,
    )

    assert seen == queries
    assert all(item["retrieval_trace"]["reranked"] for item in results.values())


def test_rim_reranks_lexical_only_shortlist_without_hidden_query_expansion(
    monkeypatch,
    tmp_path,
):
    from proxy.smeta_core import norm_browser

    query = "шина заземления в шкафу"
    lexical = [
        {
            "norm_key": f"l:{index}",
            "norm_code": f"ГЭСНм10-01-00{index}-01",
            "title": f"lex {index}",
        }
        for index in range(6)
    ]
    seen = []
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_args, **_kwargs: lexical)
    monkeypatch.setattr(
        norm_browser,
        "_rag_cards_many",
        lambda values, **_kwargs: {value: [] for value in values},
    )
    monkeypatch.setattr(
        norm_browser,
        "_query_variants",
        lambda _query: (_ for _ in ()).throw(
            AssertionError("RIM query expansion must remain disabled")
        ),
    )
    monkeypatch.setattr(
        norm_browser,
        "_rerank_cards",
        lambda value, cards, **_kwargs: (
            seen.append((value, len(cards))) or cards,
            True,
            "ok",
        ),
    )
    monkeypatch.setattr(
        norm_browser,
        "normative_base_integrity",
        lambda **_kwargs: {"status": "trusted", "trusted_for_pricing": True},
    )

    result = norm_browser.browse_norms_many(
        [query],
        limit=5,
        base_path=tmp_path / "base.sqlite",
        rerank=True,
        expand_queries=False,
    )[query]

    assert seen == [(query, 6)]
    assert result["retrieval_trace"]["rerank_status"] == "ok"
    assert result["retrieval_trace"]["reranked"] is True
    assert result["retrieval_trace"]["query_variants"] == [query]
    assert result["retrieval_trace"]["query_expansion"] is False


def test_agent_can_explicitly_skip_reranker_for_narrow_search(monkeypatch, tmp_path):
    from proxy.smeta_core import norm_browser

    lexical = [{"norm_key": "l:1", "norm_code": "L-1", "title": "lex"}]
    semantic = [{"norm_key": "s:1", "norm_code": "S-1", "title": "sem"}]
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_args, **_kwargs: lexical)
    monkeypatch.setattr(
        norm_browser, "_rag_cards_many",
        lambda values, **_kwargs: {query: semantic for query in values},
    )
    monkeypatch.setattr(
        norm_browser, "_rerank_cards",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reranker requires explicit opt-in")),
    )
    monkeypatch.setattr(
        norm_browser, "normative_base_integrity",
        lambda **_kwargs: {"status": "trusted", "trusted_for_pricing": True},
    )

    result = norm_browser.browse_norms_many(
        ["спорная работа"], limit=5, base_path=tmp_path / "base.sqlite", rerank=False,
    )["спорная работа"]

    assert result["retrieval_trace"]["reranked"] is False
    assert result["retrieval_trace"]["rerank_deferred"] is True
    assert result["retrieval_trace"]["rerank_status"] == "disabled_by_caller"


def test_reranker_exception_returns_fallback_input_order(monkeypatch):
    from proxy.smeta_core import norm_browser

    cards = [{"norm_code": f"N-{i}", "title": str(i)} for i in range(6)]

    class BoomReranker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def rerank(self, *_args, **_kwargs):
            raise RuntimeError("sentence-transformers missing")

    monkeypatch.setattr(norm_browser, "select_reranker_cls", lambda: BoomReranker)

    ranked, used, status = norm_browser._rerank_cards("query", cards, limit=4)

    assert used is False
    assert status == "fallback_input_order"
    assert [item["norm_code"] for item in ranked] == ["N-0", "N-1", "N-2", "N-3"]


def test_reranker_partial_response_is_filled_from_fused_order(monkeypatch):
    from proxy.smeta_core import norm_browser

    cards = [{"norm_code": f"N-{i}", "title": str(i)} for i in range(6)]

    class Result:
        def __init__(self, index):
            self.metadata = {"index": index}

    class Reranker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def rerank(self, *_args, **_kwargs):
            return [Result(4), Result(4), Result(999)]

    monkeypatch.setattr(norm_browser, "select_reranker_cls", lambda: Reranker)

    ranked, used, status = norm_browser._rerank_cards("query", cards, limit=4)

    assert used is True
    assert status == "ok"
    assert [item["norm_code"] for item in ranked] == ["N-0", "N-1", "N-4", "N-2"]


def test_reranker_is_fused_with_original_rrf_instead_of_erasing_it(monkeypatch):
    from proxy.smeta_core import norm_browser

    cards = [
        {"norm_code": "GOOD-1", "title": "strong hybrid candidate"},
        {"norm_code": "GOOD-2", "title": "second hybrid candidate"},
        {"norm_code": "NOISE-1", "title": "weak candidate"},
        {"norm_code": "NOISE-2", "title": "weak candidate"},
        {"norm_code": "NOISE-3", "title": "weak candidate"},
    ]

    class Result:
        def __init__(self, index):
            self.metadata = {"index": index}

    class CatastrophicReranker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def rerank(self, *_args, **_kwargs):
            return [Result(4), Result(3), Result(2), Result(1), Result(0)]

    monkeypatch.setattr(norm_browser, "select_reranker_cls", lambda: CatastrophicReranker)

    ranked, used, status = norm_browser._rerank_cards("query", cards, limit=3)

    assert used is True
    assert status == "ok"
    assert {item["norm_code"] for item in ranked[:3]} & {"GOOD-1", "GOOD-2"}


def test_reranker_failure_is_visible_and_preserves_raw_order(monkeypatch):
    from proxy.smeta_core import norm_browser

    cards = [{"norm_code": f"N-{i}", "title": str(i)} for i in range(6)]

    class BrokenReranker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def rerank(self, *_args, **_kwargs):
            raise TimeoutError("offline")

    monkeypatch.setattr(norm_browser, "select_reranker_cls", lambda: BrokenReranker)

    ranked, used, status = norm_browser._rerank_cards("query", cards, limit=4)

    assert used is False
    assert status == "fallback_input_order"
    assert ranked == cards[:4]


def test_selected_official_table_returns_every_row_in_code_order(tmp_path, monkeypatch):
    from proxy.smeta_core import norm_browser

    path = tmp_path / "base.sqlite"
    conn = _base(path)
    _insert_norm(conn, key="ГЭСНм:08-02-001-03", name="Третий вариант")
    _insert_norm(conn, key="ГЭСНм:08-02-001-01", name="Первый вариант")
    _insert_norm(conn, key="ГЭСНм:08-02-001-02", name="Второй вариант")
    _insert_norm(conn, key="ГЭСНм:08-02-002-01", name="Другая таблица")
    _insert_norm(conn, key="ГЭСН:08-02-001-01", name="Другое семейство")
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        norm_browser,
        "normative_base_integrity",
        lambda **_kwargs: {"status": "trusted", "trusted_for_pricing": True},
    )

    result = norm_browser.browse_norms_many(
        ["выбранная моделью таблица"],
        limit=1,
        base_path=path,
        base_types=["ГЭСНм"],
        table_codes=["08-02-001"],
    )["выбранная моделью таблица"]

    assert result["backend"] == "official_table_listing"
    assert [card["norm_code"] for card in result["cards"]] == [
        "ГЭСНм08-02-001-01",
        "ГЭСНм08-02-001-02",
        "ГЭСНм08-02-001-03",
    ]
    assert result["retrieval_trace"]["complete_table"] is True
    assert result["retrieval_trace"]["rerank_status"] == "not_needed_table_listing"


def test_rrf_uses_typed_norm_identity_not_display_code():
    from proxy.smeta_core.norm_browser import _rrf_cards

    cards = _rrf_cards(
        [{"norm_key": "ГЭСН:01", "norm_code": "01", "title": "one"}],
        [{"norm_key": "ФЕР:01", "norm_code": "01", "title": "two"}],
        limit=5,
    )

    assert {item["norm_key"] for item in cards} == {"ГЭСН:01", "ФЕР:01"}


def test_rrf_equal_scores_have_stable_casefold_tie_break():
    from proxy.smeta_core.norm_browser import _rrf_cards

    first = {"norm_key": "а:01", "norm_code": "B"}
    second = {"norm_key": "А:01", "norm_code": "A"}
    expected = [item["norm_key"] for item in _rrf_cards([second], [first], limit=5)]
    actual = [item["norm_key"] for item in _rrf_cards([first], [second], limit=5)]
    assert actual == expected


def test_rag_manifest_rejects_embedding_or_base_mismatch(tmp_path):
    from proxy.smeta_core.norm_browser import _rag_manifest_status

    base = tmp_path / "base.sqlite"
    base.write_bytes(b"current-base")
    manifest = tmp_path / "les_smeta_norm_rag_manifest.json"
    manifest.write_text(json.dumps({
        "status": "passed",
        "collection": "norms",
        "embedding_model": "old-embedder",
        "base_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
    }), encoding="utf-8")

    assert _rag_manifest_status(
        base_path=base, collection="norms", embedding_model="new-embedder"
    ) == (False, "embedding_model_mismatch")

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["embedding_model"] = "new-embedder"
    payload["base_sha256"] = "stale"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert _rag_manifest_status(
        base_path=base, collection="norms", embedding_model="new-embedder"
    ) == (False, "base_revision_mismatch")


def test_smeta_dense_requires_same_or_explicitly_verified_embedding_space(tmp_path, monkeypatch):
    from proxy.smeta_core.norm_browser import _rag_dense_compatibility

    base = tmp_path / "base.sqlite"
    base.write_bytes(b"base")
    manifest = tmp_path / "les_smeta_norm_rag_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "embedding_backend": "sentence_transformers_mps",
                "embedding_space_verified": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EMBED_BACKEND", "coreml")
    monkeypatch.delenv("LES_SMETA_NORM_EMBED_BACKEND", raising=False)
    monkeypatch.delenv("LES_SMETA_EMBEDDING_SPACE_ID", raising=False)

    # The dedicated smeta generation is independent of the general RAG
    # backend. Its active manifest defines the expected query backend.
    assert _rag_dense_compatibility(base) == (True, "same_backend")

    monkeypatch.setenv("LES_SMETA_NORM_EMBED_BACKEND", "coreml")
    compatible, reason = _rag_dense_compatibility(base)
    assert compatible is False
    assert "embedding_backend_mismatch" in reason

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload.update(
        {
            "embedding_space_verified": True,
            "embedding_space_id": "qwen-space-v1",
        }
    )
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("LES_SMETA_EMBEDDING_SPACE_ID", "qwen-space-v1")

    assert _rag_dense_compatibility(base) == (True, "verified_embedding_space")


def test_smeta_dense_contract_uses_manifest_backend_when_general_rag_env_is_absent(
    tmp_path,
    monkeypatch,
):
    from proxy.smeta_core.norm_browser import _rag_dense_contract

    base = tmp_path / "base.sqlite"
    base.write_bytes(b"base")
    base.with_name("les_smeta_norm_rag_manifest.json").write_text(
        json.dumps({"embedding_backend": "coreml"}),
        encoding="utf-8",
    )
    monkeypatch.delenv("EMBED_BACKEND", raising=False)
    monkeypatch.delenv("LES_SMETA_NORM_EMBED_BACKEND", raising=False)

    assert _rag_dense_contract(base) == (
        True,
        "same_backend",
        "coreml",
        "coreml",
    )


def test_norm_rag_projection_does_not_embed_incidental_resources(tmp_path):
    from tools.build_smeta_norm_rag import _rows

    path = tmp_path / "base.sqlite"
    conn = _base(path)
    _insert_norm(conn, name="Установка небольшого устройства")
    conn.execute(
        "INSERT INTO resources VALUES(?,?,?,?,?,?)",
        ("n1", "ГЭСНм:08-02-001-01", "machine", "91.01", "Башенный кран", "маш.-ч"),
    )
    conn.commit()
    conn.close()

    row = _rows(path)[0]

    assert "Башенный кран" not in row["text"]
    assert "Башенный кран" in row["resource_text"]


def test_staged_smeta_manifest_does_not_replace_active_manifest(monkeypatch, tmp_path):
    from proxy.smeta_core.norm_browser import _rag_manifest_path

    base = tmp_path / "les_smeta_base.sqlite"
    active = tmp_path / "les_smeta_norm_rag_manifest.json"
    staged = tmp_path / "les_smeta_norm_cards_v4.manifest.json"
    active.write_text('{"collection":"active"}', encoding="utf-8")
    staged.write_text('{"collection":"staged"}', encoding="utf-8")
    monkeypatch.setenv("LES_SMETA_NORM_RAG_MANIFEST", str(staged))

    assert _rag_manifest_path(base) == staged
    assert json.loads(active.read_text(encoding="utf-8"))["collection"] == "active"


def test_collection_shortlist_keeps_cable_collection_when_norm_rerank_disabled(monkeypatch):
    """Miss@known guard: disabled CE must not return raw GESNr 51-56 head only."""
    from proxy.smeta_core import norm_browser

    items = [
        {
            "key": code,
            "title": title,
            "purpose": purpose,
            "source_example": example,
            "node_type": "collection",
            "cipher": code,
        }
        for code, title, purpose, example in [
            ("51", "Земляные работы", "земля", "котлован"),
            ("52", "Фундаменты", "фундамент", "бетон"),
            ("53", "Стены", "стены", "кирпич"),
            ("54", "Перекрытия", "перекрытия", "плиты"),
            ("55", "Перегородки", "перегородки", "гкл"),
            ("56", "Проемы", "проемы", "двери окна"),
            ("67", "Электромонтажные работы", "электромонтаж", "демонтаж кабеля"),
            ("69", "Прочие ремонтно-строительные работы", "прочие", "разное"),
        ]
    ]
    monkeypatch.setenv("LES_SMETA_NORM_RERANK", "false")
    monkeypatch.setattr(
        norm_browser,
        "browse_norm_catalog",
        lambda **_kwargs: {"items": items, "source_integrity": {"ok": True}},
    )
    monkeypatch.setattr(
        norm_browser,
        "_collections_from_family_norm_hits",
        lambda *_args, **_kwargs: ["67"],
    )

    result = norm_browser.rank_norm_catalog_collections(
        "демонтаж кабеля в гофре",
        family="ГЭСНр",
        limit=6,
    )
    collections = [card["collection"] for card in result["cards"]]
    assert "67" in collections
    assert result["retrieval_trace"]["rerank_status"] == "disabled"
    assert collections[0] == "67"
