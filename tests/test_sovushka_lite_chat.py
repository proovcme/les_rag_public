from sovushka.lite_chat import bridge_request_allowed, lite_chat_html


def test_lite_chat_html_uses_static_shell_and_local_bridge():
    html = lite_chat_html()

    assert "Л.Е.С. LITE" in html
    assert "без NiceGUI client state" in html
    assert "/lite-api" in html
    assert 'path.replace(/^\\/api(?=\\/)/, "")' in html
    assert "/api/chat" in html
    assert "/api/chat/history/" in html
    assert "history_id: data.history_id || null" in html
    assert "Плохой ответ" in html
    assert "bad_answer" in html
    assert "Источник не из того датасета" in html
    assert "/api/mail/threads" in html
    assert "Е.Ж.И.К. Почта" in html
    assert "/classic" in html
    assert "Индексирование активно:" in html
    assert 'const isLocalUi = location.port === "8051";' in html
    assert "bot.innerHTML" not in html


def test_bridge_allows_auth_verify_without_existing_key():
    assert bridge_request_allowed("auth/verify", has_key=False, is_loopback=False)


def test_bridge_requires_key_for_remote_chat_requests():
    assert not bridge_request_allowed("chat", has_key=False, is_loopback=False)
    assert bridge_request_allowed("chat", has_key=True, is_loopback=False)


def test_bridge_allows_loopback_without_key_for_local_trusted_runtime():
    assert bridge_request_allowed("indexing-mode", has_key=False, is_loopback=True)


def test_bridge_allows_configured_trusted_network_without_key():
    assert bridge_request_allowed(
        "settings",
        has_key=False,
        is_loopback=False,
        is_trusted_network=True,
    )
