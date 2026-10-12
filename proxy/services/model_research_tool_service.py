"""Model-requested source search bound to the canonical chat retriever."""

from __future__ import annotations

from pathlib import Path

from functools import lru_cache

import sqlite3

import re
from html import unescape

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping


def executed_empty_search(payload: Mapping[str, Any]) -> bool:
    """Поиск выполнен и не нашёл совпадений — это ответ базы, а не отказ.

    `missing` приходит в двух случаях: база честно ответила «ничего» на выполненный
    запрос, или сам запрос пуст (`missing` содержит "q"). Первое модель должна увидеть
    и решить сама; второе — некорректный запрос. `blocked` — неготовый сервис, это
    всегда технический отказ (аудит Codex 17.09, P2).
    """
    # Доказательство выполнения — статус самой трассы поиска: общий retrieval пишет
    # status="ok", сметный — rag.status="ok". Внешний `missing` без такого доказательства
    # может скрывать технический отказ: общий адаптер ставил его при любых пустых chunks,
    # в том числе при blocked/native_rrf_unavailable (проверка Codex 17.09).
    trace = payload.get("trace") if isinstance(payload.get("trace"), Mapping) else {}
    rag = trace.get("rag") if isinstance(trace.get("rag"), Mapping) else {}
    executed = str(trace.get("status") or "") == "ok" or str(rag.get("status") or "") == "ok"
    return (str(payload.get("status") or "") == "missing" and executed
            and "q" not in [str(item) for item in (payload.get("missing") or [])])


def model_rag_empty_queries(results: list[dict[str, Any]]) -> list[int]:
    """Номера запросов модели (с единицы), выполненных без совпадений."""
    return [index for index, payload in enumerate(results, 1) if executed_empty_search(payload)]


