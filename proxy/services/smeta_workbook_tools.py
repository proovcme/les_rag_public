"""Estimator file tools: code writes LSR/VOR xlsx, the model only chooses which.

These tools wrap existing application code. They do not invent prices, norms or
quantities, and they do not restore a hidden chat-route intercept.
"""

from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from proxy.services.smeta_chat_application_service import SMETA_ARTIFACT_DIR


LSR_TOOL = "build_lsr_workbook"
VOR_TOOL = "build_vor_workbook"
WORKBOOK_TOOLS = (LSR_TOOL, VOR_TOOL)

SELECTOR_WORKBOOK_RULE = (
    "Если в available_tools есть build_lsr_workbook или build_vor_workbook "
    "и оператор просит готовый xlsx, выбери ровно один файловый инструмент: "
    "ЛСР / локальная смета / расценка → build_lsr_workbook; "
    "ВОР / ведомость объёмов работ без расценки → build_vor_workbook. "
    "Передай attachment_id из payload. Не составляй сметную таблицу текстом "
    "и не выдумывай цены. Эти инструменты запускают код, это не read-only search."
)

ESTIMATOR_SKILL_WORKBOOK_APPENDIX = (
    "\n\n6. Если оператор просит готовый файл ЛСР (xlsx сметы) по вложению PDF/XLSX — "
    "вызови `build_lsr_workbook` с `attachment_id`. Не составляй расценённую таблицу "
    "вручную и не выдумывай цены: файл пишет код существующего document workflow.\n"
    "7. Если оператор просит ВОР / ведомость объёмов работ как xlsx без расценки — "
    "вызови `build_vor_workbook`. Не путай с ЛСР: ВОР — объёмы, ЛСР — расценка кодом."
)


def workbook_file_intent(question: str) -> str | None:
    """Return ``lsr``, ``vor`` or ``None`` for an explicit file request."""

    q = (question or "").casefold().replace("ё", "е")
    wants_vor = bool(
        re.search(r"\bвор\b", q)
        or ("ведомост" in q and "работ" in q)
        or "объем работ" in q
        or "объемов работ" in q
    )
    wants_lsr = (
        "лср" in q
        or "локальн" in q
        or (
            "смет" in q
            and any(token in q for token in ("собери", "сделай", "построй", "xlsx", "excel", "файл"))
        )
    )
    if wants_lsr and not wants_vor:
        return "lsr"
    if wants_vor and not wants_lsr:
        return "vor"
    if wants_lsr and wants_vor:
        return "lsr"
    return None


def maybe_forced_workbook_call(
    *,
    question: str,
    attachment_id: str | None,
    profile_tools: list[str] | tuple[str, ...] | set[str],
    already_called: list[str] | tuple[str, ...] | set[str],
) -> dict[str, Any] | None:
    """If the operator asked for a file and the model skipped the tool, call it once."""

    ident = str(attachment_id or "").strip()
    if not ident:
        return None
    intent = workbook_file_intent(question)
    if intent is None:
        return None
    tool = LSR_TOOL if intent == "lsr" else VOR_TOOL
    allowed = {str(name).strip() for name in profile_tools if str(name).strip()}
    called = {str(name).strip() for name in already_called if str(name).strip()}
    if tool not in allowed or tool in called:
        return None
    return {"tool": tool, "args": {"attachment_id": ident, "question": question}}


