"""Ц14, Ярус 3 — action-сервис ЛЕС: инструменты ДЕЙСТВИЯ (меняют состояние).

Compute-инструменты ЛЕС (les_lsr_assemble/les_bor/...) только СЧИТАЮТ — отдают числа.
Этот сервис добавляет тонкий слой ДЕЙСТВИЯ: собранную смету → сохранить как документ
в проект; запись о работе → дописать в журнал полевых объёмов. Действия композятся
с compute-инструментами (assemble → save). 0 LLM (ADR-11): сохранение/запись — это
детерминированный рендер/INSERT поверх уже посчитанных данных.

Безопасность (требование Яруса 3):
  • явность — путь сохранения уникален по таймстампу; вслепую не перезаписываем;
  • append/create, не overwrite — журнал дописывает запись, документ создаётся новым файлом;
  • идемпотентность журнала — опциональный idem_key защищает от дублей при ретраях;
  • валидация входа — пустые/битые позиции отсекаются до записи;
  • локальный путь — пишем в storage/projects/<id>/smeta, без сети.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

PROJECTS_ROOT = Path("storage/projects")

# Формы-документы, в которые умеем разложить собранную смету (бланк ВОР/ЛСР).
_SMETA_FORMS = {"vor", "smeta_lsr"}


def _projects_root() -> Path:
    import os

    return Path(os.getenv("LES_PROJECTS_DIR", str(PROJECTS_ROOT)))


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _fmt_qty(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


# ── 1. les_smeta_save: собранная смета → документ (ВОР/ЛСР) в проект ──

def _smeta_rows(assembled: dict[str, Any]) -> list[list[str]]:
    """Позиции собранной сметы → строки бланка (ВОР-колонки + строка ИТОГО).

    Колонки ВОР: № п/п | Наименование работ | Ед. изм. | Количество | Обоснование | Примечание.
    «Всего по позиции» кладём в Примечание — числовой результат сборки виден в документе.
    """
    rows: list[list[str]] = []
    for i, pos in enumerate(assembled.get("positions") or [], 1):
        total = _f(pos.get("total"))
        rows.append([
            str(i),
            str(pos.get("name") or pos.get("code") or "—"),
            str(pos.get("unit") or ""),
            _fmt_qty(_f(pos.get("qty"))),
            str(pos.get("code") or ""),
            f"Всего: {total:.2f} ₽" if total else "",
        ])
    summary = assembled.get("summary") or {}
    grand = _f(summary.get("total"))
    if rows:
        rows.append(["", "ИТОГО по смете", "", "", "", f"{grand:.2f} ₽"])
    return rows


def save_smeta(
    assembled: dict[str, Any],
    project_id: int,
    *,
    form_id: str = "vor",
    fmt: str = "xlsx",
    doc_code: str = "",
    link: bool = True,
) -> dict[str, Any]:
    """Собранную смету (выход les_lsr_assemble) → документ ВОР/ЛСР в storage проекта.

    assembled — словарь с ключами positions[] и summary{} (как отдаёт assemble).
    Создаёт НОВЫЙ файл (не перезаписывает) под storage/projects/<id>/smeta и,
    если link=True и проект существует, регистрирует его как привязку проекта.
    """
    from proxy.services import forms_service

    if not isinstance(assembled, dict):
        raise ValueError("assembled должен быть словарём (выход les_lsr_assemble)")
    positions = assembled.get("positions") or []
    if not positions:
        raise ValueError("В смете нет позиций — нечего сохранять")
    if form_id not in _SMETA_FORMS:
        raise ValueError(f"form_id: {sorted(_SMETA_FORMS)}")
    if fmt not in ("xlsx", "docx"):
        raise ValueError("fmt: xlsx|docx")
    if int(project_id) <= 0:
        raise ValueError("project_id должен быть положительным (документ пишется в проект)")

    # Бланк + резолв шапки из данных объекта; строки заменяем на позиции сметы.
    resolved = forms_service.resolve_fields(
        form_id, project_id=project_id, manual={"doc_code": doc_code} if doc_code else None
    )
    if resolved is None:
        raise ValueError(f"Форма {form_id!r} не найдена")
    if resolved.get("columns"):
        resolved["rows"] = _smeta_rows(assembled)

    out_dir = _projects_root() / str(int(project_id)) / "smeta"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    # Имя уникально по таймстампу; если файл уже есть (тот же момент) — суффикс,
    # чтобы НИКОГДА не перезаписать существующий документ вслепую.
    out_path = out_dir / f"{form_id}_{int(project_id)}_{stamp}.{fmt}"
    n = 1
    while out_path.exists():
        out_path = out_dir / f"{form_id}_{int(project_id)}_{stamp}_{n}.{fmt}"
        n += 1

    descriptor = forms_service.load_descriptor(form_id) or {}
    tmpl = (descriptor.get("templates") or {}).get(fmt)
    tmpl_path = Path(tmpl) if tmpl else None
    if fmt == "xlsx":
        forms_service.render_xlsx(resolved, out_path, tmpl_path)
    else:
        forms_service.render_docx(resolved, out_path, tmpl_path)

    linked = False
    if link:
        try:
            from proxy.services import project_service

            if project_service.get_project(int(project_id)) is not None:
                project_service.link_entity(int(project_id), "folder", str(out_path))
                linked = True
        except Exception:
            linked = False  # привязка — best-effort; документ уже сохранён

    summary = assembled.get("summary") or {}
    return {
        "ok": True,
        "operation": "smeta_save",
        "form_id": form_id,
        "fmt": fmt,
        "project_id": int(project_id),
        "path": str(out_path),
        "positions": len(positions),
        "total": _f(summary.get("total")),
        "linked": linked,
    }


# ── 2. les_journal_append: запись о работе → журнал (pending) ──

def journal_append(
    position: str,
    volume: float,
    unit: str = "",
    *,
    project_id: int = 0,
    entry_date: str = "",
    zahvatka: str = "",
    author: str = "",
    notes: str = "",
    idem_key: str = "",
) -> dict[str, Any]:
    """Добавить запись (вид работ + объём + дата) в журнал полевых объёмов как PENDING.

    pending (а не confirmed) — как приёмка ИД: записи из инструмента ждут подтверждения
    человеком W8.3, в отчёты/чат идут только confirmed. idem_key — защита от дублей при
    ретраях: если запись с таким ключом уже есть, возвращаем её, не создавая новую.
    """
    from proxy.services import field_intake_service as fis

    position = (position or "").strip()
    if not position:
        raise ValueError("Пустой вид работ (position)")
    vol = _f(volume)
    if vol <= 0:
        raise ValueError(f"Объём должен быть > 0 (получено {volume!r})")

    idem_key = (idem_key or "").strip()
    note_full = notes.strip()
    tag = f"[idem:{idem_key}]" if idem_key else ""
    if tag:
        note_full = f"{tag} {note_full}".strip()

    # Идемпотентность: ищем уже существующую pending-запись с этим ключом.
    if idem_key:
        existing = fis.list_entries(
            status="pending",
            position=position,
            project_id=int(project_id) if project_id else None,
            limit=500,
        )
        for e in existing:
            if tag in (e.get("notes") or ""):
                return {
                    "ok": True,
                    "operation": "journal_append",
                    "status": "pending",
                    "entry_id": e["id"],
                    "idempotent": True,
                    "note": "запись с этим idem_key уже есть — дубль не создан",
                }

    entry = fis.create_entry(
        position,
        vol,
        unit.strip(),
        entry_date=entry_date.strip(),
        zahvatka=zahvatka.strip(),
        author=author.strip(),
        status="pending",
        notes=note_full,
        project_id=int(project_id),
    )
    return {
        "ok": True,
        "operation": "journal_append",
        "status": "pending",
        "entry_id": entry["id"],
        "position": position,
        "volume": vol,
        "unit": unit.strip(),
        "zahvatka": zahvatka.strip(),
        "project_id": int(project_id),
        "idempotent": False,
        "note": "запись pending — подтвердите (W8.3), чтобы попала в отчёты",
    }
