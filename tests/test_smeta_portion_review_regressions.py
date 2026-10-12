"""Review regressions on real portion planning and SQLite; no live services."""

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.portion_cursor_service import PortionCursorService
from proxy.smeta_core.vor_rows import rows_from_attachment_text, source_revision


TEXT = "Файл: original.xlsx\nS!R1: № | Наименование | Ед. изм | Количество\n" + "".join(
    f"S!R{n + 1}: {n} | Work {n} | шт. | 1\n" for n in range(1, 7)
)


@pytest.fixture
def store(tmp_path):
    return PortionCursorService(tmp_path / "cursor.db")


def record(store, state, rows):
    service.record_portion_pass(
        store, session_id="s", portion_state=state, rows=rows,
        closed=service.closed_row_anchors(rows, state["shown"]),
        artifact_revision_id=None,
    )


def return_to_open_row(store, anchor):
    """Exercise a full fair queue cycle, without closing any intervening row."""
    for _ in range(len(rows_from_attachment_text(TEXT)) + 1):
        text, state = service.smeta_portion_context(TEXT, session_id="s", limit=1, cursors=store)
        if state['shown'] == [anchor]:
            return text, state
        record(store, state, [{'source_row': state['shown'][0], 'norm_code': ''}])
    pytest.fail(f'Open row {anchor} was starved')


def test_latest_model_revision_survives_another_portion(store):
    _, state = service.smeta_portion_context(TEXT, session_id="s", limit=3, cursors=store)
    record(store, state, [{"source_row": "1", "norm_code": ""},
                          {"source_row": "2", "norm_code": "OLD"}])
    retry = state  # a later response for the same offered snapshot
    record(store, retry, [{"source_row": "1", "norm_code": "A"},
                          {"source_row": "2", "norm_code": "NEW"},
                          {"source_row": "3", "norm_code": "C"}])
    _, later = service.smeta_portion_context(TEXT, session_id="s", limit=3, cursors=store)
    assert later["prior_decisions"]["S!2"]["norm_code"] == "NEW"


def test_structural_rejections_visit_all_source_rows_without_packagable_decisions(store):
    """A rejected final must not trap the intact attachment at its first rows."""
    from proxy.services.portion_feedback_service import PortionFeedbackService
    shown=[]
    for number in range(1,4):
        text,state=service.smeta_portion_context(TEXT,session_id='s',limit=2,cursors=store)
        assert state['shown']==[f'S!{2*number-1}',f'S!{2*number}']
        shown.extend(state['shown'])
        assert 'OTHER_PORTION_ERROR' not in text
        answer=f'original malformed answer {number}'
        rows=[{'source_row':state['shown'][0],'norm_code':'MODEL_CHOICE','evidence_refs':[]}]
        assert service._record_structural_feedback(store,session_id='s',revision=state['source_revision'],turn_id=f't{number}',
            answer=answer,rows=rows,errors=['OTHER_PORTION_ERROR'],evidence={'portion_shown':state['shown']})
        # Replaying the terminal response must not rotate another time.
        assert service._record_structural_feedback(store,session_id='s',revision=state['source_revision'],turn_id=f't{number}',
            answer=answer,rows=rows,errors=['OTHER_PORTION_ERROR'],evidence={'portion_shown':state['shown']})
        progress=store.progress(session_id='s',source_revision=state['source_revision'])
        assert not progress.decisions and not progress.completed and not progress.attempts
        assert progress.artifact_revision_id is None
    assert len(set(shown))==6
    # After one traversal the original rejected rows remain open for model review.
    restarted=PortionCursorService(store.db_path)
    text,state=service.smeta_portion_context(TEXT,session_id='s',limit=2,cursors=restarted)
    assert state['shown']==['S!1','S!2'] and state['complete'] is False
    assert state['pass_no']==4
    assert 'OTHER_PORTION_ERROR' in text and 'Предыдущая строка S!1' in text
    assert 'Предыдущая строка S!5' not in text
    original=PortionFeedbackService(store.db_path).last(session_id='s',source_revision=state['source_revision'])
    assert original['raw_answer']=='original malformed answer 3'
    assert original['rows'][0]['norm_code']=='MODEL_CHOICE'
    _,other=service.smeta_portion_context(TEXT,session_id='other',limit=2,cursors=store)
    assert other['shown']==['S!1','S!2'] and other['pass_no']==1


