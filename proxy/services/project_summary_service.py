"""Сводка проекта: ТЭП + стадия + состав документов — W11.15 (каркас).

«Дай сводку проекта» одним детерминированным ответом: стадия (ПД/РД), технико-экономические
показатели (ТЭП) и состав документов. Источник — нормализованные Parquet-строки (числа из
таблиц) + имена документов. ADR-11: числа/факты считает код, не LLM. ТЭП-якоря калибруются
на реальных документах (котельная) — каркас уже рабочий.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Any

from proxy.services.dataset_memory_service import build_typed_dataset_memory, infer_file_typing, latest_file_cards
from proxy.services.reconcile_service import collect_rows_by_doc_type
from proxy.services.spec_to_bor_service import _row_qty

logger = logging.getLogger(__name__)

# Стадия проекта по маркерам в именах/заголовках документов.
_STAGE_RD = ("рабочая документац", "рабочий проект", " рд ", "_рд", "стадия р", "(р)")
_STAGE_PD = ("проектная документац", " пд ", "_пд", "стадия п", "пояснительная записк", "(п)")

# ТЭП на уровне ТАБЛИЦЫ (весь лист/таблица = ТЭП): якоря в doc_title/section.
_TEP_TABLE_ANCHORS = (
    "технико-эконом", "технико эконом", "тэп", "основные показател",
    "основные технические", "технические характеристики", "общие данные",
)
# ТЭП на уровне СТРОКИ: наименование показателя (котельная и общестрой).
_TEP_ROW_ANCHORS = (
    "мощност", "теплопроизводит", "производительност", "кпд", "расход топлив",
    "расход газа", "расход воды", "топлив", "котл", "температурн", "график",
    "категория надежн", "категория надёжн", "давлени", "теплоноситель",
    "годовая выработк", "число часов", "площад", "объем здани", "объём здани",
    "этажност", "строительный объем", "строительный объём",
)


def _norm(s: Any) -> str:
    return str(s or "").lower().replace("ё", "е")


def is_project_summary_query(question: str) -> bool:
    """Намерение «дай сводку проекта / ТЭП / стадия / что за проект». Без LLM."""
    q = _norm(question)
    if any(t in q for t in ("сводк", "тэп", "технико-эконом", "технико эконом", "основные показател")):
        return True
    # «дай/сделай/покажи + проект/котельн» или «что за проект», «опиши проект»
    if ("проект" in q or "котельн" in q or "объект" in q) and any(
        v in q for v in ("сводк", "сводн", "что за", "опиши", "паспорт", "стади", "кратко о", "обзор")
    ):
        return True
    return False


def is_project_inventory_query(question: str) -> bool:
    """Intent: list/register dataset/project files, optionally with a project description."""
    q = _norm(question)
    if "датасет" in q and any(t in q for t in ("что за", "что это за", "что внутри", "что есть")):
        return True
    has_inventory = any(t in q for t in (
        "перечен", "реестр", "список", "перечисли", "какие файлы", "файлы в датасете",
        "документы в датасете", "состав документац", "комплект документац",
    ))
    has_scope = any(t in q for t in ("файл", "документ", "датасет", "проект", "объект", "комплект"))
    return bool(has_inventory and has_scope)


def _detect_stage(rows: list[dict]) -> str:
    blob = " ".join(_norm(r.get("source_file")) + " " + _norm(r.get("doc_title")) for r in rows)
    pd = any(m in blob for m in _STAGE_PD)
    rd = any(m in blob for m in _STAGE_RD)
    if pd and rd:
        return "ПД + РД"
    if rd:
        return "РД (рабочая документация)"
    if pd:
        return "ПД (проектная документация)"
    return "не определена"


def extract_tep(rows: list[dict], *, limit: int = 40) -> list[dict[str, Any]]:
    """Кандидаты ТЭП: строки из ТЭП-таблиц (по якорю в заголовке) + показатели по якорю имени.

    Возвращает [{indicator, value, unit, source}]. Числа — из Parquet (qty/объём), не LLM.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = " ".join(str(row.get("name") or row.get("work_name") or "").split())
        if not name or len(name) < 3:
            continue
        title_blob = _norm(row.get("doc_title")) + " " + _norm(row.get("section"))
        low_name = _norm(name)
        in_tep_table = any(a in title_blob for a in _TEP_TABLE_ANCHORS)
        is_indicator = any(a in low_name for a in _TEP_ROW_ANCHORS)
        if not (in_tep_table or is_indicator):
            continue
        value = _row_qty(row)
        # Без числа показатель малоинформативен, кроме явных ТЭП-таблиц (там может быть текст-значение).
        if value is None and not in_tep_table:
            continue
        key = low_name[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "indicator": name,
            "value": round(value, 4) if value is not None else None,
            "unit": str(row.get("unit") or "").strip(),
            "source": str(row.get("source_file") or "").strip(),
        })
        if len(out) >= limit:
            break
    return out


