"""Sidecar Operations (v0.16) — инвентаризация датасетов, классификация по заголовкам из sidecar,
extraction-state сообщения, lexical-индекс извлечённого тела (отдельная FTS), OCR-детект, Qdrant-defer.

Делает извлечение ОПЕРАТОРСКИ ВИДИМОЙ и УПРАВЛЯЕМОЙ операцией. Никогда: не пишет runtime-sidecar без
одобрения (это в extract_dataset_bodies_v14), не трогает оригиналы, не запускает OCR, не выдумывает
заголовки/source_ref, не хардкодит доменные термины (ОЗК и пр.). Чистые функции → юнит-тестируемо.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from proxy.services import doc_extract_service as de
from proxy.services.doc_type_classifier import classify_doc_type, classify_discipline

V16_VERSION = "sidecar_ops_v0_16"

# ── §1 инвентаризация датасетов рантайма ─────────────────────────────────────────────────

_EXT_GROUPS = {"md": (".md",), "eml": (".eml",), "pdf": (".pdf",), "docx": (".docx", ".doc"),
               "xlsx": (".xlsx", ".xls"), "txt": (".txt",), "csv": (".csv",), "parquet": (".parquet",)}

# признаки project-like (НЕ хардкод терминов поиска — это эвристика типа корпуса по ИМЕНАМ файлов)
_PROJECT_KW = ("котельн", "акт", "исполнительн", "спецификац", "ф9", "ф-9", "вор", "лср", "смет",
               "кс-2", "кс2", "журнал", "оборудован", "_ов", "_вк", "_тм", "гсв", "аупт", "апс",
               "ппа", "тепломех", "дымоудал", "эом")
_NORM_KW = ("гост", "снип", "свод правил", " сп ", "сп ", "стандарт", "ту ", "межгосударствен")
_ESTIMATE_KW = ("смет", "лср", "кс-2", "кс2", "ведомость объ", "ф9", "ф-9", "вор", "расцен", "гэсн", "фер")


def _iter_files(ds_dir: Path) -> list[Path]:
    out = []
    for p in ds_dir.rglob("*"):
        if p.is_file() and de.SIDECAR_DIRNAME not in p.parts and not p.name.startswith("."):
            out.append(p)
    return out


def inspect_dataset(ds_dir: Path, *, storage_root: Path) -> dict:
    """Один датасет → счётчики расширений + sidecar/manifest/stale + скоринг типа корпуса."""
    ds = ds_dir.name
    files = _iter_files(ds_dir)
    names = [f.name.lower() for f in files]
    counts = {g: 0 for g in _EXT_GROUPS}
    for n in names:
        for g, exts in _EXT_GROUPS.items():
            if n.endswith(exts):
                counts[g] += 1
    legacy_xls = sum(1 for n in names if n.endswith((".xls", ".doc")) and not n.endswith((".xlsx", ".docx")))
    sc = de.sidecar_count(storage_root, ds)
    manifest = de.read_manifest(storage_root, ds)
    stale = de.sidecar_stale_files(storage_root, ds) if sc else []
    blob = " ".join(names)

    def _score(kws):
        return sum(blob.count(k) for k in kws)

    proj = _score(_PROJECT_KW)
    mail = counts["eml"]
    norm = _score(_NORM_KW)
    est = _score(_ESTIMATE_KW)
    # candidate_doc_types — по именам файлов (грубо, до sidecar-классификации)
    cdt = Counter(classify_doc_type(n) for n in names)
    extractable = counts["pdf"] + counts["docx"] + counts["xlsx"] + counts["txt"] + counts["csv"]
    return {
        "dataset_id": ds, "file_count": len(files),
        "md_count": counts["md"], "eml_count": counts["eml"], "pdf_count": counts["pdf"],
        "docx_count": counts["docx"], "xlsx_count": counts["xlsx"], "txt_count": counts["txt"],
        "csv_count": counts["csv"], "parquet_count": counts["parquet"],
        "legacy_xls_count": legacy_xls,
        "extractable_count": extractable,
        "sidecar_count": sc, "manifest_exists": manifest is not None, "stale_count": len(stale),
        "likely_project_score": proj, "likely_mail_score": mail,
        "likely_norm_score": norm, "likely_estimate_score": est,
        "candidate_doc_types": dict(cdt.most_common(6)),
        "corpus_guess": _corpus_guess(proj, mail, norm, est),
    }


def _corpus_guess(proj: int, mail: int, norm: int, est: int) -> str:
    best = max((mail, "mail"), (norm, "norm"), (est, "estimate"), (proj, "project"), key=lambda x: x[0])
    return best[1] if best[0] > 0 else "unknown"


def inventory_datasets(storage_root: Path) -> dict:
    """Все датасеты рантайма → инвентарь (без записи)."""
    root = Path(storage_root)
    dss = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")) if root.exists() else []
    items = [inspect_dataset(d, storage_root=root) for d in dss]
    return {
        "version": V16_VERSION, "storage_root": str(root), "dataset_count": len(items),
        "mail_datasets": [i["dataset_id"] for i in items if i["likely_mail_score"] > 0],
        "norm_datasets": [i["dataset_id"] for i in items if i["likely_norm_score"] >= 2],
        "project_like_datasets": [i["dataset_id"] for i in items if i["corpus_guess"] == "project"],
        "extraction_candidates": [i["dataset_id"] for i in items
                                  if i["extractable_count"] > 0 and i["sidecar_count"] == 0],
        "already_extracted": [i["dataset_id"] for i in items if i["sidecar_count"] > 0],
        "datasets": items,
    }


# ── §3 классификация документа по заголовкам из sidecar ──────────────────────────────────

# heading-правила (по тексту заголовка/первых абзацев/имён листов) — порядок = приоритет
_HEADING_RULES: list[tuple[str, Any]] = [
    ("installed_equipment_act", lambda t: "акт" in t and ("смонтирован" in t or "оборудован" in t)),
    ("ks2", lambda t: "кс-2" in t or "кс2" in t or ("форма" in t and "кс" in t)),
    ("lsr", lambda t: ("локальн" in t and "сметн" in t) or "лср" in t),
    ("f9_bor", lambda t: "ведомость объ" in t or "ф9" in t or "ф-9" in t or "форма 9" in t),
    ("specification", lambda t: "спецификац" in t),
    ("work_log", lambda t: "журнал" in t and ("работ" in t or "производ" in t)),
    ("asbuilt", lambda t: "исполнительн" in t),
    ("estimate", lambda t: "сметн" in t or "смета" in t),
    ("norm", lambda t: "гост" in t or "свод правил" in t or "снип" in t or bool(re.search(r"\bсп\b", t))),
    ("external_reference", lambda t: any(k in t for k in ("revit", " api ", "cad-bim", "speckle"))),
]


def _sidecar_signals(sidecar_items: list[dict]) -> dict:
    """Из sidecar-items вытащить heading (первый непустой абзац/p0), первые абзацы, имена листов."""
    heading = ""
    heading_ref = ""
    paras: list[str] = []
    sheets: list[str] = []
    for it in sidecar_items or []:
        txt = str(it.get("text", "")).strip()
        if not txt:
            continue
        sheet = it.get("sheet") or it.get("sheet_name")
        if sheet and str(sheet) not in sheets:
            sheets.append(str(sheet))
        if not heading and (it.get("paragraph_index") in (0, None) or len(paras) == 0):
            heading = txt[:160]
            heading_ref = str(it.get("source_ref") or "")
        if len(paras) < 5:
            paras.append(txt[:160])
    return {"heading": heading, "heading_source_ref": heading_ref, "paragraphs": paras, "sheets": sheets}


def classify_document_from_sidecar(record: dict, sidecar_items: list[dict] | None) -> dict:
    """doc_type+discipline по заголовкам из sidecar (улучшает filename-классификацию). Sidecar нет →
    откат на имя файла; classified_by показывает источник сигнала. Заголовки НЕ выдумываем."""
    file_name = str((record or {}).get("file_name") or (record or {}).get("name") or "")
    sig = _sidecar_signals(sidecar_items or [])
    signal_text = " ".join([sig["heading"]] + sig["paragraphs"][:3] + sig["sheets"]).lower()

    dt_heading = ""
    if signal_text.strip():
        for dt, pred in _HEADING_RULES:
            if pred(signal_text):
                dt_heading = dt
                break
    dt_name = classify_doc_type(file_name)
    # заголовок специфичнее имени → берём его; иначе имя; иначе unknown (не теряем «не-мусор»)
    if dt_heading:
        doc_type, by = dt_heading, "sidecar_heading"
    elif dt_name not in ("unknown",):
        doc_type, by = dt_name, "filename"
    else:
        doc_type, by = "unknown", "none"

    disc = classify_discipline(signal_text) if signal_text.strip() else "unknown"
    if disc == "unknown":
        disc = classify_discipline(file_name)
    return {
        "doc_type": doc_type, "discipline": disc, "classified_by": by,
        "heading": sig["heading"], "heading_source_ref": sig["heading_source_ref"],
        "sheets": sig["sheets"][:8],
        "is_noise": doc_type == "garbage",
    }


# ── §4 extraction-state сообщения (видимый MISSING/BLOCKED + следующее действие) ───────────

def extraction_state_message(*, sidecar_available: bool = False, has_extractable_docs: bool = False,
                             is_runtime: bool = False, write_allowed: bool = False,
                             stale_count: int = 0, no_text_layer_count: int = 0,
                             term_searched: bool = False, term_found: bool = False,
                             is_eml_dataset: bool = False, legacy_xls_count: int = 0) -> dict:
    """Состояние извлечения → {case, message, action, ocr_required}. Приоритет конкретного состояния
    над дженериком. Никогда не «не найдено»/«no_lexical_index», если состояние известно."""
    # G: EML-корпус просмотрен
    if is_eml_dataset and term_searched:
        return _msg("eml_dataset_searched", "Почтовые файлы найдены и просмотрены как `.eml`.",
                    "" if term_found else "Уточните адресата/тему или выберите другой датасет.")
    # F: sidecar есть, искали, но термина нет
    if sidecar_available and term_searched and not term_found:
        return _msg("term_absent_after_extracted_search",
                    "Источник доступен и был просмотрен, но термин не найден.",
                    "Проверьте формулировку термина или выберите другой датасет.")
    # E: scanned PDF / нет текстового слоя
    if no_text_layer_count > 0 and not sidecar_available:
        return _msg("no_text_layer", "PDF найден, но текстовый слой отсутствует; нужен OCR вне горячего пути.",
                    "OCR — отдельный офлайн-пайплайн (не в этом запросе).", ocr_required=True)
    # D: sidecar устарел
    if stale_count > 0:
        return _msg("sidecar_stale", "Извлечённый текст устарел относительно исходного файла.",
                    "Перезапустите извлечение тела документа для обновления sidecar.")
    # A: sidecar есть и просмотрен
    if sidecar_available:
        return _msg("sidecar_exists_and_searched", "Искал в извлечённом тексте документов.",
                    "")
    # C: извлекаемые есть, но runtime-запись не разрешена
    if has_extractable_docs and is_runtime and not write_allowed:
        return _msg("extraction_write_not_approved",
                    "Извлечение возможно, но запись sidecar в runtime-хранилище не разрешена оператором.",
                    "Включите LES_ALLOW_RUNTIME_SIDECAR_WRITE=1 и подтвердите запись.")
    # legacy .xls/.doc — честный actionable (не читаем как новый формат, не фейк-таблицы)
    if legacy_xls_count > 0 and not has_extractable_docs and not sidecar_available:
        return _msg("legacy_xls_unsupported",
                    "Найдены legacy .xls/.doc — не поддержаны без конвертации/совместимого парсера.",
                    "Сохраните как .xlsx/.docx или подключите xlrd/antiword-совместимый парсер.")
    # B: извлекаемые есть, sidecar нет
    if has_extractable_docs:
        return _msg("extraction_required",
                    "Документы найдены, но текстовое тело ещё не извлечено.",
                    "Запустите извлечение тела документа («Извлечь тело»).")
    return _msg("no_extractable_docs", "Извлекаемых документов (PDF/DOCX/XLSX) в датасете не найдено.",
                "Выберите другой датасет или загрузите документы.")


def _msg(case: str, message: str, action: str, *, ocr_required: bool = False) -> dict:
    return {"case": case, "message": message, "action": action, "ocr_required": ocr_required}


# ── §7 OCR-детект (только детект+рекомендация, БЕЗ OCR) ───────────────────────────────────

def ocr_detection(dataset_id: str, *, storage_root: Path) -> dict:
    """Сколько PDF без текстового слоя (по manifest-статусам). OCR НЕ запускаем."""
    man = de.read_manifest(storage_root, dataset_id)
    no_text = 0
    candidates: list[str] = []
    if man:
        for e in man.get("entries", []):
            if e.get("status") == "no_text_layer" and str(e.get("ext", "")).lower() == ".pdf":
                no_text += 1
                candidates.append(str(e.get("original_relative_path", "")))
    return {
        "dataset_id": dataset_id, "pdf_no_text_layer_count": no_text,
        "scanned_pdf_candidates": candidates[:50],
        "ocr_required": no_text > 0, "ocr_status": "deferred",
        "message": ("PDF без текстового слоя — нужен OCR вне горячего пути (отдельный офлайн-пайплайн)."
                    if no_text else "PDF со сканами не обнаружено в manifest."),
    }


# ── §6A lexical-индекс извлечённого тела (отдельная FTS extracted_fts) ────────────────────

def extracted_fts_db_path() -> str:
    return os.getenv("LES_EXTRACTED_FTS_DB") or str(Path.home() / "LES" / "storage" / "extracted_fts.db")


def _ensure_extracted_fts(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS extracted_chunks (
            id INTEGER PRIMARY KEY,
            dataset_id TEXT, file_name TEXT, source_ref TEXT UNIQUE,
            source_kind TEXT, locator TEXT, text TEXT,
            sidecar_mtime REAL, original_mtime REAL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS extracted_fts
            USING fts5(text, file_name, content='extracted_chunks', content_rowid='id',
                       tokenize='unicode61');
        CREATE TRIGGER IF NOT EXISTS extracted_ai AFTER INSERT ON extracted_chunks BEGIN
            INSERT INTO extracted_fts(rowid, text, file_name) VALUES (new.id, new.text, new.file_name);
        END;
        CREATE TRIGGER IF NOT EXISTS extracted_ad AFTER DELETE ON extracted_chunks BEGIN
            INSERT INTO extracted_fts(extracted_fts, rowid, text, file_name)
                VALUES('delete', old.id, old.text, old.file_name);
        END;
        """
    )


