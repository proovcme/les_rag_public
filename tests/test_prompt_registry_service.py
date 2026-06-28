from proxy.services.prompt_registry_service import (
    build_mode_system_prompt,
    build_smeta_batch_system_prompt,
    mode_tools,
    prompt_registry_snapshot,
)


def test_prompt_registry_exposes_common_tone_modes_and_tools():
    snap = prompt_registry_snapshot()

    assert snap["schema"] == "prompt_registry_v2"
    assert "модель связывает" in snap["common"].lower()
    assert "ирони" in snap["tone"].lower()
    assert "smeta" in snap["modes"]
    assert "search_norm" in snap["modes"]["smeta"]["tools"]
    assert "retrieval" in snap["modes"]["rag"]["tools"]


def test_mode_system_prompt_includes_mode_tone_and_tools():
    prompt = build_mode_system_prompt("rag")

    assert "evidence" in prompt.lower()
    assert "бардак" in prompt.lower()
    assert "retrieval" in prompt


def test_smeta_prompt_is_model_first_and_has_no_object_templates():
    prompt = build_smeta_batch_system_prompt("Верни JSON.")
    low = prompt.lower()

    assert "модель сама раскладывает объект" in low
    assert "search_norm" in prompt
    assert "object_templates" not in prompt
    assert "шаблон" not in low


def test_mode_tools_unknown_is_empty():
    assert mode_tools("unknown") == []
