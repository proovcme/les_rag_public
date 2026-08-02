"""Behavioral contract for the tolerant smeta mapping interpreter."""

from proxy.smeta_core.document_workflow import (
    SmetaNormToolSession,
    resolve_extracted_norm_code_flexible,
)


def _card(code: str, title: str = "Монтаж оборудования") -> dict:
    return {
        "norm_code": code,
        "cipher": code,
        "title": title,
        "measure_unit": "шт",
        "source_ref": f"typed://{code}",
    }


def test_balanced_resolver_preserves_existing_bind():
    item = {
        "work_id": "vor-0001",
        "decision": "bind",
        "norm_code": "ГЭСНм37-01-002-01",
        "reason": "Я выбрала открытую карточку",
    }
    opened = {"vor-0001": {item["norm_code"]: _card(item["norm_code"])}}

    result = resolve_extracted_norm_code_flexible(dict(item), opened_cards=opened)

    assert result["decision"] == "bind"
    assert result["norm_code"] == "ГЭСНм37-01-002-01"
    assert result["_les_flexible_interpretation"]["decision_preserved"] == "bind"


def test_balanced_resolver_recovers_unique_opened_code_for_model_bind():
    code = "ГЭСНм11-04-027-01"
    item = {
        "work_id": "vor-0010",
        "decision": "bind",
        "norm_code": "",
        "reason": "Применима открытая таблица ГЭСНм 11-04-027.",
    }
    opened = {"vor-0010": {code: _card(code)}}

    result = resolve_extracted_norm_code_flexible(dict(item), opened_cards=opened)

    assert result["decision"] == "bind"
    assert result["norm_code"] == code
    assert result["_les_flexible_interpretation"]["repair"] == (
        "resolved_unique_opened_model_reference"
    )


def test_balanced_resolver_does_not_choose_between_two_opened_leaf_norms():
    item = {
        "work_id": "vor-0010",
        "decision": "bind",
        "norm_code": "",
        "reason": "Применима таблица ГЭСНм 11-04-027.",
    }
    opened = {
        "vor-0010": {
            "ГЭСНм11-04-027-01": _card("ГЭСНм11-04-027-01"),
            "ГЭСНм11-04-027-02": _card("ГЭСНм11-04-027-02"),
        }
    }

    result = resolve_extracted_norm_code_flexible(dict(item), opened_cards=opened)

    assert result["decision"] == "bind"
    assert result["norm_code"] == ""
    assert result["_les_flexible_interpretation"]["matched_opened_codes"] == [
        "ГЭСНм11-04-027-01",
        "ГЭСНм11-04-027-02",
    ]


def test_balanced_resolver_keeps_unbound_and_never_creates_evidence():
    item = {
        "work_id": "vor-0007",
        "decision": "unbound",
        "covered_by_work_id": "",
        "reason": "Таблица ГЭСНм 11-04-027 не подходит по составу работ",
    }
    opened: dict = {}

    result = resolve_extracted_norm_code_flexible(dict(item), opened_cards=opened)

    assert result["decision"] == "unbound"
    assert result.get("norm_code", "") == ""
    assert opened == {}
    assert result["_les_flexible_interpretation"]["reason_suggests_positive_applicability"] is False


def test_balanced_resolver_keeps_covered_by_and_never_converts_to_bind():
    item = {
        "work_id": "vor-0010",
        "decision": "covered_by",
        "covered_by_work_id": "vor-0001",
        "reason": "Монтаж учтён открытой нормой ГЭСНм 11-04-027-01 в строке vor-0001",
    }

    result = resolve_extracted_norm_code_flexible(dict(item), opened_cards={})

    assert result["decision"] == "covered_by"
    assert result["covered_by_work_id"] == "vor-0001"
    assert result.get("norm_code", "") == ""


def test_submit_rejects_self_covered_by_with_a_model_clarification_hint():
    session = SmetaNormToolSession(
        [{"work_id": "vor-0001", "title": "Шкаф", "unit": "шт", "quantity": 1}],
        candidate_limit=3,
    )

    result = session._submit({
        "rows": [{
            "work_id": "vor-0001",
            "decision": "covered_by",
            "covered_by_work_id": "vor-0001",
            "reason": "Покрывается монтажом шкафа",
        }]
    })

    assert result["ok"] is False
    assert result["errors"][0]["error"] == (
        "covered_by requires another existing source work_id"
    )


def test_submit_returns_positive_unbound_reference_to_same_model():
    code = "ГЭСНм11-04-027-01"
    session = SmetaNormToolSession(
        [{"work_id": "vor-0001", "title": "Патч-панель", "unit": "шт", "quantity": 1}],
        candidate_limit=3,
    )
    session.opened["vor-0001"][code] = _card(code)

    result = session._submit({
        "rows": [{
            "work_id": "vor-0001",
            "decision": "unbound",
            "reason": "Открытая норма ГЭСНм 11-04-027-01 подходит для монтажа",
        }]
    })

    assert result["ok"] is False
    assert result["errors"][0]["error"] == (
        "unbound decision conflicts with the model's positive norm reference"
    )
    assert result["errors"][0]["resolver_hint"]["matched_opened_codes"] == [code]


def test_legacy_mode_preserves_gemini_aggressive_binding(monkeypatch):
    from proxy.smeta_core import norm_browser

    code = "ГЭСНм11-04-027-01"
    monkeypatch.setattr(
        norm_browser,
        "browse_norms",
        lambda *_args, **_kwargs: {"cards": [_card(code)]},
    )
    item = {
        "work_id": "vor-0007",
        "decision": "unbound",
        "reason": "Монтаж относится к таблице 11-04-027",
    }
    opened: dict = {}

    result = resolve_extracted_norm_code_flexible(
        dict(item),
        opened_cards=opened,
        mode="legacy",
    )

    assert result["decision"] == "bind"
    assert result["norm_code"] == code
    assert opened["vor-0007"][code]["source_ref"] == f"typed://{code}"


def test_off_mode_is_exact_bypass():
    item = {
        "work_id": "vor-0002",
        "decision": "unbound",
        "reason": "Подходит ГЭСНм 11-04-027-01",
    }

    assert resolve_extracted_norm_code_flexible(dict(item), mode="off") == item
