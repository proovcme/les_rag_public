"""Ordinary profiles must not let the deterministic spec_to_bor channel hijack
the model route.

Routing is a pure decision (0 LLM), so it is asserted deterministically and can
NEVER skip. Whether a live ``answer`` model connection is reachable is a separate
concern checked only by the explicitly-gated full-route test at the bottom.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from proxy.routers import chat as chat_router
from proxy.services.chat_attachment_service import preserve_read_attachment
from proxy.services.profile_resolver import resolve as resolve_profile
from proxy.services.query_router import route_query
from proxy.services.spec_to_bor_service import is_spec_to_bor_query


# The intent recognizer may see "ВОР из спецификации", but the ordinary
# (auto -> agent) route must resolve the channel through query_router and never
# hand control to a deterministic spec_to_bor handler.
_SPEC_VOR_QUESTIONS = (
    "сделай ВОР из спецификации",
    "Собери ВОР в разрезе ЛВЖ",
)


@pytest.mark.parametrize("question", _SPEC_VOR_QUESTIONS)
def test_spec_vor_intent_never_hijacks_channel_deterministically(question: str) -> None:
    # Meaningful precondition: this really is a recognised spec->ВОР intent, so
    # "not hijacked" is a non-trivial claim about routing, not about the intent
    # matcher finding nothing.
    assert is_spec_to_bor_query(question, has_attachment=True) is True

    intent = route_query(question)
    assert intent.channel != "spec_to_bor"
    assert resolve_profile(mode="auto", question=question).profile_id == "agent"


# ── separate concern: live-model availability of the full agent route ──────────
# The end-to-end agent route needs a bound `answer` model connection; when the
# runtime has none, resolution raises 503. That is an external dependency, so
# ONLY these two checks may skip. Routing correctness above must never skip.
_MODEL_CONNECTION_MARKERS = (
    "ROLE_BINDING_MISSING",
    "MODEL_CONNECTION_RESOLUTION_FAILED",
    "MODEL_SERVICE_UNAVAILABLE",
    "MODEL_CONNECTION_RESOLVER_REQUIRED",
)


async def _chat_or_skip(request, **kwargs):
    from fastapi import HTTPException

    try:
        return await chat_router.chat(request, **kwargs)
    except HTTPException as error:
        if error.status_code == 503 and any(
            marker in str(error.detail) for marker in _MODEL_CONNECTION_MARKERS
        ):
            pytest.skip("ordinary-agent VOR needs a bound answer model connection")
        raise


def _mock_chat_state() -> None:
    class _Backend:
        async def list_datasets(self):
            raise AssertionError("retrieval must not run for spec_to_bor")

        async def retrieve(self, *a, **k):
            raise AssertionError("retrieve must not run for spec_to_bor")

    chat_router.set_chat_state(
        chat_router.ChatRouterState(
            rag_backend=_Backend(),
            llm_semaphore=SimpleNamespace(_value=1),
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            chat_metrics={
                "latency_search": [],
                "latency_gen": [],
                "tokens": [],
                "crag_pass": 0,
                "crag_fail": 0,
            },
            reranker_available=False,
            reranker_cls=None,
            current_mode={"mode": "chat"},
        )
    )


def _write_spec_xlsx(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Раздел", "Наименование", "Артикул", "Ед. изм.", "Кол-во ФАКТ"])
    ws.append(["ЛВЖ", "Кабель КПСнг(А)-FRLS", "x", "м.", 100])
    ws.append(["Компрессор", "Лоток глухой 200*50*3000", "35024", "м.", 33])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


@pytest.mark.asyncio
async def test_live_agent_vor_from_attachment_stays_in_selected_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta_qwen.db"))
    attach_root = tmp_path / "storage" / "chat_attachments"
    artifact_dir = tmp_path / "storage" / "smeta_artifacts"
    artifact_dir.mkdir(parents=True)
    monkeypatch.setattr(chat_router, "_SMETA_ARTIFACT_DIR", artifact_dir)

    src = tmp_path / "kamenka.xlsx"
    _write_spec_xlsx(src)
    meta = preserve_read_attachment(
        src,
        attachment_id="read_abcdef123456",
        original_name="Общая по Каменке.xlsx",
        root=attach_root,
    )
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attach_root))

    async def fail_attachment_mode(*_a, **_k):
        raise AssertionError("attachment LLM must not run for VOR-from-spec")

    _mock_chat_state()
    monkeypatch.setattr(chat_router, "_run_attachment_mode", fail_attachment_mode)

    resp = await _chat_or_skip(
        chat_router.ChatRequest(
            question="сделай ВОР из спецификации",
            mode="auto",
            attachment_id=meta["attachment_id"],
            attachment_context=f"Файл: {meta['original_name']}\n\nРаздел|Наименование|...",
        ),
        _user=object(),
    )

    assert resp["crag_status"] != "DETERMINISTIC"
    assert resp["query_route"]["channel"] != "spec_to_bor"
    assert resp["query_route"]["profile"]["profile_id"] == "agent"


@pytest.mark.asyncio
async def test_live_agent_vor_without_attachment_id_is_not_claimed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta_qwen.db"))
    _mock_chat_state()

    async def fail_attachment_mode(*_a, **_k):
        raise AssertionError("must not fall through to attachment LLM")

    monkeypatch.setattr(chat_router, "_run_attachment_mode", fail_attachment_mode)
    resp = await _chat_or_skip(
        chat_router.ChatRequest(
            question="Собери ВОР в разрезе ЛВЖ",
            mode="auto",
            attachment_context="Файл: Общая по Каменке.xlsx\n\nстроки...",
        ),
        _user=object(),
    )
    assert resp["query_route"]["channel"] != "spec_to_bor"
    assert resp["query_route"]["profile"]["profile_id"] == "agent"
