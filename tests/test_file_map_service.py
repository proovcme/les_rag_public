"""W15.1: сканер папок — карта без чтения содержимого, без LLM."""

from pathlib import Path

from proxy.services.file_map_service import extract_cipher, map_stats, scan_root, search_map


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "archive"
    (root / "НТД").mkdir(parents=True)
    (root / "Проект" / "ОВ").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "НТД" / "СП 60.13330.2020 Отопление.pdf").write_bytes(b"x" * 100)
    (root / "Проект" / "ОВ" / "АТ-РД-ОВ2-С-00-П1.pdf").write_bytes(b"y" * 200)
    (root / "Проект" / "записка.docx").write_bytes(b"z" * 50)
    (root / ".git" / "config").write_bytes(b"hidden")
    return root


def test_extract_cipher_ntd_and_project():
    assert extract_cipher("СП 60.13330.2020 Отопление.pdf").startswith("СП 60.13330")
    assert extract_cipher("ГОСТ Р 53300-2009.docx").startswith("ГОСТ")
    assert "АТ-РД-ОВ2" in extract_cipher("АТ-РД-ОВ2-С-00-П1.pdf")
    assert extract_cipher("просто файл.txt") == ""


def test_scan_builds_map_and_skips_excluded(tmp_path):
    root = _tree(tmp_path)
    db = tmp_path / "map.db"
    result = scan_root(root, db_path=db)
    assert result["files"] == 3  # .git исключён
    assert result["added"] == 3 and result["removed"] == 0

    found = search_map(q="СП 60", db_path=db)
    assert len(found) == 1 and found[0]["cipher"].startswith("СП 60")


def test_rescan_incremental_and_removal(tmp_path):
    root = _tree(tmp_path)
    db = tmp_path / "map.db"
    scan_root(root, db_path=db)

    (root / "Проект" / "записка.docx").unlink()
    (root / "НТД" / "новый ГОСТ 12.1.004.pdf").write_bytes(b"n" * 10)
    result = scan_root(root, db_path=db)
    assert result["added"] == 1
    assert result["removed"] == 1
    assert result["unchanged"] == 2


def test_search_filters(tmp_path):
    root = _tree(tmp_path)
    db = tmp_path / "map.db"
    scan_root(root, db_path=db)
    assert len(search_map(ext="pdf", db_path=db)) == 2
    assert len(search_map(cipher="РД-ОВ2", db_path=db)) == 1
    stats = map_stats(db_path=db)
    assert stats["roots"][0]["file_count"] == 3
    assert stats["files_with_cipher"] == 2


def test_no_content_read(tmp_path):
    """Карта не читает содержимое: битый «pdf» сканится без ошибок."""
    root = tmp_path / "a"
    root.mkdir()
    (root / "битый.pdf").write_bytes(b"\x00\xff not a pdf at all")
    result = scan_root(root, db_path=tmp_path / "m.db")
    assert result["files"] == 1


# ── W15.2: выборочная индексация из карты ──

def test_resolve_selection_by_prefix_and_cipher(tmp_path):
    from proxy.services.file_map_service import resolve_selection

    root = _tree(tmp_path)
    db = tmp_path / "map.db"
    scan_root(root, db_path=db)

    by_prefix = resolve_selection(path_prefix="Проект", db_path=db)
    rels = {item["rel_path"] for item in by_prefix}
    assert rels == {"Проект/ОВ/АТ-РД-ОВ2-С-00-П1.pdf", "Проект/записка.docx"}
    assert all(item["abs_path"].endswith(item["rel_path"]) for item in by_prefix)

    by_cipher = resolve_selection(cipher="СП 60", db_path=db)
    assert len(by_cipher) == 1 and by_cipher[0]["name"].startswith("СП 60")


def test_resolve_selection_explicit_rel_paths(tmp_path):
    from proxy.services.file_map_service import resolve_selection

    root = _tree(tmp_path)
    db = tmp_path / "map.db"
    scan_root(root, db_path=db)
    sel = resolve_selection(rel_paths=["Проект/записка.docx"], db_path=db)
    assert len(sel) == 1 and sel[0]["rel_path"] == "Проект/записка.docx"


def test_suggest_candidates_prefers_ciphered_folders(tmp_path):
    from proxy.services.file_map_service import suggest_index_candidates

    root = _tree(tmp_path)
    db = tmp_path / "map.db"
    scan_root(root, db_path=db)
    cands = suggest_index_candidates(db_path=db)
    folders = {c["folder"] for c in cands}
    # папки с шифрами: НТД (СП 60) и Проект/ОВ (АТ-РД-ОВ2); «Проект» без шифра — нет
    assert "НТД" in folders and "Проект/ОВ" in folders
    assert all(c["ciphered"] > 0 for c in cands)
