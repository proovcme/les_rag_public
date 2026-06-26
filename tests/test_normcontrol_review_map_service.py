"""Тест review-map loader (СПДС-нормоконтроль, Phase 1).

Проверяет: загрузку реального gost_r_21_101_2026 + fail-closed валидацию схемы + архитектурный
инвариант — review-map грузится как КАРТА (RAG-led review), а НЕ как rule-engine: у ReviewTarget
нет поля status/verdict, статус замечания появляется позже (computed evidence / human decision).
"""

import dataclasses

import pytest

from proxy.services.normcontrol_review_map_service import (
    VALID_KIND,
    ReviewTarget,
    list_review_maps,
    load_review_map,
)


def test_loads_real_gost_map():
    m = load_review_map("gost_r_21_101_2026")
    assert m.standard == "ГОСТ Р 21.101-2026"
    assert m.supersedes == "ГОСТ Р 21.101-2020"
    assert len(m.targets) >= 10  # 10-15 review targets первого среза
    assert all(t.kind in VALID_KIND for t in m.targets)
    assert all(t.id and t.check for t in m.targets)


def test_gost_map_in_list():
    assert "gost_r_21_101_2026" in list_review_maps()


def test_review_target_has_no_verdict_field():
    # АРХИТЕКТУРА: карта НЕ судит → у ReviewTarget нет status/human_decision/verdict/result.
    fields = {f.name for f in dataclasses.fields(ReviewTarget)}
    assert not (fields & {"status", "human_decision", "result", "verdict"})


def _write(tmp_path, body):
    (tmp_path / "bad.yaml").write_text(body, encoding="utf-8")
    return tmp_path


def test_rejects_legacy_deterministic_kind(tmp_path):
    # «deterministic» переименован в «computed» — старый rule-engine-нейминг запрещён.
    _write(tmp_path, "meta:\n  standard: X\nrules:\n  - id: A\n    kind: deterministic\n"
                     "    scope: both\n    severity: info\n    check: c\n")
    with pytest.raises(ValueError):
        load_review_map("bad", base=tmp_path)


def test_rejects_duplicate_id(tmp_path):
    _write(tmp_path, "meta:\n  standard: X\nrules:\n"
                     "  - id: A\n    kind: computed\n    scope: both\n    severity: info\n    check: c\n"
                     "  - id: A\n    kind: computed\n    scope: both\n    severity: info\n    check: c\n")
    with pytest.raises(ValueError):
        load_review_map("bad", base=tmp_path)


def test_rejects_missing_standard(tmp_path):
    _write(tmp_path, "meta:\n  name: x\nrules:\n"
                     "  - id: A\n    kind: computed\n    scope: both\n    severity: info\n    check: c\n")
    with pytest.raises(ValueError):
        load_review_map("bad", base=tmp_path)


def test_rejects_empty_rules(tmp_path):
    _write(tmp_path, "meta:\n  standard: X\nrules: []\n")
    with pytest.raises(ValueError):
        load_review_map("bad", base=tmp_path)


def test_rejects_missing_check(tmp_path):
    _write(tmp_path, "meta:\n  standard: X\nrules:\n"
                     "  - id: A\n    kind: computed\n    scope: both\n    severity: info\n")
    with pytest.raises(ValueError):
        load_review_map("bad", base=tmp_path)
