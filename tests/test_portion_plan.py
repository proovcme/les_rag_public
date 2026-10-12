"""План прохода: какие строки ведомости берём сейчас и что остаётся на потом.

Собирает вместе три готовых части — якоря строк, подтверждённый прогресс и нарезку.
Отдельно проверяется то, чего Codex справедливо требовал: продолжение опирается на
закрытые строки, а не на число поисковых запросов и не на фазу инструмента; показанная
строка закрытой не считается; повторный запрос без нового прогресса не топчется на месте.
"""

from __future__ import annotations

from proxy.services.portion_plan_service import continuous_cursor, portion_plan


def test_changing_diagnostics_cannot_starve_unseen_rows(tmp_path):
    from proxy.services.portion_cursor_service import PortionCursorService
    cursors = PortionCursorService(tmp_path/'cursor.sqlite')
    rows = VOR[:6]
    shown = []
    for number in range(6):
        plan = portion_plan(rows=rows, limit=2, session_id='s', source_revision=REVISION, cursors=cursors)
        anchors = [r['anchor'] for r in plan['rows']]
        shown.append(anchors)
        decisions = {a: {'source_row': a, 'norm_code': '', 'rejected_reason': f'needs_basis_{number}'} for a in anchors}
        progress = cursors.record_pass(session_id='s', source_revision=REVISION,
            completed={}, decisions=decisions, rejected={a: f'needs_basis_{number}' for a in anchors},
            pass_id=f'pass-{number}')
        assert not progress.completed
        assert not progress.settled
    expected = [[r['anchor'] for r in rows[i:i+2]] for i in (0, 2, 4)]
    assert shown == expected * 2
    assert len(progress.decisions) == 6
    # Scheduling must not depend on identical error text or exhaust rows.
    assert set(progress.attempts.values()) == {0}


def test_repeated_transport_does_not_change_queue_order(tmp_path):
    from proxy.services.portion_cursor_service import PortionCursorService
    cursors = PortionCursorService(tmp_path/'cursor.sqlite')
    first = VOR[0]['anchor']
    args = dict(session_id='s', source_revision=REVISION, completed={},
        decisions={first: {'source_row': first, 'norm_code': ''}}, pass_id='same', declined=[first])
    cursors.record_pass(**args)
    before = portion_plan(rows=VOR[:3], limit=1, session_id='s', source_revision=REVISION, cursors=cursors)
    cursors.record_pass(**args)
    after = portion_plan(rows=VOR[:3], limit=1, session_id='s', source_revision=REVISION, cursors=cursors)
    assert before['rows'] == after['rows'] == [VOR[1]]
    assert before['pass_no'] == after['pass_no'] == 2
    assert cursors.progress(session_id='s', source_revision=REVISION).last_decision_pass == {first: 1}


VOR = [
    {
        "source_row": str(900 + n),
        "sheet": "СКС",
        "anchor": f"СКС!{900 + n}",
        "title": f"Позиция {n}",
        "unit": "шт.",
        "quantity": n,
    }
    for n in range(1, 21)
]
REVISION = "rev-" + "0" * 60


class _Cursors:
    """Хранилище прогресса, какое отдаёт PortionCursorService."""

    def __init__(self, completed: tuple[str, ...] = (), passes: int = 0, artifact: str | None = None) -> None:
        self.completed = frozenset(completed)
        self.passes = passes
        self.artifact = artifact

    def progress(self, *, session_id: str, source_revision: str):
        return type(
            "P",
            (),
            {
                "completed": self.completed,
                "passes": self.passes,
                "artifact_revision_id": self.artifact,
            },
        )()


def _anchors(count: int) -> tuple[str, ...]:
    return tuple(row["anchor"] for row in VOR[:count])


def test_first_pass_starts_from_the_beginning():
    plan = portion_plan(
        rows=VOR, limit=8, session_id="s1", source_revision=REVISION, cursors=_Cursors(),
    )
    assert plan["rows"][0]["source_row"] == "901"
    assert len(plan["rows"]) == 8
    assert plan["remaining"] == 12
    assert plan["after"] == ""
    assert plan["pass_no"] == 1


def test_second_pass_continues_after_the_closed_rows():
    plan = portion_plan(
        rows=VOR, limit=8, session_id="s1", source_revision=REVISION,
        cursors=_Cursors(completed=_anchors(8), passes=1),
    )
    assert plan["rows"][0]["source_row"] == "909"
    assert plan["remaining"] == 4
    assert plan["after"] == "СКС!908"
    assert plan["pass_no"] == 2


def test_unfinished_row_inside_a_portion_is_not_skipped():
    """Показанная строка без решения остаётся невзятой — курсор до неё не доходит.

    Ревью Codex 10.09 (R4): считать всю показанную порцию пройденной значит молча
    потерять позиции, для которых карточек в пакете не нашлось.
    """
    closed = tuple(row["anchor"] for row in VOR[:8] if row["source_row"] != "905")
    plan = portion_plan(
        rows=VOR, limit=8, session_id="s1", source_revision=REVISION,
        cursors=_Cursors(completed=closed, passes=1),
    )
    assert plan["after"] == "СКС!904", "курсор обязан остановиться перед незакрытой строкой"
    assert plan["rows"][0]["source_row"] == "905", "следующий проход возвращается к ней"


