"""One persistent conversational turn for a RIM estimate session.

The model owns scope, questions and draft professional choices.  This service
only supplies state-scoped tools, validates their transport and persists the
result as immutable session revisions.
"""

from __future__ import annotations

import json
from typing import Any, Callable
from uuid import uuid4

from proxy.services.prompt_registry_service import smeta_native_skill_prompt
from proxy.services.rim_agent_action_service import model_tool_specs, validate_model_action
from proxy.services.rim_knowledge_service import model_reference_for_session
from proxy.smeta_core.document_workflow import _run_batch_norm_agent
from proxy.smeta_core.rim_session import RimSessionConflict, RimSessionStore


Exchange = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]
MappingExchange = Callable[[list[dict[str, Any]], dict[str, Any]], dict[str, Any]]
_INTAKE_WORK_ITEM_BATCH_SIZE = 5
_NORM_MAPPING_CHECKPOINT = "norm_mapping"
_IMMUTABLE_PROJECT_SOURCE_FIELDS = (
    "source_ref",
    "source_refs",
    "source_row",
)


def _arguments(tool_call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    name = str(function.get("name") or "")
    raw = function.get("arguments")
    if isinstance(raw, dict):
        return name, raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Qwen returned invalid arguments for {name}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"Qwen arguments for {name} must be an object")
    return name, parsed


def _single_action(
    *,
    session: dict[str, Any],
    context: dict[str, Any],
    user_message: str,
    exchange: Exchange,
    only_actions: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    session_fact_fields = (
        "normative_base_version",
        "pricebook_id",
        "region_code",
        "price_period",
    )
    confirmed_session_facts = {
        field: str(session.get(field) or "")
        for field in session_fact_fields
        if str(session.get(field) or "").strip()
    }
    tools = model_tool_specs(session)
    if only_actions is not None:
        tools = [
            tool
            for tool in tools
            if str((tool.get("function") or {}).get("name") or "") in only_actions
        ]
    system_message = {
        "role": "system",
        "content": (
            smeta_native_skill_prompt()
            + "\n\nRIM DIALOG CONTRACT: use only the supplied state-scoped tools. "
            "The server owns session identity and state. Ask one highest-value question. "
            "Before pricing, a question may request only an observable installation fact or a "
            "concrete fact stated in project documents, including region or period. Technical "
            "parts, norm catalog scope and search strategy belong to evidence tools. Never ask "
            "for a blanket coefficient. Do not invent a norm, price, coefficient or calculation."
            " Every non-empty value in confirmed_session_facts is server-confirmed: use it and "
            "never ask the user to repeat it."
        ),
    }
    request_payload: dict[str, Any] = {
        "user_message": str(user_message or ""),
        "session_context": {
            **context,
            "confirmed_session_facts": confirmed_session_facts,
            "rim_reference": model_reference_for_session(session),
        },
        "required_result": "Call exactly one supplied tool. Ordinary prose is not an action.",
    }
    last_error: ValueError | None = None
    for attempt in range(2):
        message = exchange(
            [
                system_message,
                {
                    "role": "user",
                    "content": json.dumps(
                        request_payload,
                        ensure_ascii=False,
                        default=str,
                    ),
                },
            ],
            tools,
        )
        try:
            calls = list(message.get("tool_calls") or [])
            if len(calls) != 1:
                raise ValueError("Qwen must return exactly one state-scoped tool call")
            action, arguments = _arguments(calls[0])
            intent = (
                str(message.get("content") or "").strip()
                or f"Выполняю действие {action}."
            )
            validated = validate_model_action(
                session,
                {
                    "action": action,
                    "arguments": arguments,
                    "user_visible_intent": intent,
                },
            )
            return validated, message
        except ValueError as error:
            last_error = error
            if attempt:
                raise
            request_payload = {
                **request_payload,
                "rejected_tool_call": {
                    "error": str(error),
                    "required_correction": (
                        "Return one corrected call using the supplied JSON schema. "
                        "Do not explain the error in prose and do not change the professional "
                        "decision merely to satisfy validation."
                    ),
                },
            }
    raise last_error or ValueError("Qwen did not return a valid action")


def _current_payload(
    store: RimSessionStore,
    session: dict[str, Any],
    revision_id: str,
    *,
    owner_id: str,
    allow_admin: bool,
) -> dict[str, Any]:
    if not revision_id:
        return {}
    return store.revision_payload(
        session["session_id"],
        revision_id,
        owner_id=owner_id,
        allow_admin=allow_admin,
    )["payload"]


def _work_rows(vor_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "work_id": str(row.get("work_id") or ""),
            "title": str(row.get("work_name") or row.get("title") or ""),
            "unit": str(row.get("unit") or ""),
            "quantity": row.get("quantity"),
            "section": str(row.get("section_name") or row.get("section") or ""),
            "note": str(row.get("note") or ""),
            "source_row": row.get("source_row"),
            "source_refs": list(
                row.get("source_refs")
                or ([row.get("source_ref")] if row.get("source_ref") else [])
            ),
        }
        for row in vor_rows[:30]
    ]


