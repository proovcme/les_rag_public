"""Тесты pp87_composition_service (T2.5, TDD red->green).

АРХИТЕКТУРА (implementation_plan.md, промпт T2.5): детерминированный composition-checker
состава ПД по ПП РФ №87 от 16.02.2008. check_composition — чистая функция: принимает inventory
(список {file_name, ...}, как из checklist_review_service inventory_provider) и config (dict из
``config/checklists/pp87_composition.yaml``), сопоставляет разделы по filename_patterns (regex).
Ни одного обращения к живым сервисам (Qdrant/MLX/MetaDB) — конфиг и inventory приходят
параметрами, как и остальные механизмы checklist_review_service (_run_presence/_run_calculation).

Правила:
  - required=always, найден >=1 файл -> status=present;
  - required=always, файлов нет -> status=missing;
  - required=conditional, найден >=1 файл -> status=present;
  - required=conditional, файлов нет -> status=unknown (НЕ missing — кондиционный раздел мог быть
    не нужен для конкретного объекта, отсутствие evidence не равно нарушению, тот же принцип, что
    и в presence/calculation механизмах checklist_review_service);
  - matched_files — список имён файлов, совпавших хоть с одним filename_pattern раздела;
  - summary — агрегаты: total/present/missing/unknown, all_required_present (bool).
"""

from __future__ import annotations

import pytest

from proxy.services.pp87_composition_service import check_composition, load_pp87_config


def _mini_config() -> dict:
    return {
        "meta": {"version": 1, "title": "test"},
        "sections": [
            {
                "code": "1",
                "title": "Пояснительная записка (ПЗ)",
                "required": "always",
                "filename_patterns": [r"раздел\s*пд\s*№?\s*1\b", r"\bпз\b"],
                "requirement_ref": "ПП РФ №87 от 16.02.2008, п.12, раздел 1",
            },
            {
                "code": "3",
                "title": "Архитектурные решения (АР)",
                "required": "always",
                "filename_patterns": [r"раздел\s*пд\s*№?\s*3\b", r"\bар\d*\b"],
                "requirement_ref": "ПП РФ №87 от 16.02.2008, п.12, раздел 3",
            },
            {
                "code": "11",
                "title": "Смета на строительство (СМ)",
                "required": "conditional",
                "filename_patterns": [r"раздел\s*пд\s*№?\s*11\b", r"\bсм\d*\b"],
                "requirement_ref": "ПП РФ №87 от 16.02.2008, п.12, раздел 11",
            },
        ],
    }


# ── load_pp87_config ────────────────────────────────────────────────────────────────────────


def test_load_pp87_config_reads_canonical_yaml():
    cfg = load_pp87_config()
    codes = {s["code"] for s in cfg["sections"]}
    assert "1" in codes and "3" in codes
    for section in cfg["sections"]:
        assert section["required"] in ("always", "conditional")
        assert section["filename_patterns"]
        assert section["requirement_ref"]


def test_load_pp87_config_fail_closed_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_pp87_config(tmp_path / "missing.yaml")


