"""Раздел проекта по наименованию локальной сметы и её номеру.

ЗАЧЕМ. Шифр в имени файла ненадёжен: одна и та же система пишется «ОВ», «ОВиК»,
«АППЗ», «ППА», «СПД», «БСПД», а номер системы у каждого этапа свой. Зато объектные
сметы перечисляют локальные расчёты парами «номер → наименование», и наименования
писали люди русскими словами: «Демонтаж. Структурированная кабельная система».

ЧТО ЗДЕСЬ. Чистые правила разбора: снять вид работ и тип затрат, найти раздел по
признакам из `config/domain/smeta_section_taxonomy.yaml`. Ни файлов архива, ни сети.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "smeta_section_taxonomy_v1"

# Номер сметы: «02-05-03.1и2» у локальной, «02-10» у объектной. Первый сегмент —
# вид работ, дальше адрес внутри проекта. Смысл второго и третьего сегментов у
# проектов разный (в одном 01-01-17 это СКС, в другом 02-03-02 это отопление),
# поэтому здесь они не толкуются: раздел берётся из наименования.
ESTIMATE_NUMBER = re.compile(
    r"(?<![\d-])(\d{2})-(\d{2})(?:-(\d{1,3}))?(?:\.(\d+))?(?:и(\d+))?(?![\d-])"
)


def _config_path() -> Path:
    candidate = Path("config/domain/smeta_section_taxonomy.yaml")
    if candidate.is_file():
        return candidate
    return Path(__file__).resolve().parents[2] / "config" / "domain" / "smeta_section_taxonomy.yaml"


@lru_cache(maxsize=1)
def load_taxonomy(path: str | None = None) -> dict[str, Any]:
    """Прочитать таксономию разделов; отсутствие файла означает «правил нет»."""
    import yaml

    target = Path(path) if path else _config_path()
    empty = {"sections": {}, "cost_prefixes": [], "work_kinds": {}, "file_codes": {}}
    if not target.is_file():
        return dict(empty)
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return dict(empty)
    return {
        "sections": payload.get("sections") if isinstance(payload.get("sections"), Mapping) else {},
        "cost_prefixes": [str(x).casefold() for x in payload.get("cost_prefixes") or ()],
        "work_kinds": payload.get("work_kinds") if isinstance(payload.get("work_kinds"), Mapping) else {},
        "file_codes": payload.get("file_codes") if isinstance(payload.get("file_codes"), Mapping) else {},
    }


def parse_estimate_number(text: str) -> dict[str, str]:
    """Разобрать номер сметы: вид работ и адрес внутри проекта.

    `01-01-17.1и1` → вид работ 01 (демонтаж), раздел 01, позиция 17, редакция 1.
    `02-10` — объектная смета: третьего сегмента нет.
    """
    match = ESTIMATE_NUMBER.search(str(text or ""))
    if not match:
        return {}
    stage, chapter, item, part, revision = match.groups()
    number = f"{stage}-{chapter}" + (f"-{item}" if item else "") + (f".{part}" if part else "")
    kinds = load_taxonomy().get("work_kinds") or {}
    return {
        "number": number,
        "stage": stage,
        "chapter": chapter,
        "item": item or "",
        "work_kind": str(kinds.get(stage, "")),
        "revision": revision or "",
    }


def strip_cost_prefix(title: str) -> str:
    """Убрать вид работ и тип затрат: раздел определяет система, а не «ЗИП» или «ПНР».

    «ЗИП Система оповещения и управления эвакуацией» → «Система оповещения…».
    Регистр остатка сохраняется: наименование идёт в отчёты как есть. Префикс
    снимается только вместе с его разделителем, иначе «ПО» съело бы «Полы».
    """
    text = str(title or "").strip()
    prefixes = load_taxonomy().get("cost_prefixes") or []
    changed = True
    while changed and text:
        changed = False
        folded = text.casefold()
        for prefix in prefixes:
            if not folded.startswith(prefix) or len(folded) == len(prefix):
                continue
            if folded[len(prefix)] not in " .,:;":
                continue
            rest = text[len(prefix):].lstrip(" .,:;-—")
            if rest:
                text = rest
                changed = True
            break
    return text


@lru_cache(maxsize=4096)
def _marker_pattern(marker: str) -> re.Pattern[str]:
    """Признак — цепочка основ: «пожарн сигнализац» находит «пожарной сигнализации».

    Наименования писали люди, падеж и число произвольны, поэтому каждой основе
    разрешено дописать окончание, а между основами обязателен пробел или дефис.
    """
    text = str(marker).casefold().replace("ё", "е").strip()
    # Знак «$» в конце признака требует, чтобы дальше фраза кончалась. Нужен там, где
    # различие именно в этом: «Система контроля и управления.» — это СКУД, а
    # «Система контроля и управления вентиляцией» — климат, названный следом объект.
    anchored = text.endswith("$")
    if anchored:
        text = text[:-1].strip()
    stems = [re.escape(word) for word in text.split() if word]
    body = r"[\s-]+".join(stem + r"[а-яa-z]*" for stem in stems)
    tail = r"\s*(?=[.,;)]|$)" if anchored else ""
    return re.compile(r"(?<![а-яa-z])" + body + tail)


def section_for_title(title: str, *, taxonomy: Mapping[str, Any] | None = None) -> str:
    """Раздел по наименованию сметы; пустая строка, если признаков нет.

    Наименование в шапке составное: сначала сама смета, затем объект и вид затрат
    («Проект организации платных услуг автостоянки., Информационно-технологическая
    инфраструктура»). Поэтому сперва читается первая фраза — она и есть смета, —
    и только если признаков в ней нет, разбирается строка целиком: у смет вида
    «Система контроля и управления. 36 этаж, КИТСО» раздел назван как раз в хвосте.
    """
    rules = (taxonomy or load_taxonomy()).get("sections") or {}
    text = strip_cost_prefix(title).casefold().replace("ё", "е")
    if not text:
        return ""
    lead = re.split(r"[.,;]", text, maxsplit=1)[0].strip()
    for haystack in (lead, text):
        if not haystack:
            continue
        for name, payload in rules.items():
            markers = (payload or {}).get("markers") or []
            if any(_marker_pattern(str(marker)).search(haystack) for marker in markers):
                return str(name)
    return ""


def section_title(section: str, *, taxonomy: Mapping[str, Any] | None = None) -> str:
    rules = (taxonomy or load_taxonomy()).get("sections") or {}
    payload = rules.get(section)
    return str((payload or {}).get("title") or section) if isinstance(payload, Mapping) else section


# Шифр раздела в имени файла: заглавные буквы отдельным словом, возможно с цифрой.
FILE_CODE = re.compile(r"(?<![А-ЯЁA-Za-zа-яё])([А-ЯЁ][А-ЯЁа-яё]{1,5}\d?)(?![а-яё])")


def section_for_file_name(name: str, *, taxonomy: Mapping[str, Any] | None = None) -> str:
    """Раздел по шифру в имени файла — резерв, когда наименование его не называет.

    «01-01-01.3и2 АР Д доп работы» — наименование говорит только «Демонтаж.
    Дополнительные работы», раздел виден лишь в шифре АР.
    """
    codes = (taxonomy or load_taxonomy()).get("file_codes") or {}
    found: set[str] = set()
    for code in FILE_CODE.findall(Path(str(name or "")).stem):
        # Порядковый номер системы раздела не меняет: СОУЭ1 и СОУЭ2 — пожарные,
        # ОВ1 отопление и ОВ2 вентиляция — оба климат.
        code = code.upper()
        found.update({code, code.rstrip("0123456789")})
    if not found:
        return ""
    for section, values in codes.items():
        if found.intersection({str(v).strip().upper() for v in values or ()}):
            return str(section)
    return ""


def classify_estimate(title: str, file_name: str = "", *, taxonomy: Mapping[str, Any] | None = None) -> str:
    """Раздел сметы: сперва по наименованию из шапки, затем по шифру в имени файла."""
    return section_for_title(title, taxonomy=taxonomy) or section_for_file_name(file_name, taxonomy=taxonomy)