def _preserve_project_source_provenance(
    previous_rows: list[dict[str, Any]],
    revised_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep model revisions bound to the immutable uploaded source rows.

    Qwen owns the revised work wording and may add a quantity derivation, but it
    does not own the identity or provenance of the project row. Normative
    evidence is stored later on mapping rows and must never replace source_ref.
    """
    previous_by_id = {
        str(row.get("work_id") or ""): row
        for row in previous_rows
        if str(row.get("work_id") or "")
    }
    previous_by_ref: dict[str, dict[str, Any]] = {}
    for row in previous_rows:
        refs = list(row.get("source_refs") or [])
        if row.get("source_ref"):
            refs.insert(0, row["source_ref"])
        for ref in refs:
            normalized = str(ref or "").strip()
            if normalized:
                previous_by_ref[normalized] = row
    preserved: list[dict[str, Any]] = []
    for row in revised_rows:
        work_id = str(row.get("work_id") or "")
        bound = dict(row)
        source = previous_by_id.get(work_id)
        if source is not None:
            for field in _IMMUTABLE_PROJECT_SOURCE_FIELDS:
                value = source.get(field)
                if field == "source_refs":
                    value = list(
                        value
                        or (
                            [source.get("source_ref")]
                            if source.get("source_ref")
                            else []
                        )
                    )
                bound[field] = value
        else:
            refs = [
                str(ref or "").strip()
                for ref in (
                    list(row.get("source_refs") or [])
                    or ([row.get("source_ref")] if row.get("source_ref") else [])
                )
                if str(ref or "").strip()
            ]
            if not refs or any(ref not in previous_by_ref for ref in refs):
                raise RimSessionConflict(
                    "new derived VOR work must cite only project source refs "
                    "from the parent revision"
                )
            source_rows = {
                previous_by_ref[ref].get("source_row")
                for ref in refs
                if previous_by_ref[ref].get("source_row") is not None
            }
            bound["source_ref"] = refs[0]
            bound["source_refs"] = refs
            bound["source_row"] = (
                next(iter(source_rows)) if len(source_rows) == 1 else None
            )
        preserved.append(bound)
    return preserved


def _mapping_rows(
    work_rows: list[dict[str, Any]],
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    by_work = {str(row.get("work_id") or ""): row for row in work_rows}
    opened = {
        str(work_id): {
            str(card.get("norm_code") or ""): card
            for card in cards or []
            if isinstance(card, dict)
        }
        for work_id, cards in (result.get("opened_cards") or {}).items()
    }
    candidates: dict[str, dict[str, dict[str, Any]]] = {}
    for work_id, payloads in (result.get("browse_trace") or {}).items():
        bucket = candidates.setdefault(str(work_id), {})
        for payload in payloads or []:
            for card in (payload or {}).get("candidates") or []:
                if isinstance(card, dict) and str(card.get("norm_code") or ""):
                    bucket[str(card["norm_code"])] = card

    rows: list[dict[str, Any]] = []
    for work_id, selection in (result.get("selections") or {}).items():
        work = by_work.get(str(work_id), {})
        norm_code = str(selection.get("norm_code") or "")
        covered_by = str(selection.get("covered_by_work_id") or "")
        reason = str(selection.get("reason") or selection.get("coverage_reason") or "")
        source_refs = list(work.get("source_refs") or [])
        if not norm_code:
            rows.append(
                {
                    "schema": "rim_mapping_row_v1",
                    "mapping_row_id": uuid4().hex,
                    "work_id": str(work_id),
                    "norm_key": "",
                    "norm_code": "",
                    "norm_title": "",
                    "norm_unit": "",
                    "norm_quantity": None,
                    "candidate_rank": 1,
                    "selection_status": "selected" if covered_by else "conflict",
                    "selection_kind": "covered_by" if covered_by else "unbound",
                    "covered_by_work_id": covered_by,
                    "is_analog": False,
                    "reason": reason,
                    "source_refs": source_refs,
                    "edited_by": "model",
                    "card_opened": False,
                    "unbound_evidence": dict(selection.get("unbound_evidence") or {}),
                }
            )
            continue
        candidate_bucket = candidates.setdefault(str(work_id), {})
        candidate_bucket.setdefault(norm_code, opened.get(str(work_id), {}).get(norm_code, {}))
        ordered_codes = [norm_code, *sorted(code for code in candidate_bucket if code != norm_code)]
        for rank, code in enumerate(ordered_codes, 1):
            card = opened.get(str(work_id), {}).get(code) or candidate_bucket.get(code) or {}
            selected = code == norm_code
            selection_kind = str(selection.get("selection_kind") or "exact")
            rows.append(
                {
                    "schema": "rim_mapping_row_v1",
                    "mapping_row_id": uuid4().hex,
                    "work_id": str(work_id),
                    "norm_key": str(card.get("norm_key") or ""),
                    "norm_code": code,
                    "norm_title": str(card.get("title") or ""),
                    "norm_unit": str(card.get("measure_unit") or ""),
                    "norm_quantity": None,
                    "candidate_rank": rank,
                    "selection_status": "selected" if selected else "candidate",
                    "selection_kind": (
                        "analog" if selected and selection_kind == "analog" else "direct"
                    ),
                    "is_analog": bool(selected and selection_kind == "analog"),
                    "reason": reason if selected else "",
                    "source_refs": source_refs,
                    "norm_source_ref": str(card.get("source_ref") or ""),
                    "normative_base_version": str(card.get("edition") or ""),
                    "questions_to_ask": list(card.get("questions_to_ask") or [])[:8],
                    "edited_by": "model",
                    "card_opened": bool(code in opened.get(str(work_id), {})),
                    "applicability": (
                        str(selection.get("applicability") or "") if selected else ""
                    ),
                    "analog_limitations": (
                        list(selection.get("analog_limitations") or []) if selected else []
                    ),
                    "technology_check": (
                        dict(selection.get("technology_check") or {}) if selected else {}
                    ),
                    "resource_bindings": (
                        list(selection.get("resource_bindings") or []) if selected else []
                    ),
                    "nr_sp_rule_id": (
                        str(selection.get("nr_sp_rule_id") or "") if selected else ""
                    ),
                }
            )
    return rows


def _question_hints(mapping_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints = []
    for row in mapping_rows:
        if str(row.get("selection_status") or "") != "selected":
            continue
        for question in row.get("questions_to_ask") or []:
            text = str(question or "").strip()
            if text and not any(item["text"] == text for item in hints):
                hints.append(
                    {
                        "text": text,
                        "work_ids": [str(row.get("work_id") or "")],
                        "norm_code": str(row.get("norm_code") or ""),
                    }
                )
    return hints[:15]


def run_rim_agent_turn(
    store: RimSessionStore,
    session_id: str,
    *,
    owner_id: str,
    user_message: str,
    exchange: Exchange,
    mapping_exchange: MappingExchange,
    allow_admin: bool = False,
) -> dict[str, Any]:
    """Run one user-visible turn; long norm research remains one bounded tool loop."""
    session = store.get_session(
        session_id, owner_id=owner_id, allow_admin=allow_admin
    )
    if session.get("pending_question_id"):
        pending_question = dict(session.get("pending_question") or {})
        action, model_message = _single_action(
            session=session,
            context={
                "pending_question": pending_question,
                "instruction": "Interpret the user message only as this pending answer.",
            },
            user_message=user_message,
            exchange=exchange,
        )
        if action["action"] != "interpret_pending_answer":
            raise RimSessionConflict("pending question must be answered in place")
        result = store.answer_question(
            session_id,
            owner_id=owner_id,
            answer=dict(action["arguments"].get("answer") or {}),
            expected_parent_revision_id=session["head_revision_id"],
            allow_admin=allow_admin,
        )
        if (
            str(session.get("phase") or "") == "vor"
            and str(session.get("mapping_status") or "") == "not_started"
            and not any(
                str((action["arguments"].get("answer") or {}).get(field) or "").strip()
                for field in ("region_code", "price_period")
            )
        ):
            vor = _current_payload(
                store,
                session,
                str(session.get("current_vor_revision_id") or ""),
                owner_id=owner_id,
                allow_admin=allow_admin,
            )
            draft_action, draft_message = _single_action(
                session=result.session,
                context={
                    "answered_question": pending_question,
                    "answer": dict(action["arguments"].get("answer") or {}),
                    "current_vor_draft": {
                        "rows": list(vor.get("rows") or [])[:_INTAKE_WORK_ITEM_BATCH_SIZE],
                    },
                    "instruction": (
                        "Revise the VOR draft using the confirmed answer. The rows must now name "
                        "technological work operations, not repeat equipment supply descriptions. "
                        "Preserve source quantities, units and source_ref unless the answer gives "
                        "an explicit derivation. Do not select or discuss norms in this action."
                    ),
                },
                user_message=user_message,
                exchange=exchange,
                only_actions={"draft_work_schedule"},
            )
            revised_rows = list(draft_action["arguments"].get("rows") or [])
            if not revised_rows:
                raise RimSessionConflict(
                    "Qwen returned an empty VOR revision after the answered question; "
                    "the previous source-linked revision remains current"
                )
            revised = store.save_vor_revision(
                session_id,
                owner_id=owner_id,
                rows=_preserve_project_source_provenance(
                    list(vor.get("rows") or []),
                    revised_rows,
                ),
                expected_parent_revision_id=result.revision_id,
                created_by="model",
                change_note="Уточнение черновика ВОР по ответу пользователя",
                allow_admin=allow_admin,
            )
            return {
                **revised.as_dict(),
                "answer_revision_id": result.revision_id,
                "vor_revision_id": revised.revision_id,
                "agent_action": action,
                "draft_action": draft_action,
                "model": (
                    draft_message.get("_les_model")
                    or model_message.get("_les_model")
                    or ""
                ),
                "message": (
                    "Ответ сохранён; Qwen обновил пять строк ВОР как монтажные "
                    "операции. Следующий шаг — подбор норм."
                ),
            }
        return {
            **result.as_dict(),
            "agent_action": action,
            "model": model_message.get("_les_model") or "",
            "message": "Ответ сохранён в текущем контексте сессии.",
        }

    if session.get("phase") == "intake":
        intake_revision = _current_payload(
            store,
            session,
            str(session.get("head_revision_id") or ""),
            owner_id=owner_id,
            allow_admin=allow_admin,
        )
        intake = (
            dict(intake_revision.get("intake") or {})
            if isinstance(intake_revision.get("intake"), dict)
            else dict(intake_revision)
        )
        declared_source_kind = str(
            intake_revision.get("source_kind")
            or intake.get("source_kind")
            or "auto"
        )
        work_items = list(intake.get("work_items") or [])
        visible_work_items = work_items[:_INTAKE_WORK_ITEM_BATCH_SIZE]
        intake_actions = (
            {"draft_work_schedule"}
            if declared_source_kind == "specification"
            else None
        )
        action, model_message = _single_action(
            session=session,
            context={
                "intake": {
                    "source_kind": declared_source_kind,
                    "work_item_count": len(work_items),
                    "work_items": visible_work_items,
                    "remaining_work_item_count": max(
                        0, len(work_items) - len(visible_work_items)
                    ),
                    "issues": list(intake.get("issues") or [])[:20],
                },
                "instruction": (
                    "The workbook was already inspected by code. Do not request inspect_file. "
                    "Every uploaded source row is in scope by default. Never ask whether to include "
                    "all rows, whether to process the remaining rows later, or whether exact versus "
                    "analog norms should be preferred: norm-search strategy belongs to the model. "
                    "For a specification, the first required action is a source-linked VOR draft "
                    "for the visible items. Preserve unresolved technical facts in row notes or "
                    "assumptions; the harness will request one question only after saving the draft. "
                    "This is not norm mapping: do not mark rows unbound, claim a norm was not found, "
                    "or propose search families. Use only actual source work_ids."
                ),
            },
            user_message=user_message,
            exchange=exchange,
            only_actions=intake_actions,
        )
        if action["action"] == "ask_user":
            result = store.open_question(
                session_id,
                owner_id=owner_id,
                question=action["arguments"],
                expected_parent_revision_id=session["head_revision_id"],
                allow_admin=allow_admin,
            )
            return {
                **result.as_dict(),
                "agent_action": action,
                "model": model_message.get("_les_model") or "",
                "message": action["arguments"]["text"],
            }
        if action["action"] != "draft_work_schedule":
            return {
                "session_id": session_id,
                "status": session["display_state"],
                "agent_action": action,
                "message": action["user_visible_intent"],
            }
        result = store.save_vor_revision(
            session_id,
            owner_id=owner_id,
            rows=list(action["arguments"].get("rows") or []),
            expected_parent_revision_id=session["head_revision_id"],
            created_by="model",
            change_note="Черновик ВОР из спецификации",
            allow_admin=allow_admin,
        )
        question_action, question_message = _single_action(
            session=result.session,
            context={
                "vor_draft": {
                    "row_count": len(action["arguments"].get("rows") or []),
                    "rows": list(action["arguments"].get("rows") or [])[:30],
                    "source_work_item_count": len(work_items),
                },
                "instruction": (
                    "Ask one highest-value unresolved question for this VOR draft. "
                    "State the known fact, why it affects the work or norm, give practical "
                    "answer options and keep the question bound to the relevant work_ids. "
                    "Ask only for a missing physical installation condition or a concrete project "
                    "fact such as region or period. "
                    "Do not ask the user to prioritize norm searches, choose collections, "
                    "a technical part, approve unbound rows, approve a blanket coefficient "
                    "or decide the model's retrieval strategy. Set question_kind to "
                    "physical_installation or project_condition."
                ),
            },
            user_message=user_message,
            exchange=exchange,
            only_actions={"ask_user"},
        )
        question_revision = store.open_question(
            session_id,
            owner_id=owner_id,
            question=question_action["arguments"],
            expected_parent_revision_id=result.revision_id,
            allow_admin=allow_admin,
        )
        return {
            **question_revision.as_dict(),
            "vor_revision_id": result.revision_id,
            "agent_action": action,
            "question_action": question_action,
            "model": (
                question_message.get("_les_model")
                or model_message.get("_les_model")
                or ""
            ),
            "message": question_action["arguments"]["text"],
        }

    if session.get("phase") == "vor" and session.get("mapping_status") == "not_started":
        vor_revision_id = str(session.get("current_vor_revision_id") or "")
        vor = _current_payload(
            store,
            session,
            vor_revision_id,
            owner_id=owner_id,
            allow_admin=allow_admin,
        )
        work_rows = _work_rows(list(vor.get("rows") or []))
        if not work_rows:
            raise RimSessionConflict("VOR has no rows for norm mapping")
        stored_checkpoint = store.load_agent_checkpoint(
            session_id,
            owner_id=owner_id,
            checkpoint_kind=_NORM_MAPPING_CHECKPOINT,
            base_revision_id=vor_revision_id,
            allow_admin=allow_admin,
        )

        def save_mapping_checkpoint(payload: dict[str, Any]) -> None:
            store.save_agent_checkpoint(
                session_id,
                owner_id=owner_id,
                checkpoint_kind=_NORM_MAPPING_CHECKPOINT,
                base_revision_id=vor_revision_id,
                payload=payload,
                allow_admin=allow_admin,
            )

        result = _run_batch_norm_agent(
            work_rows,
            exchange,
            mapping_exchange=mapping_exchange,
            # One five-row RIM navigation batch must stay digestible for the
            # local 9B model. Qwen still selects candidates and may request a
            # later page; code only bounds the current payload.
            candidate_limit=4,
            max_turns=64,
            user_request=user_message,
            checkpoint=save_mapping_checkpoint,
            resume_checkpoint=(
                dict(stored_checkpoint.get("payload") or {})
                if stored_checkpoint
                else None
            ),
            require_scoped_search=True,
        )
        mapping_rows = _mapping_rows(work_rows, result)
        revision = store.save_mapping_revision(
            session_id,
            owner_id=owner_id,
            mapping_rows=mapping_rows,
            expected_parent_revision_id=session["head_revision_id"],
            created_by="model",
            change_note="Qwen batch mapping: catalog → scoped search → typed read",
            allow_admin=allow_admin,
        )
        store.clear_agent_checkpoint(
            session_id,
            owner_id=owner_id,
            checkpoint_kind=_NORM_MAPPING_CHECKPOINT,
            allow_admin=allow_admin,
        )
        current = revision.session
        hints = _question_hints(mapping_rows)
        question_action: dict[str, Any] | None = None
        if hints:
            question_action, _message = _single_action(
                session=current,
                context={
                    "mapping_summary": {
                        "rows": len(mapping_rows),
                        "selected": sum(
                            row.get("selection_status") == "selected"
                            for row in mapping_rows
                        ),
                    },
                    "navigation_questions_to_ask": hints,
                    "instruction": (
                        "Choose one highest-value unresolved navigation hint and turn it "
                        "into a human question with fact, reason, options and consequences. "
                        "Ask for the missing physical/project fact, not for a technical part "
                        "or coefficient choice. Set question_kind to physical_installation "
                        "or project_condition."
                    ),
                },
                user_message=user_message,
                exchange=exchange,
                only_actions={"ask_user"},
            )
            if question_action["action"] == "ask_user":
                question_revision = store.open_question(
                    session_id,
                    owner_id=owner_id,
                    question=question_action["arguments"],
                    expected_parent_revision_id=revision.revision_id,
                    allow_admin=allow_admin,
                )
                return {
                    **question_revision.as_dict(),
                    "mapping_revision_id": revision.revision_id,
                    "agent_action": question_action,
                    "message": question_action["arguments"]["text"],
                    "agent_trace": result.get("agent_trace") or {},
                    "resumed_from_checkpoint": bool(stored_checkpoint),
                }
        return {
            **revision.as_dict(),
            "mapping_revision_id": revision.revision_id,
            "agent_action": question_action,
            "message": (
                "Кандидаты и модельный черновик mapping сохранены. "
                "Для расчёта нужна пользовательская проверка и global review."
            ),
            "agent_trace": result.get("agent_trace") or {},
            "resumed_from_checkpoint": bool(stored_checkpoint),
        }

    return {
        "session_id": session_id,
        "status": session["display_state"],
        "revision_id": session["head_revision_id"],
        "parent_revision_id": "",
        "issues": session.get("issues") or [],
        "requirements": session.get("requirements") or [],
        "message": (
            "Текущий шаг требует пользовательского решения в рабочей таблице "
            "или запуска детерминированного действия."
        ),
    }