def test_unstructured_final_is_observed_without_inventing_a_row_decision(store):
    _,state=service.smeta_portion_context(TEXT,session_id='s',limit=2,cursors=store)
    service._record_structural_feedback(store,session_id='s',revision=state['source_revision'],turn_id='unstructured',
        answer='raw prose without any table',rows=[],errors=['unstructured_model_result'],evidence={'portion_shown':state['shown']})
    _,next_state=service.smeta_portion_context(TEXT,session_id='s',limit=2,cursors=store)
    assert next_state['shown']==['S!3','S!4']
    assert not next_state['prior_decisions'] and next_state['completed']==0


def test_calculated_material_and_resource_close_without_fake_norm(store):
    _, state = service.smeta_portion_context(TEXT, session_id="s", limit=3, cursors=store)
    rows = [
        {"source_row": "1", "norm_code": "", "decision_kind": "самостоятельный материал"},
        {"source_row": "2", "norm_code": "", "decision_kind": "ресурс", "included_in": "6"},
        {"source_row": "3", "norm_code": "", "decision_kind": "самостоятельный материал"},
    ]
    service.record_portion_pass(
        store, session_id="s", portion_state=state, rows=rows, closed=[],
        artifact_revision_id="rev-calculated",
        row_statuses={"1": "material_bound", "2": "resource_bound", "3": "material_price_missing"},
    )
    progress = store.progress(session_id="s", source_revision=state["source_revision"])
    assert progress.completed == {"S!1", "S!2"}
    assert not progress.exhausted
    assert progress.decisions["S!1"]["norm_code"] == ""
    assert progress.decisions["S!3"]["rejected_reason"] == "material_price_missing"


def test_partial_format_failure_returns_original_cells_on_next_review(store):
    import json
    _, state = service.smeta_portion_context(TEXT, session_id="s", limit=1, cursors=store)
    header = ["source_row", "norm_code", "conversion_factor", "conversion_source"]
    cells = ["1", "N", "", "100", "https://manufacturer.example/pack"]
    decision = {"source_row": "1", "parse_error": "column_count_mismatch",
                "raw_header": header, "raw_cells": cells}
    service.record_portion_pass(
        store, session_id="s", portion_state=state, rows=[decision], closed=[],
        artifact_revision_id="rev-partial", row_statuses={"1": "model_row_format_error"},
    )
    # New rows get a turn first; the later review must still get every bad cell.
    text, _ = return_to_open_row(store, 'S!1')
    assert json.dumps(header, ensure_ascii=False) in text
    assert json.dumps(cells, ensure_ascii=False) in text
    assert not store.progress(session_id='s', source_revision=state['source_revision']).completed


def test_model_can_reopen_a_previously_closed_row(store):
    _, state = service.smeta_portion_context(TEXT, session_id="s", limit=3, cursors=store)
    record(store, state, [{"source_row": "2", "norm_code": "OLD"}])
    retry = state  # the model revises its earlier response to this portion
    record(store, retry, [{"source_row": "1", "norm_code": "A"},
                          {"source_row": "2", "norm_code": ""}])
    _, later = return_to_open_row(store, 'S!2')
    assert later["shown"] == ["S!2"]
    assert later["prior_decisions"]["S!2"]["norm_code"] == ""
    assert store.progress(session_id='s', source_revision=state['source_revision']).completed == {'S!1'}


def test_hole_inside_a_portion_keeps_original_workbook_order(store):
    _, state = service.smeta_portion_context(TEXT, session_id="s", limit=3, cursors=store)
    record(store, state, [{"source_row": "2", "norm_code": "B"},
                          {"source_row": "3", "norm_code": "C"}])
    _, retry = service.smeta_portion_context(TEXT, session_id="s", limit=3, cursors=store)
    merged = service.merged_pass_decisions(
        [{"source_row": "1", "norm_code": "A"}], closed=["S!1"], portion_state=retry,
    )
    assert [r["source_row"] for r in merged] == ["1", "2", "3"]


