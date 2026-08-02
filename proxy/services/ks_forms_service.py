"""КС-2 / КС-3 / КС-6а: детерминированное заполнение бланков из ЛСР или журнала.

Числа считает код (ADR-11). Код не выбирает нормы: КС-2/КС-3 переносят уже
принятое модельное решение ЛСР; КС-6а строится только из confirmed field_intake.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KS2_KS3_FORMS = frozenset({"ks2", "ks3"})
KS6A_FORM = "ks6a"
FILLED_KS_FORMS = frozenset({"ks2", "ks3", "ks6a"})

_SOURCE_LAST_LSR = "last_lsr"
_SOURCE_FIELD_JOURNAL = "field_journal"
_SOURCE_BLANK = "blank"


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _fmt_qty(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _fmt_money(value: float) -> str:
    return f"{value:.2f}"


def assembled_from_rim_form(rim: dict[str, Any] | None) -> dict[str, Any]:
    """rim_lsr_form / lsr_form → shape les_lsr_assemble (positions + summary)."""
    if not isinstance(rim, dict):
        return {"positions": [], "summary": {"positions": 0, "total": 0.0}}
    positions: list[dict[str, Any]] = []
    for row in rim.get("rows") or []:
        if not isinstance(row, dict):
            continue
        qty = _f(row.get("quantity") if row.get("quantity") is not None else row.get("qty"))
        amount = _f(row.get("amount") if row.get("amount") is not None else row.get("total"))
        name = str(row.get("title") or row.get("name") or "").strip()
        code = str(row.get("basis") or row.get("code") or row.get("norm_code") or "").strip()
        if not name and not code and qty == 0 and amount == 0:
            continue
        positions.append({
            "code": code,
            "name": name or code or "—",
            "unit": str(row.get("unit") or "").strip(),
            "qty": qty,
            "total": amount,
        })
    total = _f(rim.get("amount_total"))
    if total <= 0:
        total = sum(_f(p.get("total")) for p in positions)
    return {
        "positions": positions,
        "summary": {"positions": len(positions), "total": total},
        "source": "rim_lsr_form",
    }


def _position_from_rim_trace_entry(pos: dict[str, Any]) -> dict[str, Any] | None:
    """One RIM position (document/chat LSR) → assemble row."""
    if not isinstance(pos, dict):
        return None
    code = str(pos.get("code") or pos.get("norm_code") or "").strip()
    name = str(pos.get("name") or pos.get("title") or "").strip()
    unit = str(pos.get("unit") or "").strip()
    qty = _f(pos.get("qty") if pos.get("qty") is not None else pos.get("quantity"))
    summary = pos.get("summary") if isinstance(pos.get("summary"), dict) else {}
    total = _f(summary.get("total") if summary else pos.get("total"))
    if not name and not code:
        for row in pos.get("rows") or []:
            if not isinstance(row, dict) or str(row.get("type") or "") != "work":
                continue
            cols = row.get("columns") if isinstance(row.get("columns"), dict) else {}
            code = str(cols.get(2) or code).strip()
            name = str(cols.get(3) or name).strip()
            unit = str(cols.get(4) or unit).strip()
            qty = _f(cols.get(5) if cols.get(5) is not None else qty)
            break
    if not name and not code:
        return None
    return {
        "code": code,
        "name": name or code or "—",
        "unit": unit,
        "qty": qty,
        "total": total,
    }


def assembled_from_rim_trace(trace: dict[str, Any] | None) -> dict[str, Any]:
    """Document/chat rim_trace (sections[].positions[] or flat positions) → assemble shape."""
    if not isinstance(trace, dict):
        return {"positions": [], "summary": {"positions": 0, "total": 0.0}}
    positions: list[dict[str, Any]] = []
    for section in trace.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for pos in section.get("positions") or []:
            row = _position_from_rim_trace_entry(pos if isinstance(pos, dict) else {})
            if row:
                positions.append(row)
    if not positions:
        for pos in trace.get("positions") or []:
            row = _position_from_rim_trace_entry(pos if isinstance(pos, dict) else {})
            if row:
                positions.append(row)
    summary = trace.get("summary") if isinstance(trace.get("summary"), dict) else {}
    total = _f(
        summary.get("total_with_vat")
        or summary.get("total_without_vat")
        or summary.get("total")
        or summary.get("known_amount")
        or summary.get("full_amount")
    )
    if total <= 0:
        total = sum(_f(p.get("total")) for p in positions)
    return {
        "positions": positions,
        "summary": {"positions": len(positions), "total": total},
        "source": "rim_trace",
    }


def assembled_from_artifact(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract assemble-shaped payload from a stored smeta chat artifact or report."""
    if not isinstance(artifact, dict):
        return None
    rim = artifact.get("rim_lsr_form")
    if not isinstance(rim, dict):
        rim = artifact.get("lsr_form")
    if isinstance(rim, dict) and (rim.get("rows") or rim.get("amount_total") is not None):
        assembled = assembled_from_rim_form(rim)
        if assembled["positions"]:
            return assembled
    positions = artifact.get("positions")
    if isinstance(positions, list) and positions:
        usable = [p for p in positions if isinstance(p, dict) and (
            p.get("name") or p.get("code") or p.get("title") or p.get("total") is not None
        )]
        if usable and any(
            p.get("name") or p.get("code") or p.get("title") or _f(p.get("total"))
            for p in usable
        ):
            summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
            total = _f(summary.get("total") or summary.get("total_with_vat") or summary.get("total_without_vat"))
            if total <= 0:
                total = sum(_f(p.get("total")) for p in usable)
            # Thin workflow stubs ({work_id, selected_by}) are not assemble rows.
            if any(p.get("name") or p.get("code") or p.get("title") for p in usable):
                return {
                    "positions": usable,
                    "summary": {"positions": len(usable), "total": total},
                    "source": "artifact_positions",
                }
    for key in ("rim_trace", "lsr"):
        trace = artifact.get(key)
        if isinstance(trace, dict):
            assembled = assembled_from_rim_trace(trace)
            if assembled["positions"]:
                return assembled
    return None


