"""ADR-12 (Ц9): табличные приложения норм поднимаются в ретриве (офлайн).

Фикстура — синтетические чанки type=table_row/markdown с pipe-таблицей и doc_name,
без живого Qdrant. Проверяем:
  • интент-детектор ловит «табличные» запросы (перечень/приложение/помещения);
  • fetch_table_appendix_chunks тянет ТОЛЬКО pipe-table чанки узлов-документов;
  • merge аддитивен и дедуплицирует;
  • guarantee_table_appendix поднимает приложение в видимое окно, когда реранк
    утопил его под прозой — и НЕ трогает порядок, если приложение уже в окне;
  • без интента / без узлов / пустой scope — полный no-op (флат не страдает).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from proxy.services.table_appendix_service import (
    fetch_table_appendix_chunks,
    guarantee_table_appendix,
    has_table_intent,
    merge_table_appendix,
    table_appendix_enabled,
)


@dataclass
class Chunk:
    content: str
    doc_name: str
    score: float = 1.0
    meta: dict = field(default_factory=dict)


_LOG = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)


class ScopedBackend:
    """Бэкенд, который по doc_filter отдаёт смесь прозы и pipe-таблиц СП 486."""

    def __init__(self):
        self.calls = []

    async def retrieve(self, query, dataset_ids=None, top_k=5, doc_filter=None):
        self.calls.append({"query": query, "doc_filter": doc_filter, "top_k": top_k})
        # Прозовые чанки (высокий «семантический» приоритет) + табличное приложение.
        prose = [
            Chunk("5.1 Общие положения СПА проектируются...", "СП 484.1311500.2020.docx", 0.66),
            Chunk("10.3 Требования к защищаемым помещениям...", "СП 485.1311500.2020.docx", 0.65),
        ]
        tables = [
            Chunk(
                "| N | Объект защиты | Нормативный показатель | | --- | --- | --- | "
                "| 1 | Серверные, помещения с ЭВМ | АУПТ независимо от площади |",
                "СП 486.1311500.2020.docx", 0.59,
            ),
            Chunk(
                "| 18.2 | Автозалы АТС | Независимо от площади | "
                "| 19 | Коммутационное оборудование | АУПС |",
                "СП 486.1311500.2020.docx", 0.58,
            ),
        ]
        result = prose + tables
        return result[:top_k]


def test_has_table_intent_detects_appendix_questions():
    assert has_table_intent("В каких помещениях требуется АУПТ? перечень помещений")
    assert has_table_intent("требования к серверным")
    assert has_table_intent("приложение с категориями помещений")
    # Не-табличный нормативный вопрос — интент НЕ срабатывает (boost остаётся no-op).
    assert not has_table_intent("какая минимальная ширина эвакуационного выхода")
    assert not has_table_intent("найди пункт 7.3 в СП 7.13130")


@pytest.mark.asyncio
async def test_fetch_returns_only_pipe_tables_from_nodes():
    assert table_appendix_enabled()  # дефолт-вкл
    backend = ScopedBackend()
    out = await fetch_table_appendix_chunks(
        question="перечень помещений под АУПТ таблица",
        retrieval_query="перечень помещений под АУПТ таблица",
        doc_filter=["СП 486.1311500.2020.docx", "СП 485.1311500.2020.docx"],
        dataset_ids=None,
        rag_backend=backend,
        logger=_LOG,
    )
    # Только pipe-table чанки (проза отфильтрована).
    assert out, "ожидали поднять табличные приложения"
    assert all("|" in c.content for c in out)
    assert all(c.doc_name == "СП 486.1311500.2020.docx" for c in out)
    # Scope доехал до бэкенда (искали ТОЛЬКО в узлах-документах).
    assert backend.calls[0]["doc_filter"] == ["СП 486.1311500.2020.docx", "СП 485.1311500.2020.docx"]


@pytest.mark.asyncio
async def test_fetch_noop_without_doc_filter_or_intent():
    backend = ScopedBackend()
    # Нет узлов-документов → no-op, бэкенд не дёргаем.
    out = await fetch_table_appendix_chunks(
        question="перечень помещений таблица", retrieval_query="x",
        doc_filter=None, dataset_ids=None, rag_backend=backend, logger=_LOG,
    )
    assert out == []
    assert backend.calls == []
    # Есть узлы, но запрос НЕ табличный → no-op.
    out2 = await fetch_table_appendix_chunks(
        question="какая ширина эвакуационного выхода", retrieval_query="x",
        doc_filter=["СП 486.1311500.2020.docx"], dataset_ids=None,
        rag_backend=backend, logger=_LOG,
    )
    assert out2 == []
    assert backend.calls == []


def test_merge_is_additive_and_dedups():
    base = [Chunk("прозовый чанк", "СП 485.docx", 0.7)]
    tables = [
        Chunk("| a | b |", "СП 486.docx", 0.5),
        Chunk("| a | b |", "СП 486.docx", 0.5),  # дубль
    ]
    merged = merge_table_appendix(base, tables)
    # Базовый чанк сохранён + 1 уникальная таблица (дубль схлопнут).
    assert merged[0] is base[0]
    assert len(merged) == 2
    # Пустые таблицы → полный no-op (тот же список).
    assert merge_table_appendix(base, []) is base


def test_guarantee_promotes_appendix_into_visible_window():
    # Реранк утопил таблицу под прозой: окно top-2 — одна проза.
    prose = [Chunk(f"проза {i}", "СП 485.docx", 0.6) for i in range(6)]
    table = Chunk("| перечень | помещений |", "СП 486.docx", 0.5)
    ranked = prose[:2] + [table] + prose[2:]  # таблица на позиции 2 (вне окна=2)
    promoted = guarantee_table_appendix(ranked, [table], window=2, slots=1)
    # Таблица поднята В окно top-2.
    head = promoted[:2]
    assert any("|" in c.content for c in head), "приложение должно войти в видимое окно"
    # Аддитивно: ничего не потеряли (та же длина, проза в хвосте).
    assert len(promoted) == len(ranked)
    assert all(c in promoted for c in ranked)


def test_guarantee_noop_when_table_already_in_window():
    table = Chunk("| перечень |", "СП 486.docx", 0.5)
    prose = [Chunk("проза", "СП 485.docx", 0.6)]
    ranked = [table] + prose  # таблица уже первая
    promoted = guarantee_table_appendix(ranked, [table], window=2, slots=1)
    assert promoted == ranked  # порядок не тронут


def test_guarantee_noop_without_tables():
    ranked = [Chunk("проза", "СП 485.docx", 0.6)]
    assert guarantee_table_appendix(ranked, [], window=8) is ranked
