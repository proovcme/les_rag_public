"""Состояние порционного разбора ведомости на настоящем SQLite.

ЗАЧЕМ ОТДЕЛЬНОЕ ХРАНИЛИЩЕ. Прогресс порций сперва читался из `phase` контрольной точки
инструмента. Ревью Codex 10.09 (R4) воспроизвело поломку: `begin_or_resume` с новым
ключом заводит точку с `phase='started'`, она становится последней и прячет
подтверждённый прогресс — проход возвращал первые строки заново.

Здесь состояние прохода отделено от фазы инструмента и живёт своей схемой.
"""

from __future__ import annotations

import json

import pytest

from proxy.services.portion_cursor_service import PortionCursorService


REVISION = "a" * 64
OTHER = "b" * 64


@pytest.fixture()
def cursors(tmp_path):
    return PortionCursorService(tmp_path / "portions.db")


def test_empty_store_reports_a_first_pass(cursors):
    progress = cursors.progress(session_id="s1", source_revision=REVISION)
    assert progress.completed == frozenset()
    assert progress.passes == 0
    assert progress.started is False


def test_recorded_rows_survive_a_reopen(cursors, tmp_path):
    cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed=["СКС!984", "СКС!985"],
    )
    reopened = PortionCursorService(tmp_path / "portions.db")
    progress = reopened.progress(session_id="s1", source_revision=REVISION)
    assert progress.completed == frozenset({"СКС!984", "СКС!985"})
    assert progress.passes == 1


def test_passes_accumulate_and_rows_do_not_duplicate(cursors):
    cursors.record_pass(session_id="s1", source_revision=REVISION, completed=["СКС!984"])
    progress = cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed=["СКС!984", "СКС!985"],
    )
    assert progress.completed == frozenset({"СКС!984", "СКС!985"})
    assert progress.passes == 2


def test_a_pass_without_decisions_still_counts_but_closes_nothing(cursors):
    """Повтор того же сообщения — не первый проход, но и не закрытые строки."""
    progress = cursors.record_pass(session_id="s1", source_revision=REVISION, completed=[])
    assert progress.passes == 1
    assert progress.completed == frozenset()


def test_another_vor_has_its_own_progress(cursors):
    cursors.record_pass(session_id="s1", source_revision=REVISION, completed=["СКС!984"])
    other = cursors.progress(session_id="s1", source_revision=OTHER)
    assert other.completed == frozenset()
    assert other.passes == 0


def test_another_session_has_its_own_progress(cursors):
    cursors.record_pass(session_id="s1", source_revision=REVISION, completed=["СКС!984"])
    assert cursors.progress(session_id="s2", source_revision=REVISION).passes == 0


def test_book_revision_is_kept_until_a_new_one_arrives(cursors):
    """Проход, который книгу не собирал, не должен стирать ссылку на собранную."""
    cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed=["СКС!984"],
        artifact_revision_id="rev_1",
    )
    kept = cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed=["СКС!985"],
    )
    assert kept.artifact_revision_id == "rev_1"
    moved = cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed=["СКС!986"],
        artifact_revision_id="rev_2",
    )
    assert moved.artifact_revision_id == "rev_2"


def test_progress_drives_the_plan_end_to_end(cursors):
    """Хранилище и план прохода сходятся на настоящих данных, а не на заглушке."""
    from proxy.services.portion_plan_service import portion_plan

    rows = [
        {"source_row": str(984 + n), "sheet": "СКС", "anchor": f"СКС!{984 + n}", "title": f"П{n}"}
        for n in range(6)
    ]
    first = portion_plan(
        rows=rows, limit=2, session_id="s1", source_revision=REVISION, cursors=cursors,
    )
    assert [row["source_row"] for row in first["rows"]] == ["984", "985"]

    # Закрыта только одна из двух показанных: вторая осталась без карточки.
    cursors.record_pass(session_id="s1", source_revision=REVISION, completed=["СКС!984"])
    second = portion_plan(
        rows=rows, limit=2, session_id="s1", source_revision=REVISION, cursors=cursors,
    )
    assert [row["source_row"] for row in second["rows"]] == ["985", "986"]
    assert second["pass_no"] == 2


