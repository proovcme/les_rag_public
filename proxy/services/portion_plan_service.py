"""План одного прохода по длинной ведомости.

ЗАЧЕМ. Ведомость на восемь десятков позиций не закрывается за раз, и это измерено:
в окно модели помещаются свидетельства примерно по 18 запросам из 51 — 32 768 токенов
контекста, 22 528 на вход этапа ответа, минус профиль сметчика и текст ведомости
оставляют 14 031 токен на карточки норм. Настройкой бюджета этого не изменить.

ЧТО ЗДЕСЬ. Ответ на один вопрос: какие строки берём сейчас и что остаётся на потом.
Продолжение опирается на якоря закрытых строк, а не на счётчик поисковых запросов —
соответствия один к одному между ними нет: на 80 строк модель формулировала 51, 55 и
59 запросов в разных прогонах.

Курсор двигают только закрытые строки, причём подряд от начала. Показанная строка не
считается закрытой: внутри порции часть позиций остаётся без подходящей карточки, и
если считать порцию пройденной целиком, они потеряются молча (ревью Codex 10.09, R4).

Из оборота уходит только подтверждённая строка (`completed`). Повторные отказы
(`exhausted`) остаются диагностикой. Сначала берём ещё не разобранные строки,
затем открытые строки в порядке давности последнего решения модели.
Структурно отклонённый завершённый ответ также даёт очередь следующим строкам:
сервер сохраняет показанные якоря отдельно от решений, не подтверждая их.

Исключение — строка, расчёт которой уже посчитан и ждёт проверки модели. Закрыть
строку способно только подтверждение фактического чека (`resource_review_status`
и `resource_review_ref` против `calculation_ref`), а сам чек попадает в контекст
лишь вместе со своей строкой. Пока такая строка не вернётся в порцию, подтверждать
нечего, и `completed` остаётся нулём при любом качестве модели: живой прогон 14.09 —
217 якорей показаны ровно по одному разу за 35 проходов, привязано 0 из 318.
Поэтому половина порции резервируется под проверку посчитанных чеков, а вторая
половина по-прежнему берёт ещё не разобранные строки: меняющаяся диагностика не
должна их вытеснять (ревью Codex 10.09, R4).

Прогресс ищется по ревизии содержимого ведомости, а не по имени файла: тот же файл под
другим именем обязан продолжаться, другая ведомость под тем же именем — начинаться
заново.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


SCHEMA = "les.smeta.portion-plan.v2"


def continuous_cursor(
    rows: Sequence[Mapping[str, Any]], completed: frozenset[str] | set[str] | None
) -> str:
    """Якорь последней закрытой строки непрерывной части ведомости.

    Непрерывной — потому что дырка означает незакрытую позицию: перепрыгнуть через неё
    значит потерять её навсегда. Проход вернётся к ней, а не к концу порции.
    """
    from proxy.smeta_core.vor_rows import row_anchor

    done = set(completed or ())
    if not done:
        return ""
    cursor = ""
    for row in rows:
        anchor = row_anchor(row)
        if anchor not in done:
            break
        cursor = anchor
    return cursor


RECEIPT_REVIEW_PENDING = "resource_review_required"


def awaits_receipt_review(decision: Mapping[str, Any] | None) -> bool:
    """True, когда расчёт строки посчитан и ждёт проверки модели по своему чеку."""
    stored = decision or {}
    return bool(
        stored.get("calculation_receipts")
        and str(stored.get("rejected_reason") or "") == RECEIPT_REVIEW_PENDING
    )


def portion_plan(
    *,
    rows: Sequence[Mapping[str, Any]],
    limit: int,
    session_id: str,
    source_revision: str,
    cursors: Any = None,
) -> dict[str, Any]:
    """Строки текущего прохода, остаток и номер прохода.

    `cursors` — хранилище прогресса с методом `progress` (`PortionCursorService`). Его
    отсутствие или сбой означают первый проход: начать ведомость заново хуже, чем упасть,
    но лучше, чем потерять её целиком.
    """
    from proxy.smeta_core.vor_rows import row_anchor, slice_rows

    ordered = [dict(row) for row in rows]
    completed: set[str] = set()
    exhausted: set[str] = set()
    decisions: dict[str, Any] = {}
    passes = 0
    last_decision_pass = {}
    last_observed_pass = {}
    artifact_revision_id: str | None = None
    artifact_decisions_revision: str | None = None
    if cursors is not None:
        try:
            progress = cursors.progress(
                session_id=str(session_id or ""),
                source_revision=str(source_revision or ""),
            )
        except Exception:  # noqa: BLE001 — сбой хранилища не должен ронять сборку сметы
            progress = None
        if progress is not None:
            completed = set(getattr(progress, "completed", ()) or ())
            exhausted = set(getattr(progress, "exhausted", ()) or ())
            decisions = dict(getattr(progress, "decisions", {}) or {})
            passes = int(getattr(progress, "passes", 0) or 0)
            last_decision_pass = dict(getattr(progress, 'last_decision_pass', {}) or {})
            last_observed_pass = dict(getattr(progress, 'last_observed_pass', {}) or {})
            artifact_revision_id = getattr(progress, "artifact_revision_id", None)
            artifact_decisions_revision = getattr(progress, "artifact_decisions_revision", None)

    after = continuous_cursor(ordered, completed)
    # A changed rejection reason resets diagnostic attempts, but must not restart
    # the queue at the same rows. First visit unseen rows, then the oldest authored
    # decisions. This order never closes a row or changes the model's selection.
    pending = [row for row in ordered if row_anchor(row) not in completed]
    pending.sort(key=lambda row: (row_anchor(row) in decisions or row_anchor(row) in last_observed_pass,
        last_observed_pass.get(row_anchor(row), 0),last_decision_pass.get(row_anchor(row), 0)))
    # Проверка посчитанных чеков идёт вместе с разбором новых строк: без возврата
    # такой строки её `calculation_ref` модель никогда не увидит и не закроет ни одной
    # позиции, а отдать ей всю порцию значило бы остановить обход ведомости.
    awaiting = [row for row in pending if awaits_receipt_review(decisions.get(row_anchor(row)))]
    if awaiting:
        head = awaiting[: max(1, limit // 2)]
        reserved = {row_anchor(row) for row in head}
        pending = head + [row for row in pending if row_anchor(row) not in reserved]
    portion, rest = slice_rows(pending, limit=limit)
    return {
        "schema": SCHEMA,
        "rows": portion,
        "after": after,
        "remaining": len(rest),
        "total": len(ordered),
        "completed": len(completed),
        "exhausted": len(exhausted),
        "unresolved": sorted(exhausted),
        "completed_anchors": sorted(completed),
        "decisions": decisions,
        "pass_no": passes + 1,
        "artifact_revision_id": artifact_revision_id,
        "artifact_decisions_revision": artifact_decisions_revision,
        "complete": not rest and not portion,
        "final_portion": not rest,
    }
