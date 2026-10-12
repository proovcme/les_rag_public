"""Порционный разбор ведомости подключён к чату и переживает несколько проходов.

ЗАЧЕМ ЭТОТ ФАЙЛ. Два ревью Codex подряд поймали одно и то же: механизм написан,
покрыт зелёными тестами и при этом не вызывается из рабочего пути. Здесь проверяется
и место вызова в горячем пути, и весь цикл на настоящем хранилище прогресса.
"""

from __future__ import annotations

import inspect

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.portion_cursor_service import PortionCursorService


VOR_TEXT = "Файл: СКС.xlsx\n\n## Лист: СКС\nСКС!R1: № П.П | НАИМЕНОВАНИЕ РАБОТ И ЗАТРАТ | Артикул | ЕД. ИЗМ | ОБЪЕМ\n" + "".join(
    f"СКС!R{5 + n}: {983 + n} | Позиция {n} | ART-{n:03d} | шт. | {n}\n"
    for n in range(1, 13)
)


def test_hot_path_prepares_a_portion_before_the_model_sees_the_vor():
    """Вложение попадает к модели порцией, а не целиком."""
    source = inspect.getsource(service._execute_chat_evidence_application)

    prepared = source.index("attachment_context, portion_state = smeta_portion_context(")
    used = source.index("selector_evidence = selector_evidence_payload(")
    assert prepared < used, "порция обязана готовиться до сборки свидетельств"
    assert "cursors=portion_cursors" in source


def test_hot_path_records_the_pass_by_closed_rows():
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "closed_row_anchors(" in source
    assert "record_portion_pass(" in source
    recorded = source.index("record_portion_pass(")
    parsed = source.index("parsed_model_result = parse_model_rag_result(answer)")
    assert parsed < recorded, "проход засчитывается после разбора ответа модели"


def test_hot_path_builds_the_book_from_every_pass():
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert '"decisions": merged_decisions,' in source
    assert '"parent_revision_id": (' in source
    assert "merged_decisions = merged_pass_decisions(" in source


def test_closed_rows_are_only_those_with_a_norm():
    """Пустой шифр — предусмотренный ответ «карточек нет», строка вернётся позже."""
    closed = service.closed_row_anchors(
        [
            {"source_row": "984", "norm_code": "ГЭСНм10-01-001-01"},
            {"source_row": "985", "norm_code": ""},
            {"source_row": "986", "norm_code": "   "},
            {"source_row": "987", "norm_code": "ГЭСНм10-06-060-03"},
        ],
        ["СКС!984", "СКС!985", "СКС!986", "СКС!987"],
    )
    assert closed == ["СКС!984", "СКС!987"]


def test_a_row_outside_the_portion_does_not_move_the_cursor():
    """Решение по строке, которой в порции не было, засчитывать нельзя."""
    closed = service.closed_row_anchors(
        [{"source_row": "999", "norm_code": "ГЭСН01-01-001-01"}],
        ["СКС!984", "СКС!985"],
    )
    assert closed == []


def test_merged_decisions_keep_the_earlier_passes():
    merged = service.merged_pass_decisions(
        [{"source_row": "986", "norm_code": "C"}],
        closed=[],
        portion_state={
            "prior_decisions": {
                "СКС!984": {"source_row": "984", "norm_code": "A"},
                "СКС!985": {"source_row": "985", "norm_code": "B"},
            }
        },
    )
    assert [row["source_row"] for row in merged] == ["984", "985", "986"]


def test_a_row_decided_again_replaces_the_old_decision():
    merged = service.merged_pass_decisions(
        [{"source_row": "985", "norm_code": "НОВОЕ"}],
        closed=[],
        portion_state={
            "prior_decisions": {"СКС!985": {"source_row": "985", "norm_code": "СТАРОЕ"}}
        },
    )
    assert len(merged) == 1
    assert merged[0]["norm_code"] == "НОВОЕ"


