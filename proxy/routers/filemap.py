"""Карта файлового архива — W15.1 (LES3_PLAN). Без LLM, без чтения содержимого."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.smart_index import verify_source_file
from proxy.security import require_admin, require_user
from proxy.services.file_map_service import (
    map_stats,
    resolve_selection,
    scan_root,
    search_map,
    suggest_index_candidates,
)

router = APIRouter(prefix="/api/filemap", tags=["filemap"])


class ScanRequest(BaseModel):
    path: str
    max_files: int = 500_000


@router.post("/scan")
async def filemap_scan(req: ScanRequest, _admin=Depends(require_admin)):
    """Скан/рескан корня (инкрементальный по mtime). Только метаданные."""
    try:
        return await asyncio.to_thread(scan_root, Path(req.path), max_files=req.max_files)
    except ValueError as err:
        raise HTTPException(400, str(err))


@router.get("/search")
async def filemap_search(q: str = "", ext: str = "", cipher: str = "", limit: int = 100, _user=Depends(require_user)):
    """Поиск по карте: имя/путь/шифр (LIKE), фильтр расширения."""
    if not (q or ext or cipher):
        raise HTTPException(400, "укажи q, ext или cipher")
    return {"results": await asyncio.to_thread(search_map, q, ext, cipher, limit)}


@router.get("/stats")
async def filemap_stats(_user=Depends(require_user)):
    """Корни, топ расширений, файлы с распознанными шифрами."""
    return await asyncio.to_thread(map_stats)


@router.get("/candidates")
async def filemap_candidates(limit: int = 40, _user=Depends(require_user)):
    """Папки-кандидаты на индексацию (где лежат файлы с шифрами НТД/комплектов)."""
    return {"candidates": await asyncio.to_thread(suggest_index_candidates, limit)}


class IndexRequest(BaseModel):
    dataset_name: str
    root: str = ""
    rel_paths: list[str] | None = None
    path_prefix: str = ""
    q: str = ""
    ext: str = ""
    cipher: str = ""
    parse: bool = False
    parse_limit: int = 200
    max_files: int = 5000


@router.post("/index")
async def filemap_index(req: IndexRequest, _admin=Depends(require_admin)):
    """W15.2: проиндексировать выбранное из карты — создать датасет и втянуть файлы.

    Файлы копируются в staging самой системой (без ручного копирования оператором),
    проходят те же фильтры, что обычный sync. Контент читается уже на этапе parse.
    """
    from proxy.routers.datasets import assert_parse_admission, get_dataset_state

    name = req.dataset_name.strip()
    if len(name) < 2:
        raise HTTPException(400, "dataset_name слишком короткий")
    if not (req.rel_paths or req.path_prefix or req.q or req.ext or req.cipher):
        raise HTTPException(400, "пустой выбор: задай rel_paths, path_prefix, q, ext или cipher")

    selection = await asyncio.to_thread(
        resolve_selection,
        root=req.root,
        rel_paths=req.rel_paths,
        path_prefix=req.path_prefix,
        q=req.q,
        ext=req.ext,
        cipher=req.cipher,
        limit=req.max_files,
    )
    if not selection:
        raise HTTPException(404, "по выбору ничего не найдено в карте (сделай scan?)")

    accepted: list[dict] = []
    rejected: dict[str, int] = {}
    for item in selection:
        path = Path(item["abs_path"])
        decision = verify_source_file(path, path.parent)
        if decision.accepted:
            accepted.append(item)
        else:
            rejected[decision.reason] = rejected.get(decision.reason, 0) + 1
    if not accepted:
        return {"status": "nothing_supported", "selected": len(selection), "rejected": rejected}

    state = get_dataset_state()
    ds_list = await state.backend.list_datasets()
    dataset_id = next((d.id for d in ds_list if d.name == name), None)
    created = dataset_id is None
    if dataset_id is None:
        dataset_id = await state.backend.create_dataset(name)

    for item in accepted:
        await state.backend.upload_file(
            dataset_id, Path(item["abs_path"]), relative_path=item["rel_path"]
        )

    parse_result = None
    if req.parse:
        async with state.sync_parse_semaphore:
            await assert_parse_admission(state)
            parse_result = await state.backend.parse_dataset(dataset_id, limit=req.parse_limit)

    return {
        "status": "indexed",
        "dataset_id": dataset_id,
        "dataset_name": name,
        "dataset_created": created,
        "registered": len(accepted),
        "selected": len(selection),
        "rejected": rejected,
        "parse_started": req.parse,
        "parse_result": parse_result,
    }
