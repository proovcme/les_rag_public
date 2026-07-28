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

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response

from proxy.security import require_user
from proxy.services.file_viewer_service import file_viewer_html, is_viewable_file
from proxy.services.pdf_contour_service import render_page_preview
from proxy.services.pdf_viewer_service import pdf_file_info, viewer_html

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
    rel = path or ""
    if rel == _DEFAULT_KEY:
        rel = ""
    elif rel.startswith(f"{_DEFAULT_KEY}/"):
        rel = rel[len(_DEFAULT_KEY) + 1:]
    return _DEFAULT_KEY, rel


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


def _pdf(path: str) -> Path:
    target = _safe(path)
    if not target.is_file():
        raise HTTPException(404, "файл не найден")
    if target.suffix.lower() != ".pdf":
        raise HTTPException(415, "viewer доступен только для PDF")
    return target


def _bbox(value: str, *, field: str) -> tuple[float, float, float, float] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        values = tuple(float(item.strip()) for item in raw.split(","))
    except ValueError as exc:
        raise HTTPException(400, f"{field} должен содержать четыре числа") from exc
    if len(values) != 4:
        raise HTTPException(400, f"{field} должен содержать четыре числа")
    return values


@router.get("/file/pdf-info")
async def rag_file_pdf_info(path: str, _user=Depends(require_user)):
    target = _pdf(path)
    try:
        return await asyncio.to_thread(pdf_file_info, target)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/file/pdf-preview")
async def rag_file_pdf_preview(
    path: str,
    page: int = Query(default=1, ge=1),
    width: int = Query(default=1100, ge=320, le=1800),
    highlight_bbox: str = Query(default="", max_length=160),
    _user=Depends(require_user),
):
    target = _pdf(path)
    try:
        content = await asyncio.to_thread(
            render_page_preview,
            target,
            page_number=page,
            max_width=width,
            highlight_bbox=_bbox(highlight_bbox, field="highlight_bbox"),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "Content-Disposition": f'inline; filename="page-{page}.png"'},
    )


@router.get("/file/pdf-viewer", response_class=HTMLResponse)
async def rag_file_pdf_viewer(
    path: str,
    page: int = Query(default=1, ge=1),
    bbox: str = Query(default="", max_length=160),
    _user=Depends(require_user),
):
    target = _pdf(path)
    try:
        info = await asyncio.to_thread(pdf_file_info, target)
        html = viewer_html(
            path_id=path,
            file_name=str(info["name"]),
            page_count=int(info["page_count"]),
            initial_page=page,
            highlight_bbox=_bbox(bbox, field="bbox"),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return HTMLResponse(html, headers={"Cache-Control": "private, no-store"})


@router.get("/file/viewer", response_class=HTMLResponse)
async def rag_file_viewer(
    path: str,
    page: int = Query(default=1, ge=1),
    bbox: str = Query(default="", max_length=160),
    locator: str = Query(default="", max_length=240),
    sheet: str = Query(default="", max_length=180),
    _user=Depends(require_user),
):
    """One guarded, read-only GUI entry point for PDF and office evidence."""
    target = _safe(path)
    if not target.is_file():
        raise HTTPException(404, "файл не найден")
    if not is_viewable_file(target):
        raise HTTPException(415, "встроенный просмотр для этого формата недоступен")
    try:
        if target.suffix.lower() == ".pdf":
            info = await asyncio.to_thread(pdf_file_info, target)
            content = viewer_html(
                path_id=path,
                file_name=str(info["name"]),
                page_count=int(info["page_count"]),
                initial_page=page,
                highlight_bbox=_bbox(bbox, field="bbox"),
            )
        else:
            content = await asyncio.to_thread(
                file_viewer_html,
                target,
                path_id=path,
                locator=locator,
                sheet=sheet,
            )
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(400, f"Не удалось открыть предпросмотр: {str(exc)[:240]}") from exc
    return HTMLResponse(content, headers={"Cache-Control": "private, no-store"})