def lexical_index_extracted(dataset_id: str, *, storage_root: Path, dry_run: bool = True,
                            db_path: str | None = None) -> dict:
    """Sidecar JSONL → отдельная FTS extracted_fts (source_ref сохраняется; дубли по source_ref
    не переиндексируются). dry_run=True (по умолчанию) — только считает, ничего не пишет."""
    items = de.read_sidecars(storage_root, dataset_id)
    stale = set(de.sidecar_stale_files(storage_root, dataset_id))
    rep = {"version": V16_VERSION, "dataset_id": dataset_id, "dry_run": dry_run,
           "sidecar_items": len(items), "would_index": 0, "indexed": 0, "skipped_unchanged": 0,
           "stale_warned": len(stale), "db_path": db_path or extracted_fts_db_path()}
    if not items:
        rep["warning"] = "нет sidecar — сначала извлеките тело"
        return rep

    if dry_run:
        rep["would_index"] = len(items)
        return rep

    conn = sqlite3.connect(rep["db_path"])
    try:
        _ensure_extracted_fts(conn)
        existing = {r[0] for r in conn.execute(
            "SELECT source_ref FROM extracted_chunks WHERE dataset_id=?", (dataset_id,))}
        ins = 0
        for it in items:
            ref = str(it.get("source_ref") or "")
            if not ref or ref in existing:
                rep["skipped_unchanged"] += 1
                continue
            conn.execute(
                "INSERT OR IGNORE INTO extracted_chunks"
                "(dataset_id,file_name,source_ref,source_kind,locator,text,sidecar_mtime,original_mtime)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (dataset_id, str(it.get("original_file_name") or ""), ref,
                 str(it.get("source_kind") or it.get("kind") or "extracted_body"),
                 ref.partition("#")[2], str(it.get("text") or ""),
                 it.get("sidecar_mtime"), it.get("original_mtime")))
            ins += 1
        conn.commit()
        rep["indexed"] = ins
    finally:
        conn.close()
    return rep