_INV_ARTIFACTS = ("_preprocess_state.json",)  # служебные артефакты EXT_INDEX — не документы


def _inventory_meta_columns(conn) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(documents)").fetchall()}


def _file_ref_norm(value: Any) -> str:
    text = str(value or "").casefold().replace("ё", "е").replace("\\", "/")
    text = re.sub(r"[«»\"'`]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _contains_file_ref(haystack: str, needle: str) -> bool:
    """Substring match with filename-ish boundaries.

    Plain `in` is too loose for file names: `01_Содержание...` matches inside
    `001_Содержание...`, which makes an exact click look ambiguous.
    """
    if not haystack or not needle:
        return False
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return False
        before = haystack[idx - 1] if idx > 0 else ""
        after_idx = idx + len(needle)
        after = haystack[after_idx] if after_idx < len(haystack) else ""
        before_ok = not before or not (before.isalnum() or before in "_-")
        after_ok = not after or not (after.isalnum() or after in "_-")
        if before_ok and after_ok:
            return True
        start = idx + 1


def _path_suffixes(norm_path: str) -> list[str]:
    parts = [part for part in str(norm_path or "").split("/") if part]
    suffixes = []
    for idx in range(len(parts)):
        suffix = "/".join(parts[idx:])
        if suffix:
            suffixes.append(suffix)
    return suffixes


def resolve_inventory_file_reference(
    question: str,
    dataset_ids: list[str],
    *,
    meta_db_path: str | None = None,
) -> dict[str, Any] | None:
    """Resolve a user-mentioned file name/path to MetaDB `documents.file_name`.

    This is a retrieval routing hint, not an answer: if a user names a file from the
    dataset inventory, chat can narrow RAG to that exact document instead of hoping
    broad semantic search lands there.
    """
    if not question or not dataset_ids:
        return None
    import os
    import sqlite3

    from backend.rag_config import rag_meta_db_path

    q = _file_ref_norm(question)
    if "." not in q and not any(token in q for token in ("файл", "документ")):
        return None
    path = meta_db_path or rag_meta_db_path()
    try:
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        columns = _inventory_meta_columns(con)
        chunk_expr = "COALESCE(chunk_count, 0)" if "chunk_count" in columns else "0"
        source_expr = "COALESCE(source_path, '')" if "source_path" in columns else "''"
        qmarks = ",".join("?" * len(dataset_ids))
        rows = con.execute(
            f"""
            SELECT dataset_id, file_name, status, {chunk_expr} AS chunk_count, {source_expr} AS source_path
            FROM documents
            WHERE dataset_id IN ({qmarks})
            ORDER BY file_name
            """,
            list(dataset_ids),
        ).fetchall()
        con.close()
    except Exception:  # noqa: BLE001
        return None

    scored: list[tuple[int, sqlite3.Row]] = []
    for row in rows:
        file_name = str(row["file_name"] or "")
        if not file_name or any(a in file_name for a in _INV_ARTIFACTS):
            continue
        norm_path = _file_ref_norm(file_name)
        base = os.path.basename(file_name.replace("\\", "/"))
        norm_base = _file_ref_norm(base)
        stem = _file_ref_norm(os.path.splitext(base)[0])
        best = 0
        for suffix in _path_suffixes(norm_path):
            if _contains_file_ref(q, suffix):
                best = max(best, 10_000 + len(suffix))
        if norm_base and _contains_file_ref(q, norm_base):
            best = max(best, 5_000 + len(norm_base))
        if len(stem) >= 8 and _contains_file_ref(q, stem):
            best = max(best, 1_000 + len(stem))
        if best:
            scored.append((best, row))

    if scored:
        best_score = max(score for score, _row in scored)
        matches = [row for score, row in scored if score == best_score]
    else:
        matches = []
    if not matches:
        return None

    def _payload(row) -> dict[str, Any]:
        return {
            "dataset_id": str(row["dataset_id"] or ""),
            "file_name": str(row["file_name"] or ""),
            "basename": os.path.basename(str(row["file_name"] or "").replace("\\", "/")),
            "status": str(row["status"] or ""),
            "chunk_count": int(row["chunk_count"] or 0),
            "source_path": str(row["source_path"] or ""),
        }

    if len(matches) == 1:
        out = _payload(matches[0])
        out["match_status"] = "matched"
        return out
    return {
        "match_status": "ambiguous",
        "matches": [_payload(row) for row in matches[:12]],
        "match_count": len(matches),
    }


def inventory_from_metadb(dataset_ids: list[str], *, meta_db_path: str | None = None) -> dict[str, Any]:
    """Опись документов датасета(ов) из MetaDB — ВСЕ файлы (не только табличные/Parquet),
    сгруппированы по папке, с разбивкой по типам. Источник «реестра/что-в-папке». Без LLM.

    Это закрывает асимметрию: ТЭП-сводка (Parquet) есть не у всех датасетов (BAI — PDF/docx без
    таблиц), а опись файлов есть всегда (она в documents независимо от парсинга)."""
    import os
    import sqlite3
    from collections import Counter, defaultdict

    from backend.rag_config import rag_meta_db_path

    path = meta_db_path or rag_meta_db_path()
    by_folder: dict[str, list[tuple[str, str]]] = defaultdict(list)
    files: list[dict[str, Any]] = []
    ext_c: Counter = Counter()
    total = indexed = 0
    if dataset_ids:
        try:
            for ds in dataset_ids:
                try:
                    build_typed_dataset_memory(str(ds), meta_db_path=meta_db_path)
                except Exception:
                    pass
            cards = latest_file_cards([str(ds) for ds in dataset_ids], meta_db_path=meta_db_path)
            con = sqlite3.connect(path)
            columns = _inventory_meta_columns(con)
            chunk_expr = "COALESCE(chunk_count, 0)" if "chunk_count" in columns else "0"
            source_expr = "COALESCE(source_path, '')" if "source_path" in columns else "''"
            doc_type_expr = "COALESCE(doc_type, '')" if "doc_type" in columns else "''"
            content_type_expr = "COALESCE(content_type, '')" if "content_type" in columns else "''"
            domain_expr = "COALESCE(domain, '')" if "domain" in columns else "''"
            pipeline_expr = "COALESCE(pipeline, '')" if "pipeline" in columns else "''"
            qmarks = ",".join("?" * len(dataset_ids))
            cur = con.execute(
                f"""
                SELECT dataset_id, file_name, status, {chunk_expr} AS chunk_count,
                       {source_expr} AS source_path, {doc_type_expr} AS doc_type,
                       {content_type_expr} AS content_type, {domain_expr} AS domain,
                       {pipeline_expr} AS pipeline
                FROM documents
                WHERE dataset_id IN ({qmarks})
                ORDER BY file_name
                """,
                list(dataset_ids),
            )
            for dsid, fn, st, chunk_count, source_path, doc_type, content_type, domain, pipeline in cur.fetchall():
                fn = str(fn or "")
                if not fn or any(a in fn for a in _INV_ARTIFACTS):
                    continue
                parts = fn.split("/")
                folder = "/".join(parts[1:-1]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else "(корень)")
                by_folder[folder].append((parts[-1], str(st or "")))
                doc_payload = {
                    "file_name": fn,
                    "status": st,
                    "chunk_count": chunk_count,
                    "doc_type": doc_type,
                    "content_type": content_type,
                    "domain": domain,
                    "pipeline": pipeline,
                }
                typing = infer_file_typing(doc_payload)
                card = cards.get((str(dsid or ""), fn)) or {}
                content_layers = card.get("content_layers") or typing["content_layers"]
                content_layer_labels = [
                    str(x) for x in (typing.get("content_layer_labels") or [])
                    if x
                ]
                files.append({
                    "dataset_id": str(dsid or ""),
                    "file_name": fn,
                    "name": parts[-1],
                    "folder": folder,
                    "status": str(st or ""),
                    "chunk_count": int(chunk_count or 0),
                    "source_path": str(source_path or ""),
                    "file_kind": str(card.get("file_kind") or typing["file_kind"]),
                    "content_layers": content_layers,
                    "content_layer_labels": content_layer_labels,
                    "document_role": str(card.get("document_role") or typing["document_role"]),
                    "source_granularity": str(typing["source_granularity"]),
                })
                ext_c[os.path.splitext(fn)[1].lower() or "(без расш.)"] += 1
                total += 1
                if str(st or "") == "INDEXED":
                    indexed += 1
            con.close()
        except Exception:  # noqa: BLE001 — опись best-effort, не роняет сводку
            return {"folders": {}, "total": 0, "indexed": 0, "by_ext": []}
    return {"folders": dict(by_folder), "files": files, "total": total, "indexed": indexed,
            "by_ext": ext_c.most_common()}


def build_project_summary(
    dataset_ids: list[str],
    *,
    storage_root: Path = mutable_path("storage/datasets"),
    meta_db_path: str | None = None,
) -> dict[str, Any]:
    """Сводка по датасетам: стадия + ТЭП (Parquet) + ОПИСЬ документов (MetaDB). Без LLM.

    Опись (inventory) добавлена, чтобы датасеты без Parquet-таблиц (BAI и пр.) тоже давали
    осмысленный «реестр/что-в-папке», а не проваливались в RAG → NO_DATA."""
    rows: list[dict] = []
    for ds in dataset_ids:
        for _dt, rws in collect_rows_by_doc_type(ds, storage_root=storage_root).items():
            rows.extend(rws)

    documents = sorted({str(r.get("source_file") or "").strip() for r in rows if r.get("source_file")})
    inventory = inventory_from_metadb(dataset_ids, meta_db_path=meta_db_path)
    return {
        "dataset_ids": dataset_ids,
        "stage": _detect_stage(rows),
        "tep": extract_tep(rows),
        "documents": documents,
        "document_count": len(documents),
        "table_rows": len(rows),
        "inventory": inventory,
        "file_count": inventory["total"],
    }


def format_project_summary(result: dict[str, Any], label: str = "") -> str:
    lines = [f"Сводка проекта{(' · ' + label) if label else ''}:",
             f"Стадия: {result['stage']}"]

    # ── Реестр документов (опись из MetaDB — есть всегда, не зависит от Parquet) ──
    inv = result.get("inventory") or {}
    folders = inv.get("folders") or {}
    if inv.get("total"):
        lines.append(f"\nРеестр документов: {inv['total']} файлов · {len(folders)} папок · "
                     f"в индексе {inv.get('indexed', 0)}/{inv['total']}")
        for folder in sorted(folders)[:14]:
            files = folders[folder]
            lines.append(f"  📁 {folder} ({len(files)})")
            for name, st in files[:6]:
                mark = "·" if st == "INDEXED" else "○"
                lines.append(f"       {mark} {name}")
            if len(files) > 6:
                lines.append(f"       … ещё {len(files) - 6}")
        if len(folders) > 14:
            lines.append(f"  … ещё {len(folders) - 14} папок")
        by_ext = inv.get("by_ext") or []
        if by_ext:
            lines.append("По типам: " + ", ".join(f"{e} {n}" for e, n in by_ext))

    # ── ТЭП/таблицы (Parquet) — если у датасета есть табличные документы ──
    tep = result.get("tep") or []
    if result.get("table_rows"):
        lines.append(f"\nДокументов с таблицами: {result['document_count']} · табличных строк: {result['table_rows']}")
    if tep:
        lines.append(f"Технико-экономические показатели (кандидаты, {len(tep)}):")
        for t in tep[:25]:
            val = (f"{t['value']} {t['unit']}".strip() if t["value"] is not None else "—")
            lines.append(f"  • {t['indicator']} — {val}")

    lines.append("\nРеестр — из MetaDB, числа — из Parquet (0 LLM). «○» — ещё не в индексе.")
    return "\n".join(lines)


def format_project_inventory_context(
    result: dict[str, Any],
    label: str = "",
    *,
    max_folders: int = 80,
    max_files_per_folder: int = 120,
) -> str:
    """Fuller file inventory block for RAG synthesis prompts.

    This is deterministic evidence from MetaDB, not a semantic retrieval chunk.
    """
    inv = result.get("inventory") or {}
    folders = inv.get("folders") or {}
    lines = [
        f"ПРОВЕРЯЕМАЯ ОПИСЬ ФАЙЛОВ ДАТАСЕТА{(' · ' + label) if label else ''}",
        "Источник: внутренняя таблица документов ЛЕС (MetaDB documents). "
        "Это проверяемая опись файлов датасета, не вывод модели.",
        f"Всего файлов: {inv.get('total', 0)}; в индексе: {inv.get('indexed', 0)}; папок: {len(folders)}.",
    ]
    by_ext = inv.get("by_ext") or []
    if by_ext:
        lines.append("Типы файлов: " + ", ".join(f"{ext}×{count}" for ext, count in by_ext))
    for folder in sorted(folders)[:max_folders]:
        files = folders[folder]
        lines.append(f"\nПапка: {folder} ({len(files)})")
        for name, status in files[:max_files_per_folder]:
            mark = "INDEXED" if str(status or "") == "INDEXED" else (str(status or "") or "UNKNOWN")
            lines.append(f"- {name} [{mark}]")
        if len(files) > max_files_per_folder:
            lines.append(f"- ... ещё {len(files) - max_files_per_folder} файлов")
    if len(folders) > max_folders:
        lines.append(f"\n... ещё {len(folders) - max_folders} папок")
    return "\n".join(lines)


def format_project_inventory_prompt(
    result: dict[str, Any],
    label: str = "",
    *,
    max_folders: int = 16,
    max_files: int = 24,
) -> str:
    """Compact navigation map for the LLM.

    The full deterministic registry stays in ``project_inventory``/artifact/UI.
    This prompt block should help the model choose where to look, not make it
    rewrite the whole file list.
    """
    inv = result.get("inventory") or {}
    folders = inv.get("folders") or {}
    files = inv.get("files") or []
    lines = [
        f"КАРТА РЕЕСТРА ДАТАСЕТА{(' · ' + label) if label else ''}",
        "Навигационная карта из MetaDB documents. Это не содержимое файлов и не evidence для фактов.",
        "Полный реестр доступен отдельным артефактом/project_inventory; не переписывай его в ответ.",
        f"Всего файлов: {inv.get('total', 0)}; в индексе: {inv.get('indexed', 0)}; папок: {len(folders)}.",
    ]
    by_ext = inv.get("by_ext") or []
    if by_ext:
        lines.append("Типы: " + ", ".join(f"{ext}×{count}" for ext, count in by_ext[:12]))

    if folders:
        folder_bits: list[str] = []
        for folder in sorted(folders)[:max_folders]:
            folder_bits.append(f"{folder} ({len(folders[folder])})")
        if len(folders) > max_folders:
            folder_bits.append(f"... ещё {len(folders) - max_folders}")
        lines.append("Папки: " + "; ".join(folder_bits))

    def _score_file(item: dict[str, Any]) -> tuple[int, str]:
        text = " ".join([
            str(item.get("file_name") or ""),
            str(item.get("name") or ""),
            str(item.get("document_role") or ""),
            " ".join(str(x) for x in (item.get("content_layers") or [])),
        ]).casefold()
        score = 0
        for needle, weight in (
            ("состав проект", 80),
            ("поясн", 70),
            ("_пз", 70),
            ("содержание", 55),
            ("задание", 55),
            ("сту", 50),
            ("тэп", 45),
            ("xlsx", 35),
            ("estimate", 30),
            ("table", 20),
        ):
            if needle in text:
                score += weight
        if str(item.get("status") or "") == "INDEXED":
            score += 10
        score += min(int(item.get("chunk_count") or 0), 20)
        return (-score, str(item.get("file_name") or ""))

    important = sorted([item for item in files if isinstance(item, dict)], key=_score_file)[:max_files]
    if important:
        lines.append("Файлы-кандидаты для широких вопросов:")
        for item in important:
            role = str(item.get("document_role") or "").strip()
            layers = ", ".join(str(x) for x in (item.get("content_layer_labels") or item.get("content_layers") or [])[:3])
            suffix = " — ".join(x for x in (role, layers) if x)
            status = str(item.get("status") or "UNKNOWN")
            lines.append(f"- {item.get('file_name')} [{status}]" + (f" · {suffix}" if suffix else ""))
    return "\n".join(lines)
