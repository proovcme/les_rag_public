"""Подготовка контекста одного прохода: порция ведомости плюс её описание в трассе.

Связывает готовые части в то, что вызывается из горячего пути чата. Проверяется именно
результат подготовки — что уйдёт модели и что увидит следующий проход.
"""

from __future__ import annotations

from proxy.services.chat_evidence_application_service import smeta_portion_context


TEXT = """Файл: СКС (2).xlsx

## Лист: СКС
СКС!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | Артикул | Производитель | ЕД. ИЗМ | ОБЪЕМ
СКС!R6: 984 | Шкаф напольный 42U | TTR-4281 | Hyperline | шт. | 2
СКС!R7: 985 | Кабельный организатор | CM-1U-ML | Hyperline | шт. | 8
СКС!R8: 986 | Шина заземления | TGRD-19 | Hyperline | шт. | 2
СКС!R9: 987 | Блок розеток | SHE19 | Hyperline | шт. | 4
"""

ANCHORS = ("СКС!984", "СКС!985", "СКС!986", "СКС!987")


class _Cursors:
    def __init__(self, completed: tuple[str, ...] = (), passes: int = 0) -> None:
        self.completed = frozenset(completed)
        self.passes = passes

    def progress(self, *, session_id: str, source_revision: str):
        return type(
            "P",
            (),
            {"completed": self.completed, "passes": self.passes, "artifact_revision_id": None},
        )()


def test_first_pass_gets_a_portion_and_describes_it():
    text, plan = smeta_portion_context(TEXT, session_id="s1", limit=2, cursors=_Cursors())
    assert "984 | Шкаф напольный 42U" in text
    assert "986 | Шина заземления" not in text
    assert plan["state"] == "portion"
    assert plan["pass_no"] == 1
    assert plan["remaining"] == 2
    assert plan["shown"] == ["СКС!984", "СКС!985"]
    assert plan["last_row"] == "СКС!985"
    assert plan["total"] == 4


def test_portion_keeps_the_whole_source_row():
    """Артикул и производитель различают похожие позиции — порция их не теряет."""
    text, _plan = smeta_portion_context(TEXT, session_id="s1", limit=2, cursors=_Cursors())
    assert "TTR-4281" in text and "Hyperline" in text
    assert "Ячейки строк ниже означают:" in text, "шапка объясняет, что значит каждая ячейка"


def test_second_pass_continues_from_the_closed_rows():
    text, plan = smeta_portion_context(
        TEXT, session_id="s1", limit=2, cursors=_Cursors(completed=ANCHORS[:2], passes=1),
    )
    assert "986 | Шина заземления" in text
    assert "984 | Шкаф" not in text
    assert plan["pass_no"] == 2
    assert plan["final_portion"] is True
    assert plan["last_row"] == "СКС!987"


def test_text_without_a_vor_is_left_alone():
    """Не всякое вложение — ведомость: письмо или договор идут как есть."""
    text, plan = smeta_portion_context(
        "Файл: письмо.docx\n\nДобрый день!", session_id="s1", limit=5, cursors=None,
    )
    assert text == "Файл: письмо.docx\n\nДобрый день!"
    assert plan["state"] == "not-a-vor"
    assert plan["total"] == 0
    assert plan["rows_in_pass"] == 0
    assert plan["complete"] is False, "нераспознанное вложение — не пройденная ведомость"


def test_short_vor_goes_whole_in_one_pass():
    text, plan = smeta_portion_context(TEXT, session_id="s1", limit=50, cursors=_Cursors())
    assert all(number in text for number in ("984", "985", "986", "987"))
    assert plan["final_portion"] is True
    assert plan["remaining"] == 0
    assert plan["rows_in_pass"] == 4


def test_closed_vor_is_not_handed_back_whole():
    """Разобранная ведомость не возвращается целиком — иначе окно съедается заново.

    Ревью Codex 10.09 (R5): при пустой порции `or text` отдавал исходное вложение,
    одновременно сообщая rows_in_pass=0 и complete=True.
    """
    text, plan = smeta_portion_context(
        TEXT, session_id="s1", limit=2, cursors=_Cursors(completed=ANCHORS, passes=2),
    )
    assert plan["state"] == "complete"
    assert plan["complete"] is True
    assert plan["rows_in_pass"] == 0
    assert "985 | Кабельный организатор" not in text
    assert "решение принято по 4 позициям из 4" in text
    assert "нерешённ" not in text, "нерешённых нет — и говорить о них незачем"
    assert len(text) < len(TEXT) / 2


