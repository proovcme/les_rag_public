"""Durable packet checkpoints for the active model-owned workbook path.

The store also owns the difference between "this packet was set aside" and "this
run stopped": every pause records which guard wrote it (``pause_kind``), and only
an operator stop, a cancellation or the per-run budget may stop a document —
build 823 read any pause as a stop and abandoned eight sheets of the customer's
ВОР behind two dead rows of sheet АР (blocker file
``QWEN_BLOCKERS_AFTER_823_2026-09-29.md`` § 1).  Per-sheet deferrals and the
per-locator offer history live here too, so a restarted process continues the
same queue instead of re-offering rows the model already gave up on, and a row
that was never put to the model cannot be closed as "the model produced nothing".

A chat continuation is a *research of the same document*, not a fresh document:
the question is part of the durable identity, so every «Продолжи это же задание…»
turn opened a new row that started the queue again at the first sheet (live on
build 824: 177 already-decided rows put to the model again, all 32 deferred rows
re-offered and 18 of those deferrals dropped, 275 cached queries re-issued and 277
evidence records re-derived).  :meth:`WorkbookResearchJobService.begin_or_resume`
therefore inherits a document's durable state into the next research of it —
decisions, evidence, query cache, deferrals, the held packet and the outstanding
remainder — while the run-scoped guard counters start fresh, and
:meth:`WorkbookResearchJobService.list_events_with_lineage` reads the offer ledger
across that chain instead of restarting it at zero.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from proxy.config import META_DB_PATH
from proxy.services.lsr_source_coverage_service import inferred_row_role
from proxy.services.packaging_recovery_service import (
    packaging_recovery_payload,
    workbook_document_from_events,
)

SCHEMA = "les.workbook-research-job.v1"
_PRICE_BASIS_KEY = "_price_basis"
TERMINAL_STATUSES = {"complete", "failed"}
RESUMABLE_STATUSES = {"running", "paused", "failed", "cancelled"}


def research_cache_entry(
    hits: Sequence[Mapping[str, Any]], *, cache_contract: str = "", previous: Any = None,
) -> Any:
    """Version technical retrieval results without rewriting cited evidence."""
    records = [dict(item) for item in hits if isinstance(item, Mapping)]
    if not cache_contract:
        return records
    entry = {"contract": str(cache_contract), "hits": records}
    if previous is not None:
        entry["superseded"] = [previous]
    return entry


_EXTRA_COLUMNS = {
    "task_context_json": "TEXT NOT NULL DEFAULT '{}'",
    "remaining_json": "TEXT NOT NULL DEFAULT '[]'",
    "query_cache_json": "TEXT NOT NULL DEFAULT '{}'",
    "held_packet_json": "TEXT NOT NULL DEFAULT '{}'",
    "operator_overrides_json": "TEXT NOT NULL DEFAULT '{}'",
    # Directive §4: product-internal stall guard (replaces external chain-script logic).
    # Directive §1 (22.09): the guard is split into orthogonal counters so that
    # sequential processing of *new* packets with real progress is never treated
    # as looping.  ``stall_count`` now means "consecutive packets without
    # substantive progress"; ``round_count`` is a purely informational cumulative
    # packet counter that NEVER triggers a pause; the per-run budget lives in
    # ``run_round_count`` and resets on every begin_or_resume so a paused job can
    # always be continued.  ``held_fingerprint``/``held_attempts`` bound retries
    # of the *same* deferred packet, an axis distinct from progress.
    "stall_count": "INTEGER NOT NULL DEFAULT 0",
    "round_count": "INTEGER NOT NULL DEFAULT 0",
    "stall_reason": "TEXT NOT NULL DEFAULT ''",
    "run_round_count": "INTEGER NOT NULL DEFAULT 0",
    "held_fingerprint": "TEXT NOT NULL DEFAULT ''",
    "held_attempts": "INTEGER NOT NULL DEFAULT 0",
    # Cross-resume memory of the *global* remainder.  ``stall_count`` and
    # ``held_attempts`` reset on every run, so a job whose last rows the model
    # refuses again and again pauses and resumes forever: the live customer ВОР
    # reproduced 34 identical pauses on the same five work rows (АР!R22, R23,
    # R24, R26, R49) and never reached a terminal state.  These two columns
    # remember which remainder was reported last and how many resumes in a row
    # reported the very same one.
    "stall_fingerprint": "TEXT NOT NULL DEFAULT ''",
    "stall_occurrences": "INTEGER NOT NULL DEFAULT 0",
    # Blocker file § 1 (29.09), build 823: which guard wrote the current pause.
    # ``stalled``/``held_retry_exhausted`` set a single PACKET aside; ``run_budget``,
    # ``operator`` and ``cancelled`` end the RUN.  The sheet-pass loop used to read
    # the pause itself as the stop signal, so the first hard sheet ended the whole
    # document: on the customer ВОР seven runs in a row stopped on АР and 278 of
    # the 295 outstanding rows were never put to the model at all.
    "pause_kind": "TEXT NOT NULL DEFAULT ''",
    # Durable memory of the packets that were set aside, keyed by locator.  Without
    # it a restart re-offered the same dead rows first, which is the "repeat the
    # same set without new data" the blocker forbids.  A deferral is released when
    # the job gained evidence since it was written (``evidence_watermark``) or when
    # an operator reopens the locator.
    "deferrals_json": "TEXT NOT NULL DEFAULT '{}'",
    # Blocker file § 1 (29.09), build 824: the research a continuation turn picked
    # up where this one's durable progress was inherited FROM.  A chat turn is a
    # new identity (its question is part of the digest), so without a lineage the
    # next turn re-opened the queue at the first sheet and re-offered rows the model
    # had already decided.  '' means this job is the first research of its document.
    "continues_job_id": "TEXT NOT NULL DEFAULT ''",
}

# Guard kinds that set ONE packet aside and let the run go on with the next
# sheet.  The vocabulary is deliberately short: ``record_packet`` writes
# ``stalled``/``held_retry_exhausted``/``run_budget``, ``pause`` writes
# ``run_end``/``cancelled``, ``reopen_locators`` writes ``refine`` and
# ``finish_with_declared_gaps`` writes ``starved_scheduler``/``declared_gaps_partial``.
PACKET_DEFERRAL_PAUSE_KINDS = frozenset({"stalled", "held_retry_exhausted"})


def _pause_defers_one_packet(row: sqlite3.Row) -> bool:
    """Is the stored pause only a guard setting ONE packet aside?

    The narrow, fail-closed form of the question: a pause written by older code
    (empty ``pause_kind``), by an unknown future guard, or by an operator is never
    read as "keep working".
    """

    if str(row["status"] or "") != "paused":
        return False
    keys = row.keys()
    if "pause_kind" not in keys:
        return False
    return str(row["pause_kind"] or "") in PACKET_DEFERRAL_PAUSE_KINDS


def _pause_stops_the_run(row: sqlite3.Row) -> bool:
    """Does the current pause end the run, or only set one packet aside?

    On the customer's 377-row ВОР the sheet-pass loop read the guard pause as a
    stop signal, broke out of the sheet loop at АР and left eight sheets with zero
    offers (``stage_b/live_823/b1_plateau_trace_823.json``: 278 of the 295
    outstanding rows were never put to the model).  Only a pause that names the
    single packet it gave up on lets the run go on to the next sheet.
    """

    status = str(row["status"] or "")
    if status == "cancelled" or bool(row["cancel_requested"]):
        return True
    if status != "paused":
        return False
    return not _pause_defers_one_packet(row)

# Directive §4 / §1: bounded, orthogonal stall detection thresholds.
_STALL_THRESHOLD = 2          # consecutive packets with no substantive progress
_MAX_ROUNDS = 8               # DEPRECATED as a pause trigger; kept only so the
                              # legacy ceiling value is still reportable.
# Continuable per-run budget: sized for the customer's ~386-element VOR pass so
# genuine work is never mistaken for a loop; resets on begin_or_resume.
_RUN_PACKET_BUDGET = 48       # packets within a single run before a *continuable*
                              # run_budget pause
_HELD_PACKET_MAX_ATTEMPTS = 3  # retries of the same deferred packet before it
                               # starts counting toward the stall streak
# How many times the *same* global remainder may be reported by consecutive
# resumes before the stalled rows are closed as declared gaps.  The number is
# taken from the live customer ВОР, not from taste: a healthy 12-pass run
# produced two streaks of three identical remainders (377 on passes 1-3 while
# the query cache warmed, 231 on passes 8-10 on a hard packet) and then made
# progress again, while the pathological run reported the same remainder 34
# times in a row and never reached a terminal state.  Four therefore sits above
# every observed healthy streak without excusing a real deadlock - and closing
# at the bound only removes those rows from `remaining`, it does not complete a
# document that still has sheets to work on.
STALL_TERMINAL_OCCURRENCES = 4


def stalled_resume_seconds() -> int:
    """Молчание чекпоинта, после которого `running` считается мёртвым исполнителем.

    Чат читает эту же ручку (`LES_LSR_STALLED_RESUME_SEC`, по умолчанию 20
    минут), чтобы выбрать между «Сборка продолжается» и «Сборка остановилась».
    Хранилище обязано делить ровно ту же границу, иначе два слоя разойдутся
    тем же способом, которым они расходились до сборки 810.
    """

    try:
        return max(60, int(os.getenv("LES_LSR_STALLED_RESUME_SEC", "1200") or 1200))
    except ValueError:
        return 1200


def checkpoint_age_seconds(updated_at: str, *, now: datetime | None = None) -> float:
    """Сколько секунд чекпоинт молчит (SQLite пишет наивный UTC).

    Отсутствие даты читается как «молчит вечно»: строка, у которой нет
    валидного `updated_at`, не может быть показана как живая сборка.
    """

    text = str(updated_at or "").strip()
    stamp: datetime | None = None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            stamp = datetime.strptime(text, pattern)
            break
        except ValueError:
            continue
    if stamp is None:
        try:
            stamp = datetime.fromisoformat(text.replace(" ", "T"))
        except ValueError:
            return float("inf")
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    moment = now if now is not None else datetime.now(timezone.utc).replace(tzinfo=None)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return max(0.0, (moment - stamp).total_seconds())


def remainder_fingerprint(remaining: Sequence[Any]) -> str:
    """Order-independent fingerprint of the outstanding locator set."""

    locators = sorted({str(item).strip() for item in remaining or () if str(item).strip()})
    if not locators:
        return ""
    raw = json.dumps(locators, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def declared_gap_decision(
    locator: str,
    *,
    line: str = "",
    unit: str = "",
    quantity: Any = None,
    row_classification: str = "",
    reason: str,
    attempts: int = 0,
) -> dict[str, Any]:
    """One durable position that records the ABSENCE of a model decision.

    A declared gap is bookkeeping, never a professional decision: it carries no
    norm cipher, no price and no title the source does not have.  ``title`` is
    the source row as the catalog renders it, and ``open_gap`` states in plain
    Russian that the application closed the row because the model produced no
    solution for it.  ``decision_origin='declared_gap'`` keeps it distinguishable
    from a model row everywhere the durable set is read back.
    """

    text = " ".join(str(line or "").split())
    # the document's "Строка" column is for the customer: a machine prefix such
    # as ``LOCATOR:`` must never reach it, in either the title or the locator.
    raw = str(locator or "").strip()
    if raw.upper().startswith("LOCATOR:"):
        raw = raw[len("LOCATOR:") :].strip()
    for prefix in (f"LOCATOR:{raw}:", f"{raw}:"):
        if text.upper().startswith(prefix.upper()):
            text = text[len(prefix) :].strip()
            break
    title = text
    return {
        "source_row": raw,
        "work_row": raw,
        "row_role": "unresolved",
        "title": title[:480],
        "unit": str(unit or ""),
        "quantity": quantity,
        "norm_code": "",
        "norm_status": "MISSING",
        "open_gap": str(reason or "").strip(),
        "row_classification": str(row_classification or "work"),
        "decision_origin": "declared_gap",
        "declared_after_offers": int(attempts or 0),
        "evidence_refs": [],
        "evidence_bindings": {},
    }



class WorkbookResearchJobError(ValueError):
    pass


def _decision_key(item: Mapping[str, Any]) -> tuple[str, str]:
    """One durable decision is a source locator plus its authored role."""

    locator = str(item.get("source_row") or "").strip()
    return locator, inferred_row_role(item) or "work"


_IDENTITY_DECISION_FIELDS = frozenset(
    {
        # Identity / version bookkeeping (never part of the "what did the operator
        # actually decide" content fingerprint, and never refreshed from a redelivery:
        # the durable revision chain belongs to the store, not to the answer).
        "operation_id",
        "revision",
        "revision_origin",
        "content_sha256",
    }
)
# Task 2026-09-29 § 3: these fields explain a decision that is already on the record.
# ``gap_reason`` joins them because declaring *why* a row stays open is not a new paid
# operation — and if the reader refused to refresh it, a continuation that finally
# names «нет подходящего кандидата» would be dropped as "same packet, nothing
# changed", leaving the model with a field the prompt promises and the store keeps
# nowhere.  One list feeds both the digest exclusion and the in-place refresh, so the
# prompt, the reader and the durable record cannot drift apart.
_EXPLANATORY_DECISION_FIELDS = frozenset(
    {
        # Directive 2.1: a note, evidence-ref drift or status transition does not
        # by itself introduce a new paid operation. Keeping these out of the
        # content digest lets merge_model_rag_rows dedup such redeliveries while
        # still distinguishing operations that differ in locator, role, title,
        # norm_code, unit or quantity.
        "note",
        "evidence_refs",
        "status",
        # Directive §3 (23.09): open_gap is the model's free-text explanation of a
        # remaining gap (why no norm applies), not a billable decision. When a
        # paused job resumes and the model re-proposes the same source row with the
        # same role/title/norm fields but a reworded open_gap, the digest must stay
        # stable so record_packet dedups the redelivery instead of appending a
        # duplicate durable decision for one source position.
        "open_gap",
        "gap_reason",
    }
)
_VOLATILE_DECISION_FIELDS = _IDENTITY_DECISION_FIELDS | _EXPLANATORY_DECISION_FIELDS
DECISION_REFRESH_FIELDS = tuple(sorted(_EXPLANATORY_DECISION_FIELDS))


def _decision_content_sha(item: Mapping[str, Any]) -> str:
    """Content fingerprint of one decision, ignoring identity/version bookkeeping."""

    core = {
        str(key): value
        for key, value in item.items()
        if str(key) not in _VOLATILE_DECISION_FIELDS
    }
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _packaged_price_basis(price_basis: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compact the basis one packaged revision was priced in for durable storage.

    Only what a later revision has to inherit is kept: the applied book, its
    subject and period, the human-readable label, and whether it was itself
    inherited.  A revision without a bound book stores nothing — its question is
    re-asked, never silently answered by the next pass.
    """
    if not isinstance(price_basis, Mapping):
        return {}
    book = str(price_basis.get("actual_book") or price_basis.get("pricebook") or "").strip()
    if not book:
        return {}
    region = str(
        price_basis.get("actual_region") or price_basis.get("region") or ""
    ).strip()
    quarter = str(
        price_basis.get("actual_quarter") or price_basis.get("quarter") or ""
    ).strip()
    return {
        "pricebook": book,
        "region": region,
        "quarter": quarter,
        "binding": " ".join(part for part in (region, quarter) if part).strip(),
        "match": str(price_basis.get("match") or "").strip(),
        "inherited_from": str(
            price_basis.get("inherited_from_document") or ""
        ).strip(),
    }


