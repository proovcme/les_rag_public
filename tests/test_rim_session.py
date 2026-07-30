from pathlib import Path

import pytest

from proxy.smeta_core.rim_session import (
    RimSessionConflict,
    RimSessionStore,
    RimSessionValidationError,
)


def _vor_rows():
    return [
        {
            "schema": "rim_vor_line_v1",
            "work_id": "vor-001",
            "section_name": "Кабельные трассы",
            "work_name": "Прокладка кабеля в лотке",
            "unit": "м",
            "quantity": 400.0,
            "source_ref": "spec.xlsx#sheet=СКС#row=14",
            "status": "valid",
        }
    ]


def _mapping_rows():
    return [
        {
            "schema": "rim_mapping_row_v1",
            "mapping_row_id": "map-001",
            "work_id": "vor-001",
            "norm_key": "ГЭСНм:10-06-001-01",
            "norm_code": "10-06-001-01",
            "norm_title": "Прокладка кабеля",
            "norm_unit": "100 м",
            "norm_quantity": 4.0,
            "candidate_rank": 1,
            "selection_status": "selected",
            "selection_kind": "direct",
            "is_analog": False,
            "card_opened": True,
            "reason": "Выбрано моделью после чтения карточки",
            "source_refs": ["spec.xlsx#sheet=СКС#row=14"],
            "edited_by": "model",
        }
    ]


def _create_with_vor(store: RimSessionStore):
    created = store.create_session(owner_id="tester", region_code="77", price_period="2026-Q2")
    return store.save_vor_revision(
        created.session["session_id"],
        owner_id="tester",
        rows=_vor_rows(),
        expected_parent_revision_id=created.revision_id,
    )


def test_persistent_session_separates_mapping_pricing_and_final_locks(tmp_path):
    store = RimSessionStore(tmp_path)
    vor = _create_with_vor(store)
    session_id = vor.session["session_id"]

    mapping = store.save_mapping_revision(
        session_id,
        owner_id="tester",
        mapping_rows=_mapping_rows(),
        expected_parent_revision_id=vor.revision_id,
    )
    reviewed = store.save_mapping_revision(
        session_id,
        owner_id="tester",
        mapping_rows=_mapping_rows(),
        conflicts=[
            {
                "conflict_id": "conflict-1",
                "code": "possible_duplicate_norm_binding",
                "severity": "warning",
            }
        ],
        revision_kind="mapping_global_review",
        expected_parent_revision_id=mapping.revision_id,
    )
    locked = store.lock_mapping(
        session_id,
        owner_id="tester",
        review_note="Проверено сметчиком",
        accepted_conflict_ids=["conflict-1"],
        expected_parent_revision_id=reviewed.revision_id,
    )
    assert locked.session["mapping_status"] == "mapping_locked"
    assert locked.session["pricing_status"] == "unpriced"
    assert locked.session["mapping_lock_revision_id"] == locked.revision_id

    priced = store.save_pricing_revision(
        session_id,
        owner_id="tester",
        trace={"schema": "rim_lsr_trace_v1", "summary": {"known_amount": 1000.0}},
        requirements=[
            {
                "requirement_id": "req-1",
                "kind": "kac",
                "severity": "blocking",
                "finality_policy": "blocks_final",
                "work_id": "vor-001",
                "description": "Нет подтвержденной текущей цены",
                "required_fields": ["supplier_offer_refs", "price_date"],
            }
        ],
        expected_parent_revision_id=locked.revision_id,
    )
    assert priced.session["pricing_status"] == "priced_partial"
    with pytest.raises(RimSessionConflict, match="complete priced draft"):
        store.finalize(
            session_id,
            owner_id="tester",
            review_note="Финальная проверка",
            expected_parent_revision_id=priced.revision_id,
        )
    with pytest.raises(RimSessionConflict, match="cannot be waived"):
        store.resolve_requirement(
            session_id,
            "req-1",
            owner_id="tester",
            status="waived_by_user",
            resolution={"reason": "принять риск"},
            expected_parent_revision_id=priced.revision_id,
        )

    resolved = store.resolve_requirement(
        session_id,
        "req-1",
        owner_id="tester",
        status="resolved",
        resolution={"supplier_offer_refs": ["kp.pdf"], "price_date": "2026-07-29"},
        expected_parent_revision_id=priced.revision_id,
    )
    assert resolved.session["pricing_status"] == "priced_partial"
    with pytest.raises(RimSessionConflict, match="complete priced draft"):
        store.finalize(
            session_id,
            owner_id="tester",
            review_note="Трасса ещё не пересчитана",
            expected_parent_revision_id=resolved.revision_id,
        )
    recalculated = store.save_pricing_revision(
        session_id,
        owner_id="tester",
        trace={"schema": "rim_lsr_trace_v1", "summary": {"known_amount": 1200.0}},
        requirements=[],
        expected_parent_revision_id=resolved.revision_id,
        created_by="user",
        change_note="Пересчёт с подтверждённым КАЦ",
    )
    assert recalculated.session["pricing_status"] == "priced_draft"
    final = store.finalize(
        session_id,
        owner_id="tester",
        review_note="Цены и итог проверены",
        expected_parent_revision_id=recalculated.revision_id,
    )
    assert final.session["pricing_status"] == "priced_final"
    assert final.session["final_lock_revision_id"] == final.revision_id
    assert final.session["mapping_lock_revision_id"] == locked.revision_id
    assert len(store.list_revisions(session_id, owner_id="tester")) == 9


