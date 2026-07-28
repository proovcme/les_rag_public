from pathlib import Path

import asyncio
from io import BytesIO
import json
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from starlette.requests import Request


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
    assert "BackfillComplete" in source
    assert "cursor.BackfillComplete || registered >= BatchLimit || RunBudgetExceeded()" in source
    assert "cursor.BackfillComplete = true;" in source
    assert '--self-test-cursor' in source
    assert "CursorSelfTest()" in source
    assert "duration_ms=" in source
    assert "private const int BatchLimit = 10;" in source
    assert "RunBudgetMilliseconds = 12000" in source
    assert "HardStopMilliseconds = 15000" in source
    assert "Environment.Exit(0)" in source
    assert "run forced stop duration_ms=" in source
    assert "RunBudgetExceeded()" in source
    assert "if (!Register(" in source
    assert "GetItemFromID(entryId, storeId)" in source
    assert "item.Delete(" not in source
    assert "item.Move(" not in source
    assert ".UnRead =" not in source


def test_windows_bootstrap_installs_bounded_manual_interactive_task():
    setup = (ROOT / "clients/outlook_mail_poller/setup_task.ps1").read_text(encoding="utf-8")
    bootstrap = (ROOT / "installers/windows/app/bootstrap.ps1").read_text(encoding="utf-8-sig")

    assert "LES E.ZH.I.K. Outlook Collector" in setup
    assert "New-ScheduledTaskAction -Execute $target" in setup
    assert "Register-ScheduledTask" in setup
    assert 'schedule = "manual"' in setup
    assert "New-TimeSpan -Seconds 20" in setup
    assert "/sc minute" not in setup
    assert "New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive" in setup
    assert "collector/import" in setup
    assert "outlook_mail_poller\\setup_task.ps1" in bootstrap
    assert "-EveryMinutes" not in bootstrap
    production = (ROOT / "tools/windows_production_deploy.ps1").read_text(encoding="utf-8-sig")
    assert "LesMailPoller.exe" in production
    assert "--probe" in production
    assert "Invoke-InteractiveOutlookProbe" in production
    assert "New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive" in production
    assert 'probe_mode = "interactive_scheduled_task"' in production
    assert 'outlook_probe = $outlookProbe' in production
    assert "Outlook probe skipped:" in production
    assert "Unregister-ScheduledTask -TaskName $probeTaskName" in production
    assert "/api/mail/accounts" in production
    assert "password" in production

    platform_gate = (ROOT / "tools/platform_release_gate.py").read_text(encoding="utf-8")
    assert "def verify_windows_mail_collector()" in platform_gate
    assert 'verify_windows_mail_collector()' in platform_gate
    assert '"--self-test-cursor"' in platform_gate


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
    assert 'f"ds:{account[\'dataset_id\']}"' in page
    assert '"target_file"' in page
    assert "Ответить" not in page
    assert "Переслать" not in page
    assert "Забрать новые письма" in page
    assert "/api/mail/collector/run" in page


@pytest.mark.asyncio
async def test_outlook_snapshot_upload_is_queued_without_waiting_for_rag(monkeypatch, tmp_path):
    from proxy.routers import mail

    started = asyncio.Event()
    release = asyncio.Event()
    marks: list[tuple[str, str, str]] = []
    parses: list[tuple[str, str]] = []

    class Backend:
        async def upload_file(self, dataset_id, raw_path, *, relative_path):
            started.set()
            await release.wait()
            return "rag-doc"

    class Registry:
        def register_message(self, **kwargs):
            return {"id": "message"}, True

        def mark_indexed(self, message_id, *, rag_doc_id="", status="registered"):
            marks.append((message_id, rag_doc_id, status))

    monkeypatch.setattr(mail, "get_dataset_state", lambda: SimpleNamespace(backend=Backend()))
    monkeypatch.setattr(mail, "get_mail_registry", lambda: Registry())
    monkeypatch.setattr(
        mail,
        "_schedule_mailbox_parse",
        lambda account_id, dataset_id: parses.append((account_id, dataset_id)),
    )
    mail._outlook_upload_queues.clear()
    mail._outlook_upload_tasks.clear()
    mail._outlook_queued_manifests.clear()
    raw_path = tmp_path / "message.msg"
    raw_path.write_bytes(b"snapshot")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "account_id": "account",
                "dataset_id": "dataset",
                "store_id": "store",
                "entry_id": "entry",
                "folder_id": "folder",
                "folder_path": "Inbox",
                "internet_message_id": "",
                "received_at": "",
                "raw_path": str(raw_path),
                "relative_path": "outlook/message.msg",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LES_MAIL_STATE_ROOT", str(tmp_path))

    queue_depth, worker = mail._queue_outlook_spool_manifest(
        account_id="account",
        dataset_id="dataset",
        manifest_path=manifest_path,
    )

    assert queue_depth == 1
    await asyncio.wait_for(started.wait(), timeout=1)
    assert not worker.done()
    assert marks == [("message", "", "queued")]

    release.set()
    await asyncio.wait_for(worker, timeout=1)
    assert marks == [
        ("message", "", "queued"),
        ("message", "rag-doc", "registered"),
    ]
    assert parses == [("account", "dataset")]
    assert not manifest_path.exists()


@pytest.mark.asyncio
async def test_outlook_intake_persists_spool_before_exact_registry(monkeypatch, tmp_path):
    from proxy.routers import mail

    async def account(*_args, **_kwargs):
        return {"id": "account", "dataset_id": "dataset"}

    queued: list[Path] = []

    def queue_manifest(*, account_id, dataset_id, manifest_path):
        queued.append(manifest_path)
        return 1, asyncio.create_task(asyncio.sleep(0))

    monkeypatch.setenv("LES_MAIL_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(mail, "_ensure_outlook_store_account", account)
    monkeypatch.setattr(mail, "_queue_outlook_spool_manifest", queue_manifest)
    monkeypatch.setattr(
        mail,
        "get_mail_registry",
        lambda: (_ for _ in ()).throw(AssertionError("registry must run after HTTP intake")),
    )
    request = Request({"type": "http", "client": ("127.0.0.1", 50000), "headers": []})
    upload = UploadFile(filename="message.eml", file=BytesIO(b"Subject: Test\r\n\r\nBody"))

    result = await mail.import_outlook_message(
        request=request,
        message=upload,
        store_id="store",
        entry_id="entry",
        store_label="Outlook",
        folder_id="folder",
        folder_path="Inbox",
        internet_message_id="",
        received_at="",
        _internal=object(),
    )

    assert result["status"] == "accepted"
    assert result["index_status"] == "queued"
    assert result["queue_depth"] == 1
    assert len(queued) == 1
    payload = json.loads(queued[0].read_text(encoding="utf-8"))
    assert Path(payload["raw_path"]).read_bytes() == b"Subject: Test\r\n\r\nBody"
