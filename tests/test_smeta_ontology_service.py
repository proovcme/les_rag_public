"""Доменная онтология сметного дела: целостность графа, резолв терминов, деривация."""

from __future__ import annotations

from proxy.services.smeta_ontology_service import (
    derivation,
    get_concept,
    glossary_markdown,
    load_ontology,
    mermaid_graph,
    validate,
)


def test_graph_integrity_no_dangling_refs():
    assert validate() == []


def test_load_has_core_concepts():
    onto = load_ontology()
    ids = set(onto["by_id"])
    assert {"vor", "kac", "lsr", "ks2", "ks3", "spec", "fgis_cs", "gesn"} <= ids


def test_resolve_terms_and_aliases():
    assert get_concept("КАЦ")["id"] == "kac"
    assert get_concept("конъюнктурный анализ")["id"] == "kac"
    assert get_concept("ВОР")["id"] == "vor"
    assert get_concept("смета")["id"] == "lsr"
    assert get_concept("спецификация")["id"] == "spec"  # не путать с «специфиКАЦия»
    assert get_concept("несуществующий концепт XZ") is None


def test_kac_feeds_lsr():
    kac = get_concept("КАЦ")
    assert "lsr" in kac["outputs"]
    der = derivation("КАЦ")
    assert "lsr" in {x["id"] for x in der["downstream"]}
    assert "ved_mat" in {x["id"] for x in der["upstream"]}


def test_lsr_upstream_traverses_key_concepts():
    der = derivation("ЛСР")
    up = {x["id"] for x in der["upstream"]}
    # ЛСР собирается из ВОР + норм ГЭСН + цен ФГИС ЦС + КАЦ
    assert {"vor", "gesn", "fgis_cs", "kac"} <= up
    down = {x["id"] for x in der["downstream"]}
    assert {"ks2", "ks3"} <= down


def test_glossary_markdown_renders():
    md = glossary_markdown()
    assert "# Глоссарий" in md
    assert "конъюнктурный анализ" in md.lower()
    assert "Из чего выходит" in md


def test_mermaid_graph_has_edges():
    g = mermaid_graph()
    assert g.startswith("flowchart")
    assert "kac --> lsr" in g
