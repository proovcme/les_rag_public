"""
pdf_layout.py — layout-aware извлечение PDF (Ц11, ADR-5).

ЗАЧЕМ. Штатный `page.get_text()` склеивает многоколоночные листы и таблицы в
«простыню»: порядок чтения ломается, табличные данные превращаются в кашу.
Этот модуль восстанавливает СТРУКТУРУ перед чанкингом:

  • блоки сортируются по X-кластерам (колонки) → внутри колонки по Y (порядок чтения);
  • заголовки/абзацы отдаются как обычный текст;
  • ТАБЛИЦЫ (`page.find_tables()` — по линиям/выравниванию) → markdown PIPE-таблица
    (`| .. | .. |`). Регион таблицы вырезается из текстового потока, чтобы не было
    дублей «текст + таблица».

СТЫКОВКА С Ц9 (table_appendix_service). Ц9 поднимает табличные приложения норм,
опознавая чанк как таблицу по плотности разделителей `|` (>= LES_TABLE_APPENDIX_MIN_PIPES).
Поэтому таблицы здесь отдаются именно как markdown-pipe — тогда они и индексируются
структурно (type=markdown), и достаются ретривом Ц9.

СТРОГО АДДИТИВНО. Модуль ничего не индексирует и не меняет чанкинг/эмбеддинг — он
лишь возвращает текст с сохранённой структурой. Встройка в converter._parse_pdf за
флагом LES_LAYOUT_PDF с тихим fallback на штатный путь при любом сбое.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Флаг включения. Дефолт on — но встройка обёрнута try/except + проверкой длины,
# так что пустой/сбойный результат тихо откатывается на штатный pymupdf-путь.
_FLAG_ENV = "LES_LAYOUT_PDF"
_FLAG_DEFAULT = "on"

# Минимальная горизонтальная щель (в долях ширины страницы), считаемая границей
# колонок. Подобрано так, чтобы обычный межсловный/межабзацный отступ не делил текст.
_COLUMN_GAP_RATIO = float(os.getenv("LES_LAYOUT_COLUMN_GAP_RATIO", "0.06"))

# Таблицы меньше этого числа строк/столбцов считаем ложными срабатываниями
# (рамка/одиночная ячейка) и НЕ вырезаем из текста — пусть идут как обычный текст.
_MIN_TABLE_ROWS = int(os.getenv("LES_LAYOUT_MIN_TABLE_ROWS", "2"))
_MIN_TABLE_COLS = int(os.getenv("LES_LAYOUT_MIN_TABLE_COLS", "2"))


def layout_pdf_enabled() -> bool:
    return os.getenv(_FLAG_ENV, _FLAG_DEFAULT).strip().lower() in ("1", "true", "yes", "on")


def _bbox_overlaps(a: tuple, b: tuple, tol: float = 2.0) -> bool:
    """Пересекаются ли два bbox (x0,y0,x1,y1) с небольшим допуском."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 <= bx0 + tol or bx1 <= ax0 + tol or ay1 <= by0 + tol or by1 <= ay0 + tol)


def _block_text(block: dict) -> str:
    """Склеивает текст блока из dict-структуры pymupdf, сохраняя переносы строк."""
    lines_out = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        text = "".join(span.get("text", "") for span in spans)
        if text.strip():
            lines_out.append(text)
    return "\n".join(lines_out)


def _cluster_columns(blocks: list[dict], page_width: float) -> list[list[dict]]:
    """Группирует текстовые блоки в колонки по X, возвращает колонки слева-направо.

    Алгоритм: сортируем блоки по левому краю; начинаем новую колонку, когда левый
    край блока отстоит от правого края текущей колонки больше, чем на порог-щель.
    Это грубая, но устойчивая эвристика для 1-3 колоночных листов (нормы/сметы).
    """
    if not blocks:
        return []
    gap = max(20.0, page_width * _COLUMN_GAP_RATIO)
    by_x = sorted(blocks, key=lambda b: b["bbox"][0])

    columns: list[dict] = []  # каждая: {"x0","x1": края, "blocks": [...]}
    for blk in by_x:
        x0, _, x1, _ = blk["bbox"]
        placed = False
        for col in columns:
            # Блок принадлежит колонке, если его левый край не дальше gap от её правого края.
            if x0 <= col["x1"] + gap:
                col["blocks"].append(blk)
                col["x1"] = max(col["x1"], x1)
                col["x0"] = min(col["x0"], x0)
                placed = True
                break
        if not placed:
            columns.append({"x0": x0, "x1": x1, "blocks": [blk]})

    columns.sort(key=lambda c: c["x0"])
    # Внутри колонки — порядок чтения сверху вниз.
    return [sorted(c["blocks"], key=lambda b: b["bbox"][1]) for c in columns]


