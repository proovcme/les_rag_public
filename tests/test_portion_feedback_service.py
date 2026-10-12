import json
import sqlite3

import pytest

from proxy.services.portion_feedback_service import PortionFeedbackService


@pytest.fixture
def store(tmp_path):
    return PortionFeedbackService(tmp_path / 'feedback.sqlite')


def event(**changes):
    return dict(dict(session_id='s1', source_revision='r1', turn_id='t1',
                     raw_answer='Original answer', rows=[{'source_row': 'S!1', 'norm_code': 'N1'}],
                     errors=['missing_evidence_ref:S!1'], evidence={'Q1.H1': {'content': 'Exact card'}}),
                **changes)


def test_append_is_immutable_and_survives_reopen(store):
    first = event()
    assert store.record(**first) is True
    saved = store.last(session_id='s1', source_revision='r1')
    first['rows'][0]['norm_code'] = 'changed'
    assert store.record(**event(turn_id='t2', raw_answer='Second answer')) is True
    reopened = PortionFeedbackService(store.db_path)
    assert reopened.last(session_id='s1', source_revision='r1')['sequence'] > saved['sequence']
    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute('SELECT raw_answer, rows_json FROM smeta_portion_feedback ORDER BY sequence').fetchall()
    assert [row[0] for row in rows] == ['Original answer', 'Second answer']
    assert json.loads(rows[0][1])[0]['norm_code'] == 'N1'


def test_repeat_is_idempotent(store):
    assert store.record(**event()) is True
    before = store.last(session_id='s1', source_revision='r1')
    assert store.record(**event()) is False
    assert store.last(session_id='s1', source_revision='r1') == before


@pytest.mark.parametrize('change', [
    {'raw_answer': 'different'}, {'rows': []}, {'errors': []}, {'evidence': {}},
])
def test_same_turn_conflict_cannot_overwrite(store, change, caplog):
    store.record(**event())
    before = store.last(session_id='s1', source_revision='r1')
    assert store.record(**event(**change)) is False
    assert store.last(session_id='s1', source_revision='r1') == before
    assert 'conflict' in caplog.text.lower()
    assert 'Original answer' not in caplog.text


def test_session_and_source_are_isolated(store):
    assert store.last(session_id='s1', source_revision='r1') is None
    for session, revision in [('s1', 'r1'), ('s2', 'r1'), ('s1', 'r2')]:
        assert store.record(**event(session_id=session, source_revision=revision)) is True
    for session, revision in [('s1', 'r1'), ('s2', 'r1'), ('s1', 'r2')]:
        saved = store.last(session_id=session, source_revision=revision)
        assert (saved['session_id'], saved['source_revision']) == (session, revision)
    assert store.last(session_id='s2', source_revision='r2') is None


def test_duplicate_rows_and_error_order_are_preserved(store):
    rows = [{'source_row': 'S!1', 'norm_code': 'N1'}, {'source_row': 'S!1', 'norm_code': 'N2'}]
    errors = ['second', 'first', 'second']
    store.record(**event(rows=rows, errors=errors))
    saved = store.last(session_id='s1', source_revision='r1')
    assert saved['rows'] == rows
    assert saved['errors'] == errors
    assert saved['evidence'] == event()['evidence']


def test_clean_event_clears_current_warning_without_removing_history(store):
    store.record(**event())
    store.record(**event(turn_id='t2', errors=[]))
    assert store.last(session_id='s1', source_revision='r1')['errors'] == []
    with sqlite3.connect(store.db_path) as conn:
        history = conn.execute('SELECT errors_json FROM smeta_portion_feedback ORDER BY sequence').fetchall()
    assert [json.loads(row[0]) for row in history] == [event()['errors'], []]


def test_no_decision_attempt_or_artifact_tables_touched(store):
    with sqlite3.connect(store.db_path) as conn:
        conn.execute('CREATE TABLE decisions (value TEXT)')
        conn.execute("INSERT INTO decisions VALUES ('unchanged')")
    store.record(**event())
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute('SELECT value FROM decisions').fetchall() == [('unchanged',)]
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {'decisions', 'smeta_portion_feedback'}


def test_scoped_feedback_does_not_request_revision_of_another_source_row(store):
    store.record(**event(rows=[{'source_row':'S!1','norm_code':'N1'},{'source_row':'S!2','norm_code':'N2'}],
        errors=['missing_evidence_ref:S!1','missing_evidence_ref:S!2'],evidence={'portion_shown':['S!1','S!2']}))
    feedback=store.for_anchors(session_id='s1',source_revision='r1',anchors=['S!1'],source_anchors=['S!1','S!2'])
    assert feedback['rows']==[{'source_row':'S!1','norm_code':'N1'}]
    assert feedback['errors']==['missing_evidence_ref:S!1']
    assert store.last(session_id='s1',source_revision='r1')['errors']==['missing_evidence_ref:S!1','missing_evidence_ref:S!2']


def test_observation_metadata_survives_conflict_and_never_invents_legacy_visits(store):
    store.record(**event())
    assert store.observation_order(session_id='s1',source_revision='r1')==(0,{})
    store.record(**event(turn_id='t2',evidence={'portion_shown':['S!1']}))
    store.record(**event(turn_id='t2',evidence={'portion_shown':['S!2']}))
    assert store.observation_order(session_id='s1',source_revision='r1')==(1,{'S!1':1})
    assert store.observation_order(session_id='s1',source_revision='other')==(0,{})
    store.record(**event(turn_id='t3',errors=[],evidence={'portion_shown':['S!1']}))
    assert store.for_anchors(session_id='s1',source_revision='r1',anchors=['S!1'],source_anchors=['S!1']) is None


@pytest.mark.parametrize('kind,field,value', [
    ('unknown_evidence_ref', 'evidence_refs', ['Q999.H1']),
    ('duplicate_work_id', 'work_id', 'work_2'),
])
def test_reference_and_operation_feedback_stays_with_authored_rows(store, kind, field, value):
    label = value[0] if isinstance(value, list) else value
    rows = [{'source_row': 'S!1', 'evidence_refs': ['Q1.H1'], 'work_id': 'work_1'},
            {'source_row': 'S!2', field: value}]
    error = f'{kind}:{label}'
    store.record(**event(rows=rows, errors=[error], evidence={'portion_shown': ['S!1', 'S!2']}))
    assert store.for_anchors(session_id='s1', source_revision='r1', anchors=['S!1'], source_anchors=['S!1', 'S!2']) is None
    assert store.for_anchors(session_id='s1', source_revision='r1', anchors=['S!2'], source_anchors=['S!1', 'S!2']) == {'rows': [rows[1]], 'errors': [error]}
    assert store.last(session_id='s1', source_revision='r1')['errors'] == [error]
