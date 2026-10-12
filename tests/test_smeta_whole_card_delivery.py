"""Нормативная карточка доходит до модели целиком либо её запрос ждёт следующего прохода.

Живой контроль .199 (10.10): 20 запросов модели дали 102 разные карточки по 700–3300
символов. Упаковщик считал запрос «помещающимся», если каждой карточке хватало 240
символов, и потому оставил 15 запросов, обрезав все тела до заголовка: целых карточек
0 из 102, состав работ и ресурсы не дошли ни по одной. Выбирать норму по одному
наименованию нельзя — поздний запрос честнее отдать следующему проходу.
"""
from __future__ import annotations

from proxy.services.chat_evidence_application_service import (
    EVIDENCE_TRUNCATION_SUFFIX,
    build_model_rag_evidence_groups,
    model_rag_evidence_coverage,
)

NORM_DOC = "smeta_norm_cards.v1"
PRICE_DOC = "fgis_price_cards.v1"


class _Hit:
    def __init__(self, name: str, body: str, *, header_chars: int = 0) -> None:
        self.doc_name = name
        self.doc_id = name
        self.content = body
        self.score = 0.5
        self.meta = {"smeta_required_header_chars": header_chars} if header_chars else {}


def _norm_card(query: int, hit: int, *, resources: int = 12) -> _Hit:
    header = (
        f"Шифр: ГЭСНм{query:02d}-01-{hit:03d}-01\nИзмеритель: 100 м\n"
        f"Наименование: Работа {query}.{hit} с собственными условиями применения"
    )
    steps = f"Состав работы: Подготовка {query}.{hit}.; Основная операция {query}.{hit}.; Проверка."
    lines = "; ".join(
        f"91.{query:02d}.{hit:02d}-{row:03d}: Ресурс {query}.{hit}.{row} [маш.-ч; 0.{row}]"
        for row in range(1, resources + 1)
    )
    body = f"{header}\n{steps}\nМашины и материалы (неполный перечень; расход на 100 м): {lines}"
    return _Hit(NORM_DOC, body, header_chars=len(header))


def _query_hits(queries: int, *, hits: int = 6):
    return [
        (f"запрос модели {query}", [_norm_card(query, hit) for hit in range(1, hits + 1)])
        for query in range(1, queries + 1)
    ]


def test_normative_cards_arrive_whole_and_late_queries_wait_for_the_next_pass():
    query_hits = _query_hits(20)
    blocks, chunks = build_model_rag_evidence_groups(query_hits, max_chars=28000, hits_per_query=6)

    rendered = "\n".join(blocks)
    assert len(rendered) <= 28000
    assert chunks, "хотя бы первый запрос обязан дойти"
    # Ни одна дошедшая нормативная карточка не обрезана: состав работ и ресурсы на месте.
    assert EVIDENCE_TRUNCATION_SUFFIX not in rendered
    assert not [chunk.meta["model_evidence_ref"] for chunk in chunks
                if chunk.meta.get("model_evidence_truncated")]
    for chunk in chunks:
        assert "Состав работы:" in chunk.content and "Проверка." in chunk.content

    # Остаются первые запросы в порядке модели, ширина выбора не опускается ниже пола.
    kept = [int(block.split("Q", 1)[1].split("]", 1)[0]) for block in blocks]
    assert kept == list(range(1, len(kept) + 1))
    assert all(block.count(f"[Q{index}.H") >= 5 for index, block in enumerate(blocks, 1))

    # Потеря поздних запросов объявлена, а не скрыта.
    coverage = model_rag_evidence_coverage(query_hits, blocks)
    assert coverage["queries_covered"] == len(kept) < 20
    assert coverage["complete"] is False


def test_everything_stays_when_whole_cards_fit():
    query_hits = _query_hits(3)
    blocks, chunks = build_model_rag_evidence_groups(query_hits, max_chars=28000, hits_per_query=6)

    assert len(blocks) == 3 and len(chunks) == 18
    assert not any(chunk.meta.get("model_evidence_truncated") for chunk in chunks)


def test_short_price_cards_do_not_push_out_whole_norm_cards():
    prices = [_Hit(PRICE_DOC, f"Ресурс ФССЦ: 01.7.10.15-{row:04d}\nНаименование: Изделие {row}\nЦена: {row}.00")
              for row in range(1, 11)]
    query_hits = [("запрос нормы", [_norm_card(1, hit) for hit in range(1, 7)]),
                  ("цена: изделие", prices)]
    blocks, chunks = build_model_rag_evidence_groups(query_hits, max_chars=12000, hits_per_query=6)

    assert len(blocks) == 2
    assert not any(chunk.meta.get("model_evidence_truncated") for chunk in chunks)
    assert sum(1 for chunk in chunks if chunk.doc_name == PRICE_DOC) == 10


def test_one_oversized_query_is_cut_openly_instead_of_vanishing():
    query_hits = [("единственный запрос", [_norm_card(1, hit, resources=80) for hit in range(1, 7)])]
    blocks, chunks = build_model_rag_evidence_groups(query_hits, max_chars=3000, hits_per_query=6)

    rendered = "\n".join(blocks)
    assert len(rendered) <= 3000 and chunks
    # Целиком не помещается ничего — сокращение остаётся видимым модели.
    assert EVIDENCE_TRUNCATION_SUFFIX in rendered
    assert "Шифр: ГЭСНм01-01-001-01" in rendered


def test_card_larger_than_a_query_share_is_cut_openly_without_evicting_other_queries():
    giant = _norm_card(1, 1, resources=400)
    assert len(giant.content) > 12000 // 5
    query_hits = [("запрос с огромной карточкой", [giant]),
                  ("обычный запрос", [_norm_card(2, hit) for hit in range(1, 4)])]
    blocks, chunks = build_model_rag_evidence_groups(query_hits, max_chars=12000, hits_per_query=6)

    assert len(blocks) == 2
    truncated = [chunk.meta["model_evidence_ref"] for chunk in chunks if chunk.meta.get("model_evidence_truncated")]
    assert truncated == ["Q1.H1"]
    assert "Состав работы:" in chunks[0].content
    assert len("\n".join(blocks)) <= 12000
