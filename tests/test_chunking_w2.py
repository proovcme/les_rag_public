"""W2.1+W2.5: токенный чанкинг и обогащение заголовками — офлайн-тесты."""

import pytest

from backend.qdrant_adapter import (
    StructureAwareSplitter,
    _apply_context_metadata_to_nodes,
    _section_heading_info,
)
from backend.rag_config import chunking_config, rag_chunk_unit


class FakeDoc:
    def __init__(self, text):
        self.text = text
        self.metadata = {}
        self.node_id = "doc-1"


def _fake_token_len(text: str) -> int:
    """Псевдотокенизатор: 1 токен ≈ 4 символа (детерминированно, без transformers)."""
    return max(1, len(text) // 4)


# ── W2.1: len_fn в сплиттере ──

def test_splitter_token_mode_respects_token_budget():
    splitter = StructureAwareSplitter(chunk_size=50, chunk_overlap=5, len_fn=_fake_token_len)
    text = "\n\n".join(f"5.{i} Пункт номер {i}. " + "Содержимое предложения раздела. " * 6 for i in range(1, 11))
    nodes = splitter.get_nodes_from_documents([FakeDoc(text)])
    assert len(nodes) > 1
    for node in nodes:
        assert _fake_token_len(node.text) <= 50 + 5  # бюджет + допуск на склейку


def test_splitter_chars_mode_unchanged_default():
    splitter = StructureAwareSplitter(chunk_size=200, chunk_overlap=20)
    text = "Первое предложение текста. " * 30
    nodes = splitter.get_nodes_from_documents([FakeDoc(text)])
    assert all(len(n.text) <= 200 + 20 for n in nodes)


def test_splitter_keeps_numbered_clause_atomic_in_token_mode():
    splitter = StructureAwareSplitter(chunk_size=100, chunk_overlap=10, len_fn=_fake_token_len)
    clause = "7.2 Требования к воздуховодам. " + "Текст требования. " * 5
    text = "Преамбула документа. " * 3 + "\n\n" + clause + "\n\n8 Другой раздел\nТекст."
    nodes = splitter.get_nodes_from_documents([FakeDoc(text)])
    joined = [n.text for n in nodes]
    assert any("7.2 Требования" in t for t in joined)


# ── W2.1: chunking_config ──

def test_chunking_config_chars_mode(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_UNIT", "chars")
    cfg = chunking_config()
    assert cfg["unit"] == "chars" and cfg["len_fn"] is None


def test_chunking_config_clamps_to_seq_len(monkeypatch):
    monkeypatch.setenv("RAG_CHUNK_UNIT", "tokens")
    monkeypatch.setenv("RAG_CHUNK_TOKENS", "1000")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP_TOKENS", "50")
    monkeypatch.setenv("COREML_EMBED_SEQ_LEN", "512")
    import backend.rag_config as rc

    monkeypatch.setattr(rc, "token_length_fn", lambda: _fake_token_len)
    cfg = rc.chunking_config()
    assert cfg["chunk_size"] + cfg["chunk_overlap"] <= 512 - 32 + 50  # клампнуто (ADR-7)
    assert cfg["chunk_size"] <= 512


def test_rag_chunk_unit_default_tokens(monkeypatch):
    monkeypatch.delenv("RAG_CHUNK_UNIT", raising=False)
    assert rag_chunk_unit() == "tokens"


# ── W2.5: заголовки ──

def test_section_heading_info_markdown_and_numbered():
    assert _section_heading_info("## Вентиляция\nтело") == ("Вентиляция", 2)
    heading, level = _section_heading_info("5.2.1 Требования к стоку\nтело")
    assert heading == "5.2.1 Требования к стоку" and level == 3


def test_section_heading_info_body_text_is_not_heading():
    heading, level = _section_heading_info("обычное предложение без номера и решёток")
    assert heading == "" and level == 0


def test_heading_propagation_to_continuation_chunks():
    nodes = [
        {"text": "5.2 Требования к вентиляции\nНачало раздела.", "payload": {}},
        {"text": "Продолжение раздела без своего заголовка.", "payload": {}},
        {"text": "6 Отопление\nНовый раздел.", "payload": {}},
        {"text": "Хвост раздела отопления.", "payload": {}},
    ]
    _apply_context_metadata_to_nodes(nodes, "ds", "doc.md")
    payloads = [n["payload"] for n in nodes]
    assert payloads[0]["section_heading"].startswith("5.2")
    assert payloads[1]["section_heading"].startswith("5.2")  # унаследован
    assert payloads[1].get("heading_inherited") is True
    assert payloads[2]["section_heading"].startswith("6 ")
    assert payloads[3]["section_heading"].startswith("6 ")
    assert payloads[0]["heading_level"] == 2
    assert payloads[2]["heading_level"] == 1
