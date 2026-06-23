"""ADR-12 (Ц9) — подъём ТАБЛИЧНЫХ ПРИЛОЖЕНИЙ нормативов в ретриве.

Боль (ADR-12, кейс «серверные»): управляющие нормы (СП 485/486/484) описывают
объект КАТЕГОРИЕЙ, а ответ сидит в их таблицах-приложениях (перечень помещений
под АУПТ/АУПС и т.п.). Плоский гибрид их не достаёт по двум причинам:
  1) эмбеддинг строки/ячейки таблицы ≠ натуральный запрос → низкий ранг;
  2) даже когда нужный СП поднят (doc_router/фильтр), приложение тонет под прозой.

ЭМПИРИКА (2026-06-23, живой индекс les_rag_qwen3_06b):
  • В нормативных СП НЕТ чанков type=table_row — это поле ставит ТОЛЬКО parquet_writer
    для xlsx-спецификаций/смет (664 шт., все из проектных датасетов). Поэтому
    «фильтр по type=table_row» (вариант A из ADR-12) для норм даёт ПУСТО.
  • Табличные приложения норм индексируются как type=markdown с pipe-таблицей
    (`| ... | ... |`). У СП 486 — 62/94 чанка pipe-table, у СП 485 — 33, у 484 — 20.
  • Если сузить leaf-поиск на нужные СП (doc_filter) — приложения встают
    в топ (СП 485 §10.3 «Требования к защищаемым помещениям», СП 486 перечень).

РЕШЕНИЕ (вариант B, прицеленный scope'ом узлов — тонкий срез варианта C):
  Когда уже известны документы-узлы (из dataset_filter ИЛИ из doc_router стадии-1)
  и запрос «табличный» (просит перечень/таблицу/приложение/категорию помещений) —
  ДОБАВЛЯЕМ в пул-кандидатов top-N pipe-table чанков ЭТИХ документов по векторной
  близости. Реранкер (ADR-3) дальше сам поднимает релевантные.

АДДИТИВНО и БЕЗОПАСНО:
  • только ДОБАВЛЯЕТ кандидатов в пул, ничего не убирает из плоского пути;
  • без узлов-документов / без табличного интента / пустой результат → no-op (флат);
  • за флагом LES_TABLE_APPENDIX (дефолт включён, но активна лишь при scope+интенте);
  • дедуп по (doc_name, первые 80 симв.) — не плодит дубли при слиянии.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Сигналы «ответ в таблице/приложении/перечне/категории помещений».
_TABLE_INTENT_TOKENS = (
    "таблиц", "приложени", "перечен", "помещени", "категори",
    "серверн", "эвм", "по списку", "в каких помещени", "какие помещени",
)
# Чанк считаем pipe-таблицей по плотности разделителей столбцов.
_MIN_PIPES = int(os.getenv("LES_TABLE_APPENDIX_MIN_PIPES", "4"))
# Сколько табличных кандидатов добавлять в пул (реранк сам отсортирует).
_TABLE_POOL_N = int(os.getenv("LES_TABLE_APPENDIX_POOL_N", "8"))


def table_appendix_enabled() -> bool:
    return os.getenv("LES_TABLE_APPENDIX", "true").strip().lower() in {"1", "true", "yes", "on"}


def has_table_intent(question: str) -> bool:
    """Запрос «табличного» характера — ответ ждём в перечне/таблице/приложении."""
    q = (question or "").casefold().replace("ё", "е")
    return any(tok in q for tok in _TABLE_INTENT_TOKENS)


def _is_pipe_table(text: str) -> bool:
    if not text:
        return False
    return text.count("|") >= _MIN_PIPES


def _dedup_key(chunk: Any) -> tuple:
    doc = str(getattr(chunk, "doc_name", "") or "")
    head = " ".join(str(getattr(chunk, "content", "") or "").split())[:80]
    return (doc, head)


async def fetch_table_appendix_chunks(
    *,
    question: str,
    retrieval_query: str,
    doc_filter: Optional[list[str]],
    dataset_ids: Optional[list[str]],
    rag_backend: Any,
    logger: logging.Logger,
    pool_n: int = _TABLE_POOL_N,
) -> list[Any]:
    """Top-N pipe-table чанков из документов-узлов по векторной близости.

    Возвращает [] (no-op) если: фича выключена / нет интента / нет узлов-документов /
    бэкенд не умеет retrieve. Любой сбой → [] (плоский путь не страдает).
    """
    if not table_appendix_enabled():
        return []
    if not doc_filter:
        # Без явного scope (узлы doc_router или конкретные документы) не лезем:
        # тянуть таблицы по всему датасету — шум, не подъём приложения.
        return []
    if not has_table_intent(question):
        return []
    try:
        # Тянем заведомо БОЛЬШЕ, чем нужно: дальше отфильтруем по pipe-плотности.
        over_k = max(pool_n * 4, 24)
        candidates = await rag_backend.retrieve(
            retrieval_query or question,
            dataset_ids=dataset_ids,
            top_k=over_k,
            doc_filter=doc_filter,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, плоский путь не трогаем
        logger.warning("[TABLE_APPENDIX] retrieve fallback: %s", exc)
        return []

    tables = [c for c in candidates if _is_pipe_table(str(getattr(c, "content", "") or ""))]
    if not tables:
        return []
    out = tables[:pool_n]
    logger.info(
        "[TABLE_APPENDIX] подмешано %d табличных чанков из %d узлов (интент=табличный)",
        len(out), len(doc_filter),
    )
    return out


# Сколько табличных приложений ГАРАНТИРОВАННО держим в видимом окне ответа
# (после реранка). Реранкер склонен топить сырой текст таблицы под прозой —
# без брони приложение не доезжает до пользователя.
_GUARANTEE_SLOTS = int(os.getenv("LES_TABLE_APPENDIX_GUARANTEE", "2"))


def merge_table_appendix(base_chunks: list[Any], table_chunks: list[Any]) -> list[Any]:
    """Аддитивное слияние: к базовому пулу добавляем табличные кандидаты, дедуп.

    Базовый порядок сохраняется; новые таблицы дописываются в хвост — реранкер
    дальше переупорядочит весь пул по релевантности (ADR-3). Если table_chunks
    пуст — возвращаем base без изменений (полный no-op флата).
    """
    if not table_chunks:
        return base_chunks
    seen = {_dedup_key(c) for c in base_chunks}
    merged = list(base_chunks)
    for ch in table_chunks:
        key = _dedup_key(ch)
        if key in seen:
            continue
        seen.add(key)
        merged.append(ch)
    return merged


def guarantee_table_appendix(
    ranked_chunks: list[Any],
    table_chunks: list[Any],
    *,
    window: int,
    slots: int = _GUARANTEE_SLOTS,
) -> list[Any]:
    """Гарантировать табличным приложениям места в видимом окне `window`.

    После реранка прозовые чанки часто вытесняют сырые таблицы за окно ответа.
    Если в первых `window` чанках нет ни одного из подмешанных табличных
    приложений — поднимаем top-`slots` из них (в порядке их исходной близости)
    на позиции window-slots..window-1, сдвигая прозу вниз БЕЗ удаления (она
    остаётся в хвосте). Аддитивно: при table_chunks=[] или slots<=0 — no-op.

    Дедуп: если приложение уже в окне — ничего не двигаем.
    """
    if not table_chunks or slots <= 0 or not ranked_chunks:
        return ranked_chunks
    window = max(1, min(window, len(ranked_chunks)))
    table_keys = {_dedup_key(c) for c in table_chunks}
    head_keys = {_dedup_key(c) for c in ranked_chunks[:window]}
    already = len(table_keys & head_keys)
    need = min(slots, len(table_chunks)) - already
    if need <= 0:
        return ranked_chunks
    # Кандидаты на подъём — табличные приложения, ещё не попавшие в окно,
    # в порядке их близости (как пришли из fetch_table_appendix_chunks).
    promote: list[Any] = []
    for ch in table_chunks:
        if _dedup_key(ch) in head_keys:
            continue
        promote.append(ch)
        if len(promote) >= need:
            break
    if not promote:
        return ranked_chunks
    promote_keys = {_dedup_key(c) for c in promote}
    # Убираем продвигаемые из их текущих позиций, вставляем в хвост окна.
    rest = [c for c in ranked_chunks if _dedup_key(c) not in promote_keys]
    insert_at = max(0, window - len(promote))
    return rest[:insert_at] + promote + rest[insert_at:]
