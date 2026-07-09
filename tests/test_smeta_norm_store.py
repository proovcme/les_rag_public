"""SQLite-light norm store for model-first smeta candidate search."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from proxy.services.smeta_norm_store import (
    SmetaNormStore,
    SmetaNormRow,
    _composition_steps_from_cards,
    _composition_steps_from_markdown,
    _build_rows,
    get_smeta_norm_store,
    norm_store_payload,
)


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
        "navigation", "applicability", "price_inputs", "decision_order", "work_composition",
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
    row = store.by_code("ГЭСН:01-02-057-01")

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
    row = store.by_code("ГЭСН:01-02-057-01")
    assert row is not None

    navigation = store.navigation_for(row, family_hint="earthworks", element_hint="excavation")

    assert navigation["collection"]["key"] == "01"
    assert navigation["nearby_norms"]
    assert all(item["code"] != row.code for item in navigation["nearby_norms"])
    assert "соседними нормами" in navigation["selection_hint"]


def test_smeta_norm_store_profile_exposes_work_composition_steps():
    row = SmetaNormRow(
        code="ГЭСН:11-01-011-01",
        title="устройство стяжек: цементных толщиной 20 мм",
        measure_unit="100 м2",
        base_unit="м2",
        base_type="ГЭСН",
        collection="11",
        collection_key="11",
        subsection="11-01",
        source_kind="base_parquet",
        provenance="fixture",
        resource_count=1,
        resource_kinds="labor",
        family_hints="floors",
        element_hints="floors",
        action_hints="устройство",
        negative_hints="",
        condition_hints="материал/основание",
        work_steps='["Подготовка основания.", "Устройство стяжки."]',
        token_text="устройство стяжек подготовка основания",
    )

    profile = row.profile()

    assert profile["work_steps"] == ["Подготовка основания.", "Устройство стяжки."]
    assert profile["model_card"]["work_composition"]["steps"] == [
        "Подготовка основания.",
        "Устройство стяжки.",
    ]


def test_smeta_norm_store_reads_work_composition_from_service_cards(tmp_path, monkeypatch):
    card = tmp_path / "gesn2" / "codes" / "11_01_011_01.md"
    card.parent.mkdir(parents=True)
    card.write_text(
        "# 11-01-011-01 Устройство стяжек\n\n"
        "## Наименование\n\nУстройство стяжек\n\n"
        "## Состав работ\n\n"
        "- Подготовка основания.\n"
        "- Устройство стяжки.\n\n"
        "## Ресурсы на измеритель нормы\n\n| Код | Наименование |\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("LES_SMETA_COMPOSITION_CARD_ROOTS", str(tmp_path))
    _composition_steps_from_cards.cache_clear()

    cards = _composition_steps_from_cards()

    assert _composition_steps_from_markdown(card.read_text(encoding="utf-8")) == [
        "Подготовка основания.",
        "Устройство стяжки.",
    ]
    assert cards["ГЭСН:11-01-011-01"] == ["Подготовка основания.", "Устройство стяжки."]


def test_smeta_norm_store_demotes_legacy_untyped_and_hides_empty_norms(monkeypatch):
    from proxy.services import smeta_norm_store as store_mod

    monkeypatch.setattr(
        "proxy.services.gesn_service.load_base_norms",
        lambda: {
            "ГЭСН:10-08-005-04": {
                "code": "ГЭСН10-08-005-04",
                "base_type": "ГЭСН",
                "key": "ГЭСН:10-08-005-04",
                "name": "Линия скрутка из проводов",
                "unit": "м",
                "resources": [{"kind": "labor", "name": "Рабочий", "unit": "чел.-ч", "per_unit": 1}],
                "_source_kind": "legacy_untyped_parquet",
            },
            "ГЭСНм:10-08-005-04": {
                "code": "ГЭСНм10-08-005-04",
                "base_type": "ГЭСНм",
                "key": "ГЭСНм:10-08-005-04",
                "name": "Линия скрутка из проводов",
                "unit": "м",
                "resources": [{"kind": "labor", "name": "Рабочий", "unit": "чел.-ч", "per_unit": 1}],
                "_source_kind": "base_parquet",
            },
            "ГЭСН:99-99-999-99": {
                "code": "ГЭСН99-99-999-99",
                "base_type": "ГЭСН",
                "key": "ГЭСН:99-99-999-99",
                "name": "",
                "unit": "м",
                "resources": [{"kind": "labor", "name": "Рабочий", "unit": "чел.-ч", "per_unit": 1}],
                "_source_kind": "base_parquet",
            },
        },
    )
    monkeypatch.setattr("proxy.services.gesn_service.load_norms", lambda: {})
    store_mod._composition_steps_from_cards.cache_clear()

    store = SmetaNormStore(_build_rows())

    assert store.by_code("ГЭСН:99-99-999-99") is None
    assert store.by_code("ГЭСНм:10-08-005-04") is not None
    rows = store.search_rows(["линия", "скрутка"], limit=2)
    assert [row.code for row in rows] == ["ГЭСНм:10-08-005-04", "ГЭСН:10-08-005-04"]
