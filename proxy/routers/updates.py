"""Manual LES update endpoints. No background checks or automatic installation."""

from fastapi import APIRouter, Depends, HTTPException

from proxy.security import require_admin, require_user
from proxy.services.update_service import UpdateError, check_update, download_and_launch_update


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