def search_extracted_fts(query: str, *, dataset_id: str | None = None, top_k: int = 10,
                         db_path: str | None = None) -> list[dict]:
    """Поиск по extracted_fts. source_ref сохранён → ссылка до .docx#para остаётся честной."""
    path = db_path or extracted_fts_db_path()
    if not Path(path).exists() or not (query or "").strip():
        return []
    conn = sqlite3.connect(path)
    try:
        _ensure_extracted_fts(conn)
        q = " OR ".join(re.findall(r"\w{3,}", query.lower())) or query
        sql = ("SELECT c.dataset_id,c.file_name,c.source_ref,c.text FROM extracted_fts f "
               "JOIN extracted_chunks c ON c.id=f.rowid WHERE extracted_fts MATCH ?")
        params: list[Any] = [q]
        if dataset_id:
            sql += " AND c.dataset_id=?"
            params.append(dataset_id)
        sql += " LIMIT ?"
        params.append(top_k)
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
        return [{"dataset_id": r[0], "file_name": r[1], "source_ref": r[2],
                 "snippet": (r[3] or "")[:200]} for r in rows]
    finally:
        conn.close()


# ── §6B Qdrant — только отложенный отчёт (без эмбеддинга) ─────────────────────────────────

# ── §5 backend-экшены для GUI/API (status / dry-run / approved write) ─────────────────────

