"""Append-only model feedback, isolated from packagable and confirmed decisions."""
from __future__ import annotations

from contextlib import closing
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Mapping


class PortionFeedbackService:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS smeta_portion_feedback (
                    sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    raw_answer TEXT NOT NULL,
                    rows_json TEXT NOT NULL,
                    errors_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    UNIQUE(session_id, source_revision, turn_id)
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def record(
        self, *, session_id: str, source_revision: str, turn_id: str,
        raw_answer: str, rows: list[dict[str, Any]], errors: list[str],
        evidence: Mapping[str, Any],
    ) -> bool:
        """Insert one event; repeats/conflicts return False without replacing history.

        An empty errors list is a successful event, superseding the current warning.
        Conflicts are logged without exposing model content or evidence.
        """
        if not all(isinstance(value, str) and value.strip()
                   for value in (session_id, source_revision, turn_id)):
            raise ValueError('feedback requires session_id, source_revision and turn_id')
        if not isinstance(rows, list) or not isinstance(errors, list):
            raise TypeError('feedback rows and errors must be lists')
        if not isinstance(evidence, Mapping) or not isinstance(raw_answer, str):
            raise TypeError('feedback evidence must be a mapping and raw_answer a string')
        payload = (
            raw_answer,
            json.dumps(rows, ensure_ascii=False, sort_keys=True, allow_nan=False),
            json.dumps(errors, ensure_ascii=False, sort_keys=True, allow_nan=False),
            json.dumps(dict(evidence), ensure_ascii=False, sort_keys=True, allow_nan=False),
        )
        identity = (session_id, source_revision, turn_id)
        with closing(self._connect()) as conn, conn:
            inserted = conn.execute(
                """INSERT INTO smeta_portion_feedback
                   (session_id, source_revision, turn_id, raw_answer, rows_json, errors_json, evidence_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id, source_revision, turn_id) DO NOTHING""",
                (*identity, *payload),
            ).rowcount
            if inserted:
                return True
            existing = conn.execute(
                """SELECT raw_answer, rows_json, errors_json, evidence_json
                   FROM smeta_portion_feedback
                   WHERE session_id=? AND source_revision=? AND turn_id=?""", identity,
            ).fetchone()
            if tuple(existing) != payload:
                logging.getLogger(__name__).warning(
                    '[PORTION_FEEDBACK] content conflict for existing turn; original event preserved'
                )
            return False

    def last(self, *, session_id: str, source_revision: str) -> dict[str, Any] | None:
        """Return the newest event for exactly this session and attachment revision."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT * FROM smeta_portion_feedback
                   WHERE session_id=? AND source_revision=? ORDER BY sequence DESC LIMIT 1""",
                (session_id, source_revision),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for field in ('rows', 'errors', 'evidence'):
            result[field] = json.loads(result.pop(field + '_json'))
        return result

    def observation_order(self, *, session_id: str, source_revision: str) -> tuple[int, dict[str, int]]:
        """Order terminal observations; never infer accepted decisions from them.

        Only server-owned portion metadata is authoritative. Legacy events without
        that metadata do not invent visits from possibly invalid model row labels.
        """
        with closing(self._connect()) as conn:
            events=conn.execute('SELECT evidence_json FROM smeta_portion_feedback WHERE session_id=? AND source_revision=? ORDER BY sequence',
                                (session_id,source_revision)).fetchall()
        passes=0
        observed={}
        for event in events:
            shown=json.loads(event['evidence_json']).get('portion_shown')
            if not isinstance(shown,list) or not shown or any(not isinstance(a,str) or not a.strip() for a in shown):
                continue
            passes+=1
            for anchor in shown:observed[anchor]=passes
        return passes,observed

    def for_anchors(self, *, session_id: str, source_revision: str, anchors: list[str], source_anchors: list[str]) -> dict[str, Any] | None:
        """Latest feedback for each current row, without dragging other portions in.

        The append-only records remain untouched. A later successful event clears
        the earlier warning only for the rows it actually observed.
        """
        from proxy.smeta_core.vor_rows import decision_anchor
        with closing(self._connect()) as conn:
            events=conn.execute('SELECT rows_json,errors_json,evidence_json FROM smeta_portion_feedback WHERE session_id=? AND source_revision=? ORDER BY sequence DESC',
                                (session_id,source_revision)).fetchall()
        pending=set(anchors)
        rows=[]
        errors=[]
        row_errors={'missing_evidence_ref','norm_code_not_in_referenced_evidence','model_row_format_error',
                    'invalid_portion_source_row','inconsistent_portion_source_label','duplicate_source_row'}
        for event in events:
            authored=json.loads(event['rows_json'])
            evidence=json.loads(event['evidence_json'])
            shown=evidence.get('portion_shown')
            if not isinstance(shown,list):
                shown=[decision_anchor(row,source_anchors) for row in authored]
            relevant=pending.intersection(shown)
            if not relevant:continue
            pending-=relevant
            event_errors=json.loads(event['errors_json'])
            if not event_errors:continue
            rows.extend(row for row in authored if decision_anchor(row,source_anchors) in relevant)
            for error in event_errors:
                kind,_,label=str(error).partition(':')
                anchor=decision_anchor({'source_row':label},source_anchors) if kind in row_errors else ''
                if anchor and anchor not in relevant:
                    continue
                if kind in {'unknown_evidence_ref', 'duplicate_work_id'}:
                    affected = {
                        decision_anchor(row, source_anchors)
                        for row in authored
                        if (
                            label in [str(ref or '').strip().upper() for ref in (row.get('evidence_refs') or [])]
                            if kind == 'unknown_evidence_ref'
                            else label == str(row.get('work_id') or '').strip()
                        )
                    }
                    if affected and not affected.intersection(relevant):
                        continue
                if error not in errors:errors.append(error)
            if not pending:break
        return {'rows':rows,'errors':errors} if errors else None
