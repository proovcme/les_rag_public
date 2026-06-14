"""W18.1 — отдача файлов/структуры: path-guard, дерево, текст."""
import pytest

from fastapi import HTTPException

from proxy.routers import files as files_router


@pytest.fixture()
def root(tmp_path, monkeypatch):
    (tmp_path / "NTD").mkdir()
    (tmp_path / "NTD" / "note.md").write_text("# Привет\nтекст", encoding="utf-8")
    (tmp_path / "NTD" / "doc.pdf").write_bytes(b"%PDF-1.4 ...")
    (tmp_path / ".hidden").write_text("secret")
    monkeypatch.setattr(files_router, "_ROOT", tmp_path)
    return tmp_path


def test_safe_blocks_traversal(root):
    with pytest.raises(HTTPException) as e:
        files_router._safe("../../etc/passwd")
    assert e.value.status_code == 400


def test_safe_allows_inside(root):
    p = files_router._safe("NTD/note.md")
    assert p.name == "note.md"


@pytest.mark.asyncio
async def test_tree_lists_dirs_first_skips_hidden(root):
    tree = await files_router.rag_tree(path="", depth=2, _user=object())
    assert tree["dir"] is True
    names = [c["name"] for c in tree["children"]]
    assert "NTD" in names
    assert ".hidden" not in names  # скрытые не показываем
    ntd = next(c for c in tree["children"] if c["name"] == "NTD")
    files = {c["name"]: c for c in ntd["children"]}
    assert files["note.md"]["dir"] is False
    assert files["note.md"]["path"] == "NTD/note.md"


@pytest.mark.asyncio
async def test_file_text_returns_content(root):
    res = await files_router.rag_file_text(path="NTD/note.md", _user=object())
    assert res["language"] == "md"
    assert "Привет" in res["content"]


@pytest.mark.asyncio
async def test_file_text_rejects_binary(root):
    with pytest.raises(HTTPException) as e:
        await files_router.rag_file_text(path="NTD/doc.pdf", _user=object())
    assert e.value.status_code == 415  # бинарь → через /file/raw


@pytest.mark.asyncio
async def test_file_text_404_missing(root):
    with pytest.raises(HTTPException) as e:
        await files_router.rag_file_text(path="NTD/nope.md", _user=object())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_file_raw_serves_pdf(root):
    resp = await files_router.rag_file_raw(path="NTD/doc.pdf", _user=object())
    assert str(resp.path).endswith("doc.pdf")
