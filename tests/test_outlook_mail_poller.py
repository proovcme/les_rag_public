from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_outlook_sidecar_is_read_only_resumable_and_uploads_unicode_msg():
    source = (ROOT / "clients/outlook_mail_poller/LesMailPoller.cs").read_text(encoding="utf-8")

    assert "session.Stores" in source
    assert "new int[] { 3, 16, 23 }" in source
    assert "item.SaveAs(temp, 9)" in source
    assert "InternetMessageIdSchema" in source
    assert 'fields["store_id"]' in source
    assert 'fields["entry_id"]' in source
    assert "SaveCursor(storeId, folderId, cursor)" in source
    assert "incremental.Count - 1" in source
    assert "if (!RegisterItemAt(" in source
    assert "NewestEntryIds" in source
    assert "OldestEntryIds" in source
    assert "if (!Register(" in source
    assert "GetItemFromID(entryId, storeId)" in source
    assert "item.Delete(" not in source
    assert "item.Move(" not in source
    assert ".UnRead =" not in source


def test_windows_bootstrap_installs_interactive_three_minute_task():
    setup = (ROOT / "clients/outlook_mail_poller/setup_task.ps1").read_text(encoding="utf-8")
    bootstrap = (ROOT / "installers/windows/app/bootstrap.ps1").read_text(encoding="utf-8-sig")

    assert "LES E.ZH.I.K. Outlook Collector" in setup
    assert "/sc minute /mo $EveryMinutes" in setup
    assert "/it /f" in setup
    assert "collector/import" in setup
    assert "outlook_mail_poller\\setup_task.ps1" in bootstrap
    assert "-EveryMinutes 3" in bootstrap
    production = (ROOT / "tools/windows_production_deploy.ps1").read_text(encoding="utf-8-sig")
    assert "LesMailPoller.exe" in production
    assert "--probe" in production
    assert "/api/mail/accounts" in production
    assert "password" in production


def test_mail_has_a_dedicated_offline_and_windows_static_release_gate():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    release = (ROOT / "tools/patch_release.py").read_text(encoding="utf-8")

    assert "test-mail:" in makefile
    assert "test_mail_registry_service.py" in makefile
    assert "test_outlook_mail_poller.py" in makefile
    assert "test-mail-release: test-mail test-tauri" in makefile
    assert '["make", "test-mail-release"]' in release


def test_mail_ui_is_read_only_and_scopes_chat_to_the_mailbox_dataset():
    header = (ROOT / "sovushka/components/header.py").read_text(encoding="utf-8")
    page = (ROOT / "sovushka/pages/mail.py").read_text(encoding="utf-8")

    assert 'ui.tab("Почта"' in header
    assert "/api/mail/accounts" in page
    assert "/api/mail/messages" in page
    assert "Открыть в Outlook" in page
    assert "scope=ds:{account['dataset_id']}" in page
    assert "Ответить" not in page
    assert "Переслать" not in page
