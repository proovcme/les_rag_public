"""Расположение meta-хранилища выбирается при конструировании сервиса, а не при импорте модуля.

Дефект зафиксирован живым прогоном канонического гейта 15.10: сбор `942/943` был зелёным, а тот
же состав тестов при выставленной переменной окружения `RAG_META_DB_PATH` дал 4 падения в
`tests/test_model_query_checkpoint_draft.py` (при пустом хранилище — уже 8). Причина: значение
переменной считывалось один раз при импорте `proxy.config`, поэтому `monkeypatch.setenv` внутри
теста переставал влиять на сервис, собранный без явного пути, и тест читал не своё хранилище, а
чужое — результат зависит от того, что в чужом хранилище уже лежит.

Это не мелкость тестов: ровно тем же механизмом граница черновика в живом прогоне зависит от
расположения durable-состояния (задача № 92), а проверяющий на чистом worktree получает другой
результат, чем автор. Проверка дискриминации: при обоих значениях окружения (переменная выставлена
и не выставлена) тесты границы черновика обязаны давать один и тот же результат.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from proxy.config import meta_db_path
from proxy.memory_core.store import MemoryStore
from proxy.services.workbook_research_job_service import WorkbookResearchJobService


def test_meta_db_path_function_follows_the_env_on_every_call(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "first.db"))
    assert meta_db_path() == tmp_path / "first.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "second.db"))
    assert meta_db_path() == tmp_path / "second.db", (
        "meta_db_path() снова отдаёт значение, снятое при импорте модуля; тест, который меняет "
        "RAG_META_DB_PATH через monkeypatch, читает не своё хранилище")


def test_services_without_explicit_path_use_the_current_env_value(tmp_path, monkeypatch):
    target = tmp_path / "store.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(target))
    services = (WorkbookResearchJobService(), MemoryStore())
    for service in services:
        resolved = Path(str(service.db_path))
        assert resolved == target, (
            f"{type(service).__name__} построился с путём {resolved}, а окружение указывает на "
            f"{target}: путь зафиксирован при импорте, поэтому изоляция тестов по хранилищу "
            "иллюзорна")
        assert target.exists(), (
            "хранилище не создано по пути из окружения — записи сервиса уходят в другое место")


def test_explicit_path_argument_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "from-env.db"))
    explicit = tmp_path / "explicit.db"
    assert WorkbookResearchJobService(db_path=explicit).db_path == explicit
    assert Path(MemoryStore(db_path=explicit).db_path) == explicit, (
        "явный путь перестал быть приоритетнее окружения — вызывающий код не сможет задать своё "
        "хранилище")


def test_two_env_values_isolate_written_jobs(tmp_path, monkeypatch):
    first = tmp_path / "first.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(first))
    store_a = WorkbookResearchJobService()
    second = tmp_path / "second.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(second))
    store_b = WorkbookResearchJobService()
    assert store_a.db_path != store_b.db_path, (
        "два сервиса, построенные при разных значениях окружения, указывают на одно хранилище: "
        "тест с monkeypatch.setenv читает строки соседнего теста")
