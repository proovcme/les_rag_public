"""Deterministic Е.Ж.И.К. answers for mail-shaped chat questions."""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from backend.mail_ingest import MAIL_DATASET_NAME
from backend.mail_threads import filter_mail_messages, group_mail_threads, read_mail_messages


MAIL_QUERY_TOKENS = (
    "почт",
    "письм",
    "email",
    "e-mail",
    "переписк",
    "вложени",
    "кто кому",
    "цепочк",
    "thread",
    "отправил",
    "получил",
)

THREAD_QUERY_TOKENS = ("цепочк", "переписк", "thread", "кто кому")

STOPWORDS = {
    "найди",
    "покажи",
    "покажи",
    "расскажи",
    "письма",
    "письмо",
    "писем",
    "почта",
    "почту",
    "почте",
    "переписку",
    "переписка",
    "цепочку",
    "цепочки",
    "кто",
    "кому",
    "что",
    "про",
    "по",
    "о",
    "об",
    "от",
    "и",
    "или",
    "за",
    "последние",
    "последних",
    "коротко",
    "ответь",
}


@dataclass(frozen=True)
class MailQueryResult:
    matched: bool
    answer: str
    sources: list[str]
    query: str
    mode: str
    total: int
    rows: list[dict[str, Any]]

    def payload(self) -> dict[str, Any]:
        return asdict(self)


async def maybe_answer_mail_query(
    question: str,
    rag_backend: Any,
    *,
    max_items: int = 5,
    max_files: int = 2000,
) -> Optional[MailQueryResult]:
    if not _looks_like_mail_query(question):
        return None

    dataset_root = await _mail_dataset_root(rag_backend)
    if dataset_root is None:
        return None

    messages = await asyncio.to_thread(read_mail_messages, dataset_root, max_files=max_files)
    query = _search_query(question)
    filtered = filter_mail_messages(messages, q=query) if query else messages
    if not filtered:
        return MailQueryResult(
            matched=True,
            answer=f"В MAIL_Index нет писем по запросу: {query or question}",
            sources=[],
            query=query,
            mode="mail",
            total=0,
            rows=[],
        )

    concise = _concise_mode(question)
    item_limit = min(max_items, 3) if concise else max_items
    if _thread_mode(question):
        threads = group_mail_threads(filtered)
        selected = threads[:item_limit]
        lines = [f"Нашёл {len(threads)} почтовых цепочек по запросу: {query or 'последние письма'}."]
        rows: list[dict[str, Any]] = []
        sources: list[str] = []
        for idx, thread in enumerate(selected, start=1):
            payload = thread.summary_payload()
            latest = thread.latest
            who = payload.get("who_to_whom") or {}
            to = ", ".join(who.get("to") or []) or "-"
            snippet = (payload.get("what") or {}).get("snippet") or ""
            lines.append(
                f"{idx}. {thread.subject} — {len(thread.messages)} писем, "
                f"{thread.first_date} → {thread.last_date}; {who.get('from') or '-'} -> {to}."
            )
            if snippet and not concise:
                lines.append(f"   {snippet}")
            rows.append(payload)
            sources.extend(message.relative_path for message in thread.messages)
        return MailQueryResult(
            matched=True,
            answer="\n".join(lines),
            sources=_dedupe(sources),
            query=query,
            mode="mail_threads",
            total=len(threads),
            rows=rows,
        )

    selected_messages = sorted(filtered, key=lambda item: (item.timestamp, item.relative_path), reverse=True)[:item_limit]
    lines = [f"Нашёл {len(filtered)} писем по запросу: {query or 'последние письма'}."]
    rows = []
    sources = []
    for idx, message in enumerate(selected_messages, start=1):
        to = ", ".join(message.to) or "-"
        lines.append(f"{idx}. {message.date or '-'} — {message.subject}; {message.sender or '-'} -> {to}.")
        if message.body_snippet and not concise:
            lines.append(f"   {message.body_snippet}")
        rows.append(message.payload())
        sources.append(message.relative_path)
    return MailQueryResult(
        matched=True,
        answer="\n".join(lines),
        sources=sources,
        query=query,
        mode="mail_messages",
        total=len(filtered),
        rows=rows,
    )


def _looks_like_mail_query(question: str) -> bool:
    q = question.casefold()
    return any(token in q for token in MAIL_QUERY_TOKENS)


def _thread_mode(question: str) -> bool:
    q = question.casefold()
    return any(token in q for token in THREAD_QUERY_TOKENS)


def _concise_mode(question: str) -> bool:
    q = question.casefold()
    return any(token in q for token in ("коротко", "кратко", "без подробностей", "только список"))


def _search_query(question: str) -> str:
    q = question.casefold().replace("ё", "е")
    tokens = re.findall(r"[a-zа-я0-9@._+-]+", q, flags=re.IGNORECASE)
    useful = []
    for token in tokens:
        normalized = token.strip("._+-")
        if (
            len(normalized) > 2
            and normalized not in STOPWORDS
            and not any(marker in normalized for marker in ("письм", "почт", "переписк", "цепоч"))
        ):
            useful.append(normalized)
    return " ".join(useful[:6]).strip()


async def _mail_dataset_root(rag_backend: Any) -> Optional[Path]:
    try:
        datasets = await rag_backend.list_datasets()
    except Exception:
        return None
    dataset = next((item for item in datasets if getattr(item, "name", "") == MAIL_DATASET_NAME), None)
    if dataset is None:
        return None
    content_dir = getattr(rag_backend, "content_dir", None)
    if content_dir is None:
        content_dir = Path("storage/datasets")
    content_root = Path(content_dir).resolve()
    dataset_root = (content_root / str(dataset.id)).resolve()
    if content_root != dataset_root and content_root not in dataset_root.parents:
        return None
    if not dataset_root.exists() or not dataset_root.is_dir():
        return None
    return dataset_root


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out