def ks2_rows(assembled: dict[str, Any]) -> list[list[str]]:
    """КС-2 official columns (HTML/Goskomstat): № | № сметы | Наименование | Расценка | Ед. | Кол-во | Цена | Стоимость."""
    rows: list[list[str]] = []
    for i, pos in enumerate(assembled.get("positions") or [], 1):
        if not isinstance(pos, dict):
            continue
        qty = _f(pos.get("qty"))
        total = _f(pos.get("total"))
        unit_price = (total / qty) if qty else 0.0
        smeta_pos = str(pos.get("smeta_pos") or pos.get("position_no") or i)
        rows.append([
            str(i),
            smeta_pos,
            str(pos.get("name") or pos.get("code") or "—"),
            str(pos.get("code") or ""),
            str(pos.get("unit") or ""),
            _fmt_qty(qty),
            _fmt_money(unit_price) if unit_price else "",
            _fmt_money(total) if total else "",
        ])
    grand = _f((assembled.get("summary") or {}).get("total"))
    if rows:
        rows.append(["", "", "Итого", "", "", "", "", _fmt_money(grand)])
    return rows


def ks3_rows(assembled: dict[str, Any]) -> list[list[str]]:
    """Draft KS-3: only the current-period amount is known from one LSR.

    Cumulative columns stay empty until project-period history exists; copying
    the same total into all three official columns would assert false facts.
    """
    grand = _f((assembled.get("summary") or {}).get("total"))
    if grand <= 0 and assembled.get("positions"):
        grand = sum(_f(p.get("total")) for p in assembled["positions"] if isinstance(p, dict))
    money = _fmt_money(grand)
    return [[
        "1",
        "Выполненные работы и затраты по локальной смете (перенос из ЛСР за отчётный период)",
        "",
        "",
        money,
    ]]


def ks6a_rows(entries: list[dict[str, Any]]) -> list[list[str]]:
    """КС-6а: № | Дата | Наименование | Ед. | Объём за период | Нарастающий итог."""
    ordered = sorted(
        (e for e in entries if isinstance(e, dict)),
        key=lambda e: (str(e.get("entry_date") or ""), int(e.get("id") or 0)),
    )
    cumulative: dict[tuple[str, str], float] = {}
    rows: list[list[str]] = []
    for i, entry in enumerate(ordered, 1):
        position = str(entry.get("position") or "").strip() or "—"
        unit = str(entry.get("unit") or "").strip()
        volume = _f(entry.get("volume"))
        key = (position.casefold(), unit.casefold())
        cumulative[key] = cumulative.get(key, 0.0) + volume
        rows.append([
            str(i),
            str(entry.get("entry_date") or ""),
            position,
            unit,
            _fmt_qty(volume),
            _fmt_qty(cumulative[key]),
        ])
    return rows