@pytest.fixture()
def cursors(tmp_path):
    return PortionCursorService(tmp_path / "portions.db")


def test_three_passes_close_the_whole_vor_without_losing_a_row(cursors):
    """Полный цикл на настоящем хранилище: ведомость закрывается и книга растёт.

    Одна строка каждого прохода намеренно остаётся без нормы — так ведёт себя модель,
    когда карточек в пакете для неё не нашлось. Такая строка обязана вернуться, а не
    исчезнуть между проходами.
    """
    seen: list[list[str]] = []
    book: list[dict] = []
    for _pass in range(8):
        text, state = service.smeta_portion_context(
            VOR_TEXT, session_id="s1", limit=5, cursors=cursors,
        )
        if state["state"] == "complete":
            break
        seen.append(list(state["shown"]))
        # Пока ведомость не кончилась, последняя строка порции остаётся без нормы:
        # так ведёт себя модель, когда карточек для неё в пакете не нашлось.
        undecided = 1 if state["remaining"] else 0
        shown = state["shown"]
        rows = [
            {"source_row": anchor.split("!")[1], "norm_code": f"ГЭСНм10-01-{index:03d}-01"}
            for index, anchor in enumerate(shown[: len(shown) - undecided], 1)
        ]
        if undecided:
            rows.append({"source_row": shown[-1].split("!")[1], "norm_code": ""})
        closed = service.closed_row_anchors(rows, state["shown"])
        book = service.merged_pass_decisions(rows, closed=closed, portion_state=state)
        service.record_portion_pass(
            cursors,
            session_id="s1",
            portion_state=state,
            rows=rows,
            closed=closed,
            artifact_revision_id=f"rev_{_pass}",
            trace=None,
        )

    # Незакрытая строка каждой порции возвращается следующей.
    assert seen[0][-1] == seen[1][0], "строка без нормы обязана вернуться в следующий проход"
    assert seen[1][-1] == seen[2][0]

    closed_total = cursors.progress(session_id="s1", source_revision="").completed
    progress = cursors.progress(
        session_id="s1",
        source_revision=service.smeta_portion_context(
            VOR_TEXT, session_id="s1", limit=5, cursors=None,
        )[1]["source_revision"],
    )
    assert len(progress.completed) == 12, "закрыты все двенадцать позиций ведомости"
    assert progress.artifact_revision_id, "ревизия книги сохранена для склейки"
    assert closed_total == frozenset()

    numbers = [str(row["source_row"]) for row in book]
    assert len(numbers) == len(set(numbers)), "строка не должна попасть в книгу дважды"
    assert len(numbers) == 12, "книга последнего прохода обязана нести всю ведомость"
    assert numbers == sorted(numbers), "порядок ведомости сохранён"


def test_the_last_pass_reports_completion_instead_of_the_whole_vor(cursors):
    _text, state = service.smeta_portion_context(
        VOR_TEXT, session_id="s2", limit=50, cursors=cursors,
    )
    rows = [
        {"source_row": anchor.split("!")[1], "norm_code": "ГЭСНм10-01-001-01"}
        for anchor in state["shown"]
    ]
    closed = service.closed_row_anchors(rows, state["shown"])
    service.record_portion_pass(
        cursors, session_id="s2", portion_state=state, rows=rows, closed=closed,
        artifact_revision_id="rev_final", trace=None,
    )
    text, done = service.smeta_portion_context(
        VOR_TEXT, session_id="s2", limit=50, cursors=cursors,
    )
    assert done["state"] == "complete"
    assert done["rows_in_pass"] == 0
    assert "Позиция 1 |" not in text
    assert len(text) < 200


def test_a_broken_store_does_not_swallow_the_answer(cursors):
    class _Broken:
        def record_pass(self, **_kwargs):
            raise RuntimeError("диск занят")

    trace: dict = {}
    closed = service.record_portion_pass(
        _Broken(),
        session_id="s1",
        portion_state={"source_revision": "r", "state": "portion"},
        rows=[{"source_row": "984", "norm_code": "A"}],
        closed=["СКС!984"],
        artifact_revision_id=None,
        trace=trace,
    )
    assert closed == 0
    assert trace["smeta_portion_recorded"] is False


