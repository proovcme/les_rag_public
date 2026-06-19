"""asbuilt_intake_service.py — приёмка смонтированного объёма из исполнительных схем (сканов).

Конвейер: ``render → rotate → vision-JSON(строки) → parse/validate → журнал → свод``.
Детерминировано ВСЁ, кроме одного vision-вызова (``asbuilt_ocr.vision_ocr_tables``): модель
переписывает ячейки таблиц, а числа/типизацию/фильтрацию/свод считает код (ADR-11).

Контекст (этаж/система/линия) детерминированно выводится из имени файла; строки падают в
журнал объёмов (`field_intake_service.create_entry`) c тегом ``zahvatka = floor/system/line`` —
чтобы существующий свод `/api/field/summary` и `table_query` резали по этаж×система.

Канон логики — `docs/ALGO-asbuilt-intake.md`. См. также CODE_MAP / SKILL.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from proxy.services.asbuilt_ocr import (
    OcrEngine,
    parse_rows_json,
    resolve_engine,
    vision_locate_tables,
    vision_ocr_tables,
)

logger = logging.getLogger(__name__)

ROTATE_CANDIDATES = (90, 0, 270, 180)  # эти листы повёрнуты на 90°: пробуем его первым
_SUPPORTED = {".pdf"}

# подзаголовки секций спецификации — не объём, в журнал не пишем
_SECTION_RE = re.compile(r"кабельн\w*\s+лини|в\s+состав|^\s*$", re.IGNORECASE)


# ── 1. Контекст из имени файла (детерм.) ──

_SYSTEMS = ("АУПС", "СОУЭ", "СКС", "ОВ", "ВК", "ЭОМ", "АД", "СС")
_FNAME_RE = re.compile(
    r"(?P<building>Б\d+).*?(?P<system>" + "|".join(_SYSTEMS) + r").*?(?P<floor>L\d+|Э\d+)"
    r"(?:.*?_(?P<line>[А-ЯA-Z]{2,3})_)?",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"(\d{2}[.\-]\d{2}[.\-]\d{4})")


def parse_asbuilt_filename(name: str) -> dict[str, str]:
    """`МФЗ_Б4_АУПС_L5_ОП_ОКЛ_13.06.2023` → {building, system, floor, line, date}.

    Мягкая деградация: что не распозналось — пустая строка (исходное имя осядет в notes).
    """
    stem = Path(name).stem
    out = {"building": "", "system": "", "floor": "", "line": "", "date": ""}
    m = _FNAME_RE.search(stem)
    if m:
        out["building"] = (m.group("building") or "").upper()
        out["system"] = (m.group("system") or "").upper()
        out["floor"] = (m.group("floor") or "").upper()
        out["line"] = (m.group("line") or "").upper()
    d = _DATE_RE.search(stem)
    if d:
        out["date"] = d.group(1).replace("-", ".")
    return out


def zahvatka_tag(ctx: dict[str, str]) -> str:
    """Тег для журнала: floor/system/line (пустые сегменты опускаем)."""
    return "/".join(s for s in (ctx.get("floor"), ctx.get("system"), ctx.get("line")) if s)


# ── 2. Нормализация чисел / строк (детерм.) ──

def _num(value: Any) -> Optional[float]:
    """«1003», «502,5», «1 003» → float; иначе None (заголовки/пустые/мусор)."""
    if value is None:
        return None
    s = str(value).strip().replace(" ", " ").replace(" ", "").replace(",", ".")
    if not s or not re.fullmatch(r"\d+(?:\.\d+)?", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class Row:
    table: str
    no: str
    name: str
    type: str
    unit: str
    qty: Optional[float]
    raw_qty: str


def _to_rows(raw_rows: list[dict]) -> list[Row]:
    rows: list[Row] = []
    for r in raw_rows:
        name = str(r.get("name", "")).strip()
        raw_qty = str(r.get("qty", "")).strip()
        rows.append(
            Row(
                table=str(r.get("table", "")).strip(),
                no=str(r.get("no", "")).strip(),
                name=name,
                type=str(r.get("type", "")).strip(),
                unit=str(r.get("unit", "")).strip(),
                qty=_num(raw_qty),
                raw_qty=raw_qty,
            )
        )
    return rows


def _is_kept(row: Row) -> bool:
    """В журнал идут только строки с положительным числовым кол-вом и непустым наименованием."""
    if not row.name or _SECTION_RE.search(row.name):
        return False
    return row.qty is not None and row.qty > 0


# ── 3. Рендер + авто-поворот + OCR ──

def _render_page(pdf_path: Path, dpi: int):
    from backend.ocr_parser import render_pdf_to_images

    images = render_pdf_to_images(pdf_path, dpi=dpi)
    return images


def _rotate(image, clockwise_deg: int):
    if clockwise_deg % 360 == 0:
        return image
    return image.rotate(-clockwise_deg, expand=True)  # PIL: + против часовой → -deg = по часовой


def _maybe_downscale(image, max_side: int):
    if max_side and max(image.size) > max_side:
        img = image.copy()
        img.thumbnail((max_side, max_side))
        return img
    return image


def _tiles(image, rows: int, cols: int, overlap: float):
    """Нарезать изображение на сетку rows×cols с перекрытием (доля). Yield (idx, crop)."""
    W, H = image.size
    tw, th = W / cols, H / rows
    ox, oy = tw * overlap, th * overlap
    idx = 0
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(c * tw - ox)); y0 = max(0, int(r * th - oy))
            x1 = min(W, int((c + 1) * tw + ox)); y1 = min(H, int((r + 1) * th + oy))
            idx += 1
            yield idx, image.crop((x0, y0, x1, y1))


def _row_key(r: Row) -> tuple:
    return (r.name.strip().lower(), r.type.strip().lower(), r.unit.strip().lower(), r.raw_qty.strip())


def _ocr_rows(image, eng: OcrEngine) -> list[Row]:
    raw = vision_ocr_tables(image, eng)
    return _to_rows(parse_rows_json(raw))


def _extract_tiled(page, angle: int, eng: OcrEngine, *, rows: int, cols: int,
                   overlap: float, max_side: int) -> list[Row]:
    """OCR по сетке фрагментов нативного разрешения + мерж с дедупом (overlap → дубли)."""
    img = _rotate(page, angle)
    merged: dict[tuple, Row] = {}
    for idx, tile in _tiles(img, rows, cols, overlap):
        tile = _maybe_downscale(tile, max_side)
        try:
            tile_rows = _ocr_rows(tile, eng)
        except Exception as err:  # noqa: BLE001 — один фрагмент не должен ронять лист
            logger.warning("[ASBUILT] фрагмент %d @%d°: %s", idx, angle, err)
            continue
        for r in tile_rows:
            if _is_kept(r):
                merged.setdefault(_row_key(r), r)
    return list(merged.values())


def _locate_and_read(page, angle: int, eng: OcrEngine, *, locate_side: int,
                     pad: float, max_side: int) -> list[Row]:
    """Стратегия «найди→прочитай»: bbox таблиц по уменьшенному листу → кроп нативного
    разрешения на каждую таблицу → OCR строк целиком (без обрезки строк и дублей перекрытия)."""
    img = _rotate(page, angle)
    W, H = img.size
    probe = _maybe_downscale(img, locate_side)
    try:
        boxes = vision_locate_tables(probe, eng)
    except Exception as err:  # noqa: BLE001
        logger.warning("[ASBUILT] locate @%d°: %s", angle, err)
        return []
    merged: dict[tuple, Row] = {}
    for b in boxes:
        x0, y0, x1, y1 = b["bbox"]
        # запас вокруг рамки + клип в границы листа
        x0 = max(0.0, min(x0, x1) - pad); y0 = max(0.0, min(y0, y1) - pad)
        x1 = min(1.0, max(x0, x1) + pad); y1 = min(1.0, max(y0, y1) + pad)
        crop = img.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
        if min(crop.size) < 40:
            continue
        crop = _maybe_downscale(crop, max_side)
        try:
            for r in _ocr_rows(crop, eng):
                if _is_kept(r):
                    merged.setdefault(_row_key(r), r)
        except Exception as err:  # noqa: BLE001
            logger.warning("[ASBUILT] read bbox %s @%d°: %s", b.get("title", ""), angle, err)
    logger.info("[ASBUILT] locate→read @%d°: %d таблиц → %d строк объёма", angle, len(boxes), len(merged))
    return list(merged.values())


def _detect_rotation(page, eng: OcrEngine, candidates: tuple[int, ...]) -> int:
    """Дешёвое определение ориентации: даунскейл-проба на лист, берём угол с макс. строками."""
    best_angle, best_n = candidates[0], -1
    for angle in candidates:
        probe = _maybe_downscale(_rotate(page, angle), 1500)
        try:
            n = len(_ocr_rows(probe, eng))
        except Exception:  # noqa: BLE001
            n = 0
        logger.info("[ASBUILT] проба поворота %d° → %d строк", angle, n)
        if n > best_n:
            best_angle, best_n = angle, n
        if n >= 2:  # достаточно уверенно — не тратим остальные пробы
            break
    return best_angle


@dataclass
class ExtractResult:
    pdf: str
    ctx: dict[str, str]
    rotation_used: Optional[int]
    engine: str
    kept: list[Row] = field(default_factory=list)
    skipped: list[Row] = field(default_factory=list)
    raw_count: int = 0
    error: str = ""


def extract_rows(
    pdf_path: str | Path,
    *,
    rotate: str | int = "auto",
    engine: str = "local",
    dpi: Optional[int] = None,
    max_side: Optional[int] = None,
    ocr_engine: Optional[OcrEngine] = None,
) -> ExtractResult:
    """Один PDF → строки таблиц смонтированного объёма (kept/skipped) + использованный поворот."""
    pdf_path = Path(pdf_path)
    ctx = parse_asbuilt_filename(pdf_path.name)
    res = ExtractResult(pdf=pdf_path.name, ctx=ctx, rotation_used=None, engine=engine)
    if pdf_path.suffix.lower() not in _SUPPORTED:
        res.error = f"неподдерживаемый формат: {pdf_path.suffix}"
        return res

    dpi = dpi or int(os.getenv("LES_ASBUILT_DPI", "200"))
    if max_side is None:
        max_side = int(os.getenv("LES_ASBUILT_MAX_SIDE", "0"))  # 0 = без даунскейла
    eng = ocr_engine or resolve_engine(engine)

    try:
        pages = _render_page(pdf_path, dpi)
    except Exception as err:  # noqa: BLE001 — рендер не должен ронять приёмку
        res.error = f"render: {err}"
        logger.error("[ASBUILT] рендер %s: %s", pdf_path.name, err)
        return res
    if not pages:
        res.error = "пустой PDF"
        return res

    trows, tcols = _tile_grid()
    overlap = float(os.getenv("LES_ASBUILT_TILE_OVERLAP", "0.12"))

    # берём первую страницу (исполнительная схема — 1 лист)
    page = pages[0]
    if isinstance(rotate, int) or (isinstance(rotate, str) and str(rotate).lstrip("-").isdigit()):
        angle = int(rotate)
    else:
        angle = _detect_rotation(page, eng, ROTATE_CANDIDATES)
    res.rotation_used = angle
    strategy = os.getenv("LES_ASBUILT_STRATEGY", "locate").strip().lower()

    try:
        if strategy == "locate":
            kept = _locate_and_read(
                page, angle, eng,
                locate_side=int(os.getenv("LES_ASBUILT_LOCATE_SIDE", "1600")),
                pad=float(os.getenv("LES_ASBUILT_LOCATE_PAD", "0.035")),
                max_side=max_side,
            )
            if not kept:  # локализация пуста → фолбэк на сетку
                logger.info("[ASBUILT] %s: locate пусто → фолбэк tiles", pdf_path.name)
                kept = _extract_tiled(page, angle, eng, rows=trows, cols=tcols, overlap=overlap, max_side=max_side)
        else:
            kept = _extract_tiled(page, angle, eng, rows=trows, cols=tcols, overlap=overlap, max_side=max_side)
    except Exception as err:  # noqa: BLE001
        res.error = f"ocr: {err}"
        logger.error("[ASBUILT] OCR %s @%d°: %s", pdf_path.name, angle, err)
        return res

    res.kept = kept
    res.raw_count = len(kept)
    logger.info("[ASBUILT] %s @%d° (%s) → %d строк объёма", pdf_path.name, angle, strategy, len(kept))
    if not res.kept and not res.error:
        res.error = "таблица смонтированного объёма не распознана"
    return res


def _tile_grid() -> tuple[int, int]:
    """LES_ASBUILT_TILES = 'RxC' (по умолчанию 3x3)."""
    spec = os.getenv("LES_ASBUILT_TILES", "3x3").lower().replace(" ", "")
    try:
        r, c = spec.split("x")
        return max(1, int(r)), max(1, int(c))
    except (ValueError, AttributeError):
        return 3, 3


# ── 4. Запись в журнал объёмов (переиспользуем field_intake_service) ──

def to_journal(
    result: ExtractResult,
    *,
    status: str = "pending",
    project_id: int = 0,
    author: str = "asbuilt-intake",
) -> list[dict[str, Any]]:
    """Каждую kept-строку → запись журнала. zahvatka=floor/system/line, status=pending (приёмка)."""
    from proxy.services.field_intake_service import create_entry

    tag = zahvatka_tag(result.ctx)
    date = result.ctx.get("date", "")
    created: list[dict[str, Any]] = []
    for row in result.kept:
        note_bits = [b for b in (row.type, f"ИД {date}" if date else "", "смонтировано") if b]
        created.append(
            create_entry(
                row.name,
                float(row.qty or 0),
                row.unit,
                zahvatka=tag,
                doc_id=result.pdf,
                author=author,
                status=status,
                notes="; ".join(note_bits),
                project_id=project_id,
            )
        )
    logger.info("[ASBUILT] %s → %d записей журнала (%s, тег %s)", result.pdf, len(created), status, tag)
    return created


# ── 5. Высокоуровневый прогон файла/папки ──

def iter_pdfs(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.suffix.lower() in _SUPPORTED)
    return [path] if path.suffix.lower() in _SUPPORTED else []


def process_path(
    path: str | Path,
    *,
    rotate: str | int = "auto",
    engine: str = "local",
    model: Optional[str] = None,
    write: bool = False,
    status: str = "pending",
    project_id: int = 0,
    dpi: Optional[int] = None,
    max_side: Optional[int] = None,
) -> dict[str, Any]:
    """Папка/файл → извлечение по всем PDF (+опц. запись в журнал) + плоский список строк/свод."""
    path = Path(path)
    pdfs = iter_pdfs(path)
    eng = resolve_engine(engine, model=model)
    files_out: list[dict[str, Any]] = []
    flat_rows: list[dict[str, Any]] = []
    written = 0
    for pdf in pdfs:
        res = extract_rows(pdf, rotate=rotate, engine=engine, dpi=dpi, max_side=max_side, ocr_engine=eng)
        if write and res.kept:
            written += len(to_journal(res, status=status, project_id=project_id))
        for r in res.kept:
            flat_rows.append({
                "pdf": res.pdf, "zahvatka": zahvatka_tag(res.ctx),
                "system": res.ctx.get("system", ""), "floor": res.ctx.get("floor", ""),
                "line": res.ctx.get("line", ""), "name": r.name, "type": r.type,
                "unit": r.unit, "qty": r.qty,
            })
        files_out.append({
            "pdf": res.pdf, "ctx": res.ctx, "rotation_used": res.rotation_used,
            "engine": res.engine, "kept": len(res.kept), "skipped": len(res.skipped),
            "raw_count": res.raw_count, "error": res.error,
        })
    return {
        "engine": eng.name, "model": eng.model,
        "files": files_out, "rows": flat_rows,
        "written": written, "status": status if write else None,
        "consolidation": consolidate(flat_rows),
    }


def consolidate(flat_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Свод по (system, name, unit): SUM(qty) — числа считает код (ADR-11)."""
    agg: dict[tuple, dict[str, Any]] = {}
    for r in flat_rows:
        key = (r.get("system", ""), r.get("name", ""), r.get("unit", ""))
        slot = agg.setdefault(key, {"system": key[0], "name": key[1], "unit": key[2], "total": 0.0, "rows": 0})
        slot["total"] += float(r.get("qty") or 0)
        slot["rows"] += 1
    return sorted(agg.values(), key=lambda x: (x["system"], x["name"], x["unit"]))
