"""Import Smetnoedelo API v2.0 cards into the LES smeta RAG corpus.

The API token is a secret: pass it with env ``LES_SMETNOE_TOKEN``. This tool
never writes the token to cache, markdown, manifest, or logs.

Typical safe runs:

    # fetch only known codes into runtime RAG_Content
    LES_SMETNOE_TOKEN=... uv run python -m tools.smetnoedelo_rag_import \\
        --runtime-root /Users/ovc/LES --base gesnm2 --code 10-06-058-01 --code 38-01-001-01

    # crawl navigation for one base with a hard request cap
    LES_SMETNOE_TOKEN=... uv run python -m tools.smetnoedelo_rag_import \\
        --runtime-root /Users/ovc/LES --base gesn2 --max-depth 2 --max-requests 40

    # after writing files, ask LES to register/parse the RAG_Content folder
    LES_SMETNOE_TOKEN=... uv run python -m tools.smetnoedelo_rag_import \\
        --runtime-root /Users/ovc/LES --base gesnm2 --section 10 --max-requests 40 --sync-rag

This is a RAG projection, not a calculation source of truth. The smeta runtime
still uses norm/resource/price services for arithmetic and provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


API_URL = "https://api.smetnoedelo.ru/cs/"
DEFAULT_OUT_REL = Path("RAG_Content/TABLE_SMETA/SMETA_SERVICE/smetnoedelo_api")
DEFAULT_CACHE_REL = Path("storage/cache/smetnoedelo_api")

BASE_LABELS: dict[str, str] = {
    "gesn": "ГЭСН-2020. Государственные элементные сметные нормы на строительные работы",
    "gesnm": "ГЭСНм-2020. Государственные элементные сметные нормы на монтаж оборудования",
    "gesnmr": "ГЭСНмр-2020. Нормы на капитальный ремонт оборудования",
    "gesnp": "ГЭСНп-2020. Нормы на пусконаладочные работы",
    "gesnr": "ГЭСНр-2020. Нормы на ремонтно-строительные работы",
    "fer": "ФЕР-2020. Федеральные единичные расценки на строительные работы",
    "ferm": "ФЕРм-2020. Федеральные единичные расценки на монтаж оборудования",
    "fermr": "ФЕРмр-2020. Расценки на капитальный ремонт оборудования",
    "ferp": "ФЕРп-2020. Расценки на пусконаладочные работы",
    "ferr": "ФЕРр-2020. Расценки на ремонтно-строительные работы",
    "fsscm": "ФССЦм-2001. Сметные цены на материалы",
    "fssco": "ФССЦо-2001. Сметные цены на оборудование",
    "fsem": "ФСЭМ-2001. Сметные цены на машины и механизмы",
    "fsscpg": "ФССЦпг. Перевозка грузов",
    "gesn2": "ГЭСН-2022. Государственные элементные сметные нормы на строительные работы",
    "gesnm2": "ГЭСНм-2022. Государственные элементные сметные нормы на монтаж оборудования",
    "gesnmr2": "ГЭСНмр-2022. Нормы на капитальный ремонт оборудования",
    "gesnp2": "ГЭСНп-2022. Нормы на пусконаладочные работы",
    "gesnr2": "ГЭСНр-2022. Нормы на ремонтно-строительные работы",
    "fsbcm": "ФСБЦм-2022. Федеральный сборник базовых цен на материалы",
    "fsbco": "ФСБЦо-2022. Федеральный сборник базовых цен на оборудование",
    "fsbcmm": "ФСБЦмм-2022. Федеральный сборник базовых цен на машины и механизмы",
}

DEFAULT_BASES = (
    "gesn2", "gesnm2", "gesnmr2", "gesnp2", "gesnr2",
    "fsbcm", "fsbco", "fsbcmm",
)

_NORM_CODE_RE = re.compile(r"(?<!\d)(\d{2}-\d{2}-\d{3}-\d{2})(?!\d)")
_RESOURCE_CODE_RE = re.compile(r"(?<!\d)(\d{2}\.\d(?:\.\d{2}){1,3}-\d{3,4}|9\d\.\d{2}\.\d{2}-\d{3})(?!\d)")


def _token() -> str:
    value = os.getenv("LES_SMETNOE_TOKEN", "").strip()
    if not value:
        raise RuntimeError("нет токена: задайте env LES_SMETNOE_TOKEN")
    return value


def _slug(value: Any, *, fallback: str = "item") -> str:
    text = str(value or "").strip().lower()
    out: list[str] = []
    for char in text:
        if char.isalnum():
            out.append(char)
        elif out and out[-1] != "_":
            out.append("_")
    return ("".join(out).strip("_") or fallback)[:120]


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _extract_code(text: Any) -> str:
    s = str(text or "")
    m = _NORM_CODE_RE.search(s) or _RESOURCE_CODE_RE.search(s)
    return m.group(1) if m else ""


def _extract_section_id(text: Any) -> str:
    s = _clean_text(text)
    m = re.search(r"\b(?:Сборник|Сборника)\s+(\d{1,3})\b", s, flags=re.IGNORECASE)
    if m:
        return m.group(1).zfill(2)
    m = re.search(r"\bТаблица\s+(\d{2}-\d{2}-\d{3})\b", s, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\bРаздел\s+(\d{1,3})\b", s, flags=re.IGNORECASE)
    if m:
        return m.group(1).zfill(2)
    return ""


def _looks_like_item_code(code: str) -> bool:
    return bool(_NORM_CODE_RE.fullmatch(code or "") or _RESOURCE_CODE_RE.fullmatch(code or ""))


def _label_for_base(base: str) -> str:
    return BASE_LABELS.get(base, base)


def _cache_key(base: str, *, section: str = "", code: str = "") -> str:
    payload = _json_dumps({"base": base, "section": section, "code": code})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


@dataclass
class ApiEntry:
    title: str
    section: str = ""
    code: str = ""
    raw: Any = None


class RequestBudgetExceeded(RuntimeError):
    pass


class SmetnoedeloClient:
    def __init__(
        self,
        *,
        cache_dir: Path,
        max_requests: int = 50,
        sleep: float = 0.3,
        timeout: int = 30,
        use_cache: bool = True,
    ) -> None:
        self.cache_dir = cache_dir
        self.max_requests = max_requests
        self.sleep = sleep
        self.timeout = timeout
        self.use_cache = use_cache
        self.requests_used = 0
        self.cache_hits = 0

    def _cache_path(self, base: str, *, section: str = "", code: str = "") -> Path:
        return self.cache_dir / base / f"{_cache_key(base, section=section, code=code)}.json"

    def fetch(self, base: str, *, section: str = "", code: str = "") -> Any:
        path = self._cache_path(base, section=section, code=code)
        if self.use_cache and path.is_file():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))
        if self.requests_used >= self.max_requests:
            raise RequestBudgetExceeded(f"request cap reached: {self.max_requests}")
        query = {"token": _token(), "base": base}
        if section:
            query["section"] = section
        if code:
            query["code"] = code
        url = f"{API_URL}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.requests_used += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(data), encoding="utf-8")
        if self.sleep:
            time.sleep(self.sleep)
        return data


def _iter_payload_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in (
        "SECTIONS", "sections", "CHILDREN", "children", "ITEMS", "items",
        "DATA", "data", "RESULT", "result", "ROWS", "rows",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [{"section": k, "name": v} for k, v in value.items()]
    ignored = {"REQUESTS", "DURATIONS", "CODE", "NAME", "COMPOSITION", "URL"}
    scalar_pairs = []
    for key, value in payload.items():
        if key in ignored:
            continue
        if isinstance(value, (str, int, float)):
            scalar_pairs.append({"section": key, "name": value})
        elif isinstance(value, dict):
            item = dict(value)
            item.setdefault("section", key)
            scalar_pairs.append(item)
    return scalar_pairs


def normalize_entries(payload: Any) -> list[ApiEntry]:
    entries: list[ApiEntry] = []
    for item in _iter_payload_items(payload):
        if isinstance(item, str):
            text = _clean_text(item)
            code = _extract_code(text)
            entries.append(ApiEntry(title=text, section="" if code else _extract_section_id(text), code=code, raw=item))
            continue
        if not isinstance(item, dict):
            continue
        title = _clean_text(
            item.get("NAME") or item.get("name") or item.get("TITLE") or item.get("title")
            or item.get("TEXT") or item.get("text") or item.get("label")
        )
        section = _clean_text(
            item.get("SECTION") or item.get("section") or item.get("ID") or item.get("id")
            or item.get("KEY") or item.get("key")
        )
        code = _clean_text(item.get("CODE") or item.get("code") or item.get("cipher") or "")
        if not code:
            code = _extract_code(title) or (_extract_code(section) if _looks_like_item_code(section) else "")
        if not section and not code:
            section = _extract_section_id(title)
        if not title:
            title = _clean_text(item)
        if code and not section:
            section = ""
        entries.append(ApiEntry(title=title, section=section, code=code, raw=item))
    return entries


def _norm_code(payload: dict[str, Any]) -> str:
    code = _clean_text(payload.get("CODE") or payload.get("code") or "")
    return re.sub(r"^[А-ЯA-Zа-яa-z]+\s*", "", code).strip() or _extract_code(code)


def _norm_title(payload: dict[str, Any]) -> str:
    return _clean_text(payload.get("NAME") or payload.get("name") or payload.get("BASE_NAME") or "")


def _composition(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]] | list[str]]:
    comp = payload.get("COMPOSITION") or payload.get("composition") or {}
    if not isinstance(comp, dict):
        return {"jobs": [], "resources": []}
    jobs = [_clean_text(x) for x in comp.get("JOBS", []) or comp.get("jobs", []) or [] if _clean_text(x)]
    resources = []
    for raw in comp.get("RESOURCES", []) or comp.get("resources", []) or []:
        if isinstance(raw, dict):
            resources.append({
                "code": _clean_text(raw.get("CODE") or raw.get("code")),
                "name": _clean_text(raw.get("NAME") or raw.get("name")),
                "quan": _clean_text(raw.get("QUAN") or raw.get("quantity") or raw.get("quan")),
                "unit": _clean_text(raw.get("UNIT") or raw.get("unit")),
            })
    return {"jobs": jobs, "resources": resources}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def render_code_card(base: str, payload: dict[str, Any]) -> str:
    code = _norm_code(payload)
    title = _norm_title(payload)
    sections = [_clean_text(x) for x in payload.get("SECTIONS", []) or payload.get("sections", []) or []]
    comp = _composition(payload)
    lines = [
        f"# {code or 'Карточка'} {title}".strip(),
        "",
        f"Источник: API smetnoedelo v2.0; база `{base}` — {_label_for_base(base)}.",
        "Назначение в ЛЕС: RAG-карточка нормы/ресурса для выбора нормативного маршрута. Это не финальная смета.",
        "",
    ]
    if sections:
        lines += ["## Разделы", "", *[f"- {item}" for item in sections], ""]
    if title:
        lines += ["## Наименование", "", title, ""]
    jobs = comp["jobs"]
    if jobs:
        lines += ["## Состав работ", "", *[f"- {item}" for item in jobs], ""]
    resources = comp["resources"]
    if resources:
        lines += [
            "## Ресурсы на измеритель нормы",
            "",
            "| Код ресурса | Наименование | Расход | Ед. |",
            "|---|---|---:|---|",
        ]
        for item in resources:
            lines.append(
                f"| {item.get('code') or '—'} | {str(item.get('name') or '—').replace('|', '/')} "
                f"| {item.get('quan') or '—'} | {item.get('unit') or '—'} |"
            )
        lines.append("")
    if payload.get("URL"):
        lines += ["## URL", "", str(payload.get("URL")), ""]
    lines += [
        "## Правило использования",
        "",
        "- Модель может использовать эту карточку как кандидата нормы или ресурсной строки.",
        "- Применимость, объём в измерителе нормы, НР/СП, НДС и цены должны закрываться отдельной расчётной трассой.",
        "- Отсутствующая цена ресурса не равна 0.",
    ]
    return "\n".join(lines)


def render_section_card(base: str, section: str, payload: Any, entries: list[ApiEntry]) -> str:
    title = f"{_label_for_base(base)}"
    if section:
        title += f" · раздел {section}"
    lines = [
        f"# {title}",
        "",
        f"Источник: API smetnoedelo v2.0; база `{base}`.",
        "Назначение в ЛЕС: навигационная RAG-карточка раздела/таблицы для подбора норм.",
        "",
        f"- Записей в ответе: {len(entries)}",
        "",
    ]
    if entries:
        lines += [
            "## Дочерние разделы и строки",
            "",
            "| Тип | Код/раздел | Наименование |",
            "|---|---|---|",
        ]
        for entry in entries[:500]:
            kind = "код" if entry.code else "раздел"
            ident = entry.code or entry.section or "—"
            lines.append(f"| {kind} | {ident} | {entry.title.replace('|', '/')} |")
        lines.append("")
    lines += [
        "## Правило использования",
        "",
        "- Эта карточка помогает выбрать сборник/раздел и соседние нормы.",
        "- Если точный код не подтверждён, в ответе пользователю нужно писать «кандидат» или «раздел для проверки».",
    ]
    return "\n".join(lines)


class Importer:
    def __init__(
        self,
        *,
        client: SmetnoedeloClient,
        out_dir: Path,
        fetch_codes: bool = False,
        max_depth: int = 2,
    ) -> None:
        self.client = client
        self.out_dir = out_dir
        self.fetch_codes = fetch_codes
        self.max_depth = max_depth
        self.visited_sections: set[tuple[str, str]] = set()
        self.visited_codes: set[tuple[str, str]] = set()
        self.written: list[str] = []
        self.errors: list[str] = []

    def write_code(self, base: str, code: str) -> None:
        key = (base, code)
        if key in self.visited_codes:
            return
        self.visited_codes.add(key)
        try:
            payload = self.client.fetch(base, code=code)
        except RequestBudgetExceeded:
            raise
        except Exception as error:  # noqa: BLE001
            self.errors.append(f"{base} code {code}: {error}")
            return
        if not isinstance(payload, dict):
            self.errors.append(f"{base} code {code}: unexpected payload")
            return
        rel = Path(base) / "codes" / f"{_slug(code)}.md"
        _write(self.out_dir / rel, render_code_card(base, payload))
        self.written.append(rel.as_posix())

    def crawl_section(self, base: str, section: str = "", *, depth: int = 0) -> None:
        key = (base, section)
        if key in self.visited_sections:
            return
        self.visited_sections.add(key)
        try:
            payload = self.client.fetch(base, section=section)
        except RequestBudgetExceeded:
            raise
        except Exception as error:  # noqa: BLE001
            self.errors.append(f"{base} section {section or '<root>'}: {error}")
            return
        entries = normalize_entries(payload)
        rel_name = "root.md" if not section else f"{_slug(section)}.md"
        rel = Path(base) / "sections" / rel_name
        _write(self.out_dir / rel, render_section_card(base, section, payload, entries))
        self.written.append(rel.as_posix())
        for entry in entries:
            if self.fetch_codes and entry.code:
                self.write_code(base, entry.code)
            if depth < self.max_depth and entry.section and not entry.code:
                self.crawl_section(base, entry.section, depth=depth + 1)


def write_manifest(out_dir: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Smetnoedelo API RAG import",
        "",
        "Generated files from API responses. Token is never stored.",
        "",
        f"- Bases: {', '.join(summary['bases'])}",
        f"- API requests used: {summary['requests_used']}",
        f"- Cache hits: {summary['cache_hits']}",
        f"- Files written: {summary['files_written']}",
        f"- Errors: {len(summary['errors'])}",
        "",
        "## Notes",
        "",
        "- These cards are RAG/navigation evidence, not priced_final calculation traces.",
        "- Use exact norm/resource services for final arithmetic.",
    ]
    if summary["errors"]:
        lines += ["", "## Errors", "", *[f"- {item}" for item in summary["errors"][:50]]]
    _write(out_dir / "00_import_manifest.md", "\n".join(lines))
    _write(out_dir / "00_import_manifest.json", _json_dumps(summary))


def sync_rag(*, proxy_url: str, source_root: str = "RAG_Content", parse: bool = False, parse_limit: int = 25) -> dict[str, Any]:
    body = json.dumps({"source_root": source_root, "parse": parse, "parse_limit_per_dataset": parse_limit}).encode("utf-8")
    request = urllib.request.Request(
        proxy_url.rstrip("/") + "/api/rag/sync-smart",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def run(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    out_dir = runtime_root / args.out
    cache_dir = runtime_root / args.cache
    bases = list(args.base or [])
    if args.default_bases:
        bases.extend(DEFAULT_BASES)
    bases = list(dict.fromkeys(bases))
    if not bases:
        raise SystemExit("укажите --base ... или --default-bases")
    unknown = [base for base in bases if base not in BASE_LABELS]
    if unknown:
        raise SystemExit(f"неизвестные base: {', '.join(unknown)}")

    client = SmetnoedeloClient(
        cache_dir=cache_dir,
        max_requests=args.max_requests,
        sleep=args.sleep,
        timeout=args.timeout,
        use_cache=not args.no_cache,
    )
    importer = Importer(client=client, out_dir=out_dir, fetch_codes=args.fetch_codes, max_depth=args.max_depth)
    stopped_by_budget = False
    try:
        for base in bases:
            for code in args.code or []:
                importer.write_code(base, code)
            sections = args.section if args.section else [""]
            if args.crawl_sections or not args.code:
                for section in sections:
                    importer.crawl_section(base, section)
    except RequestBudgetExceeded:
        stopped_by_budget = True

    summary = {
        "schema": "les.smetnoedelo_api_rag_import.v1",
        "bases": bases,
        "out_dir": out_dir.as_posix(),
        "cache_dir": cache_dir.as_posix(),
        "requests_used": client.requests_used,
        "cache_hits": client.cache_hits,
        "files_written": len(importer.written),
        "written": importer.written,
        "errors": importer.errors,
        "stopped_by_budget": stopped_by_budget,
    }
    write_manifest(out_dir, summary)
    if args.sync_rag:
        summary["sync_rag"] = sync_rag(
            proxy_url=args.proxy_url,
            source_root=args.sync_source_root,
            parse=args.parse,
            parse_limit=args.parse_limit,
        )
        write_manifest(out_dir, summary)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smetnoedelo API → LES smeta RAG cards")
    parser.add_argument("--runtime-root", default=".", help="LES root that owns RAG_Content")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_REL, help="output folder relative to runtime root")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_REL, help="response cache relative to runtime root")
    parser.add_argument("--base", action="append", choices=sorted(BASE_LABELS), help="API base; repeatable")
    parser.add_argument("--default-bases", action="store_true", help=f"use default 2022 bases: {', '.join(DEFAULT_BASES)}")
    parser.add_argument("--section", action="append", default=[], help="section/table id to crawl; repeatable")
    parser.add_argument("--code", action="append", default=[], help="exact norm/resource code to fetch; repeatable")
    parser.add_argument("--crawl-sections", action="store_true", help="crawl sections even when --code is also passed")
    parser.add_argument("--fetch-codes", action="store_true", help="fetch item cards for codes found in section listings")
    parser.add_argument("--max-depth", type=int, default=2, help="recursive section depth")
    parser.add_argument("--max-requests", type=int, default=50, help="hard API request cap excluding cache hits")
    parser.add_argument("--sleep", type=float, default=0.3, help="pause after uncached API request")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds")
    parser.add_argument("--no-cache", action="store_true", help="ignore local response cache")
    parser.add_argument("--sync-rag", action="store_true", help="call local LES /api/rag/sync-smart after writing files")
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050", help="LES proxy URL for --sync-rag")
    parser.add_argument("--sync-source-root", default="RAG_Content", help="source_root value for sync-smart")
    parser.add_argument("--parse", action="store_true", help="parse registered files during --sync-rag")
    parser.add_argument("--parse-limit", type=int, default=25, help="parse limit per dataset for --sync-rag")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        summary = run(args)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(_json_dumps({k: v for k, v in summary.items() if k != "written"}))
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