def test_unfinished_vor_keeps_the_attachment_for_the_next_message():
    """«Продолжай» работает только если интерфейс сохранил скрепку.

    Интерфейс держит файл ровно столько, сколько просит сервер (`attachment_retry`).
    Пока ведомость не закрыта, сервер обязан просить.
    """
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert '"preserved": True,' in source
    kept = source.index('if portion_state.get("state") == "portion" and portion_state.get("pending"):')
    assert kept > source.index("response.update(workbook_chat_meta)")

    from sovushka.pages.chat import _preserved_attachment

    sent = {"id": "att-1", "mode": "read", "text": "…", "name": "СКС.xlsx"}
    unfinished = {
        "attachment_retry": {"attachment_id": "att-1", "id": "att-1", "preserved": True}
    }
    assert _preserved_attachment(unfinished, sent) == sent
    assert _preserved_attachment({}, sent) == {}


def test_the_book_is_rebuilt_from_stored_decisions_without_asking_the_model():
    """Повтор упаковки идёт по сохранённым решениям и не трогает модель.

    Ревью Codex 11.09: прежняя пересборка требовала состояния «ведомость закрыта», а
    штатный отказ упаковщика оставляет ведомость открытой — то есть не покрывался вовсе.
    И просить модель пройти те же строки заново нельзя: её ответ мог бы отличаться, и
    книга перестала бы соответствовать записанному решению.
    """
    import asyncio

    calls: list[dict] = []

    async def executor(call, context, progress):
        calls.append(call)
        return {
            "schema": "les.workbook_tool_result.v1",
            "status": "complete",
            "artifact": {
                "revision_id": "rev_rebuilt", "artifact_kind": "lsr_workbook",
                "download_url": "/api/artifacts/rev_rebuilt", "filename": "LSR.xlsx",
                "source_scope": ["attachment:att-1"], "decision_checkpoint_id": "cp-1",
            },
            "source": {"attachment_id": "att-1", "sha256": "a" * 64},
            "checkpoint": {"checkpoint_id": "cp-1", "status": "complete"},
        }

    state = {
        "prior_decisions": {
            "СКС!985": {"source_row": "985", "norm_code": "B"},
            "СКС!984": {"source_row": "984", "norm_code": "A"},
        },
        "source_anchors": ["СКС!984", "СКС!985", "СКС!986"],
        "artifact_revision_id": "rev_old",
    }
    trace: dict = {}
    harvested = asyncio.run(
        service.rebuild_workbook_from_stored_decisions(
            executor=executor, portion_state=state, attachment_id="att-1",
            question="Собери смету", context={"session_id": "s1"},
            progress=(lambda _e: asyncio.sleep(0)), trace=trace,
        )
    )
    assert harvested["artifact"]["revision_id"] == "rev_rebuilt"
    assert trace["smeta_portion_rebuild"] == "rebuilt"
    assert len(calls) == 1, "одна упаковка и ни одного обращения к модели"

    args = calls[0]["args"]
    assert [row["source_row"] for row in args["decisions"]] == ["984", "985"], (
        "решения берутся из хранилища в порядке ведомости, а не из нового ответа"
    )
    assert args["parent_revision_id"] == "rev_old", "родословная книги сохранена"


def test_a_failed_rebuild_does_not_break_the_answer():
    import asyncio

    async def broken(_call, _context, _progress):
        raise RuntimeError("диск занят")

    trace: dict = {}
    assert asyncio.run(
        service.rebuild_workbook_from_stored_decisions(
            executor=broken,
            portion_state={"prior_decisions": {"СКС!1": {"source_row": "1", "norm_code": "A"}}},
            attachment_id="att-1", question="q", context={},
            progress=(lambda _e: asyncio.sleep(0)), trace=trace,
        )
    ) == {}
    assert trace["smeta_portion_rebuild"] == "failed"


