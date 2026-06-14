"""W17.2 — типизированные рёбра + детерминированный вывод (0 LLM)."""
import importlib

import pytest


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    import backend.rag_config as rc
    importlib.reload(rc)
    import proxy.services.edge_service as es
    importlib.reload(es)
    return es


# ── экстракторы (чистые, без БД) ─────────────────────────────────────

def test_extract_ntd_refs_normalizes():
    from proxy.services.edge_service import extract_ntd_refs
    text = "Согласно сп 7.13130. и ГОСТ Р 59639-2021, а также СНиП 2.01.07-85."
    refs = extract_ntd_refs(text)
    assert "СП 7.13130" in refs
    assert "ГОСТ Р 59639-2021" in refs
    assert "СНиП 2.01.07-85" in refs


def test_extract_ntd_dedup_and_case():
    from proxy.services.edge_service import extract_ntd_refs
    assert extract_ntd_refs("СП 4.13130 и сп 4.13130 снова") == ["СП 4.13130"]


def test_extract_wiki_links():
    from proxy.services.edge_service import extract_wiki_links
    assert extract_wiki_links("см. [[СП 4.13130]] и [[ Этаж 01 ]] и [[задача 7]]") == [
        "СП 4.13130", "Этаж 01", "задача 7",
    ]


def test_extract_element_refs():
    from proxy.services.edge_service import extract_element_refs
    text = "Source ID: 0J$u4Qbqf7A9h1vBM9EA01 и Source ID / GlobalId: abc-123."
    assert extract_element_refs(text) == ["0J$u4Qbqf7A9h1vBM9EA01", "abc-123"]


def test_extractors_empty():
    from proxy.services.edge_service import extract_ntd_refs, extract_wiki_links, extract_element_refs
    assert extract_ntd_refs("") == [] and extract_wiki_links(None) == [] and extract_element_refs("") == []


# ── хранилище + деривация ────────────────────────────────────────────

def test_derive_edges_from_text(svc):
    text = "Решение по [[корпус Б]]: фасад по СП 4.13130, элемент Source ID: wall-7"
    created = svc.derive_edges_from_text("note", "12", text, provenance="note#12")
    types = {(e["edge_type"], e["dst_id"]) for e in created}
    assert ("references_ntd", "СП 4.13130") in types
    assert ("wiki_link", "корпус Б") in types
    assert ("mentions_element", "wall-7") in types

    out = svc.edges_for("note", "12")["out"]
    assert len(out) == 3
    assert all(e["confidence"] == "trusted" for e in out)  # детерминированные доверенные
    assert all(e["provenance"] == "note#12" for e in out)


def test_derive_is_idempotent(svc):
    svc.derive_edges_from_text("note", "1", "СП 1.13130 [[a]]")
    svc.derive_edges_from_text("note", "1", "СП 1.13130 [[a]]")  # повтор
    assert len(svc.edges_for("note", "1")["out"]) == 2  # не задвоилось

    # ре-деривация с новым текстом заменяет авто-рёбра
    svc.derive_edges_from_text("note", "1", "ГОСТ 21.501")
    out = svc.edges_for("note", "1")["out"]
    assert len(out) == 1 and out[0]["dst_id"] == "ГОСТ 21.501"


def test_backlinks_both_directions(svc):
    # две заметки ссылаются на один норматив → у норматива два входящих бэклинка
    svc.derive_edges_from_text("note", "1", "по СП 4.13130")
    svc.derive_edges_from_text("note", "2", "тоже СП 4.13130")
    inc = svc.edges_for("ntd_code", "СП 4.13130")["in"]
    assert len(inc) == 2
    assert {e["src_id"] for e in inc} == {"1", "2"}


def test_add_edge_manual_and_candidate(svc):
    svc.add_edge("decision", "5", "element", "w-1", "concerns", method="manual")
    svc.add_edge("decision", "5", "ntd_code", "СП X", "justified_by", method="llm", confidence="candidate")
    out = svc.edges_for("decision", "5")["out"]
    conf = {e["edge_type"]: e["confidence"] for e in out}
    assert conf["concerns"] == "trusted"
    assert conf["justified_by"] == "candidate"  # LLM-ребро в карантине


def test_list_edges_filter_by_method(svc):
    svc.derive_edges_from_text("note", "9", "СП 1.13130 [[x]]")
    assert len(svc.list_edges(method="regex_ntd")) == 1
    assert len(svc.list_edges(method="wikilink")) == 1
