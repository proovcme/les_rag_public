"""Latest-job polling reads foreign identities, never their large workbook bodies."""
import json
import sqlite3

import pytest

from proxy.services.workbook_research_job_service import WorkbookResearchJobService as Store


def create(store, *, session="owned", attachment="read_owned", question="original"):
    identity = store.identity(session_id=session, attachment_id=attachment, source_sha256="a" * 64,
                              dataset_ids=[], profile_revision_id="same", model_identity="same", question=question)
    return store.begin_or_resume(identity)


def stamp(store, job, value):
    with store._connect() as conn:
        conn.execute("UPDATE workbook_research_jobs SET updated_at=? WHERE job_id=?", (value, job["job_id"]))


def observe(store, monkeypatch, *, selected_id=""):
    trace, candidate_rows, full_rows = [], [], []
    connect = store._connect

    def instrumented():
        conn = connect()
        conn.set_trace_callback(trace.append)

        def row_factory(cursor, values):
            columns = tuple(column[0] for column in cursor.description)
            if columns == ("job_id", "identity_json"):
                assert sum(len(str(value)) for value in values) < 4096
                candidate_rows.append(values)
            elif "accepted_rows_json" in columns:
                assert selected_id and values[columns.index("job_id")] == selected_id
                full_rows.append(values)
            return sqlite3.Row(cursor, values)

        conn.row_factory = row_factory
        return conn

    monkeypatch.setattr(store, "_connect", instrumented)
    return trace, candidate_rows, full_rows


def test_foreign_megabyte_bodies_are_not_fetched_or_decoded_and_selected_job_is_unchanged(tmp_path, monkeypatch):
    store = Store(tmp_path / "large-foreign.sqlite")
    selected = create(store)
    selected = store.record_packet(selected["job_id"], sheet="Раздел Ω", packet_locators=["Раздел Ω!R2"],
        accepted_rows=[{"source_row": "Раздел Ω!R2", "row_role": "work", "title": "Авторская работа",
                        "unit": "м", "quantity": 0, "coverage": "Подтверждённый исходный ноль"}],
        evidence=[{"global_evidence_id": "own-evidence", "content": "Literal issued evidence"}], remaining=[])
    store.record_search_cache(selected["job_id"], {"literal owned query": [{"content": "Literal card"}]})
    store.finish(selected["job_id"], status="complete")
    store.record_packaging(selected["job_id"], tool="build_lsr_workbook", revision_id="literal-final", draft=False,
                           price_basis={"actual_book": "sankt-peterburg_3kv2026", "match": "exact"})
    foreign = [create(store, session=f"foreign-{index}", attachment=f"read_foreign_{index}") for index in range(3)]
    # These source bodies deliberately belong to different sessions/attachments.
    # Polling one owned identity must not materialize them into Python at all.
    large = json.dumps({"foreign_literal": "x" * 1_048_576})
    with store._connect() as conn:
        for item in foreign:
            conn.execute("UPDATE workbook_research_jobs SET accepted_rows_json=?,evidence_json=?,query_cache_json=?,"
                         "held_packet_json=?,task_context_json=?,updated_at='2026-10-16 12:00:00' WHERE job_id=?",
                         (large, large, large, large, large, item["job_id"]))
    stamp(store, selected, "2026-10-16 11:00:00")
    expected = store.get(selected["job_id"])
    trace, candidates, fetched = observe(store, monkeypatch, selected_id=selected["job_id"])
    original_loads = json.loads

    def no_foreign_decode(value, *args, **kwargs):
        assert "foreign_literal" not in str(value)
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", no_foreign_decode)
    actual = store.latest(session_id="owned", attachment_id="read_owned")
    assert actual == expected
    assert len(candidates) == 1 and len(fetched) == 1
    selects = [statement for statement in trace if statement.startswith("SELECT")]
    assert selects[0].startswith("SELECT job_id,identity_json FROM workbook_research_jobs WHERE ")
    assert "json_extract(identity_json,'$.session_id')='owned'" in selects[0]
    assert "json_extract(identity_json,'$.attachment_id')='read_owned'" in selects[0]
    assert selects[0].endswith("ORDER BY updated_at DESC LIMIT 200")
    full_selects = [statement for statement in selects if statement.startswith("SELECT * FROM workbook_research_jobs")]
    assert len(full_selects) == 1 and selected["job_id"] in full_selects[0]
    assert actual["document"]["final_revision_id"] == "literal-final"
    assert actual["accepted_rows"][0]["quantity"] == 0


def test_newest_matching_session_attachment_and_combined_scope_keep_the_same_order(tmp_path):
    store = Store(tmp_path / "ordered.sqlite")
    oldest = create(store, session="owned", attachment="read_same", question="old")
    other = create(store, session="other", attachment="read_same", question="new")
    newest = create(store, session="owned", attachment="read_new", question="latest")
    for hour, item in enumerate([oldest, other, newest], 1):
        stamp(store, item, f"2026-10-16 0{hour}:00:00")
    assert store.latest(session_id=" owned ")["job_id"] == newest["job_id"]
    assert store.latest(attachment_id=" read_same ")["job_id"] == other["job_id"]
    assert store.latest(session_id="owned", attachment_id="read_same")["job_id"] == oldest["job_id"]
    assert store.latest(session_id="other", attachment_id="read_new") is None


def test_old_owned_job_is_retrievable_beyond_200_foreign_jobs(tmp_path, monkeypatch):
    store = Store(tmp_path / "window.sqlite")
    selected = create(store)
    stamp(store, selected, "2026-01-01 00:00:00")
    with store._connect() as conn:
        for index in range(201):
            conn.execute("INSERT INTO workbook_research_jobs(job_id,identity_hash,identity_json,status,phase,updated_at)"
                         " VALUES(?,?,?,'complete','complete','2026-02-01 00:00:00')",
                         (f"foreign_{index}", f"foreign_hash_{index}", json.dumps({"session_id": "foreign"})))
    trace, candidates, fetched = observe(store, monkeypatch, selected_id=selected["job_id"])
    assert store.latest(session_id="owned")["job_id"] == selected["job_id"]
    assert len(candidates) == len(fetched) == 1
    candidates.clear()
    assert store.latest(session_id="owned", limit=1)["job_id"] == selected["job_id"]
    assert len(candidates) == 1 and len(fetched) == 2


@pytest.mark.parametrize("requested,expected", [(0, 200), (1, 1), (2, 2), (999, 500), (-1, 1)])
def test_candidate_window_limit_default_and_clamps_are_unchanged(tmp_path, monkeypatch, requested, expected):
    store = Store(tmp_path / "limit.sqlite")
    selected = create(store)
    trace, _candidates, fetched = observe(store, monkeypatch, selected_id=selected["job_id"])
    assert store.latest(session_id="owned", limit=requested)["job_id"] == selected["job_id"]
    assert trace[0].endswith(f"LIMIT {expected}") and len(fetched) == 1


def test_empty_scope_performs_no_database_read_and_missing_scope_fetches_no_full_job(tmp_path, monkeypatch):
    store = Store(tmp_path / "absent.sqlite")
    create(store)
    trace, candidates, fetched = observe(store, monkeypatch)
    assert store.latest() is None and store.latest(session_id=" ", attachment_id=" ") is None
    assert trace == [] and candidates == [] and fetched == []
    assert store.latest(session_id="absent") is None
    assert candidates == [] and fetched == []
    assert len([statement for statement in trace if statement.startswith("SELECT")]) == 1
