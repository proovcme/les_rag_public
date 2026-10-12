"""Причина отказа инструмента не должна теряться.

10.09: сборка книги возвращала `TOOL_HANDLER_ERROR` без единого слова о том, что
случилось. Исключение гасилось в общем перехвате, и выяснять причину пришлось ручным
воспроизведением обработчика — оказалось, дело в переменной окружения, подменявшей
пути. Тип и текст исключения обязаны доходить до вызывающего.
"""

from __future__ import annotations

import pytest

from proxy.services.tool_contract_service import (
    EffectClass,
    IdempotencyPolicy,
    ResultBudget,
    RetryPolicy,
    ToolContract,
)
from proxy.services.trusted_executor_service import (
    ExecutionRequest,
    ToolRegistration,
    ToolRegistry,
    TrustedExecutor,
)


def _contract() -> ToolContract:
    return ToolContract(
        name="breaking_tool",
        version="1.0.0",
        title="breaking_tool",
        category="test",
        summary="падает намеренно",
        input_schema={"type": "object"},
        result_schema="les_tool_result_v1",
        effect=EffectClass.READ,
        scopes=(),
        timeout_seconds=30,
        retry=RetryPolicy.SAFE,
        idempotency=IdempotencyPolicy.DERIVED,
        result_budget=ResultBudget(max_chars=7000, max_items=20),
        model_owned_fields=(),
        provenance="test",
    )


def _request(call_id: str) -> ExecutionRequest:
    import time

    return ExecutionRequest(
        call_id=call_id,
        tool_name="breaking_tool",
        arguments={},
        allowed_dataset_ids=(),
        actor_id="test",
        actor_role="user",
        approval_receipt_id=None,
        idempotency_key=f"test:{call_id}",
        deadline_monotonic=time.monotonic() + 60,
    )


@pytest.mark.asyncio
async def test_handler_failure_keeps_its_reason():
    async def handler(args):
        raise ValueError("нет колонки «Наименование» в ведомости")

    executor = TrustedExecutor(
        ToolRegistry([ToolRegistration(contract=_contract(), handler=handler)])
    )
    envelope = await executor.execute(
        _request("c1")
    )

    assert envelope.status == "error", f"код отказа: {envelope.code}"
    assert envelope.code == "TOOL_HANDLER_ERROR"
    reason = str((envelope.result or {}).get("failure_reason") or "")
    assert "ValueError" in reason
    assert "Наименование" in reason, "текст исключения — единственный ключ к причине"


@pytest.mark.asyncio
async def test_reason_is_capped_and_never_leaks_a_whole_traceback():
    """Причина коротка: в неё идёт тип и сообщение, а не весь стек."""
    async def handler(args):
        raise RuntimeError("подробность " * 200)

    executor = TrustedExecutor(
        ToolRegistry([ToolRegistration(contract=_contract(), handler=handler)])
    )
    envelope = await executor.execute(_request("c3"))

    reason = str((envelope.result or {}).get("failure_reason") or "")
    assert reason.startswith("RuntimeError: ")
    assert len(reason) <= 500
    assert "Traceback" not in reason