def test_question_answer_is_bound_to_one_pending_question(tmp_path):
    store = RimSessionStore(tmp_path)
    vor = _create_with_vor(store)
    opened = store.open_question(
        vor.session["session_id"],
        owner_id="tester",
        question={
            "text": "Как проложен кабель?",
            "reason": "Способ влияет на норму",
            "work_ids": ["vor-001"],
            "options": ["в лотке", "в трубе"],
        },
        expected_parent_revision_id=vor.revision_id,
    )
    with pytest.raises(RimSessionConflict, match="unanswered question"):
        store.open_question(
            vor.session["session_id"],
            owner_id="tester",
            question={"text": "Второй вопрос"},
            expected_parent_revision_id=opened.revision_id,
        )
    answered = store.answer_question(
        vor.session["session_id"],
        owner_id="tester",
        answer={"value": "в лотке"},
        expected_parent_revision_id=opened.revision_id,
    )
    assert answered.session["pending_question_id"] == ""
    question_revision = store.list_revisions(
        vor.session["session_id"], owner_id="tester"
    )[-1]
    assert question_revision["payload"]["answer"] == {"value": "в лотке"}


def test_stale_parent_cannot_overwrite_session_head(tmp_path):
    store = RimSessionStore(tmp_path)
    vor = _create_with_vor(store)
    opened = store.open_question(
        vor.session["session_id"],
        owner_id="tester",
        question={"text": "Уточните способ монтажа"},
        expected_parent_revision_id=vor.revision_id,
    )
    with pytest.raises(RimSessionConflict, match="session head changed"):
        store.answer_question(
            vor.session["session_id"],
            owner_id="tester",
            answer={"value": "в лотке"},
            expected_parent_revision_id=vor.revision_id,
        )
    assert opened.session["head_revision_id"] == opened.revision_id


def test_agent_checkpoint_is_durable_bound_to_input_revision_and_not_a_revision(tmp_path):
    store = RimSessionStore(tmp_path)
    vor = _create_with_vor(store)
    session_id = vor.session["session_id"]
    revision_count = len(store.list_revisions(session_id, owner_id="tester"))
    payload = {
        "resume_state": {
            "schema": "smeta_norm_agent_resume_v1",
            "next_turn": 4,
            "conversation": [{"role": "tool", "content": "catalog result"}],
        }
    }

    saved = store.save_agent_checkpoint(
        session_id,
        owner_id="tester",
        checkpoint_kind="norm_mapping",
        base_revision_id=vor.revision_id,
        payload=payload,
    )

    assert saved["payload_sha256"]
    assert len(store.list_revisions(session_id, owner_id="tester")) == revision_count
    with pytest.raises(
        RimSessionValidationError,
        match="base revision does not belong",
    ):
        store.save_agent_checkpoint(
            session_id,
            owner_id="tester",
            checkpoint_kind="norm_mapping",
            base_revision_id="another-vor-revision",
            payload=payload,
        )
    loaded = store.load_agent_checkpoint(
        session_id,
        owner_id="tester",
        checkpoint_kind="norm_mapping",
        base_revision_id=vor.revision_id,
    )
    assert loaded["payload"] == payload
    assert (
        store.load_agent_checkpoint(
            session_id,
            owner_id="tester",
            checkpoint_kind="norm_mapping",
            base_revision_id="another-vor-revision",
        )
        is None
    )

    store.clear_agent_checkpoint(
        session_id,
        owner_id="tester",
        checkpoint_kind="norm_mapping",
    )
    assert (
        store.load_agent_checkpoint(
            session_id,
            owner_id="tester",
            checkpoint_kind="norm_mapping",
            base_revision_id=vor.revision_id,
        )
        is None
    )


def test_vor_validation_preserves_bad_rows_as_issues(tmp_path):
    store = RimSessionStore(tmp_path)
    created = store.create_session(owner_id="tester")
    result = store.save_vor_revision(
        created.session["session_id"],
        owner_id="tester",
        rows=[
            {
                "work_id": "vor-001",
                "section_name": "",
                "work_name": "",
                "unit": "",
                "quantity": -1,
            }
        ],
        expected_parent_revision_id=created.revision_id,
    )
    codes = {item["code"] for item in result.issues}
    assert {"work_name_missing", "unit_missing", "section_missing", "quantity_negative"} <= codes
    revision = store.revision_payload(
        created.session["session_id"],
        result.revision_id,
        owner_id="tester",
    )
    assert len(revision["payload"]["rows"]) == 1
    assert Path(store.db_path).is_file()