def test_load_pp87_config_fail_closed_on_bad_operator_field(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "meta:\n  version: 1\nsections:\n"
        "  - code: '1'\n    title: x\n    required: sometimes\n"
        "    filename_patterns: ['a']\n    requirement_ref: 'x'\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_pp87_config(bad)


def test_load_pp87_config_fail_closed_on_empty_patterns(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "meta:\n  version: 1\nsections:\n"
        "  - code: '1'\n    title: x\n    required: always\n"
        "    filename_patterns: []\n    requirement_ref: 'x'\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_pp87_config(bad)


# ── check_composition: present/missing/unknown ─────────────────────────────────────────────


def test_all_required_sections_present_gives_present_status_and_matched_files():
    inventory = [
        {"file_name": "Раздел ПД №1. Часть 1. ПЗ.pdf"},
        {"file_name": "Раздел ПД №3. Часть 1. АР1.pdf"},
    ]
    result = check_composition(inventory, _mini_config())
    by_code = {s["code"]: s for s in result["sections"]}

    assert by_code["1"]["status"] == "present"
    assert by_code["1"]["matched_files"] == ["Раздел ПД №1. Часть 1. ПЗ.pdf"]
    assert by_code["1"]["requirement_ref"] == "ПП РФ №87 от 16.02.2008, п.12, раздел 1"

    assert by_code["3"]["status"] == "present"
    assert by_code["3"]["matched_files"] == ["Раздел ПД №3. Часть 1. АР1.pdf"]


def test_missing_required_always_section_gives_missing_status():
    inventory = [{"file_name": "Раздел ПД №1. Часть 1. ПЗ.pdf"}]
    result = check_composition(inventory, _mini_config())
    by_code = {s["code"]: s for s in result["sections"]}

    assert by_code["3"]["status"] == "missing"
    assert by_code["3"]["matched_files"] == []


def test_missing_conditional_section_gives_unknown_not_missing():
    inventory = [
        {"file_name": "Раздел ПД №1. Часть 1. ПЗ.pdf"},
        {"file_name": "Раздел ПД №3. Часть 1. АР1.pdf"},
    ]
    result = check_composition(inventory, _mini_config())
    by_code = {s["code"]: s for s in result["sections"]}

    assert by_code["11"]["status"] == "unknown"
    assert by_code["11"]["required"] == "conditional"
    assert by_code["11"]["matched_files"] == []


def test_present_conditional_section_gives_present_not_unknown():
    inventory = [
        {"file_name": "Раздел ПД №1. Часть 1. ПЗ.pdf"},
        {"file_name": "Раздел ПД №3. Часть 1. АР1.pdf"},
        {"file_name": "Раздел ПД №11. Часть 1. СМ.pdf"},
    ]
    result = check_composition(inventory, _mini_config())
    by_code = {s["code"]: s for s in result["sections"]}
    assert by_code["11"]["status"] == "present"
    assert by_code["11"]["matched_files"] == ["Раздел ПД №11. Часть 1. СМ.pdf"]


def test_matching_is_case_insensitive_and_ignores_extra_files():
    inventory = [
        {"file_name": "РАЗДЕЛ пд №1. ПЗ.PDF"},
        {"file_name": "Раздел ПД №3. АР1.pdf"},
        {"file_name": "Незначащий_файл.docx"},
    ]
    result = check_composition(inventory, _mini_config())
    by_code = {s["code"]: s for s in result["sections"]}
    assert by_code["1"]["status"] == "present"
    assert by_code["3"]["status"] == "present"


def test_multiple_files_match_same_section_all_listed():
    inventory = [
        {"file_name": "Раздел ПД №3. Часть 1. АР1.pdf"},
        {"file_name": "Раздел ПД №3. Часть 2. АР2.pdf"},
    ]
    cfg = {
        "meta": {"version": 1},
        "sections": [_mini_config()["sections"][1]],  # раздел 3 only
    }
    result = check_composition(inventory, cfg)
    section = result["sections"][0]
    assert section["status"] == "present"
    assert section["matched_files"] == [
        "Раздел ПД №3. Часть 1. АР1.pdf",
        "Раздел ПД №3. Часть 2. АР2.pdf",
    ]


def test_empty_inventory_gives_missing_for_always_and_unknown_for_conditional():
    result = check_composition([], _mini_config())
    by_code = {s["code"]: s for s in result["sections"]}
    assert by_code["1"]["status"] == "missing"
    assert by_code["3"]["status"] == "missing"
    assert by_code["11"]["status"] == "unknown"


def test_inventory_items_without_file_name_are_ignored_not_crashing():
    inventory = [{"doc_type": "x"}, {"file_name": None}, {"file_name": "Раздел ПД №1. ПЗ.pdf"}]
    result = check_composition(inventory, _mini_config())
    by_code = {s["code"]: s for s in result["sections"]}
    assert by_code["1"]["status"] == "present"


# ── summary ──────────────────────────────────────────────────────────────────────────────────


def test_summary_counts_and_all_required_present_flag():
    inventory = [
        {"file_name": "Раздел ПД №1. ПЗ.pdf"},
        {"file_name": "Раздел ПД №3. АР1.pdf"},
    ]
    result = check_composition(inventory, _mini_config())
    summary = result["summary"]
    assert summary["total"] == 3
    assert summary["present"] == 2
    assert summary["missing"] == 0
    assert summary["unknown"] == 1
    assert summary["all_required_present"] is True


def test_summary_all_required_present_false_when_required_missing():
    inventory = [{"file_name": "Раздел ПД №1. ПЗ.pdf"}]
    result = check_composition(inventory, _mini_config())
    assert result["summary"]["all_required_present"] is False
    assert result["summary"]["missing"] == 1


def test_check_composition_uses_canonical_config_by_default_via_load_pp87_config():
    # Проверка интеграции: результат на реальном каноническом конфиге содержит все ожидаемые коды.
    cfg = load_pp87_config()
    result = check_composition([], cfg)
    codes = {s["code"] for s in result["sections"]}
    assert {"1", "2", "3", "4", "5", "6", "8", "9", "10"} <= codes
    # always-разделы отсутствуют в пустом inventory -> missing
    always_codes = {s["code"] for s in cfg["sections"] if s["required"] == "always"}
    by_code = {s["code"]: s for s in result["sections"]}
    for code in always_codes:
        assert by_code[code]["status"] == "missing"