def test_the_rebuild_runs_before_any_model_call():
    """Пересборка обязана стоять до исследования и до ответа модели."""
    source = inspect.getsource(service._execute_chat_evidence_application)

    rebuild = source.index("rebuilt_meta = await rebuild_workbook_from_stored_decisions(")
    research = source.index("model_research_tools.execute(")
    answer = source.index("govern_inference_messages(")
    assert rebuild < research, "пересборка идёт раньше исследования"
    assert rebuild < answer, "пересборка идёт раньше запроса ответа"


def test_a_stale_book_is_told_apart_from_a_missing_one():
    """«Ревизии книги нет» — не то же самое, что «книга соответствует решениям»."""
    from proxy.services.portion_cursor_service import decisions_revision

    stored = {"СКС!1": {"source_row": "1", "norm_code": "A", "quantity": 2, "unit": "шт."}}
    fresh = {
        "prior_decisions": stored,
        "artifact_revision_id": "rev_1",
        "artifact_decisions_revision": decisions_revision(stored),
    }
    assert service.stored_decisions_need_a_workbook(fresh) is False

    grown = dict(stored)
    grown["СКС!2"] = {"source_row": "2", "norm_code": "B", "quantity": 1, "unit": "шт."}
    stale = {**fresh, "prior_decisions": grown}
    assert service.stored_decisions_need_a_workbook(stale) is True, (
        "книга прошлой порции не должна сходить за актуальную"
    )
    assert service.stored_decisions_need_a_workbook({"prior_decisions": {}}) is False


def test_a_just_built_book_is_not_stale():
    """Отпечаток решений обязан совпасть сразу после сборки.

    Ревью Codex 11.09: одна функция строила отпечаток по якорям «S!1», другая по
    номерам «1» — только что собранная книга немедленно числилась устаревшей и
    пересобиралась на каждом запросе.
    """
    from proxy.services.portion_cursor_service import decisions_revision

    packed = [{"source_row": "1", "norm_code": "A", "quantity": 2, "unit": "шт."}]
    stored = {"СКС!1": dict(packed[0])}
    assert decisions_revision(packed) == decisions_revision(stored), (
        "упаковка и хранилище обязаны считать одну ревизию"
    )
    assert service.stored_decisions_need_a_workbook({
        "prior_decisions": stored,
        "artifact_revision_id": "rev_1",
        "artifact_decisions_revision": decisions_revision(packed),
    }) is False


def test_the_revision_notices_a_changed_coefficient():
    """Коэффициент влияет на расчёт — значит и на отпечаток."""
    from proxy.services.portion_cursor_service import decisions_revision

    base = [{"source_row": "1", "norm_code": "A", "quantity": 2, "unit": "шт.", "coefficient": 1}]
    changed = [{**base[0], "coefficient": 1.5}]
    assert decisions_revision(base) != decisions_revision(changed)


def test_unit_conflicts_reach_the_chat_answer():
    """Причина, по которой строка не попала в расчёт, обязана дойти до пользователя.

    Живой прогон 11.09: из 48 решений в книгу попали 30, восемнадцать отброшены с
    unit_conflict — «шт.» против измерителя «100 м». Книга со статусом partial внешне
    неотличима от полной, а в чате об этом не было ни слова (ревью Codex 11.09).
    """
    harvested = service.harvest_workbook_tool_result({
        "schema": "les.workbook_tool_result.v1",
        "status": "partial",
        "missing": ["row:987:unit_conflict", "row:995:unit_conflict"],
        "blockers": [],
        "artifact": {
            "revision_id": "r1", "source_scope": ["attachment:a1"],
            "decision_checkpoint_id": "cp1",
        },
        "source": {"attachment_id": "a1", "sha256": "a" * 64},
        "checkpoint": {"checkpoint_id": "cp1", "status": "complete"},
    })
    diagnostics = harvested["workbook_diagnostics"]
    assert diagnostics["status"] == "partial"
    assert diagnostics["unbound_rows"] == ["row:987:unit_conflict", "row:995:unit_conflict"]


