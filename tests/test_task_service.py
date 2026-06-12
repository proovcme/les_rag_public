"""W16.2: задачник — regex-команды и SQL, без LLM."""

import pytest

import proxy.services.task_service as ts


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "rag_meta_db_path", lambda: str(tmp_path / "meta.db"))


def test_create_list_close_cycle():
    task = ts.create_task("Проверить дымоудаление по корпусу Б", dataset_filter="NTD_FIRE")
    assert task["status"] == "open" and task["id"] == 1
    assert len(ts.list_tasks()) == 1
    ts.update_task(1, status="done")
    assert ts.get_task(1)["status"] == "done"


def test_update_validates_status():
    ts.create_task("Задача")
    with pytest.raises(ValueError):
        ts.update_task(1, status="неведомый")


# ── чат-команды ──

def test_chat_create_command():
    reply = ts.maybe_handle_task_command("поставь задачу проверить дымоудаление по корпусу Б", "NTD_FIRE")
    assert reply["operation"] == "task_create"
    assert "#1" in reply["answer"]
    assert ts.get_task(1)["dataset_filter"] == "NTD_FIRE"


def test_chat_create_variants():
    assert ts.maybe_handle_task_command("задача: позвонить в экспертизу")["operation"] == "task_create"
    assert ts.maybe_handle_task_command("создай задачу собрать ВОР по ОВ")["operation"] == "task_create"


def test_chat_list_command():
    ts.create_task("Первая")
    ts.create_task("Вторая")
    ts.update_task(1, status="done")
    reply = ts.maybe_handle_task_command("что по задачам?")
    assert reply["operation"] == "tasks_list"
    assert reply["count"] == 1  # одна активная
    assert "Вторая" in reply["answer"] and "Первая" in reply["answer"]


def test_chat_close_command():
    ts.create_task("Закрой меня")
    reply = ts.maybe_handle_task_command("задача 1 готова")
    assert reply["operation"] == "task_close"
    assert ts.get_task(1)["status"] == "done"


def test_chat_close_missing():
    reply = ts.maybe_handle_task_command("задача 99 готова")
    assert reply["count"] == 0


def test_regular_questions_pass_through():
    for q in (
        "Какие требования к путям эвакуации?",
        "Какая задача у противодымной вентиляции?",  # «задача» в середине смысла — не команда
        "Сколько задач решает СП 7?",
    ):
        assert ts.maybe_handle_task_command(q) is None, q
