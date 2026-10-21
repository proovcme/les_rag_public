import hashlib
import json
import sqlite3

import pytest

from proxy.smeta_core import norm_browser


def _exact_base(path, *, stored_count=19, consumption=True):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE norms (
                norm_key TEXT PRIMARY KEY, norm_id TEXT, edition TEXT,
                display_code TEXT, base_type TEXT, norm_name TEXT, norm_unit TEXT,
                work_steps TEXT, source_doc TEXT, source_guid TEXT, resource_count INTEGER
            );
            CREATE TABLE resources (
                id INTEGER PRIMARY KEY, parent_norm_id TEXT, kind TEXT,
                resource_code TEXT, resource_name TEXT, resource_unit TEXT,
                per_unit REAL, price REAL, source_doc TEXT, source_guid TEXT
            );
        """)
        conn.execute(
            "INSERT INTO norms VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "ГЭСНм:08-02-001-01", "norm-id", "ФСНБ fixture", "ГЭСНм08-02-001-01",
                "ГЭСНм", "Исходная работа при указанном условии", "100 м",
                json.dumps(["Первый шаг", "Условие исходной карточки"], ensure_ascii=False),
                "source.xml", "norm-guid", stored_count,
            ),
        )
        for index in range(19):
            conn.execute(
                "INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    index + 1, "norm-id", "material", f"code-{index:02}",
                    "" if index == 18 else f"Ресурс {index}", "кг",
                    index / 4 if consumption else None, None,
                    "source.xml", f"resource-{index}",
                ),
            )


def test_exact_card_returns_all_resources_consumption_and_literal_provenance(tmp_path, monkeypatch):
    path = tmp_path / "База 'норм'.sqlite"
    _exact_base(path)
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_a, **_k: pytest.fail("no search"))
    monkeypatch.setattr(norm_browser, "_rag_cards_many", lambda *_a, **_k: pytest.fail("no RAG"))

    result = norm_browser.read_norm_card_exact(
        norm_key="ГЭСНм:08-02-001-01", norm_code="ГЭСНм08-02-001-01", base_path=path,
    )

    assert result["status"] == "ok"
    card = result["card"]
    assert card["norm_key"] == "ГЭСНм:08-02-001-01"
    assert card["norm_code"] == "ГЭСНм08-02-001-01"
    assert card["work_steps"] == ["Первый шаг", "Условие исходной карточки"]
    assert card["measure_unit"] == "100 м"
    assert card["source_ref"] == "source.xml#guid=norm-guid"
    assert len(card["resource_preview"]) == 16
    assert card["resources_returned"] == card["resource_count"] == 19
    assert card["resources_complete"] is True
    assert card["resources"][0]["per_unit"] == 0
    assert card["resources"][17]["per_unit"] == 4.25
    assert card["resources"][18]["name"] == ""
    assert card["resources"][18]["source_ref"] == "source.xml#guid=resource-18"


@pytest.mark.parametrize("selector", [
    {"norm_code": "ГЭСН08-02-001-01"},
    {"norm_key": "ГЭСН:08-02-001-01"},
    {"norm_code": "ГЭСНм08-02-001-02"},
    {"norm_code": "08-02-001-01"},
    {"norm_code": "монтаж ГЭСНм08-02-001-01"},
    {},
])
def test_exact_card_never_substitutes_another_family_or_search_result(tmp_path, selector):
    path = tmp_path / "base.sqlite"
    _exact_base(path)

    result = norm_browser.read_norm_card_exact(**selector, base_path=path)

    assert result["status"] == "missing"
    assert result["card"] is None
    assert result["missing"]


def test_key_and_code_conflict_is_not_resolved_by_one_selector(tmp_path):
    path = tmp_path / "base.sqlite"
    _exact_base(path)

    result = norm_browser.read_norm_card_exact(
        norm_key="ГЭСНм:08-02-001-01", norm_code="ГЭСН08-02-001-01", base_path=path,
    )

    assert result["status"] == "conflict"
    assert result["card"] is None


@pytest.mark.parametrize("stored_count,consumption", [(20, True), (19, False)])
def test_missing_resource_or_consumption_is_not_reported_as_full(tmp_path, stored_count, consumption):
    path = tmp_path / "base.sqlite"
    _exact_base(path, stored_count=stored_count, consumption=consumption)

    result = norm_browser.read_norm_card_exact(norm_key="ГЭСНм:08-02-001-01", base_path=path)

    assert result["status"] == "ok"
    assert result["card"]["resources_returned"] == 19
    assert result["card"]["resources_complete"] is False
    assert result["warnings"]


@pytest.mark.parametrize("selector", [
    {"norm_code": "ГЭСНм08-02-001-01"},
    {"norm_key": "ГЭСНм:08-02-001-01"},
])
def test_stored_display_code_mismatch_is_visible_without_replacement(tmp_path, selector):
    path = tmp_path / "base.sqlite"
    _exact_base(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE norms SET display_code = 'ГЭСНм08-02-001-02'")

    result = norm_browser.read_norm_card_exact(**selector, base_path=path)

    assert result["status"] == "conflict"
    assert result["card"] is None


def test_exact_card_missing_base_is_explicit(tmp_path):
    result = norm_browser.read_norm_card_exact(
        norm_key="ГЭСНм:08-02-001-01", base_path=tmp_path / "absent.sqlite",
    )

    assert result["status"] == "missing"
    assert result["missing"] == ["normative base unavailable"]


def _generation_base(tmp_path, monkeypatch, *, stored_count=19, consumption=True):
    path = tmp_path / "База 'точных норм'.sqlite"
    _exact_base(path, stored_count=stored_count, consumption=consumption)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = tmp_path / "Поколение нормативной базы.json"
    manifest.write_text(json.dumps({"status": "passed", "base_sha256": digest}), encoding="utf-8")
    monkeypatch.setenv("LES_SMETA_NORM_RAG_MANIFEST", str(manifest))
    monkeypatch.setattr(norm_browser, "_base_path", lambda: path)
    return path, manifest, digest


def test_model_exact_code_reads_full_active_generation_without_search(tmp_path, monkeypatch):
    path, _manifest, digest = _generation_base(tmp_path, monkeypatch)
    before = path.read_bytes()
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_a, **_k: pytest.fail("no candidate search"))
    monkeypatch.setattr(norm_browser, "_rag_cards_many", lambda *_a, **_k: pytest.fail("no model query rewrite"))

    result = norm_browser.read_norm_card_exact(
        norm_code="ГЭСНм08-02-001-01", require_generation=True,
    )

    assert result["status"] == "ok"
    card = result["card"]
    assert card["norm_code"] == "ГЭСНм08-02-001-01"
    assert card["norm_key"] == "ГЭСНм:08-02-001-01"
    assert card["normative_base_sha256"] == digest
    assert card["source_hash_basis"] == "normative_sqlite_base_bytes"
    assert card["source_ref"] == "source.xml#guid=norm-guid"
    assert card["work_steps"] == ["Первый шаг", "Условие исходной карточки"]
    assert card["measure_unit"] == "100 м"
    assert card["resources_complete"] is True
    assert len(card["resources"]) == card["resources_returned"] == 19
    assert card["resources"][0]["per_unit"] == 0
    assert card["resources"][17]["per_unit"] == 4.25
    assert card["resources"][18]["name"] == ""
    assert path.read_bytes() == before


@pytest.mark.parametrize("manifest_content", [
    None,
    "{invalid-json",
    "[]",
    '{"status":"failed","base_sha256":"' + "a" * 64 + '"}',
    '{"status":"passed","base_sha256":"not-a-generation"}',
    '{"status":"passed"}',
])
def test_model_exact_code_requires_a_passed_valid_generation(tmp_path, monkeypatch, manifest_content):
    _path, manifest, _digest = _generation_base(tmp_path, monkeypatch)
    if manifest_content is None:
        manifest.unlink()
    else:
        manifest.write_text(manifest_content, encoding="utf-8")
    monkeypatch.setattr(norm_browser, "_connect_base_readonly", lambda *_: pytest.fail("unverified generation must not be read"))

    result = norm_browser.read_norm_card_exact(norm_code="ГЭСНм08-02-001-01", require_generation=True)

    assert result["status"] == "source_unverified"
    assert result["card"] is None
    assert result["missing"]


def test_model_exact_code_rejects_bytes_different_from_retained_generation(tmp_path, monkeypatch):
    path, _manifest, _digest = _generation_base(tmp_path, monkeypatch)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE norms SET norm_name = 'Другая редакция карточки'")
    monkeypatch.setattr(norm_browser, "_connect_base_readonly", lambda *_: pytest.fail("changed generation must not be read"))

    result = norm_browser.read_norm_card_exact(norm_code="ГЭСНм08-02-001-01", require_generation=True)

    assert result["status"] == "source_unverified"
    assert result["card"] is None
    assert result["missing"]


def test_model_exact_code_discards_card_if_database_changes_during_read(tmp_path, monkeypatch):
    path, _manifest, _digest = _generation_base(tmp_path, monkeypatch)
    original = norm_browser._read_norm_card_connection

    def read_then_change(conn, key):
        result = original(conn, key)
        with sqlite3.connect(path) as writer:
            writer.execute("UPDATE resources SET per_unit = 999 WHERE id = 1")
        return result

    monkeypatch.setattr(norm_browser, "_read_norm_card_connection", read_then_change)

    result = norm_browser.read_norm_card_exact(norm_code="ГЭСНм08-02-001-01", require_generation=True)

    assert result["status"] == "conflict"
    assert result["card"] is None
    assert result["missing"]


@pytest.mark.parametrize("change", ["remove", "different_generation", "same_generation_changed_manifest"])
def test_model_exact_code_discards_card_if_manifest_changes_during_read(tmp_path, monkeypatch, change):
    _path, manifest, digest = _generation_base(tmp_path, monkeypatch)
    original = norm_browser._read_norm_card_connection

    def read_then_change(conn, key):
        result = original(conn, key)
        if change == "remove":
            manifest.unlink()
        elif change == "different_generation":
            manifest.write_text(json.dumps({"status": "passed", "base_sha256": "b" * 64}), encoding="utf-8")
        else:
            manifest.write_text(json.dumps({"status": "passed", "base_sha256": digest, "revision": 2}), encoding="utf-8")
        return result

    monkeypatch.setattr(norm_browser, "_read_norm_card_connection", read_then_change)

    result = norm_browser.read_norm_card_exact(norm_code="ГЭСНм08-02-001-01", require_generation=True)

    assert result["status"] == "conflict"
    assert result["card"] is None
    assert result["missing"]


@pytest.mark.parametrize("code", [
    "ГЭСН08-02-001-01", "ГЭСНм08-02-001-02", "08-02-001-01",
    "ГЭСНм08-02-001", "монтаж ГЭСНм08-02-001-01",
])
def test_model_exact_code_never_substitutes_other_family_variant_or_partial_code(tmp_path, monkeypatch, code):
    _generation_base(tmp_path, monkeypatch)
    monkeypatch.setattr(norm_browser, "_typed_cards", lambda *_a, **_k: pytest.fail("no substitute search"))
    monkeypatch.setattr(norm_browser, "_rag_cards_many", lambda *_a, **_k: pytest.fail("no substitute RAG"))

    result = norm_browser.read_norm_card_exact(norm_code=code, require_generation=True)

    assert result["status"] == "missing"
    assert result["card"] is None
    assert result["missing"]


@pytest.mark.parametrize("stored_count,consumption", [(20, True), (19, False)])
def test_verified_generation_does_not_hide_incomplete_resource_data(tmp_path, monkeypatch, stored_count, consumption):
    _path, _manifest, digest = _generation_base(
        tmp_path, monkeypatch, stored_count=stored_count, consumption=consumption,
    )

    result = norm_browser.read_norm_card_exact(norm_code="ГЭСНм08-02-001-01", require_generation=True)

    assert result["status"] == "ok"
    assert result["card"]["normative_base_sha256"] == digest
    assert result["card"]["resources_returned"] == 19
    assert result["card"]["resources_complete"] is False
    assert result["warnings"]


def test_explicit_generation_pin_keeps_legacy_read_without_manifest(tmp_path):
    path = tmp_path / "legacy.sqlite"
    _exact_base(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    result = norm_browser.read_norm_card_exact(
        norm_code="ГЭСНм08-02-001-01", base_path=path, expected_base_sha256=digest,
    )

    assert result["status"] == "ok"
    assert result["card"]["normative_base_sha256"] == digest
    assert result["card"]["source_hash_basis"] == "normative_sqlite_base_bytes"
