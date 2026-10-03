"""Detect an unconsumed tool frame, never execute it or interpret domain content."""

import json


def has_unconsumed_tool_frame(text: str) -> bool:
    """Ignore fenced examples; identify literal JSON/Qwen tool request envelopes."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        value = None
    if isinstance(value, dict) and value.get("calls"):
        calls = value["calls"] if isinstance(value["calls"], list) else [value["calls"]]
        if any(isinstance(call, dict) and (call.get("tool") or call.get("name"))
               and isinstance(call.get("args"), dict) for call in calls):
            return True
    fence = None
    opened = False
    for line in str(text or "").splitlines():
        line = line.strip()
        if line.startswith(("```", "~~~")):
            marker = line[:3]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            opened = False
            continue
        if fence is not None:
            continue
        if line == "<tool_call>":
            opened = True
        elif opened and line.startswith("<function=") and line.endswith(">"):
            return True
        elif line:
            opened = False
    return False


FINAL_RESEARCH_INSTRUCTION = (
    "\nФаза исследования завершена. Сейчас нужен окончательный ответ пользователю "
    "по уже полученным материалам. В этом вызове инструменты недоступны: не формируй "
    "новые вызовы ни в tool_calls, ни в тексте. Если материалов недостаточно, "
    "прямо укажи, что осталось неизвестным, и необходимые уточнения."
)