def test_last_pass_reports_the_end():
    plan = portion_plan(
        rows=VOR, limit=8, session_id="s1", source_revision=REVISION,
        cursors=_Cursors(completed=_anchors(16), passes=2),
    )
    assert [row["source_row"] for row in plan["rows"]] == ["917", "918", "919", "920"]
    assert plan["remaining"] == 0
    assert plan["final_portion"] is True
    assert plan["complete"] is False, "строки на этот проход ещё есть"


def test_everything_closed_gives_no_rows():
    plan = portion_plan(
        rows=VOR, limit=8, session_id="s1", source_revision=REVISION,
        cursors=_Cursors(completed=_anchors(20), passes=3),
    )
    assert plan["rows"] == []
    assert plan["complete"] is True
    assert plan["remaining"] == 0


def test_missing_cursor_service_still_gives_a_first_pass():
    """Без хранилища прогресса работаем как в первый раз, а не падаем."""
    plan = portion_plan(
        rows=VOR, limit=5, session_id="s1", source_revision=REVISION, cursors=None,
    )
    assert plan["rows"][0]["source_row"] == "901"
    assert plan["pass_no"] == 1


def test_broken_cursor_service_does_not_lose_the_vor():
    class _Broken:
        def progress(self, **_kwargs):
            raise RuntimeError("хранилище недоступно")

    plan = portion_plan(
        rows=VOR, limit=5, session_id="s1", source_revision=REVISION, cursors=_Broken(),
    )
    assert len(plan["rows"]) == 5
    assert plan["pass_no"] == 1


def test_cursor_needs_a_contiguous_run():
    assert continuous_cursor(VOR, set()) == ""
    assert continuous_cursor(VOR, {"СКС!902"}) == "", "дырка в начале — курсор не двигается"
    assert continuous_cursor(VOR, {"СКС!901", "СКС!902", "СКС!904"}) == "СКС!902"


def test_plan_carries_the_book_revision_forward():
    """Ревизия собранной книги нужна следующему проходу, чтобы дописать её, а не начать."""
    plan = portion_plan(
        rows=VOR, limit=8, session_id="s1", source_revision=REVISION,
        cursors=_Cursors(completed=_anchors(8), passes=1, artifact="rev_42"),
    )
    assert plan["artifact_revision_id"] == "rev_42"


def _await_review(cursors, rows, *, pass_id: str) -> list[str]:
    """Провести проход и оставить его строки ждать проверки посчитанного чека."""
    anchors = [row["anchor"] for row in rows]
    cursors.record_pass(
        session_id="s", source_revision=REVISION, completed={},
        decisions={a: {"source_row": a, "norm_code": "ГЭСН15-05-020-01"} for a in anchors},
        pass_id=pass_id,
    )
    cursors.record_calculation(
        session_id="s", source_revision=REVISION,
        statuses={a: "resource_review_required" for a in anchors},
        receipts=[{"source_row": a, "work_id": a, "calculation_ref": "c" * 64} for a in anchors],
    )
    return anchors


def test_row_awaiting_receipt_review_returns_in_the_next_portion(tmp_path):
    """Посчитанная строка обязана вернуться к модели вместе со своим чеком.

    Закрыть строку может только подтверждение фактического расчёта
    (`resource_review_status`/`resource_review_ref` против `calculation_ref`), а чек
    попадает в контекст лишь для строк текущей порции. Если такая строка не
    возвращается, подтверждать нечего и `completed` навсегда остаётся нулём:
    живой прогон 14.09 — 217 якорей показаны ровно по одному разу за 35 проходов,
    привязано 0 из 318.
    """
    from proxy.services.portion_cursor_service import PortionCursorService

    cursors = PortionCursorService(tmp_path / "cursor.sqlite")
    rows = VOR[:6]
    first = portion_plan(rows=rows, limit=2, session_id="s", source_revision=REVISION, cursors=cursors)
    awaiting = _await_review(cursors, first["rows"], pass_id="pass-1")

    second = portion_plan(rows=rows, limit=2, session_id="s", source_revision=REVISION, cursors=cursors)
    returned = [row["anchor"] for row in second["rows"] if row["anchor"] in awaiting]
    assert returned, "строка с посчитанным чеком обязана вернуться в порцию"


def test_receipt_review_shares_the_portion_with_unseen_rows(tmp_path):
    """Проверка чеков не вытесняет ещё не разобранные строки и не съедает порцию целиком."""
    from proxy.services.portion_cursor_service import PortionCursorService

    cursors = PortionCursorService(tmp_path / "cursor.sqlite")
    rows = VOR[:8]
    first = portion_plan(rows=rows, limit=4, session_id="s", source_revision=REVISION, cursors=cursors)
    awaiting = _await_review(cursors, first["rows"], pass_id="pass-1")

    second = portion_plan(rows=rows, limit=4, session_id="s", source_revision=REVISION, cursors=cursors)
    anchors = [row["anchor"] for row in second["rows"]]
    review = [a for a in anchors if a in awaiting]
    unseen = [a for a in anchors if a not in awaiting]
    assert len(review) == 2, f"половина порции — на проверку чеков, получено {review}"
    assert len(unseen) == 2, f"вторая половина — новые строки, получено {unseen}"
