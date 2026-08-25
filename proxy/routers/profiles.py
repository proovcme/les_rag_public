"""Operator API for immutable chat profile revisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from proxy.security import require_admin, require_user
from proxy.services.chat_profile_service import (
    PROFILE_PROMPT_MAX_CHARS,
    PROFILE_SKILL_MAX_CHARS,
    activate_profile_revision,
    delete_revision,
    import_legacy_prompt_overrides,
    publish_profile_revision,
    publish_text_revision,
    registry_snapshot,
    resolve_chat_profile,
)


router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _profiles_db_path() -> Path | None:
    """Injection seam for isolated API tests; production uses canonical MetaDB."""

    return None


class TextRevisionRequest(BaseModel):
    kind: Literal["prompt", "skill"]
    name: str = Field(min_length=1, max_length=160)
    text: str = Field(
        min_length=1,
        description=(
            f"Prompt: не более {PROFILE_PROMPT_MAX_CHARS} символов; "
            f"skill: не более {PROFILE_SKILL_MAX_CHARS}."
        ),
        json_schema_extra={
            "x-les-max-length-by-kind": {
                "prompt": PROFILE_PROMPT_MAX_CHARS,
                "skill": PROFILE_SKILL_MAX_CHARS,
            }
        },
    )
    source_revision_id: str | None = None


class ProfileRevisionRequest(BaseModel):
    mode: str
    name: str = Field(min_length=1, max_length=160)
    prompt_revision_id: str
    skill_revision_id: str
    tools: list[str] = Field(default_factory=list)
    model_policy: dict[str, Any] = Field(default_factory=dict)
    rag_policy: dict[str, Any] = Field(default_factory=dict)
    source_revision_id: str | None = None


class ChatBindingRequest(BaseModel):
    mode: str
    profile_revision_id: str


def _conflict(error: ValueError) -> HTTPException:
    if str(error).startswith("profile_text_too_long:"):
        return HTTPException(
            status_code=409,
            detail={"code": "profile_text_too_long", "message": str(error)},
        )
    return HTTPException(status_code=409, detail=str(error))


@router.get("")
async def list_profiles(_user=Depends(require_user)):
    import_legacy_prompt_overrides(db_path=_profiles_db_path())
    return registry_snapshot(db_path=_profiles_db_path())


@router.post("/text-revisions")
async def create_text_revision(req: TextRevisionRequest, _admin=Depends(require_admin)):
    try:
        return publish_text_revision(
            req.kind,
            name=req.name,
            text=req.text,
            source_revision_id=req.source_revision_id,
            db_path=_profiles_db_path(),
        )
    except ValueError as error:
        raise _conflict(error) from error


@router.post("/revisions")
async def create_profile_revision(req: ProfileRevisionRequest, _admin=Depends(require_admin)):
    try:
        return publish_profile_revision(
            mode=req.mode,
            name=req.name,
            prompt_revision_id=req.prompt_revision_id,
            skill_revision_id=req.skill_revision_id,
            tools=req.tools,
            model_policy=req.model_policy,
            rag_policy=req.rag_policy,
            source_revision_id=req.source_revision_id,
            db_path=_profiles_db_path(),
        )
    except ValueError as error:
        raise _conflict(error) from error


@router.post("/{mode}/activate/{revision_id}")
async def activate_profile(mode: str, revision_id: str, _admin=Depends(require_admin)):
    try:
        return activate_profile_revision(
            mode, revision_id, db_path=_profiles_db_path()
        )
    except ValueError as error:
        raise _conflict(error) from error


@router.delete("/{kind}/{revision_id}")
async def remove_revision(kind: str, revision_id: str, _admin=Depends(require_admin)):
    try:
        return delete_revision(kind, revision_id, db_path=_profiles_db_path())
    except ValueError as error:
        raise _conflict(error) from error


@router.put("/chats/{session_id}/binding")
async def replace_chat_binding(
    session_id: str,
    req: ChatBindingRequest,
    _admin=Depends(require_admin),
):
    try:
        return resolve_chat_profile(
            session_id=session_id,
            requested_mode=req.mode,
            requested_revision_id=req.profile_revision_id,
            apply_revision=True,
            db_path=_profiles_db_path(),
        )
    except ValueError as error:
        raise _conflict(error) from error
