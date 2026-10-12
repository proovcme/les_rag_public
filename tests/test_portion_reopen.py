"""Возврат исчерпавших попытки строк, когда свидетельства обновились.

Строка уходит из оборота по пределу повторов, и это предел, а не вывод о позиции. Пока
источники подсказок те же, повтор ничего не добавит; собранный индекс применений —
новые сведения, и отказ, данный без них, о строке не свидетельствует (ревью Codex 11.09).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from proxy.services.portion_cursor_service import (
    MAX_ATTEMPTS,
    PortionCursorService,
)


REVISION = "vor-1"
SESSION = "sks-reopen"


@pytest.fixture()
def cursors(tmp_path: Path) -> PortionCursorService:
    return PortionCursorService(tmp_path / "portions.db")


def exhaust(
    cursors: PortionCursorService, anchor: str, *, revision: str = REVISION
) -> None:
    """Довести строку до исчерпания попыток так же, как это делает живой проход.

    Отказ приходит строкой ответа модели с пустым шифром: `declined` называет якоря, а
    `decisions` несёт сами строки — врозь они в живом потоке не встречаются.
    """
    for number in range(MAX_ATTEMPTS):
        cursors.record_pass(
            session_id=SESSION,
            source_revision=revision,
            completed=(),
            decisions={anchor: {"source_row": anchor.split("!")[-1], "norm_code": ""}},
            declined=(anchor,),
            pass_id=f"pass-{anchor}-{revision}-{number}",
        )


def test_a_new_evidence_revision_brings_the_row_back(
    cursors: PortionCursorService,
) -> None:
    exhaust(cursors, "СКС!997")
    assert "СКС!997" in cursors.progress(
        session_id=SESSION, source_revision=REVISION
    ).exhausted

    assert cursors.reopen_exhausted(
        session_id=SESSION, source_revision=REVISION, evidence_revision="index:42"
    ) == 1

    progress = cursors.progress(session_id=SESSION, source_revision=REVISION)
    assert progress.exhausted == frozenset()
    assert progress.attempts.get("СКС!997", 0) == 0


def test_the_same_revision_changes_nothing(cursors: PortionCursorService) -> None:
    """Иначе строка возвращалась бы каждый проход и получала тот же отказ."""
    exhaust(cursors, "СКС!997")
    assert cursors.reopen_exhausted(
        session_id=SESSION, source_revision=REVISION, evidence_revision="index:42"
    ) == 1
    assert cursors.reopen_exhausted(
        session_id=SESSION, source_revision=REVISION, evidence_revision="index:42"
    ) == 0


def test_an_unknown_revision_is_not_treated_as_new(
    cursors: PortionCursorService,
) -> None:
    """Неизвестное не равно новому: недоступный файл вернул бы строки на пустом месте."""
    exhaust(cursors, "СКС!997")
    assert cursors.reopen_exhausted(
        session_id=SESSION, source_revision=REVISION, evidence_revision=""
    ) == 0
    assert "СКС!997" in cursors.progress(
        session_id=SESSION, source_revision=REVISION
    ).exhausted


def test_a_decided_row_is_left_alone(cursors: PortionCursorService) -> None:
    """Выбранная норма остаётся выбранной: повторять по ней работу незачем."""
    cursors.record_pass(
        session_id=SESSION,
        source_revision=REVISION,
        completed=("СКС!995",),
        decisions={"СКС!995": {"source_row": "995", "norm_code": "ГЭСНм08-02-398-01"}},
        pass_id="pass-decided",
    )
    exhaust(cursors, "СКС!997")

    assert cursors.reopen_exhausted(
        session_id=SESSION, source_revision=REVISION, evidence_revision="index:42"
    ) == 1

    progress = cursors.progress(session_id=SESSION, source_revision=REVISION)
    assert "СКС!995" in progress.completed
    assert progress.decisions["СКС!995"]["norm_code"] == "ГЭСНм08-02-398-01"


def test_another_vor_in_the_same_session_is_not_touched(
    cursors: PortionCursorService,
) -> None:
    """Ревизия источника разделяет ведомости: чужие строки возвращать нельзя."""
    exhaust(cursors, "СКС!997")
    exhaust(cursors, "ЭОМ!12", revision="vor-2")

    cursors.reopen_exhausted(
        session_id=SESSION, source_revision=REVISION, evidence_revision="index:42"
    )

    assert "ЭОМ!12" in cursors.progress(
        session_id=SESSION, source_revision="vor-2"
    ).exhausted


def test_nothing_to_reopen_is_not_an_error(cursors: PortionCursorService) -> None:
    assert cursors.reopen_exhausted(
        session_id=SESSION, source_revision=REVISION, evidence_revision="index:42"
    ) == 0