def test_repeated_attempts_are_diagnostic_and_never_settle_the_row():
    """Число попыток не заменяет решение и не исключает строку из работы (T119.7)."""
    import tempfile
    from pathlib import Path

    from proxy.services.portion_cursor_service import PortionCursorService

    store = PortionCursorService(Path(tempfile.mkdtemp()) / "p.db")
    decision = {
        "source_row": "1", "norm_code": "",
        "coverage": "Карточки не вошли в пакет; требуется поиск",
    }
    first = store.record_pass(
        session_id="s1", source_revision=REVISION,
        completed={}, decisions={"СКС!1": decision}, declined=["СКС!1"], pass_id="p1",
    )
    assert first.completed == frozenset() and first.exhausted == frozenset()
    assert first.attempts["СКС!1"] == 1

    second = store.record_pass(
        session_id="s1", source_revision=REVISION,
        completed={}, decisions={"СКС!1": decision}, declined=["СКС!1"], pass_id="p2",
    )
    assert second.completed == frozenset(), "нехватка данных — не решение сметчика"
    assert "СКС!1" in second.exhausted, "повторные отказы видны отдельно"
    assert "СКС!1" not in second.settled, "попытки не закрывают строку"
    assert second.decisions["СКС!1"]["coverage"].startswith("Карточки не вошли")


def test_a_refused_row_that_later_gets_a_norm_is_closed_at_once(cursors):
    """Отказ не приговор: нашлась карточка — строка закрывается сразу."""
    cursors.record_pass(
        session_id="s1", source_revision=REVISION,
        completed={}, decisions={"СКС!1": {"source_row": "1", "norm_code": ""}},
        declined=["СКС!1"],
    )
    found = cursors.record_pass(
        session_id="s1", source_revision=REVISION,
        completed={"СКС!1": {"source_row": "1", "norm_code": "ГЭСНм10-01-055-01"}},
        declined=[],
    )
    assert "СКС!1" in found.completed
    assert found.decisions["СКС!1"]["norm_code"] == "ГЭСНм10-01-055-01"


def test_the_vor_remains_open_when_no_row_gets_a_norm(cursors):
    """Все незавершённые строки доступны после двух попыток (T119.7)."""
    from proxy.services.portion_plan_service import portion_plan

    rows = [
        {"source_row": str(n), "sheet": "СКС", "anchor": f"СКС!{n}", "title": f"Заглушка {n}"}
        for n in range(1, 6)
    ]
    for _pass in range(2):
        plan = portion_plan(
            rows=rows, limit=5, session_id="s1", source_revision=REVISION, cursors=cursors,
        )
        assert plan["rows"], "пока строки не закрыты, они обязаны показываться"
        anchors = [row["anchor"] for row in plan["rows"]]
        cursors.record_pass(
            session_id="s1", source_revision=REVISION, completed={},
            decisions={a: {"source_row": a.split("!")[1], "norm_code": ""} for a in anchors},
            declined=anchors, pass_id=f"pass-{_pass}",
        )
    final = portion_plan(
        rows=rows, limit=5, session_id="s1", source_revision=REVISION, cursors=cursors,
    )
    assert len(final["rows"]) == 5, "число попыток не исключает строки"
    assert final["complete"] is False
    assert final["completed"] == 0, "ни одна строка не решена"
    assert final["exhausted"] == 5, "все пять названы нерешёнными отдельно"
    assert len(final["unresolved"]) == 5


def test_delivering_the_same_result_twice_changes_nothing(cursors):
    """Повтор одного результата не двигает счётчик и не закрывает строку.

    Ревью Codex 11.09: два сбоя генерации до записи ничего об идемпотентности не
    доказывают — они проверяют случай, когда записи не было вовсе. Настоящий риск
    другой: запись прошла, а HTTP-ответ потерялся, и клиент повторил доставку.
    Без устойчивого идентификатора прохода такой повтор добавлял попытку и мог
    вывести строку из оборота на пустом месте.
    """
    payload = dict(
        session_id="s1", source_revision=REVISION,
        completed={"СКС!1": {"source_row": "1", "norm_code": "ГЭСНм10-01-055-01"}},
        decisions={"СКС!2": {"source_row": "2", "norm_code": ""}},
        declined=["СКС!2"],
        pass_id="answer-7f3a",
    )
    first = cursors.record_pass(**payload)
    again = cursors.record_pass(**payload)

    assert again.passes == first.passes == 1, "повтор — не новый проход"
    assert again.attempts == first.attempts, "повтор не добавляет попытку"
    assert again.completed == first.completed
    assert again.exhausted == frozenset(), "строка не должна уйти из оборота на повторе"


def test_a_different_pass_still_counts(cursors):
    """Защита от повтора не должна глушить настоящий следующий проход."""
    cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed={}, declined=["СКС!1"],
        decisions={"СКС!1": {"source_row": "1", "norm_code": ""}}, pass_id="first",
    )
    second = cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed={}, declined=["СКС!1"],
        decisions={"СКС!1": {"source_row": "1", "norm_code": ""}}, pass_id="second",
    )
    assert second.passes == 2
    assert second.attempts["СКС!1"] == 2
    assert "СКС!1" in second.exhausted