def extraction_status(dataset_id: str, *, storage_root: Path) -> dict:
    """Read-only статус извлечения датасета для GUI/API: инвентарь + sidecar/manifest/stale + OCR +
    extraction-state сообщение + гейт-флаги. Ничего не пишет."""
    sr = Path(storage_root)
    inv = inspect_dataset(sr / dataset_id, storage_root=sr)
    ocr = ocr_detection(dataset_id, storage_root=sr)
    is_runtime = de.is_runtime_path(sr)
    write_allowed = de.runtime_write_allowed()
    state = extraction_state_message(
        sidecar_available=inv["sidecar_count"] > 0, has_extractable_docs=inv["extractable_count"] > 0,
        is_runtime=is_runtime, write_allowed=write_allowed, stale_count=inv["stale_count"],
        no_text_layer_count=ocr["pdf_no_text_layer_count"], is_eml_dataset=inv["eml_count"] > 0,
        legacy_xls_count=inv.get("legacy_xls_count", 0))
    return {"version": V16_VERSION, "dataset_id": dataset_id, "inventory": inv, "ocr": ocr,
            "state": state, "is_runtime": is_runtime, "write_allowed": write_allowed,
            "sidecar_count": inv["sidecar_count"], "manifest_exists": inv["manifest_exists"],
            "stale_count": inv["stale_count"]}


