from extensions.lemonade.vendor_status import (
    EMBEDDING_BACKEND,
    EMBEDDING_CHUNK_OVERLAP,
    EMBEDDING_CHUNK_TOKENS,
    EMBEDDING_FAMILY,
    EMBEDDING_MODEL_ID,
    EMBEDDING_VECTOR_SIZE,
    lemonade_health_from_vendor,
)


def test_vendor_idle_guard_observes_direct_requests_and_fails_closed():
    from extensions.lemonade.vendor_status import VendorIdleGuard
    guard = VendorIdleGuard()
    def health(last_use=10, busy=False):
        return {"all_models_loaded": [{"model_name":"answer", "pid":42, "loaded":True,
                "last_use":last_use,"is_busy":busy,"is_streaming":False}]}
    assert not guard.may_unload(health(), now=0, idle_seconds=60)
    assert not guard.may_unload(health(), now=59, idle_seconds=60)
    assert not guard.may_unload(health(11), now=60, idle_seconds=60)
    assert not guard.may_unload(health(11, True), now=150, idle_seconds=60)
    assert not guard.may_unload(health(12), now=151, idle_seconds=60)
    assert guard.may_unload(health(12), now=211, idle_seconds=60)
    assert not guard.may_unload({"all_models_loaded":[{"model_name":"answer","loaded":True}]}, now=400, idle_seconds=60)
    assert not guard.may_unload(health(12), now=401, idle_seconds=60)
    assert not guard.may_unload(health(12), now=999, idle_seconds=0)


def test_vendor_health_keeps_unloaded_roles_factual():
    snapshot = lemonade_health_from_vendor(
        {
            "status": "ok",
            "all_models_loaded": [
                {
                    "model_name": "Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S",
                    "type": "llm",
                    "recipe": "llamacpp",
                    "device": "gpu",
                    "pid": 1234,
                }
            ],
        },
        chat_model="Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S",
        validation_model="qwen3.5-4b-FLM",
        rerank_model="Qwen3-Reranker-0.6B-Q8_0-GGUF",
    )

    roles = {descriptor.role: descriptor for descriptor in snapshot.models}
    assert snapshot.available is True
    assert roles["chat"].loaded is True
    assert roles["chat"].backend == "llama_cpp"
    assert roles["validation"].loaded is False
    assert roles["embedding"].loaded is False
    assert roles["rerank"].loaded is False


def test_vendor_health_requires_successful_upstream_shape():
    snapshot = lemonade_health_from_vendor(
        None,
        chat_model="Qwen3.6-35B",
        validation_model="Qwen3.5-4B-FLM",
        rerank_model="Qwen3-Reranker-0.6B-Q8_0-GGUF",
    )

    assert snapshot.available is False
    assert snapshot.detail == "vendor_health_unavailable"
    assert all(descriptor.loaded is False for descriptor in snapshot.models)


def test_embedding_identity_is_the_preserved_collection_contract():
    assert EMBEDDING_FAMILY == "Qwen/Qwen3-Embedding-0.6B"
    assert EMBEDDING_MODEL_ID == "Qwen3-Embedding-0.6B-GGUF"
    assert EMBEDDING_BACKEND == "llama_cpp"
    assert EMBEDDING_VECTOR_SIZE == 1024
    assert EMBEDDING_CHUNK_TOKENS == 430
    assert EMBEDDING_CHUNK_OVERLAP == 50


def test_recipe_options_bootstrap_only_fills_missing_entries():
    """Bootstrap добавляет ненастроенную модель и не трогает ручные настройки."""
    from extensions.lemonade.model_policy import plan_recipe_options_bootstrap

    existing = {
        "user.Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_S": {
            "ctx_size": 32768,
            "llamacpp_args": "--temp 1.0",  # ручная правка оператора
        },
        "builtin.Qwen3-Embedding-0.6B-GGUF": {"ctx_size": 2048},
    }
    catalogue = [
        "Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_M",   # в каталоге есть, настроек нет
        "Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_S",   # уже настроена вручную
        "Qwen3-Embedding-0.6B-GGUF",                    # не наша модель
    ]

    plan = plan_recipe_options_bootstrap(existing, catalogue)

    # Добавляется только ненастроенная Carnice.
    assert set(plan["add"]) == {"user.Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_M"}
    assert plan["add"]["user.Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_M"]["ctx_size"] == 32768
    # Ручная настройка сохранена, но расхождение показано оператору.
    assert "user.Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_S" in plan["differs"]
    assert plan["add"].get("builtin.Qwen3-Embedding-0.6B-GGUF") is None

    # Повторный запуск ничего не меняет.
    merged = {**existing, **plan["add"]}
    assert plan_recipe_options_bootstrap(merged, catalogue)["add"] == {}


def test_recipe_options_bootstrap_writes_only_missing_and_keeps_backup(tmp_path):
    """Применение bootstrap не теряет чужие записи и сохраняет прежний файл."""
    import json
    from extensions.lemonade.model_policy import apply_recipe_options_bootstrap

    path = tmp_path / "recipe_options.json"
    path.write_text(json.dumps({
        "builtin.Qwen3-Embedding-0.6B-GGUF": {"ctx_size": 2048},
        "user.Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_S": {"ctx_size": 32768},
    }, ensure_ascii=False), encoding="utf-8")

    report = apply_recipe_options_bootstrap(
        path, ["Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_M", "Qwen3-Embedding-0.6B-GGUF"]
    )

    written = json.loads(path.read_text(encoding="utf-8"))
    assert "user.Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_M" in written
    assert written["builtin.Qwen3-Embedding-0.6B-GGUF"] == {"ctx_size": 2048}
    assert written["user.Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_S"] == {"ctx_size": 32768}
    assert report["added"] == ["user.Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_M"]
    assert report["backup"] and (tmp_path / report["backup"]).exists()

    # Повтор идемпотентен и второй копии не плодит.
    again = apply_recipe_options_bootstrap(
        path, ["Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_M"]
    )
    assert again["added"] == [] and again["backup"] is None

    # Отсутствующий файл создаётся с нуля.
    fresh = tmp_path / "new.json"
    made = apply_recipe_options_bootstrap(fresh, ["Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_M"])
    assert fresh.exists() and made["added"]
