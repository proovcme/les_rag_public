from sovushka.lite_admin import lite_admin_html, local_runtime_action_allowed


def test_lite_admin_html_uses_static_admin_shell():
    html = lite_admin_html()

    assert "Л.Е.С. LITE ADMIN" in html
    assert "без NiceGUI client state" in html
    assert "/les/classic" in html
    assert "/api/indexing-mode" in html
    assert "/api/rag/parse-scheduler" in html
    assert "/lite-runtime/status" in html


def test_lite_admin_runtime_actions_are_loopback_only():
    assert local_runtime_action_allowed(is_loopback=True)
    assert not local_runtime_action_allowed(is_loopback=False)
