"""SQLite-light norm store for model-first smeta candidate search."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from proxy.services.smeta_norm_store import get_smeta_norm_store, norm_store_payload


def test_smeta_norm_store_builds_typed_sqlite_projection():
    store = get_smeta_norm_store()
    payload = store.payload()

    assert payload["schema"] == "smeta_norm_store_v5"
    assert payload["backend"] == "sqlite_light"
    assert payload["norm_count"] > 0
    assert "ГЭСН" in payload["by_base_type"]
    assert payload["collections"] > 0
    assert set(payload["profile_fields"]) >= {
        "family_hints", "element_hints", "resource_kinds", "condition_hints", "provenance", "model_card",
        "navigation", "applicability", "price_inputs", "decision_order",
    }


def test_smeta_norm_store_searches_by_work_terms():
    store = get_smeta_norm_store()
    rows = store.search_rows(["кровля", "устройство"])

    assert rows
    assert any("кров" in row.title or row.collection == "12" for row in rows)
    assert all(row.code for row in rows)
    assert all(row.measure_unit is not None for row in rows)


def test_norm_store_payload_is_lightweight_operator_trace():
    payload = norm_store_payload()

    assert set(payload) >= {"schema", "backend", "norm_count", "fts", "by_base_type", "collections", "profile_fields"}
    assert "rows" not in payload


def test_smeta_norm_store_profile_exposes_applicability_and_resources():
    store = get_smeta_norm_store()
    row = store.by_code("ГЭСН:01-02-056-01")

    assert row is not None
    profile = row.profile()
    assert profile["family_hints"] == ["earthworks"]
    assert "excavation" in profile["element_hints"]
    assert "разработка" in profile["action_hints"]
    assert set(profile["condition_hints"]) >= {"группа грунта", "глубина", "крепления"}
    assert profile["resource_count"] > 0
    assert profile["provenance"]
    assert profile["model_card"]["measure"] == "измеритель нормы: 100 м3; базовая единица: м3"
    assert "земляные работы" in profile["model_card"]["domain"]["families"]
    assert profile["model_card"]["applicability"]["unit"] == "м3"
    assert "материал без цены" in profile["model_card"]["price_inputs"]["material_gap"]
    assert "это навигационная карточка нормы, не расчёт стоимости" in profile["model_card"]["warnings"]
    assert profile["navigation"]["collection"]["label"].startswith("ГЭСН 01")
    assert "уточнить группу грунта" in profile["navigation"]["questions_to_ask"]
    assert profile["navigation"]["decision_order"]


def test_smeta_norm_store_metal_mounting_profile_keeps_gesnm_base():
    profile = get_smeta_norm_store().norm_profile("ГЭСНм:38-01-001-01")

    assert profile["base_type"] == "ГЭСНм"
    assert profile["collection_key"] == "ГЭСНм38"
    assert "metal" in profile["family_hints"]
    assert "metal_assembly" in profile["element_hints"]
    assert set(profile["resource_kinds"]) >= {"labor", "machine", "material"}
    assert "масса элемента" in profile["condition_hints"]
    assert "машины и механизмы" in profile["model_card"]["resources"]["kinds"]


def test_smeta_norm_store_prioritizes_gesnm10_optical_candidates():
    rows = get_smeta_norm_store().search_rows(["сварка", "волокон", "оптического"], limit=5)

    assert rows
    assert rows[0].code == "ГЭСНм:10-06-058-01"
    assert rows[0].base_type == "ГЭСНм"


def test_smeta_norm_store_cached_connection_can_be_read_from_worker_thread():
    store = get_smeta_norm_store()
    assert store.search_rows(["траншеи", "грунта"])

    with ThreadPoolExecutor(max_workers=1) as pool:
        rows = pool.submit(lambda: store.search_rows(["траншеи", "грунта"])).result(timeout=5)

    assert rows
    assert any("транше" in row.title for row in rows)


def test_smeta_norm_store_navigation_exposes_nearby_norms():
    store = get_smeta_norm_store()
    row = store.by_code("ГЭСН:01-02-056-01")
    assert row is not None

    navigation = store.navigation_for(row, family_hint="earthworks", element_hint="excavation")

    assert navigation["collection"]["key"] == "01"
    assert navigation["nearby_norms"]
    assert all(item["code"] != row.code for item in navigation["nearby_norms"])
    assert "соседними нормами" in navigation["selection_hint"]
