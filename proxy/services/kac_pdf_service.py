"""КАЦ из PDF-КП: извлечение котировок {поставщик, материал, цена, ед.изм} из PDF
коммерческих предложений → кормим в детерминированное ядро ``kac_service.analyze_kac``.

Регламент (см. [[kac]]): для материалов вне ФГИС ЦС собирают ≥3 КП на материал и берут
экономичный вариант. Этот модуль — ИЗВЛЕЧЕНИЕ строк из PDF; анализ/выбор делает kac_service.

Стратегия (LLM-минимализм, ADR-11 — LLM последний инструмент):
  1. ТЕКСТОВЫЙ СЛОЙ. pdfplumber: сначала таблицы (extract_tables), потом — построчный текст
     с regex'ом по цене/ед.изм. Это покрывает «цифровые» КП (выгрузка из 1С/Excel→PDF).
  2. OCR-ФОЛБЭК для сканов (страница без текстового слоя). Зовём бинарь Tesseract+rus через
     backend.ocr_parser.TesseractOCRParser — он subprocess'ом ИЗОЛИРОВАН от proxy-venv
     (MLX/transformers не трогает). По распознанному тексту — те же regex'ы.
  3. LLM-фолбэк — ОПЦИОНАЛЬНО, за флагом ``use_llm`` (по умолчанию OFF). Для совсем грязных КП.

Поставщик: из шапки документа (ИНН/ООО/«поставщик:») или из имени файла (фолбэк).
Цена/ед.изм: regex по строке материала. Всё детерминированно, 0 LLM по умолчанию.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# --- Словари для распознавания (0 LLM) --------------------------------------

# Единицы измерения — от длинных к коротким (жадность regex).
_UNITS = [
    "тыс.шт", "тыс. шт", "пог.м", "пог. м", "п.м", "п. м", "м.п", "м.п.",
    "м2", "м²", "м3", "м³", "кв.м", "кв. м", "куб.м", "куб. м",
    "компл", "компл.", "уп", "уп.", "упак", "шт", "шт.", "кг", "т", "л",
    "м", "г", "рулон", "лист", "набор", "пара",
    # Латинские эквиваленты — выгрузки 1С/Excel→PDF иногда дают «m2», «sht».
    "m2", "m3", "sht", "kg", "pcs", "m",
]
# Трейлинг-граница исключает И буквы И цифры: «m» в «M150»/«М500» (марка) — не единица.
_UNIT_RE = re.compile(
    r"(?<![A-Za-zА-Яа-я0-9])(" + "|".join(re.escape(u) for u in _UNITS) + r")(?![A-Za-zА-Яа-я0-9])",
    re.IGNORECASE,
)

# Валюта.
_CURRENCY = {
    "руб": "RUB", "руб.": "RUB", "₽": "RUB", "rub": "RUB", "р.": "RUB",
    "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR",
}
# Граница (?<![A-Za-zА-Яа-я]) не даёт зацепить «rub» внутри слова (TRUBA → не валюта).
_CURRENCY_RE = re.compile(
    r"(?<![A-Za-zА-Яа-я])(₽|руб\.?|rub|usd|\$|eur|€)(?![A-Za-zА-Яа-я])", re.IGNORECASE)
# Цена-число: 1234,56 | 1234.56 | 1234 — целое с опц. дробной частью, БЕЗ внутренних
# пробелов в матче. Тысячный пробел-разделитель склеиваем в _find_price_in_text.
# Граница не даёт хвосту единицы (m2/м3) прилипнуть к началу цены.
_NUM_TOKEN = re.compile(r"(?<![\dA-Za-zА-Яа-я])\d+(?:[.,]\d+)?(?![\dA-Za-zА-Яа-я])")
# Группа с тысячными разделителями (пробел/неразрывный): 1 234 / 1 234 567,89.
# Левая граница не даёт «m2 410» слиться в «2 410».
_THOUSANDS = re.compile(r"(?<![\dA-Za-zА-Яа-я])\d{1,3}(?:[\u0020\u00a0]\d{3})+(?:[.,]\d+)?")

# Шапка с поставщиком.
_SUPPLIER_HINTS = re.compile(
    r"(?:поставщик|продавец|организация|компания|от\s+кого)\s*[:\-]?\s*(.+)",
    re.IGNORECASE,
)
_ORG_RE = re.compile(r'((?:ООО|ОАО|ЗАО|ПАО|АО|ИП)\s*[«"]?[^»"\n,;]{2,60})', re.IGNORECASE)

# Шумовые/служебные строки — не материалы (+ латинские транслит-эквиваленты).
_NOISE_RE = re.compile(
    r"^\s*(итого|всего|ндс|в\s+т\.?ч\.?\s+ндс|сумма|подпись|менеджер|тел\.?|"
    r"коммерческое\s+предложение|прайс|стр\.|дата|email|e-mail|"
    r"itogo|vsego|nds|summa|telefon|kommercheskoe|prays)",
    re.IGNORECASE,
)
# Строки-заголовки таблицы.
_HEADER_RE = re.compile(
    r"(наименование|материал|товар|цена|стоимость|ед\.?\s*изм|кол-?во|количество|поставщик)",
    re.IGNORECASE,
)


def _parse_price(token: str) -> Optional[float]:
    """'1 234,56' / '2 300' / '1234.56' → float. None если не цена."""
    if not token:
        return None
    t = token.strip().replace(" ", "").replace(" ", "")
    # И точка и запятая → запятая дробная, точка тысячная (рус. формат): 1.234,56
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    t = re.sub(r"[^\d.]", "", t)
    if not t or t == ".":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _find_price_in_text(text: str) -> Optional[float]:
    """Наибольшее «ценоподобное» число в строке (в КП цена обычно справа/крупная).

    Сначала ищем числа с тысячными разделителями (1 234,56) и «гасим» их в тексте,
    чтобы оставшийся скан одиночных групп не разрезал их и не склеивал хвост единицы.
    """
    candidates: list[float] = []
    rest = text
    for m in _THOUSANDS.finditer(text):
        val = _parse_price(m.group(0))
        if val is not None and val > 0:
            candidates.append(val)
        rest = rest.replace(m.group(0), " ")
    for m in _NUM_TOKEN.finditer(rest):
        val = _parse_price(m.group(0))
        if val is not None and val > 0:
            candidates.append(val)
    if not candidates:
        return None
    return max(candidates)


def _find_unit(text: str) -> str:
    m = _UNIT_RE.search(text)
    if not m:
        return ""
    u = m.group(1).lower().replace("²", "2").replace("³", "3").rstrip(".")
    return {"кв.м": "м2", "кв. м": "м2", "куб.м": "м3", "куб. м": "м3",
            "пог. м": "пог.м", "п. м": "п.м"}.get(u, u)


def _find_currency(text: str) -> str:
    m = _CURRENCY_RE.search(text)
    if not m:
        return ""
    return _CURRENCY.get(m.group(1).lower(), "RUB")


def _supplier_from_text(full_text: str) -> str:
    """Поставщик из шапки: явная метка «Поставщик:» → организация (ООО…) → пусто."""
    for line in full_text.splitlines()[:25]:
        m = _SUPPLIER_HINTS.search(line)
        if m:
            cand = m.group(1).strip(" :-«»\"")
            org = _ORG_RE.search(cand)
            if org:
                return _clean_org(org.group(1))
            if cand and len(cand) <= 80:
                return cand
    org = _ORG_RE.search(full_text[:1500])
    if org:
        return _clean_org(org.group(1))
    return ""


def _clean_org(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(' «»"').strip()


def _supplier_from_filename(pdf_path: str | Path) -> str:
    stem = Path(pdf_path).stem
    # «КП_ГранитИнвест_2024» → «ГранитИнвест»; вычищаем служебные токены.
    parts = re.split(r"[ _\-]+", stem)
    drop = {"кп", "kp", "коммерческое", "предложение", "прайс", "price", "offer"}
    parts = [p for p in parts if p and p.lower() not in drop and not p.isdigit()]
    return " ".join(parts).strip() or stem


# --- Извлечение строк-материалов --------------------------------------------

def _is_pure_number(s: str) -> bool:
    return bool(re.fullmatch(r"[\d\s .,₽$€%]+", s.strip())) if s.strip() else False


def _clean_material(s: str) -> str:
    s = re.sub(r"^\s*\d+[.)]\s*", "", s)  # ведущая нумерация «1. », «2) »
    s = _CURRENCY_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip(" .,;:№-")


def _row_to_offer(cells: list[str]) -> Optional[dict[str, Any]]:
    """Строка таблицы (список ячеек) → {material, unit, price, currency} или None."""
    cells = [str(c or "").strip() for c in cells]
    joined = " ".join(cells)
    if not joined:
        return None
    if _NOISE_RE.match(joined):
        return None
    if _HEADER_RE.search(joined) and _find_price_in_text(joined) is None:
        return None
    # Материал — самая длинная «текстовая» ячейка (с буквами, не чисто число).
    text_cells = [c for c in cells if re.search(r"[А-Яа-яA-Za-z]{3,}", c) and not _is_pure_number(c)]
    if not text_cells:
        return None
    material = max(text_cells, key=len)
    price = _find_price_in_text(joined)
    if price is None:
        return None
    unit = ""
    for c in cells:
        unit = _find_unit(c)
        if unit:
            break
    if not unit:
        unit = _find_unit(material)
    return {
        "material": _clean_material(material),
        "unit": unit,
        "price": price,
        "currency": _find_currency(joined) or "RUB",
    }


def _line_to_offer(line: str) -> Optional[dict[str, Any]]:
    """Строка свободного текста → offer. Материал = текст без ХВОСТА цены/ед.изм/валюты.

    Имя срезаем СПРАВА (а не по первой цифре), чтобы не рубить названия с цифрами внутри
    (DN50, 600×300×30, М400). Хвост — последняя «числовая зона»: ед.изм + кол-во + цена.
    """
    if not line.strip() or _NOISE_RE.match(line):
        return None
    if _HEADER_RE.search(line) and not re.search(r"\d", line):
        return None
    price = _find_price_in_text(line)
    if price is None:
        return None
    unit = _find_unit(line)
    # Срезаем хвост: всё от первого вхождения «ед.изм + число»/«число …» в правой части.
    head = _strip_trailing_numeric(line)
    if not re.search(r"[А-Яа-яA-Za-z]{3,}", head):
        return None
    return {
        "material": _clean_material(head),
        "unit": unit,
        "price": price,
        "currency": _find_currency(line) or "RUB",
    }


# Хвост строки: (опц. ед.изм) + кол-во/цена/сумма/валюта до конца строки.
_TRAILING_RE = re.compile(
    r"\s+(?:"
    + "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
    + r")?\s*(?:\d[\d  .,]*\s*(?:₽|руб\.?|rub|usd|\$|eur|€)?\s*){1,}$",
    re.IGNORECASE,
)


def _strip_trailing_numeric(line: str) -> str:
    """Отрезать правую «числовую зону» (ед.изм + кол-во + цена + валюта). Имя — слева."""
    cut = _TRAILING_RE.sub("", line)
    # Если ничего не отрезали (имя само кончается цифрой без хвоста-цены) — фолбэк на
    # удаление только финального числа.
    if cut == line:
        cut = re.sub(r"\s*\d[\d  .,]*\s*$", "", line)
    return cut or line


# --- Текстовый слой PDF ------------------------------------------------------

def _add(offers: list[dict[str, Any]], seen: set, off: dict[str, Any]) -> None:
    if not off.get("material"):
        return
    key = (off["material"].lower(), round(off["price"], 2))
    if key in seen:
        return
    seen.add(key)
    offers.append(off)


def _extract_from_text_layer(pdf_path: str | Path) -> tuple[list[dict[str, Any]], str, list[int]]:
    """pdfplumber: таблицы + текст. Возвращает (offers, full_text, пустые_страницы)."""
    import pdfplumber

    offers: list[dict[str, Any]] = []
    text_parts: list[str] = []
    empty_pages: list[int] = []
    seen: set[tuple[str, float]] = set()

    with pdfplumber.open(str(pdf_path)) as pdf:
        for pidx, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            if not page_text.strip():
                empty_pages.append(pidx)

            try:
                tables = page.extract_tables() or []
            except Exception as e:  # noqa: BLE001
                logger.debug("[KAC-PDF] extract_tables упал на стр.%s: %s", pidx, e)
                tables = []
            for table in tables:
                for row in table or []:
                    off = _row_to_offer(row)
                    if off:
                        _add(offers, seen, off)

            if not tables and page_text.strip():
                for line in page_text.splitlines():
                    off = _line_to_offer(line)
                    if off:
                        _add(offers, seen, off)

    return offers, "\n".join(text_parts), empty_pages


# --- OCR-фолбэк (изолированный Tesseract) -----------------------------------

def _extract_via_ocr(pdf_path: str | Path) -> tuple[list[dict[str, Any]], str]:
    """Скан-фолбэк: Tesseract+rus (бинарь, изолирован от venv) → regex по строкам."""
    try:
        from backend.ocr_parser import TesseractOCRParser
    except Exception as e:  # noqa: BLE001
        logger.warning("[KAC-PDF] OCR недоступен (%s) — пропускаю скан-фолбэк", e)
        return [], ""
    try:
        parser = TesseractOCRParser()
        text = parser.parse_pdf(Path(pdf_path))
    except Exception as e:  # noqa: BLE001 — рендер/распознавание скана могут упасть
        logger.warning("[KAC-PDF] OCR не отработал на %s: %s", pdf_path, e)
        return [], ""
    offers: list[dict[str, Any]] = []
    seen: set = set()
    for line in (text or "").splitlines():
        off = _line_to_offer(line)
        if off:
            _add(offers, seen, off)
    return offers, text or ""


# --- LLM-фолбэк (опционально, за флагом) -------------------------------------

def _extract_via_llm(pdf_path: str | Path, raw_text: str) -> list[dict[str, Any]]:
    """ОПЦИОНАЛЬНЫЙ фолбэк для грязных КП. Возвращает [] если LLM-путь недоступен.

    Намеренно best-effort и без жёсткой зависимости: ядро работает 0-LLM, поэтому здесь
    не тащим тяжёлый клиент в офлайн-гейт. Точка расширения под локальную LLM.
    """
    logger.info("[KAC-PDF] LLM-фолбэк запрошен для %s (len(text)=%d)",
                Path(pdf_path).name, len(raw_text or ""))
    return []


# --- Публичный API -----------------------------------------------------------

def extract_offers(
    pdf_path: str | Path,
    *,
    supplier: str = "",
    use_ocr: bool = True,
    use_llm: bool = False,
) -> list[dict[str, Any]]:
    """PDF одного КП → список предложений [{material, supplier, unit, price, currency, source}].

    Формат совместим со входом ``kac_service.analyze_kac`` (нужны material/supplier/unit/price).

    Порядок: текстовый слой (таблицы→текст) → OCR-фолбэк (страницы без текста и use_ocr)
    → LLM-фолбэк (use_llm и всё пусто). Поставщик: аргумент → шапка → имя файла.
    """
    pdf_path = Path(pdf_path)
    source = pdf_path.name

    offers, full_text, empty_pages = _extract_from_text_layer(pdf_path)

    if use_ocr and (empty_pages or not offers):
        try:
            ocr_offers, ocr_text = _extract_via_ocr(pdf_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("[KAC-PDF] OCR-фолбэк упал: %s", e)
            ocr_offers, ocr_text = [], ""
        if ocr_offers:
            full_text = (full_text + "\n" + ocr_text).strip()
            seen = {(o["material"].lower(), round(o["price"], 2)) for o in offers}
            for o in ocr_offers:
                _add(offers, seen, o)

    if not offers and use_llm:
        offers = _extract_via_llm(pdf_path, full_text)

    sup = supplier or _supplier_from_text(full_text) or _supplier_from_filename(pdf_path)

    for o in offers:
        o["supplier"] = sup
        o["source"] = source
    return offers


def extract_and_analyze(
    pdf_paths: list[str | Path],
    *,
    suppliers: Optional[dict[str, str]] = None,
    min_suppliers: int = 3,
    strategy: str = "min",
    use_ocr: bool = True,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Несколько PDF-КП → собрать котировки по материалам → ``kac_service.analyze_kac``.

    ``suppliers``: опц. мэппинг {имя_файла → поставщик} (если поставщик не вычитывается).
    Возвращает результат analyze_kac + ключ ``extraction`` (диагностика извлечения).
    """
    from proxy.services import kac_service

    suppliers = suppliers or {}
    pdf_paths = list(pdf_paths)
    all_quotes: list[dict[str, Any]] = []
    per_file: list[dict[str, Any]] = []

    for p in pdf_paths:
        name = Path(p).name
        offs = extract_offers(
            p, supplier=suppliers.get(name, ""), use_ocr=use_ocr, use_llm=use_llm,
        )
        all_quotes.extend(offs)
        per_file.append({"file": name, "offers": len(offs),
                         "supplier": (offs[0]["supplier"] if offs else "")})

    result = kac_service.analyze_kac(
        all_quotes, min_suppliers=min_suppliers, strategy=strategy,
    )
    result["extraction"] = {
        "files": len(pdf_paths),
        "total_offers": len(all_quotes),
        "per_file": per_file,
    }
    return result
