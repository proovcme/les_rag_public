"""W18.1 — отдача файлов и файловой структуры для чат-визуалайзера.

Корни чтения: `RAG_Content` (внутренний контент) + внешние корни индексации
по ссылке (`LES_EXTERNAL_SOURCE_ROOTS`, ADR-12) — чтобы проекты, проиндексированные
in-place (котельная и пр.), были видны и листались в чате, а не только копии.

Только чтение, строгий path-guard на каждый корень (никаких выходов за корни).
Пути в дереве: внутри RAG_Content — относительные (legacy); во внешнем корне —
с префиксом `<ключ-корня>::<относительный>`. Текст — строкой, бинарь
(pdf/картинки) — FileResponse для вьювера/iframe.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from proxy.security import require_user

router = APIRouter(prefix="/api/rag", tags=["files"])

# Корень внутреннего контента (переопределяется в тестах через files._ROOT).
_ROOT = Path("RAG_Content")
_DEFAULT_KEY = "RAG_Content"
_ROOT_SEP = "::"  # разделитель «<ключ-корня>::<относительный путь>»

_TEXT_EXT = {
    ".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".xml", ".yaml", ".yml",
    ".log", ".html", ".svg", ".py", ".ini", ".cfg", ".sql",
}
_MAX_TEXT_BYTES = 2_000_000


def _root() -> Path:
    return _ROOT


def _roots() -> dict[str, Path]:
    """Разрешённые корни чтения: RAG_Content + внешние корни индексации по ссылке.

    Ключ внешнего корня — имя его папки (дедуп суффиксом при коллизии). Внутренний
    корень всегда под ключом `RAG_Content`.
    """
    roots: dict[str, Path] = {_DEFAULT_KEY: _root()}
    raw = os.getenv("LES_EXTERNAL_SOURCE_ROOTS", "")
    for item in (s.strip() for s in raw.split(",")):
        if not item:
            continue
        rp = Path(item).expanduser()
        key = rp.name or "ext"
        base, n = key, 2
        while key in roots:
            key = f"{base}_{n}"
            n += 1
        roots[key] = rp
    return roots


def _split_key(path: str) -> tuple[str, str]:
    """Разбор пути на (ключ-корня, относительный). Без префикса → RAG_Content (legacy)."""
    if path and _ROOT_SEP in path:
        key, rel = path.split(_ROOT_SEP, 1)
        return key, rel
    return _DEFAULT_KEY, (path or "")


def _safe(path: str) -> Path:
    """Резолв пути внутри разрешённого корня; выход за корень → 400."""
    roots = _roots()
    key, rel = _split_key(path)
    if key not in roots:
        raise HTTPException(400, "неизвестный корень")
    root = roots[key].resolve()
    target = (root / rel).resolve() if rel else root
    if target != root and root not in target.parents:
        raise HTTPException(400, "путь вне разрешённого корня")
    return target


def _node(p: Path, depth: int, root: Path, key: str) -> dict:
    rel = "" if p == root else str(p.relative_to(root))
    # RAG_Content — относительные пути (legacy/тесты); внешние — с префиксом ключа.
    if key == _DEFAULT_KEY:
        path_id = rel
    else:
        path_id = f"{key}{_ROOT_SEP}{rel}" if rel else f"{key}{_ROOT_SEP}"
    item: dict = {"name": p.name or key, "path": path_id, "dir": p.is_dir()}
    if p.is_dir() and depth > 0:
        try:
            children = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError:
            children = []
        item["children"] = [
            _node(c, depth - 1, root, key) for c in children if not c.name.startswith(".")
        ][:500]
    return item


@router.get("/tree")
async def rag_tree(
    path: str = "",
    depth: int = Query(default=1, ge=1, le=3),
    _user=Depends(require_user),
):
    roots = _roots()
    # Верхний уровень при наличии внешних корней — синтетический супер-корень
    # «Источники» с детьми-корнями (RAG_Content + внешние). Без внешних — как было.
    if not path and len(roots) > 1:
        children = []
        for key, rp in roots.items():
            rr = rp.resolve()
            if rr.exists():
                child = _node(rr, depth - 1, rr, key)
                child["name"] = key  # ярлык корня — ключ (а не имя tmp/папки)
                children.append(child)
        return {"name": "Источники", "path": "", "dir": True, "children": children}

    base = _safe(path)
    if not base.exists():
        raise HTTPException(404, "путь не найден")
    key, _rel = _split_key(path)
    root = roots[key].resolve()
    return _node(base, depth, root, key)


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
