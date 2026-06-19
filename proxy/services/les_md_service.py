"""les_md_service.py — LES.md: файл-контекст папки (CLAUDE.md для ЛЕС).

Кладёшь `LES.md` (или `ЛЕС.md`) в папку — ЛЕС читает его как авторитетный контекст:
- **frontmatter (YAML)** — машинно: проект/объект/стадия/шифр/адрес, директивы пайплайнов
  (`ид→asbuilt`, `спецификации→ВОР`), `ignore` (что не индексировать);
- **тело (md)** — свободно: как работать с папкой; Совушка подмешивает его в контекст запросов
  по этому проекту (как CLAUDE.md).

Втыкается в существующее: `project_service` (привязка папки к объекту `les_projects`/links),
досье. 0 LLM на разбор (YAML+regex, ADR-11). Если файла нет — `generate_draft` собирает черновик
из скана папки (типы/шифры/даты), оператор правит.

Канон — `docs/ALGO-les-md.md`.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from backend.rag_config import rag_meta_db_path

logger = logging.getLogger(__name__)

LES_MD_NAMES = ("LES.md", "ЛЕС.md", "les.md", "лес.md", "Les.md")

# нормализация ключей frontmatter: RU/EN → канон
_KEY_ALIASES = {
    "project": "project", "проект": "project",
    "object": "object", "объект": "object",
    "stage": "stage", "стадия": "stage",
    "cipher": "cipher", "code": "cipher", "шифр": "cipher", "код": "cipher",
    "address": "address", "адрес": "address",
    "pipelines": "pipelines", "директивы": "pipelines", "пайплайны": "pipelines",
    "ignore": "ignore", "игнор": "ignore", "исключить": "ignore",
    "doc_types": "doc_types", "типы": "doc_types", "типы_документов": "doc_types",
}


# ── поиск + парс ──

def find_les_md(folder: str | Path) -> Optional[Path]:
    folder = Path(folder)
    if folder.is_file():
        return folder if folder.name in LES_MD_NAMES else None
    for name in LES_MD_NAMES:
        p = folder / name
        if p.exists():
            return p
    # регистронезависимо на всякий
    for child in folder.iterdir() if folder.is_dir() else []:
        if child.is_file() and child.name.lower() in {n.lower() for n in LES_MD_NAMES}:
            return child
    return None


def parse_les_md(text: str) -> tuple[dict[str, Any], str]:
    """Текст LES.md → (frontmatter-словарь канонизированный, тело-markdown)."""
    fm: dict[str, Any] = {}
    body = text or ""
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", text or "", re.DOTALL)
    if m:
        import yaml
        try:
            raw = yaml.safe_load(m.group(1)) or {}
            if isinstance(raw, dict):
                fm = raw
        except yaml.YAMLError as err:
            logger.warning("[LES.md] YAML frontmatter не распарсился: %s", err)
        body = m.group(2)
    return _canon(fm), body.strip()


def _canon(fm: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in fm.items():
        out[_KEY_ALIASES.get(str(k).strip().lower(), str(k).strip().lower())] = v
    return out


# ── хранилище контекста (привязка к проекту) ──

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_md_context (
            project_id INTEGER PRIMARY KEY,
            source_path TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            body TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        )
        """
    )
    return conn