def test_a_complete_book_carries_no_diagnostics():
    """Полная книга не должна нести пустой раздел проблем."""
    harvested = service.harvest_workbook_tool_result({
        "schema": "les.workbook_tool_result.v1",
        "status": "complete", "missing": [], "blockers": [],
        "artifact": {
            "revision_id": "r1", "source_scope": ["attachment:a1"],
            "decision_checkpoint_id": "cp1",
        },
        "source": {"attachment_id": "a1", "sha256": "a" * 64},
        "checkpoint": {"checkpoint_id": "cp1", "status": "complete"},
    })
    assert "workbook_diagnostics" not in harvested


def test_a_rejected_binding_comes_back_to_the_model_with_the_reason():
    """Строку, чью привязку отверг расчёт, нельзя считать решённой.

    Живой прогон 11.09: из 48 решений в книгу попали 30, восемнадцать отброшены с
    unit_conflict. Они числились решёнными и к модели больше не возвращались — то
    есть смета молча теряла их навсегда. Теперь строка возвращается вместе с
    причиной, чтобы модель пересмотрела выбор, а не предложила ту же норму снова.
    """
    import tempfile
    from pathlib import Path

    from proxy.services.portion_cursor_service import PortionCursorService

    store = PortionCursorService(Path(tempfile.mkdtemp()) / "p.db")
    state = {
        "source_revision": "r1",
        "shown": ["СКС!987", "СКС!988"],
        "prior_decisions": {},
        "source_anchors": ["СКС!987", "СКС!988"],
    }
    rows = [
        {"source_row": "987", "norm_code": "ГЭСНм10-01-055-02", "unit": "шт.", "quantity": 4},
        {"source_row": "988", "norm_code": "ГЭСНм08-05-045-04", "unit": "шт.", "quantity": 2},
    ]
    trace: dict = {}
    service.record_portion_pass(
        store, session_id="s1", portion_state=state, rows=rows,
        closed=["СКС!987", "СКС!988"], artifact_revision_id="rev_1",
        rejected={"987": "unit_conflict"}, trace=trace,
    )
    progress = store.progress(session_id="s1", source_revision="r1")
    assert progress.completed == frozenset({"СКС!988"}), "отвергнутая привязка — не решение"
    assert progress.attempts["СКС!987"] == 0, (
        "объяснение модель видит впервые — строка возвращается в оборот, а не тратит попытку"
    )
    assert "СКС!987" not in progress.exhausted
    assert progress.decisions["СКС!987"]["rejected_reason"] == "unit_conflict"
    assert trace["smeta_portion_rejected"] == 1


def test_the_reason_is_shown_next_to_the_row_in_plain_words():
    """Модель должна прочесть причину, а не код ошибки."""
    rows = [{
        "source_row": "987", "anchor": "СКС!987", "title": "Блок розеток",
        "unit": "шт.", "quantity": 4, "raw": "987 | Блок розеток | шт. | 4",
    }]
    notes = service._previous_rejections({
        "СКС!987": {"norm_code": "ГЭСНм10-01-055-02", "rejected_reason": "unit_conflict"},
        "СКС!988": {"norm_code": "ГЭСН1"},
        # Отметка прежней версии: выбора не было, а не он отклонён.
        "СКС!989": {"norm_code": "", "rejected_reason": "norm_selection_required"},
    })
    assert set(notes) == {"СКС!987"}, "пометку получает только отвергнутый выбор"
    text = service.attachment_portion_text(
        rows, limit=5, name="СКС.xlsx", rejected=notes,
    )
    assert "[Прошлый выбор отклонён]" in text
    assert "ГЭСНм10-01-055-02" in text
    assert "измеритель" in text
    assert "unit_conflict" not in text, "модели нужен смысл, а не код"