def test_an_unresolved_first_row_does_not_starve_later_rows(store):
    _, first = service.smeta_portion_context(TEXT, session_id="s", limit=3, cursors=store)
    record(store, first, [{"source_row": "1", "norm_code": ""},
                          {"source_row": "2", "norm_code": "B"},
                          {"source_row": "3", "norm_code": "C"}])
    body, second = service.smeta_portion_context(TEXT, session_id="s", limit=3, cursors=store)
    assert second["shown"] == ["S!4", "S!5", "S!6"]
    assert "Work 4" in body and "Work 2" not in body
    record(store, second, [{'source_row': a, 'norm_code': ''} for a in second['shown']])
    _, review = service.smeta_portion_context(TEXT, session_id='s', limit=1, cursors=store)
    assert review['shown'] == ['S!1']
    assert store.progress(session_id='s', source_revision=first['source_revision']).completed == {'S!2', 'S!3'}


@pytest.mark.parametrize("missing", ["—", "нет", "n/a", "(—)"])
def test_explicit_no_norm_is_not_a_closed_row(missing):
    assert service.closed_row_anchors([{"source_row": "1", "norm_code": missing}], ["S!1"]) == []


def test_ambiguous_position_number_cannot_close_an_arbitrary_sheet():
    assert service.closed_row_anchors(
        [{"source_row": "1", "norm_code": "A"}], ["S!1", "T!1"]
    ) == []


def test_qualified_model_labels_survive_record_and_merge(store):
    text = TEXT + "T!R1: № | Наименование | Количество | Ед. изм\nT!R2: 1 | Other | 12 | м\n"
    body, state = service.smeta_portion_context(text, session_id="s", limit=10, cursors=store)
    assert "S!1" in body and "T!1" in body
    # Пояснение к ячейкам не «Колонки: …»: короткий список имён модель читала как
    # образец таблицы и копировала его в ответ вместо требуемой шапки (прогон 21:24).
    assert "Ячейки строк ниже означают: № | Наименование | Количество | Ед. изм" in body
    rows = [{"source_row": "S!1", "norm_code": "A"}, {"source_row": "T!1", "norm_code": "B"}]
    record(store, state, rows)
    progress = store.progress(session_id="s", source_revision=state["source_revision"])
    assert progress.completed == {"S!1", "T!1"}
    assert progress.decisions["S!1"] == rows[0]
    assert progress.decisions["T!1"] == rows[1]


def test_section_and_column_meaning_invalidate_source_revision():
    section = TEXT.replace("S!R2:", "S!R0: Раздел: монтаж\nS!R2:")
    changed = section.replace("Раздел: монтаж", "Раздел: демонтаж")
    assert source_revision(rows_from_attachment_text(section)) != source_revision(rows_from_attachment_text(changed))
    assert source_revision(rows_from_attachment_text(TEXT)) != source_revision(
        rows_from_attachment_text(TEXT.replace("Ед. изм | Количество", "Количество | Ед. изм"))
    )


def test_rebuild_reopens_rejected_saved_choice_without_new_model_attempt(store):
    _, state = service.smeta_portion_context(TEXT, session_id="s", limit=2, cursors=store)
    rows = [{"source_row": "1", "norm_code": "A"}, {"source_row": "2", "norm_code": "B"}]
    record(store, state, rows)  # choices survived a failed packaging attempt
    before = store.progress(session_id="s", source_revision=state["source_revision"])
    store.record_calculation(
        session_id="s", source_revision=state["source_revision"],
        statuses={"S!1": "unit_conflict", "S!2": "bound"},
    )
    store.record_calculation(
        session_id="s", source_revision=state["source_revision"],
        statuses={"S!1": "unit_conflict", "S!2": "bound"},
    )
    after = store.progress(session_id="s", source_revision=state["source_revision"])
    assert after.passes == before.passes
    assert after.attempts == before.attempts
    assert after.last_decision_pass == before.last_decision_pass
    assert after.completed == {"S!2"}
    assert after.decisions["S!1"]["norm_code"] == "A"
    text, next_state = return_to_open_row(store, 'S!1')
    assert next_state["shown"] == ["S!1"]
    assert "измеритель нормы" in text
