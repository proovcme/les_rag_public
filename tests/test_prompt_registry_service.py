from proxy.services.prompt_registry_service import (
    build_mode_system_prompt,
    build_smeta_batch_system_prompt,
    mode_tools,
    prompt_registry_snapshot,
    reset_prompt_override,
    smeta_estimator_role_pack,
    update_prompt_override,
)


def test_prompt_registry_exposes_common_tone_modes_and_tools():
    snap = prompt_registry_snapshot()

    assert snap["schema"] == "prompt_registry_v2"
    assert "модель связывает" in snap["common"].lower()
    assert "ирони" in snap["tone"].lower()
    assert "smeta" in snap["modes"]
    assert "search_norm" in snap["modes"]["smeta"]["tools"]
    assert "retrieval" in snap["modes"]["rag"]["tools"]
    assert snap["role_packs"]["smeta_harness"]["id"] == "experienced_estimator_v1"
    assert snap["role_packs"]["smeta_harness"]["output_contract"]["schema"] == "smeta_work_plan_v1"


def test_mode_system_prompt_includes_mode_tone_without_tool_contracts():
    prompt = build_mode_system_prompt("rag")

    assert "evidence" in prompt.lower()
    assert "бардак" in prompt.lower()
    assert "Доступные инструменты режима" not in prompt
    assert "retrieval" not in prompt


def test_prompt_overrides_change_effective_prompts(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "proxy.services.prompt_registry_service._PROMPT_OVERRIDES_PATH",
        tmp_path / "prompt_overrides.json",
    )

    update_prompt_override("tone", "Говори живо, но считай строго.")
    update_prompt_override("modes.rag", "Режим RAG: сначала думай, потом ищи.")
    snap = prompt_registry_snapshot()

    assert snap["tone"] == "Говори живо, но считай строго."
    assert snap["modes"]["rag"]["prompt"] == "Режим RAG: сначала думай, потом ищи."
    assert any(item["key"] == "tone" and item["overridden"] for item in snap["editable"])
    prompt = build_mode_system_prompt("rag")
    assert "Говори живо, но считай строго." in prompt
    assert "Режим RAG: сначала думай, потом ищи." in prompt

    reset_prompt_override("tone")
    snap = prompt_registry_snapshot()
    assert snap["tone"] != "Говори живо, но считай строго."
    assert any(item["key"] == "tone" and not item["overridden"] for item in snap["editable"])


def test_smeta_prompt_is_model_first_and_has_no_object_templates():
    prompt = build_smeta_batch_system_prompt("Верни JSON.")
    low = prompt.lower()

    assert "модель сама раскладывает объект" in low
    assert "search_norm" in prompt
    assert "experienced_estimator_v1" in prompt
    assert "smeta_work_plan_v1" in prompt
    assert "не могут автоматически стать несколькими денежными позициями" in prompt
    assert "не одна самая заметная позиция" in prompt.lower()
    assert "счётные количества" in prompt.lower()
    assert "не отказывайся только потому, что нет проекта/ВОР/РД".lower() in prompt.lower()
    assert "условное здание/участок работ по допущениям" in prompt
    assert "поставка оборудования" in prompt.lower()
    assert "не ГЭСН search_norm" in prompt
    assert "object_templates" not in prompt
    assert "шаблон" not in low


def test_smeta_estimator_role_pack_is_json_contract():
    pack = smeta_estimator_role_pack()

    assert pack["schema"] == "les.prompt.role_pack.v1"
    assert pack["id"] == "experienced_estimator_v1"
    assert pack["output_contract"]["response_format"] == "json_object"
    assert "works" in pack["output_contract"]["top_level_required"]
    assert "mass_t" in pack["direct_quantity_policy"]["slots"]
    assert pack["object_decomposition_policy"]["rule"]
    assert any("не отказывайся" in item.lower() for item in pack["operating_principles"])
    assert any("поставка оборудования" in item.lower() for item in pack["operating_principles"])
    assert any("не проводи через search_norm" in item.lower() for item in pack["source_and_price_policy"])
    assert "dry" in pack["voice_policy"]["style"]


def test_mode_tools_unknown_is_empty():
    assert mode_tools("unknown") == []
