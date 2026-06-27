"""Document set model (СПДС-нормоконтроль, Phase 2).

Нормализует комплект документации в структурированную модель: файл → документ → обозначение
(базовый шифр + марка/дисциплина) → сопоставление с ведомостью. Это EVIDENCE-слой (computed):
он даёт факты для RAG-led review (doc_review_service), но сам не выносит review-status.

Чистый модуль: работает на списке файлов (+ опц. позиции ведомости), без живых сервисов — тестируем
синтетикой. Парс шифра переиспользует normcontrol_service.extract_cipher (NK-03).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from proxy.services.normcontrol_service import _norm_doc_ref, extract_cipher

# Марки комплектов СПДС (дисциплины). Не исчерпывающе, но покрывает типовой РД/ПД.
MARKA_CODES = (
    "ПЗ", "ГП", "ПЗУ", "АР", "АС", "КР", "КЖ", "КМ", "КМД", "КД",
    "ОВ", "ОВиК", "ТМ", "ВК", "НВК", "ЭОМ", "ЭМ", "ЭО", "ЭС", "СС", "СКС", "АК", "АУПТ",
    "ПОС", "ПОД", "ООС", "ПБ", "МПБ", "ТХ", "ГОЧС", "ЭЭ", "ИОС", "СМ",
)
_MARKA_RE = re.compile(
    r"(?<![А-ЯA-Z0-9])("
    + "|".join(sorted((c.upper() for c in MARKA_CODES), key=len, reverse=True))
    + r")(?![А-ЯA-Z])"
)
# Недопустимые разделители в обозначении: пробелы, двойные дефисы/точки, подчёркивания.
_BAD_SEP_RE = re.compile(r"\s|--|\.\.|__")
SUPPORTED_EXT = {".pdf", ".docx", ".doc", ".dwg", ".xlsx", ".xls"}


@dataclass(frozen=True)
class Designation:
    raw: str                # шифр из имени (как распознан)
    base_cipher: str | None  # базовый шифр комплекта
    marka: str | None        # марка/дисциплина (АР/КР/ОВ/...)
    bad_separators: bool     # есть недопустимые разделители


@dataclass(frozen=True)
class DocumentRecord:
    file_name: str
    ext: str
    designation: Designation | None


@dataclass
class VedomostMatch:
    matched: list[str] = field(default_factory=list)   # обозначения из ведомости, найденные в файлах
    missing: list[dict] = field(default_factory=list)  # из ведомости, но НЕТ файла
    extra: list[str] = field(default_factory=list)     # файл есть, в ведомости НЕТ


@dataclass
class DocumentSet:
    documents: list[DocumentRecord]
    base_ciphers: list[str]        # уникальные базовые шифры (>1 = рассинхрон комплекта)
    main_cipher: str | None
    markas: list[str]              # встреченные марки/дисциплины
    unrecognized: list[str]        # файлы без распознанного обозначения


def parse_designation(file_name: str) -> Designation | None:
    stem = Path(file_name).stem
    base = extract_cipher(file_name)
    marka_match = _MARKA_RE.search(stem.upper())
    marka = marka_match.group(1) if marka_match else None
    bad = bool(_BAD_SEP_RE.search(stem))
    if not base and not marka:
        return None
    return Designation(raw=stem, base_cipher=base.upper() if base else None, marka=marka, bad_separators=bad)


def build_document_set(files: list[dict | str]) -> DocumentSet:
    """files: список имён или словарей с file_name. Возвращает нормализованную модель комплекта."""
    docs: list[DocumentRecord] = []
    cipher_count: dict[str, int] = {}
    markas: set[str] = set()
    unrecognized: list[str] = []
    for f in files:
        name = f if isinstance(f, str) else str(f.get("file_name") or f.get("name") or "")
        if not name:
            continue
        ext = Path(name).suffix.lower()
        des = parse_designation(name)
        docs.append(DocumentRecord(file_name=name, ext=ext, designation=des))
        if des is None or (des.base_cipher is None and des.marka is None):
            unrecognized.append(name)
        if des and des.base_cipher:
            cipher_count[des.base_cipher] = cipher_count.get(des.base_cipher, 0) + 1
        if des and des.marka:
            markas.add(des.marka)
    main = max(cipher_count, key=lambda c: cipher_count[c]) if cipher_count else None
    return DocumentSet(
        documents=docs,
        base_ciphers=sorted(cipher_count),
        main_cipher=main,
        markas=sorted(markas),
        unrecognized=unrecognized,
    )


def match_vedomost(doc_set: DocumentSet, vedomost_entries: list[dict]) -> VedomostMatch:
    """Сопоставление позиций ведомости (designation/code + name) с фактическими файлами.
    vedomost_entries: [{"designation": "...", "name": "..."}]. Нормализация как в NK-04."""
    result = VedomostMatch()
    file_norms = {_norm_doc_ref(Path(d.file_name).stem): d.file_name for d in doc_set.documents}
    ved_norms: set[str] = set()
    for row in vedomost_entries or []:
        ref = str(row.get("designation") or row.get("code") or "").strip()
        title = str(row.get("name") or "").strip()
        if not ref:
            continue
        ref_norm = _norm_doc_ref(ref)
        ved_norms.add(ref_norm)
        if any(ref_norm in fn or fn in ref_norm for fn in file_norms):
            result.matched.append(ref)
        else:
            result.missing.append({"designation": ref, "name": title})
    # extra: файлы, которых нет ни в одной позиции ведомости
    for fnorm, fname in file_norms.items():
        if not any(fnorm in vn or vn in fnorm for vn in ved_norms):
            result.extra.append(fname)
    return result