def _new_operation_id() -> str:
    return f"op_{uuid4().hex[:16]}"


def _legacy_operation_id(job_id: str, item: Mapping[str, Any]) -> str:
    """Stable old-record -> new-identifier mapping (never by title guessing)."""

    core = {
        str(key): value
        for key, value in item.items()
        if str(key) not in _VOLATILE_DECISION_FIELDS
    }
    raw = json.dumps(
        {"job": str(job_id), "decision": core},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "op_leg_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class WorkbookResearchIdentity:
    session_id: str
    attachment_id: str
    source_sha256: str
    dataset_ids: tuple[str, ...]
    profile_revision_id: str
    model_identity: str
    question_sha256: str

    def digest(self) -> str:
        payload = {
            "session_id": self.session_id,
            "attachment_id": self.attachment_id,
            "source_sha256": self.source_sha256,
            "dataset_ids": sorted(self.dataset_ids),
            "profile_revision_id": self.profile_revision_id,
            "model_identity": self.model_identity,
            "question_sha256": self.question_sha256,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class WorkbookResearchJobService:
    def __init__(self, db_path: Path | str = META_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workbook_research_jobs (
                    job_id TEXT PRIMARY KEY,
                    identity_hash TEXT NOT NULL UNIQUE,
                    identity_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    sheet_name TEXT NOT NULL DEFAULT '',
                    packet_json TEXT NOT NULL DEFAULT '[]',
                    accepted_rows_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    omitted_json TEXT NOT NULL DEFAULT '[]',
                    remaining_json TEXT NOT NULL DEFAULT '[]',
                    query_cache_json TEXT NOT NULL DEFAULT '{}',
                    held_packet_json TEXT NOT NULL DEFAULT '{}',
                    operator_overrides_json TEXT NOT NULL DEFAULT '{}',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS workbook_research_events (
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(job_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS workbook_research_revisions (
                    job_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    origin TEXT NOT NULL,
                    base_revision INTEGER,
                    content_sha256 TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(job_id, operation_id, revision)
                );
                """
            )
            self._ensure_columns(conn)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        existing = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(workbook_research_jobs)")
        }
        for name, spec in _EXTRA_COLUMNS.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE workbook_research_jobs ADD COLUMN {name} {spec}"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def identity(
        *,
        session_id: str,
        attachment_id: str,
        source_sha256: str,
        dataset_ids: Sequence[str],
        profile_revision_id: str,
        model_identity: str,
        question: str,
    ) -> WorkbookResearchIdentity:
        if not session_id or not attachment_id or len(source_sha256) != 64:
            raise WorkbookResearchJobError("durable workbook identity is incomplete")
        return WorkbookResearchIdentity(
            session_id=str(session_id),
            attachment_id=str(attachment_id),
            source_sha256=str(source_sha256),
            dataset_ids=tuple(sorted(str(item) for item in dataset_ids if str(item))),
            profile_revision_id=str(profile_revision_id or "factory"),
            model_identity=str(model_identity or "unknown"),
            question_sha256=hashlib.sha256(str(question).encode("utf-8")).hexdigest(),
        )

    def begin_or_resume(
        self, identity: WorkbookResearchIdentity, *, task_context: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        digest = identity.digest()
        identity_json = json.dumps(identity.__dict__, ensure_ascii=False, sort_keys=True)
        prior_elapsed = 0.0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE identity_hash=?", (digest,)
            ).fetchone()
            if row is None:
                job_id = f"wrj_{uuid4().hex}"
                conn.execute(
                    """INSERT INTO workbook_research_jobs
                    (job_id,identity_hash,identity_json,status,phase)
                    VALUES (?,?,?,'running','catalog')""",
                    (job_id, digest, identity_json),
                )
                self._append_event(conn, job_id, "started", {"schema": SCHEMA})
                # A new question over a document this app has already researched is a
                # continuation, not a fresh start: pick the durable progress up.
                inherited = self._inherit_document_progress(
                    conn, job_id=job_id, identity=identity
                )
                prior_elapsed = float(inherited.get("parent_elapsed_seconds") or 0.0)
            else:
                job_id = str(row["job_id"])
                if str(row["identity_json"]) != identity_json:
                    raise WorkbookResearchJobError("identity hash collision")
                prior_elapsed = self.elapsed_seconds_between(
                    str(row["created_at"]), str(row["updated_at"])
                )
                status = str(row["status"])
                if status in RESUMABLE_STATUSES:
                    # Directive §1: resuming starts a fresh run budget and clears
                    # the stall/retry streaks, so a job previously stopped by the
                    # old cumulative ceiling continues without immediately
                    # re-triggering a pause.  round_count stays cumulative
                    # (informational only).
                    conn.execute(
                        """UPDATE workbook_research_jobs
                        SET status='running',cancel_requested=0,
                            stall_count=0,stall_reason='',pause_kind='',
                            run_round_count=0,held_attempts=0,held_fingerprint='',
                            updated_at=CURRENT_TIMESTAMP
                        WHERE job_id=?""",
                        (job_id,),
                    )
                    self._append_event(
                        conn,
                        job_id,
                        "resumed",
                        {"from_status": status, "reset_run_budget": True},
                    )
            if task_context:
                stored = conn.execute(
                    "SELECT task_context_json FROM workbook_research_jobs WHERE job_id=?",
                    (job_id,),
                ).fetchone()
                context = _json_object(stored, "task_context_json")
                if not context.get("original_question"):
                    context["original_question"] = str(task_context.get("original_question") or "")
                # Only explicitly named dimensions replace an inherited request.
                # No default book/period and no model decision are introduced here.
                basis = dict(context.get("price_basis") or {})
                for key, value in dict(task_context.get("price_basis") or {}).items():
                    if value:
                        basis[key] = value
                context["price_basis"] = basis
                conn.execute(
                    "UPDATE workbook_research_jobs SET task_context_json=? WHERE job_id=?",
                    (json.dumps(context, ensure_ascii=False), job_id),
                )
        job = self.get(job_id)
        job["prior_elapsed_seconds"] = prior_elapsed
        return job

    def _inherit_document_progress(
        self,
        conn: sqlite3.Connection,
        *,
        job_id: str,
        identity: WorkbookResearchIdentity,
    ) -> dict[str, Any]:
        """Carry a document's durable research state into the next research of it.

        Blocker file ``QWEN_BLOCKERS_AFTER_823_2026-09-29.md`` § 1 states two rules
        together: «Состояние очереди/попыток сохранять при рестарте» and «Не повторять
        один и тот же набор без новых данных/evidence».  The sheet-pass half of both
        was fixed in 824 (a guard pause no longer ends the document, and the offer
        ledger is read from the durable checkpoints).  The live customer ВОР then
        broke the other half: «Продолжи это же задание по тому же прикреплённому
        документу.» is a different *question*, and the question digest is part of the
        job identity, so the continuation opened a new row whose queue started again
        at sheet СВОДНАЯ/АР and re-measured the document from scratch.  Measured on the
        live customer ВОР by ``stage_b/b1_continuation_lineage_probe_825.py``
        (``stage_b/live_824/b1_lineage_824_continuation.json``): of the parent's 284
        decided rows the continuation put **177 already-decided rows back to the
        model**, re-offered **all 32** rows it had deferred, dropped **18 of those 32**
        deferrals, re-issued **275** queries the document had already cached and
        re-derived **277** evidence records it already held — while its own sheet
        queue never got past СКС, short of the ЭОМ the first research had reached.

        The scope is the *document*, exactly as § 7/§ 9 already scope its price
        basis: same attachment, same source hash.  A replaced file under the same
        attachment inherits nothing, and a regenerated UI session does not lose the
        state it is continuing.  What carries is the state the scheduler reads —
        decided rows, evidence, omitted rows, the query cache, the packet still held,
        the outstanding remainder and the deferrals — while the run-scoped guard
        counters (``run_round_count``, ``stall_count``, ``held_attempts``) start
        fresh, because a continuation is a new run with a new budget.

        A deferral keeps its meaning by being re-based to the inherited evidence
        watermark: it stays set aside until *this* continuation gathers evidence the
        document had not seen, which is the "without new data" the blocker names.
        """

        parent = conn.execute(
            "SELECT * FROM workbook_research_jobs"
            " WHERE json_extract(identity_json,'$.attachment_id')=?"
            "   AND json_extract(identity_json,'$.source_sha256')=?"
            "   AND job_id<>?"
            " ORDER BY rowid DESC LIMIT 1",
            (identity.attachment_id, identity.source_sha256, str(job_id)),
        ).fetchone()
        if parent is None:
            return {}
        # A refused first model turn can have no decisions yet. Its user's price
        # request must nevertheless survive the next turn and a process restart.
        conn.execute(
            "UPDATE workbook_research_jobs SET task_context_json=? WHERE job_id=?",
            (str(parent["task_context_json"] or "{}"), str(job_id)),
        )
        accepted = _json_list(parent, "accepted_rows_json")
        evidence = _json_list(parent, "evidence_json")
        omitted = _json_list(parent, "omitted_json")
        cache = _json_object(parent, "query_cache_json")
        deferrals = _json_object(parent, "deferrals_json")
        held = _json_object(parent, "held_packet_json")
        remaining = _json_list(parent, "remaining_json")
        if not (accepted or evidence or omitted or cache or deferrals):
            # nothing was decided, cached or set aside: there is no progress to lose.
            return {}
        watermark = len(evidence) + len(cache)
        rebased: dict[str, Any] = {}
        for locator, entry in deferrals.items():
            if not isinstance(entry, Mapping):
                continue
            carried = dict(entry)
            carried["inherited_from_job"] = str(parent["job_id"])
            carried["evidence_watermark"] = watermark
            rebased[str(locator)] = carried
        conn.execute(
            """UPDATE workbook_research_jobs
            SET accepted_rows_json=?,evidence_json=?,omitted_json=?,
                query_cache_json=?,deferrals_json=?,held_packet_json=?,
                remaining_json=?,continues_job_id=?,updated_at=CURRENT_TIMESTAMP
            WHERE job_id=?""",
            (
                json.dumps(accepted, ensure_ascii=False),
                json.dumps(evidence, ensure_ascii=False),
                json.dumps(omitted, ensure_ascii=False),
                json.dumps(cache, ensure_ascii=False),
                json.dumps(rebased, ensure_ascii=False),
                json.dumps(held, ensure_ascii=False),
                json.dumps(remaining, ensure_ascii=False),
                str(parent["job_id"]),
                str(job_id),
            ),
        )
        parent_identity = _json_object(parent, "identity_json")
        payload = {
            "schema": "les.progress-inherited.v1",
            "from_job": str(parent["job_id"]),
            "parent_status": str(parent["status"] or ""),
            "parent_sheet": str(parent["sheet_name"] or ""),
            # Named apart because a continuation that carries another model's or
            # another profile's decisions across it must be visible in the trace.
            "parent_model_identity": str(parent_identity.get("model_identity") or ""),
            "parent_profile_revision_id": str(
                parent_identity.get("profile_revision_id") or ""
            ),
            "parent_question_sha256": str(parent_identity.get("question_sha256") or ""),
            "continuation_model_identity": str(identity.model_identity or ""),
            "continuation_profile_revision_id": str(identity.profile_revision_id or ""),
            "decided_rows": len(accepted),
            "evidence_records": len(evidence),
            "omitted_rows": len(omitted),
            "cached_queries": len(cache),
            "deferrals": len(rebased),
            "remaining_rows": len(remaining),
            "evidence_watermark": watermark,
            "guard_counters_reset": True,
            # The document's already-spent time belongs to the continuation's ETA:
            # a resumed run is not measured from the second this turn started.
            "parent_elapsed_seconds": self.elapsed_seconds_between(
                str(parent["created_at"] or ""), str(parent["updated_at"] or "")
            ),
        }
        self._append_event(conn, job_id, "progress_inherited", payload)
        return payload

    def lineage_job_ids(self, job_id: str) -> list[str]:
        """This research and every research of the same document it continued from.

        Oldest first, so reading the chain reads the document's history in the order
        it happened.  Bounded because the chain is walked, not indexed.
        """

        chain = [str(job_id)]
        with self._connect() as conn:
            for _ in range(32):
                row = conn.execute(
                    "SELECT continues_job_id FROM workbook_research_jobs WHERE job_id=?",
                    (chain[-1],),
                ).fetchone()
                if row is None:
                    break
                parent = str(row["continues_job_id"] or "").strip()
                if not parent or parent in chain:
                    break
                chain.append(parent)
        return list(reversed(chain))

    def list_events_with_lineage(
        self, job_id: str, event_type: str = ""
    ) -> list[dict[str, Any]]:
        """Durable events of this research *and* of the researches it continued from.

        The offer ledger and the packet attempt numbers are built from
        ``packet_checkpoint`` events.  Read per job they restart at zero on every
        continuation turn, which is the "same set offered again without new data"
        § 1 forbids; read across the lineage they keep the fairness memory of the
        document.  Every event belongs to the job that wrote it and says so here, so
        no history is duplicated or rewritten.
        """

        chain = self.lineage_job_ids(job_id)
        events: list[dict[str, Any]] = []
        for step in chain:
            for event in self.list_events(step, event_type):
                if len(chain) > 1:
                    event["job_id"] = step
                events.append(event)
        return events

    @staticmethod
    def elapsed_seconds_between(created_at: str, updated_at: str) -> float:
        """Wall time from SQLite timestamps before resume bumps updated_at."""

        def _parse(value: str) -> datetime | None:
            text = str(value or "").strip()
            if not text:
                return None
            try:
                return datetime.fromisoformat(text.replace(" ", "T"))
            except ValueError:
                return None

        start = _parse(created_at)
        end = _parse(updated_at)
        if start is None or end is None:
            return 0.0
        return max(0.0, (end - start).total_seconds())

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        job_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM workbook_research_events WHERE job_id=?",
            (job_id,),
        ).fetchone()
        sequence = int(row[0])
        conn.execute(
            """INSERT INTO workbook_research_events
            (job_id,sequence,event_type,payload_json) VALUES (?,?,?,?)""",
            (job_id, sequence, event_type, json.dumps(dict(payload), ensure_ascii=False)),
        )
        return sequence

    def list_events(
        self, job_id: str, event_type: str = ""
    ) -> list[dict[str, Any]]:
        """Durable job events, oldest first: attempt identity rebuild after restart."""

        with self._connect() as conn:
            if event_type:
                rows = conn.execute(
                    "SELECT sequence,event_type,payload_json FROM workbook_research_events"
                    " WHERE job_id=? AND event_type=? ORDER BY sequence",
                    (str(job_id), str(event_type)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT sequence,event_type,payload_json FROM workbook_research_events"
                    " WHERE job_id=? ORDER BY sequence",
                    (str(job_id),),
                ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except ValueError:
                payload = {}
            events.append(
                {
                    "sequence": int(row["sequence"]),
                    "event_type": str(row["event_type"]),
                    "payload": payload if isinstance(payload, Mapping) else {},
                }
            )
        return events

    def document_packaging_events(
        self,
        *,
        attachment_id: str,
        source_sha256: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """``workbook_packaged`` events of *this document*, across every research of it.

        A continuation is a new research of the same attachment: the durable identity
        of a job covers ``question_sha256``, so «добери нормы» opens its own ``job_id``
        while the downloadable document stays one artifact (§ 4).  Reading the basis
        out of the current job alone therefore asked the operator to choose the price
        basis again on the very next turn — build 822's live matrix on ``B0_camenka``
        recorded ``sankt-peterburg_3kv2026`` under revision 1's job and found nothing
        in the job that packaged revisions 2..5, so those files printed «Ценовая база
        не задана явно» over a document that had been priced in a book.  The document,
        not the run, owns its basis (§ 7), so this read is scoped to the document: same
        attachment, same source hash, every job that researched it, oldest event first.
        """

        aid = str(attachment_id or "").strip()
        if not aid:
            return []
        digest = str(source_sha256 or "").strip()
        limit_n = max(1, min(int(limit or 200), 500))
        ordered: list[tuple[str, int, int, dict[str, Any]]] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT rowid, job_id, identity_json FROM workbook_research_jobs"
                " ORDER BY updated_at DESC LIMIT ?",
                (limit_n,),
            ).fetchall()
            for row in rows:
                identity = json.loads(str(row["identity_json"] or "{}") or "{}")
                if not isinstance(identity, dict):
                    continue
                if str(identity.get("attachment_id") or "") != aid:
                    continue
                if digest and str(identity.get("source_sha256") or "").strip() not in {
                    "",
                    digest,
                }:
                    # the file behind this attachment was replaced: nothing a pricing
                    # of the old one decided carries over to the new one (§ 9).
                    continue
                job_id = str(row["job_id"])
                research_order = int(row["rowid"])
                for event in self._events(conn, job_id, "workbook_packaged"):
                    event["job_id"] = job_id
                    ordered.append((
                        str(event.get("created_at") or ""),
                        research_order,
                        int(event.get("sequence") or 0),
                        event,
                    ))
        # ``sequence`` restarts per research job, so the document's chronology is the
        # chronology of its events; two events written in the same second are ordered
        # by the research they belong to, oldest research first.
        ordered.sort(key=lambda item: item[:3])
        return [item[3] for item in ordered]

    def record_packaging(
        self,
        job_id: str,
        *,
        tool: str,
        revision_id: str,
        draft: bool,
        parent_revision_id: str | None = None,
        price_basis: Mapping[str, Any] | None = None,
    ) -> int:
        """Durable trace of a packaged workbook revision for this job.

        The next packaging pass reads these events to keep the downloadable
        document in one revision chain: draft revisions while the job is
        paused, the final revision once the job is terminal.

        ``price_basis`` is stored beside the lineage because it belongs to the
        same document: the region, period and book the revision was actually
        priced in.  A continuation turn that names no basis reads it back
        instead of asking the operator to choose again (task 2026-09-28 § 4).
        """
        basis = _packaged_price_basis(price_basis)
        with self._connect() as conn:
            if basis and str(tool) == "build_lsr_workbook":
                row = conn.execute(
                    "SELECT task_context_json FROM workbook_research_jobs WHERE job_id=?",
                    (str(job_id),),
                ).fetchone()
                if row is not None:
                    context = _json_object(row, "task_context_json")
                    context["price_basis"] = basis
                    conn.execute(
                        "UPDATE workbook_research_jobs SET task_context_json=? WHERE job_id=?",
                        (json.dumps(context, ensure_ascii=False), str(job_id)),
                    )
            return self._append_event(
                conn,
                str(job_id),
                "workbook_packaged",
                {
                    "tool": str(tool),
                    "revision_id": str(revision_id),
                    "draft": bool(draft),
                    "parent_revision_id": str(parent_revision_id or ""),
                    "price_basis": basis,
                },
            )

    def record_packet(
        self,
        job_id: str,
        *,
        sheet: str,
        packet_locators: Sequence[str],
        accepted_rows: Sequence[Mapping[str, Any]],
        evidence: Sequence[Mapping[str, Any]],
        omitted: Sequence[str] = (),
        remaining: Sequence[str] = (),
        held_packet: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            if str(row["status"]) in TERMINAL_STATUSES:
                return self._row(row)
            existing_rows = json.loads(str(row["accepted_rows_json"]))
            migrated = self._ensure_operation_ids(str(job_id), existing_rows)
            by_op: dict[str, dict[str, Any]] = {
                str(item["operation_id"]): item
                for item in existing_rows
                if isinstance(item, Mapping) and item.get("operation_id")
            }
            active_shas = {op: _decision_content_sha(item) for op, item in by_op.items()}
            new_revisions: list[tuple[str, int, str, dict[str, Any]]] = [
                (op, int(item.get("revision") or 1), "migration", item)
                for op, item in migrated
            ]
            for item in accepted_rows:
                if not isinstance(item, Mapping):
                    continue
                payload = dict(item)
                locator = str(payload.get("source_row") or "").strip()
                if not locator:
                    continue
                origin = str(payload.pop("revision_origin", "") or "model")
                op_id = str(payload.get("operation_id") or "").strip()
                if op_id and op_id in by_op:
                    sha = _decision_content_sha(payload)
                    if sha == active_shas.get(op_id):
                        continue
                    revision = int(by_op[op_id].get("revision") or 1) + 1
                    payload["operation_id"] = op_id
                    payload["revision"] = revision
                    by_op[op_id] = payload
                    active_shas[op_id] = sha
                    for pos, old in enumerate(existing_rows):
                        if (
                            isinstance(old, Mapping)
                            and str(old.get("operation_id") or "") == op_id
                        ):
                            existing_rows[pos] = payload
                            break
                    new_revisions.append((op_id, revision, origin, payload))
                    continue
                sha = _decision_content_sha(payload)
                if sha in active_shas.values():
                    # The identical result was delivered again; never duplicate it.
                    continue
                op_id = _new_operation_id()
                payload["operation_id"] = op_id
                payload["revision"] = 1
                existing_rows.append(payload)
                by_op[op_id] = payload
                active_shas[op_id] = sha
                new_revisions.append((op_id, 1, origin, payload))
            existing_evidence = json.loads(str(row["evidence_json"]))
            evidence_ids = {
                str(item.get("global_evidence_id") or "") for item in existing_evidence
            }
            for item in evidence:
                payload = dict(item)
                key = str(payload.get("global_evidence_id") or "")
                if key and key not in evidence_ids:
                    existing_evidence.append(payload)
                    evidence_ids.add(key)
            existing_omitted = list(json.loads(str(row["omitted_json"])))
            existing_omitted.extend(
                item for item in map(str, omitted) if item not in existing_omitted
            )
            packet = [str(item) for item in packet_locators]
            remaining_locators = [
                str(item) for item in remaining if str(item).strip()
            ]
            held_payload = dict(held_packet or {})
            for op_id, revision, origin, payload in new_revisions:
                self._insert_revision(conn, job_id, op_id, revision, origin, payload, None)
            # ─── Directive §1 (22.09): orthogonal stall / progress counters ───
            # Substantive progress is measured by *content produced by this packet*
            # (new operations or new revisions) plus rows newly resolved as omitted —
            # never by the sheet-local ``remaining`` count, which legitimately grows
            # when the pass moves to the next sheet.
            prev_stall = int(row["stall_count"] or 0) if "stall_count" in row.keys() else 0
            prev_round = int(row["round_count"] or 0) if "round_count" in row.keys() else 0
            prev_run = int(row["run_round_count"] or 0) if "run_round_count" in row.keys() else 0
            prev_held_fp = str(row["held_fingerprint"] or "") if "held_fingerprint" in row.keys() else ""
            prev_held_attempts = int(row["held_attempts"] or 0) if "held_attempts" in row.keys() else 0
            prev_omitted = _json_list(row, "omitted_json")
            newly_omitted = len(existing_omitted) - len(prev_omitted)
            previous_held = _json_object(row, "held_packet_json")
            previous_queries = list(previous_held.get("queries") or [])
            previous_offset = previous_held.get("query_offset")
            next_offset = held_payload.get("query_offset")
            delivered_queries = (
                next_offset - previous_offset
                if isinstance(previous_offset, int) and isinstance(next_offset, int)
                else 0
            )
            # A shrinking transport queue is not a professional decision and
            # not a retry. Require the exact suffix/cursor relation so an
            # unchanged or replaced query list cannot reset the stall guard.
            evidence_page_progress = bool(
                previous_queries and 0 < delivered_queries <= len(previous_queries)
                and str(previous_held.get("sheet") or "") == str(sheet)
                and list(previous_held.get("locators") or []) == packet
                and list(held_payload.get("queries") or []) == previous_queries[delivered_queries:]
            )
            progressed = bool(new_revisions) or newly_omitted > 0 or evidence_page_progress

            new_round = prev_round + 1  # informational cumulative counter only
            new_run = prev_run + 1      # per-run budget (reset by begin_or_resume)

            # Held (deferred) packet retry axis: the same deferred locators replayed
            # without progress is a *retry*, tracked separately from stalling.
            held_present = bool(held_payload.get("locators"))
            held_fp = ""
            if held_present:
                held_fp = hashlib.sha256(
                    json.dumps(
                        {
                            "sheet": str(sheet),
                            "locators": sorted(
                                str(x) for x in (held_payload.get("locators") or [])
                            ),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()[:16]
            if progressed:
                new_held_attempts = 0
            elif held_present and held_fp == prev_held_fp:
                new_held_attempts = prev_held_attempts + 1
            elif held_present:
                new_held_attempts = 0  # a new/different deferred packet restarts retries
            else:
                new_held_attempts = 0

            # Stall streak axis: consecutive packets with no substantive progress.
            if progressed:
                new_stall = 0
            elif held_present and new_held_attempts < _HELD_PACKET_MAX_ATTEMPTS:
                # A deferred packet awaiting more evidence is an in-flight retry,
                # not a stall yet; hold the streak flat rather than incrementing.
                new_stall = prev_stall
            else:
                new_stall = prev_stall + 1

            # Decide pause.  Order: genuine stall, then held retry exhaustion, then
            # the continuable per-run budget.  Finishing the last packet (nothing
            # remaining and nothing held) is NEVER a pause.
            work_outstanding = bool(remaining_locators) or held_present
            stall_reason = ""
            should_auto_pause = False
            pause_kind = ""
            # A no-progress streak is only a stall while there is still work to
            # do (locators remaining or a deferred packet held).  Reaching the end
            # with nothing outstanding is natural completion, NEVER a paused with
            # remaining=0.
            if new_stall >= _STALL_THRESHOLD and work_outstanding:
                should_auto_pause = True
                pause_kind = "stalled"
                stall_reason = (
                    f"stalled: {new_stall} consecutive packets without substantive "
                    f"progress (sheet='{sheet}' sheet_remaining="
                    f"{len(remaining_locators)}; global document remainder is "
                    f"reported on job.remaining)"
                )
            elif held_present and new_held_attempts >= _HELD_PACKET_MAX_ATTEMPTS:
                should_auto_pause = True
                pause_kind = "held_retry_exhausted"
                stall_reason = (
                    f"held_retry_exhausted: {new_held_attempts} attempts on the same "
                    f"deferred packet without progress"
                )
            elif new_run >= _RUN_PACKET_BUDGET and work_outstanding:
                should_auto_pause = True
                pause_kind = "run_budget"
                stall_reason = (
                    f"run_budget: {new_run} packets in this run (continuable; "
                    f"sheet='{sheet}' sheet_remaining={len(remaining_locators)}, "
                    f"held={held_present}; global document remainder is reported "
                    f"on job.remaining)"
                )
            new_status = "paused" if should_auto_pause else str(row["status"])
            if not should_auto_pause:
                new_phase = "packets"
                # A guard pause that only set one packet aside is not a stop.  The
                # run went on and just recorded another packet, so the durable
                # status says what is actually true — the document is being worked.
                # Leaving it "paused" would make the next per-packet guard test read
                # an unlabelled pause and abort the run at the second sheet.
                if _pause_defers_one_packet(row):
                    new_status = "running"
            elif pause_kind == "run_budget":
                new_phase = "run_budget"
            else:
                new_phase = "stalled"
            conn.execute(
                """UPDATE workbook_research_jobs
                SET status=?,phase=?,sheet_name=?,packet_json=?,accepted_rows_json=?,
                    evidence_json=?,omitted_json=?,remaining_json=?,held_packet_json=?,
                    stall_count=?,round_count=?,stall_reason=?,
                    run_round_count=?,held_fingerprint=?,held_attempts=?,pause_kind=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE job_id=?""",
                (
                    new_status,
                    new_phase,
                    str(sheet),
                    json.dumps(packet, ensure_ascii=False),
                    json.dumps(existing_rows, ensure_ascii=False),
                    json.dumps(existing_evidence, ensure_ascii=False),
                    json.dumps(existing_omitted, ensure_ascii=False),
                    json.dumps(remaining_locators, ensure_ascii=False),
                    json.dumps(held_payload, ensure_ascii=False),
                    new_stall,
                    new_round,
                    stall_reason if should_auto_pause else "",
                    new_run,
                    held_fp,
                    new_held_attempts,
                    pause_kind if should_auto_pause else "",
                    job_id,
                ),
            )
            self._append_event(
                conn,
                job_id,
                "packet_checkpoint",
                {
                    "sheet": str(sheet),
                    "packet_locators": packet,
                    "accepted_total": len(existing_rows),
                    "omitted_total": len(existing_omitted),
                    "remaining_total": len(remaining_locators),
                    "held_queries": len(held_payload.get("queries") or []),
                    "new_revisions": len(new_revisions),
                    "evidence_page_progress": evidence_page_progress,
                },
            )
            # Directive §4: emit stall event when auto-paused
            if should_auto_pause:
                self._append_event(
                    conn,
                    job_id,
                    "stall_guard_triggered",
                    {
                        "reason": stall_reason,
                        "kind": pause_kind,
                        "stall_count": new_stall,
                        "round_count": new_round,
                        "run_round_count": new_run,
                        "held_attempts": new_held_attempts,
                        "remaining_total": len(remaining_locators),
                        "threshold": _STALL_THRESHOLD,
                        "run_packet_budget": _RUN_PACKET_BUDGET,
                        "held_max_attempts": _HELD_PACKET_MAX_ATTEMPTS,
                    },
                )
        return self.get(job_id)

    @staticmethod
    def _ensure_operation_ids(
        job_id: str, rows: list[Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        """Assign missing operation ids in place; returns newly created (op, row).

        Legacy records map deterministically by content, so re-running the
        migration on unchanged rows produces the same identifiers.
        """

        created: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for pos, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                continue
            item = raw if isinstance(raw, dict) else dict(raw)
            if not isinstance(raw, dict):
                rows[pos] = item
            op = str(item.get("operation_id") or "").strip()
            if not op:
                op = _legacy_operation_id(job_id, item)
                if op in seen:
                    op = _new_operation_id()
                item["operation_id"] = op
                item["revision"] = 1
                created.append((op, item))
            elif "revision" not in item:
                item["revision"] = 1
            seen.add(op)
        return created

    @staticmethod
    def _insert_revision(
        conn: sqlite3.Connection,
        job_id: str,
        operation_id: str,
        revision: int,
        origin: str,
        decision: Mapping[str, Any],
        base_revision: int | None,
    ) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO workbook_research_revisions
            (job_id,operation_id,revision,origin,base_revision,content_sha256,decision_json)
            VALUES (?,?,?,?,?,?,?)""",
            (
                str(job_id),
                str(operation_id),
                int(revision),
                str(origin or "model"),
                None if base_revision is None else int(base_revision),
                _decision_content_sha(decision),
                json.dumps(dict(decision), ensure_ascii=False, default=str),
            ),
        )

    def record_search_cache(
        self,
        job_id: str,
        query_hits: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        context: Mapping[str, Any] | None = None,
        cache_contract: str = "",
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            if str(row["status"]) in TERMINAL_STATUSES:
                return self._row(row)
            cache = json.loads(str(row["query_cache_json"] or "{}"))
            if not isinstance(cache, dict):
                cache = {}
            added = 0
            refreshed = 0
            for query, hits in query_hits.items():
                key = str(query or "").strip()
                if not key:
                    continue
                previous = cache.get(key)
                if key in cache:
                    if not cache_contract or (
                        isinstance(previous, Mapping) and previous.get("contract") == cache_contract
                    ):
                        continue
                    refreshed += 1
                else:
                    added += 1
                cache[key] = research_cache_entry(hits, cache_contract=cache_contract, previous=previous)
            conn.execute(
                """UPDATE workbook_research_jobs
                SET query_cache_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (json.dumps(cache, ensure_ascii=False), job_id),
            )
            if added or refreshed:
                payload: dict[str, Any] = {"added": added, "cached_total": len(cache)}
                if cache_contract:
                    payload.update(cache_contract=cache_contract, refreshed=refreshed)
                for key in ("sheet", "packet_id", "locators", "queries"):
                    value = dict(context or {}).get(key)
                    if isinstance(value, (list, tuple)):
                        value = list(value)
                    if value:
                        payload[key] = value
                self._append_event(conn, job_id, "search_cache", payload)
        return self.get(job_id)

    def record_overrides(
        self,
        job_id: str,
        overlays: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        from proxy.services.lsr_source_coverage_service import _CONFIRMED_KEYS

        payload = overlays if isinstance(overlays, Mapping) else {}
        cleaned: dict[str, dict[str, Any]] = {}
        confirmation = payload.get(_PRICE_BASIS_KEY)
        if isinstance(confirmation, Mapping):
            basis_item = {
                field: confirmation[field]
                for field in ("pricebook", "note")
                if str(confirmation.get(field) or "").strip()
            }
            basis_item["confirmed_by"] = "operator"
            if basis_item:
                cleaned[_PRICE_BASIS_KEY] = basis_item
        for locator, patch in payload.items():
            key = str(locator or "").strip()
            if not key or not isinstance(patch, Mapping) or key == _PRICE_BASIS_KEY:
                continue
            item = {
                field: patch[field]
                for field in _CONFIRMED_KEYS
                if field in patch and patch.get(field) not in (None, "")
            }
            item.pop("norm_code", None)
            if item:
                cleaned[key] = item
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            existing = _json_object(row, "operator_overrides_json")
            for key, item in cleaned.items():
                current = dict(existing.get(key) or {})
                current.update(item)
                existing[key] = current
            conn.execute(
                """UPDATE workbook_research_jobs
                SET operator_overrides_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (json.dumps(existing, ensure_ascii=False), job_id),
            )
            self._append_event(
                conn,
                job_id,
                "operator_overrides",
                {"locators": sorted(cleaned)},
            )
        return self.get(job_id)

    def replace_accepted_rows(
        self,
        job_id: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Overwrite listed decisions only, as a new revision. Does not invent a cipher."""

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            existing_rows = json.loads(str(row["accepted_rows_json"]))
            self._ensure_operation_ids(str(job_id), existing_rows)
            index_by_op: dict[str, int] = {}
            index_by_key: dict[tuple[str, str], int] = {}
            for pos, item in enumerate(existing_rows):
                if not isinstance(item, Mapping):
                    continue
                op = str(item.get("operation_id") or "").strip()
                if op:
                    index_by_op[op] = pos
                key = _decision_key(item)
                if key[0]:
                    index_by_key.setdefault(key, pos)
            replaced = 0
            for item in rows:
                if not isinstance(item, Mapping):
                    continue
                payload = dict(item)
                base_revision = payload.pop("base_revision", None)
                op = str(payload.get("operation_id") or "").strip()
                pos = index_by_op.get(op) if op else None
                if pos is None:
                    key = _decision_key(payload)
                    pos = index_by_key.get(key) if key[0] else None
                if pos is None:
                    continue
                current = existing_rows[pos]
                op = str(op or current.get("operation_id") or "")
                if base_revision is not None:
                    current_revision = int(current.get("revision") or 1)
                    try:
                        wanted_base = int(base_revision)
                    except (TypeError, ValueError) as error:
                        raise WorkbookResearchJobError(
                            f"invalid base_revision for {op}: {base_revision!r}"
                        ) from error
                    if wanted_base != current_revision:
                        raise WorkbookResearchJobError(
                            f"stale revision for {op}: "
                            f"base={wanted_base} current={current_revision}"
                        )
                keep_code = current.get("norm_code")
                if "norm_code" not in payload or payload.get("norm_code") in (None, ""):
                    payload["norm_code"] = keep_code
                if not op:
                    # Pre-migration duplicate that could not carry an id: assign one now.
                    op = _new_operation_id()
                if _decision_content_sha(payload) == _decision_content_sha(current):
                    payload["operation_id"] = op
                    payload["revision"] = int(current.get("revision") or 1)
                    existing_rows[pos] = payload
                    index_by_op[op] = pos
                    continue
                revision = int(current.get("revision") or 1) + 1
                payload["operation_id"] = op
                payload["revision"] = revision
                existing_rows[pos] = payload
                index_by_op[op] = pos
                self._insert_revision(
                    conn, job_id, op, revision, "operator", payload, revision - 1
                )
                replaced += 1
            conn.execute(
                """UPDATE workbook_research_jobs
                SET accepted_rows_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (json.dumps(existing_rows, ensure_ascii=False), job_id),
            )
            self._append_event(
                conn, job_id, "rows_replaced", {"replaced": replaced}
            )
        return self.get(job_id)

    def record_revision(
        self,
        job_id: str,
        *,
        operation_id: str,
        decision: Mapping[str, Any],
        origin: str = "operator",
        base_revision: int | None = None,
    ) -> dict[str, Any]:
        """Append one revision of an existing operation.

        ``base_revision`` guards a late request against overwriting a newer
        revision; a mismatch is rejected instead of silently clobbering.
        """

        op = str(operation_id or "").strip()
        if not op:
            raise WorkbookResearchJobError("operation_id is required")
        payload = dict(decision)
        origin_text = str(payload.pop("revision_origin", "") or origin or "operator")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            existing_rows = json.loads(str(row["accepted_rows_json"]))
            self._ensure_operation_ids(str(job_id), existing_rows)
            pos = next(
                (
                    index
                    for index, item in enumerate(existing_rows)
                    if isinstance(item, Mapping)
                    and str(item.get("operation_id") or "") == op
                ),
                None,
            )
            if pos is None:
                raise WorkbookResearchJobError(f"unknown operation_id {op}")
            current = existing_rows[pos]
            revision = int(current.get("revision") or 1)
            if base_revision is not None and int(base_revision) != revision:
                raise WorkbookResearchJobError(
                    f"stale revision for {op}: base={int(base_revision)} current={revision}"
                )
            payload["operation_id"] = op
            payload["revision"] = revision + 1
            existing_rows[pos] = payload
            conn.execute(
                """UPDATE workbook_research_jobs
                SET accepted_rows_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (json.dumps(existing_rows, ensure_ascii=False), job_id),
            )
            self._insert_revision(
                conn, job_id, op, revision + 1, origin_text, payload, revision
            )
            self._append_event(
                conn,
                job_id,
                "decision_revision",
                {"operation_id": op, "revision": revision + 1, "origin": origin_text},
            )
        return self.get(job_id)

    def list_revisions(
        self, job_id: str, operation_id: str = ""
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if operation_id:
                rows = conn.execute(
                    """SELECT * FROM workbook_research_revisions
                    WHERE job_id=? AND operation_id=? ORDER BY revision""",
                    (str(job_id), str(operation_id)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM workbook_research_revisions
                    WHERE job_id=? ORDER BY operation_id, revision""",
                    (str(job_id),),
                ).fetchall()
        return [
            {
                "operation_id": str(item["operation_id"]),
                "revision": int(item["revision"]),
                "origin": str(item["origin"]),
                "base_revision": item["base_revision"],
                "content_sha256": str(item["content_sha256"]),
                "created_at": str(item["created_at"]),
                "decision": json.loads(str(item["decision_json"])),
            }
            for item in rows
        ]

    def reopen_locators(
        self,
        job_id: str,
        locators: Sequence[str],
        *,
        chat_review: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Remove listed rows from accepted decisions and return them to remaining."""

        wanted = [str(item).strip() for item in locators if str(item).strip()]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            existing_rows = json.loads(str(row["accepted_rows_json"]))
            kept = [
                item
                for item in existing_rows
                if str(item.get("source_row") or "") not in wanted
            ]
            remaining = _json_list(row, "remaining_json")
            for locator in wanted:
                if locator not in remaining:
                    remaining.append(locator)
            overlays = _json_object(row, "operator_overrides_json")
            if chat_review is None:
                for locator in wanted:
                    overlays.pop(locator, None)
            # An operator who reopens a row also lifts the packet deferral that
            # had set it aside; otherwise the next run would skip the very row the
            # operator asked to revisit.
            deferrals = _json_object(row, "deferrals_json")
            released = [locator for locator in wanted if locator in deferrals]
            for locator in released:
                deferrals.pop(locator, None)
            conn.execute(
                """UPDATE workbook_research_jobs
                SET status='paused',phase='refine',accepted_rows_json=?,remaining_json=?,
                    operator_overrides_json=?,deferrals_json=?,
                    pause_kind='refine',cancel_requested=0,
                    stall_fingerprint='',stall_occurrences=0,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=?""",
                (
                    json.dumps(kept, ensure_ascii=False),
                    json.dumps(remaining, ensure_ascii=False),
                    json.dumps(overlays, ensure_ascii=False),
                    json.dumps(deferrals, ensure_ascii=False),
                    job_id,
                ),
            )
            self._append_event(
                conn,
                job_id,
                "locators_reopened",
                {
                    "locators": wanted, "accepted_total": len(kept),
                    **({
                        "chat_review": dict(chat_review),
                        "prior_rows": [item for item in existing_rows if str(item.get("source_row") or "") in wanted],
                    } if chat_review is not None else {}),
                },
            )
        return self.get(job_id)

    def pause(
        self,
        job_id: str,
        *,
        remaining: Sequence[str] | None = None,
        held_packet: Mapping[str, Any] | None = None,
        phase: str = "paused",
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            if str(row["status"]) in TERMINAL_STATUSES:
                return self._row(row)
            remaining_locators = (
                [str(item) for item in remaining if str(item).strip()]
                if remaining is not None
                else _json_list(row, "remaining_json")
            )
            held_payload = (
                dict(held_packet)
                if held_packet is not None
                else _json_object(row, "held_packet_json")
            )
            keys = row.keys()
            fingerprint = remainder_fingerprint(remaining_locators)
            previous_fingerprint = (
                str(row["stall_fingerprint"] or "") if "stall_fingerprint" in keys else ""
            )
            previous_occurrences = (
                int(row["stall_occurrences"] or 0) if "stall_occurrences" in keys else 0
            )
            # The same remainder reported by consecutive resumes is the loop the
            # per-run counters cannot see; anything else (progress, a different
            # sheet, an operator reopen) restarts the count from one.
            if not fingerprint:
                occurrences = 0
            elif fingerprint == previous_fingerprint:
                occurrences = previous_occurrences + 1
            else:
                occurrences = 1
            conn.execute(
                """UPDATE workbook_research_jobs
                SET status='paused',phase=?,cancel_requested=0,remaining_json=?,
                    held_packet_json=?,stall_fingerprint=?,stall_occurrences=?,
                    pause_kind=?,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=?""",
                (
                    str(phase),
                    json.dumps(remaining_locators, ensure_ascii=False),
                    json.dumps(held_payload, ensure_ascii=False),
                    fingerprint,
                    occurrences,
                    "cancelled" if str(phase) == "cancelled" else "run_end",
                    job_id,
                ),
            )
            self._append_event(
                conn,
                job_id,
                "paused",
                {
                    "remaining_total": len(remaining_locators),
                    "held_queries": len(held_payload.get("queries") or []),
                    "remainder_fingerprint": fingerprint,
                    "remainder_repeats": occurrences,
                    "terminal_bound": STALL_TERMINAL_OCCURRENCES,
                },
            )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE workbook_research_jobs
                SET cancel_requested=1,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=? AND status NOT IN ('complete','failed')""",
                (job_id,),
            ).rowcount
            if changed:
                self._append_event(conn, job_id, "cancel_requested", {})
        return self.get(job_id)

    def should_cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if bool(job.get("cancel_requested")):
            return True
        return str(job.get("status") or "") in {"paused", "cancelled"}

    def run_should_stop(self, job_id: str) -> bool:
        """Whether the sheet-pass run in progress must end right now.

        This is a narrower question than :meth:`should_cancel`, which every other
        surface keeps using to ask "is this job no longer being worked" (a paused
        job is, from outside).  Inside the run, the product-internal stall guard
        pauses the record for ONE packet while the rest of the document still
        deserves work: on the live customer ВОР the run read the pause as a stop,
        broke out of the sheet loop at АР and left eight sheets with zero offers
        (``stage_b/live_823/b1_plateau_trace_823.json``: 278 of 295 outstanding
        rows were never put to the model).  Only the per-run budget, an operator
        stop and a cancellation end the run.
        """

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (str(job_id),)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            return _pause_stops_the_run(row)

    def defer_locators(
        self,
        job_id: str,
        *,
        sheet: str,
        locators: Sequence[str],
        reason: str,
        offers: int = 0,
    ) -> dict[str, Any]:
        """Set rows aside durably so a restart does not start from them again.

        The deferral remembers how much evidence the job held when it was written.
        A later run that gained evidence (a new card, a new cached query) releases
        it, because the blocker's rule is "do not repeat the same set without new
        data", not "never revisit a hard row".
        """

        wanted = [str(item).strip() for item in locators if str(item).strip()]
        if not wanted:
            return self.get(job_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (str(job_id),)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            if str(row["status"]) in TERMINAL_STATUSES:
                return self._row(row)
            deferrals = _json_object(row, "deferrals_json")
            watermark = self._evidence_watermark(row)
            for locator in wanted:
                deferrals[locator] = {
                    "sheet": str(sheet or ""),
                    "reason": str(reason or ""),
                    "offers": int(offers or 0),
                    "evidence_watermark": watermark,
                }
            conn.execute(
                """UPDATE workbook_research_jobs
                SET deferrals_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (json.dumps(deferrals, ensure_ascii=False), str(job_id)),
            )
            self._append_event(
                conn,
                job_id,
                "locators_deferred",
                {
                    "schema": "les.packet-deferral.v1",
                    "sheet": str(sheet or ""),
                    "locators": wanted,
                    "count": len(wanted),
                    "reason": str(reason or ""),
                    "offers": int(offers or 0),
                    "evidence_watermark": watermark,
                },
            )
        return self.get(job_id)

    def still_deferred(
        self,
        job_id: str,
        *,
        sheet: str,
        release_on_new_evidence: bool = True,
    ) -> list[str]:
        """Rows of ``sheet`` that a previous run set aside and that stay aside.

        Released when the job has gained evidence since the deferral (or when the
        caller passes ``release_on_new_evidence=False``); an operator reopen of the
        locator clears it outright in :meth:`reopen_locators`.
        """

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (str(job_id),)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            deferrals = _json_object(row, "deferrals_json")
            if not deferrals:
                return []
            watermark = self._evidence_watermark(row)
            wanted_sheet = str(sheet or "")
            held: list[str] = []
            released: list[str] = []
            for locator, entry in list(deferrals.items()):
                if not isinstance(entry, Mapping):
                    continue
                if str(entry.get("sheet") or "") != wanted_sheet:
                    continue
                before = int(entry.get("evidence_watermark") or 0)
                if release_on_new_evidence and watermark > before:
                    released.append(locator)
                    continue
                held.append(locator)
            if released:
                for locator in released:
                    deferrals.pop(locator, None)
                conn.execute(
                    """UPDATE workbook_research_jobs
                    SET deferrals_json=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                    (json.dumps(deferrals, ensure_ascii=False), str(job_id)),
                )
                self._append_event(
                    conn,
                    job_id,
                    "deferrals_released",
                    {
                        "schema": "les.packet-deferral.v1",
                        "sheet": wanted_sheet,
                        "locators": sorted(released),
                        "count": len(released),
                        "evidence_watermark": watermark,
                        "because": "новое evidence с момента отложения",
                    },
                )
        return sorted(held)

    @staticmethod
    def _evidence_watermark(row: sqlite3.Row) -> int:
        """Monotone "has the job seen anything new" marker: cards + cached queries."""

        evidence = _json_list(row, "evidence_json")
        cache = _json_object(row, "query_cache_json")
        return len(evidence) + len(cache)

    def finish(self, job_id: str, *, status: str, phase: str = "complete") -> dict[str, Any]:
        if status == "cancelled":
            return self.pause(job_id, phase="cancelled")
        if status not in TERMINAL_STATUSES:
            raise WorkbookResearchJobError("invalid terminal status")
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE workbook_research_jobs
                SET status=?,phase=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
                (status, str(phase), job_id),
            ).rowcount
            if not changed:
                raise WorkbookResearchJobError("workbook research job not found")
            self._append_event(conn, job_id, status, {"phase": str(phase)})
        return self.get(job_id)

    def finish_with_declared_gaps(
        self,
        job_id: str,
        *,
        gap_rows: Sequence[Mapping[str, Any]],
        reason: str = "",
        attempts: int = 0,
        offers_by_locator: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        """Close the rows no model offer ever produced, without lying about the rest.

        This is the terminal half of the stall bound.  It never touches an
        accepted model decision: a locator that already has any role keeps it,
        and only the locators with NO decision at all are appended, through
        :func:`declared_gap_decision`, as positions that state the absence of a
        solution.

        ``offers_by_locator`` is the durable per-row offer ledger (derived from
        ``packet_checkpoint`` events).  When it is supplied, a row the model was
        never asked about is NOT closed with the sentence "the model produced no
        solution after N offers" - that cause would be a lie about a row that
        never reached the model, and declaring it would let a scheduler defect
        masquerade as a finished document.  Such rows stay in ``remaining``, the
        job stays resumable with ``pause_kind='starved_scheduler'``, and the count
        is reported in the ``gaps_declared`` event and on ``stall_guard``.

        Whether the job also becomes ``complete`` depends on the *global*
        remainder, not on the stalled sheet.  On the live customer ВОР a pass
        stalls on two dead rows of АР while six whole sheets (200 work rows) have
        not been offered yet; completing there would have told the customer the
        document was finished.  So the stalled locators leave ``remaining`` for
        good - the model is never asked about them again, which is what breaks
        the loop - and the job only reaches ``complete`` / phase ``declared_gaps``
        when nothing is left, which is the state the caller packages the final
        workbook from with no further model call.  Reporting stays honest either
        way because a declared row carries no cipher and no price and the
        readiness projection counts them separately as ``declared_gaps``.
        """

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (str(job_id),)
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            existing_rows = json.loads(str(row["accepted_rows_json"]))
            self._ensure_operation_ids(str(job_id), existing_rows)

            def _plain(item: Mapping[str, Any]) -> str:
                # both sides of the "already decided?" test are normalised the
                # same way, so a ``LOCATOR:`` spelling cannot smuggle in a
                # duplicate position for a row the model already answered.
                text = str(item.get("source_row") or "").strip()
                if text.upper().startswith("LOCATOR:"):
                    text = text[len("LOCATOR:"):].strip()
                return text.upper()

            def _offer_of(locator: str) -> int | None:
                if offers_by_locator is None:
                    return None
                text = str(locator or "").strip()
                if text.upper().startswith("LOCATOR:"):
                    text = text[len("LOCATOR:"):].strip()
                for key, value in offers_by_locator.items():
                    if str(key).strip().upper() == text.upper():
                        return int(value or 0)
                return 0

            decided = {
                _plain(item)
                for item in existing_rows
                if isinstance(item, Mapping) and _plain(item)
            }
            declared: list[dict[str, Any]] = []
            unoffered: list[str] = []
            for raw in gap_rows or ():
                if not isinstance(raw, Mapping):
                    continue
                payload = dict(raw)
                locator = str(payload.get("source_row") or "").strip()
                if not locator or _plain(payload) in decided:
                    continue
                if _offer_of(locator) == 0:
                    # Never put to the model: a technical gap of the scheduler,
                    # not a professional verdict, and it keeps the job resumable.
                    unoffered.append(locator)
                    continue
                payload["operation_id"] = _new_operation_id()
                payload["revision"] = 1
                payload["revision_origin"] = "declared_gap"
                decided.add(_plain(payload))
                existing_rows.append(payload)
                declared.append(payload)
                self._insert_revision(
                    conn, str(job_id), payload["operation_id"], 1, "declared_gap", payload, None
                )
            closed = {_plain(item) for item in declared}
            kept_open = {str(item).replace("LOCATOR:", "").strip().upper() for item in unoffered}
            still_open = [
                str(loc)
                for loc in _json_list(row, "remaining_json")
                if str(loc).strip()
                and str(loc).replace("LOCATOR:", "").strip().upper() not in closed
                and str(loc).replace("LOCATOR:", "").strip().upper() not in kept_open
            ] + [str(loc) for loc in unoffered]
            completed = not still_open
            phase = "declared_gaps" if (declared and completed) else (
                "research_complete" if completed else "packets"
            )
            pause_kind = "" if completed else (
                "starved_scheduler" if unoffered else "declared_gaps_partial"
            )
            conn.execute(
                """UPDATE workbook_research_jobs
                SET status=?,phase=?,accepted_rows_json=?,remaining_json=?,
                    stall_count=0,stall_reason='',stall_fingerprint='',
                    stall_occurrences=0,run_round_count=0,held_attempts=0,
                    held_packet_json='{}',pause_kind=?,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=?""",
                (
                    "complete" if completed else "paused",
                    phase,
                    json.dumps(existing_rows, ensure_ascii=False),
                    json.dumps(still_open, ensure_ascii=False),
                    pause_kind,
                    str(job_id),
                ),
            )
            if declared:
                self._append_event(
                    conn,
                    job_id,
                    "gaps_declared",
                    {
                        "schema": "les.declared-gaps.v1",
                        "locators": [item["source_row"] for item in declared],
                        "count": len(declared),
                        "offers": int(attempts or 0),
                        "reason": str(reason or ""),
                        "decision_author": "application",
                        "model_called": False,
                        "job_completed": completed,
                        "still_remaining": len(still_open),
                        # Fail-closed visibility: rows the loop never reached are
                        # reported apart and do NOT count toward completion.
                        "unoffered_open": len(unoffered),
                        "unoffered_locators": [str(item) for item in unoffered][:80],
                    },
                )
            if completed:
                self._append_event(
                    conn,
                    job_id,
                    "complete",
                    {"phase": phase, "declared_gaps": len(declared)},
                )
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workbook_research_jobs WHERE job_id=?", (str(job_id),)
            ).fetchone()
            events = self._events(conn, str(job_id), "workbook_packaged")
        if row is None:
            # An unknown id is the documented "not found" answer, not a crash:
            # callers probe several durable databases and skip the ones that do
            # not hold this job.
            raise WorkbookResearchJobError("workbook research job not found")
        job = self._row(row)
        job["document"] = workbook_document_from_events(
            events, status=str(job.get("status") or "")
        )
        # ADR-16 § 7 asks every surface for the same basis; § 10 for one state.
        # The job answers with the basis its own packaged document carries.
        basis = job["document"].get("price_basis")
        job["price_basis"] = dict(basis) if isinstance(basis, Mapping) else {}
        if job["document"]["needs_document"]:
            job["document_recovery"] = packaging_recovery_payload(job, job["document"])
        return job

    def document_state(self, job_id: str) -> dict[str, Any]:
        """Durable answer to "does this finished job already have its file?".

        Read from the job's own ``workbook_packaged`` events, so a process
        restart or an SSE detach cannot lose it: ``state='pending'`` means the
        model decision is saved and terminal while the document was never
        packaged, which is exactly the case the interface must repair without
        starting a new research.
        """

        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM workbook_research_jobs WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
            if row is None:
                raise WorkbookResearchJobError("workbook research job not found")
            events = self._events(conn, str(job_id), "workbook_packaged")
        return workbook_document_from_events(
            events, status=str(row["status"] or "")
        )

    @staticmethod
    def _events(
        conn: sqlite3.Connection, job_id: str, event_type: str
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT sequence,event_type,payload_json,created_at FROM workbook_research_events"
            " WHERE job_id=? AND event_type=? ORDER BY sequence",
            (str(job_id), str(event_type)),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except ValueError:
                payload = {}
            events.append(
                {
                    "sequence": int(row["sequence"]),
                    "event_type": str(row["event_type"]),
                    # the moment the event itself was written: a document read that
                    # spans researches orders by this, because ``sequence`` restarts
                    # per job and a research created in the same second as its
                    # predecessor would otherwise sort by the wrong clock.
                    "created_at": str(row["created_at"] or ""),
                    "payload": payload if isinstance(payload, Mapping) else {},
                }
            )
        return events

    def list_active(
        self,
        *,
        session_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Running sheet-pass checkpoints, newest first.

        Session match is preferred after a UI restart; if the NiceGUI session
        was regenerated, the newest running job is still returned so overnight
        progress is not blank — but only while its checkpoint is actually fresh,
        because a stale `running` row belongs to a dead executor and must not be
        adopted by a chat that never started it.
        """

        limit_n = max(1, min(int(limit or 20), 100))
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM workbook_research_jobs
                   WHERE status='running'
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (limit_n,),
            ).fetchall()
        jobs = [self._row(row) for row in rows]
        sid = str(session_id or "").strip()
        if not sid:
            return jobs
        matched = [
            job
            for job in jobs
            if str((job.get("identity") or {}).get("session_id") or "") == sid
        ]
        if matched:
            return matched
        # Фallback «самая свежая running-строка любой сессии» существует ради
        # ночной сборки: NiceGUI пересоздаёт session_id, и чат без него открывался
        # пустым там, где работа реально шла. Но ровно тот же fallback притаскивал
        # в *новый* чат мёртвую строку `running`, которую исполнитель оставил 66
        # часов назад: заказчик открывал новый чат и видел «Сборка остановилась»
        # с кнопкой «Продолжить» на чужое задание («В новом чате… криво
        # отражается все»). Поэтому чужое задание принимается только пока его
        # чекпоинт действительно живой — ту же границу задаёт
        # `stalled_resume_seconds`.
        return [
            job
            for job in jobs
            if checkpoint_age_seconds(str(job.get("updated_at") or ""))
            <= stalled_resume_seconds()
        ]

    def latest(
        self,
        *,
        session_id: str = "",
        attachment_id: str = "",
        limit: int = 200,
    ) -> dict[str, Any] | None:
        """Newest research of a session or source, in *any* status.

        ``list_active``/``list_open`` hide terminal jobs, which is right for
        progress reconnect but wrong for the question "does this session
        already have a finished research and its document?".  Matching on the
        durable identity lets a regenerated UI session still find the job.
        """

        sid = str(session_id or "").strip()
        aid = str(attachment_id or "").strip()
        if not sid and not aid:
            return None
        limit_n = max(1, min(int(limit or 200), 500))
        found: sqlite3.Row | None = None
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workbook_research_jobs"
                " ORDER BY updated_at DESC LIMIT ?",
                (limit_n,),
            ).fetchall()
            for row in rows:
                identity = json.loads(str(row["identity_json"] or "{}") or "{}")
                identity = identity if isinstance(identity, dict) else {}
                if sid and str(identity.get("session_id") or "") != sid:
                    continue
                if aid and str(identity.get("attachment_id") or "") != aid:
                    continue
                found = row
                events = self._events(conn, str(row["job_id"]), "workbook_packaged")
                break
        if found is None:
            return None
        job = self._row(found)
        job["document"] = workbook_document_from_events(
            events, status=str(job.get("status") or "")
        )
        basis = job["document"].get("price_basis")
        job["price_basis"] = dict(basis) if isinstance(basis, Mapping) else {}
        if job["document"]["needs_document"]:
            job["document_recovery"] = packaging_recovery_payload(job, job["document"])
        return job

    def list_open(
        self,
        *,
        session_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Running sheet-pass first; paused draft of the same session otherwise."""

        limit_n = max(1, min(int(limit or 20), 100))
        sid = str(session_id or "").strip()
        with self._connect() as conn:

            def _fetch(status: str, session: str) -> list[dict[str, Any]]:
                if session:
                    rows = conn.execute(
                        """SELECT * FROM workbook_research_jobs
                           WHERE status=? AND json_extract(identity_json,'$.session_id')=?
                           ORDER BY updated_at DESC LIMIT ?""",
                        (status, session, limit_n),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT * FROM workbook_research_jobs
                           WHERE status=? ORDER BY updated_at DESC LIMIT ?""",
                        (status, limit_n),
                    ).fetchall()
                return [self._row(row) for row in rows]

            running = _fetch("running", sid)
            if running:
                return running
            paused = _fetch("paused", sid)
            if paused:
                return paused
        return self.list_active(session_id=session_id, limit=limit)

    def events_after(self, job_id: str, sequence: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT sequence,event_type,payload_json,created_at
                FROM workbook_research_events
                WHERE job_id=? AND sequence>? ORDER BY sequence""",
                (str(job_id), max(0, int(sequence))),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "event": str(row["event_type"]),
                "data": json.loads(str(row["payload_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        accepted_rows = json.loads(str(row["accepted_rows_json"]))
        omitted = json.loads(str(row["omitted_json"]))
        missing = sum(
            1
            for item in accepted_rows
            if not str(item.get("norm_code") or "").strip()
            or str(item.get("norm_code") or "").strip().casefold()
            in {"missing", "нет", "не найдено"}
        )
        ambiguous = sum(
            1
            for item in accepted_rows
            if str(item.get("row_classification") or "") == "ambiguous"
        )
        status = str(row["status"])
        remaining = _json_list(row, "remaining_json")
        query_cache = _json_object(row, "query_cache_json")
        held_packet = _json_object(row, "held_packet_json")
        operator_overrides = _json_object(row, "operator_overrides_json")
        identity = json.loads(str(row["identity_json"] or "{}"))
        return {
            "schema": SCHEMA,
            "job_id": str(row["job_id"]),
            # Which research of the same document this one continued from ('' when it
            # is the first).  Reported so a continuation never looks like fresh work.
            "continues_job_id": (
                str(row["continues_job_id"] or "")
                if "continues_job_id" in row.keys()
                else ""
            ),
            "status": status,
            "phase": str(row["phase"]),
            "sheet": str(row["sheet_name"]),
            "packet_locators": json.loads(str(row["packet_json"])),
            "accepted_rows": accepted_rows,
            "evidence": json.loads(str(row["evidence_json"])),
            "omitted": omitted,
            "remaining": remaining,
            "query_cache": query_cache,
            "held_packet": held_packet,
            "operator_overrides": operator_overrides,
            "task_context": _json_object(row, "task_context_json"),
            "identity": identity if isinstance(identity, dict) else {},
            "resumable": status in RESUMABLE_STATUSES and status != "failed",
            "status_dimensions": {
                "processed": len(accepted_rows),
                "omitted": len(omitted),
                "ambiguous": ambiguous,
                "missing": missing,
                "remaining": len(remaining),
                "cached_queries": len(query_cache),
                "operations": len(
                    {
                        str(item.get("operation_id"))
                        for item in accepted_rows
                        if isinstance(item, Mapping) and item.get("operation_id")
                    }
                ),
                "completeness": (
                    "full"
                    if status == "complete" and not omitted and not remaining
                    else "partial"
                ),
            },
            "cancel_requested": bool(row["cancel_requested"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            # Directive §4: stall guard visibility in API response
            "stall_guard": {
                # Directive §2: the stall reason counts the SHEET-LOCAL tail of
                # this sheet; `remaining`/`status_dimensions.remaining` is the
                # GLOBAL document remainder.  Expose the sheet so the two are
                # never conflated under one label.
                "sheet": str(row["sheet_name"]),
                "remaining_scope": "sheet_local_in_reason_global_in_remaining",
                "stall_count": int(row["stall_count"] or 0) if "stall_count" in row.keys() else 0,
                "round_count": int(row["round_count"] or 0) if "round_count" in row.keys() else 0,
                "run_round_count": int(row["run_round_count"] or 0) if "run_round_count" in row.keys() else 0,
                "held_attempts": int(row["held_attempts"] or 0) if "held_attempts" in row.keys() else 0,
                "reason": str(row["stall_reason"] or "") if "stall_reason" in row.keys() else "",
                # Which guard wrote the current pause: a packet set aside is not a
                # run that stopped, and the two must never share one label here.
                "pause_kind": (
                    str(row["pause_kind"] or "") if "pause_kind" in row.keys() else ""
                ),
                "run_stops": _pause_stops_the_run(row),
                "deferred_locators": len(
                    _json_object(row, "deferrals_json") if "deferrals_json" in row.keys() else {}
                ),
                "threshold": _STALL_THRESHOLD,
                "run_packet_budget": _RUN_PACKET_BUDGET,
                "held_max_attempts": _HELD_PACKET_MAX_ATTEMPTS,
                # Cross-resume bound: how many resumes in a row reported the very
                # same GLOBAL remainder.  The per-run counters above reset on every
                # resume, so without this a job whose last rows the model keeps
                # refusing pauses and resumes forever and never reaches a terminal
                # state the customer can download.
                "remainder_fingerprint": (
                    str(row["stall_fingerprint"] or "")
                    if "stall_fingerprint" in row.keys()
                    else ""
                ),
                "remainder_repeats": (
                    int(row["stall_occurrences"] or 0)
                    if "stall_occurrences" in row.keys()
                    else 0
                ),
                "terminal_bound": STALL_TERMINAL_OCCURRENCES,
            },
        }


def _json_list(row: sqlite3.Row, name: str) -> list[Any]:
    try:
        payload = json.loads(str(row[name] or "[]"))
    except (KeyError, json.JSONDecodeError, TypeError):
        return []
    return list(payload) if isinstance(payload, list) else []


def _json_object(row: sqlite3.Row, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(row[name] or "{}"))
    except (KeyError, json.JSONDecodeError, TypeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}
