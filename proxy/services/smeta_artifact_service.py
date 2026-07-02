"""Build user-facing smeta artifacts from model-written estimate answers.

The service is intentionally shallow: it does not choose works, norms, rates or
quantities.  It only extracts Markdown tables already produced by the estimator
model, computes visible table totals, and prepares a separate artifact payload.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proxy.services.estimate_math_service import parse_ru_number


@dataclass(frozen=True)
class SmetaTable:
    title: str
    kind: str
    headers: list[str]
    rows: list[list[str]]
    markdown: str
    amount_total: float | None = None


_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_MONEY_HEADER_TOKENS = ("сумм", "стоим", "итого", "руб")


def _split_cells(line: str) -> list[str]:
    text = str(line or "").strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_table_header(line: str, next_line: str) -> bool:
    return "|" in str(line or "") and bool(_SEPARATOR_RE.match(str(next_line or "")))


def _clean_title(line: str) -> str:
    text = str(line or "").strip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = text.strip("*").strip()
    return text


def _nearest_title(lines: list[str], start: int) -> str:
    for idx in range(start - 1, max(-1, start - 8), -1):
        text = lines[idx].strip()
        if not text:
            continue
        if text.startswith("|"):
            continue
        if text.startswith("#") or text.startswith("**"):
            return _clean_title(text)
        if len(text) <= 90:
            return _clean_title(text)
    return "Сметная таблица"


def _classify_table(headers: list[str], title: str) -> str:
    joined = " ".join([title, *headers]).casefold()
    if "поставка" in joined or "материал" in joined and "работ" not in joined:
        return "supply"
    if "развилк" in joined or "вариант" in joined and "объ" in joined:
        return "quantity_conflict"
    if ("рим" in joined and "рын" in joined) or "гэсн" in joined and "рын" in joined:
        return "method_comparison"
    if any(token in joined for token in ("сумм", "стоим", "ставк", "руб")):
        return "work_cost"
    if any(token in joined for token in ("работ", "вор", "ед.", "кол-во", "количество")):
        return "bor"
    return "table"


def _amount_column_indexes(headers: list[str]) -> list[int]:
    out: list[int] = []
    for idx, header in enumerate(headers):
        low = header.casefold()
        if "ставк" in low or "цена" in low and "итого" not in low:
            continue
        if any(token in low for token in _MONEY_HEADER_TOKENS):
            out.append(idx)
    return out


def _parse_money_cell(cell: str) -> float | None:
    text = str(cell or "")
    if not re.search(r"\d", text):
        return None
    value = parse_ru_number(text.replace("**", ""))
    if value is None:
        return None
    return float(value)


def _table_amount_total(headers: list[str], rows: list[list[str]]) -> float | None:
    indexes = _amount_column_indexes(headers)
    if not indexes:
        return None
    total = 0.0
    found = False
    for row in rows:
        first = row[0].casefold() if row else ""
        if "итого" in first or "всего" in first:
            continue
        row_value: float | None = None
        for idx in indexes:
            if idx < len(row):
                parsed = _parse_money_cell(row[idx])
                if parsed is not None:
                    row_value = parsed
        if row_value is not None:
            total += row_value
            found = True
    return total if found else None


def _fmt_money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " руб."


def _safe_sheet_title(title: str, used: set[str]) -> str:
    text = re.sub(r"[\[\]:*?/\\]", " ", str(title or "Таблица")).strip() or "Таблица"
    text = re.sub(r"\s+", " ", text)[:31]
    base = text or "Таблица"
    candidate = base
    idx = 2
    while candidate in used:
        suffix = f" {idx}"
        candidate = (base[: 31 - len(suffix)] + suffix).strip()
        idx += 1
    used.add(candidate)
    return candidate


def extract_smeta_tables(answer: str) -> list[SmetaTable]:
    """Extract Markdown tables from a smeta answer without interpreting domain logic."""
    lines = str(answer or "").splitlines()
    tables: list[SmetaTable] = []
    idx = 0
    while idx < len(lines) - 1:
        if not _is_table_header(lines[idx], lines[idx + 1]):
            idx += 1
            continue
        start = idx
        idx += 2
        while idx < len(lines) and "|" in lines[idx]:
            idx += 1
        raw = lines[start:idx]
        headers = _split_cells(raw[0])
        rows = [_split_cells(line) for line in raw[2:] if line.strip()]
        title = _nearest_title(lines, start)
        kind = _classify_table(headers, title)
        tables.append(SmetaTable(
            title=title,
            kind=kind,
            headers=headers,
            rows=rows,
            markdown="\n".join(raw),
            amount_total=_table_amount_total(headers, rows),
        ))
    return tables


def build_smeta_artifact(answer: str, *, question: str = "") -> dict[str, Any] | None:
    """Return a Markdown artifact payload for visible smeta tables, if any."""
    tables = extract_smeta_tables(answer)
    if not tables:
        return None
    lines = ["# Сметный артефакт", ""]
    if question:
        lines += ["## Запрос", str(question).strip(), ""]
    lines += [
        "## Свод таблиц",
        "| Таблица | Тип | Строк | Сумма по видимым строкам |",
        "|---|---|---:|---:|",
    ]
    for table in tables:
        amount = _fmt_money(table.amount_total) if table.amount_total is not None else ""
        lines.append(f"| {table.title} | {table.kind} | {len(table.rows)} | {amount} |")
    for num, table in enumerate(tables, start=1):
        lines += ["", f"## {num}. {table.title}", "", table.markdown]
    total = sum(table.amount_total or 0.0 for table in tables if table.kind in {"work_cost", "method_comparison"})
    if total > 0:
        lines += ["", "## Арифметика", f"Сумма по видимым строкам таблиц стоимости: **{_fmt_money(total)}**."]
    return {
        "mode": "markdown",
        "title": "Сметный артефакт",
        "content": "\n".join(lines).strip(),
        "tables": [
            {
                "title": table.title,
                "kind": table.kind,
                "rows": len(table.rows),
                "amount_total": table.amount_total,
                "headers": table.headers,
                "data": table.rows,
            }
            for table in tables
        ],
    }


def persist_smeta_artifact_exports(
    artifact: dict[str, Any] | None,
    *,
    output_dir: str | Path = "storage/smeta_artifacts",
    prefix: str = "smeta_artifact",
) -> dict[str, Any] | None:
    """Write XLSX and CSV downloads for an already built smeta artifact.

    The export preserves model-written tables.  It does not add works, choose
    norms, change rates, or recalculate hidden positions.
    """
    if not artifact:
        return None
    tables = [t for t in artifact.get("tables") or [] if t.get("headers") and t.get("data")]
    if not tables:
        return artifact

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    import time

    stamp = int(time.time() * 1000)
    safe_prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix).strip("_") or "smeta_artifact"
    xlsx_name = f"{safe_prefix}_{stamp}.xlsx"
    csv_name = f"{safe_prefix}_{stamp}.csv"
    xlsx_path = out_dir / xlsx_name
    csv_path = out_dir / csv_name

    import openpyxl

    wb = openpyxl.Workbook()
    summary_ws = wb.active
    summary_ws.title = "Свод"
    summary_ws.append(["Таблица", "Тип", "Строк", "Сумма по видимым строкам"])
    for table in tables:
        summary_ws.append([
            table.get("title") or "",
            table.get("kind") or "",
            table.get("rows") or 0,
            table.get("amount_total") or "",
        ])
    used = {"Свод"}
    for table in tables:
        ws = wb.create_sheet(_safe_sheet_title(str(table.get("title") or "Таблица"), used))
        ws.append([str(h) for h in table.get("headers") or []])
        for row in table.get("data") or []:
            ws.append([str(cell) for cell in row])
        for column_cells in ws.columns:
            width = min(max(len(str(cell.value or "")) for cell in column_cells) + 2, 60)
            ws.column_dimensions[column_cells[0].column_letter].width = width
    wb.save(xlsx_path)

    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        for table in tables:
            writer.writerow([str(table.get("title") or "Таблица")])
            writer.writerow([str(h) for h in table.get("headers") or []])
            for row in table.get("data") or []:
                writer.writerow([str(cell) for cell in row])
            writer.writerow([])

    artifact = dict(artifact)
    artifact["downloads"] = {
        "xlsx": f"/api/smeta-artifacts/download?path={xlsx_name}",
        "csv": f"/api/smeta-artifacts/download?path={csv_name}",
    }
    artifact["files"] = {
        "xlsx_path": str(xlsx_path),
        "csv_path": str(csv_path),
    }
    return artifact


def compact_smeta_answer(answer: str, artifact: dict[str, Any] | None) -> str:
    """Keep chat readable when the answer contains long estimate tables.

    Short tables stay in the chat. Long tables are replaced with a short marker;
    the full table remains in the artifact payload.
    """
    if not artifact:
        return answer
    tables = extract_smeta_tables(answer)
    if not tables or sum(len(table.rows) for table in tables) < 5:
        return answer

    result_lines: list[str] = []
    lines = str(answer or "").splitlines()
    idx = 0
    table_num = 0
    while idx < len(lines):
        if idx < len(lines) - 1 and _is_table_header(lines[idx], lines[idx + 1]):
            start = idx
            idx += 2
            while idx < len(lines) and "|" in lines[idx]:
                idx += 1
            table = tables[table_num] if table_num < len(tables) else None
            table_num += 1
            if table and len(table.rows) >= 4:
                amount = f", сумма строк {_fmt_money(table.amount_total)}" if table.amount_total is not None else ""
                result_lines.append(f"Таблица вынесена в артефакт: {table.title} ({len(table.rows)} строк{amount}).")
            else:
                result_lines.extend(lines[start:idx])
            continue
        result_lines.append(lines[idx])
        idx += 1
    compacted = "\n".join(result_lines)
    compacted = re.sub(r"\n{3,}", "\n\n", compacted).strip()
    return compacted or answer
