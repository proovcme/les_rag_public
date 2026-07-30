"""Authenticated API for persistent conversational RIM estimate sessions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from proxy.security import RequestUser, require_user
from proxy.smeta_core import application as smeta_application
from proxy.smeta_core.rim_session import (
    RimSessionConflict,
    RimSessionError,
    RimSessionForbidden,
    RimSessionNotFound,
    RimSessionValidationError,
)
from proxy.smeta_core.source_intake import intake_vor_document
from proxy.services.rim_mapping_xlsx_service import read_mapping_xlsx, render_mapping_xlsx
from proxy.services.rim_mapping_progress_service import build_mapping_progress
from proxy.services.rim_mapping_review_service import review_mapping
from proxy.services.rim_agent_action_service import model_tool_specs, validate_model_action
from proxy.services.rim_agent_turn_service import run_rim_agent_turn
from proxy.services.rim_scenario_service import (
    calculation_rows_for_scenario,
    requirements_from_calculation,
    validate_authored_scenarios,
)
from proxy.services.rim_session_xlsx_service import render_session_lsr_xlsx


router = APIRouter(prefix="/api/rim", tags=["rim"])
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_SOURCE_BYTES = 50 * 1024 * 1024


def _store():
    return smeta_application.get_rim_session_store()


def _actor(user: RequestUser) -> str:
    return str(user.holder or user.source or user.role)


def _allow_admin(user: RequestUser) -> bool:
    return bool(user.is_root_admin)


def _raise_http(error: Exception) -> None:
    if isinstance(error, RimSessionNotFound):
        raise HTTPException(404, str(error)) from error
    if isinstance(error, RimSessionForbidden):
        raise HTTPException(403, str(error)) from error
    if isinstance(error, RimSessionConflict):
        raise HTTPException(409, str(error)) from error
    if isinstance(error, (RimSessionValidationError, ValueError)):
        raise HTTPException(422, str(error)) from error
    if isinstance(error, RimSessionError):
        raise HTTPException(400, str(error)) from error
    raise error


def _session_root(session_id: str) -> Path:
    root = _store().root.resolve()
    target = (root / "files" / session_id).resolve()
    if root not in target.parents:
        raise HTTPException(422, "invalid session path")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _save_upload(session_id: str, name: str, content: bytes) -> Path:
    suffix = Path(name or "").suffix.lower()
    if suffix not in {".xlsx", ".xlsm", ".csv"}:
        raise HTTPException(415, "Поддерживаются XLSX, XLSM и CSV")
    digest = hashlib.sha256(content).hexdigest()
    target = _session_root(session_id) / "sources" / f"{digest}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_bytes(content)
        temp.replace(target)
    return target


def _vor_lines(intake: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(intake.get("work_items") or [], 1):
        refs = list(item.get("source_refs") or [])
        assumptions = list(item.get("assumptions") or [])
        result.append(
            {
                "schema": "rim_vor_line_v1",
                "work_id": str(item.get("work_id") or f"vor-{index:04d}"),
                "order_no": index * 10,
                "section_code": "",
                "section_name": str(item.get("section") or ""),
                "work_name": str(item.get("title") or ""),
                "unit": str(item.get("unit") or ""),
                "quantity": item.get("quantity"),
                "note": str(item.get("note") or ""),
                "source_row": item.get("source_row"),
                "source_ref": refs[0] if refs else "",
                "source_refs": refs,
                "quantity_origin": "source_explicit",
                "quantity_formula": "",
                "status": "invalid" if assumptions else "valid",
                "assumptions": assumptions,
            }
        )
    return result


class CreateSessionRequest(BaseModel):
    project_id: str = ""
    normative_base_version: str = ""
    pricebook_id: str = ""
    region_code: str = ""
    price_period: str = ""


class RevisionRequest(BaseModel):
    expected_parent_revision_id: str = ""


class VorRevisionRequest(RevisionRequest):
    rows: list[dict[str, Any]]
    created_by: Literal["model", "user"] = "model"
    change_note: str = ""


class MappingRevisionRequest(RevisionRequest):
    mapping_rows: list[dict[str, Any]]
    created_by: Literal["model", "user"] = "model"
    change_note: str = ""


class MappingGlobalReviewRequest(MappingRevisionRequest):
    professional_conflicts: list[dict[str, Any]] = Field(default_factory=list)


class MappingLockRequest(RevisionRequest):
    review_note: str
    accepted_conflict_ids: list[str] = Field(default_factory=list)


class OpenQuestionRequest(RevisionRequest):
    text: str
    reason: str = ""
    work_ids: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    answer_schema: dict[str, Any] = Field(default_factory=dict)


class AnswerQuestionRequest(RevisionRequest):
    answer: dict[str, Any]


class PricingRevisionRequest(RevisionRequest):
    trace: dict[str, Any]
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    created_by: Literal["model", "user"] = "model"
    change_note: str = ""


class RequirementResolutionRequest(RevisionRequest):
    status: Literal["resolved", "waived_by_user"]
    resolution: dict[str, Any]


class FinalizeRequest(RevisionRequest):
    review_note: str


class GenerateScenariosRequest(RevisionRequest):
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    max_combinations: int = 1000
    created_by: Literal["model", "user"] = "model"


class CalculateScenarioRequest(RevisionRequest):
    scenario_id: str
    title: str = "ЛСР РИМ"
    book: str | None = None
    kac_map: dict[str, float] = Field(default_factory=dict)
    k_ozp: float = 1.0
    k_em: float = 1.0
    coefficient_basis: str = ""


class AgentActionRequest(BaseModel):
    action: str
    arguments: dict[str, Any]
    user_visible_intent: str


class AgentTurnRequest(BaseModel):
    message: str = ""


def _workflow_payloads(
    session_id: str,
    *,
    user: RequestUser,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    store = _store()
    session = store.get_session(
        session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
    )
    vor_revision_id = str(session.get("current_vor_revision_id") or "")
    if not vor_revision_id:
        raise RimSessionConflict("VOR revision is required")
    vor = store.revision_payload(
        session_id,
        vor_revision_id,
        owner_id=_actor(user),
        allow_admin=_allow_admin(user),
    )["payload"]
    mapping_lock_id = str(session.get("mapping_lock_revision_id") or "")
    if not mapping_lock_id:
        raise RimSessionConflict("mapping lock is required")
    mapping_lock = store.revision_payload(
        session_id,
        mapping_lock_id,
        owner_id=_actor(user),
        allow_admin=_allow_admin(user),
    )["payload"]
    mapping_revision_id = str(mapping_lock.get("mapping_revision_id") or "")
    mapping = store.revision_payload(
        session_id,
        mapping_revision_id,
        owner_id=_actor(user),
        allow_admin=_allow_admin(user),
    )["payload"]
    scenario_payload: dict[str, Any] | None = None
    scenario_revision_id = str(session.get("current_scenario_revision_id") or "")
    if scenario_revision_id:
        scenario_payload = store.revision_payload(
            session_id,
            scenario_revision_id,
            owner_id=_actor(user),
            allow_admin=_allow_admin(user),
        )["payload"]
    return (
        session,
        list(vor.get("rows") or []),
        list(mapping.get("mapping_rows") or []),
        scenario_payload,
    )


@router.post("/sessions")
async def create_session(
    req: CreateSessionRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        result = _store().create_session(
            owner_id=_actor(user),
            project_id=req.project_id,
            normative_base_version=req.normative_base_version,
            pricebook_id=req.pricebook_id,
            region_code=req.region_code,
            price_period=req.price_period,
        )
        return result.as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(default=100, ge=1, le=500),
    user: RequestUser = Depends(require_user),
):
    try:
        return {
            "sessions": _store().list_sessions(
                owner_id=_actor(user),
                allow_admin=_allow_admin(user),
                limit=limit,
            )
        }
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: RequestUser = Depends(require_user),
):
    try:
        return _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/revisions")
async def list_revisions(
    session_id: str,
    user: RequestUser = Depends(require_user),
):
    try:
        return {
            "session_id": session_id,
            "revisions": _store().list_revisions(
                session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
            ),
        }
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/agent/tools")
async def get_agent_tools(
    session_id: str,
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        return {
            "session_id": session_id,
            "state": session["display_state"],
            "tools": model_tool_specs(session),
        }
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/agent/actions/validate")
async def validate_agent_action(
    session_id: str,
    req: AgentActionRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        return validate_model_action(session, req.model_dump())
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/agent/turn")
async def run_agent_turn(
    session_id: str,
    req: AgentTurnRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        from proxy.services import smeta_chat_adapter_service as adapters

        return await asyncio.to_thread(
            run_rim_agent_turn,
            _store(),
            session_id,
            owner_id=_actor(user),
            user_message=req.message,
            exchange=adapters._smeta_document_exchange,
            mapping_exchange=adapters._smeta_document_mapping_exchange,
            allow_admin=_allow_admin(user),
        )
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/vor/import")
async def import_vor(
    session_id: str,
    file: UploadFile = File(...),
    source_kind: Literal["vor", "specification", "auto"] = Form(default="vor"),
    expected_parent_revision_id: str = Form(default=""),
    column_map_json: str = Form(default=""),
    user: RequestUser = Depends(require_user),
):
    try:
        _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        content = await file.read()
        if not content:
            raise ValueError("Загруженный файл пуст")
        if len(content) > _MAX_SOURCE_BYTES:
            raise ValueError("Файл превышает лимит 50 МБ")
        try:
            column_map = json.loads(column_map_json) if column_map_json else None
        except json.JSONDecodeError as error:
            raise ValueError("column_map_json должен быть JSON-объектом") from error
        if column_map is not None and not isinstance(column_map, dict):
            raise ValueError("column_map_json должен быть JSON-объектом")
        path = _save_upload(session_id, file.filename or "source.xlsx", content)
        intake = intake_vor_document(path, column_map=column_map)
        intake["original_filename"] = Path(file.filename or path.name).name
        intake["stored_source_ref"] = f"rim-session:{session_id}:sha256:{intake['source_sha256']}"
        intake_result = _store().save_intake(
            session_id,
            owner_id=_actor(user),
            intake=intake,
            expected_parent_revision_id=expected_parent_revision_id,
            source_kind=source_kind,
            allow_admin=_allow_admin(user),
        )
        if source_kind == "vor" and intake.get("work_items"):
            return _store().save_vor_revision(
                session_id,
                owner_id=_actor(user),
                rows=_vor_lines(intake),
                expected_parent_revision_id=intake_result.revision_id,
                created_by="user",
                change_note=f"Импорт {Path(file.filename or path.name).name}",
                allow_admin=_allow_admin(user),
            ).as_dict()
        return intake_result.as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/vor")
async def get_vor(
    session_id: str,
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        revision_id = str(session.get("current_vor_revision_id") or "")
        if not revision_id:
            return {"session_id": session_id, "revision_id": "", "rows": [], "issues": []}
        revision = _store().revision_payload(
            session_id,
            revision_id,
            owner_id=_actor(user),
            allow_admin=_allow_admin(user),
        )
        payload = revision["payload"]
        return {
            "session_id": session_id,
            "revision_id": revision_id,
            "rows": payload.get("rows") or [],
            "issues": payload.get("issues") or [],
        }
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/vor/revisions")
async def save_vor_revision(
    session_id: str,
    req: VorRevisionRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        return _store().save_vor_revision(
            session_id,
            owner_id=_actor(user),
            rows=req.rows,
            expected_parent_revision_id=req.expected_parent_revision_id,
            created_by=req.created_by,
            change_note=req.change_note,
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/mapping/candidates")
async def save_mapping_candidates(
    session_id: str,
    req: MappingRevisionRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        return _store().save_mapping_revision(
            session_id,
            owner_id=_actor(user),
            mapping_rows=req.mapping_rows,
            expected_parent_revision_id=req.expected_parent_revision_id,
            created_by=req.created_by,
            change_note=req.change_note,
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/mapping")
async def get_mapping(
    session_id: str,
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        revision_id = str(session.get("current_mapping_revision_id") or "")
        if not revision_id:
            return {
                "session_id": session_id,
                "revision_id": "",
                "mapping_rows": [],
                "issues": [],
                "professional_conflicts": [],
            }
        payload = _store().revision_payload(
            session_id,
            revision_id,
            owner_id=_actor(user),
            allow_admin=_allow_admin(user),
        )["payload"]
        return {
            "session_id": session_id,
            "revision_id": revision_id,
            "mapping_rows": payload.get("mapping_rows") or [],
            "issues": payload.get("issues") or [],
            "professional_conflicts": payload.get("professional_conflicts") or [],
        }
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/mapping/progress")
async def get_mapping_progress(
    session_id: str,
    user: RequestUser = Depends(require_user),
):
    try:
        store = _store()
        session = store.get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        vor_revision_id = str(session.get("current_vor_revision_id") or "")
        if not vor_revision_id:
            return {
                "session_id": session_id,
                **build_mapping_progress([], None),
            }
        vor = store.revision_payload(
            session_id,
            vor_revision_id,
            owner_id=_actor(user),
            allow_admin=_allow_admin(user),
        )["payload"]
        checkpoint = store.load_agent_checkpoint(
            session_id,
            owner_id=_actor(user),
            checkpoint_kind="norm_mapping",
            base_revision_id=vor_revision_id,
            allow_admin=_allow_admin(user),
        )
        return {
            "session_id": session_id,
            **build_mapping_progress(list(vor.get("rows") or []), checkpoint),
        }
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/mapping/global-review")
async def save_mapping_global_review(
    session_id: str,
    req: MappingGlobalReviewRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        vor_revision_id = str(session.get("current_vor_revision_id") or "")
        if not vor_revision_id:
            raise RimSessionConflict("VOR revision is required")
        vor_payload = _store().revision_payload(
            session_id,
            vor_revision_id,
            owner_id=_actor(user),
            allow_admin=_allow_admin(user),
        )["payload"]
        detected = review_mapping(
            list(vor_payload.get("rows") or []),
            req.mapping_rows,
        )
        return _store().save_mapping_revision(
            session_id,
            owner_id=_actor(user),
            mapping_rows=req.mapping_rows,
            expected_parent_revision_id=req.expected_parent_revision_id,
            created_by=req.created_by,
            revision_kind="mapping_global_review",
            conflicts=[*detected, *req.professional_conflicts],
            change_note=req.change_note,
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/mapping/export")
async def export_mapping(
    session_id: str,
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        revision_id = str(session.get("current_mapping_revision_id") or "")
        mapping_rows: list[dict[str, Any]] = []
        if revision_id:
            revision = _store().revision_payload(
                session_id,
                revision_id,
                owner_id=_actor(user),
                allow_admin=_allow_admin(user),
            )
            mapping_rows = list(revision["payload"].get("mapping_rows") or [])
        target = _session_root(session_id) / "exports" / f"mapping_{revision_id or 'empty'}.xlsx"
        render_mapping_xlsx(
            mapping_rows,
            target,
            session_id=session_id,
            parent_revision_id=session["head_revision_id"],
            vor_revision_id=session["current_vor_revision_id"],
        )
        return FileResponse(target, media_type=_XLSX_MEDIA, filename=target.name)
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/mapping/import")
async def import_mapping(
    session_id: str,
    file: UploadFile = File(...),
    expected_parent_revision_id: str = Form(default=""),
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        content = await file.read()
        if not content or len(content) > _MAX_SOURCE_BYTES:
            raise ValueError("Некорректный размер mapping XLSX")
        if Path(file.filename or "").suffix.lower() != ".xlsx":
            raise ValueError("Mapping round-trip поддерживает только XLSX")
        digest = hashlib.sha256(content).hexdigest()
        target = _session_root(session_id) / "imports" / f"mapping_{digest}.xlsx"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temp = target.with_suffix(".xlsx.tmp")
            temp.write_bytes(content)
            temp.replace(target)
        imported = read_mapping_xlsx(
            target,
            expected_session_id=session_id,
            expected_vor_revision_id=session["current_vor_revision_id"],
        )
        expected = expected_parent_revision_id or str(
            imported["manifest"].get("parent_revision_id") or ""
        )
        return _store().save_mapping_revision(
            session_id,
            owner_id=_actor(user),
            mapping_rows=imported["mapping_rows"],
            expected_parent_revision_id=expected,
            created_by="user",
            revision_kind="mapping_xlsx_import",
            change_note=f"Импорт {Path(file.filename or target.name).name}",
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/mapping/lock")
async def lock_mapping(
    session_id: str,
    req: MappingLockRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        return _store().lock_mapping(
            session_id,
            owner_id=_actor(user),
            review_note=req.review_note,
            accepted_conflict_ids=req.accepted_conflict_ids,
            expected_parent_revision_id=req.expected_parent_revision_id,
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/combinations/generate")
async def generate_scenarios(
    session_id: str,
    req: GenerateScenariosRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        session, work_rows, mapping_rows, _scenario_payload = _workflow_payloads(
            session_id, user=user
        )
        scenario_set = validate_authored_scenarios(
            work_rows,
            mapping_rows,
            req.scenarios,
            max_combinations=req.max_combinations,
        )
        return _store().save_scenario_revision(
            session_id,
            owner_id=_actor(user),
            scenario_set=scenario_set,
            expected_parent_revision_id=(
                req.expected_parent_revision_id or session["head_revision_id"]
            ),
            created_by=req.created_by,
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/combinations")
async def get_scenarios(
    session_id: str,
    user: RequestUser = Depends(require_user),
):
    try:
        session, _work_rows, _mapping_rows, scenario_payload = _workflow_payloads(
            session_id, user=user
        )
        return {
            "session_id": session_id,
            "revision_id": session.get("current_scenario_revision_id") or "",
            "status": session.get("scenario_status") or "not_started",
            **(scenario_payload or {"scenarios": [], "issues": []}),
        }
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/recalculate")
@router.post("/sessions/{session_id}/combinations/calculate")
async def calculate_scenario(
    session_id: str,
    req: CalculateScenarioRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        session, work_rows, mapping_rows, scenario_payload = _workflow_payloads(
            session_id, user=user
        )
        if not scenario_payload or session.get("scenario_status") != "ready":
            raise RimSessionConflict("a ready authored scenario set is required")
        scenario = next(
            (
                item
                for item in (scenario_payload.get("scenarios") or [])
                if str(item.get("scenario_id") or "") == req.scenario_id
            ),
            None,
        )
        if scenario is None:
            raise RimSessionNotFound("RIM scenario not found")
        rows = calculation_rows_for_scenario(work_rows, mapping_rows, scenario)
        trace = smeta_application.calculate_visible_rows_revision(
            rows,
            selected_by=str(scenario.get("authored_by") or "model"),
            created_by="user",
            parent_revision_id=session["mapping_lock_revision_id"],
            change_note=f"Расчёт сценария {req.scenario_id}",
            revision_root=str(_session_root(session_id) / "calculations"),
            title=req.title,
            book=req.book or session.get("pricebook_id") or None,
            kac_map=req.kac_map,
            k_ozp=req.k_ozp,
            k_em=req.k_em,
            coefficient_basis=req.coefficient_basis,
        )
        trace["rim_session"] = {
            "session_id": session_id,
            "vor_revision_id": session["current_vor_revision_id"],
            "mapping_lock_revision_id": session["mapping_lock_revision_id"],
            "scenario_revision_id": session["current_scenario_revision_id"],
            "scenario_id": req.scenario_id,
            "normative_base_version": session["normative_base_version"],
            "pricebook_id": req.book or session.get("pricebook_id") or "",
            "region_code": session["region_code"],
            "price_period": session["price_period"],
        }
        requirements = requirements_from_calculation(trace)
        result = _store().save_pricing_revision(
            session_id,
            owner_id=_actor(user),
            trace=trace,
            requirements=requirements,
            expected_parent_revision_id=(
                req.expected_parent_revision_id or session["head_revision_id"]
            ),
            created_by="user",
            change_note=f"Сценарий {req.scenario_id}",
            allow_admin=_allow_admin(user),
        )
        response = result.as_dict()
        response["trace"] = trace
        return response
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/questions")
async def open_question(
    session_id: str,
    req: OpenQuestionRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        return _store().open_question(
            session_id,
            owner_id=_actor(user),
            question=req.model_dump(exclude={"expected_parent_revision_id"}),
            expected_parent_revision_id=req.expected_parent_revision_id,
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/questions/answer")
async def answer_question(
    session_id: str,
    req: AnswerQuestionRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        return _store().answer_question(
            session_id,
            owner_id=_actor(user),
            answer=req.answer,
            expected_parent_revision_id=req.expected_parent_revision_id,
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/pricing/revisions")
async def save_pricing_revision(
    session_id: str,
    req: PricingRevisionRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        return _store().save_pricing_revision(
            session_id,
            owner_id=_actor(user),
            trace=req.trace,
            requirements=req.requirements,
            expected_parent_revision_id=req.expected_parent_revision_id,
            created_by=req.created_by,
            change_note=req.change_note,
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/requirements")
async def get_requirements(
    session_id: str,
    status: str | None = Query(default=None),
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        requirements = list(session.get("requirements") or [])
        if status:
            requirements = [item for item in requirements if item.get("status") == status]
        return {"session_id": session_id, "requirements": requirements}
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/requirements/{requirement_id}/resolve")
async def resolve_requirement(
    session_id: str,
    requirement_id: str,
    req: RequirementResolutionRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        return _store().resolve_requirement(
            session_id,
            requirement_id,
            owner_id=_actor(user),
            status=req.status,
            resolution=req.resolution,
            expected_parent_revision_id=req.expected_parent_revision_id,
            allow_admin=_allow_admin(user),
        ).as_dict()
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.post("/sessions/{session_id}/finalize")
async def finalize(
    session_id: str,
    req: FinalizeRequest,
    user: RequestUser = Depends(require_user),
):
    try:
        result = _store().finalize(
            session_id,
            owner_id=_actor(user),
            review_note=req.review_note,
            expected_parent_revision_id=req.expected_parent_revision_id,
            allow_admin=_allow_admin(user),
        ).as_dict()
        result["artifact"] = {
            "title": "Финальная ЛСР РИМ",
            "xlsx": f"/api/rim/sessions/{session_id}/export?kind=final",
        }
        return result
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/export")
async def export_lsr(
    session_id: str,
    kind: Literal["draft", "final"] = Query(default="final"),
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        if kind == "final" and session.get("pricing_status") != "priced_final":
            raise RimSessionConflict("final XLSX requires estimate final lock")
        pricing_revision_id = str(session.get("current_pricing_revision_id") or "")
        if not pricing_revision_id:
            raise RimSessionConflict("pricing revision is required for XLSX export")
        pricing = _store().revision_payload(
            session_id,
            pricing_revision_id,
            owner_id=_actor(user),
            allow_admin=_allow_admin(user),
        )["payload"]
        trace = pricing.get("trace") if isinstance(pricing.get("trace"), dict) else {}
        if not trace:
            raise RimSessionConflict("pricing revision has no calculation trace")
        revisions = _store().list_revisions(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        token = (
            session.get("final_lock_revision_id")
            if kind == "final"
            else pricing_revision_id
        )
        target = _session_root(session_id) / "exports" / f"lsr_{kind}_{token}.xlsx"
        if not target.exists():
            render_session_lsr_xlsx(
                trace,
                list(session.get("requirements") or []),
                {"session": session, "revisions": revisions},
                target,
                is_final=(kind == "final"),
            )
        return FileResponse(target, media_type=_XLSX_MEDIA, filename=target.name)
    except Exception as error:  # noqa: BLE001
        _raise_http(error)


@router.get("/sessions/{session_id}/audit")
async def audit(
    session_id: str,
    user: RequestUser = Depends(require_user),
):
    try:
        session = _store().get_session(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        revisions = _store().list_revisions(
            session_id, owner_id=_actor(user), allow_admin=_allow_admin(user)
        )
        return {
            "schema": "rim_session_audit_v1",
            "session": session,
            "revisions": revisions,
        }
    except Exception as error:  # noqa: BLE001
        _raise_http(error)
