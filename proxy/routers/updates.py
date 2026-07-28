"""Manual LES update endpoints. No background checks or automatic installation."""

from fastapi import APIRouter, Depends, HTTPException

from proxy.security import require_admin, require_user
from proxy.services.update_service import (
    UpdateError,
    check_mac_update,
    check_update,
    check_vps_patch,
    download_and_launch_update,
    download_and_launch_vps_patch,
    launch_mac_update,
    read_mac_update_status,
    read_vps_patch_status,
)


router = APIRouter(prefix="/api/update", tags=["update"])


@router.get("/check")
async def update_check(_user=Depends(require_user)):
    try:
        return await check_update()
    except UpdateError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/install")
async def update_install(_admin=Depends(require_admin)):
    try:
        return await download_and_launch_update()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/patch/check")
async def patch_check(_user=Depends(require_user)):
    try:
        return await check_vps_patch()
    except UpdateError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/patch/status")
async def patch_status(_user=Depends(require_user)):
    return read_vps_patch_status()


@router.post("/patch/install")
async def patch_install(_admin=Depends(require_admin)):
    try:
        return await download_and_launch_vps_patch()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/mac/check")
async def mac_update_check(_user=Depends(require_user)):
    try:
        return check_mac_update()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/mac/status")
async def mac_update_status(_user=Depends(require_user)):
    return read_mac_update_status()


@router.post("/mac/install")
async def mac_update_install(_admin=Depends(require_admin)):
    try:
        return launch_mac_update()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