def _table_to_markdown(table) -> Optional[str]:
    """find_tables → markdown PIPE-таблица. Чистим пустые/дублирующие строки и колонки."""
    try:
        rows = table.extract()
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None

    # Нормализуем ячейки: None → '', схлопываем пробелы/переводы строк.
    norm = [[(" ".join(str(c).split()) if c is not None else "") for c in row] for row in rows]

    # Выкидываем полностью пустые строки.
    norm = [r for r in norm if any(cell for cell in r)]
    if len(norm) < _MIN_TABLE_ROWS:
        return None

    width = max(len(r) for r in norm)
    if width < _MIN_TABLE_COLS:
        return None
    norm = [r + [""] * (width - len(r)) for r in norm]

    # Выкидываем полностью пустые колонки (частый артефакт пере-сегментации find_tables).
    keep = [j for j in range(width) if any(r[j] for r in norm)]
    if len(keep) < _MIN_TABLE_COLS:
        return None
    norm = [[r[j] for j in keep] for r in norm]
    width = len(keep)

    # Схлопываем строки, где все непустые ячейки одинаковы (артефакт «слитого» заголовка
    # на всю ширину) — оставляем одну содержательную ячейку в первой колонке.
    def _dedup(row: list[str]) -> list[str]:
        nonempty = [c for c in row if c]
        if len(nonempty) > 1 and len(set(nonempty)) == 1:
            return [nonempty[0]] + [""] * (width - 1)
        return row

    norm = [_dedup(r) for r in norm]

    # Разреженная таблица (find_tables нередко накрывает грид-сеткой весь лист нормы:
    # реальных данных мало, остальное — пустые ячейки). Сжимаем каждую строку до её
    # непустых ячеек, выравнивая по максимальной ширине — данные сохраняются, а море
    # `|  |  |` уходит. Ширину после сжатия пересчитываем.
    cells_total = width * len(norm)
    nonempty_total = sum(1 for r in norm for c in r if c)
    if cells_total and nonempty_total / cells_total < 0.5:
        squeezed = [[c for c in r if c] for r in norm]
        squeezed = [r for r in squeezed if r]
        if len(squeezed) < _MIN_TABLE_ROWS:
            return None
        width = max(len(r) for r in squeezed)
        if width < _MIN_TABLE_COLS:
            return None
        norm = [r + [""] * (width - len(r)) for r in squeezed]
        # Повторно дропаем пустые колонки, появившиеся от выравнивания по max-ширине.
        keep2 = [j for j in range(width) if any(r[j] for r in norm)]
        if len(keep2) < _MIN_TABLE_COLS:
            return None
        norm = [[r[j] for j in keep2] for r in norm]
        width = len(keep2)

    header = norm[0]
    body = norm[1:]
    sep = ["---"] * width

    def _fmt(row: list[str]) -> str:
        cells = [c.replace("|", "\\|") for c in row]
        return "| " + " | ".join(cells) + " |"

    md_lines = [_fmt(header), _fmt(sep)] + [_fmt(r) for r in body]
    return "\n".join(md_lines)


def _extract_tables(page) -> list[tuple[tuple, str]]:
    """Возвращает [(bbox, markdown_pipe), ...] для валидных таблиц страницы."""
    out: list[tuple[tuple, str]] = []
    try:
        finder = page.find_tables()
    except Exception as e:  # noqa: BLE001 — старый pymupdf без find_tables
        logger.debug("[LAYOUT] find_tables недоступен/упал: %s", e)
        return out
    for table in getattr(finder, "tables", []):
        md = _table_to_markdown(table)
        if not md:
            continue
        try:
            bbox = tuple(table.bbox)
        except Exception:  # noqa: BLE001
            continue
        out.append((bbox, md))
    return out


def _render_page(page) -> str:
    """Один лист → структурный текст: колонки в порядке чтения + pipe-таблицы."""
    tables = _extract_tables(page)
    table_bboxes = [bb for bb, _ in tables]

    data = page.get_text("dict")
    text_blocks: list[dict] = []
    page_width = float(page.rect.width) or 595.0
    for blk in data.get("blocks", []):
        if blk.get("type") != 0:  # 0 = текст, 1 = картинка
            continue
        bbox = blk.get("bbox")
        if not bbox:
            continue
        # Блоки внутри таблиц не дублируем текстом — они уйдут pipe-таблицей.
        if any(_bbox_overlaps(bbox, tb) for tb in table_bboxes):
            continue
        if not _block_text(blk).strip():
            continue
        text_blocks.append(blk)

    columns = _cluster_columns(text_blocks, page_width)

    # Собираем поток: текстовые блоки колонка за колонкой; затем таблицы по их
    # вертикальному положению. Для норм/смет таблица обычно занимает основной блок
    # листа, текст — шапка/состав работ сверху.
    parts: list[str] = []
    for col in columns:
        chunk = "\n\n".join(_block_text(b) for b in col if _block_text(b).strip())
        if chunk.strip():
            parts.append(chunk)

    for _bbox, md in sorted(tables, key=lambda t: t[0][1]):
        parts.append(md)

    return "\n\n".join(p for p in parts if p.strip())


def extract_layout_markdown(path: Path, pages: Optional[list[int]] = None) -> str:
    """PDF → текст с сохранённой структурой (порядок чтения + markdown pipe-таблицы).

    Бросает исключение при отсутствии fitz/ошибке открытия — вызывающая сторона
    (converter._parse_pdf) ловит и откатывается на штатный путь.
    """
    import fitz

    out_pages: list[str] = []
    with fitz.open(str(path)) as doc:
        page_count = doc.page_count
        idxs = pages if pages is not None else range(page_count)
        for i in idxs:
            if i < 0 or i >= page_count:
                continue
            try:
                rendered = _render_page(doc[i])
            except Exception as e:  # noqa: BLE001 — один битый лист не должен ронять весь PDF
                logger.warning("[LAYOUT] стр. %s %s: %s — пропуск листа", i + 1, path.name, e)
                rendered = ""
            if rendered.strip():
                out_pages.append(rendered)
    return "\n\n".join(out_pages)