def workbook_artifact_from_tool_results(results: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for payload in reversed(list(results or [])):
        if not isinstance(payload, dict):
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        artifact = result.get("artifact")
        if isinstance(artifact, dict) and artifact.get("downloads"):
            return artifact
    return None


def attachment_retry_from_tool_results(results: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for payload in reversed(list(results or [])):
        if not isinstance(payload, dict):
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        retry = result.get("attachment_retry")
        if isinstance(retry, dict) and retry.get("preserved"):
            return retry
    return None


def _result(**kwargs: Any) -> dict[str, Any]:
    from proxy.services.tool_harness_service import _result as harness_result

    return harness_result(**kwargs)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except Exception as error:  # noqa: BLE001 - surface into the tool payload
            box["error"] = error

    thread = threading.Thread(target=worker, name="les-workbook-tool")
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _artifact_dir() -> Path:
    path = Path(SMETA_ARTIFACT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_url(filename: str) -> str:
    return f"/api/smeta-artifacts/download?path={filename}"


def _workbook_missing(tool: str, operation: str, args: dict[str, Any], missing: list[str], trace: str) -> dict[str, Any]:
    return _result(
        tool=tool,
        operation=operation,
        inputs=[args],
        status="missing",
        result={},
        missing=missing,
        trace=trace,
    )


def _lsr_payload_from_outcome(
    *,
    attachment_id: str,
    project_id: int | None,
    outcome: Any,
) -> dict[str, Any]:
    extra = dict(outcome.extra or {})
    artifact = extra.get("artifact") if isinstance(extra.get("artifact"), dict) else {}
    status = "error" if str(outcome.crag or "").upper() == "ERROR" else "ok"
    return _result(
        tool=LSR_TOOL,
        operation=str(outcome.operation or "build_lsr"),
        inputs=[{"attachment_id": attachment_id, "project_id": project_id}],
        status=status,
        result={
            "answer": outcome.answer,
            "crag": outcome.crag,
            "artifact": artifact,
            "attachment_retry": extra.get("attachment_retry") or {},
        },
        warnings=[] if status == "ok" else [str(outcome.answer or "ЛСР не собрана")[:240]],
        trace="priced LSR xlsx built by existing document workflow; model did not supply rows",
    )


async def build_lsr_workbook_async(
    args: dict[str, Any],
    *,
    token_sink: Any | None = None,
) -> dict[str, Any]:
    """Async LSR path so chat SSE can show live row progress."""

    from proxy.services.smeta_chat_application_service import run_smeta_document_application

    attachment_id = str(args.get("attachment_id") or "").strip()
    question = str(args.get("question") or "").strip() or "Собери первичную ЛСР"
    project_raw = args.get("project_id")
    project_id = None
    if project_raw not in (None, ""):
        try:
            project_id = int(project_raw)
        except (TypeError, ValueError):
            project_id = None
    if not attachment_id:
        return _workbook_missing(
            LSR_TOOL,
            "build_lsr",
            args,
            ["attachment_id: прикрепи PDF или XLSX исходник к этому ходу"],
            "LSR workbook needs a server-owned chat attachment",
        )

    outcome = await run_smeta_document_application(
        attachment_id=attachment_id,
        project_id=project_id,
        user_request=question,
        token_sink=token_sink,
    )
    if outcome is None:
        return _workbook_missing(
            LSR_TOOL,
            "build_lsr",
            {"attachment_id": attachment_id},
            ["unsupported attachment type: нужен PDF или XLSX"],
            "document application declined this attachment",
        )
    return _lsr_payload_from_outcome(
        attachment_id=attachment_id,
        project_id=project_id,
        outcome=outcome,
    )


def build_lsr_workbook(args: dict[str, Any]) -> dict[str, Any]:
    """Wrap ``run_smeta_document_application``; the model must not pass prices."""

    return _run_async(build_lsr_workbook_async(args))


def _items_to_bor_xlsx(
    items: list[dict[str, Any]],
    output_path: Path,
    *,
    title: str,
    source_label: str,
) -> int:
    from proxy.services.bor_service import BorLine, bor_to_xlsx, normalize_unit

    lines: list[BorLine] = []
    for item in items:
        name = str(item.get("title") or item.get("name") or "").strip()
        if not name:
            continue
        raw_qty = item.get("quantity")
        if raw_qty is None:
            raw_qty = item.get("qty")
        try:
            qty = float(raw_qty) if raw_qty is not None and str(raw_qty).strip() != "" else None
        except (TypeError, ValueError):
            qty = None
        lines.append(
            BorLine(
                section=str(item.get("section") or "").strip(),
                name=name,
                code=str(item.get("code") or "").strip(),
                mark=str(item.get("mark") or "").strip(),
                unit=normalize_unit(item.get("unit")),
                qty=qty,
                qty_missing_rows=0 if qty is not None else 1,
                source_rows=1,
                sources=[source_label],
            )
        )
    if not lines:
        return 0
    return bor_to_xlsx(lines, output_path, title=title)


def build_vor_workbook(args: dict[str, Any]) -> dict[str, Any]:
    """Build a quantities-only VOR xlsx from the attached spec or bill of works."""

    from proxy.services.chat_attachment_service import resolve_read_attachment
    from proxy.smeta_core.source_intake import intake_vor_document

    attachment_id = str(args.get("attachment_id") or "").strip()
    question = str(args.get("question") or "").strip()
    if not attachment_id:
        return _result(
            tool=VOR_TOOL,
            operation="build_vor",
            inputs=[args],
            status="missing",
            result={},
            missing=["attachment_id: прикрепи спецификацию или ВОР (PDF/XLSX)"],
            trace="VOR workbook needs a server-owned chat attachment",
        )
    try:
        source_path, metadata = resolve_read_attachment(attachment_id)
    except (FileNotFoundError, ValueError, OSError) as error:
        return _result(
            tool=VOR_TOOL,
            operation="build_vor",
            inputs=[{"attachment_id": attachment_id}],
            status="missing",
            result={},
            missing=[f"attachment not readable: {error}"],
            trace="chat attachment missing or expired",
        )

    source_name = str(metadata.get("original_name") or source_path.name)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    xlsx_path = _artifact_dir() / f"VOR_{attachment_id}_{stamp}.xlsx"
    q = question.casefold().replace("ё", "е")
    prefer_spec = "спецификац" in q and source_path.suffix.lower() in {".xlsx", ".xlsm"}
    mode = "intake"
    line_count = 0
    source_rows = 0
    warnings: list[str] = []

    if prefer_spec:
        from proxy.services.spec_to_bor_service import generate_spec_bor_from_rows, rows_from_spec_xlsx

        rows = rows_from_spec_xlsx(source_path, source_label=source_name)
        generated = generate_spec_bor_from_rows(
            rows,
            output_dir=xlsx_path.parent,
            title=f"ВОР из спецификации — {source_name}",
            source_id=attachment_id,
        )
        generated_path = generated.get("xlsx_path")
        if generated_path:
            Path(generated_path).replace(xlsx_path)
        line_count = int(generated.get("bor_lines") or 0)
        source_rows = int(generated.get("source_rows") or 0)
        mode = str(generated.get("mode") or "spec")
    else:
        intake = intake_vor_document(source_path)
        items = list(intake.get("work_items") or [])
        source_rows = len(items)
        if not items and source_path.suffix.lower() in {".xlsx", ".xlsm"}:
            from proxy.services.spec_to_bor_service import generate_spec_bor_from_rows, rows_from_spec_xlsx

            rows = rows_from_spec_xlsx(source_path, source_label=source_name)
            generated = generate_spec_bor_from_rows(
                rows,
                output_dir=xlsx_path.parent,
                title=f"ВОР из спецификации — {source_name}",
                source_id=attachment_id,
            )
            generated_path = generated.get("xlsx_path")
            if generated_path:
                Path(generated_path).replace(xlsx_path)
            line_count = int(generated.get("bor_lines") or 0)
            source_rows = int(generated.get("source_rows") or 0)
            mode = "spec_fallback"
        else:
            line_count = _items_to_bor_xlsx(
                items,
                xlsx_path,
                title=f"Ведомость объёмов работ — {source_name}",
                source_label=source_name,
            )
            mode = "vor_intake"
            issues = intake.get("issues") or []
            if issues:
                warnings.append(f"intake issues: {len(issues)}")

    if line_count <= 0 or not xlsx_path.is_file():
        return _result(
            tool=VOR_TOOL,
            operation="build_vor",
            inputs=[{"attachment_id": attachment_id, "source": source_name}],
            status="missing",
            result={"source_name": source_name, "mode": mode, "source_rows": source_rows},
            missing=["не удалось извлечь видимые строки работ/спецификации без догадок"],
            warnings=warnings,
            trace="VOR parser keeps source facts only; empty intake is not a zero estimate",
        )

    artifact = {
        "mode": "xlsx",
        "stage": "vor",
        "title": f"ВОР — {source_name}",
        "downloads": {"xlsx": _download_url(xlsx_path.name)},
        "files": {"xlsx_path": str(xlsx_path)},
    }
    return _result(
        tool=VOR_TOOL,
        operation="build_vor",
        inputs=[{"attachment_id": attachment_id, "source": source_name}],
        status="ok",
        result={
            "answer": (
                f"ВОР собрана кодом: {line_count} строк из {source_rows} исходных "
                f"позиций файла «{source_name}». Количества только из исходника, без цен."
            ),
            "mode": mode,
            "source_rows": source_rows,
            "bor_lines": line_count,
            "artifact": artifact,
        },
        warnings=warnings,
        trace="quantities-only VOR xlsx; no GESN mapping and no prices",
    )