def test_a_pass_without_an_id_is_recorded_as_before(cursors):
    """Без идентификатора работаем как раньше: потерять проход хуже, чем задвоить."""
    cursors.record_pass(session_id="s1", source_revision=REVISION, completed={})
    twice = cursors.record_pass(session_id="s1", source_revision=REVISION, completed={})
    assert twice.passes == 2


def _legacy_store(tmp_path, rows):
    """Хранилище прежней схемы: is_closed без различия решения и исчерпанного лимита."""
    import sqlite3

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE smeta_portion_done (session_id TEXT NOT NULL, source_revision TEXT NOT NULL,"
        " anchor TEXT NOT NULL, decision_json TEXT NOT NULL DEFAULT '{}',"
        " is_closed INTEGER NOT NULL DEFAULT 1, attempts INTEGER NOT NULL DEFAULT 0,"
        " recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,"
        " PRIMARY KEY (session_id, source_revision, anchor))"
    )
    conn.execute(
        "CREATE TABLE smeta_portion_state (session_id TEXT NOT NULL, source_revision TEXT NOT NULL,"
        " passes INTEGER NOT NULL DEFAULT 0, artifact_revision_id TEXT,"
        " updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (session_id, source_revision))"
    )
    for anchor, decision, attempts in rows:
        conn.execute(
            "INSERT INTO smeta_portion_done VALUES ('s1',?,?,?,1,?,CURRENT_TIMESTAMP)",
            (REVISION, anchor, json.dumps(decision, ensure_ascii=False), attempts),
        )
    conn.commit()
    conn.close()
    return path


def test_old_state_is_migrated_by_the_decision_not_by_the_closed_flag(tmp_path):
    """Обновление установки не должно превращать исчерпанные строки в решённые.

    Ревью Codex 11.09: прежняя реализация закрывала флагом `is_closed` и строки с
    пустой нормой после двух попыток. Перенос всех таких записей в «решено» сохранил
    бы уже накопленную ошибку отчёта «всё закрыто» на существующей базе.
    """
    from proxy.services.portion_cursor_service import PortionCursorService

    path = _legacy_store(tmp_path, [
        ("СКС!1", {"source_row": "1", "norm_code": ""}, 2),
        ("СКС!2", {"source_row": "2", "norm_code": "ГЭСНм10-01-055-01"}, 0),
    ])
    progress = PortionCursorService(path).progress(session_id="s1", source_revision=REVISION)
    assert progress.completed == frozenset({"СКС!2"}), "решение — только там, где есть норма"
    assert progress.exhausted == frozenset({"СКС!1"}), "пустая норма остаётся нерешённой"


def test_recording_works_right_after_opening_an_old_store(tmp_path):
    """Первый же `record_pass` на старой базе не должен падать на отсутствующей колонке."""
    from proxy.services.portion_cursor_service import PortionCursorService

    path = _legacy_store(tmp_path, [("СКС!1", {"source_row": "1", "norm_code": "A"}, 0)])
    store = PortionCursorService(path)
    progress = store.record_pass(
        session_id="s1", source_revision=REVISION, completed={},
        artifact_revision_id="rev_1", artifact_decisions_revision="digest_1",
    )
    assert progress.artifact_revision_id == "rev_1"
    assert progress.artifact_decisions_revision == "digest_1"


def test_the_same_turn_with_a_different_answer_is_refused(cursors):
    """Тот же ключ хода с другим ответом — противоречие, а не повтор доставки."""
    cursors.record_pass(
        session_id="s1", source_revision=REVISION,
        completed={"СКС!1": {"source_row": "1", "norm_code": "A", "quantity": 2}},
        pass_id="turn-9", result_digest="digest-a",
    )
    after = cursors.record_pass(
        session_id="s1", source_revision=REVISION,
        completed={"СКС!1": {"source_row": "1", "norm_code": "A", "quantity": 7}},
        pass_id="turn-9", result_digest="digest-b",
    )
    assert after.decisions["СКС!1"]["quantity"] == 2, "историю нельзя переписать старым ключом"


def test_without_a_turn_id_every_pass_counts(cursors):
    """Без ключа хода два «Продолжай» подряд неотличимы — значит считаем каждый.

    Ревью Codex 11.09: отпечаток по содержимому склеивал три настоящих прохода с
    одинаковым пустым ответом в один, и строка никогда не исчерпывала попытки.
    """
    decision = {"source_row": "1", "norm_code": ""}
    for _ in range(3):
        progress = cursors.record_pass(
            session_id="s1", source_revision=REVISION, completed={},
            decisions={"СКС!1": decision}, declined=["СКС!1"],
        )
    assert progress.passes == 3
    assert progress.attempts["СКС!1"] == 3
    assert "СКС!1" in progress.exhausted


