from pathlib import Path


VIEWER_MAIN = Path("frontend/cad_bim_viewer/src/main.ts")


def test_vizor_selection_card_can_ask_les_chat():
    source = VIEWER_MAIN.read_text(encoding="utf-8")

    assert 'id="ask-les-rag"' in source
    assert 'fetch("/lite-api/chat"' in source
    assert 'dataset_filter: "CAD_BIM"' in source
    assert "renderLesAnswer" in source
    assert "LES ответил по выбранному элементу" in source