def _store_context(project_id: int, source_path: str, meta: dict[str, Any], body: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO les_md_context(project_id, source_path, meta_json, body, updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET "
            "source_path=excluded.source_path, meta_json=excluded.meta_json, "
            "body=excluded.body, updated_at=excluded.updated_at",
            (int(project_id), source_path, json.dumps(meta, ensure_ascii=False), body, time.time()),
        )
        conn.commit()


def context_for_chat(project_id: int, *, max_chars: int = 1500) -> str:
    """Блок контекста LES.md для промпта по проекту ('' если нет). Всегда для in-project."""
    if not project_id:
        return ""
    with _connect() as conn:
        row = conn.execute(
            "SELECT meta_json, body FROM les_md_context WHERE project_id=?", (project_id,)
        ).fetchone()
    if not row:
        return ""
    meta = {}
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        pass
    head_bits = [f"{k}: {v}" for k in ("object", "stage", "cipher", "address") if (v := meta.get(k))]
    parts = ["[LES.md — контекст папки/проекта]"]
    if head_bits:
        parts.append("; ".join(str(b) for b in head_bits))
    if row["body"]:
        parts.append(row["body"])
    block = "\n".join(parts)
    return block[:max_chars]


# ── привязка к проекту ──

def read_and_bind(folder: str | Path, *, write_draft: bool = False,
                  enrich: bool = False) -> dict[str, Any]:
    """Найти/прочитать LES.md в папке → привязать к проекту + сохранить контекст.

    Нет файла и write_draft=True → ЛЕС сам собирает заполненный LES.md (auto-init). `enrich`
    (best-effort LLM) дочитывает якорные доки и заполняет пустые поля (адрес/объект/стадия).
    """
    from proxy.services import project_service as ps

    folder = Path(folder)
    path = find_les_md(folder)
    drafted = False
    if path is None:
        if not write_draft:
            return {"found": False, "folder": str(folder),
                    "hint": "LES.md не найден — могу собрать сам (write_draft=true)"}
        path = folder / "LES.md"
        path.write_text(generate_draft(folder), encoding="utf-8")
        drafted = True

    meta, body = parse_les_md(path.read_text(encoding="utf-8", errors="ignore"))

    if enrich:
        filled = enrich_blanks(folder, meta)
        if filled:
            meta.update(filled)
            _patch_frontmatter(path, filled)

    # find-or-create проект по имени/объекту
    name = str(meta.get("project") or meta.get("object") or folder.name).strip()
    is_global = str(meta.get("project") or "").strip().lower() in ("global", "глобально", "вне", "")
    project_id = 0
    if name and not (is_global and not meta.get("object")):
        project = _find_or_create_project(ps, name, str(meta.get("cipher") or ""), str(meta.get("address") or ""))
        project_id = int(project["id"])
        ps.link_entity(project_id, "folder", str(folder.resolve()))
        _store_context(project_id, str(path), meta, body)

    return {
        "found": True, "drafted": drafted, "path": str(path),
        "project_id": project_id, "project": name if project_id else "global",
        "meta": meta, "body_chars": len(body),
        "pipelines": meta.get("pipelines") or {}, "ignore": meta.get("ignore") or [],
    }


def _find_or_create_project(ps, name: str, code: str, address: str) -> dict[str, Any]:
    for p in ps.list_projects(limit=200):
        if str(p.get("name", "")).strip().lower() == name.strip().lower():
            return p
    return ps.create_project(name, code=code, address=address)


# ── авто-инициализация: скан папки → ЛЕС сам выводит объект/стадии/системы/директивы ──

_CIPHER_RE = re.compile(r"\b([А-ЯA-Z]{2,5}[-_][А-ЯA-Z0-9-]{3,})\b")
_DATE_RE = re.compile(r"\b(\d{2}[.\-]\d{2}[.\-]\d{4})\b")
# стадии: токен → канон (ищем в именах верхнеуровневых подпапок)
_STAGE_TOKENS = {"ирд": "ИРД", "пд": "ПД", "рд": "РД", "ид": "ИД", "гэ": "ГЭ", "сдо": "СДО",
                 "исполнит": "ИД", "рабочая": "РД", "проектн": "ПД"}
# инженерные системы (для тела «о чём папка»)
_SYSTEMS = ("АУПС", "СОУЭ", "СКС", "ОВ", "ВК", "ЭОМ", "ТМ", "ГСВ", "АТМ", "АГСВ", "ТС", "КР", "АР",
            "КСБ", "АПС", "ЭО", "ВСС", "ДПР")


def _infer_object(folder: Path) -> str:
    """«00_Лесной 64_Котельная» → «Лесной 64 Котельная» (снять ведущий номер, _ → пробел)."""
    name = re.sub(r"^[\d]{1,3}[_\-.\s]+", "", folder.name)  # ведущий «00_»
    return re.sub(r"[_\s]+", " ", name).strip() or folder.name


def _scan(folder: Path):
    exts: dict[str, int] = {}
    ciphers: dict[str, int] = {}
    dates: list[str] = []
    systems: dict[str, int] = {}
    has_id = False
    has_spec = False
    for f in folder.rglob("*"):
        if not f.is_file() or f.name in LES_MD_NAMES:
            continue
        exts[f.suffix.lower()] = exts.get(f.suffix.lower(), 0) + 1
        low = f.name.lower()
        if f.suffix.lower() == ".pdf" and ("ид" in low or "исполнит" in low or "чек-лист" in low):
            has_id = True
        if "специф" in low:
            has_spec = True
        up = f.stem.upper()
        for s in _SYSTEMS:
            if f"_{s}" in up or f" {s}" in up or up.startswith(s):
                systems[s] = systems.get(s, 0) + 1
        for c in _CIPHER_RE.findall(f.stem):
            ciphers[c] = ciphers.get(c, 0) + 1
        d = _DATE_RE.search(f.stem)
        if d:
            dates.append(d.group(1).replace("-", "."))
    return exts, ciphers, dates, systems, has_id, has_spec


def _infer_stages(folder: Path) -> list[str]:
    stages: list[str] = []
    if not folder.is_dir():
        return stages
    for child in folder.iterdir():
        if not child.is_dir():
            continue
        low = child.name.lower()
        for tok, canon in _STAGE_TOKENS.items():
            if tok in low and canon not in stages:
                stages.append(canon)
    order = ["ИРД", "ПД", "ГЭ", "РД", "ИД", "СДО"]
    return sorted(stages, key=lambda s: order.index(s) if s in order else 99)


def generate_draft(folder: str | Path) -> str:
    """Скан папки → ЗАПОЛНЕННЫЙ LES.md: объект/стадии/шифр/системы/директивы выведены из папки.

    ЛЕС сам себя инициализирует в папке (как `/init` для CLAUDE.md). Руками — только правки.
    Адрес детерминированно не вывести → оставляем пустым (заполнит llm-обогащение по запросу).
    """
    folder = Path(folder)
    exts, ciphers, dates, systems, has_id, has_spec = _scan(folder)
    obj = _infer_object(folder)
    stages = _infer_stages(folder)
    stage_val = stages[0] if len(stages) == 1 else (", ".join(stages) if stages else "")
    top_ext = ", ".join(f"{e or '—'}×{n}" for e, n in sorted(exts.items(), key=lambda x: -x[1])[:8])
    top_cipher = sorted(ciphers.items(), key=lambda x: -x[1])[:5]
    top_sys = [s for s, _ in sorted(systems.items(), key=lambda x: -x[1])[:8]]

    lines = [
        "---",
        f"project: {obj}",
        f"object: {obj}",
        f"stage: {stage_val}",
        f"cipher: {top_cipher[0][0] if top_cipher else ''}",
        "address:          # ЛЕС не вывел из имён — скажи «разберись внимательно», прочту титул/договор",
        "pipelines:",
    ]
    if has_id:
        lines.append("  ид: asbuilt          # исполнительные/чек-листы → приёмка смонтированного объёма")
    if has_spec:
        lines.append("  спецификации: spec_to_bor")
    if not has_id and not has_spec:
        lines.append("  # (типовых директив не распознано)")
    lines += [
        "ignore:",
        "  - '*.bak'",
        "  - '*.dwl*'",
        "  - '*.log'",
        "  - '*.dwl2'",
        "---",
        f"# {obj}",
        "",
        "_Авто-инициализация ЛЕС из скана папки. Поправь, если что._",
        "",
        f"- Файлов по типам: {top_ext}",
    ]
    if stages:
        lines.append(f"- Стадии (по подпапкам): {', '.join(stages)}")
    if top_sys:
        lines.append(f"- Системы (по именам): {', '.join(top_sys)}")
    if top_cipher:
        lines.append("- Шифры: " + ", ".join(f"{c}×{n}" for c, n in top_cipher))
    if dates:
        def _key(d: str) -> str:
            p = d.split(".")
            return f"{p[2]}{p[1]}{p[0]}" if len(p) == 3 else d
        lines.append(f"- Даты: {min(dates, key=_key)} … {max(dates, key=_key)}")
    lines += [
        "",
        "## Как работать с папкой",
        "_Конвенции имён (этаж/система), что тянуть, на что не отвлекаться — допиши при желании._",
    ]
    return "\n".join(lines) + "\n"


# ── LLM-обогащение пустых полей (best-effort, opt-in «разберись внимательно») ──

_ANCHOR_HINTS = ("договор", "задание", "титул", "пояснит", "общие данные", "обложка", "решение")
_ENRICH_KEYS = ("object", "stage", "address")


def _anchor_docs(folder: Path, limit: int = 3) -> list[Path]:
    """Якорные документы для извлечения метаданных объекта (договор/задание/титул…)."""
    cands = [p for p in folder.rglob("*")
             if p.is_file() and p.suffix.lower() in (".pdf", ".docx", ".doc")]
    hinted = [p for p in cands if any(h in p.name.lower() for h in _ANCHOR_HINTS)]
    pick = hinted[:limit] or sorted(cands, key=lambda p: p.stat().st_size)[:limit]
    return pick


def enrich_blanks(folder: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """Дочитать якорные доки → заполнить пустые object/stage/address. Пусто при любой осечке."""
    blanks = [k for k in _ENRICH_KEYS if not str(meta.get(k) or "").strip()]
    if not blanks:
        return {}
    try:
        from backend.converter import convert_to_markdown
    except Exception:  # noqa: BLE001
        return {}
    excerpts = []
    for p in _anchor_docs(folder):
        try:
            txt = convert_to_markdown(p) or ""
        except Exception:  # noqa: BLE001
            txt = ""
        if txt.strip():
            excerpts.append(f"### {p.name}\n{txt[:2500]}")
    if not excerpts:
        return {}
    prompt = (
        "По фрагментам проектных документов заполни поля об объекте. "
        f"Верни ТОЛЬКО JSON с ключами {blanks} (что не уверен — пустая строка). "
        "object — название объекта, stage — стадия (ИРД/ПД/РД/ИД), address — адрес.\n\n"
        + "\n\n".join(excerpts)
    )
    raw = _llm_text(prompt)
    try:
        import json as _json
        data = _json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except (ValueError, TypeError):
        return {}
    out = {k: str(data[k]).strip() for k in blanks if isinstance(data, dict) and str(data.get(k) or "").strip()}
    if out:
        logger.info("[LES.md] enrich заполнил: %s", ", ".join(out))
    return out


def _llm_text(prompt: str, *, max_tokens: int = 400) -> str:
    """Минимальный текстовый вызов LLM (OpenAI-совместимый, облако proxyapi). Best-effort."""
    import os

    import httpx

    base = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1")
    if not base or not key:
        return ""
    url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    try:
        resp = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, timeout=60, json={
            "model": model, "temperature": 0.0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        })
        resp.raise_for_status()
        return str(resp.json().get("choices", [{}])[0].get("message", {}).get("content", "") or "")
    except Exception as err:  # noqa: BLE001
        logger.warning("[LES.md] enrich LLM недоступен: %s", err)
        return ""


def _patch_frontmatter(path: Path, fields: dict[str, Any]) -> None:
    """Точечно обновить значения ключей в YAML-frontmatter файла (object/stage/address)."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for key, val in fields.items():
        text = re.sub(rf"(?m)^({re.escape(key)}:).*$", rf"\1 {val}", text, count=1)
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass
