"""Smeta-specific model, retrieval, prompt and parsing adapters.

Transport/evidence adapters only: the model owns norm selection and professional decisions.
"""
from __future__ import annotations
import asyncio, json, logging, os, re, time
from dataclasses import dataclass
from typing import Any, Callable
import httpx
from backend.inference.routing import is_cloud_provider
from proxy.services.context_expander_service import expand_context_windows
from proxy.services.estimate_math_service import parse_ru_number, quantity_sum_audit
from proxy.services.kot_service import analyze_question
from proxy.local_model_registry import DEFAULT_LOCAL_MLX_MODEL
from proxy.services.notebook_service import dataset_memory_prompt_excerpt
from proxy.services.project_summary_service import resolve_inventory_file_reference
from proxy.services.query_router import route_query
from proxy.services.retrieval_service import resolve_dataset_ids, retrieve_chat_chunks
from proxy.services.saferag_service import build_context, concentrate_sources, rank_chunks_for_question, source_map_for_context, source_names
logger = logging.getLogger(__name__)
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_LOCAL_SMETA_TOOL_MODEL = "qwen3.5:9b"
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_SMETA_ROW_UNITS_RE = re.compile(r"^(?:м|м2|м²|м3|м³|мм|см|км|шт\.?|компл\.?|комплект|ед\.?|т|кг|100\s*м|100\s*м2|100\s*м²|100\s*шт|100\s*отверстий)$", re.IGNORECASE)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def _smeta_source_row_count(text: str) -> int:
    raw = str(text or "")
    json_rows = len(re.findall(r'"source_no"\s*:', raw))
    if json_rows:
        return json_rows
    markdown_rows = 0
    for line in raw.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 4:
            continue
        first = cells[0]
        if not re.fullmatch(r"\d+[.)]?", first):
            continue
        name = cells[1] if len(cells) > 1 else ""
        unit = cells[2] if len(cells) > 2 else ""
        qty = cells[3] if len(cells) > 3 else ""
        if not name or name.isdigit() or set(name) <= {"-"}:
            continue
        if not _SMETA_ROW_UNITS_RE.match(unit.replace(" ", "")) and not re.search(r"[А-Яа-яA-Za-z]", unit):
            continue
        if not re.search(r"\d", qty):
            continue
        markdown_rows += 1
    return markdown_rows

def _smeta_norm_lookup_max_calls(text: str) -> int:
    source_rows = _smeta_source_row_count(text)
    configured = max(1, _env_int("LES_SMETA_NORM_LOOKUP_MAX_CALLS", 30))
    if source_rows <= 0:
        return configured
    # This is a technical runaway guard, not a workflow decision. The model owns
    # how many lookup calls are needed; code must not truncate ordinary VOR rows.
    return max(configured, min(300, source_rows * 2))

def _smeta_norm_lookup_selector_tokens(text: str) -> int:
    source_rows = _smeta_source_row_count(text)
    configured = max(256, _env_int("LES_SMETA_NORM_LOOKUP_SELECTOR_MAX_TOKENS", 1800))
    if source_rows <= 10:
        return configured
    return max(configured, min(6000, 800 + source_rows * 220))

@dataclass(frozen=True)
class LlmRuntime:
    provider: str
    base_url: str
    chat_url: str
    model: str
    api_key: str
    supports_validation: bool

def _join_openai_path(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") or base.endswith("/api/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"

def _is_local_llm_url(base_url: str) -> bool:
    low = (base_url or "").strip().lower()
    return (
        low.startswith("http://127.")
        or low.startswith("http://localhost")
        or low.startswith("http://[::1]")
        or low.startswith("http://0.0.0.0")
    )

def _model_needs_completion_tokens(model: str) -> bool:
    """GPT-5.x и reasoning o-серия (o1/o3/o4) требуют `max_completion_tokens`
    вместо `max_tokens` — иначе OpenAI/proxyapi отвечает 400."""
    m = (model or "").strip().lower().rsplit("/", 1)[-1]
    return m.startswith("gpt-5") or (len(m) >= 2 and m[0] == "o" and m[1].isdigit())

def _cloud_body_for_model(body: dict, model: str, provider: str) -> dict:
    """Облако: для GPT-5/o-моделей переименовать max_tokens→max_completion_tokens
    (один точечный фикс совместимости; для остальных тело без изменений)."""
    if (is_cloud_provider(provider) and "max_tokens" in body
            and _model_needs_completion_tokens(model)):
        b = dict(body)
        b["max_completion_tokens"] = b.pop("max_tokens")
        return b
    return body

def _llm_runtime() -> LlmRuntime:
    provider = os.getenv("LES_LLM_PROVIDER", "mlx").strip().lower() or "mlx"
    if provider == "openrouter":
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
        model = os.getenv("OPENROUTER_MODEL", "").strip() or os.getenv("LLM_MODEL", "")
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key and not _is_local_llm_url(base_url):
            return _mlx_runtime()
        return LlmRuntime(provider, base_url, _join_openai_path(base_url, "/chat/completions"), model, api_key, False)
    if provider in {"openai", "openai-compatible", "openai_compatible"}:
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
        model = os.getenv("OPENAI_MODEL", "").strip() or os.getenv("LES_DEFAULT_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key and not _is_local_llm_url(base_url):
            return _mlx_runtime()
        return LlmRuntime(provider, base_url, _join_openai_path(base_url, "/chat/completions"), model, api_key, False)
    if provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).strip()
        model = os.getenv("OLLAMA_MODEL", "").strip() or os.getenv("LLM_MODEL", "")
        api_key = os.getenv("OLLAMA_API_KEY", "").strip()
        return LlmRuntime(provider, base_url, _join_openai_path(base_url, "/chat/completions"), model, api_key, False)
    if provider == "lemonade":
        base_url = os.getenv("LEMONADE_BASE_URL", "http://127.0.0.1:13305/api/v1").strip()
        model = os.getenv("LEMONADE_MODEL", "").strip() or os.getenv("LLM_MODEL", "")
        api_key = os.getenv("LEMONADE_API_KEY", "lemonade").strip()
        return LlmRuntime(provider, base_url, _join_openai_path(base_url, "/chat/completions"), model, api_key, False)

    return _mlx_runtime()

def _mlx_runtime() -> LlmRuntime:
    """Локальный MLX-провайдер — он же fallback политики маршрутизации (W3.3)."""
    base_url = os.getenv("MLX_URL", "http://127.0.0.1:8080").strip()
    model = (
        os.getenv("LLM_MODEL", "").strip()
        or os.getenv("MLX_MODEL", "").strip()
        or DEFAULT_LOCAL_MLX_MODEL
    )
    return LlmRuntime("mlx", base_url, _join_openai_path(base_url, "/chat/completions"), model, "", True)

def _smeta_model_runtime(env_name: str) -> LlmRuntime:
    """Runtime for smeta model-owned steps.

    Explicit LES_SMETA_* provider still wins. Without an override, follow the
    configured *local* runtime (MLX on macOS, Ollama/Lemonade on Windows).  A
    cloud-backed global chat still does not silently move smeta off-local unless
    the document consent rule below permits it.  This is transport selection;
    the model continues to own workflow/lookup/choice/final text.
    """
    provider = (
        os.getenv(env_name, "").strip().lower()
        or os.getenv("LES_SMETA_PROVIDER", "").strip().lower()
    )
    if not provider and env_name == "LES_SMETA_DOCUMENT_PROVIDER" and _env_bool("LES_CLOUD_CONSENT", False):
        configured = _llm_runtime()
        if is_cloud_provider(configured.provider) and configured.api_key:
            document_model = os.getenv("LES_SMETA_DOCUMENT_MODEL", "").strip()
            if document_model:
                return LlmRuntime(
                    configured.provider,
                    configured.base_url,
                    configured.chat_url,
                    document_model,
                    configured.api_key,
                    configured.supports_validation,
                )
            return configured
    if provider in {"", "local"}:
        configured = _llm_runtime()
        runtime = configured if not is_cloud_provider(configured.provider) else _mlx_runtime()
        if env_name == "LES_SMETA_DOCUMENT_PROVIDER":
            document_model = os.getenv("LES_SMETA_DOCUMENT_MODEL", "").strip()
            if runtime.provider == "ollama":
                return LlmRuntime(
                    runtime.provider,
                    runtime.base_url,
                    runtime.chat_url,
                    document_model or DEFAULT_LOCAL_SMETA_TOOL_MODEL,
                    runtime.api_key,
                    runtime.supports_validation,
                )
            if document_model.startswith("mlx-") or document_model.startswith("mlx/"):
                mlx_runtime = _mlx_runtime()
                return LlmRuntime(
                    mlx_runtime.provider,
                    mlx_runtime.base_url,
                    mlx_runtime.chat_url,
                    document_model,
                    mlx_runtime.api_key,
                    mlx_runtime.supports_validation,
                )
        return runtime
    if provider == "mlx":
        runtime = _mlx_runtime()
        if env_name == "LES_SMETA_DOCUMENT_PROVIDER":
            document_model = os.getenv("LES_SMETA_DOCUMENT_MODEL", "").strip()
            if document_model.startswith("mlx-") or document_model.startswith("mlx/"):
                return LlmRuntime(
                    runtime.provider,
                    runtime.base_url,
                    runtime.chat_url,
                    document_model,
                    runtime.api_key,
                    runtime.supports_validation,
                )
        return runtime
    if provider == "ollama":
        base_url = os.getenv(
            "OLLAMA_BASE_URL",
            os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
        ).strip()
        document_model = (
            os.getenv("LES_SMETA_DOCUMENT_MODEL", "").strip()
            if env_name == "LES_SMETA_DOCUMENT_PROVIDER"
            else ""
        )
        model = (
            document_model
            or os.getenv("OLLAMA_MODEL", "").strip()
            or os.getenv("LLM_MODEL", "").strip()
            or DEFAULT_LOCAL_SMETA_TOOL_MODEL
        )
        return LlmRuntime(
            "ollama",
            base_url,
            _join_openai_path(base_url, "/chat/completions"),
            model,
            os.getenv("OLLAMA_API_KEY", "").strip(),
            False,
        )
    runtime = _llm_runtime()
    if env_name == "LES_SMETA_DOCUMENT_PROVIDER":
        document_model = os.getenv("LES_SMETA_DOCUMENT_MODEL", "").strip()
        if document_model:
            return LlmRuntime(
                runtime.provider,
                runtime.base_url,
                runtime.chat_url,
                document_model,
                runtime.api_key,
                runtime.supports_validation,
            )
    return runtime

def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None

def _parse_model_tool_calls(text: str, *, allowed_tools: set[str], max_calls: int = 3) -> list[dict[str, Any]]:
    parsed = _extract_json_object(text)
    if not parsed:
        return []
    calls_raw = parsed.get("calls")
    if isinstance(calls_raw, dict):
        calls_raw = [calls_raw]
    if not isinstance(calls_raw, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in calls_raw:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or item.get("name") or "").strip()
        if tool not in allowed_tools:
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        calls.append({"tool": tool, "args": dict(args)})
        if len(calls) >= max(1, max_calls):
            break
    return calls

def _strip_think(text: str) -> str:
    """Срезать <think>…</think> — reasoning-модели инлайнят размышления в content."""
    return _THINK_RE.sub("", text or "").strip()

def _assistant_text(message: dict) -> str:
    """Текст ответа из chat-completion `message` с поддержкой reasoning-моделей.

    Reasoning-модели (Qwen3.5, o-серия и др.) держат ФИНАЛЬНЫЙ ответ в ``content``, а
    размышления — в ``reasoning``/``reasoning_content`` и/или в ``<think>…</think>`` внутри
    content. Берём content без think-блоков; если он пуст (модель «думала» и упёрлась в лимит
    токенов — ровно случай ollama qwen3.5 на Windows) — fallback на reasoning, чтобы не отдать
    пустой ответ. Не-reasoning модели не затронуты (content присутствует → возвращается как был)."""
    if not isinstance(message, dict):
        return ""
    content = _strip_think(str(message.get("content") or ""))
    if content:
        return content
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        arguments = function.get("arguments") if isinstance(function, dict) else ""
        if isinstance(arguments, dict):
            return json.dumps(arguments, ensure_ascii=False)
        if str(arguments or "").strip():
            return str(arguments).strip()
    legacy_call = message.get("function_call") or {}
    if isinstance(legacy_call, dict) and str(legacy_call.get("arguments") or "").strip():
        return str(legacy_call["arguments"]).strip()
    reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
    return _strip_think(str(reasoning))

def _mlx_prefill_no_think_messages(messages: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    """Local Qwen reasoning models need a final-answer prefill to avoid empty visible content."""
    if str(provider or "").lower() != "mlx":
        return messages
    return [*messages, {"role": "assistant", "content": "<think>\n\n</think>\n\n"}]

def _smeta_document_timeout(runtime: LlmRuntime) -> float:
    return _env_float(
        "LES_SMETA_DOCUMENT_TIMEOUT_SEC",
        180.0 if is_cloud_provider(runtime.provider) else 300.0,
    )


def _ollama_native_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the shared conversation to Ollama's native message contract."""
    native: list[dict[str, Any]] = []
    for source in messages:
        role = str(source.get("role") or "")
        message: dict[str, Any] = {
            "role": role,
            "content": source.get("content") or "",
        }
        if role == "assistant" and source.get("tool_calls"):
            message["tool_calls"] = source["tool_calls"]
        if role == "assistant" and source.get("thinking"):
            message["thinking"] = source["thinking"]
        if role == "tool":
            tool_name = str(source.get("tool_name") or source.get("name") or "").strip()
            if tool_name:
                message["tool_name"] = tool_name
        native.append(message)
    return native


def _smeta_document_exchange(messages: list[dict], tools: list[dict]) -> dict[str, Any]:
    """Native tool-call exchange for one continuous smeta conversation."""
    runtime = _smeta_model_runtime("LES_SMETA_DOCUMENT_PROVIDER")
    max_tokens = _env_int("LES_SMETA_DOCUMENT_TOOL_MAX_TOKENS", 1800)
    native_ollama = runtime.provider == "ollama"
    if native_ollama:
        # Ollama's OpenAI-compatible endpoint can silently lose Gemma native
        # tool_calls. Its native /api/chat contract preserves them for both
        # Gemma and Qwen, while keeping the same messages/tools schema.
        body = {
            "model": runtime.model,
            "messages": _ollama_native_messages(messages),
            "tools": tools,
            "stream": False,
            # Ollama's documented agent loop keeps thinking enabled and passes
            # it back in conversation history with the tool call.
            "think": _env_bool("LES_SMETA_DOCUMENT_THINK", False),
            "options": {
                "temperature": 0.0,
                "num_predict": max_tokens,
                # The Ollama default can be only 4K. Agent/tool workflows need
                # enough room to retain search/read evidence across turns.
                "num_ctx": _env_int("LES_SMETA_DOCUMENT_NUM_CTX", 32768),
            },
        }
        ollama_root = runtime.base_url.rstrip("/")
        if ollama_root.casefold().endswith("/v1"):
            ollama_root = ollama_root[:-3]
        chat_url = f"{ollama_root}/api/chat"
    else:
        body = {
            "model": runtime.model,
            # Native tool selection must end on the real user/tool message.  The
            # MLX no-think assistant prefill is useful for visible prose, but here
            # it turns the next turn into prose continuation and suppresses
            # Qwen's tool_calls entirely.
            "messages": messages,
            "tools": tools,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "parallel_tool_calls": True,
        }
        body = _cloud_body_for_model(body, runtime.model, runtime.provider)
        chat_url = runtime.chat_url
    if is_cloud_provider(runtime.provider) and "glm" in str(runtime.model or "").casefold():
        body["thinking"] = {"type": "disabled"}
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    try:
        with httpx.Client(timeout=_smeta_document_timeout(runtime)) as client:
            response = client.post(chat_url, headers=headers, json=body)
            if response.status_code == 400 and "thinking" in body:
                fallback_body = dict(body)
                fallback_body.pop("thinking", None)
                response = client.post(chat_url, headers=headers, json=fallback_body)
            response.raise_for_status()
            payload = response.json()
            message = (
                payload.get("message", {})
                if native_ollama
                else payload.get("choices", [{}])[0].get("message", {})
            )
            message = message if isinstance(message, dict) else {}
            message["_les_done_reason"] = payload.get("done_reason")
            message["_les_eval_count"] = payload.get("eval_count")
            message.setdefault("_les_model", runtime.model)
            message.setdefault("_les_provider", runtime.provider)
            return message
    except Exception as error:
        logger.warning("[SMETA_DOCUMENT] native agent exchange failed: %s", error)
        if isinstance(error, httpx.HTTPStatusError):
            response = error.response
            detail = " ".join(str(response.text or "").split())[:300]
            raise RuntimeError(
                f"smeta provider HTTP {response.status_code}: {detail or response.reason_phrase}"
            ) from error
        raise RuntimeError(f"smeta provider {type(error).__name__}: {error}") from error


def _smeta_document_mapping_exchange(
    messages: list[dict[str, Any]], schema: dict[str, Any],
) -> dict[str, Any]:
    """Serialize the same model's decisions with provider-enforced JSON schema."""
    runtime = _smeta_model_runtime("LES_SMETA_DOCUMENT_PROVIDER")
    max_tokens = _env_int("LES_SMETA_DOCUMENT_MAPPING_MAX_TOKENS", 6000)
    native_ollama = runtime.provider == "ollama"
    if native_ollama:
        body = {
            "model": runtime.model,
            "messages": _ollama_native_messages(messages),
            "format": schema,
            "stream": False,
            # Do not set think=false: current Qwen/Gemma Ollama templates can
            # silently ignore `format` when thinking is explicitly disabled.
            "options": {
                "temperature": 0.0,
                "num_predict": max_tokens,
                "num_ctx": _env_int("LES_SMETA_DOCUMENT_NUM_CTX", 32768),
            },
        }
        ollama_root = runtime.base_url.rstrip("/")
        if ollama_root.casefold().endswith("/v1"):
            ollama_root = ollama_root[:-3]
        chat_url = f"{ollama_root}/api/chat"
    else:
        body = {
            "model": runtime.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "lsr_mapping", "strict": True, "schema": schema},
            },
        }
        body = _cloud_body_for_model(body, runtime.model, runtime.provider)
        chat_url = runtime.chat_url
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    try:
        with httpx.Client(timeout=_smeta_document_timeout(runtime)) as client:
            response = client.post(chat_url, headers=headers, json=body)
            response.raise_for_status()
            response_payload = response.json()
            message = (
                response_payload.get("message", {})
                if native_ollama
                else response_payload.get("choices", [{}])[0].get("message", {})
            )
            message = message if isinstance(message, dict) else {}
            parsed = _extract_json_object(str(message.get("content") or ""))
            if parsed is None:
                raise RuntimeError("smeta provider returned invalid structured mapping JSON")
            parsed["_les_done_reason"] = response_payload.get("done_reason")
            parsed["_les_eval_count"] = response_payload.get("eval_count")
            parsed["_les_model"] = runtime.model
            parsed["_les_provider"] = runtime.provider
            return parsed
    except Exception as error:
        logger.warning("[SMETA_DOCUMENT] structured mapping exchange failed: %s", error)
        if isinstance(error, httpx.HTTPStatusError):
            detail = " ".join(str(error.response.text or "").split())[:300]
            raise RuntimeError(
                f"smeta provider HTTP {error.response.status_code}: "
                f"{detail or error.response.reason_phrase}"
            ) from error
        if isinstance(error, RuntimeError):
            raise
        raise RuntimeError(f"smeta provider {type(error).__name__}: {error}") from error

def _voice_claims_source_truncated(text: str) -> bool:
    t = str(text or "").casefold().replace("ё", "е")
    return bool(re.search(
        r"(?:исходн\w*|файл|тз|ведомост\w*|перечен\w*)\s+"
        r"(?:оборвал|обрыва|усеч|неполн|не полн|заканчива|прерыва)|"
        r"(?:пришл(?:ите|и)|дошл(?:ите|и))\s+(?:продолжени|остаток)",
        t,
    ))

async def _smeta_direct_rag_context(
    req: "ChatRequest",
    *,
    rag_backend: Any,
    dataset_ids: list[str] | None,
    state: Any,
) -> dict[str, Any]:
    """Compact RAG packet for direct smeta mode: context only, no deterministic answer."""
    query_intent = route_query(
        req.question,
        dataset_filter=req.dataset_filter,
        dataset_ids=dataset_ids,
    )
    kot_decision = analyze_question(req.question)
    explicit_scope = bool(dataset_ids or req.dataset_filter or req.project_id)
    effective_dataset_filter = req.dataset_filter
    if not explicit_scope:
        return {
            "text": "",
            "trace": {
                "schema": "smeta_direct_rag_context_v1",
                "effective_dataset_filter": "",
                "dataset_ids": [],
                "status": "skipped",
                "reason": "no_explicit_scope",
                "router_hint": query_intent.dataset_filter or kot_decision.dataset_filter or "",
            },
            "sources": [],
            "source_map": [],
        }
    resolved_ids = await resolve_dataset_ids(
        rag_backend,
        dataset_ids,
        effective_dataset_filter,
        logger,
        question=req.question,
    )
    trace: dict[str, Any] = {
        "schema": "smeta_direct_rag_context_v1",
        "effective_dataset_filter": effective_dataset_filter,
        "dataset_ids": resolved_ids,
        "status": "skipped",
    }
    if not resolved_ids:
        trace["reason"] = "no_dataset_scope"
        return {"text": "", "trace": trace, "sources": [], "source_map": []}

    target_file_ref: dict[str, Any] | None = None
    target_doc_filter: list[str] = []
    target_query = req.target_file or req.question
    try:
        target_file_ref = await asyncio.to_thread(
            resolve_inventory_file_reference,
            target_query,
            [str(d) for d in resolved_ids],
        )
        if target_file_ref and target_file_ref.get("match_status") == "matched" and target_file_ref.get("file_name"):
            target_doc_filter = [str(target_file_ref["file_name"])]
    except Exception as file_err:  # noqa: BLE001
        trace["target_file_error"] = f"{type(file_err).__name__}: {file_err}"

    try:
        reranker_on = (
            req.reranker_enabled
            if req.reranker_enabled is not None
            else os.getenv("RERANKER_ENABLED", "true").lower() == "true"
        )
        retrieval = await retrieve_chat_chunks(
            question=req.question,
            dataset_ids=resolved_ids,
            rag_backend=rag_backend,
            reranker_enabled=reranker_on,
            reranker_available=state.reranker_available,
            reranker_cls=state.reranker_cls,
            mlx_url=os.getenv("MLX_URL", "http://127.0.0.1:8080"),
            logger=logger,
            llm_semaphore=state.llm_semaphore,
            return_trace=True,
            doc_filter=target_doc_filter or None,
        )
        chunks = rank_chunks_for_question(req.question, retrieval.chunks)
        chunks = concentrate_sources(
            chunks,
            max_docs=_env_int("LES_SMETA_RAG_MAX_DOCS", 4),
            min_score=_env_float("LES_SMETA_RAG_MIN_SCORE", 0.0),
            max_chunks=_env_int("LES_SMETA_RAG_MAX_CHUNKS", 10),
            protected_doc_names=target_doc_filter,
        )
        windows = expand_context_windows(
            chunks,
            collection=getattr(rag_backend, "collection_name", ""),
            logger=logger,
            max_chunks=_env_int("LES_SMETA_RAG_CONTEXT_MAX_CHUNKS", 8),
            max_chars_per_chunk=_env_int("LES_SMETA_RAG_CONTEXT_WINDOW_CHARS", 1800),
            radius=0,
        )
        ctx_chunks = windows.chunks
        max_chars = _env_int("LES_SMETA_RAG_CONTEXT_CHARS", 9000)
        context = build_context(ctx_chunks, max_chars, include_metadata=True)
        source_map = source_map_for_context(ctx_chunks, max_chars, include_metadata=True)
        try:
            memory_prompt = await asyncio.to_thread(
                dataset_memory_prompt_excerpt,
                [str(d) for d in resolved_ids],
                question=req.question,
            )
        except TypeError:
            # Compatibility for tests/older notebook providers with the pre-question
            # signature. Notebook memory is navigation, so a missing query hint must
            # not collapse the whole smeta RAG context.
            memory_prompt = await asyncio.to_thread(
                dataset_memory_prompt_excerpt,
                [str(d) for d in resolved_ids],
            )
        blocks = []
        if context:
            blocks.append(
                "Проверяемые фрагменты из выбранного RAG-корпуса для сметного ответа:\n"
                f"{context}"
            )
        if memory_prompt:
            blocks.append(
                "Навигационная карта корпуса (не источник фактов, только куда смотреть):\n"
                f"{memory_prompt}"
            )
        if target_file_ref and target_file_ref.get("match_status") == "matched":
            blocks.append(
                "Запрос привязан к файлу: "
                f"{target_file_ref.get('file_name')} "
                f"(статус индекса: {target_file_ref.get('status')}, чанков: {target_file_ref.get('chunk_count')})."
            )
        retrieval_payload = retrieval.payload()
        trace.update({
            "status": "ready" if blocks else "empty",
            "retrieval": retrieval_payload,
            "source_count": len(source_map),
            "target_file": target_file_ref,
            "context_chars": sum(len(b) for b in blocks),
            "dataset_memory": bool(memory_prompt),
        })
        return {
            "text": "\n\n".join(blocks),
            "trace": trace,
            "sources": source_names(ctx_chunks),
            "source_map": source_map,
        }
    except Exception as rag_err:  # noqa: BLE001
        logger.warning("[SMETA_RAG] context skipped: %s", rag_err)
        trace.update({
            "status": "error",
            "error": f"{type(rag_err).__name__}: {rag_err}",
        })
        return {"text": "", "trace": trace, "sources": [], "source_map": []}

def _smeta_direct_light_system_prompt() -> str:
    return (
        "Ты работаешь в сметном модуле ЛЕС. Самостоятельно реши задачу пользователя по переданному "
        "исходнику, доступным источникам и расчётной трассе. Используй источники и инструменты по "
        "необходимости; не следуй заранее заданному нормативному маршруту. Профессиональные решения "
        "принимает модель, код выполняет поиск, проверяет provenance и считает. Не подменяй отсутствующие "
        "данные выдуманными фактами. Верни непосредственно запрошенный пользователем результат."
    )

def _smeta_request_needs_lsr_output(text: str) -> bool:
    low = str(text or "").casefold().replace("ё", "е")
    no_money = bool(re.search(
        r"\bбез\s+(?:расчет[а-я]*|рубл[а-я]*|стоимост[а-я]*|денег)\b|"
        r"\bне\s+(?:считай|рассчитывай|оценивай)\b",
        low,
    ))
    asks_method = bool(re.search(
        r"\b(?:порядок|алгоритм|методик[а-я]*|как\s+работа[а-я]*|тест|провер[а-я]*|"
        r"таблиц[а-я]*\s+кандидат[а-я]*|без\s+расчет[а-я]*)\b",
        low,
    ))
    asks_process_explanation = bool(re.search(
        r"\b(?:объясни|расскажи|опиши|процесс|workflow|как\s+(?:ты\s+)?работа[а-я]*|"
        r"как\s+устроен[а-я]*|что\s+выбираешь|что\s+считает\s+код|что\s+делаешь)\b",
        low,
    ))
    explicit_lsr_or_money_action = bool(re.search(
        r"\b(?:сделай|составь|оформи|сформируй|подготовь|рассчитай|посчитай|оцени|дай)\b"
        r"[^.\n]{0,100}\b(?:лср|смет[ауыеой]*|стоимост[ьяиюе]*|оценк[ауи]|сумм[ауыеой]*|рубл[яей]*|цен[ауыеой]*|итог[а-я]*)\b",
        low,
    ))
    asks_lsr_or_money = bool(re.search(
        r"\b(?:лср|смет[ауыеой]*|стоимост[ьяиюе]*|оценк[ауи]|рассчит[а-я]*|посчитай|"
        r"сумм[ауыеой]*|рубл[яей]*|цен[ауыеой]*|итог[а-я]*)\b",
        low,
    ))
    if asks_process_explanation and not explicit_lsr_or_money_action:
        return False
    if no_money and asks_method:
        return False
    return asks_lsr_or_money and not no_money

def _smeta_direct_user_prompt(
    harness_question: str,
    rag_context: str,
    numeric_audit_context: str,
    *,
    light: bool,
) -> str:
    """Pass source, evidence, and calculations without prescribing a workflow."""
    sections = [
        f"Запрос пользователя и исходные документы:\n{str(harness_question or '')[:22000]}"
    ]
    if rag_context:
        sections.append(
            "Доступные фрагменты источников и результаты инструментов:\n"
            f"{str(rag_context)[:16000]}"
        )
    if numeric_audit_context:
        sections.append(f"Проверенная кодом расчётная трасса:\n{numeric_audit_context}")
    return "\n\n".join(sections)

def _smeta_direct_max_tokens(harness_question: str, *, runtime_provider: str) -> int:
    default = 900 if runtime_provider == "mlx" else 3200
    configured = os.getenv("LES_SMETA_DIRECT_MODEL_MAX_TOKENS", "").strip()
    if configured:
        try:
            return int(configured)
        except ValueError:
            return default
    row_count = len(re.findall(r'"source_no"\s*:', str(harness_question or "")))
    if row_count >= 15:
        return 3600 if runtime_provider == "mlx" else 6000
    if row_count >= 5:
        return 2400 if runtime_provider == "mlx" else 4500
    return default

def _smeta_direct_model_answer(
    harness_question: str,
    rag_context: str = "",
) -> str:
    """Visible smeta answer from the estimator model over prompt + attachment + RAG."""
    runtime = _smeta_model_runtime("LES_SMETA_DIRECT_MODEL_PROVIDER")
    numeric_audit_context = _smeta_direct_numeric_audit_context(harness_question)
    sys_prompt = _smeta_direct_light_system_prompt()
    user_prompt = _smeta_direct_user_prompt(
        harness_question,
        rag_context,
        numeric_audit_context,
        light=True,
    )
    body = {
        "model": runtime.model,
        "messages": _mlx_prefill_no_think_messages(
            [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            runtime.provider,
        ),
        "temperature": _env_float("LES_SMETA_DIRECT_MODEL_TEMPERATURE", 0.0),
        "max_tokens": _smeta_direct_max_tokens(harness_question, runtime_provider=runtime.provider),
    }
    body = _cloud_body_for_model(body, runtime.model, runtime.provider)
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    timeout_s = _env_float(
        "LES_SMETA_DIRECT_MODEL_TIMEOUT_SEC",
        1200.0 if runtime.provider == "mlx" else 120.0,
    )
    try:
        with httpx.Client(timeout=timeout_s) as c:
            r = c.post(runtime.chat_url, headers=headers, json=body)
            r.raise_for_status()
            text = _assistant_text(r.json().get("choices", [{}])[0].get("message", {})).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[HARNESS] direct model smeta answer failed: %s", e)
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text).strip(" \n\t\"'")
    if not text or _voice_claims_source_truncated(text):
        return ""
    return text[:12000]

def _smeta_direct_norm_lookup_context(harness_question: str) -> dict[str, Any]:
    """Let the model choose norm lookup calls, then return lookup evidence for final smeta answer.

    This deliberately does not map source rows to norms in code. The selector model
    decides which `search_norm` calls are needed; code only executes the read-only
    lookup and passes compact results back to the final estimator prompt.
    """
    if not _env_bool("LES_SMETA_DIRECT_NORM_LOOKUP_ENABLED", True):
        return {"text": "", "trace": {"enabled": False}}
    question = str(harness_question or "").strip()
    if not question:
        return {"text": "", "trace": {"enabled": True, "selected_calls": []}}
    runtime = _smeta_model_runtime("LES_SMETA_NORM_LOOKUP_PROVIDER")
    source_row_count = _smeta_source_row_count(question)
    max_calls = _smeta_norm_lookup_max_calls(question)
    tool_spec = {
        "tool": "search_norm",
        "args": {
            "work_description": "описание одной нормируемой работы",
            "work_family": "electric|low_current|metal|finishes|mep|earthworks|foundation|...",
            "element_type": "фактический тип элемента из строки источника",
            "action": "монтаж|демонтаж|устройство|проверка|...",
            "unit_hint": "м|м2|м3|т|шт|...",
        },
    }
    body = {
        "model": runtime.model,
        "messages": _mlx_prefill_no_think_messages([
            {
                "role": "system",
                "content": (
                    "Ты инженер-сметчик и выбираешь только read-only lookup-вызовы перед ЛСР. "
                    "Код не выбирает нормы за тебя. Верни только JSON вида "
                    "{\"calls\":[{\"tool\":\"search_norm\",\"args\":{...}}]}. "
                    "Каждый вызов — одна нормируемая работа, а не весь объект. "
                    "Если поиск норм не нужен, верни {\"calls\":[]}."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": question[:18000],
                        "available_tool": tool_spec,
                        "source_rows_expected": source_row_count,
                        "max_calls": max_calls,
                        "policy": (
                            "выбирай lookup-запросы сам; не ставь цены; не финализируй ЛСР; "
                            "цель — получить реальные коды норм-кандидатов из базы ЛЕС; "
                            "если во входе есть табличная ВОР/PDF table/source_no, не сокращай покрытие: нужен lookup "
                            "по каждой исходной строке или явное объединение нескольких строк только если это одна "
                            "нормируемая операция; "
                            "не выводи семейство/сборник из названия раздела или файла; описывай фактический элемент, "
                            "операцию и единицу каждой строки. Если строка не является отдельной нормируемой операцией, "
                            "оставь явный gap или объясни объединение, не подменяя её похожей работой."
                        ),
                    },
                    ensure_ascii=False,
                ),
            },
        ], runtime.provider),
        "temperature": 0,
        "max_tokens": _smeta_norm_lookup_selector_tokens(question),
    }
    body = _cloud_body_for_model(body, runtime.model, runtime.provider)
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    try:
        timeout_sec = _env_float(
            "LES_SMETA_NORM_LOOKUP_TIMEOUT_SEC",
            1200.0 if runtime.provider == "mlx" else 90.0,
        )
        with httpx.Client(timeout=timeout_sec) as c:
            r = c.post(runtime.chat_url, headers=headers, json=body)
            r.raise_for_status()
            selector_text = _assistant_text(r.json().get("choices", [{}])[0].get("message", {})).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[SMETA] norm lookup selector failed: %s", e)
        return {
            "text": "",
            "trace": {
                "enabled": True,
                "status": "selector_error",
                "provider": runtime.provider,
                "model": runtime.model,
                "timeout_sec": timeout_sec,
                "error": f"{type(e).__name__}: {e}",
            },
        }
    calls = _parse_model_tool_calls(selector_text, allowed_tools={"search_norm"}, max_calls=max_calls)
    if not calls:
        return {
            "text": "",
            "trace": {
                "enabled": True,
                "model_owns_selection": True,
                "selected_calls": [],
                "source_rows_expected": source_row_count,
                "source_rows_covered": 0,
                "max_calls": max_calls,
                "selector_text": selector_text[:1000],
                "provider": runtime.provider,
                "model": runtime.model,
            },
        }
    from proxy.services.estimate_harness_service import search_norm

    results: list[dict[str, Any]] = []
    top_k = max(1, _env_int("LES_SMETA_NORM_LOOKUP_TOP_K", 25))
    for call in calls:
        args = dict(call.get("args") or {})
        result = search_norm(
            str(args.get("work_description", "")),
            work_family=str(args.get("work_family", "")),
            element_type=str(args.get("element_type", "")),
            action=str(args.get("action", "")),
            unit_hint=str(args.get("unit_hint", "")),
            top_k=top_k,
        )
        results.append({"call": {"tool": "search_norm", "args": args}, "result": result})
    return {
        "text": _format_smeta_norm_lookup_results_for_model(results),
        "trace": {
            "enabled": True,
            "model_owns_selection": True,
            "selected_calls": calls,
            "results": results,
            "source_rows_expected": source_row_count,
            "source_rows_covered": len(results),
            "coverage_missing": max(0, source_row_count - len(results)) if source_row_count else 0,
            "max_calls": max_calls,
            "provider": runtime.provider,
            "model": runtime.model,
        },
    }

def _format_smeta_norm_lookup_results_for_model(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    compact: list[dict[str, Any]] = []
    for item in results:
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        candidates = []
        for cand in (result.get("candidates") or [])[: max(1, _env_int("LES_SMETA_NORM_LOOKUP_PROMPT_CANDIDATES", 20))]:
            if not isinstance(cand, dict):
                continue
            candidates.append(
                {
                    "norm_code": cand.get("norm_code"),
                    "title": cand.get("title"),
                    "measure_unit": cand.get("measure_unit"),
                    "unit_compatible": cand.get("unit_compatible"),
                    "applicability_status": cand.get("applicability_status"),
                    "score_total": cand.get("score_total"),
                    "norm_card": _smeta_norm_candidate_card(cand),
                }
            )
        compact.append(
            {
                "model_selected_lookup": item.get("call"),
                "status": result.get("status"),
                "work_family": result.get("work_family"),
                "element_type": result.get("element_type"),
                "norm_store": result.get("norm_store"),
                "candidates": candidates,
                "navigation": result.get("norm_navigation"),
            }
        )
    text = json.dumps(compact, ensure_ascii=False, indent=2, default=str)
    return (
        "MODEL-SELECTED NORM LOOKUP RESULTS (read-only; это найденные записи базы норм, "
        "не готовая смета и не выбор кода):\n"
        "Модель должна сама выбрать полный шифр из этих результатов или оставить строку ЛСР с 0.00.\n"
        "Запрещено ставить модельную ставку/рубли по строке, если полный norm_code не скопирован в Обоснование.\n"
        f"{text[: max(2000, _env_int('LES_SMETA_NORM_LOOKUP_CONTEXT_CHARS', 32000))]}"
    )

def _smeta_short_list(values: Any, *, limit: int = 5, chars: int = 140) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values[:limit]:
        text = str(value or "").strip()
        if text:
            out.append(text[:chars])
    return out

def _smeta_norm_candidate_card(candidate: dict[str, Any]) -> dict[str, Any]:
    profile = candidate.get("norm_profile") if isinstance(candidate.get("norm_profile"), dict) else {}
    card = profile.get("model_card") if isinstance(profile.get("model_card"), dict) else {}
    navigation = profile.get("navigation") if isinstance(profile.get("navigation"), dict) else {}
    work_composition = card.get("work_composition") if isinstance(card.get("work_composition"), dict) else {}
    domain = card.get("domain") if isinstance(card.get("domain"), dict) else {}
    resources = card.get("resources") if isinstance(card.get("resources"), dict) else {}
    applicability = card.get("applicability") if isinstance(card.get("applicability"), dict) else {}
    collection = navigation.get("collection") if isinstance(navigation.get("collection"), dict) else {}
    return {
        "title": str(card.get("title") or "")[:220],
        "domain": {
            "families": _smeta_short_list(domain.get("families"), limit=4, chars=80),
            "elements": _smeta_short_list(domain.get("elements"), limit=4, chars=80),
            "actions": _smeta_short_list(domain.get("actions"), limit=4, chars=80),
        },
        "work_steps": _smeta_short_list(work_composition.get("steps"), limit=5, chars=160),
        "conditions_to_check": _smeta_short_list(card.get("conditions_to_check"), limit=4, chars=120),
        "resources": {
            "count": resources.get("count"),
            "kinds": _smeta_short_list(resources.get("kinds"), limit=5, chars=80),
        },
        "applicability_check": str(applicability.get("check") or "")[:180],
        "collection": {
            "key": collection.get("key"),
            "subsection": collection.get("subsection"),
            "base_type": collection.get("base_type"),
        },
    }

def _smeta_norm_choice_tokens(text: str) -> int:
    source_rows = _smeta_source_row_count(text)
    configured = max(512, _env_int("LES_SMETA_NORM_CHOICE_MAX_TOKENS", 9000))
    if source_rows <= 10:
        return configured
    return max(configured, min(14000, 2400 + source_rows * 420))

def _smeta_norm_choice_runtime() -> LlmRuntime:
    return _smeta_model_runtime("LES_SMETA_NORM_CHOICE_PROVIDER")

def _smeta_norm_review_timeout(runtime: LlmRuntime) -> float:
    default = 1200.0 if runtime.provider in {"mlx", "local"} else 180.0
    return _env_float("LES_SMETA_NORM_REVIEW_TIMEOUT_SEC", default)

def _smeta_review_structured_norm_choice(
    harness_question: str,
    compact_results: list[dict[str, Any]],
    allowed_by_lookup: dict[int, set[str]],
    draft_rows: list[dict[str, Any]],
    runtime: LlmRuntime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run a second model-owned audit over draft norm choices before pricing."""
    if not _env_bool("LES_SMETA_NORM_REVIEW_ENABLED", True):
        return draft_rows, {"enabled": False}
    if not compact_results:
        return draft_rows, {"enabled": True, "status": "empty_compact_lookup"}

    draft_by_lookup: dict[int, dict[str, Any]] = {}
    for row in draft_rows:
        if not isinstance(row, dict):
            continue
        try:
            lookup_index = int(row.get("lookup_index") or 0)
        except (TypeError, ValueError):
            lookup_index = 0
        if lookup_index > 0 and lookup_index not in draft_by_lookup:
            draft_by_lookup[lookup_index] = row

    def lookup_context(lookup_index: int) -> dict[str, Any]:
        return compact_results[lookup_index - 1] if 1 <= lookup_index <= len(compact_results) else {}

    def unbound_row(lookup_index: int, *, title: str = "", unit: str = "", qty: Any = "", reason: str = "") -> dict[str, Any]:
        lookup = lookup_context(lookup_index)
        return {
            "basis": "нужен подбор нормы",
            "title": title or str(lookup.get("work_description") or f"Работа lookup {lookup_index}"),
            "unit": unit or str(lookup.get("unit_hint") or ""),
            "quantity": qty if qty not in (None, "") else "",
            "unit_price": "0.00",
            "amount": 0.0,
            "status": "norm_selection_required",
            "source_table": "structured model norm review",
            "lookup_index": lookup_index,
            "flags": reason or "ревизия модели не подтвердила норму из candidates",
        }

    def source_title_unit(lookup_index: int) -> tuple[str, str]:
        lookup = lookup_context(lookup_index)
        return str(lookup.get("work_description") or "").strip(), str(lookup.get("unit_hint") or "").strip()

    messages = [
        {
            "role": "system",
            "content": (
                "Ты главный сметчик-ревизор. Перед расчётом ЛСР проверь черновой выбор норм. "
                "Решение принимает модель, код только проверит, что norm_code скопирован из candidates. "
                "Верни строго JSON вида {\"rows\":[{\"lookup_index\":1,\"decision\":\"approve|replace|unbound\","
                "\"norm_code\":\"...\",\"title\":\"...\",\"unit\":\"...\",\"quantity\":1.0,\"reason\":\"...\"}]}. "
                "approve — оставить draft norm_code; replace — заменить на другой norm_code, но только из candidates "
                "этого lookup; unbound — оставить строку с нулём/пустой ценой и причиной. "
                "Обязательная проверка: норма не должна менять элемент и технологию на явно чужие. "
                "Но это pricing-stage: если точной нормы нет, сметчик должен выбрать ближайший защитимый "
                "нормативный аналог из candidates, когда совпадают семейство, физическая операция или ремонтный "
                "смысл, измеритель и ресурсная логика; в reason явно напиши, что это аналог и что проверить. "
                "unbound — только если все candidates пустые, без количества, с несовместимой единицей или "
                "описывают очевидно чужую операцию/объект. "
                "Для аналога должны быть защитимы фактическая операция, назначение элемента, измеритель и "
                "ресурсная логика. Не заменяй отсутствующую норму технологически чужой работой ради заполнения строки. "
                "В reason перечисли совпадения, различия и условия, которые должен проверить сметчик. "
                "Не пиши Markdown и не ставь цены."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": str(harness_question or "")[:18000],
                    "lookup_results": compact_results,
                    "draft_rows": draft_rows,
                    "rules": [
                        "return exactly one review row per lookup_index where a source work quantity exists",
                        "norm_code for replace must be copied exactly from that lookup candidates",
                        "approve if draft norm_code is technically defensible by title, norm_card, work_composition, element, unit and source-row intent",
                        "replace unbound draft rows when candidates contain a defensible normative analog, including repair/dismantling/replacement analogs",
                        "unbound only when candidates are empty, unit-incompatible, quantity-less or all clearly foreign operations/objects",
                        "do not price protective film covering with plaster, primer or painting candidates",
                        "quantity and unit should stay from source/draft unless draft is empty and source gives them",
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
    body = {
        "model": runtime.model,
        "messages": _mlx_prefill_no_think_messages(messages, runtime.provider),
        "temperature": 0,
        "max_tokens": _smeta_norm_choice_tokens(harness_question),
    }
    body = _cloud_body_for_model(body, runtime.model, runtime.provider)
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    timeout_sec = _smeta_norm_review_timeout(runtime)
    try:
        with httpx.Client(timeout=timeout_sec) as c:
            r = c.post(runtime.chat_url, headers=headers, json=body)
            r.raise_for_status()
            review_text = _assistant_text(r.json().get("choices", [{}])[0].get("message", {})).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[SMETA] structured norm review failed: %s", e)
        return draft_rows, {
            "enabled": True,
            "status": "review_error",
            "provider": runtime.provider,
            "model": runtime.model,
            "timeout_sec": timeout_sec,
            "error": f"{type(e).__name__}: {e}",
        }

    parsed = _extract_json_object(review_text) or {}
    raw_rows = parsed.get("rows") if isinstance(parsed.get("rows"), list) else []
    reviewed_by_lookup: dict[int, dict[str, Any]] = {}
    invalid_rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        try:
            lookup_index = int(raw.get("lookup_index") or 0)
        except (TypeError, ValueError):
            lookup_index = 0
        if lookup_index <= 0 or lookup_index > len(compact_results):
            invalid_rows.append({"lookup_index": lookup_index, "reason": "invalid_lookup_index"})
            continue
        reviewed_by_lookup[lookup_index] = raw

    final_rows: list[dict[str, Any]] = []
    approved = replaced = unbound = 0
    invalid_norm_codes: list[dict[str, Any]] = []
    for lookup_index in range(1, len(compact_results) + 1):
        draft = draft_by_lookup.get(lookup_index) or unbound_row(
            lookup_index,
            reason="черновой выбор не вернул строку для этого lookup",
        )
        review = reviewed_by_lookup.get(lookup_index)
        if not review:
            final_rows.append(draft)
            continue
        decision = str(review.get("decision") or "").strip().casefold()
        reason = str(review.get("reason") or "").strip()
        title = str(review.get("title") or draft.get("title") or "").strip()
        unit = str(review.get("unit") or draft.get("unit") or "").strip()
        qty = review.get("quantity")
        if qty in (None, ""):
            qty = draft.get("quantity")
        source_title, source_unit = source_title_unit(lookup_index)
        display_title = source_title or title
        display_unit = source_unit or unit
        if decision == "approve":
            basis = str(draft.get("basis") or "").strip()
            if basis and basis != "нужен подбор нормы" and basis in (allowed_by_lookup.get(lookup_index) or set()):
                approved += 1
                row = dict(draft)
                row["title"] = display_title or str(row.get("title") or "")
                row["unit"] = display_unit or str(row.get("unit") or "")
                row["source_table"] = "structured model norm review"
                row["review_reason"] = reason
                final_rows.append(row)
            else:
                unbound += 1
                final_rows.append(unbound_row(
                    lookup_index,
                    title=display_title,
                    unit=display_unit,
                    qty=qty,
                    reason=reason or "review approve без допустимого draft norm_code",
                ))
            continue
        if decision == "replace":
            code = str(review.get("norm_code") or "").strip()
            allowed = allowed_by_lookup.get(lookup_index) or set()
            if not code or code not in allowed:
                invalid_norm_codes.append({
                    "lookup_index": lookup_index,
                    "norm_code": code,
                    "reason": reason or "review_norm_code_not_in_lookup_candidates",
                })
                unbound += 1
                final_rows.append(unbound_row(
                    lookup_index,
                    title=display_title,
                    unit=display_unit,
                    qty=qty,
                    reason=reason or "review_norm_code_not_in_lookup_candidates",
                ))
                continue
            if qty in (None, "", 0, "0"):
                unbound += 1
                final_rows.append(unbound_row(
                    lookup_index,
                    title=display_title,
                    unit=display_unit,
                    reason=reason or "review replace без количества для расчёта",
                ))
                continue
            replaced += 1
            final_rows.append(
                {
                    "basis": code,
                    "title": display_title or f"Работа lookup {lookup_index}",
                    "unit": display_unit,
                    "quantity": qty,
                    "unit_price": "",
                    "amount": None,
                    "status": "model_reviewed_norm_code",
                    "source_table": "structured model norm review",
                    "lookup_index": lookup_index,
                    "choice_reason": str(draft.get("choice_reason") or ""),
                    "review_reason": reason,
                }
            )
            continue
        if decision == "unbound":
            unbound += 1
            final_rows.append(unbound_row(
                lookup_index,
                title=display_title,
                unit=display_unit,
                qty=qty,
                reason=reason or "review rejected draft norm_code",
            ))
            continue
        invalid_rows.append({"lookup_index": lookup_index, "decision": decision, "reason": "invalid_decision"})
        final_rows.append(draft)

    return final_rows, {
        "enabled": True,
        "status": "ok",
        "provider": runtime.provider,
        "model": runtime.model,
        "timeout_sec": timeout_sec,
        "selector_text": review_text[:4000],
        "approved": approved,
        "replaced": replaced,
        "unbound": unbound,
        "missing_review_rows": len(compact_results) - len(reviewed_by_lookup),
        "invalid_rows": invalid_rows,
        "invalid_norm_codes": invalid_norm_codes,
    }

def _smeta_direct_structured_norm_choice(
    harness_question: str,
    norm_lookup_trace: dict[str, Any],
    progress_sink: Callable[[dict[str, Any]], None] | None = None,
    *,
    _batched_child: bool = False,
) -> dict[str, Any]:
    """Ask the model to choose concrete norm codes from lookup results as JSON."""
    if not _env_bool("LES_SMETA_STRUCTURED_NORM_CHOICE_ENABLED", True):
        return {"rows": [], "trace": {"enabled": False}}
    results = norm_lookup_trace.get("results") if isinstance(norm_lookup_trace, dict) else None
    if not isinstance(results, list) or not results:
        return {"rows": [], "trace": {"enabled": True, "status": "no_lookup_results"}}

    runtime = _smeta_norm_choice_runtime()
    default_candidate_limit = 5 if runtime.provider in {"mlx", "local"} else 8
    candidate_limit = max(1, _env_int("LES_SMETA_NORM_CHOICE_CANDIDATES", default_candidate_limit))
    compact_results: list[dict[str, Any]] = []
    allowed_by_lookup: dict[int, set[str]] = {}
    candidate_meta_by_lookup: dict[int, dict[str, dict[str, Any]]] = {}
    for idx, item in enumerate(results, 1):
        if not isinstance(item, dict):
            continue
        call = item.get("call") if isinstance(item.get("call"), dict) else {}
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        candidates = []
        allowed: set[str] = set()
        candidate_meta: dict[str, dict[str, Any]] = {}
        for cand in (result.get("candidates") or [])[:candidate_limit]:
            if not isinstance(cand, dict):
                continue
            code = str(cand.get("norm_code") or "").strip()
            candidate_allowed = (
                str(cand.get("applicability_status") or "").strip().casefold() != "rejected"
                and cand.get("unit_compatible") is not False
            )
            if code and candidate_allowed:
                allowed.add(code)
            if code:
                candidate_meta[code] = {
                    "title": cand.get("title"),
                    "measure_unit": cand.get("measure_unit"),
                    "unit_compatible": cand.get("unit_compatible"),
                    "applicability_status": cand.get("applicability_status"),
                }
            candidates.append(
                {
                    "norm_code": code,
                    "title": cand.get("title"),
                    "measure_unit": cand.get("measure_unit"),
                    "unit_compatible": cand.get("unit_compatible"),
                    "applicability_status": cand.get("applicability_status"),
                    "score_total": cand.get("score_total"),
                    "norm_card": _smeta_norm_candidate_card(cand),
                }
            )
        allowed_by_lookup[idx] = allowed
        candidate_meta_by_lookup[idx] = candidate_meta
        compact_results.append(
            {
                "lookup_index": idx,
                "work_description": args.get("work_description"),
                "work_family": args.get("work_family"),
                "element_type": args.get("element_type"),
                "unit_hint": args.get("unit_hint"),
                "candidates": candidates,
            }
        )
    if not compact_results:
        return {"rows": [], "trace": {"enabled": True, "status": "empty_compact_lookup"}}

    # The model sees the whole professional task. Tool execution may batch,
    # but fixed row windows must not split norm selection into isolated worlds.
    batch_size = 0
    if batch_size and len(compact_results) > batch_size:
        total_batches = (len(results) + batch_size - 1) // batch_size
        all_rows: list[dict[str, Any]] = []
        batches: list[dict[str, Any]] = []
        accepted_rows: list[dict[str, Any]] = []
        draft_accepted_rows: list[dict[str, Any]] = []
        rejected_rows: list[dict[str, Any]] = []
        unbound_rows_added = 0
        draft_unbound_rows_added = 0
        review_summary = {
            "enabled": True,
            "status": "batched",
            "provider": runtime.provider,
            "model": runtime.model,
            "approved": 0,
            "replaced": 0,
            "unbound": 0,
            "missing_review_rows": 0,
            "invalid_rows": [],
            "invalid_norm_codes": [],
            "batches": [],
        }

        def remap_lookup(row: dict[str, Any], offset: int) -> dict[str, Any]:
            out = dict(row)
            try:
                local_idx = int(out.get("lookup_index") or 0)
            except (TypeError, ValueError):
                local_idx = 0
            if local_idx > 0:
                out["lookup_index"] = offset + local_idx
            return out

        def remap_list(rows: Any, offset: int) -> list[dict[str, Any]]:
            if not isinstance(rows, list):
                return []
            return [remap_lookup(row, offset) for row in rows if isinstance(row, dict)]

        def emit_batch(status: str, payload: dict[str, Any]) -> None:
            event_payload = {
                "phase": "norm_choice",
                "status": status,
                "provider": runtime.provider,
                "model": runtime.model,
                **payload,
            }
            logger.info(
                "[SMETA_BATCH] %s batch=%s/%s rows=%s-%s accepted=%s unbound=%s elapsed=%.1f status=%s",
                status,
                event_payload.get("batch"),
                event_payload.get("batch_count"),
                event_payload.get("start_lookup_index"),
                event_payload.get("end_lookup_index"),
                event_payload.get("accepted", ""),
                event_payload.get("unbound", ""),
                float(event_payload.get("elapsed_sec") or 0.0),
                event_payload.get("trace_status") or "",
            )
            if progress_sink is not None:
                try:
                    progress_sink({"event": "smeta_batch", "data": event_payload})
                except Exception as err:  # noqa: BLE001
                    logger.warning("[SMETA_BATCH] progress sink failed: %s", err)

        def fail_open_batch_rows(batch_results: list[Any], offset: int, reason: str) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for local_idx, item in enumerate(batch_results, 1):
                item = item if isinstance(item, dict) else {}
                call = item.get("call") if isinstance(item.get("call"), dict) else {}
                args = call.get("args") if isinstance(call.get("args"), dict) else {}
                rows.append(
                    {
                        "basis": "нужен подбор нормы",
                        "title": str(args.get("work_description") or f"Работа lookup {offset + local_idx}"),
                        "unit": str(args.get("unit_hint") or ""),
                        "quantity": "",
                        "unit_price": "0.00",
                        "amount": 0.0,
                        "status": "norm_selection_required",
                        "source_table": "structured model norm choice batch",
                        "lookup_index": offset + local_idx,
                        "flags": reason,
                    }
                )
            return rows

        for start in range(0, len(results), batch_size):
            batch_results = results[start:start + batch_size]
            if not batch_results:
                continue
            batch_no = len(batches) + 1
            batch_started = time.monotonic()
            start_lookup = start + 1
            end_lookup = start + len(batch_results)
            emit_batch(
                "started",
                {
                    "batch": batch_no,
                    "batch_count": total_batches,
                    "start_lookup_index": start_lookup,
                    "end_lookup_index": end_lookup,
                    "batch_size": len(batch_results),
                    "label": f"Смета: выбор норм {start_lookup}-{end_lookup}/{len(results)}",
                },
            )
            try:
                batch_packet = _smeta_direct_structured_norm_choice(
                    harness_question,
                    {"results": batch_results},
                    None,
                    _batched_child=True,
                )
            except Exception as err:  # noqa: BLE001
                logger.exception("[SMETA_BATCH] failed batch=%s/%s", batch_no, total_batches)
                batch_packet = {
                    "rows": [],
                    "trace": {
                        "enabled": True,
                        "status": "batch_exception",
                        "provider": runtime.provider,
                        "model": runtime.model,
                        "error": f"{type(err).__name__}: {err}",
                    },
                }
            batch_trace = batch_packet.get("trace") if isinstance(batch_packet.get("trace"), dict) else {}
            offset = start
            batch_rows = remap_list(batch_packet.get("rows"), offset)
            batch_fail_open_unbound = 0
            if not batch_rows:
                batch_rows = fail_open_batch_rows(
                    batch_results,
                    offset,
                    str(batch_trace.get("error") or batch_trace.get("status") or "selector returned no rows"),
                )
                batch_fail_open_unbound = len(batch_rows)
            all_rows.extend(batch_rows)
            accepted_rows.extend(remap_list(batch_trace.get("accepted_rows"), offset))
            draft_accepted_rows.extend(remap_list(batch_trace.get("draft_accepted_rows"), offset))
            rejected_rows.extend(remap_list(batch_trace.get("rejected_rows"), offset))
            unbound_rows_added += int(batch_trace.get("unbound_rows_added") or 0) + batch_fail_open_unbound
            draft_unbound_rows_added += int(batch_trace.get("draft_unbound_rows_added") or 0)
            batch_review = batch_trace.get("review") if isinstance(batch_trace.get("review"), dict) else {}
            for key in ("approved", "replaced", "unbound", "missing_review_rows"):
                review_summary[key] += int(batch_review.get(key) or 0)
            review_summary["invalid_rows"].extend(remap_list(batch_review.get("invalid_rows"), offset))
            review_summary["invalid_norm_codes"].extend(remap_list(batch_review.get("invalid_norm_codes"), offset))
            review_summary["batches"].append({
                "start_lookup_index": start + 1,
                "end_lookup_index": start + len(batch_results),
                "status": batch_review.get("status"),
                "approved": batch_review.get("approved"),
                "replaced": batch_review.get("replaced"),
                "unbound": batch_review.get("unbound"),
            })
            batches.append({
                "start_lookup_index": start + 1,
                "end_lookup_index": start + len(batch_results),
                "status": batch_trace.get("status"),
                "provider": batch_trace.get("provider"),
                "model": batch_trace.get("model"),
                "accepted": len(batch_trace.get("accepted_rows") or []),
                "unbound": int(batch_trace.get("unbound_rows_added") or 0) + batch_fail_open_unbound,
                "review": {
                    "status": batch_review.get("status"),
                    "approved": batch_review.get("approved"),
                    "replaced": batch_review.get("replaced"),
                    "unbound": batch_review.get("unbound"),
                },
                "selector_text": str(batch_trace.get("selector_text") or "")[:1200],
            })
            emit_batch(
                "done",
                {
                    "batch": batch_no,
                    "batch_count": total_batches,
                    "start_lookup_index": start_lookup,
                    "end_lookup_index": end_lookup,
                    "batch_size": len(batch_results),
                    "accepted": len(batch_trace.get("accepted_rows") or []),
                    "unbound": int(batch_trace.get("unbound_rows_added") or 0) + batch_fail_open_unbound,
                    "trace_status": str(batch_trace.get("status") or ""),
                    "review_status": str(batch_review.get("status") or ""),
                    "elapsed_sec": round(time.monotonic() - batch_started, 1),
                    "label": (
                        f"Смета: нормы {start_lookup}-{end_lookup}/{len(results)} "
                        f"готовы, принято {len(batch_trace.get('accepted_rows') or [])}, "
                        f"добор {int(batch_trace.get('unbound_rows_added') or 0) + batch_fail_open_unbound}"
                    ),
                },
            )

        return {
            "rows": all_rows,
            "trace": {
                "enabled": True,
                "status": "ok" if all_rows else "no_valid_choices",
                "model_owns_selection": True,
                "batched": True,
                "batch_size": batch_size,
                "batch_count": len(batches),
                "candidate_limit": candidate_limit,
                "provider": runtime.provider,
                "model": runtime.model,
                "timeout_sec": _env_float("LES_SMETA_NORM_CHOICE_TIMEOUT_SEC", 1200.0),
                "batch_timeout_sec": _env_float("LES_SMETA_NORM_CHOICE_BATCH_TIMEOUT_SEC", 180.0),
                "batches": batches,
                "accepted_rows": accepted_rows,
                "draft_accepted_rows": draft_accepted_rows,
                "unbound_rows_added": unbound_rows_added,
                "draft_unbound_rows_added": draft_unbound_rows_added,
                "rejected_rows": rejected_rows,
                "review": review_summary,
            },
        }

    messages = [
        {
            "role": "system",
            "content": (
                "Ты сметчик. Выбери нормы для расчёта, но только из candidates. "
                "Верни строго JSON вида {\"rows\":[{\"lookup_index\":1,\"title\":\"...\","
                "\"unit\":\"м\",\"quantity\":160,\"norm_code\":\"ГЭСНм:...\","
                "\"reason\":\"...\"}]}. Сверяй не только название, но и norm_card: title, "
                "work_composition.steps, domain/actions, измеритель, resources и conditions_to_check. "
                "Это pricing-stage: если точной нормы нет, но есть технически близкий accepted "
                "или unit_compatible candidate из правильного семейства/сборника, выбери лучший "
                "как нормативный аналог для расчёта и напиши в reason «нормативный аналог, проверить ...». "
                "Не обнуляй строку только потому, что основание/материал/условие не совпадает идеально. "
                "norm_code пустой только если все candidates описывают явно чужую операцию/чужое семейство "
                "или несовместимую единицу, candidates пустой, либо нет количества работы. "
                "Для аналога сопоставь фактическую операцию, назначение элемента, поверхность/среду, "
                "измеритель, состав работ, ресурсы и условия применения. Отличия явно перечисли в reason. "
                "Не выбирай технологически чужую работу только потому, что совпало одно слово или единица. "
                "Не ставь цены и не пиши Markdown."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": str(harness_question or "")[:18000],
                    "lookup_results": compact_results,
                        "rules": [
                            "norm_code must be copied exactly from candidates",
                            "pricing stage prefers a usable normative analog over empty norm_code when candidate family, collection and unit are technically close",
                            "if exact title/work_composition is missing, choose the closest accepted/unit-compatible candidate and mark reason as нормативный аналог for verification",
                            "do not select a candidate whose title/norm_card/work_composition is an obviously foreign operation or foreign family; leave norm_code empty and explain mismatch",
                            "an analog must preserve the physical operation, element purpose, measure, resource logic and applicable conditions",
                            "state every material, technology, surface, environment or scope difference in reason",
                            "do not select a technologically foreign candidate merely to avoid an unbound row",
                            "prefer candidates with unit_compatible=true and applicability_status accepted, but score is only retrieval evidence, not permission to price a wrong norm",
                            "quantity and unit come from the source task/work description",
                            "one output row per lookup where a work quantity exists",
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
    body = {
        "model": runtime.model,
        "messages": _mlx_prefill_no_think_messages(messages, runtime.provider),
        "temperature": 0,
        "max_tokens": _smeta_norm_choice_tokens(harness_question if not batch_size else "\n".join(
            str(item.get("work_description") or "") for item in compact_results
        )),
    }
    body = _cloud_body_for_model(body, runtime.model, runtime.provider)
    headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}
    prompt_chars = sum(
        len(str(message.get("content") or ""))
        for message in body.get("messages", [])
        if isinstance(message, dict)
    )
    prompt_est_tokens = max(1, round(prompt_chars / 4))
    compact_candidate_count = sum(len(item.get("candidates") or []) for item in compact_results)
    logger.info(
        "[SMETA_NORM_CHOICE] provider=%s model=%s rows=%s candidates=%s candidate_limit=%s "
        "prompt_chars=%s prompt_est_tokens=%s max_tokens=%s batch_child=%s",
        runtime.provider,
        runtime.model,
        len(compact_results),
        compact_candidate_count,
        candidate_limit,
        prompt_chars,
        prompt_est_tokens,
        body.get("max_tokens"),
        _batched_child,
    )
    try:
        timeout_default = _env_float("LES_SMETA_NORM_CHOICE_TIMEOUT_SEC", 1200.0)
        if _batched_child:
            child_default = min(timeout_default, 180.0) if runtime.provider in {"mlx", "local"} else timeout_default
            timeout_sec = _env_float("LES_SMETA_NORM_CHOICE_BATCH_TIMEOUT_SEC", child_default)
        else:
            timeout_sec = timeout_default
        with httpx.Client(timeout=timeout_sec) as c:
            r = c.post(runtime.chat_url, headers=headers, json=body)
            r.raise_for_status()
            selector_text = _assistant_text(r.json().get("choices", [{}])[0].get("message", {})).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[SMETA] structured norm choice failed: %s", e)
        return {
            "rows": [],
            "trace": {
                "enabled": True,
                "status": "selector_error",
                "provider": runtime.provider,
                "model": runtime.model,
                "timeout_sec": timeout_sec,
                "candidate_limit": candidate_limit,
                "candidate_count": compact_candidate_count,
                "prompt_chars": prompt_chars,
                "prompt_est_tokens": prompt_est_tokens,
                "error": f"{type(e).__name__}: {e}",
            },
        }

    parsed = _extract_json_object(selector_text) or {}
    raw_rows = parsed.get("rows") if isinstance(parsed.get("rows"), list) else []
    out_rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    handled_lookup_indexes: set[int] = set()

    def unbound_row(lookup_index: int, *, title: str = "", unit: str = "", qty: Any = "", reason: str = "") -> dict[str, Any]:
        lookup = compact_results[lookup_index - 1] if 1 <= lookup_index <= len(compact_results) else {}
        return {
            "basis": "нужен подбор нормы",
            "title": title or str(lookup.get("work_description") or f"Работа lookup {lookup_index}"),
            "unit": unit or str(lookup.get("unit_hint") or ""),
            "quantity": qty if qty not in (None, "") else "",
            "unit_price": "0.00",
            "amount": 0.0,
            "status": "norm_selection_required",
            "source_table": "structured model norm choice",
            "lookup_index": lookup_index,
            "flags": reason or "модель не выбрала технически защитимый norm_code из candidates",
        }

    def source_title_unit(lookup_index: int) -> tuple[str, str]:
        lookup = compact_results[lookup_index - 1] if 1 <= lookup_index <= len(compact_results) else {}
        return str(lookup.get("work_description") or "").strip(), str(lookup.get("unit_hint") or "").strip()

    def disallowed_code_reason(lookup_index: int, code: str, fallback: str) -> str:
        meta = (candidate_meta_by_lookup.get(lookup_index) or {}).get(code) if code else None
        if not isinstance(meta, dict):
            return fallback or "norm_code пустой или отсутствует в lookup candidates"
        status = str(meta.get("applicability_status") or "").strip().casefold()
        if status == "rejected":
            return "candidate_rejected_by_lookup"
        if meta.get("unit_compatible") is False:
            return "candidate_unit_mismatch_by_lookup"
        return fallback or "norm_code_not_allowed_by_lookup_candidates"

    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        try:
            lookup_index = int(raw.get("lookup_index") or 0)
        except (TypeError, ValueError):
            lookup_index = 0
        code = str(raw.get("norm_code") or "").strip()
        title = str(raw.get("title") or "").strip()
        unit = str(raw.get("unit") or "").strip()
        qty = raw.get("quantity")
        source_title, source_unit = source_title_unit(lookup_index)
        allowed = allowed_by_lookup.get(lookup_index) or set()
        if not code or code not in allowed:
            reason = disallowed_code_reason(
                lookup_index,
                code,
                str(raw.get("reason") or "norm_code пустой или отсутствует в lookup candidates"),
            )
            handled_lookup_indexes.add(lookup_index)
            rejected.append(
                {
                    "lookup_index": lookup_index,
                    "title": source_title or title,
                    "model_title": title,
                    "norm_code": code,
                    "reason": reason,
                }
            )
            out_rows.append(unbound_row(
                lookup_index,
                title=source_title or title,
                unit=source_unit or unit,
                qty=qty,
                reason=reason,
            ))
            continue
        if qty in (None, "", 0, "0"):
            handled_lookup_indexes.add(lookup_index)
            rejected.append(
                {
                    "lookup_index": lookup_index,
                    "title": source_title or title,
                    "model_title": title,
                    "norm_code": code,
                    "reason": "missing_quantity",
                }
            )
            out_rows.append(unbound_row(
                lookup_index,
                title=source_title or title,
                unit=source_unit or unit,
                reason="нет количества для расчёта строки",
            ))
            continue
        handled_lookup_indexes.add(lookup_index)
        out_rows.append(
            {
                "basis": code,
                "title": source_title or title or f"Работа lookup {lookup_index}",
                "unit": source_unit or unit,
                "quantity": qty,
                "unit_price": "",
                "amount": None,
                "status": "model_selected_norm_code",
                "source_table": "structured model norm choice",
                "lookup_index": lookup_index,
                "choice_reason": str(raw.get("reason") or ""),
            }
        )
    for lookup_index in range(1, len(compact_results) + 1):
        if lookup_index in handled_lookup_indexes:
            continue
        out_rows.append(unbound_row(
            lookup_index,
            reason="модель не вернула строку выбора нормы для этого lookup",
        ))
    reviewed_rows, review_trace = _smeta_review_structured_norm_choice(
        harness_question,
        compact_results,
        allowed_by_lookup,
        out_rows,
        runtime,
    )
    return {
        "rows": reviewed_rows,
        "trace": {
            "enabled": True,
            "status": "ok" if reviewed_rows else "no_valid_choices",
            "model_owns_selection": True,
            "provider": runtime.provider,
            "model": runtime.model,
            "timeout_sec": _env_float("LES_SMETA_NORM_CHOICE_TIMEOUT_SEC", 1200.0),
            "candidate_limit": candidate_limit,
            "candidate_count": compact_candidate_count,
            "prompt_chars": prompt_chars,
            "prompt_est_tokens": prompt_est_tokens,
            "selector_text": selector_text[:4000],
            "accepted_rows": [row for row in reviewed_rows if row.get("basis") != "нужен подбор нормы"],
            "draft_accepted_rows": [row for row in out_rows if row.get("basis") != "нужен подбор нормы"],
            "unbound_rows_added": len([row for row in reviewed_rows if row.get("basis") == "нужен подбор нормы"]),
            "draft_unbound_rows_added": len([row for row in out_rows if row.get("basis") == "нужен подбор нормы"]),
            "rejected_rows": rejected,
            "review": review_trace,
        },
    }

def _split_table_line(line: str) -> list[str]:
    text = str(line or "")
    text = re.sub(r"^[^|\n]{0,260}#t\d+r\d+:\s*", "", text)
    cells = [cell.strip() for cell in text.split("|")]
    if cells and not cells[0]:
        cells = cells[1:]
    if cells and not cells[-1]:
        cells = cells[:-1]
    return cells

def _find_mass_column(header: list[str]) -> int | None:
    best_idx: int | None = None
    best_score = 0
    for idx, cell in enumerate(header):
        low = cell.casefold()
        score = 0
        if "масса" in low:
            score += 3
        if "итого" in low:
            score += 2
        if "кг" in low:
            score += 1
        if "вес" in low and "масса" not in low:
            score += 1
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx if best_score >= 3 else None

def _smeta_direct_numeric_audit_context(text: str) -> str:
    """Build deterministic numeric audit hints from obvious mass tables.

    This is a calculator/provenance hint for the model. It does not choose
    works, norms or contractual quantities.
    """
    source = str(text or "")
    if "|" not in source or "масса" not in source.casefold():
        return ""
    lines = [line.strip() for line in source.splitlines() if "|" in line and line.strip()]
    audits: list[dict[str, Any]] = []
    header: list[str] | None = None
    mass_idx: int | None = None
    rows: list[dict[str, Any]] = []
    table_total: dict[str, Any] | None = None

    def flush_table() -> None:
        nonlocal rows, table_total
        if len(rows) < 2:
            rows = []
            table_total = None
            return
        compared: list[dict[str, Any]] = []
        if table_total:
            compared.append(table_total)
        text_total = _extract_text_mass_total(source)
        if text_total:
            compared.append(text_total)
        partial_groups = []
        if len(rows) > 2:
            partial_groups.append({
                "label": f"rows_1_{len(rows) - 1}",
                "input_labels": [row["label"] for row in rows[:-1]],
            })
        try:
            audits.append(quantity_sum_audit(
                name="mass_rows_sum",
                inputs=rows,
                unit="кг",
                compared_to=compared,
                partial_groups=partial_groups,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[SMETA_DIRECT_AUDIT] mass audit skipped: %s", exc)
        rows = []
        table_total = None

    for line in lines:
        cells = _split_table_line(line)
        if len(cells) < 3:
            continue
        if any("масса" in cell.casefold() for cell in cells):
            flush_table()
            header = cells
            mass_idx = _find_mass_column(cells)
            continue
        if mass_idx is None or header is None or mass_idx >= len(cells):
            continue
        first = cells[0].casefold()
        value = parse_ru_number(cells[mass_idx])
        if value is None:
            continue
        if "итого" in first:
            table_total = {"label": "table_total", "value": cells[mass_idx], "unit": "кг"}
            continue
        if not re.match(r"^\d+", cells[0]):
            continue
        label = f"row_{len(rows) + 1}"
        if len(cells) > 1 and cells[1]:
            safe_name = re.sub(r"\s+", "_", cells[1].strip().casefold())[:32]
            label = f"{label}_{safe_name}" if safe_name else label
        rows.append({"label": label, "value": cells[mass_idx], "unit": "кг"})
    flush_table()

    if not audits:
        return ""
    rendered: list[str] = []
    for audit in audits[:2]:
        rendered.append(
            f"- {audit['name']}: {audit['operation']} -> {audit['result']['value']} {audit['result']['unit']}; "
            f"alt={audit.get('result_alt_units', [])}; status={audit['status']}"
        )
        for cmp_item in audit.get("compared_to", []):
            rendered.append(
                f"  compare {cmp_item['label']}: {cmp_item['value']} {cmp_item['unit']}; "
                f"delta={cmp_item['delta']} {cmp_item['unit']}"
            )
        comparisons = audit.get("compared_to", [])
        if len(comparisons) >= 2:
            base = comparisons[0]
            for other in comparisons[1:]:
                try:
                    source_delta = round(float(base["value"]) - float(other["value"]), 2)
                except Exception:  # noqa: BLE001
                    continue
                rendered.append(
                    f"  source_delta {base['label']}_vs_{other['label']}: "
                    f"{source_delta} {base['unit']}"
                )
        for match in audit.get("partial_matches", []):
            if match.get("matches"):
                rendered.append(
                    f"  partial_match {match['label']}: {match['value']} {match['unit']} "
                    f"matches {match['matches']}"
                )
    return "\n".join(rendered)

def _extract_text_mass_total(text: str) -> dict[str, Any] | None:
    for pattern in (
        r"общая\s+масса[^\n]{0,120}?([0-9][0-9\s\xa0\u202f]*[,\.][0-9]+)\s*кг",
        r"масса[^\n]{0,80}?составляет[^\n]{0,80}?([0-9][0-9\s\xa0\u202f]*[,\.][0-9]+)\s*кг",
    ):
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return {"label": "text_total", "value": m.group(1), "unit": "кг"}
    return None