def model_rag_failure_detail(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Describe failed query boundaries without exposing query text or raw exceptions."""
    from proxy.services.public_error_service import public_error_payload

    failures = []
    for index, payload in enumerate(results, 1):
        status = str(payload.get("status") or "")
        if status == "ok" or executed_empty_search(payload):
            continue
        trace = payload.get("trace") or {}
        rag = trace.get("rag") or trace
        failures.append({
            "query_index": index,
            "status": status,
            "operation": payload.get("operation"),
            "collection": rag.get("collection"),
            "error_code": rag.get("error_code") or trace.get("error_code"),
            "reason": rag.get("reason") or trace.get("reason")
                      or ("empty_query" if status == "missing" else "retrieval_not_ready"),
        })
    if not failures:
        return None
    return public_error_payload(status_code=503, detail={
        "code": "MODEL_RAG_SEARCH_INCOMPLETE",
        "blocked_queries": [item["query_index"] for item in failures],
        "query_failures": failures,
    })


class FailedToolCallGuard:
    """Per-request no-progress guard; call IDs are not part of tool identity."""

    def __init__(self) -> None:
        self._failed: set[str] = set()

    @staticmethod
    def _key(call: Mapping[str, Any]) -> str:
        return json.dumps([call.get("tool"), call.get("args") or {}],
                          sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def repeated(self, call: Mapping[str, Any]) -> bool:
        return self._key(call) in self._failed

    def record(self, call: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        if str(payload.get("status") or "") in {"error", "blocked", "missing", "overflow"}:
            self._failed.add(self._key(call))

    def failed_summary(self) -> tuple[dict[str, Any], ...]:
        """Неуспешные вызовы для промпта следующего раунда.

        Одного статуса в результатах модели мало: в chat_history 193 она повторила
        упавший `dataset_map` во втором раунде, из-за чего впустую ушёл ещё один
        вызов селектора (~11,4 тыс. токенов входа). Явный перечень позволяет
        запретить повтор в инструкции, а не гасить его постфактум.
        """
        summary: list[dict[str, Any]] = []
        for key in sorted(self._failed):
            try:
                tool, args = json.loads(key)
            except (TypeError, ValueError):
                continue
            summary.append({"tool": tool, "args": args})
        return tuple(summary)


@dataclass(frozen=True)
class ModelResearchToolResult:
    payload: dict[str, Any]
    chunks: tuple[Any, ...] = ()
    retrieval_trace: dict[str, Any] | None = None


@dataclass(frozen=True)
class _SmetaNormChunk:
    content: str
    doc_name: str
    score: float
    meta: dict[str, Any]


# Правила выбора кода, которые модель читает вместе с карточками. Сказаны прямо, потому
# что 10.09 модель проставила на все строки ЛСР «ТЕРп-08-02-12-1»: шифра такого формата
# в базе нет вовсе — там 49 747 норм и все ГЭСН. Привязка это ловит («норма ГЭСН не
# найдена»), но целый проход сборки уходит впустую.
SMETA_CODE_RULES = (
    "Код нормы бери только из карточек этой выдачи, целиком и без изменений.",
    "В базе есть только ГЭСН (в том числе ГЭСНм, ГЭСНр, ГЭСНп). Территориальных и "
    "федеральных расценок — ТЕР, ФЕР — в ней нет: такой код не будет привязан.",
    "Если подходящей нормы в выдаче нет, переформулируй запрос или оставь строку без "
    "кода — придуманный шифр хуже пустой строки.",
)


NORM_TABLE = re.compile(r"^(.*-\d{3})-\d{2}$")

# Потолок состава работы в карточке — защита от единичных гигантов, а не бюджет.
# Настоящий предел ставит упаковщик свидетельств: при боевом бюджете он режет тело
# карточки на 252 символах, и до модели состав почти не доходит независимо от этого
# числа (замер 10.09: 51 запрос, 35 140 символов групп, потолок 160 и 640 дают
# одинаковый пакет — 23 запроса, 1 % карточек с составом).
#
# А вот когда места хватает — короткая ведомость, несколько запросов — обрезка была
# чистой потерей: в базе 33 957 норм с составом, медиана 157 символов, p90 = 404,
# и потолок 160 отрезал содержание у 47,5 % из них (ревью Codex 10.09). Поэтому
# число выбрано выше p99 (807): целыми остаются практически все составы.
WORK_STEPS_MAX_CHARS = 1200


def norm_table_variants(norm_code: str) -> tuple[str, ...]:
    """Реальные номера вариантов таблицы для активной базы норм."""
    from proxy.smeta_core.norm_browser import _base_path

    base = Path(_base_path())
    try:
        stamp = base.stat()
        revision = f"{base}:{stamp.st_size}:{int(stamp.st_mtime_ns)}"
    except OSError:
        return ()
    return _norm_table_variants_cached(str(norm_code or "").strip(), revision)


@lru_cache(maxsize=512)
def _norm_table_variants_cached(norm_code: str, revision: str) -> tuple[str, ...]:
    """Реальные номера вариантов таблицы; пустой кортеж, если база недоступна.

    Именно перечень, а не диапазон: у 229 таблиц из 8 090 номера идут с пропусками.
    У ГЭСН04-01-077 всего два варианта — -09 и -10, — и справка «с -01 по -02» назвала
    бы модели два несуществующих кода, то есть механизм против выдумок сам бы их
    порождал (ревью Codex 10.09).

    База берётся та же, что и у поиска норм: расхождение ревизий дало бы перечень от
    одной базы к карточкам из другой.
    """
    match = NORM_TABLE.match(str(norm_code or "").strip())
    if not match:
        return ()
    base = Path(revision.rsplit(":", 2)[0])
    if not base.is_file():
        return ()
    try:
        with sqlite3.connect(f"file:{base}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT display_code FROM norms WHERE display_code LIKE ? ORDER BY display_code",
                (match.group(1) + "-%",),
            ).fetchall()
    except sqlite3.Error:
        return ()
    return tuple(str(row[0])[-2:] for row in rows if row and row[0])


def smeta_card_header(card: Mapping[str, Any]) -> str:
    """Identity and nearest source parent, kept whole by the evidence packer."""
    source = str(card.get("source_ref") or "").split("#guid=", 1)[0]
    lines = re.split(r"<br\s*/?>|[\r\n]+", source, flags=re.IGNORECASE)
    path = [unescape(re.sub(r"<[^>]+>", "", line)).strip() for line in lines]
    path = [line for line in path if line]
    # The source supplies the hierarchy; neither query nor code determines scope.
    parent = path[-2] if len(path) > 1 and path[-1].startswith("Таблица") else ""
    table_heading = str(card.get("table_heading") or "").strip() or next(
        (line for line in path if line.casefold().startswith("таблица ")), ""
    )
    return "\n".join(part for part in (
        f"Шифр: {card.get('norm_code') or ''}",
        f"Измеритель: {card.get('measure_unit') or ''}",
        f"Нормативная запись: {card['norm_id']}" if card.get("norm_id") else "",
        f"Наименование: {card.get('title') or ''}",
        f"Раздел источника: {parent}" if parent else "",
        table_heading,
    ) if part)


def smeta_card_context(card: Mapping[str, Any]) -> str:
    """Norm header plus the indivisible archive example and its limitations."""
    raw = card.get("usage_evidence")
    evidence = raw if isinstance(raw, Mapping) else {}
    note = str(evidence.get("note") or "").strip()
    if note:
        # Происхождение цифры — часть свидетельства: без него это мнение. Раздел, архив
        # и его ревизия называются рядом с частотой (ревью Codex 10.09).
        section = str(evidence.get("section") or "").strip()
        source = str(evidence.get("source") or "").strip()
        revision = str(evidence.get("revision") or "").strip()
        origin = ", ".join(part for part in (
            f"раздел {section}" if section else "",
            f"архив {source}" if source else "",
            f"свод {revision}" if revision else "",
        ) if part)
        if origin:
            note = f"{note} [{origin}]"
    # Чем посчитали такое же изделие. Отдельная строка, а не `source_ref`: текст
    # карточки собирается из фиксированного набора полей и лишние игнорирует — на этом
    # же 10.09 терялась практика раздела, и 11.09 так же потерялось это пояснение.
    application = str(card.get("application_note") or "").strip()
    provenance = card.get("archive_provenance")
    if not provenance and evidence:
        from proxy.smeta_core.estimate_usage import archive_provenance
        provenance = archive_provenance(evidence, card)
    if isinstance(provenance, Mapping) and provenance:
        from proxy.smeta_core.estimate_usage import archive_provenance_text
        application = (application + " " + archive_provenance_text(provenance)).strip()
    return chr(10).join(part for part in (
        smeta_card_header(card),
        f"Практика раздела: {note}" if note else "",
        f"Применение: {application}" if application else "",
    ) if part)


def smeta_resource_texts(card: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], str]]:
    """One shared serialization for visible resources and their delivery manifest."""
    if isinstance(card.get('resources'), list):
        return [(item,
            f"#{item.get('row_id')}: {item.get('kind')}; "
            f"{item.get('code') or 'код не указан'}: {item.get('name') or 'наименование не указано'} "
            f"[{item.get('unit') or 'единица не указана'}; "
            f"{item['per_unit'] if item.get('per_unit') is not None else 'неизвестен'}]"
            + (f"; исходная цена: {item['price']}" if item.get('price') is not None else '')
            + (f"; адрес: row:{item['row_id']}" if item.get('row_id') is not None else ''))
            for item in card['resources']]
    return [(item,
        f"{item.get('code')}: {item.get('name')} [{item.get('unit')}; "
        f"{item['per_unit'] if item.get('per_unit') is not None else 'неизвестен'}]"
        + (f"; исходная цена: {item['price']}" if item.get('price') is not None else '')
        + (f"; адрес: row:{item['row_id']}" if item.get('row_id') is not None else ''))
        for item in (card.get('resource_preview') or [])
        if isinstance(item, Mapping) and item.get('kind') in {'material', 'machine'} and (item.get('code') or item.get('row_id') is not None)]


def smeta_resource_group_texts(card: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], str]]:
    if not isinstance(card.get('resources'), list):
        return []
    return [(group,
        f"{group['source_resource_group_id']}: исходные SQL строки [{', '.join(group['source_resource_ids'])}]; "
        f"расчётный ресурс: {group.get('kind')}; {group.get('code') or 'код не указан'}: {group.get('name') or 'наименование не указано'} "
        f"[{group.get('unit') or 'единица не указана'}; {group['per_unit'] if group.get('per_unit') is not None else 'неизвестен'}]"
        + (f"; исходная цена: {group['price']}" if group.get('price') is not None else ''))
        for group in (card.get('resource_groups') or [])]


def smeta_card_delivery_metadata(card: Mapping[str, Any], body: str) -> dict:
    from proxy.services.smeta_evidence_delivery_service import card_delivery_metadata

    return card_delivery_metadata(card, body, smeta_resource_texts(card), group_fragments=smeta_resource_group_texts(card))


def smeta_card_text(card: Mapping[str, Any]) -> str:
    """Текст карточки нормы, который читает модель.

    Нормативный заголовок сохраняется целиком; далее идут архивное свидетельство,
    состав работ, неполный перечень ресурсов и варианты. Частота применения — основание
    для рассмотрения примера, а не доказательство пригодности нормы.
    """
    # Состав работы может сокращаться упаковщиком с хвоста. Здесь
    # только защита от единичных гигантов (максимум в базе — 2 219 символов).
    steps = "; ".join(str(item) for item in (card.get("work_steps") or []) if str(item).strip())
    full_read = isinstance(card.get("resources"), list)
    if not full_read and len(steps) > WORK_STEPS_MAX_CHARS:
        steps = steps[:WORK_STEPS_MAX_CHARS].rstrip(" ;") + "… [состав сокращён]"
    resources = '; '.join(text for _item, text in smeta_resource_texts(card))
    resource_line = (
        f"Машины и материалы (неполный перечень; расход на {card.get('measure_unit') or 'неизвестный измеритель'}): {resources}"
        if resources else ""
    )
    resource_count = card.get('resource_count')
    if not full_read and not resources and isinstance(resource_count, int) and not isinstance(resource_count, bool) and resource_count > 0:
        resource_line = "Машины и материалы (неполный перечень): состав ресурсов не показан."
    if full_read:
        completeness = (
            "полный перечень" if card.get('resources_complete') is True
            else "полнота не подтверждена: число строк отличается от паспорта нормы"
        )
        resource_line = (
            f"Ресурсы нормы ({completeness}; строк {len(card['resources'])}/{card.get('resource_count')}; "
            f"расход на {card.get('measure_unit') or 'неизвестный измеритель'}): {resources or 'нет строк'}."
        )
    code = str(card.get("norm_code") or "")
    variants = norm_table_variants(code)
    table = NORM_TABLE.match(code)
    # Длинный перечень сокращаем явным «и другие»: обрыв списка без пометки читается
    # как исчерпывающий, а диапазон приписал бы таблице несуществующие номера.
    shown = ", ".join("-" + item for item in variants[:12])
    if len(variants) > 12:
        shown += f" и другие, всего {len(variants)}"
    # Packing truncates the tail. The operation description must precede a long
    # resource preview: otherwise the model sees materials but loses what is done.
    parts = (
        smeta_card_context(card),
        # The optional archive block remains indivisible when packed.
        f"Состав работы: {steps}" if steps else "",
        resource_line,
        ('Группы исходных ресурсов: ' + '; '.join(text for _group, text in smeta_resource_group_texts(card)))
        if smeta_resource_group_texts(card) else '',
        # Граница таблицы: без неё модель достраивает ряд номеров сама. Формулировка
        # намеренно справочная — «Других номеров нет» прочиталось как запрет искать
        # аналог, и в прогоне 13:14 модель отказалась от нормы на 55 строках из 70,
        # хотя подходящие ей предлагались.
        f"Варианты таблицы {table.group(1)}: {shown}."
        if variants and table else "",
    )
    return chr(10).join(part for part in parts if part)


def retrieve_smeta_norm_cards(query: str, *, limit: int = 6, discipline: str = "") -> dict[str, Any]:
    """Read model-facing cards from the dedicated smeta dense+sparse RRF.

    К карточкам прикладывается практика раздела — сколько раз норму применяли в
    готовых сметах. Это свидетельство, а не вес: порядок кандидатов задаёт поиск,
    решение принимает модель. Именно этот маршрут использует сметный чат, поэтому
    подсказка живёт здесь, а не только в `search_norm`.
    """

    from proxy.smeta_core.norm_browser import browse_norms

    # The active chat sends model-authored queries. Legacy vocabulary expansions
    # can invent installation conditions and must not run on this boundary.
    payload = browse_norms(query, limit=limit, expand_queries=False)
    return _with_usage_evidence(payload, query, discipline=discipline)


def _with_usage_evidence(payload: dict[str, Any], query: str, *, discipline: str = "") -> dict[str, Any]:
    """Добавить свидетельство о применении, не трогая порядок и состав карточек.

    Раздел приходит из контекста запроса: отдельная строка работы его обычно не
    содержит — «Монтаж шпильки М8» не выдаёт ни дисциплины, ни системы, хотя раздел
    ведомости назван прямо. Догадка по тексту остаётся запасным путём.
    """
    from proxy.smeta_core.collection_scope import discipline_for_text, load_scope
    from proxy.smeta_core.estimate_usage import usage_evidence

    cards = payload.get("cards") if isinstance(payload, Mapping) else None
    if not isinstance(cards, list) or not cards:
        return payload
    requested = str(discipline or "").strip()
    known = set((load_scope().get("disciplines") or {}).keys())
    discipline = requested if requested in known else discipline_for_text(str(query or ""))
    if not discipline:
        return payload
    enriched: list[Any] = []
    for card in cards:
        if not isinstance(card, Mapping):
            enriched.append(card)
            continue
        evidence = usage_evidence(str(card.get("norm_code") or ""), discipline)
        enriched.append({**card, "usage_evidence": evidence} if evidence else dict(card))
    result = dict(payload)
    result["cards"] = enriched
    result["usage_discipline"] = discipline
    return result


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    meta = getattr(chunk, "meta", {}) or {}
    payload: dict[str, Any] = {
        "content": str(getattr(chunk, "content", "") or ""),
        "doc_name": str(getattr(chunk, "doc_name", "") or ""),
        "score": float(getattr(chunk, "score", 0.0) or 0.0),
        "meta": dict(meta) if isinstance(meta, Mapping) else {},
    }
    for name in ("id", "chunk_id", "dataset_id", "source_ref", "page", "_rank_score"):
        value = getattr(chunk, name, None)
        if value is not None:
            payload[name] = value
    return payload


# Запрос модели к карточкам цен ФССЦ. Самостоятельный материал оценивается только по
# точному resource_code, а до 17.09 модель карточек цен не видела вовсе: PriceBook.browse
# в активном пути не вызывался, и код ФССЦ оставалось угадывать.
PRICE_QUERY_PREFIXES = ("цена:", "price:")
PRICE_CARDS_DOC = "fgis_price_cards.v1"
# Карточка цены короче карточки нормы, а однотипных строк в справочнике много: шести
# карточек не хватало, чтобы рядом оказались родственные изделия (17.09).
PRICE_EVIDENCE_K = 10


def evidence_limit(hits: Any, default: int) -> int:
    """Сколько карточек запроса показать модели: выдаче цен — не меньше PRICE_EVIDENCE_K."""
    items = list(hits or ())
    if items and all(str(getattr(item, "doc_name", "") or "") == PRICE_CARDS_DOC for item in items):
        return max(int(default), PRICE_EVIDENCE_K)
    return int(default)
# Живая проверка 17.09: модель написала «Поиск цены на кабель витая пара…», а не «цена:»,
# запрос ушёл в поиск норм, и карточек цен она не получила. Распознаётся её собственная
# формулировка ценового запроса; запросы норм («Поиск нормы на…») сюда не попадают.
PRICE_QUERY = re.compile(r"^\s*(?:поиск\s+)?(?:цен[аы]|price)(?:\s*:\s*|\s+на\s+|\s+для\s+|\s+)(.+)$",
                         re.IGNORECASE)


# Живая проверка 17.09, проход 3: модель подписала запросы номером строки ведомости
# («СКС!5.6: цена: кабель…»). Подпись — её разметка, а не часть запроса: с ней ценовой
# запрос уходил в поиск норм, а запрос нормы нёс в поиск лишние токены.
ROW_LABEL = re.compile(r"^\s*[^\s:!]+![\w.\-]+\s*(?::|—|–|-)\s*")
# Проход 6: «поиск: цена: …» — служебное слово модели перед запросом. Чистая серия,
# проход 9: «смета: цена ковровая плитка…» — та же приставка другим словом, и ценовой
# запрос уходил в поиск норм, оставляя обе поставки без карточек цен.
SEARCH_WORD = re.compile(r"^\s*(?:поиск|смета|запрос)\s*:\s*", re.IGNORECASE)


def strip_row_label(query: str) -> str:
    """Запрос модели без ведущих подписей: строки ведомости и служебных слов."""
    text = ROW_LABEL.sub("", str(query or ""), count=1)
    for _ in range(2):
        stripped = SEARCH_WORD.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    return text.strip()


def price_query_text(query: str) -> str | None:
    """Текст ценового запроса модели без служебных слов; None — это не запрос цены."""
    match = PRICE_QUERY.match(strip_row_label(query))
    return match.group(1).strip() if match else None


def price_card_text(record: Mapping[str, Any]) -> str:
    """Карточка цены ресурса: код, наименование, единица, цена и её регион/период."""
    price = record.get("price_current_eff")
    unit = str(record.get("unit") or "")
    # General format defaults to six significant digits and changes catalogue prices.
    price_text = (f"{float(price)} руб за {unit}" if price not in (None, "") else "цена не указана")
    period = ", ".join(str(record.get(key) or "") for key in ("region", "quarter") if record.get(key))
    return (f"Ресурс ФССЦ: {record.get('code') or ''}\n"
            f"Наименование: {record.get('name') or ''}\n"
            f"Единица: {unit}\n"
            f"Цена текущая: {price_text}" + (f" ({period})" if period else ""))


class ModelResearchToolService:
    """Execute model tools without allowing `search_sources` to leave native RRF."""

    def __init__(
        self,
        *,
        retrieve: Callable[..., Awaitable[Any]],
        frozen_dataset_ids: tuple[str, ...],
        retrieval_kwargs: Mapping[str, Any],
        fallback: Callable[[str, dict[str, Any]], Any],
        smeta_norm_retrieve: Callable[..., Mapping[str, Any]] | None = None,
        price_browse: Callable[[str, int], Any] | None = None,
        retrieval_candidate_k: int = 64,
        document_diversity_k: int = 2,
        model_evidence_k: int = 6,
        price_evidence_k: int = PRICE_EVIDENCE_K,
    ) -> None:
        self._retrieve = retrieve
        self._dataset_ids = tuple(str(item) for item in frozen_dataset_ids if str(item))
        self._retrieval_kwargs = dict(retrieval_kwargs)
        self._fallback = fallback
        self._smeta_norm_retrieve = smeta_norm_retrieve
        self._price_browse = price_browse
        self._retrieval_candidate_k = max(int(retrieval_candidate_k), 1)
        self._document_diversity_k = max(int(document_diversity_k), 1)
        self._model_evidence_k = max(int(model_evidence_k), 1)
        # Карточка цены короче карточки нормы, а однотипных строк в справочнике много:
        # шести карточек не хватало, чтобы рядом оказались родственные изделия (17.09).
        self._price_evidence_k = max(int(price_evidence_k), 1)

    async def _price_cards(self, text: str) -> ModelResearchToolResult:
        """Карточки цен того справочника, по которому считается смета; выбор кода — за моделью."""
        base = {"schema": "les_tool_result_v1", "tool": "search_sources",
                "operation": "fgis_price_browse", "inputs": [{"q": text, "limit": self._price_evidence_k}],
                "warnings": [], "decision_required_from_model": True}
        if not text:
            return ModelResearchToolResult(payload={**base, "status": "missing", "missing": ["q"],
                                                    "result": {"hits": [], "count": 0}, "sources": [],
                                                    "trace": {}})
        from proxy.services import fgis_price_service
        try:
            rows = await asyncio.to_thread(self._price_browse, text, self._price_evidence_k)
        except fgis_price_service.PriceBookRevisionConflict as error:
            trace = {'status': 'blocked', 'operation': 'fgis_price_browse',
                     'error_code': 'pricebook_revision_conflict', 'expected': error.expected,
                     'actual': error.actual, 'reason': error.reason}
            return ModelResearchToolResult(payload={**base, 'status': 'blocked',
                'missing': ['pricebook_revision_conflict'], 'result': {'hits': [], 'count': 0},
                'sources': [], 'trace': trace}, retrieval_trace=trace)
        if rows is None:
            trace = {"status": "blocked", "operation": "fgis_price_browse",
                     "error_code": "pricebook_not_configured"}
            return ModelResearchToolResult(payload={**base, "status": "blocked",
                                                    "missing": ["pricebook_not_configured"],
                                                    "result": {"hits": [], "count": 0}, "sources": [],
                                                    "trace": trace}, retrieval_trace=trace)
        rows = list(rows)[: self._price_evidence_k]
        chunks = tuple(
            _SmetaNormChunk(
                content=price_card_text(record), doc_name="fgis_price_cards.v1",
                score=float(max(len(rows) - index, 1)),
                meta={"price_card": True, "resource_code": str(record.get("code") or ""),
                      "unit": str(record.get("unit") or ""), "price_current_eff": record.get("price_current_eff"),
                      "region": str(record.get("region") or ""), "quarter": str(record.get("quarter") or ""),
                      "pricebook_identity": record.get('pricebook_identity') or (record.get('price_record_identity') or {}).get('pricebook_identity'),
                      **{key: record[key] for key in ('pricebook_identity', 'price_record_identity') if key in record}},
            )
            for index, record in enumerate(rows)
        )
        hits = [_chunk_payload(chunk) for chunk in chunks]
        trace = {"status": "ok", "operation": "fgis_price_browse", "count": len(hits)}
        return ModelResearchToolResult(
            payload={**base, "status": "ok" if hits else "missing",
                     "missing": [] if hits else ["no price cards matched query"],
                     "result": {"hits": hits, "count": len(hits)},
                     "sources": [{"doc_name": "fgis_price_cards.v1", "source_ref": hit["meta"]["resource_code"]}
                                 for hit in hits],
                     "trace": trace},
            chunks=chunks, retrieval_trace=trace)

    async def execute(self, call: Mapping[str, Any]) -> ModelResearchToolResult:
        tool = str(call.get("tool") or "")
        args = dict(call.get("args") or {})
        if tool != "search_sources":
            payload = self._fallback(tool, args)
            if inspect.isawaitable(payload):
                payload = await payload
            return ModelResearchToolResult(payload=payload)

        query = str(args.get("q") or "").strip()
        if not query:
            return ModelResearchToolResult(
                payload={
                    "schema": "les_tool_result_v1",
                    "tool": "search_sources",
                    "operation": "native_rrf",
                    "inputs": [{"q": "", "dataset_ids": list(self._dataset_ids)}],
                    "status": "missing",
                    "result": {"hits": [], "count": 0},
                    "sources": [],
                    "missing": ["q"],
                    "warnings": [],
                    "trace": {},
                    "decision_required_from_model": True,
                }
            )

        price_text = price_query_text(query)
        if price_text is not None and self._price_browse is not None:
            return await self._price_cards(price_text)

        if self._smeta_norm_retrieve is not None:
            browse = await asyncio.to_thread(
                self._smeta_norm_retrieve,
                strip_row_label(query) or query,
                limit=self._model_evidence_k,
            )
            trace = dict(browse.get("retrieval_trace") or {})
            rag_trace = trace.get("rag") if isinstance(trace.get("rag"), Mapping) else {}
            # Dedicated normative generation and archive catalogues do not carry
            # the general user-RAG dataset UUID filter. Expose that boundary;
            # never infer a normative generation from a dataset's name or UUID.
            trace['scope_routing'] = {
                'user_rag': {'dataset_ids': list(self._dataset_ids), 'applied_to_normative': False},
                'normative': {'collection': str(rag_trace.get('collection') or ''),
                    'filters': dict(trace.get('filters') or {})},
                'practice': {'source': 'separate_catalog', 'user_dataset_filter_applied': False},
            }
            if str(rag_trace.get("status") or "") != "ok" or not str(
                rag_trace.get("collection") or ""
            ).strip():
                return ModelResearchToolResult(
                    payload={
                        "schema": "les_tool_result_v1",
                        "tool": "search_sources",
                        "operation": "smeta_norm_native_rrf",
                            "inputs": [{"q": query, "limit": self._model_evidence_k}],
                        "status": "blocked",
                        "result": {"hits": [], "count": 0},
                        "sources": [],
                        "missing": ["dedicated smeta native RRF is not ready"],
                        "warnings": [],
                        "trace": trace,
                        "decision_required_from_model": True,
                    },
                    retrieval_trace=trace,
                )
            cards = list(browse.get("cards") or [])[: self._model_evidence_k]
            chunks = tuple(
                _SmetaNormChunk(
                    content=(body := smeta_card_text(card)),
                    doc_name="smeta_norm_cards.v1",
                    score=float(max(len(cards) - index, 1)),
                    meta={
                        **{key: str(card.get(key) or "") for key in ("norm_id", "edition", "base_type")},
                        "norm_code": str(card.get("norm_code") or ""),
                        "measure_unit": str(card.get("measure_unit") or ""),
                        "source_ref": str(card.get("source_ref") or ""),
                        "smeta_required_header_chars": len(smeta_card_header(card)),
                        "smeta_archive_context_end": len(smeta_card_context(card)),
                        **smeta_card_delivery_metadata(card, body),
                        **({"usage_evidence": dict(card["usage_evidence"])}
                           if isinstance(card.get("usage_evidence"), Mapping) else {}),
                    },
                )
                for index, card in enumerate(cards)
            )
            hits = [_chunk_payload(chunk) for chunk in chunks]
            return ModelResearchToolResult(
                payload={
                    "schema": "les_tool_result_v1",
                    "tool": "search_sources",
                    "operation": "smeta_norm_native_rrf",
                    "inputs": [{"q": query, "limit": self._model_evidence_k}],
                    "rules": list(SMETA_CODE_RULES),
                    "status": "ok" if hits else "missing",
                    "result": {"hits": hits, "count": len(hits)},
                    "sources": [
                        {
                            "doc_name": hit["doc_name"],
                            "source_ref": (hit.get("meta") or {}).get("source_ref") or "",
                        }
                        for hit in hits
                    ],
                    "missing": [] if hits else ["no smeta norm cards matched query"],
                    "warnings": [],
                    "trace": trace,
                    "decision_required_from_model": True,
                },
                chunks=chunks,
                retrieval_trace=trace,
            )

        retrieval = await self._retrieve(
            question=query,
            dataset_ids=list(self._dataset_ids),
            result_limit=self._model_evidence_k,
            candidate_limit=self._retrieval_candidate_k,
            document_diversity_k=self._document_diversity_k,
            **self._retrieval_kwargs,
        )
        chunks = tuple(retrieval.chunks)[: self._model_evidence_k]
        trace = dict(retrieval.payload())
        hits = [_chunk_payload(chunk) for chunk in chunks]
        sources = [
            {
                "doc_name": hit.get("doc_name") or "",
                "dataset_id": (hit.get("meta") or {}).get("dataset_id") or hit.get("dataset_id") or "",
                "chunk_id": (hit.get("meta") or {}).get("chunk_id") or hit.get("chunk_id") or hit.get("id") or "",
                "page": (hit.get("meta") or {}).get("page") or hit.get("page"),
            }
            for hit in hits
        ]
        payload = {
            "schema": "les_tool_result_v1",
            "tool": "search_sources",
            "operation": "native_rrf",
            "inputs": [{"q": query, "dataset_ids": list(self._dataset_ids)}],
            # Отказ retrieval остаётся отказом: пустые chunks при blocked — не «совпадений нет».
            "status": ("blocked" if str(trace.get("status") or "") == "blocked"
                       else "ok" if hits else "missing"),
            "result": {"hits": hits, "count": len(hits)},
            "sources": sources,
            "missing": ([str(trace.get("error_code") or "retrieval_blocked")]
                        if str(trace.get("status") or "") == "blocked"
                        else [] if hits else ["no indexed chunks matched query"]),
            "warnings": [],
            "trace": trace,
            "decision_required_from_model": True,
        }
        return ModelResearchToolResult(
            payload=payload,
            chunks=chunks,
            retrieval_trace=trace,
        )
