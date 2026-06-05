from sovushka.m5_display import m5_display_html


def test_m5_display_html_targets_wokyis_screen_and_lite_bridge():
    html = m5_display_html()

    assert "S.O.V.U.S.H.K.A M5" in html
    assert "1280x720" in html
    assert "retro-apple" in html
    assert "/lite-api" in html
    assert "/api/runtime/dispatcher/status" in html
    assert "/api/rag/watch/status?source_root=RAG_Content&limit=6" in html
    assert "/api/mail/status" in html
    assert "les_lite_api_key" in html
    assert "asciiScreen" in html
    assert 'const isLocalUi = location.port === "8051";' in html
    assert ".innerHTML" not in html
