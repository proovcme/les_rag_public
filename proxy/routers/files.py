"""W18.1 — отдача файлов и файловой структуры RAG_Content для чат-визуалайзера.

Только чтение, строгий path-guard (никаких выходов за RAG_Content). Текст —
строкой, бинарь (pdf/картинки) — FileResponse для вьювера/iframe.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from proxy.security import require_user

router = APIRouter(prefix="/api/rag", tags=["files"])

# Корень контента (переопределяется в тестах через files._root()).
_ROOT = Path("RAG_Content")

_TEXT_EXT = {
    ".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".xml", ".yaml", ".yml",
    ".log", ".html", ".svg", ".py", ".ini", ".cfg", ".sql",
}
_MAX_TEXT_BYTES = 2_000_000


def _root() -> Path:
    return _ROOT


def _safe(path: str) -> Path:
    """Резолв пути внутри RAG_Content; выход за корень → 400."""
    root = _root().resolve()
    target = (root / path).resolve() if path else root
    if target != root and root not in target.parents:
        raise HTTPException(400, "путь вне RAG_Content")
    return target


def _node(p: Path, depth: int, root: Path) -> dict:
    rel = "" if p == root else str(p.relative_to(root))
    item: dict = {"name": p.name or "RAG_Content", "path": rel, "dir": p.is_dir()}
    if p.is_dir() and depth > 0:
        try:
            children = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError:
            children = []
        item["children"] = [
            _node(c, depth - 1, root) for c in children if not c.name.startswith(".")
        ][:500]
    return item


@router.get("/tree")
async def rag_tree(
    path: str = "",
    depth: int = Query(default=1, ge=1, le=3),
    _user=Depends(require_user),
):
    base = _safe(path)
    if not base.exists():
        raise HTTPException(404, "путь не найден")
    return _node(base, depth, _root().resolve())


@router.get("/file/text")
async def rag_file_text(path: str, _user=Depends(require_user)):
    p = _safe(path)
    if not p.is_file():
        raise HTTPException(404, "файл не найден")
    if p.suffix.lower() not in _TEXT_EXT:
        raise HTTPException(415, "не текстовый файл — используйте /file/raw")
    if p.stat().st_size > _MAX_TEXT_BYTES:
        raise HTTPException(413, "файл слишком большой для текстового просмотра")
    return {
        "path": path,
        "name": p.name,
        "language": p.suffix.lstrip(".") or "text",
        "content": p.read_text(errors="replace"),
    }


@router.get("/file/raw")
async def rag_file_raw(path: str, _user=Depends(require_user)):
    p = _safe(path)
    if not p.is_file():
        raise HTTPException(404, "файл не найден")
    return FileResponse(p)
