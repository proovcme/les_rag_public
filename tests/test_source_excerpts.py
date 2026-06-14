"""Цитаты из источников: конкретные фрагменты норм под ответом (дедуп, обрезка)."""
from types import SimpleNamespace as N

from proxy.routers.chat import source_excerpts


def test_dedup_truncate_skip_empty():
    chunks = [
        N(content="Ширина путей эвакуации 1,2 м " * 50, doc_name="NTD/СП 4.13130.docx", score=0.81, meta={"dataset_id": "ds1"}),
        N(content="", doc_name="empty.docx", score=0.5, meta={}),
        N(content="Ширина путей эвакуации 1,2 м " * 50, doc_name="NTD/СП 4.13130.docx", score=0.79, meta={}),  # дубль
        N(content="Дымоудаление по СП 7.13130", doc_name="NTD/СП 7.13130.docx", score=0.7, meta={"dataset_id": "ds2"}),
    ]
    ex = source_excerpts(chunks, max_n=6, max_chars=100)
    assert len(ex) == 2  # пустой пропущен, дубль дедуплицирован
    assert ex[0]["doc"] == "NTD/СП 4.13130.docx"
    assert ex[0]["text"].endswith("…")  # длинный обрезан
    assert ex[0]["score"] == 0.81 and ex[0]["dataset_id"] == "ds1"
    assert ex[1]["doc"] == "NTD/СП 7.13130.docx"


def test_max_n_limit():
    chunks = [N(content=f"фрагмент {i}", doc_name=f"d{i}.docx", score=0.5, meta={}) for i in range(10)]
    assert len(source_excerpts(chunks, max_n=3)) == 3


def test_empty_input():
    assert source_excerpts([]) == []
    assert source_excerpts(None) == []


def test_short_text_not_truncated():
    ex = source_excerpts([N(content="короткий пункт", doc_name="d.docx", score=0.6, meta={})], max_chars=700)
    assert ex[0]["text"] == "короткий пункт"  # без многоточия