def test_a_rejected_choice_with_new_feedback_gets_another_chance(cursors):
    """Отказ расчёта с новым объяснением — шанс, а не потраченная попытка.

    Живой прогон 11.09, 08:45: две строки получили норму, расчёт отверг её по
    несовпадению измерителя — и обе тут же ушли из оборота, потому что одну попытку
    уже потратили в прошлом проходе на «норма не найдена». Причину отказа модель не
    увидела бы никогда, то есть вся обратная связь была бы мертворождённой.

    Счётчик попыток существует против бессмысленного круга. Новое объяснение кругом
    не является; повтор того же объяснения — является.
    """
    without_norm = {"source_row": "995", "norm_code": ""}
    first = cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed={},
        decisions={"СКС!995": without_norm}, declined=["СКС!995"],
    )
    assert first.attempts["СКС!995"] == 1

    with_norm = {"source_row": "995", "norm_code": "A", "rejected_reason": "unit_conflict"}
    fresh = cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed={},
        decisions={"СКС!995": with_norm}, rejected={"СКС!995": "unit_conflict"},
    )
    assert fresh.attempts["СКС!995"] == 0, "новое объяснение возвращает строку в оборот"
    assert "СКС!995" not in fresh.exhausted
    assert "СКС!995" not in fresh.completed, "отвергнутая привязка решением не становится"

    again = cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed={},
        decisions={"СКС!995": with_norm}, rejected={"СКС!995": "unit_conflict"},
    )
    assert again.attempts["СКС!995"] == 1, "тот же отказ второй раз — попытка"
    last = cursors.record_pass(
        session_id="s1", source_revision=REVISION, completed={},
        decisions={"СКС!995": with_norm}, rejected={"СКС!995": "unit_conflict"},
    )
    assert "СКС!995" in last.exhausted, "объяснение не помогло — круг остановлен"


def test_an_old_applied_table_gets_the_digest_column(tmp_path):
    """Первая же запись с ключом прохода на старой таблице не должна падать."""
    import sqlite3

    from proxy.services.portion_cursor_service import PortionCursorService

    path = tmp_path / "legacy-applied.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE smeta_portion_applied (session_id TEXT NOT NULL,"
        " source_revision TEXT NOT NULL, pass_id TEXT NOT NULL,"
        " recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,"
        " PRIMARY KEY (session_id, source_revision, pass_id))"
    )
    conn.commit()
    conn.close()

    store = PortionCursorService(path)
    progress = store.record_pass(
        session_id="s1", source_revision=REVISION,
        completed={"СКС!1": {"source_row": "1", "norm_code": "A"}},
        pass_id="turn-1", result_digest="digest-1",
    )
    assert "СКС!1" in progress.completed


def test_the_book_digest_notices_a_changed_source_row():
    """Смена длины бухты в наименовании меняет расчёт — значит и отпечаток книги.

    Ревью Codex 11.09: «(305 м)» → «(500 м)» даёт 366 против 600 измерителей, а
    отпечаток оставался прежним — книга считалась актуальной.
    """
    from proxy.services.portion_cursor_service import decisions_revision

    base = [{
        "source_row": "995", "norm_code": "ГЭСНм10-01-055-02", "quantity": 120,
        "unit": "шт.", "title": "Кабель UUTP4-C5E-305 (305 м)",
    }]
    changed = [{**base[0], "title": "Кабель UUTP4-C5E-500 (500 м)"}]
    assert decisions_revision(base) != decisions_revision(changed)


def test_scheduling_migration_preserves_legacy_decision_bytes(tmp_path):
    import sqlite3
    path = tmp_path/'legacy.sqlite'
    raw = '{"source_row":"S!1","norm_code":"N","quantity":2,"rejected_reason":"needs_basis"}'
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE smeta_portion_done (
            session_id TEXT, source_revision TEXT, anchor TEXT, decision_json TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP, is_closed INTEGER,
            attempts INTEGER, row_state TEXT,
            PRIMARY KEY(session_id, source_revision, anchor))''')
        conn.execute('INSERT INTO smeta_portion_done (session_id,source_revision,anchor,decision_json,is_closed,attempts,row_state) VALUES (?,?,?,?,?,?,?)',
                     ('s','r','S!1',raw,0,1,'open'))
    cursors = PortionCursorService(path)
    progress = cursors.progress(session_id='s',source_revision='r')
    assert progress.last_decision_pass == {'S!1': 0}
    assert progress.attempts == {'S!1': 1}
    assert not progress.completed
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT decision_json FROM smeta_portion_done').fetchone()[0] == raw
    # An old runtime can still select its original columns after additive migration.
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT anchor,is_closed,attempts,row_state FROM smeta_portion_done').fetchone() == ('S!1',0,1,'open')