def _safe_under(root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except Exception:  # noqa: BLE001
        return False


def run_extraction(dataset_id: str, *, storage_root: Path, exts: set[str], max_files: int = 2000,
                   max_mb: float = 40.0, do_write: bool = False, confirm_runtime: bool = False,
                   force: bool = False) -> dict:
    """Ядро извлечения тела (перенесено из scripts/extract_dataset_bodies_v14 в v0.17 — runtime-эндпоинты
    не зависят от скрипт-файла). GATE: запись в runtime только при confirm_runtime И env. Оригиналы целы."""
    ddir = Path(storage_root) / dataset_id
    runtime = de.is_runtime_path(storage_root)
    write_blocked = ""
    effective_write = do_write
    if do_write and runtime and not (confirm_runtime and de.runtime_write_allowed()):
        effective_write = False
        write_blocked = ("runtime_sidecar_write_not_approved: запись в runtime storage требует "
                         "confirm_runtime_write И env LES_ALLOW_RUNTIME_SIDECAR_WRITE=1; выполнен dry-run")
    rep: dict[str, Any] = {"dataset_id": dataset_id, "storage_root": str(storage_root), "runtime_path": runtime,
           "dry_run": not effective_write, "write_requested": do_write, "write_blocked": write_blocked,
           "originals_mutated": False, "files_seen": 0, "would_write": 0, "wrote_sidecars": 0,
           "pdf_text_pages": 0, "pdf_no_text_layer": 0, "docx_paragraphs": 0, "xlsx_rows": 0,
           "legacy_unsupported": 0, "unsupported": 0, "skipped_large": 0, "failures": 0,
           "by_status": Counter(), "manifest": ""}
    if not ddir.exists():
        rep["error"] = "dataset_dir_not_found"
        rep["by_status"] = {}
        return rep
    max_bytes = int(max_mb * 1024 * 1024)
    manifest_entries: list[dict] = []
    for p in sorted(ddir.rglob("*")):
        if rep["files_seen"] >= max_files:
            break
        if not p.is_file() or p.name.startswith(".") or f"/{de.SIDECAR_DIRNAME}/" in p.as_posix():
            continue
        ext = p.suffix.lower()
        if ext not in exts:
            continue
        rep["files_seen"] += 1
        if not _safe_under(ddir, p):
            continue
        try:
            st = p.stat()
            if st.st_size > max_bytes:
                rep["skipped_large"] += 1
                continue
        except OSError:
            continue
        rel = p.relative_to(ddir).as_posix()
        res = de.extract_file(p, ds=dataset_id, rel=rel)
        rep["by_status"][res.status] += 1
        if res.status == "legacy_unsupported":     # v0.17 honest .xls/.doc
            rep["legacy_unsupported"] += 1
            continue
        if res.status == "skipped":
            rep["unsupported"] += 1
            continue
        if res.status == "no_text_layer" and ext == ".pdf":
            rep["pdf_no_text_layer"] += 1
        if res.status in ("unavailable", "failed"):
            rep["failures"] += 1
        for it in res.items:
            rep["pdf_text_pages"] += it.source_kind == "pdf_text"
            rep["docx_paragraphs"] += it.source_kind in ("docx_text", "docx_table")
            rep["xlsx_rows"] += it.source_kind == "xlsx_row"
        if not res.items:
            continue
        rep["would_write"] += 1
        sp = de.sidecar_path(storage_root, dataset_id, rel)
        if effective_write and (not sp.exists() or force):
            de.write_sidecar(storage_root, dataset_id, rel, res.items)
            rep["wrote_sidecars"] += 1
        manifest_entries.append({"original_relative_path": rel, "original_size": st.st_size,
                                 "original_mtime": st.st_mtime, "ext": ext, "status": res.status,
                                 "item_count": len(res.items), "sidecar_path": str(sp),
                                 "warnings": res.warnings})
    if effective_write and manifest_entries:
        rep["manifest"] = str(de.write_manifest(storage_root, dataset_id, manifest_entries, created_at=""))
    rep["by_status"] = dict(rep["by_status"])
    return rep


def extract_body_op(dataset_id: str, *, storage_root: Path, write: bool = False,
                    confirm_runtime_write: bool = False, exts: set[str] | None = None,
                    max_files: int = 2000, max_mb: float = 40.0, force: bool = False) -> dict:
    """GUI/API-экшен извлечения. dry-run по умолчанию; запись только при write И confirm_runtime_write И
    env LES_ALLOW_RUNTIME_SIDECAR_WRITE=1 (гейт внутри). Оригиналы не меняются."""
    exts = exts or {".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv"}
    return run_extraction(dataset_id, storage_root=Path(storage_root), exts=exts, max_files=max_files,
                          max_mb=max_mb, do_write=write, confirm_runtime=confirm_runtime_write, force=force)


def qdrant_deferred_report(dataset_id: str, *, storage_root: Path, chunk_chars: int = 1200) -> dict:
    """Оценка точек для будущего Qdrant-индекса. НИЧЕГО не эмбеддит (тяжёлый расчёт — отдельным решением)."""
    items = de.read_sidecars(storage_root, dataset_id)
    total_chars = sum(len(str(it.get("text", ""))) for it in items)
    est_points = (total_chars // chunk_chars) + (1 if total_chars % chunk_chars else 0)
    return {
        "version": V16_VERSION, "dataset_id": dataset_id, "extracted_chunks": len(items),
        "total_chars": total_chars, "estimated_qdrant_points": est_points,
        "qdrant_status": "deferred", "embedding_run": False,
        "source_ref_mapping_ready": all(it.get("source_ref") for it in items) if items else False,
        "todo": "run embedding/index job separately (вне v0.16, отдельным решением оператора)",
    }
