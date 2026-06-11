from tools import qwen_index_until_done as indexer


def test_is_heavy_document_flags_book_heavy_pipeline_and_large_pdf():
    assert indexer.is_heavy_document({"doc_type": "BOOK"})
    assert indexer.is_heavy_document({"complexity": "heavy"})
    assert indexer.is_heavy_document({"pipeline": "markdown_pdf_tables"})
    assert indexer.is_heavy_document({"file_name": "manual.pdf", "file_size": 30 * 1024 * 1024})


def test_light_pending_documents_filters_heavy_documents():
    docs = [
        {"file_name": "short.md", "file_size": 1000},
        {"doc_type": "BOOK", "file_name": "book.pdf", "file_size": 40 * 1024 * 1024},
        {"pipeline": "markdown_pdf_tables", "file_name": "tables.pdf", "file_size": 1024},
    ]

    assert indexer.light_pending_documents(docs) == [docs[0]]


def test_main_exits_without_starting_wave_when_only_heavy_pending(monkeypatch, capsys):
    heavy_doc = {
        "dataset_name": "BOOKS_Index",
        "file_name": "manual.pdf",
        "file_size": 40 * 1024 * 1024,
        "doc_type": "BOOK",
        "complexity": "heavy",
        "pipeline": "markdown_pdf_tables",
    }
    calls = []

    monkeypatch.setattr(indexer, "set_indexing_mode", lambda proxy_url: calls.append(("mode", proxy_url)))
    monkeypatch.setattr(indexer, "set_chat_mode", lambda proxy_url, reason: calls.append(("chat", proxy_url, reason)))
    monkeypatch.setattr(indexer, "pending_files", lambda proxy_url: 1)
    monkeypatch.setattr(indexer, "pending_documents", lambda proxy_url: [heavy_doc])
    monkeypatch.setattr(indexer, "active_scheduler_jobs", lambda proxy_url: (_ for _ in ()).throw(AssertionError("unexpected jobs check")))
    monkeypatch.setattr(indexer, "start_wave", lambda proxy_url, args: (_ for _ in ()).throw(AssertionError("unexpected wave")))

    result = indexer.main(["--proxy-url", "http://proxy/", "--poll-sec", "0", "--proxy-retry-sec", "0"])

    output = capsys.readouterr().out
    assert result == 0
    assert calls == [
        ("mode", "http://proxy"),
        ("chat", "http://proxy", "heavy pending requires manual admission"),
    ]
    assert '"event": "heavy_pending_only"' in output
    assert "BOOKS_Index" in output


def test_main_restores_chat_mode_when_no_pending_files(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(indexer, "set_indexing_mode", lambda proxy_url: calls.append(("mode", proxy_url)))
    monkeypatch.setattr(indexer, "set_chat_mode", lambda proxy_url, reason: calls.append(("chat", proxy_url, reason)))
    monkeypatch.setattr(indexer, "pending_files", lambda proxy_url: 0)

    result = indexer.main(["--proxy-url", "http://proxy", "--poll-sec", "0", "--proxy-retry-sec", "0"])

    output = capsys.readouterr().out
    assert result == 0
    assert calls == [
        ("mode", "http://proxy"),
        ("chat", "http://proxy", "qwen index done"),
    ]
    assert '"event": "done"' in output


def test_preprocess_called_before_indexing(monkeypatch, tmp_path):
    """W1.3: preprocess_dir вызывается для указанных каталогов ДО перевода в indexing-режим."""
    order = []

    import tools.pdf_preprocess as pp

    monkeypatch.setattr(pp, "preprocess_dir", lambda directory, **kw: order.append(("preprocess", str(directory))) or [])
    monkeypatch.setattr(indexer, "set_indexing_mode", lambda proxy_url: order.append(("mode", proxy_url)))
    monkeypatch.setattr(indexer, "set_chat_mode", lambda proxy_url, reason: None)
    monkeypatch.setattr(indexer, "pending_files", lambda proxy_url: 0)

    result = indexer.main([
        "--proxy-url", "http://proxy", "--poll-sec", "0", "--proxy-retry-sec", "0",
        "--preprocess-dirs", str(tmp_path),
    ])

    assert result == 0
    assert order[0] == ("preprocess", str(tmp_path))
    assert order[1][0] == "mode"


def test_preprocess_skipped_without_dirs(monkeypatch):
    """Без --preprocess-dirs препроцессор не трогается."""
    import tools.pdf_preprocess as pp

    called = []
    monkeypatch.setattr(pp, "preprocess_dir", lambda *a, **kw: called.append(1) or [])
    monkeypatch.setattr(indexer, "set_indexing_mode", lambda proxy_url: None)
    monkeypatch.setattr(indexer, "set_chat_mode", lambda proxy_url, reason: None)
    monkeypatch.setattr(indexer, "pending_files", lambda proxy_url: 0)

    assert indexer.main(["--proxy-url", "http://proxy", "--poll-sec", "0", "--proxy-retry-sec", "0"]) == 0
    assert not called
