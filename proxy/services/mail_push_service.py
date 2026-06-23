"""Приём письма из Outlook-плагина → классификация вложений → маршрут в пайплайны ЛЕС. 0 LLM.

Принцип [[local-bases-untrusted-channel]]: плагин шлёт письмо в ЛОКАЛЬНЫЙ ЛЕС (не в облако).
Эндпоинт `POST /api/mail/push` (mail.py) принимает {subject, from, date, body, attachments[]} и зовёт
`route_push`: сохраняет вложения, классифицирует по имени/расширению (детерминированно), КП → КАЦ
(`kac_pdf_service`, Ц7), прочее → план регистрации в RAG/приёмку. Возвращает сводку «что куда уехало».

Классификация — эвристика по имени/расширению (без LLM): КП (коммерческое предложение/прайс/счёт),
смета/ВОР/ЛСР, скан ИД (изображение/акт), прочий документ.
"""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from typing import Any

# Подсказки-стемы по имени файла. Сопоставление ТОКЕННОЕ (слово startswith стем), а не подстрочное —
# иначе «вор» ловит «догоВОР». Имя бьётся на слова по не-буквам.
_KP_HINTS = ("кп", "коммерч", "предложен", "прайс", "счёт", "счет", "quotation", "offer", "price")
_ESTIMATE_HINTS = ("смет", "вор", "лср", "ксз", "кс2", "кс3", "локальн")
_SCAN_HINTS = ("скан", "акт", "исполнит", "обмер")
_IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".heic"}
_XLS_EXT = {".xlsx", ".xls", ".xlsm"}


def _has_hint(name_lower: str, hints: tuple[str, ...]) -> bool:
    tokens = [t for t in re.split(r"[^0-9a-zа-яё]+", name_lower) if t]
    return any(any(t.startswith(h) for t in tokens) for h in hints)

# Куда едет каждый класс (для сводки пользователю).
_DEST = {
    "kp": "КАЦ (конъюнктурный анализ цен)",
    "estimate": "RAG · смета/ВОР",
    "scan": "приёмка ИД (очередь, pending)",
    "doc": "RAG · документ",
}


def classify_attachment(name: str) -> str:
    """Имя файла → класс: kp | estimate | scan | doc. Детерминированно, по имени+расширению."""
    nl = (name or "").lower()
    ext = Path(nl).suffix
    if ext == ".pdf" and _has_hint(nl, _KP_HINTS):
        return "kp"
    if _has_hint(nl, _ESTIMATE_HINTS) or ext in _XLS_EXT:
        return "estimate"
    if ext in _IMG_EXT or _has_hint(nl, _SCAN_HINTS):
        return "scan"
    return "doc"


def _safe_name(name: str) -> str:
    base = re.sub(r"[^\w.\-]+", "_", (name or "").strip()) or "attachment"
    return base[:120]


def save_attachments(attachments: list[dict[str, Any]], dest: Path) -> list[dict[str, Any]]:
    """Декодировать base64-вложения в файлы под `dest`. Бьётый base64 → пустой файл (не падаем)."""
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    used: set[str] = set()
    for a in attachments or []:
        orig = a.get("name") or "attachment"
        fname = _safe_name(orig)
        # не перезатирать одноимённые вложения
        stem, suf = Path(fname).stem, Path(fname).suffix
        cand, i = fname, 1
        while cand in used:
            cand, i = f"{stem}_{i}{suf}", i + 1
        used.add(cand)
        try:
            data = base64.b64decode(a.get("content_b64") or "", validate=False)
        except (binascii.Error, ValueError):
            data = b""
        p = dest / cand
        p.write_bytes(data)
        saved.append({"name": orig, "path": str(p), "kind": classify_attachment(orig), "size": len(data)})
    return saved


def route_push(saved: list[dict[str, Any]], *, min_suppliers: int = 3) -> dict[str, Any]:
    """План маршрутизации сохранённых вложений + КАЦ по КП (если есть). 0 LLM."""
    routed = [{"name": s["name"], "kind": s["kind"], "destination": _DEST.get(s["kind"], _DEST["doc"])}
              for s in saved]
    kp_paths = [s["path"] for s in saved if s["kind"] == "kp"]
    kac: dict[str, Any] | None = None
    if kp_paths:
        try:
            from proxy.services.kac_pdf_service import extract_and_analyze
            kac = extract_and_analyze(kp_paths, min_suppliers=min_suppliers)
        except Exception as exc:  # noqa: BLE001 — КАЦ best-effort, маршрут не должен падать
            kac = {"ok": False, "error": str(exc)}
    return {"routed": routed, "kac": kac, "kp_count": len(kp_paths),
            "to_rag": [s for s in saved if s["kind"] in ("estimate", "doc")],
            "to_intake": [s for s in saved if s["kind"] == "scan"]}


def email_as_text(subject: str, sender: str, date: str, body: str) -> str:
    """Письмо → текстовый документ для RAG (тема/отправитель/дата в шапке)."""
    head = f"Тема: {subject or ''}\nОт: {sender or ''}\nДата: {date or ''}\n\n"
    return head + (body or "")