def test_a_decision_keeps_what_it_was_based_on():
    """Ссылка Q1.H1 живёт один проход — рядом с решением остаётся её расшифровка.

    Ревью Codex 11.09: без снимка по сохранённому решению нельзя проверить, на что
    модель опиралась, — на следующем проходе тот же номер указывает на другую
    карточку. Для воспроизводимой сверки нужны запрос, шифр карточки, её источник и
    отпечаток ровно того текста, который ушёл модели.
    """
    import tempfile
    from pathlib import Path

    from proxy.services.portion_cursor_service import PortionCursorService

    class _Chunk:
        def __init__(self, ref, query, code, body):
            self.meta = {"model_evidence_ref": ref, "model_query": query, "norm_code": code}
            self.content = body
            self.doc_name = "smeta_norm_cards.v1"
            self.score = 0.87

    chunks = [
        _Chunk("Q1.H1", "прокладка кабеля в сетях связи", "ГЭСНм10-01-055-02", "Шифр: ГЭСНм10…"),
        _Chunk("Q2.H1", "заземление оборудования", "ГЭСНм08-05-045-04", "Шифр: ГЭСНм08…"),
    ]
    rows = [
        {"source_row": "987", "norm_code": "ГЭСНм10-01-055-02", "evidence_refs": ["Q1.H1"]},
        {"source_row": "988", "norm_code": "", "evidence_refs": []},
    ]
    store = PortionCursorService(Path(tempfile.mkdtemp()) / "p.db")
    state = {
        "source_revision": "r1", "shown": ["СКС!987", "СКС!988"],
        "prior_decisions": {}, "source_anchors": ["СКС!987", "СКС!988"],
    }
    service.record_portion_pass(
        store, session_id="s1", portion_state=state, rows=rows,
        closed=["СКС!987"], artifact_revision_id="rev_1",
        evidence=service.evidence_snapshot(rows, chunks),
    )
    stored = store.progress(session_id="s1", source_revision="r1").decisions["СКС!987"]
    snapshot = stored["evidence_snapshot"]
    assert len(snapshot) == 1
    assert snapshot[0]["query"] == "прокладка кабеля в сетях связи", "запрос, а не только номер"
    assert snapshot[0]["norm_code"] == "ГЭСНм10-01-055-02"
    assert snapshot[0]["sent_sha256"], "отпечаток отправленного текста карточки"
    assert snapshot[0]["sent_chars"] > 0

    without = store.progress(session_id="s1", source_revision="r1").decisions["СКС!988"]
    assert "evidence_snapshot" not in without, "строке без ссылок снимок не нужен"


def test_the_snapshot_records_the_text_actually_sent():
    """Отпечаток берётся с обрезанного тела, а не с исходной карточки.

    Упаковщик режет тело под бюджет; сверять надо то, что модель прочла.
    """
    import hashlib

    class _Chunk:
        meta = {"model_evidence_ref": "Q1.H1", "model_query": "q", "norm_code": "A"}
        content = "Шифр: A. Наименование…"
        doc_name = "cards"
        score = 0.5

    snapshot = service.evidence_snapshot(
        [{"source_row": "1", "evidence_refs": ["q1.h1"]}], [_Chunk()],
    )
    expected = hashlib.sha256(_Chunk.content.encode("utf-8")).hexdigest()[:16]
    assert snapshot["1"][0]["sent_sha256"] == expected
    assert snapshot["1"][0]["sent_chars"] == len(_Chunk.content)


def test_a_row_without_a_norm_is_not_called_a_rejected_choice():
    """«Норма не выбрана» — отсутствие выбора, а не его отклонение.

    Живой прогон 11.09, 08:06: упаковщик пометил 21 строку из 25 как
    `norm_selection_required` — модель просто не выбрала для них норму. Считать это
    отказом расчёта значило бы сказать ей «твой выбор отклонён» там, где выбора не
    было, и завысить число отвергнутых привязок.
    """
    reasons = service.rejected_row_reasons({
        "workbook_diagnostics": {
            "unbound_rows": [
                "row:987:unit_conflict",
                "row:988:norm_selection_required",
                "row:989:norm_not_found",
            ],
        },
    })
    assert reasons == {"987": "unit_conflict", "989": "norm_not_found"}


def test_the_rebuild_never_holds_the_answer_hostage():
    """Пересборка — удобство, а не обязательство: не уложилась, идём обычным путём.

    11.09, 08:50: проход простоял 35 минут без единой строки в журнале. Причиной
    оказался сон машины, а не код, — но шаг, который делается до ответа и не имеет
    ни потолка, ни следа в логе, всё равно неверен. Книгу соберёт конец прохода.
    """
    import asyncio

    async def slow(_call, _context, _progress):
        await asyncio.sleep(30)
        return {}

    original = service.REBUILD_TIMEOUT_SECONDS
    service.REBUILD_TIMEOUT_SECONDS = 0.2
    try:
        trace: dict = {}
        result = asyncio.run(
            service.rebuild_workbook_from_stored_decisions(
                executor=slow,
                portion_state={"prior_decisions": {"СКС!1": {"source_row": "1", "norm_code": "A"}}},
                attachment_id="a1", question="q", context={},
                progress=(lambda _e: asyncio.sleep(0)), trace=trace,
            )
        )
    finally:
        service.REBUILD_TIMEOUT_SECONDS = original
    assert result == {}, "без книги ответ хуже, но он есть"
    assert trace["smeta_portion_rebuild"] == "timeout"


def test_the_rebuild_leaves_a_trace_in_the_log():
    """Шаг до ответа обязан быть виден в журнале — иначе его не отличить от зависания."""
    import inspect

    source = inspect.getsource(service._execute_chat_evidence_application)
    assert "[SMETA_PORTION] пересборка книги по %s сохранённым решениям" in source
    assert "REBUILD_TIMEOUT_SECONDS" in inspect.getsource(
        service.rebuild_workbook_from_stored_decisions
    )


def test_each_card_keeps_its_own_query():
    """Снимок обязан помнить запрос своей карточки, а не последний запрос прохода.

    Ревью Codex 11.09: переменная цикла к моменту сборки меты держала последний
    запрос, и все карточки получали его один на всех. Диагностика происхождения —
    «модель искала монтаж короба для строки с кабелем» — строилась на этом искажении
    и должна перепроверяться по транспорту.
    """
    class _Hit:
        def __init__(self, code):
            self.doc_name = "smeta_norm_cards.v1"
            self.score = 0.9
            self.content = f"Шифр: {code}. " + "Наименование работы. " * 12
            self.meta = {"norm_code": code}

    groups, chunks = service.build_model_rag_evidence_groups(
        [
            ("прокладка кабеля витая пара", [_Hit("ГЭСНм10-01-055-02")]),
            ("монтаж короба", [_Hit("ГЭСНм08-04-750-03")]),
        ],
        max_chars=6000, hits_per_query=2,
    )
    assert len(groups) == 2
    by_ref = {c.meta["model_evidence_ref"]: c.meta["model_query"] for c in chunks}
    assert by_ref["Q1.H1"] == "прокладка кабеля витая пара"
    assert by_ref["Q2.H1"] == "монтаж короба"

    snapshot = service.evidence_snapshot(
        [
            {"source_row": "995", "evidence_refs": ["Q1.H1"]},
            {"source_row": "1012", "evidence_refs": ["Q2.H1"]},
        ],
        chunks,
    )
    assert snapshot["995"][0]["query"] == "прокладка кабеля витая пара"
    assert snapshot["1012"][0]["query"] == "монтаж короба"
