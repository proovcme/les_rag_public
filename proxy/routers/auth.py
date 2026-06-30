"""В.О.Л.К. auth routes for LES Proxy."""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from proxy.config import ADMIN_ROLE, META_DB_PATH, USER_ROLE
from proxy.security import (
    RequestUser,
    is_protected_admin_key_value,
    require_admin,
    trust_diagnostics,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthVerifyReq(BaseModel):
    key: str
    fingerprint: str = ""


class AuthKeyCreate(BaseModel):
    key_value: str
    holder_name: str = ""
    role: str = "user"
    expires_days: int = 0


class AuthKeyToggle(BaseModel):
    key_value: str
    is_active: int = 1


class AuthKeyDelete(BaseModel):
    key_value: str


def auth_db() -> sqlite3.Connection:
    conn = sqlite3.connect(META_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_keys (
            key_value          TEXT PRIMARY KEY,
            holder_name        TEXT NOT NULL DEFAULT '',
            role               TEXT NOT NULL DEFAULT 'user',
            is_active          INTEGER NOT NULL DEFAULT 1,
            created_at         TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            expires_at         TEXT DEFAULT NULL,
            device_fingerprint TEXT DEFAULT NULL
        )
        """
    )
    cols = [r[1] for r in conn.execute("PRAGMA table_info(auth_keys)").fetchall()]
    if "expires_at" not in cols:
        conn.execute("ALTER TABLE auth_keys ADD COLUMN expires_at TEXT DEFAULT NULL")
    if "device_fingerprint" not in cols:
        conn.execute("ALTER TABLE auth_keys ADD COLUMN device_fingerprint TEXT DEFAULT NULL")
    conn.commit()
    return conn


def _is_trusted_admin_actor(actor) -> bool:
    return isinstance(actor, RequestUser) and actor.is_trusted_network_admin


def _is_root_admin_actor(actor) -> bool:
    return isinstance(actor, RequestUser) and actor.is_root_admin


def _effective_role_for_key(key_value: str, stored_role: str) -> str:
    return ADMIN_ROLE if is_protected_admin_key_value(key_value) else stored_role


def _guard_protected_key_mutation(key_value: str, actor) -> None:
    if is_protected_admin_key_value(key_value) and not _is_trusted_admin_actor(actor):
        raise HTTPException(
            status_code=403,
            detail="les-admin key can be changed only from trusted network",
        )


def seed_admin_key() -> None:
    # БЕЗОПАСНОСТЬ: НЕ дефолтить предсказуемым «admin123». Нет ADMIN_PASSWORD в .env →
    # СЛУЧАЙНЫЙ admin-ключ + громкий лог (оператор берёт его в Доступ/auth_keys).
    admin_key = (os.getenv("ADMIN_PASSWORD") or "").strip()
    generated = False
    if not admin_key:
        import secrets
        admin_key = "les-admin-" + secrets.token_hex(12)
        generated = True
    conn = auth_db()
    try:
        exists = conn.execute("SELECT 1 FROM auth_keys WHERE role='admin' LIMIT 1").fetchone()
        if not exists:
            conn.execute(
                "INSERT OR IGNORE INTO auth_keys (key_value, holder_name, role) VALUES (?,?,?)",
                (admin_key, "admin", "admin"),
            )
            conn.commit()
            if generated:
                logger.warning("[В.О.Л.К.] ADMIN_PASSWORD не задан — создан СЛУЧАЙНЫЙ admin-ключ «%s» "
                               "(задай ADMIN_PASSWORD в .env для стабильного; НЕ admin123)", admin_key)
            else:
                logger.info("[В.О.Л.К.] Admin-ключ создан из ADMIN_PASSWORD")
    finally:
        conn.close()


@router.post("/verify")
async def auth_verify(req: AuthVerifyReq):
    conn = auth_db()
    try:
        row = conn.execute(
            "SELECT key_value, role, holder_name, expires_at, device_fingerprint "
            "FROM auth_keys WHERE key_value=? AND is_active=1",
            (req.key.strip(),),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Неверный ключ или ключ отключён")

        protected_admin = is_protected_admin_key_value(row["key_value"])
        role = _effective_role_for_key(row["key_value"], row["role"])

        if not protected_admin and row["expires_at"] and datetime.now() > datetime.fromisoformat(
            row["expires_at"].replace(" ", "T")
        ):
            raise HTTPException(status_code=401, detail="Ключ истёк")

        fp = req.fingerprint.strip()
        stored_fp = row["device_fingerprint"]
        if fp and not protected_admin:
            if not stored_fp:
                conn.execute(
                    "UPDATE auth_keys SET device_fingerprint=? WHERE key_value=?",
                    (fp, req.key.strip()),
                )
                conn.commit()
                logger.info("[В.О.Л.К.] Устройство привязано к ключу %s...", req.key[:12])
            elif stored_fp != fp:
                raise HTTPException(status_code=403, detail="Ключ привязан к другому устройству")

        return {"role": role, "holder": row["holder_name"]}
    finally:
        conn.close()


@router.get("/trust")
async def auth_trust(request: Request):
    return trust_diagnostics(request)


@router.get("/keys")
async def auth_list_keys(_admin=Depends(require_admin)):
    conn = auth_db()
    try:
        rows = conn.execute(
            "SELECT key_value, holder_name, role, is_active, created_at, expires_at, "
            "CASE WHEN device_fingerprint IS NULL THEN 0 ELSE 1 END as device_bound "
            "FROM auth_keys ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        item = dict(row)
        protected = is_protected_admin_key_value(item.get("key_value", ""))
        if protected:
            item["role"] = ADMIN_ROLE
            item["expires_at"] = None
            item["device_bound"] = 0
        item["protected_admin"] = 1 if protected else 0
        result.append(item)
    return result


@router.post("/keys")
async def auth_create_key(req: AuthKeyCreate, _admin=Depends(require_admin)):
    if not req.key_value.strip():
        raise HTTPException(400, "key_value не может быть пустым")
    if req.role not in {USER_ROLE, ADMIN_ROLE}:
        raise HTTPException(400, "Недопустимая роль ключа")
    protected_admin = is_protected_admin_key_value(req.key_value)
    role = ADMIN_ROLE if protected_admin else req.role
    if role == ADMIN_ROLE and not _is_root_admin_actor(_admin):
        raise HTTPException(403, "Admin/root keys can be created only from trusted network or les-admin key")
    expires_at = None
    if not protected_admin and req.expires_days > 0:
        expires_at = (datetime.now() + timedelta(days=req.expires_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    conn = auth_db()
    try:
        conn.execute(
            "INSERT INTO auth_keys (key_value, holder_name, role, expires_at) VALUES (?,?,?,?)",
            (req.key_value.strip(), req.holder_name.strip(), role, expires_at),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Ключ уже существует")
    finally:
        conn.close()
    kind = f"временный до {expires_at}" if expires_at else "постоянный"
    logger.info("[В.О.Л.К.] Новый ключ: %s [%s] %s", req.holder_name, role, kind)
    return {
        "status": "created",
        "key_value": req.key_value,
        "role": role,
        "expires_at": expires_at,
    }


@router.post("/keys/toggle")
async def auth_toggle_key(req: AuthKeyToggle, _admin=Depends(require_admin)):
    _guard_protected_key_mutation(req.key_value, _admin)
    conn = auth_db()
    try:
        conn.execute(
            "UPDATE auth_keys SET is_active=? WHERE key_value=?",
            (req.is_active, req.key_value),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "key_value": req.key_value, "is_active": req.is_active}


@router.post("/keys/reset-device")
async def auth_reset_device(req: AuthKeyToggle, _admin=Depends(require_admin)):
    _guard_protected_key_mutation(req.key_value, _admin)
    conn = auth_db()
    try:
        conn.execute(
            "UPDATE auth_keys SET device_fingerprint=NULL WHERE key_value=?",
            (req.key_value,),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("[В.О.Л.К.] Устройство отвязано от ключа %s...", req.key_value[:12])
    return {"status": "ok", "key_value": req.key_value}


@router.delete("/keys/{key_value}")
async def auth_delete_key(key_value: str, _admin=Depends(require_admin)):
    return delete_auth_key(key_value, actor=_admin)


@router.post("/keys/delete")
async def auth_delete_key_body(req: AuthKeyDelete, _admin=Depends(require_admin)):
    return delete_auth_key(req.key_value, actor=_admin)


def delete_auth_key(key_value: str, actor=None):
    _guard_protected_key_mutation(key_value, actor)
    conn = auth_db()
    try:
        conn.execute("DELETE FROM auth_keys WHERE key_value=?", (key_value,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "deleted", "key_value": key_value}