def rows_for_form(
    form_id: str,
    *,
    assembled: dict[str, Any] | None = None,
    journal_entries: list[dict[str, Any]] | None = None,
) -> list[list[str]]:
    fid = str(form_id or "").strip().casefold()
    if fid == "ks2":
        if not assembled or not assembled.get("positions"):
            raise ValueError("Для КС-2 нужна последняя ЛСР с позициями")
        return ks2_rows(assembled)
    if fid == "ks3":
        if not assembled or not (
            assembled.get("positions") or _f((assembled.get("summary") or {}).get("total"))
        ):
            raise ValueError("Для КС-3 нужна последняя ЛСР с итогом")
        return ks3_rows(assembled)
    if fid == "ks6a":
        entries = list(journal_entries or [])
        if not entries:
            raise ValueError(
                "Для КС-6а нужны confirmed записи журнала полевых объёмов "
                "(ЛСР как факт выполнения не подставляется)"
            )
        return ks6a_rows(entries)
    raise ValueError(f"form_id для заполнения КС: {sorted(FILLED_KS_FORMS)}")


def load_last_assembled_from_session(session_id: str) -> dict[str, Any] | None:
    """Latest chat_history artifact with rim/positions for this session."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    from backend.rag_config import rag_meta_db_path

    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            rows = conn.execute(
                "SELECT artifact_json FROM chat_history "
                "WHERE session_id=? AND artifact_json IS NOT NULL AND artifact_json != '' "
                "AND artifact_json != '{}' "
                "ORDER BY id DESC LIMIT 40",
                (sid,),
            ).fetchall()
    except Exception as exc:
        logger.warning("[KS_FORMS] session artifact lookup failed: %s", exc)
        return None
    for (blob,) in rows:
        try:
            artifact = json.loads(blob or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        assembled = assembled_from_artifact(artifact if isinstance(artifact, dict) else None)
        if assembled and assembled.get("positions"):
            return assembled
    return None


def load_latest_assembled_from_disk(
    artifact_dir: str | Path = "storage/smeta_artifacts",
) -> dict[str, Any] | None:
    """Fallback: newest *.json sidecar next to smeta XLSX exports."""
    root = Path(artifact_dir)
    if not root.is_dir():
        return None
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        assembled = assembled_from_artifact(payload if isinstance(payload, dict) else None)
        if assembled and assembled.get("positions"):
            return assembled
    return None


def resolve_assembled(
    *,
    assembled: dict[str, Any] | None = None,
    rim_form: dict[str, Any] | None = None,
    session_id: str = "",
    project_id: int | None = None,
) -> dict[str, Any] | None:
    """Resolve only explicit or session-scoped LSR data.

    The PR prototype fell back to the newest artifact in a shared directory.
    That could silently build a KS document from another project, so production
    resolution deliberately has no global disk fallback.
    """
    if project_id is None:
        raise ValueError("Для заполненной формы КС требуется project_id")
    if isinstance(assembled, dict) and assembled.get("positions"):
        return assembled
    if isinstance(rim_form, dict):
        from_rim = assembled_from_rim_form(rim_form)
        if from_rim["positions"]:
            return from_rim
    if session_id:
        return load_last_assembled_from_session(session_id)
    return None


def load_confirmed_journal(*, project_id: int | None = None) -> list[dict[str, Any]]:
    from proxy.services import field_intake_service as fis

    if project_id is None:
        raise ValueError("Для КС-6а требуется project_id; общий журнал не используется")
    return fis.list_entries(
        status="confirmed",
        project_id=int(project_id),
        limit=10000,
    )


def build_ks_document(
    form_id: str,
    *,
    fmt: str = "xlsx",
    project_id: int | None = None,
    manual: dict[str, Any] | None = None,
    assembled: dict[str, Any] | None = None,
    rim_form: dict[str, Any] | None = None,
    session_id: str = "",
    journal_entries: list[dict[str, Any]] | None = None,
    source: str = "",
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Fill KS form and render via forms_service. Returns path + meta."""
    from proxy.services import forms_service

    fid = str(form_id or "").strip().casefold()
    if fid not in FILLED_KS_FORMS:
        raise ValueError(f"form_id: {sorted(FILLED_KS_FORMS)}")
    if fmt not in ("xlsx", "docx", "html"):
        raise ValueError("fmt: xlsx|docx|html")
    if project_id is None:
        raise ValueError("Для заполненной формы КС требуется project_id")

    src = (source or "").strip().casefold() or (
        _SOURCE_FIELD_JOURNAL if fid == KS6A_FORM else _SOURCE_LAST_LSR
    )
    manual = dict(manual or {})
    if fid in KS2_KS3_FORMS:
        if src == _SOURCE_BLANK:
            return forms_service.generate(
                fid, fmt, project_id=project_id, manual=manual, out_path=out_path,
            )
        resolved_assembled = resolve_assembled(
            assembled=assembled,
            rim_form=rim_form,
            session_id=session_id,
            project_id=project_id,
        )
        if not resolved_assembled or not resolved_assembled.get("positions"):
            raise ValueError(
                "Нет последней ЛСР для заполнения. Сначала соберите смету в режиме «Смета», "
                "затем повторите «собери КС-2» / «собери КС-3»."
            )
        rows = rows_for_form(fid, assembled=resolved_assembled)
        manual.setdefault("period", manual.get("period") or "отчётный период (из ЛСР)")
        manual["_document_status"] = "draft_from_lsr_not_execution_fact"
        result = forms_service.generate(
            fid, fmt, project_id=project_id, manual=manual, out_path=out_path, rows=rows,
        )
        result["source"] = _SOURCE_LAST_LSR
        result["positions"] = len(resolved_assembled["positions"])
        result["total"] = _f((resolved_assembled.get("summary") or {}).get("total"))
        result["filled"] = True
        # An LSR is a plan/calculation, not evidence of completed work. Preserve
        # the useful PR export, but make its legal/factual status explicit.
        result["document_status"] = "draft_from_lsr_not_execution_fact"
        result["draft"] = True
        return result

    # ks6a
    if src == _SOURCE_BLANK:
        return forms_service.generate(
            fid, fmt, project_id=project_id, manual=manual, out_path=out_path,
        )
    entries = list(journal_entries) if journal_entries is not None else load_confirmed_journal(
        project_id=project_id,
    )
    if not entries:
        raise ValueError(
            "Журнал полевых объёмов пуст (confirmed). "
            "Сначала запишите и подтвердите объёмы — ЛСР как факт выполнения не подставляется."
        )
    rows = rows_for_form(KS6A_FORM, journal_entries=entries)
    result = forms_service.generate(
        fid, fmt, project_id=project_id, manual=manual, out_path=out_path, rows=rows,
    )
    result["source"] = _SOURCE_FIELD_JOURNAL
    result["entries"] = len(entries)
    result["filled"] = True
    return result


def persist_rim_sidecar(artifact: dict[str, Any], *, path: Path) -> None:
    """Write compact JSON next to XLSX so last_lsr works without session."""
    rim = artifact.get("rim_lsr_form") if isinstance(artifact.get("rim_lsr_form"), dict) else None
    if not rim:
        rim = artifact.get("lsr_form") if isinstance(artifact.get("lsr_form"), dict) else None
    assembled = assembled_from_artifact(artifact if isinstance(artifact, dict) else None)
    payload: dict[str, Any] = {
        "schema": "les.smeta_artifact_sidecar.v1",
        "saved_at": time.time(),
        "rim_lsr_form": rim,
        "lsr_form": rim,
        "title": artifact.get("title"),
    }
    if assembled and assembled.get("positions"):
        payload["positions"] = assembled["positions"]
        payload["summary"] = assembled.get("summary") or {}
        # Keep a slim rim_trace pointer for disk fallback when rim_lsr_form is absent
        # (document-workflow LSR stores sections under rim_trace / lsr).
        if not rim:
            payload["rim_trace"] = {
                "positions": assembled["positions"],
                "summary": assembled.get("summary") or {},
            }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