def test_renaming_the_file_does_not_restart_the_vor():
    """Ревизия считается по строкам: то же содержимое под другим именем — тот же разбор."""
    renamed = TEXT.replace("СКС (2).xlsx", "СКС (копия).xlsx")
    _text, first = smeta_portion_context(TEXT, session_id="s1", limit=2, cursors=_Cursors())
    _text, second = smeta_portion_context(renamed, session_id="s1", limit=2, cursors=_Cursors())
    assert first["source_revision"] == second["source_revision"]

    changed = TEXT.replace("| шт. | 8", "| шт. | 9")
    _text, third = smeta_portion_context(changed, session_id="s1", limit=2, cursors=_Cursors())
    assert third["source_revision"] != first["source_revision"], "другая ведомость — другой разбор"


MULTI_SHEET = """Файл: Книга.xlsx

## Лист: СКС
СКС!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | ЕД. ИЗМ | ОБЪЕМ
СКС!R2: 1 | Розетка RJ45 | шт. | 40
СКС!R3: 2 | Кабель UTP | м | 1200

## Лист: ЭОМ
ЭОМ!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | ЕД. ИЗМ | ОБЪЕМ
ЭОМ!R2: 1 | Щит распределительный | шт. | 3
ЭОМ!R3: 2 | Автомат 16А | шт. | 24
"""


def test_positions_repeat_across_sheets_without_confusing_the_cursor():
    """Позиция №1 есть на каждом листе — якорь обязан их различать (ревью Codex, R3)."""
    _text, first = smeta_portion_context(MULTI_SHEET, session_id="s1", limit=2, cursors=_Cursors())
    assert first["shown"] == ["СКС!1", "СКС!2"]

    text, second = smeta_portion_context(
        MULTI_SHEET, session_id="s1", limit=2,
        cursors=_Cursors(completed=("СКС!1", "СКС!2"), passes=1),
    )
    assert second["shown"] == ["ЭОМ!1", "ЭОМ!2"]
    assert "Щит распределительный" in text
    assert "Розетка RJ45" not in text, "второй проход не топчется на первом листе"


def test_multisheet_portion_tells_the_model_how_to_name_a_row():
    """Неоднозначный номер блокирует упаковку — значит указание должно быть явным.

    В многолистовой книге позиция №1 есть на каждом листе, и ответ «1» не привязывается
    ни к одной строке: проверка структуры помечает его `invalid_portion_source_row`,
    прогресс не записывается. Без прямого требования копировать идентификатор модель
    повторяла бы такой ответ каждый проход, и строка не закрылась бы никогда.
    """
    text, plan = smeta_portion_context(MULTI_SHEET, session_id="s9", limit=5, cursors=_Cursors())
    assert "[Строка ВОР: source_row=СКС!1]" in text
    assert "source_row" in text and "целиком" in text
    assert "[Лист] ЭОМ" in text

    from proxy.smeta_core.vor_rows import decision_anchor

    assert decision_anchor({"source_row": "СКС!1"}, plan["shown"]) == "СКС!1"
    assert decision_anchor({"source_row": "1"}, plan["shown"]) == "", "догадка о листе запрещена"


def test_single_sheet_portion_stays_short():
    """На одном листе номер однозначен — лишних пометок и указаний быть не должно."""
    text, _plan = smeta_portion_context(TEXT, session_id="s10", limit=2, cursors=_Cursors())
    assert "[Строка ВОР" not in text
    assert "несколько листов" not in text


def test_the_closing_message_separates_decided_from_unresolved():
    """Сообщение о конце обязано называть нерешённые позиции, а не прятать их в итог.

    Ревью Codex 11.09: «закрыто 70 из 70» смешивало выбранные нормы с позициями, по
    которым норма не нашлась и попытки кончились. Это разные вещи, и сметчику важна
    именно вторая.
    """
    import tempfile
    from pathlib import Path

    from proxy.services.chat_evidence_application_service import (
        closed_row_anchors, record_portion_pass,
    )
    from proxy.services.portion_cursor_service import PortionCursorService

    store = PortionCursorService(Path(tempfile.mkdtemp()) / "p.db")
    rows = [
        {"source_row": "984", "norm_code": "ГЭСНм10-01-055-01"},
        {"source_row": "985", "norm_code": ""},
        {"source_row": "986", "norm_code": ""},
        {"source_row": "987", "norm_code": ""},
    ]
    for attempt in (1, 2):
        _text, state = smeta_portion_context(TEXT, session_id="s7", limit=10, cursors=store)
        record_portion_pass(
            store, session_id="s7", portion_state=state, rows=rows,
            closed=closed_row_anchors(rows, state["shown"]),
            artifact_revision_id=None, pass_id=f"try-{attempt}",
        )
    text, done = smeta_portion_context(TEXT, session_id="s7", limit=10, cursors=store)
    assert done["state"] == "complete"
    assert done["completed"] == 1, "норма выбрана по одной позиции"
    assert done["exhausted"] == 3, "по трём норма не найдена"
    assert "по 1 позициям из 4" in text
    assert "3 позициям норма так и не найдена" in text
