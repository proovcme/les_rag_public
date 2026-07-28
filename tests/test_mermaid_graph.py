from sovushka.pages.mermaid_page import knowledge_graph_to_mermaid


def test_knowledge_graph_to_mermaid_renders_live_graph_payload():
    code = knowledge_graph_to_mermaid({
        "nodes": [
            {"id": "p:1", "kind": "project", "label": "БАИ"},
            {"id": "ds:1", "kind": "dataset", "label": "Проектная документация", "chunks": 10},
            {"id": "doc:1", "kind": "document", "label": "ИОС 5.2.pdf", "chunks": 42},
        ],
        "edges": [
            {"source": "p:1", "target": "ds:1", "type": "contains"},
            {"source": "ds:1", "target": "doc:1", "type": "contains"},
        ],
    })

    assert "flowchart TB" in code
    assert "БАИ" in code
    assert "ИОС 5.2.pdf" in code
    assert "contains" in code


def test_knowledge_graph_to_mermaid_empty_payload_is_explicit():
    code = knowledge_graph_to_mermaid({})

    assert "Граф пуст" in code
