"""Где остановился разбор длинной ведомости.

ЗАЧЕМ. Ведомость закрывается за несколько проходов, и следующий обязан знать, что уже
решено. Раньше для этого читалось поле `phase` контрольной точки инструмента — и это
было неверно: `phase` описывает стадию самого инструмента, у новой точки она `started`.
Свежая незавершённая точка становилась последней и прятала подтверждённый прогресс,
после чего проход возвращал первые строки заново (ревью Codex 10.09, R4).

ЧТО ЗДЕСЬ. Отдельное состояние прохода: ревизия источника, якоря закрытых строк, число
проходов и ревизия собранной книги. Записывается по завершённым решениям модели, а не
по последней показанной строке: внутри порции часть позиций может остаться без нормы,
и считать её закрытой значит потерять их молча.

Порядок строк здесь неизвестен, поэтому курсор считается там, где есть ведомость
(`portion_plan_service.continuous_cursor`). Хранилище отвечает на один вопрос: какие
якоря закрыты.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA = "les.smeta.portion-progress.v1"

# Threshold only labels repeated failures for diagnostics.
# It never confirms a row or removes it from subsequent portions (T119.7).
MAX_ATTEMPTS = 2

# Persisted names remain compatible: exhausted means repeated unresolved attempts.
STATE_OPEN = "open"
STATE_DECIDED = "decided"
STATE_EXHAUSTED = "exhausted"

# Change when calculation/review semantics invalidate previously built artifacts.
# It does not rewrite saved model decisions or old artifact identifiers.
CALCULATION_CONTRACT_REVISION = "smeta-price-card-name-export-v5"


# Поля решения, от которых зависит книга. Коэффициент входит: он меняет расчёт, а
# отпечаток обязан это замечать (ревью Codex 11.09).
# `title` входит намеренно: расчёт берёт из наименования недостающий множитель —
# длину бухты, габариты изделия. Смена «(305 м)» на «(500 м)» меняет результат
# расчёта с 366 на 600, и книга обязана считаться устаревшей (ревью Codex 11.09).
# Вид решения и ссылка на работу хранятся наравне с шифром: без них «входит в стоимость
# монтажа» не переживает проход и в книге неотличимо от пропущенной строки.
DECISION_FIELDS = (
    "normative_identity", "normative_identity_status", "normative_identity_refs", "normative_identity_conflicts",
    "resource_review_ref", "resource_review_status", "nr_sp_rule_id",
    "work_id", "operation", "not_covered", "coefficient_basis", "coefficient_target",
    "source_row", "norm_code", "quantity", "unit", "coefficient", "analogue", "title",
    "decision_kind", "included_in", "coverage",
    "resource_action", "resource_code", "target_resource_code", "target_resource_id", "resource_name",
    "resource_quantity", "resource_unit", "price_source_ref", "replaced_by",
    "conversion_factor", "conversion_unit", "conversion_source",
    "parse_error", "raw_cells", "raw_header", "evidence_error",
)


def canonical_decision(row: Mapping[str, Any]) -> dict[str, Any]:
    """Решение в том виде, в каком оно влияет на книгу.

    Одно представление на всех: и для отпечатка сохранённой ревизии, и для отпечатка
    того, из чего книга собрана. Две разные нормализации расходились по ключам —
    сохранённое решение шло под якорем «S!1», а упакованное под номером «1», — и
    только что собранная книга сразу числилась устаревшей.
    """
    if isinstance(row.get("operations"), list):
        return {"source_row": row.get("source_row"),
                "operations": [canonical_decision(op) for op in row["operations"]]}
    return {key: row.get(key) for key in DECISION_FIELDS}


def document_price_basis_identity(basis: Mapping[str, Any] | None) -> dict | None:
    """Semantic pricing identity; location and packet receipts are not choices."""
    if basis is None:
        return None
    return {key: basis.get(key) for key in ('schema', 'status', 'identity')}


def decisions_revision(decisions: Any, *, document_price_basis: Mapping[str, Any] | None = None) -> str:
    """Отпечаток набора решений — то, из чего собрана книга.

    Принимает и словарь по якорям, и последовательность строк: ключи в отпечаток не
    входят вовсе, порядок задаётся номером строки ведомости. Поэтому одно и то же
    решение даёт один отпечаток, как бы его ни передали.

    Книга считается устаревшей, когда её отпечаток не совпадает с текущим. Простой
    проверки «ревизия книги пуста» мало: она не отличает книгу прошлой порции от
    актуальной, и после падения упаковки старая книга сходила бы за свежую.
    """
    rows = decisions.values() if isinstance(decisions, Mapping) else decisions
    from proxy.smeta_core.row_decision import operation_rows
    canonical = [canonical_decision(op) for row in rows if isinstance(row, Mapping)
                 for op in operation_rows(row)]
    canonical.sort(key=lambda item: (str(item.get("source_row") or ""), str(item.get("norm_code") or "")))
    digest = hashlib.sha256()
    digest.update(CALCULATION_CONTRACT_REVISION.encode('utf-8') + b'\x00')
    if document_price_basis is not None:
        digest.update(json.dumps(document_price_basis_identity(document_price_basis),
                                 ensure_ascii=False, sort_keys=True).encode('utf-8') + b'\x00')
    digest.update(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    )
    return digest.hexdigest()[:32]


@dataclass(frozen=True)
class PortionProgress:
    """Решения и отдельный порядок рассмотрения ведомости в одной сессии."""

    session_id: str
    source_revision: str
    completed: frozenset[str]
    exhausted: frozenset[str]
    decisions: dict[str, dict]
    attempts: dict[str, int]
    passes: int
    artifact_revision_id: str | None
    artifact_decisions_revision: str | None
    last_decision_pass: dict[str, int] = field(default_factory=dict)
    last_observed_pass: dict[str, int] = field(default_factory=dict)

    @property
    def started(self) -> bool:
        return self.passes > 0 or bool(self.completed)

    @property
    def settled(self) -> frozenset[str]:
        """Only confirmed rows leave the queue; attempts are diagnostic history."""
        return self.completed


class PortionCursorService:
    """Долговечное состояние порционного разбора: SQLite рядом с контрольными точками."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS smeta_portion_done (
                    session_id TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    anchor TEXT NOT NULL,
                    decision_json TEXT NOT NULL DEFAULT '{}',
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, source_revision, anchor)
                )"""
            )
            # Existing cursors only stored closed decisions. Keep them while adding
            # explicit pending decisions, including rows reopened by the model.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(smeta_portion_done)")}
            if "last_decision_pass" not in columns:
                # Scheduling metadata only. Zero means the old cursor did not record
                # a pass number; never infer a professional decision from it.
                conn.execute("ALTER TABLE smeta_portion_done ADD COLUMN last_decision_pass INTEGER NOT NULL DEFAULT 0")
            if "is_closed" not in columns:
                conn.execute("ALTER TABLE smeta_portion_done ADD COLUMN is_closed INTEGER NOT NULL DEFAULT 1")
            if "attempts" not in columns:
                # Сколько раз модель уже смотрела на строку и не нашла нормы. Без счёта
                # такая строка возвращалась бы вечно: живой прогон 23:15 вернул все 25
                # позиций с «Нет подходящей нормы» — это чистые материалы (заглушки,
                # накладки, суппорты), у которых своей нормы монтажа и не бывает.
                conn.execute("ALTER TABLE smeta_portion_done ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            if "row_state" not in columns:
                # Прежнее `is_closed` не различало решение и исчерпанный лимит: им
                # закрывались и строки без нормы, отвергнутые дважды. Считать их
                # решёнными значило бы перенести прежнюю ошибку отчёта на уже
                # накопленное состояние (ревью Codex 11.09), поэтому состояние
                # восстанавливается по самому решению: есть шифр — решение, нет — лимит.
                conn.execute(
                    "ALTER TABLE smeta_portion_done ADD COLUMN row_state TEXT NOT NULL DEFAULT 'open'"
                )
                for row in conn.execute(
                    "SELECT rowid, decision_json, is_closed, attempts FROM smeta_portion_done"
                ).fetchall():
                    if not row["is_closed"]:
                        continue
                    try:
                        decision = json.loads(row["decision_json"] or "{}")
                    except (TypeError, ValueError):
                        decision = {}
                    has_norm = bool(str((decision or {}).get("norm_code") or "").strip())
                    conn.execute(
                        "UPDATE smeta_portion_done SET row_state=? WHERE rowid=?",
                        (STATE_DECIDED if has_norm else STATE_EXHAUSTED, row["rowid"]),
                    )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS smeta_portion_applied (
                    session_id TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    pass_id TEXT NOT NULL,
                    result_digest TEXT NOT NULL DEFAULT '',
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, source_revision, pass_id)
                )"""
            )
            applied_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(smeta_portion_applied)")
            }
            if applied_columns and "result_digest" not in applied_columns:
                # Таблица уже существовала без отпечатка: первая же запись с ключом
                # прохода падала «no such column» (ревью Codex 11.09).
                conn.execute(
                    "ALTER TABLE smeta_portion_applied ADD COLUMN result_digest TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS smeta_portion_state (
                    session_id TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    passes INTEGER NOT NULL DEFAULT 0,
                    artifact_revision_id TEXT,
                    artifact_decisions_revision TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, source_revision)
                )"""
            )
            # Колонка добавляется здесь, а не при чтении: `record_pass` сразу после
            # конструктора на старой БД падал «no column named
            # artifact_decisions_revision» (ревью Codex 11.09).
            state_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(smeta_portion_state)")
            }
            if "artifact_decisions_revision" not in state_columns:
                conn.execute(
                    "ALTER TABLE smeta_portion_state ADD COLUMN artifact_decisions_revision TEXT"
                )
            if "evidence_revision" not in state_columns:
                # Отпечаток источников подсказок на момент прохода. Строка уходит из
                # оборота по исчерпанию попыток, и пока источники те же, возвращать её
                # незачем — модель увидит ровно то, на что уже ответила отказом. Но
                # собранный индекс применений или пересобранный корпус — это новые
                # сведения, и отказ, данный без них, ничего о строке не доказывает
                # (ревью Codex 11.09, шаг 5).
                conn.execute(
                    "ALTER TABLE smeta_portion_state ADD COLUMN evidence_revision TEXT"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def document_price_basis(self, *, session_id: str, source_revision: str, capture) -> dict:
        """Atomically pin a new document; never infer an old document's price basis."""
        with self._connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS smeta_document_price_basis ('
                         'session_id TEXT NOT NULL, source_revision TEXT NOT NULL, basis_json TEXT NOT NULL, '
                         'PRIMARY KEY(session_id, source_revision))')
            conn.commit()
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT basis_json FROM smeta_document_price_basis WHERE session_id=? AND source_revision=?',
                                    (session_id, source_revision)).fetchone()
            if existing:
                return json.loads(existing['basis_json'])
            legacy = conn.execute('SELECT 1 FROM smeta_portion_done WHERE session_id=? AND source_revision=? LIMIT 1',
                                  (session_id, source_revision)).fetchone()
            legacy = legacy or conn.execute('SELECT 1 FROM smeta_portion_applied WHERE session_id=? AND source_revision=? LIMIT 1',
                                           (session_id, source_revision)).fetchone()
            legacy = legacy or conn.execute('SELECT 1 FROM smeta_portion_state WHERE session_id=? AND source_revision=? '
                                           'AND (passes>0 OR artifact_revision_id IS NOT NULL) LIMIT 1',
                                           (session_id, source_revision)).fetchone()
            basis = dict(schema='les.document-price-basis.v1', status='legacy_unpinned', path=None,
                         identity=None) if legacy else capture()
            conn.execute('INSERT INTO smeta_document_price_basis VALUES(?,?,?)',
                         (session_id, source_revision, json.dumps(basis, ensure_ascii=False)))
            return json.loads(json.dumps(basis))

    def replace_document_price_basis(self, *, session_id: str, source_revision: str, basis: Mapping[str, Any]) -> None:
        """Explicit trusted change; callers supply a captured basis, never model SHA."""
        with self._connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS smeta_document_price_basis ('
                         'session_id TEXT NOT NULL, source_revision TEXT NOT NULL, basis_json TEXT NOT NULL, '
                         'PRIMARY KEY(session_id, source_revision))')
            conn.execute('INSERT INTO smeta_document_price_basis VALUES(?,?,?) '
                         'ON CONFLICT(session_id,source_revision) DO UPDATE SET basis_json=excluded.basis_json',
                         (session_id, source_revision, json.dumps(dict(basis), ensure_ascii=False)))

    def reopen_exhausted(
        self, *, session_id: str, source_revision: str, evidence_revision: str
    ) -> int:
        """Вернуть в оборот строки, исчерпавшие попытки, если свидетельства обновились.

        Строка уходит из оборота по пределу попыток, и это предел повторов, а не вывод о
        позиции. Пока источники подсказок те же, возвращать её незачем: модель увидит
        ровно то, на что уже ответила отказом, и третий такой ответ ничего не добавит.
        Но собранный индекс применений или пересобранный корпус — новые сведения, и
        отказ, данный без них, о строке не свидетельствует (ревью Codex 11.09, шаг 5).

        Возвращает число вернувшихся строк. Ноль означает и «нечего возвращать», и
        «ревизия та же» — оба случая одинаково не требуют действий.

        Решённые строки не трогаются: выбранная норма остаётся выбранной, и повторять
        по ней работу незачем. Счётчик попыток обнуляется — иначе строка вернулась бы
        уже исчерпанной и ушла после первого же ответа.
        """
        session = str(session_id or "")
        revision = str(source_revision or "")
        evidence = str(evidence_revision or "").strip()
        if not evidence:
            # Пустой отпечаток означает, что источники не опознаны. Возвращать строки на
            # этом основании нельзя: неизвестное не равно новому.
            return 0
        with self._connect() as conn:
            row = conn.execute(
                "SELECT evidence_revision FROM smeta_portion_state "
                "WHERE session_id=? AND source_revision=?",
                (session, revision),
            ).fetchone()
            previous = str((row["evidence_revision"] if row else "") or "")
            if previous == evidence:
                return 0
            changed = conn.execute(
                "UPDATE smeta_portion_done SET row_state=?, is_closed=0, attempts=0 "
                "WHERE session_id=? AND source_revision=? AND row_state=?",
                (STATE_OPEN, session, revision, STATE_EXHAUSTED),
            ).rowcount
            conn.execute(
                """INSERT INTO smeta_portion_state (session_id, source_revision, evidence_revision)
                   VALUES (?, ?, ?)
                   ON CONFLICT(session_id, source_revision)
                   DO UPDATE SET evidence_revision=excluded.evidence_revision""",
                (session, revision, evidence),
            )
            conn.commit()
        if changed:
            logging.getLogger(__name__).warning(
                "[SMETA_PORTION] возвращено в оборот строк: %s (свидетельства обновились)",
                changed,
            )
        return int(changed or 0)

    def record_calculation(self, *, session_id: str, source_revision: str,
                           statuses: Mapping[str, str], receipts=()) -> None:
        """Apply a rebuilt book's facts without inventing another model attempt."""
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT anchor, decision_json, row_state FROM smeta_portion_done "
                "WHERE session_id=? AND source_revision=?", (session_id, source_revision),
            ).fetchall():
                status = str(statuses.get(str(row["anchor"])) or "")
                if not status:
                    continue
                from proxy.smeta_core.row_decision import source_resolved

                success = source_resolved(status)
                decision = json.loads(row["decision_json"])
                relevant = [dict(item) for item in receipts if item.get('source_row') == decision.get('source_row')]
                if relevant:
                    decision['calculation_receipts'] = relevant
                if success:
                    decision.pop("rejected_reason", None)
                else:
                    decision["rejected_reason"] = status
                state = (STATE_DECIDED if success else
                         STATE_EXHAUSTED if row["row_state"] == STATE_EXHAUSTED else STATE_OPEN)
                conn.execute(
                    "UPDATE smeta_portion_done SET decision_json=?, row_state=?, is_closed=? "
                    "WHERE session_id=? AND source_revision=? AND anchor=?",
                    (json.dumps(decision, ensure_ascii=False), state, int(success),
                     session_id, source_revision, row["anchor"]),
                )

    def progress(self, *, session_id: str, source_revision: str) -> PortionProgress:
        """Что уже закрыто по этой ведомости. Пустой прогресс — законный первый проход."""
        session = str(session_id or "")
        revision = str(source_revision or "")
        with self._connect() as conn:
            done: dict[str, dict] = {}
            closed: set[str] = set()
            spent: set[str] = set()
            tries: dict[str, int] = {}
            last_pass: dict[str, int] = {}
            for row in conn.execute(
                "SELECT anchor, decision_json, is_closed, attempts, row_state, last_decision_pass FROM smeta_portion_done"
                " WHERE session_id=? AND source_revision=? ORDER BY rowid",
                (session, revision),
            ):
                try:
                    decision = json.loads(row["decision_json"] or "{}")
                except (TypeError, ValueError):
                    decision = {}
                done[str(row["anchor"])] = decision if isinstance(decision, dict) else {}
                anchor = str(row["anchor"])
                tries[anchor] = int(row["attempts"] or 0)
                last_pass[anchor] = int(row["last_decision_pass"] or 0)
                state = str(row["row_state"] or STATE_OPEN)
                if state == STATE_DECIDED:
                    closed.add(anchor)
                elif state == STATE_EXHAUSTED:
                    spent.add(anchor)
            state = conn.execute(
                "SELECT passes, artifact_revision_id, artifact_decisions_revision"
                " FROM smeta_portion_state"
                " WHERE session_id=? AND source_revision=?",
                (session, revision),
            ).fetchone()
        from proxy.services.portion_feedback_service import PortionFeedbackService
        observed_passes,last_observed=PortionFeedbackService(self.db_path).observation_order(
            session_id=session,source_revision=revision,
        )
        return PortionProgress(
            session_id=session,
            source_revision=revision,
            completed=frozenset(closed),
            exhausted=frozenset(spent),
            decisions=done,
            attempts=tries,
            last_decision_pass=last_pass,
            last_observed_pass=last_observed,
            passes=max(int(state["passes"]) if state is not None else 0,observed_passes),
            artifact_revision_id=(state["artifact_revision_id"] if state is not None else None),
            artifact_decisions_revision=(
                state["artifact_decisions_revision"] if state is not None else None
            ),
        )

    def record_pass(
        self,
        *,
        session_id: str,
        source_revision: str,
        completed: Iterable[str] | Mapping[str, Mapping[str, Any]],
        decisions: Mapping[str, Mapping[str, Any]] | None = None,
        declined: Iterable[str] = (),
        rejected: Mapping[str, str] | None = None,
        artifact_revision_id: str | None = None,
        artifact_decisions_revision: str | None = None,
        pass_id: str = "",
        result_digest: str = "",
    ) -> PortionProgress:
        """Отметить проход: закрытые строки, их решения и ревизию собранной книги.

        Закрытыми считаются строки с принятым решением модели. Проход без единого
        решения тоже засчитывается — иначе повтор того же сообщения выглядел бы как
        первый раз, — но курсор от этого не двигается.

        Решение хранится рядом с якорем, потому что книга собирается из решений: без
        накопленных решений прошлых проходов последний собрал бы книгу из одной своей
        порции, а прежние строки исчезли бы. `completed` принимает и голые якоря — тогда
        решение остаётся пустым и в книгу такая строка не попадёт.

        `rejected` — строки, где норма выбрана, но расчёт её не принял, с причиной по
        каждой. Такой отказ — не пустая попытка: модель получает сведения, которых у неё
        не было, и обязана получить шанс ими воспользоваться. Поэтому новая причина
        обнуляет счётчик попыток, а повтор той же причины его двигает — иначе строка
        крутилась бы вечно (живой прогон 11.09, 08:45: две строки ушли из оборота,
        не успев увидеть ни одного объяснения).

        `declined` — показанные строки без выбора. MAX_ATTEMPTS помечает их
        exhausted для диагностики и очередности; они остаются открытыми и доступны
        следующим проходам. Лимит попыток не является предметным решением.

        `pass_id` делает запись идемпотентной: повтор доставки одного и того же
        результата не должен ни двигать счётчик попыток, ни закрывать строку. Потерянный
        HTTP-ответ после успешной записи — обычное дело, и повтор обязан вернуть уже
        зафиксированное состояние.

        Ревизия книги перезаписывается только непустым значением: проход, который книгу
        не собирал, не должен стирать ссылку на уже собранную.
        """
        session = str(session_id or "")
        revision = str(source_revision or "")
        if isinstance(completed, Mapping):
            entries = [
                (str(anchor).strip(), dict(decision or {}))
                for anchor, decision in completed.items()
                if str(anchor or "").strip()
            ]
        else:
            entries = [(str(item).strip(), {}) for item in completed if str(item or "").strip()]
        closed = {anchor for anchor, _ in entries}
        turned_down = {
            str(anchor).strip(): str(reason or "").strip()
            for anchor, reason in (rejected or {}).items()
            if str(anchor or "").strip()
        }
        refused = {
            str(item).strip() for item in declined if str(item or "").strip()
        } - closed - set(turned_down)
        latest = dict(entries)
        latest.update({str(anchor): dict(row) for anchor, row in (decisions or {}).items()})
        token = str(pass_id or "").strip()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if token:
                already = conn.execute(
                    "SELECT result_digest FROM smeta_portion_applied"
                    " WHERE session_id=? AND source_revision=? AND pass_id=?",
                    (session, revision, token),
                ).fetchone()
                if already is not None:
                    conn.execute("COMMIT")
                    stored = str(already["result_digest"] or "")
                    if result_digest and stored and stored != result_digest:
                        # Тот же ключ хода с другим ответом — не повтор доставки, а
                        # противоречие. Принять новый результат под старым ключом
                        # значило бы тихо переписать историю; отказ виден в журнале.
                        logging.getLogger(__name__).warning(
                            "[SMETA_PORTION] ход %s уже записан с другим результатом:"
                            " новый ответ отклонён", token,
                        )
                    return self.progress(session_id=session, source_revision=revision)
                conn.execute(
                    "INSERT INTO smeta_portion_applied"
                    " (session_id, source_revision, pass_id, result_digest) VALUES (?,?,?,?)",
                    (session, revision, token, str(result_digest or "")),
                )
            seen: dict[str, int] = {}
            previous_reason: dict[str, str] = {}
            for row in conn.execute(
                "SELECT anchor, attempts, decision_json FROM smeta_portion_done"
                " WHERE session_id=? AND source_revision=?",
                (session, revision),
            ):
                anchor = str(row["anchor"])
                seen[anchor] = int(row["attempts"] or 0)
                try:
                    stored_decision = json.loads(row["decision_json"] or "{}")
                except (TypeError, ValueError):
                    stored_decision = {}
                previous_reason[anchor] = str(
                    (stored_decision or {}).get("rejected_reason") or ""
                ).strip()
            previous_pass = conn.execute(
                "SELECT passes FROM smeta_portion_state WHERE session_id=? AND source_revision=?",
                (session, revision),
            ).fetchone()
            decision_pass = int(previous_pass["passes"] or 0) + 1 if previous_pass else 1
            payload = []
            for anchor, decision in latest.items():
                tries = seen.get(anchor, 0) + (1 if anchor in refused else 0)
                if anchor in turned_down:
                    # Отказ расчёта с новым объяснением — шанс, а не потраченная
                    # попытка: модель ещё не видела этой причины. Тот же отказ второй
                    # раз означает, что объяснение не помогло, и счёт идёт.
                    reason = turned_down[anchor]
                    tries = (
                        seen.get(anchor, 0) + 1
                        if reason and reason == previous_reason.get(anchor)
                        else 0
                    )
                if anchor in closed:
                    state = STATE_DECIDED
                elif (anchor in refused or anchor in turned_down) and tries >= MAX_ATTEMPTS:
                    state = STATE_EXHAUSTED
                else:
                    state = STATE_OPEN
                payload.append((
                    session, revision, anchor,
                    json.dumps(decision, ensure_ascii=False),
                    int(state == STATE_DECIDED), tries, state, decision_pass,
                ))
            conn.executemany(
                "INSERT INTO smeta_portion_done"
                " (session_id, source_revision, anchor, decision_json, is_closed, attempts, row_state, last_decision_pass)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(session_id, source_revision, anchor) DO UPDATE SET"
                " decision_json=excluded.decision_json, is_closed=excluded.is_closed,"
                " attempts=excluded.attempts, row_state=excluded.row_state,"
                " last_decision_pass=excluded.last_decision_pass,"
                " recorded_at=CURRENT_TIMESTAMP",
                payload,
            )
            conn.execute(
                """INSERT INTO smeta_portion_state
                   (session_id, source_revision, passes, artifact_revision_id,
                    artifact_decisions_revision)
                   VALUES (?,?,1,?,?)
                   ON CONFLICT(session_id, source_revision) DO UPDATE SET
                     passes = passes + 1,
                     artifact_revision_id = COALESCE(excluded.artifact_revision_id, artifact_revision_id),
                     artifact_decisions_revision = CASE
                       WHEN excluded.artifact_revision_id IS NULL THEN artifact_decisions_revision
                       ELSE excluded.artifact_decisions_revision END,
                     updated_at = CURRENT_TIMESTAMP""",
                (session, revision, artifact_revision_id, artifact_decisions_revision),
            )
        return self.progress(session_id=session, source_revision=revision)
