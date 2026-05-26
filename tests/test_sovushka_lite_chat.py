from sovushka.lite_chat import bridge_request_allowed, lite_chat_html


def test_lite_chat_html_uses_static_shell_and_local_bridge():
    html = lite_chat_html()

    assert "Л.Е.С. LITE" in html
    assert "без NiceGUI client state" in html
    assert "/lite-api" in html
    assert 'path.replace(/^\\/api(?=\\/)/, "")' in html
    assert "/api/chat" in html
    assert "/classic" in html


def test_bridge_allows_auth_verify_without_existing_key():
    assert bridge_request_allowed("auth/verify", has_key=False, is_loopback=False)


def test_bridge_requires_key_for_remote_chat_requests():
    assert not bridge_request_allowed("chat", has_key=False, is_loopback=False)
    assert bridge_request_allowed("chat", has_key=True, is_loopback=False)


def test_bridge_allows_loopback_without_key_for_local_trusted_runtime():
    assert bridge_request_allowed("indexing-mode", has_key=False, is_loopback=True)
