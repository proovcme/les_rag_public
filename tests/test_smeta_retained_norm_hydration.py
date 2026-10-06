"""Exact retained-ID expansion may add source evidence, never choose candidates."""
import copy
import hashlib
import json
import sqlite3

import pytest

from proxy.smeta_core import norm_browser


def _base(path, *, stored_count=19, consumption=True):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE norms (norm_key TEXT PRIMARY KEY, norm_id TEXT, edition TEXT,
                display_code TEXT, base_type TEXT, norm_name TEXT, norm_unit TEXT,
                work_steps TEXT, source_doc TEXT, source_guid TEXT, resource_count INTEGER);
            CREATE TABLE resources (id INTEGER PRIMARY KEY, parent_norm_id TEXT, kind TEXT,
                resource_code TEXT, resource_name TEXT, resource_unit TEXT, per_unit REAL,
                price REAL, source_doc TEXT, source_guid TEXT);
        """)
        conn.execute("INSERT INTO norms VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            "ГЭСНм:08-02-001-01", "norm-id", "ФСНБ fixture", "ГЭСНм08-02-001-01",
            "ГЭСНм", "Исходная работа", "100 м", '["Полный исходный шаг"]',
            "source.xml", "norm-guid", stored_count,
        ))
        conn.executemany("INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?,?)", [
            (i+1, "norm-id", "material", f"code-{i:02}", "" if i == 18 else f"Ресурс {i}",
             "кг", i/4 if consumption else None, None, "source.xml", f"resource-{i}")
            for i in range(19)
        ])
    preview = norm_browser.read_norm_card_exact(norm_key="ГЭСНм:08-02-001-01", base_path=path)["card"]
    for key in ("resources", "resources_returned", "resources_complete", "resource_consumption_known"):
        preview.pop(key)
    return preview, hashlib.sha256(path.read_bytes()).hexdigest()


def test_retained_cards_expand_every_resource_with_exact_rank_and_source_binding(tmp_path, monkeypatch):
    path = tmp_path / "База 'норм'.sqlite"
    preview, generation = _base(path)
    cards = [{**preview, "rank_marker": "first"}, {**preview, "rank_marker": "second"}]
    original = copy.deepcopy(cards)
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_a, **_k: pytest.fail("no extra search"))
    monkeypatch.setattr(norm_browser, "_rag_cards_many", lambda *_a, **_k: pytest.fail("no extra RAG"))
    connections = []
    connect = norm_browser._connect_base_readonly
    def tracked(source):
        conn = connect(source)
        commands = []
        conn.set_trace_callback(commands.append)
        connections.append(commands)
        return conn
    monkeypatch.setattr(norm_browser, "_connect_base_readonly", tracked)

    result = norm_browser.hydrate_retained_norm_cards(cards, base_path=path, expected_base_sha256=generation)

    assert result["status"] == "ok"
    assert cards == original
    assert len(connections) == 1
    assert any(command == "BEGIN" for command in connections[0])
    assert [card["rank_marker"] for card in result["cards"]] == ["first", "second"]
    for card in result["cards"]:
        assert card["resource_preview"] == preview["resource_preview"]
        assert card["work_steps"] == preview["work_steps"]
        assert card["resources_complete"] is True
        assert card["resources_returned"] == 19
        assert card["resources"][0]["per_unit"] == 0
        assert card["resources"][18]["name"] == ""
        assert card["resources"][18]["source_ref"] == "source.xml#guid=resource-18"
        assert card["normative_base_sha256"] == generation
        assert card["source_hash_basis"] == "normative_sqlite_base_bytes"
        assert "source_sha256" not in card
        assert card["hydration_origin"] == "application_typed_exact"
        assert card["hydration_status"] == "ok"


@pytest.mark.parametrize("field,value", [
    ("source_ref", "other.xml#guid=norm-guid"), ("edition", "other edition"),
    ("measure_unit", "м"), ("resource_count", 20), ("work_steps", ["Changed step"]),
    ("norm_id", "different-id"),
])
def test_changed_retained_identity_or_preview_is_not_replaced(tmp_path, field, value):
    path = tmp_path / "base.sqlite"
    preview, generation = _base(path)
    card = {**preview, field: value}

    result = norm_browser.hydrate_retained_norm_cards([card], base_path=path, expected_base_sha256=generation)

    assert result["status"] == "partial"
    returned = result["cards"][0]
    assert returned[field] == value
    assert returned["hydration_status"] == "conflict"
    assert "resources" not in returned
    assert returned["hydration_warnings"]


@pytest.mark.parametrize("stored_count,consumption", [(20, True), (19, False)])
def test_incomplete_source_resources_remain_full_literal_but_not_complete(tmp_path, stored_count, consumption):
    path = tmp_path / "base.sqlite"
    preview, generation = _base(path, stored_count=stored_count, consumption=consumption)
    result = norm_browser.hydrate_retained_norm_cards([preview], base_path=path, expected_base_sha256=generation)
    card = result["cards"][0]
    assert card["hydration_status"] == "ok"
    assert card["resources_returned"] == 19
    assert card["resources_complete"] is False
    assert card["hydration_warnings"]
    assert card["resource_count"] == stored_count


@pytest.mark.parametrize("generation", ["", "a" * 64])
def test_unbound_or_other_generation_keeps_original_candidates_visible(tmp_path, generation):
    path = tmp_path / "base.sqlite"
    preview, _ = _base(path)
    result = norm_browser.hydrate_retained_norm_cards([preview], base_path=path, expected_base_sha256=generation)
    assert result["status"] == "partial"
    assert result["cards"][0]["resource_preview"] == preview["resource_preview"]
    assert result["cards"][0]["hydration_status"] == "source_unverified"
    assert "resources" not in result["cards"][0]
    assert result["warnings"]
    assert "normative_base_sha256" not in result["cards"][0]
    if generation:
        assert result["cards"][0]["retained_normative_base_sha256"] == generation
    else:
        assert "retained_normative_base_sha256" not in result["cards"][0]


def test_changed_base_after_snapshot_discard_expansion_without_losing_preview(tmp_path, monkeypatch):
    path = tmp_path / "base.sqlite"
    preview, generation = _base(path)
    values = iter([generation, "b" * 64])
    monkeypatch.setattr(norm_browser, "_actual_base_sha256", lambda _path: next(values))
    result = norm_browser.hydrate_retained_norm_cards([preview], base_path=path, expected_base_sha256=generation)
    assert result["status"] == "partial"
    assert result["cards"][0]["resource_preview"] == preview["resource_preview"]
    assert result["cards"][0]["hydration_status"] == "source_changed"
    assert "resources" not in result["cards"][0]
    assert "normative_base_sha256" not in result["cards"][0]


def test_missing_exact_card_does_not_drop_other_retained_aliases(tmp_path):
    path = tmp_path / "base.sqlite"
    preview, generation = _base(path)
    missing = {**preview, "norm_key": "ГЭСНм:08-02-001-02", "norm_code": "ГЭСНм08-02-001-02"}
    result = norm_browser.hydrate_retained_norm_cards([missing, preview], base_path=path, expected_base_sha256=generation)
    assert len(result["cards"]) == 2
    assert result["cards"][0]["norm_key"] == missing["norm_key"]
    assert result["cards"][0]["hydration_status"] == "missing"
    assert "resources" not in result["cards"][0]
    assert result["cards"][1]["resources_complete"] is True


def test_bound_exact_read_verifies_newer_pointer_generation_before_rows(tmp_path, monkeypatch):
    path = tmp_path / "base.sqlite"
    preview, generation = _base(path)
    valid = norm_browser.read_norm_card_exact(norm_key=preview["norm_key"], base_path=path,
                                             expected_base_sha256=generation)
    assert valid["status"] == "ok"
    assert valid["card"]["normative_base_sha256"] == generation
    assert "source_sha256" not in valid["card"]
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE resources SET per_unit = 123 WHERE id = 1")
    monkeypatch.setattr(norm_browser, "_read_norm_card_connection", lambda *_a: pytest.fail("no unbound row read"))
    changed = norm_browser.read_norm_card_exact(norm_key=preview["norm_key"], base_path=path,
                                               expected_base_sha256=generation)
    assert changed["status"] == "conflict"
    assert changed["card"] is None


def test_bound_exact_read_does_not_deliver_rows_if_base_changes_after_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "base.sqlite"
    preview, generation = _base(path)
    values = iter([generation, "b" * 64])
    monkeypatch.setattr(norm_browser, "_actual_base_sha256", lambda _path: next(values))
    changed = norm_browser.read_norm_card_exact(norm_key=preview["norm_key"], base_path=path,
                                               expected_base_sha256=generation)
    assert changed["status"] == "conflict"
    assert changed["card"] is None
    assert changed["missing"] == ["normative base changed during exact card read"]


def _stub_browse(monkeypatch, preview, query):
    monkeypatch.setattr(norm_browser, "normative_base_integrity", lambda **_kw: {})
    ranked = [{**preview, "rank_marker": "not-retained"}, {**preview, "rank_marker": "retained"}]
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_a, **_k: ranked)
    def native(queries, **_kwargs):
        assert queries == [query]
        return {query: ranked}
    monkeypatch.setattr(norm_browser, "_rag_cards_many", native)
    monkeypatch.setattr(norm_browser, "_rrf_cards", lambda *_a, **_k: ranked)
    def rerank(actual_query, candidates, **_kwargs):
        assert actual_query == query
        assert candidates == ranked
        return [candidates[1]], True, "ok"
    monkeypatch.setattr(norm_browser, "_rerank_cards", rerank)


def test_hydration_runs_only_after_final_retained_rerank_without_query_changes(tmp_path, monkeypatch):
    path = tmp_path / "base.sqlite"
    preview, generation = _base(path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"status": "passed", "base_sha256": generation}), encoding="utf-8")
    monkeypatch.setattr(norm_browser, "_rag_manifest_path", lambda _path: manifest)
    query = "Запрос модели 'дословно'"
    _stub_browse(monkeypatch, preview, query)
    calls = []
    hydrate = norm_browser.hydrate_retained_norm_cards
    def retained(cards, **kwargs):
        calls.append([card["rank_marker"] for card in cards])
        return hydrate(cards, **kwargs)
    monkeypatch.setattr(norm_browser, "hydrate_retained_norm_cards", retained)
    result = norm_browser.browse_norms_many([query], base_path=path, limit=1,
                                          rerank=True, expand_queries=False, hydrate_resources=True)[query]
    assert calls == [["retained"]]
    assert result["query"] == query
    assert result["selected_code"] == ""
    assert result["selection_owner"] == "model_or_user"
    assert result["cards"][0]["rank_marker"] == "retained"
    assert result["cards"][0]["resources_returned"] == 19
    assert result["retrieval_trace"]["returned_candidates"] == 1
    assert result["retrieval_trace"]["query_variants"] == [query]


def test_changed_generation_manifest_preserves_original_retained_preview(tmp_path, monkeypatch):
    path = tmp_path / "base.sqlite"
    preview, generation = _base(path)
    query = "Literal model query"
    _stub_browse(monkeypatch, preview, query)
    versions = iter([generation, "c" * 64])
    monkeypatch.setattr(norm_browser, "_retained_rag_generation", lambda _path: next(versions))
    result = norm_browser.browse_norms_many([query], base_path=path, limit=1,
                                          rerank=True, expand_queries=False, hydrate_resources=True)[query]
    assert result["cards"][0]["rank_marker"] == "retained"
    assert result["cards"][0]["resource_preview"] == preview["resource_preview"]
    assert "resources" not in result["cards"][0]
    assert result["cards"][0]["hydration_status"] == "source_changed"
    assert result["retrieval_trace"]["retained_card_hydration"]["status"] == "partial"
