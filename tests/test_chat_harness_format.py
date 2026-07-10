from types import SimpleNamespace

import pytest

from proxy.routers.chat import (
    ChatRequest,
    _compact_question_excerpt,
    _estimate_harness_plan_tokens,
    _format_harness,
    _format_harness_artifact,
    _format_smeta_dialog_state,
    _harness_voice_comment,
    _mlx_prefill_no_think_messages,
    _smeta_active_state_from_answer,
    _smeta_direct_rag_context,
    _smeta_direct_norm_lookup_context,
    _format_smeta_norm_lookup_results_for_model,
    _smeta_direct_model_answer,
    _smeta_direct_max_tokens,
    _smeta_model_runtime,
    _smeta_direct_norm_candidate_stage_required,
    _smeta_direct_previous_norm_lookup_packet_for_followup,
    _smeta_direct_previous_norm_lookup_trace,
    _smeta_direct_prices_previous_candidates_request,
    _smeta_direct_structured_norm_choice,
    _smeta_direct_user_prompt,
    _smeta_direct_workflow_decision,
    _smeta_norm_lookup_max_calls,
    _smeta_source_row_count,
    _format_active_smeta_state,
    _smeta_harness_question,
    _should_use_model_first_smeta,
    _smeta_model_first_answer,
    _smeta_dialog_state,
    _voice_claims_source_truncated,
    _mlx_runtime,
    _parse_model_tool_calls,
    _augment_model_tool_args,
    _format_tool_results_for_model,
    _chat_model_final_answer,
)
from proxy.services.estimate_harness_service import _action_title_score


def test_harness_answer_is_operator_facing_with_numbers():
    text = _format_harness({
        "schema": {"object_type": "residential_house", "area_total_m2": 150},
        "total_status": "complete",
        "computed": [{
            "work": "Каркасные стены",
            "code": "ГЭСН:10-02-017-03",
            "qty": 1.86,
            "norm_unit": "100 м2",
            "phys_qty": 186.0,
            "physical_unit": "м2",
            "assumptions": ["норма выбрана по лучшему кандидату; требуется проверка"],
        }],
        "needs_input": [],
        "rejected": [],
        "partial_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "final_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "trace": [{"tool": "search_norm"}],
        "steps": 1,
    })

    assert text.startswith("**Предварительная сметная стоимость**")
    assert "Итого" in text
    assert "1 200.00" in text
    assert "Каркасные стены" in text
    assert "ГЭСН:10-02-017-03" in text
    assert "Планировщик" not in text
    assert "search_norm" not in text
    assert "декомпозиция" not in text.lower()


def test_mlx_prefill_no_think_messages_only_for_local_mlx():
    messages = [{"role": "user", "content": "ответь"}]

    mlx_messages = _mlx_prefill_no_think_messages(messages, "mlx")
    cloud_messages = _mlx_prefill_no_think_messages(messages, "openai")

    assert mlx_messages[-1]["role"] == "assistant"
    assert "<think>" in mlx_messages[-1]["content"]
    assert cloud_messages == messages


def test_mlx_runtime_defaults_to_mlx_model(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("MLX_MODEL", "mlx-community/Qwen3.5-9B-MLX-4bit")

    runtime = _mlx_runtime()

    assert runtime.model == "mlx-community/Qwen3.5-9B-MLX-4bit"


def test_smeta_model_runtime_defaults_to_local_even_when_global_cloud_is_available(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.api.proxyapi.ru/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4")
    monkeypatch.delenv("LES_SMETA_PROVIDER", raising=False)
    monkeypatch.delenv("LES_SMETA_DIRECT_MODEL_PROVIDER", raising=False)

    runtime = _smeta_model_runtime("LES_SMETA_DIRECT_MODEL_PROVIDER")

    assert runtime.provider == "mlx"


def test_smeta_model_runtime_explicit_mlx_overrides_global_cloud(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.api.proxyapi.ru/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4")
    monkeypatch.setenv("LES_SMETA_PROVIDER", "mlx")
    monkeypatch.delenv("LES_SMETA_DIRECT_MODEL_PROVIDER", raising=False)

    runtime = _smeta_model_runtime("LES_SMETA_DIRECT_MODEL_PROVIDER")

    assert runtime.provider == "mlx"


def test_smeta_model_runtime_can_explicitly_follow_global_provider(monkeypatch):
    monkeypatch.setenv("LES_SMETA_DIRECT_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("LES_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("OPENAI_MODEL", "local-compatible")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    runtime = _smeta_model_runtime("LES_SMETA_DIRECT_MODEL_PROVIDER")

    assert runtime.provider == "openai"
    assert runtime.model == "local-compatible"


def test_chat_model_final_answer_preserves_text_on_validator_block():
    answer, status, policy = _chat_model_final_answer("Модельный инженерный ответ", "UNKNOWN")

    assert answer == "Модельный инженерный ответ"
    assert status == "UNVALIDATED"
    assert policy["schema"] == "chat_model_final_preservation_v1"
    assert policy["original_status"] == "UNKNOWN"


def test_chat_model_final_answer_preserves_hallucination_label_as_warning():
    answer, status, policy = _chat_model_final_answer("Не прятать готовый ответ", "HALLUCINATION")

    assert answer == "Не прятать готовый ответ"
    assert status == "UNVALIDATED"
    assert policy["reason"] == "validator_warns_without_replacing_model_answer"


def test_model_tool_call_parser_accepts_only_allowed_json_calls():
    text = """
    ```json
    {"calls":[
      {"tool":"dataset_map","args":{"depth":"deep"}},
      {"tool":"unknown_tool","args":{}},
      {"tool":"search_sources","args":{"q":"пожарная сигнализация"}}
    ]}
    ```
    """

    calls = _parse_model_tool_calls(text, allowed_tools={"dataset_map", "search_sources"}, max_calls=5)

    assert calls == [
        {"tool": "dataset_map", "args": {"depth": "deep"}},
        {"tool": "search_sources", "args": {"q": "пожарная сигнализация"}},
    ]


def test_model_tool_args_are_scoped_to_selected_dataset_and_target_file():
    call = _augment_model_tool_args(
        {"tool": "read_pdf_source", "args": {}},
        question="сделай ЛСР",
        dataset_ids=["ds1"],
        target_file_ref={"match_status": "matched", "file_name": "ВОР.pdf", "dataset_id": "ds2"},
    )

    assert call["tool"] == "read_pdf_source"
    assert call["args"]["q"] == "сделай ЛСР"
    assert call["args"]["dataset_id"] == "ds2"
    assert call["args"]["doc_name"] == "ВОР.pdf"


def test_tool_results_prompt_block_is_material_not_final_answer():
    text = _format_tool_results_for_model([
        {
            "tool": "search_sources",
            "status": "ok",
            "result": {"count": 1, "hits": [{"text": "Источник"}]},
            "sources": [{"doc": "A.pdf"}],
        }
    ])

    assert "РЕЗУЛЬТАТЫ ИНСТРУМЕНТОВ LES" in text
    assert "не готовый ответ" in text
    assert "search_sources" in text


def test_smeta_direct_prompt_includes_available_pricebooks_without_region_hardcode(monkeypatch):
    monkeypatch.setattr(
        "proxy.services.fgis_price_service.available_pricebooks",
        lambda *args, **kwargs: [
            "/tmp/moskva_2kv2026.parquet",
            "/tmp/krasnodarskiy-kray_2kv2026.parquet",
            "/tmp/spb_2kv2026.parquet",
        ],
    )

    prompt = _smeta_direct_user_prompt(
        "Дай оценку по РИМ, Краснодарский край, 2 кв. 2026",
        "",
        "",
        light=True,
    )

    assert "krasnodarskiy-kray_2kv2026" in prompt
    assert "moskva_2kv2026" in prompt
    assert "spb_2kv2026" in prompt
    assert "сначала смотри в эти книги и RAG" in prompt
    assert "Системная книга по умолчанию при неуказанном регионе: spb_2kv2026" in prompt
    assert "спроси именно регион/период" in prompt
    assert "Карта сметного RAG ЛЕС" in prompt
    assert "Основные карточки сборников" in prompt
    assert "это карта доступных сметных источников ЛЕС, а не готовая смета" in prompt


def test_smeta_direct_prompt_exposes_physical_service_source_readiness(monkeypatch):
    monkeypatch.setattr(
        "proxy.services.service_source_registry.service_sources",
        lambda: {
            "sources": [
                {
                    "id": "gesn_base",
                    "label": "ГЭСН-2022: нормы и ресурсы",
                    "status": "ok",
                    "facts": {"parquet_rows": 609987, "base_norms": 42572},
                },
                {
                    "id": "fgis_price_base",
                    "label": "ФГИС ЦС: Сплит-формы цен",
                    "status": "ok",
                    "facts": {"pricebooks": 47, "price_rows": 12816756},
                },
                {
                    "id": "smeta_coefficients",
                    "label": "Сметные коэффициенты и правила",
                    "status": "ok",
                    "facts": {},
                },
            ]
        },
    )
    monkeypatch.setattr("proxy.services.fgis_price_service.available_pricebooks", lambda *args, **kwargs: [])

    prompt = _smeta_direct_user_prompt("сделай ЛСР", "", "", light=True)

    assert "Системные сметные источники ЛЕС физически подключены" in prompt
    assert "ГЭСН-2022: нормы и ресурсы: ok" in prompt
    assert "base_norms=42572" in prompt
    assert "ФГИС ЦС: Сплит-формы цен: ok" in prompt
    assert "pricebooks=47" in prompt
    assert "нет blocking-missing по ГЭСН/ФГИС/НРСП" in prompt


def test_harness_voice_allows_short_human_comment(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Считаю то, что можно привязать к нормам.\n"
                "А спорное пока не тащу в итог: смета не место для гадания."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._smeta_model_runtime", lambda env_name: SimpleNamespace(
        model="test-model", provider="mlx", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({"computed": [{}], "needs_input": [{}]}, "вопрос")

    assert "Считаю то" in text
    assert "\n" in text


def test_harness_plan_budget_scales_for_large_tz_context():
    small = [{"role": "user", "content": "скамья 3 шт"}]
    medium = [{"role": "user", "content": "ВОР\n" + ("строка\n" * 900)}]
    large = [{"role": "user", "content": "ВОР\n" + ("строка\n" * 1800)}]

    assert _estimate_harness_plan_tokens(small) == 1100
    assert _estimate_harness_plan_tokens(medium) == 1800
    assert _estimate_harness_plan_tokens(large) == 2400


def test_harness_voice_has_safe_excerpt_and_no_fake_truncation_claim():
    long_question = "начало ТЗ\n" + ("строка ведомости\n" * 180) + "конец ТЗ"
    excerpt = _compact_question_excerpt(long_question, max_chars=600)

    assert excerpt["truncated"] is True
    assert "начало ТЗ" in excerpt["text"]
    assert "конец ТЗ" in excerpt["text"]
    assert _voice_claims_source_truncated("исходные обрываются на п.9, пришлите продолжение")
    assert not _voice_claims_source_truncated("нужно уточнить толщину стены и способ монтажа")


def test_harness_voice_suppresses_unsupported_attachment_truncation_claim(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Исходные обрываются на пункте 9, пришлите продолжение ведомости."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._smeta_model_runtime", lambda env_name: SimpleNamespace(
        model="test-model", provider="mlx", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({"total_status": "blocked", "needs_input": [{}]}, "ВОР\n" + ("x" * 3000))

    assert text == ""


def test_blocked_all_harness_switches_to_model_first_smeta():
    assert _should_use_model_first_smeta({
        "total_status": "blocked",
        "computed": [],
        "rejected": [{"work": "Монтаж"}],
    })
    assert not _should_use_model_first_smeta({
        "total_status": "partial",
        "computed": [{"work": "Монтаж"}],
        "rejected": [{"work": "Окраска"}],
    })


def test_smeta_model_first_answer_uses_model_when_harness_blocks(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "По ТЗ вижу 3 скамьи, а деталировка дана на одну.\n"
                "| Работа | На 1 скамью | Итого |\n"
                "|---|---:|---:|\n"
                "| Бетонное основание | 0,4 м3 | 1,2 м3 |\n"
                "| Стяжка ЦПС | 0,07 м3 | 0,21 м3 |\n"
                "Деньги требуют региона, базы цен и КАЦ/КП по материалам."
            )}}]}

    class FakeClient:
        last_json = None

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            FakeClient.last_json = kwargs.get("json")
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _smeta_model_first_answer(
        "Текущий запрос:\nСмета по скамье\n\nКонтекст прикреплённого файла:\nВОР: 3 скамьи, бетон 0,4 м3",
        {"total_status": "blocked", "rejected": [{"work": "Бетон", "reason": "нужно уточнить норму"}]},
    )

    assert "3 скамьи" in text
    assert "1,2 м3" in text
    prompt_payload = FakeClient.last_json["messages"][1]["content"]
    assert "blocked_harness_advisory" in prompt_payload
    assert "ВОР: 3 скамьи" in prompt_payload


def test_smeta_direct_model_answer_does_not_need_harness_result(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "По ТЗ беру 3 скамьи, деталировка дана на одну.\n"
                "| Позиция | На 1 скамью | Итого на 3 |\n"
                "|---|---:|---:|\n"
                "| Гранит Г1 | 4 шт | 12 шт |\n"
                "| Бетон В25 | 0,4 м3 | 1,2 м3 |\n"
                "Код-калькулятор понадобится дальше для норм, цен, НР/СП и проверки единиц."
            )}}]}

    class FakeClient:
        last_json = None

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            FakeClient.last_json = kwargs.get("json")
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    monkeypatch.setenv("LES_SMETA_DIRECT_LIGHT_PROMPT", "0")

    text = _smeta_direct_model_answer(
        "Текущий запрос:\nСделай смету по скамье\n\nКонтекст прикреплённого файла:\n3 скамьи; Г1 4 шт; бетон 0,4 м3",
        "Проверяемые фрагменты из выбранного RAG-корпуса:\n[Источник 1 | нормы.docx]:\nГранитные элементы требуют КАЦ.",
    )

    assert "12 шт" in text
    assert "1,2 м3" in text
    prompt_payload = FakeClient.last_json["messages"][1]["content"]
    assert "3 скамьи" in prompt_payload
    assert "Гранитные элементы требуют КАЦ" in prompt_payload
    assert "ВОР -> кандидаты ГЭСН" in prompt_payload
    assert "Не считай деньги" in prompt_payload
    assert "таблицу доступных candidates" in prompt_payload
    assert "следующий ход «деньги по ним»" in prompt_payload
    assert "Строка ВСЕГО" not in prompt_payload
    assert "не заменяй демонтаж" in FakeClient.last_json["messages"][0]["content"]
    assert "ВОР -> нормируемая ВОР -> таблица подбора норм" in FakeClient.last_json["messages"][0]["content"]
    assert "Excel-таблицу подбора норм" in FakeClient.last_json["messages"][0]["content"]
    assert "одна строка исходной вор может раскладываться" in FakeClient.last_json["messages"][0]["content"].lower()
    assert "не пиши, что пользователь их не дал" in FakeClient.last_json["messages"][0]["content"]
    assert "какие числа сложены" in FakeClient.last_json["messages"][0]["content"]
    assert "прежняя оценка" in FakeClient.last_json["messages"][0]["content"]
    assert "Упаковка, тара, такелаж и оснастка не становятся отдельными платными разделами" in FakeClient.last_json["messages"][0]["content"]
    assert "scenario_estimate" in FakeClient.last_json["messages"][0]["content"]
    assert "Не заменяй построчную ВОР одной крупной вилкой" in FakeClient.last_json["messages"][0]["content"]
    assert "Повтор одного и того же исходника должен сохранять базовый сценарий" in FakeClient.last_json["messages"][0]["content"]
    assert "не называй сценарную таблицу готовой лср" in FakeClient.last_json["messages"][0]["content"].lower()
    assert "Способ выдачи сметы для оператора — ЛСР-форма" in FakeClient.last_json["messages"][0]["content"]
    assert "сохраняй уже принятые строки, ставки и итоги" in FakeClient.last_json["messages"][0]["content"].lower()
    assert "не сокращай 19 строк до 12" in FakeClient.last_json["messages"][0]["content"]
    assert "заполненный шаблон ЛСР граф 1-12" in FakeClient.last_json["messages"][0]["content"]
    assert "Строка ВСЕГО по смете обязательна" in FakeClient.last_json["messages"][0]["content"]
    assert "144*20%*10=288" not in FakeClient.last_json["messages"][0]["content"]
    assert "blocked_harness_advisory" not in prompt_payload


def test_smeta_direct_model_answer_returns_empty_on_model_failure(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise TimeoutError("model timeout")

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _smeta_direct_model_answer(
        "Текущий запрос:\nсделай ЛСР по ВОР монтаж аварийного питания",
        "Проверяемые фрагменты из выбранного RAG-корпуса:\nВОР содержит монтажные строки.",
    )

    assert text == ""


def test_smeta_direct_light_prompt_cuts_heavy_contract_by_default(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Считаю РИМ-сценарием по нормативным аналогам, не финальная ЛСР.\n"
                "| Работа | Объём | Нормативный ход | Сумма |\n"
                "|---|---:|---|---:|\n"
                "| Монтаж | 10 т | ГЭСН-аналог | 1 000 000 |\n"
            )}}]}

    class FakeClient:
        last_json = None

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            FakeClient.last_json = kwargs.get("json")
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    monkeypatch.delenv("LES_SMETA_DIRECT_LIGHT_PROMPT", raising=False)

    text = _smeta_direct_model_answer(
        "Текущий запрос:\nДай оценку стоимости работ\n\nКонтекст прикреплённого файла:\nВОР: монтаж 10 т",
        "Проверяемые фрагменты из выбранного RAG-корпуса:\nГЭСН, ФГИС, НР/СП доступны.",
    )

    assert "РИМ-сценарием" in text
    sys_prompt = FakeClient.last_json["messages"][0]["content"]
    assert "Работай как сметчик, а не как чат-бот" in sys_prompt
    assert "по сырому ТЗ/ВОР/спецификации сначала выдавай этап" in sys_prompt
    assert "ЛСР с рублями — следующим ходом по candidates модели" in sys_prompt
    assert "дай нормативный аналог или раздел с пометкой проверки" in sys_prompt
    assert "Пустые ценовые колонки" in sys_prompt
    assert "строй ВОР" in sys_prompt
    assert "нет данных -> ставь 0.00" in sys_prompt
    assert "графа «Обоснование»" in sys_prompt
    assert FakeClient.last_json["temperature"] == 0.0
    assert "Один и тот же исходник должен давать один и тот же базовый сценарий" in sys_prompt
    assert "Не называй сценарную таблицу готовой ЛСР" in sys_prompt
    assert "Способ выдачи сметы — ЛСР-форма" in sys_prompt
    assert "Для pricing-stage сразу заполни ЛСР граф 1-12" in sys_prompt
    assert "ВСЕГО по смете" in sys_prompt
    assert "выбранная моделью норма, аналог/раздел" in sys_prompt
    assert "не пиши одиноко" in sys_prompt
    assert "ГЭСНм10" in sys_prompt
    assert "Раздел ВОР не равен одному сборнику" in sys_prompt
    assert "role-pack" not in sys_prompt
    assert "harness" not in sys_prompt
    assert "evidence" not in sys_prompt
    assert "Компактный машинный контракт" not in sys_prompt
    assert "ВОР -> нормируемая ВОР -> таблица подбора норм" not in sys_prompt
    assert len(sys_prompt) < 2500


def test_smeta_direct_prompt_does_not_block_on_empty_spec_price_columns(monkeypatch):
    monkeypatch.setattr("proxy.services.fgis_price_service.available_pricebooks", lambda *args, **kwargs: [])

    prompt = _smeta_direct_user_prompt(
        "Оцени стоимость по спецификации СКС: кабель 1200 м, розетки 80 шт, "
        "колонки цена за ед. и итого стоимость пустые",
        "",
        "",
        light=True,
    )

    assert "ВОР -> кандидаты ГЭСН" in prompt
    assert "Не считай деньги" in prompt
    assert "таблицу доступных candidates" in prompt
    assert "следующий ход «деньги по ним»" in prompt


def test_smeta_direct_method_prompt_does_not_force_lsr_or_zero_money(monkeypatch):
    monkeypatch.setattr("proxy.services.fgis_price_service.available_pricebooks", lambda *args, **kwargs: [])

    prompt = _smeta_direct_user_prompt(
        "Сметный тест без расчета: покажи порядок работы, таблицу кандидатов норм и добор ресурсов. Без рублей.",
        "",
        "",
        light=True,
    )

    assert "не является командой посчитать или оформить ЛСР" in prompt
    assert "Не делай ЛСР-таблицу" in prompt
    assert "не ставь нулевые рубли" in prompt
    assert "не пиши строку ВСЕГО" in prompt
    assert "несколько строк ВОР могут ссылаться на одну норму" in prompt
    assert "ГЭСН, ГЭСНм, ГЭСНп, ГЭСНр, ГЭСНмр" in prompt
    assert "семейство работ -> группа сборников -> сборник -> раздел/таблица -> конкретная норма" in prompt
    assert "ресурсы выбранной" in prompt
    assert "не нераспознанные работы" in prompt
    assert "не обещай" in prompt
    assert "следующим сообщением" in prompt
    assert "Не используй Markdown-заголовки" in prompt
    assert "Строка ВСЕГО по смете обязательна" not in prompt
    assert "ВСЕГО тоже числом 0.00" not in prompt


def test_smeta_direct_process_explanation_prompt_does_not_force_lsr(monkeypatch):
    monkeypatch.setattr("proxy.services.fgis_price_service.available_pricebooks", lambda *args, **kwargs: [])

    prompt = _smeta_direct_user_prompt(
        "Объясни оператору, как ты работаешь по сметам в ЛЕС: какие шаги делаешь от исходников "
        "до ЛСР, что выбираешь ты, что считает код, когда нужны нули и примечания.",
        "",
        "",
        light=True,
    )

    assert "не является командой посчитать или оформить ЛСР" in prompt
    assert "Не делай ЛСР-таблицу" in prompt
    assert "не ставь нулевые рубли" in prompt
    assert "что считает код" in prompt
    assert "Строка ВСЕГО по смете обязательна" not in prompt
    assert "ВСЕГО тоже числом 0.00" not in prompt


def test_smeta_direct_prompt_keeps_norm_selection_model_first(monkeypatch):
    monkeypatch.setattr("proxy.services.fgis_price_service.available_pricebooks", lambda *args, **kwargs: [])

    prompt = _smeta_direct_user_prompt(
        "Этап 1: дай таблицу кандидатов ГЭСН. СКС кабель Cat.6A 1200 м, розетки RJ-45 80 шт, "
        "патч-панели 4 шт, шкаф 42U 1 шт. аварийное питание 30 шт, подключение и пусконаладка.",
        "",
        "",
        light=True,
        workflow_stage="norm_candidates",
    )

    assert "search_norm" not in prompt
    assert "Карточки нормативного поиска ЛЕС" not in prompt
    assert "ВОР -> кандидаты ГЭСН" in prompt
    assert "Не считай деньги" in prompt
    assert "| № ВОР | Исходная работа | Ед. ВОР" in prompt
    assert "Если у одной строки ВОР несколько кандидатов" in prompt
    assert "нормативный маршрут" in prompt
    assert "деньги по ним" in prompt
    assert "Нормы из локальной базы ЛЕС к исходным работам" not in prompt


def test_smeta_direct_norm_lookup_is_model_selected(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"calls":[{"tool":"search_norm","args":{'
                                '"work_description":"монтаж стальных конструкций краном",'
                                '"work_family":"metal","element_type":"metal_assembly",'
                                '"action":"монтаж","unit_hint":"т"}}]}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    captured_search = {}

    def fake_search_norm(*args, **kwargs):
        captured_search["top_k"] = kwargs.get("top_k")
        return {
            "status": "ambiguous",
            "work_family": kwargs.get("work_family"),
            "element_type": kwargs.get("element_type"),
            "norm_store": {"base_norms": 1},
            "candidates": [
                {
                    "norm_code": "09-03-002-01",
                    "title": "Монтаж стальных конструкций",
                    "measure_unit": "т",
                    "unit_compatible": True,
                    "applicability_status": "accepted",
                    "score_total": 9.0,
                }
            ],
            "norm_navigation": {"questions_to_ask": []},
        }

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    monkeypatch.setattr("proxy.services.estimate_harness_service.search_norm", fake_search_norm)

    packet = _smeta_direct_norm_lookup_context("Сделай ЛСР на монтаж стальных конструкций 10 т")

    assert packet["trace"]["model_owns_selection"] is True
    assert packet["trace"]["selected_calls"][0]["tool"] == "search_norm"
    assert "09-03-002-01" in packet["text"]
    assert "не готовая смета" in packet["text"]
    assert "Запрещено ставить модельную ставку" in packet["text"]
    assert captured_search["top_k"] == 25


def test_smeta_norm_lookup_prompt_keeps_deeper_candidate_window(monkeypatch):
    monkeypatch.delenv("LES_SMETA_NORM_LOOKUP_PROMPT_CANDIDATES", raising=False)
    monkeypatch.delenv("LES_SMETA_NORM_LOOKUP_CONTEXT_CHARS", raising=False)
    candidates = [
        {
            "norm_code": f"ГЭСН:15-01-047-{idx:02d}",
            "title": f"Кандидат {idx}",
            "measure_unit": "100 м2",
            "unit_compatible": True,
            "applicability_status": "accepted",
            "score_total": 10.0 - idx / 100,
        }
        for idx in range(1, 22)
    ]

    text = _format_smeta_norm_lookup_results_for_model([
        {
            "call": {"tool": "search_norm", "args": {"work_description": "реечный потолок"}},
            "result": {"status": "ambiguous", "candidates": candidates},
        }
    ])

    assert "ГЭСН:15-01-047-20" in text
    assert "ГЭСН:15-01-047-21" not in text


def test_smeta_norm_lookup_policy_keeps_eom_containment_out_of_metal_family(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"calls":[]}'}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            captured["json"] = kwargs["json"]
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    _smeta_direct_norm_lookup_context(
        "Сделай ЛСР: гофра ПВХ 160 м, скобы однолапковые 320 шт, коробка огнестойкая 8 шт, БАП 16 шт"
    )

    user_payload = captured["json"]["messages"][-2]["content"]
    assert "скобы крепления гофры/коробки проводки/аварийное питание" in user_payload
    assert "маршрутизируй как electric, а не как metal" in user_payload
    assert "не уводи строку в бункеры/опорные металлоконструкции ГЭСН09" in user_payload


def test_smeta_structured_norm_choice_validates_model_code_from_lookup(monkeypatch):
    monkeypatch.setenv("LES_SMETA_NORM_REVIEW_ENABLED", "0")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"rows":[{"lookup_index":1,"title":"Монтаж стальных конструкций",'
                                '"unit":"т","quantity":2,"norm_code":"ГЭСНм:38-01-001-01",'
                                '"reason":"подходит по металлоконструкциям"}]}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    lookup_trace = {
        "results": [
            {
                "call": {
                    "tool": "search_norm",
                    "args": {
                        "work_description": "монтаж стальных конструкций",
                        "work_family": "metal",
                        "element_type": "metal_assembly",
                        "unit_hint": "т",
                    },
                },
                "result": {
                    "candidates": [
                        {
                            "norm_code": "ГЭСНм:38-01-001-01",
                            "title": "Листовые конструкции массой свыше 0,5 т",
                            "measure_unit": "т",
                            "unit_compatible": True,
                            "applicability_status": "accepted",
                            "score_total": 22.5,
                        }
                    ]
                },
            }
        ]
    }

    packet = _smeta_direct_structured_norm_choice("монтаж 2 т", lookup_trace)

    assert packet["trace"]["model_owns_selection"] is True
    assert packet["rows"][0]["basis"] == "ГЭСНм:38-01-001-01"
    assert packet["rows"][0]["title"] == "монтаж стальных конструкций"
    assert packet["rows"][0]["quantity"] == 2


def test_smeta_structured_norm_choice_gets_norm_card_and_mismatch_rule(monkeypatch):
    monkeypatch.setenv("LES_SMETA_NORM_REVIEW_ENABLED", "0")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"rows":[]}'}}]}

    class FakeClient:
        last_json = {}

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            FakeClient.last_json = kwargs["json"]
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    lookup_trace = {
        "results": [
            {
                "call": {
                    "tool": "search_norm",
                    "args": {
                        "work_description": "защитное укрытие полиэтиленовой пленкой",
                        "work_family": "finishes",
                        "element_type": "finishes",
                        "unit_hint": "м2",
                    },
                },
                "result": {
                    "candidates": [
                        {
                            "norm_code": "ГЭСН:15-02-036-02",
                            "title": "штукатурка по сетке без устройства каркаса: улучшенная потолков",
                            "measure_unit": "100 м2",
                            "unit_compatible": True,
                            "applicability_status": "accepted",
                            "score_total": 25.0,
                            "norm_profile": {
                                "model_card": {
                                    "title": "штукатурка по сетке без устройства каркаса: улучшенная потолков",
                                    "work_composition": {
                                        "steps": ["Натягивание проволочной сетки.", "Оштукатуривание поверхностей."]
                                    },
                                    "domain": {"actions": ["устройство"], "elements": ["отделка"]},
                                    "conditions_to_check": ["материал/основание"],
                                    "resources": {"count": 17, "kinds": ["материалы"]},
                                    "applicability": {"check": "сверить семейство работ"},
                                },
                                "navigation": {"collection": {"label": "ГЭСН 15. Отделочные работы"}},
                            },
                        }
                    ]
                },
            }
        ]
    }

    _smeta_direct_structured_norm_choice("защитное укрытие пленкой 116 м2", lookup_trace)

    system_prompt = FakeClient.last_json["messages"][0]["content"]
    payload = FakeClient.last_json["messages"][1]["content"]
    assert "явно чужую операцию/чужое семейство" in system_prompt
    assert "norm_card" in payload
    assert "work_composition" in payload
    assert "do not select a candidate whose title/norm_card/work_composition is an obviously foreign operation" in payload
    assert "dismantling/restoration prefer repair/dismantling/replacement candidates" in payload
    assert "ответвительная коробка over клеммная" in payload
    assert "small converter/power-supply candidates over large UPS system candidates" in payload
    assert "standard finishing operations грунтовка, шпатлевка" in payload
    assert "GKL openings or hidden inspection hatches" in payload
    assert "decorative PVC film" in payload
    assert "roof hatches" in payload


def test_smeta_structured_norm_choice_rejects_rejected_or_unit_mismatch_candidate(monkeypatch):
    monkeypatch.setenv("LES_SMETA_NORM_REVIEW_ENABLED", "0")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"rows":[{"lookup_index":1,"title":"Защитное укрытие",'
                                '"unit":"100 м2","quantity":1.16,"norm_code":"ГЭСН46-05-001-03",'
                                '"reason":"выбран rejected candidate"}]}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    lookup_trace = {
        "results": [
            {
                "call": {"tool": "search_norm", "args": {"work_description": "защитное укрытие", "unit_hint": "м2"}},
                "result": {
                    "candidates": [
                        {
                            "norm_code": "ГЭСН46-05-001-03",
                            "title": "устройство временных защитных ограждений",
                            "measure_unit": "100 м2",
                            "unit_compatible": True,
                            "applicability_status": "rejected",
                        }
                    ]
                },
            }
        ]
    }

    packet = _smeta_direct_structured_norm_choice("защитное укрытие пленкой 116 м2", lookup_trace)

    assert packet["rows"][0]["basis"] == "нужен подбор нормы"
    assert packet["rows"][0]["title"] == "защитное укрытие"
    assert packet["rows"][0]["amount"] == 0.0
    assert packet["trace"]["rejected_rows"][0]["norm_code"] == "ГЭСН46-05-001-03"
    assert packet["trace"]["rejected_rows"][0]["title"] == "защитное укрытие"
    assert packet["trace"]["rejected_rows"][0]["model_title"] == "Защитное укрытие"
    assert packet["trace"]["rejected_rows"][0]["reason"] == "candidate_rejected_by_lookup"


def test_smeta_structured_norm_choice_keeps_unreturned_lookup_as_unbound_row(monkeypatch):
    monkeypatch.setenv("LES_SMETA_NORM_REVIEW_ENABLED", "0")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"rows":[{"lookup_index":1,"title":"Окраска потолков",'
                                '"unit":"м2","quantity":3.2,"norm_code":"ГЭСН15-04-005-02",'
                                '"reason":"совпадает окраска"}]}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    lookup_trace = {
        "results": [
            {
                "call": {"tool": "search_norm", "args": {"work_description": "окраска потолков", "unit_hint": "м2"}},
                "result": {
                    "candidates": [
                        {
                            "norm_code": "ГЭСН15-04-005-02",
                            "title": "Окраска потолков",
                            "measure_unit": "100 м2",
                        }
                    ]
                },
            },
            {
                "call": {"tool": "search_norm", "args": {"work_description": "защитное укрытие пленкой", "unit_hint": "м2"}},
                "result": {
                    "candidates": [
                        {
                            "norm_code": "ГЭСН15-02-036-02",
                            "title": "Штукатурка по сетке",
                            "measure_unit": "100 м2",
                        }
                    ]
                },
            },
        ]
    }

    packet = _smeta_direct_structured_norm_choice("две строки ВОР", lookup_trace)

    assert len(packet["rows"]) == 2
    assert packet["rows"][0]["basis"] == "ГЭСН15-04-005-02"
    assert packet["rows"][1]["basis"] == "нужен подбор нормы"
    assert packet["rows"][1]["title"] == "защитное укрытие пленкой"
    assert packet["trace"]["unbound_rows_added"] == 1


def test_smeta_structured_norm_choice_batches_local_lookup_rows(monkeypatch):
    monkeypatch.setenv("LES_SMETA_NORM_REVIEW_ENABLED", "0")
    monkeypatch.setenv("LES_SMETA_NORM_CHOICE_BATCH_SIZE", "5")

    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}

    class FakeClient:
        batch_sizes = []

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            payload = kwargs["json"]["messages"][1]["content"]
            lookup_results = __import__("json").loads(payload)["lookup_results"]
            FakeClient.batch_sizes.append(len(lookup_results))
            rows = []
            for item in lookup_results:
                idx = item["lookup_index"]
                code = item["candidates"][0]["norm_code"]
                rows.append({
                    "lookup_index": idx,
                    "title": item["work_description"],
                    "unit": "шт",
                    "quantity": idx,
                    "norm_code": code,
                    "reason": "batch test",
                })
            return FakeResponse(__import__("json").dumps({"rows": rows}, ensure_ascii=False))

    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    lookup_trace = {"results": []}
    for idx in range(1, 7):
        lookup_trace["results"].append({
            "call": {
                "tool": "search_norm",
                "args": {
                    "work_description": f"работа {idx}",
                    "work_family": "generic",
                    "element_type": "generic",
                    "unit_hint": "шт",
                },
            },
            "result": {
                "candidates": [{
                    "norm_code": f"ГЭСН01-01-001-0{idx if idx <= 5 else 1}",
                    "title": f"Норма {idx}",
                    "measure_unit": "шт",
                    "unit_compatible": True,
                    "applicability_status": "accepted",
                }]
            },
        })
    lookup_trace["results"][5]["result"]["candidates"][0]["norm_code"] = "ГЭСН01-01-001-01"

    progress_events = []

    packet = _smeta_direct_structured_norm_choice(
        "шесть строк",
        lookup_trace,
        lambda ev: progress_events.append(ev),
    )

    assert FakeClient.batch_sizes == [5, 1]
    assert packet["trace"]["batched"] is True
    assert packet["trace"]["batch_size"] == 5
    assert [row["lookup_index"] for row in packet["rows"]] == [1, 2, 3, 4, 5, 6]
    assert [row["title"] for row in packet["rows"]] == [f"работа {idx}" for idx in range(1, 7)]
    assert packet["trace"]["batch_count"] == 2
    assert [ev["event"] for ev in progress_events] == ["smeta_batch"] * 4
    assert [ev["data"]["status"] for ev in progress_events] == ["started", "done", "started", "done"]
    assert progress_events[0]["data"]["start_lookup_index"] == 1
    assert progress_events[1]["data"]["accepted"] == 5
    assert progress_events[2]["data"]["start_lookup_index"] == 6
    assert progress_events[3]["data"]["accepted"] == 1


def test_smeta_structured_norm_choice_local_default_limits_candidates(monkeypatch):
    monkeypatch.delenv("LES_SMETA_NORM_CHOICE_CANDIDATES", raising=False)
    monkeypatch.setenv("LES_SMETA_NORM_REVIEW_ENABLED", "0")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"rows":[{"lookup_index":1,"title":"работа","unit":"шт",'
                                '"quantity":1,"norm_code":"ГЭСН01-01-001-01","reason":"ok"}]}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        seen_candidate_count = 0

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            payload = kwargs["json"]["messages"][1]["content"]
            lookup_results = __import__("json").loads(payload)["lookup_results"]
            FakeClient.seen_candidate_count = len(lookup_results[0]["candidates"])
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="local-test", provider="mlx", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    lookup_trace = {
        "results": [
            {
                "call": {"tool": "search_norm", "args": {"work_description": "работа", "unit_hint": "шт"}},
                "result": {
                    "candidates": [
                        {
                            "norm_code": f"ГЭСН01-01-001-{idx:02d}",
                            "title": f"Норма {idx}",
                            "measure_unit": "шт",
                            "unit_compatible": True,
                            "applicability_status": "accepted",
                        }
                        for idx in range(1, 12)
                    ]
                },
            }
        ]
    }

    packet = _smeta_direct_structured_norm_choice("работа 1 шт", lookup_trace)

    assert FakeClient.seen_candidate_count == 5
    assert packet["trace"]["candidate_limit"] == 5
    assert packet["trace"]["candidate_count"] == 5
    assert packet["trace"]["prompt_chars"] > 0


def test_smeta_structured_norm_review_keeps_model_chosen_analog(monkeypatch):
    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}

    class FakeClient:
        requests = []
        responses = [
            (
                '{"rows":[{"lookup_index":1,"title":"Демонтаж кабельной линии",'
                '"unit":"100 м","quantity":1.6,"norm_code":"ГЭСНм08-02-148-01",'
                '"reason":"нормативный аналог, проверить демонтажный коэффициент"}]}'
            ),
            (
                '{"rows":[{"lookup_index":1,"decision":"approve","norm_code":"ГЭСНм08-02-148-01",'
                '"title":"Демонтаж кабельной линии","unit":"100 м","quantity":1.6,'
                '"reason":"аналог оставлен моделью для расчёта с пометкой проверки"}]}'
            ),
        ]

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            FakeClient.requests.append(kwargs.get("json") or {})
            return FakeResponse(FakeClient.responses.pop(0))

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    lookup_trace = {
        "results": [
            {
                "call": {"tool": "search_norm", "args": {"work_description": "демонтаж кабельной линии 160 м", "unit_hint": "100 м"}},
                "result": {
                    "candidates": [
                        {
                            "norm_code": "ГЭСНм08-02-148-01",
                            "title": "Прокладка кабеля",
                            "measure_unit": "100 м",
                            "unit_compatible": True,
                        }
                    ]
                },
            }
        ]
    }

    packet = _smeta_direct_structured_norm_choice("демонтаж кабеля 160 м", lookup_trace)

    assert packet["rows"][0]["basis"] == "ГЭСНм08-02-148-01"
    assert packet["trace"]["review"]["status"] == "ok"
    assert packet["trace"]["review"]["approved"] == 1
    assert packet["trace"]["review"]["unbound"] == 0
    assert packet["trace"]["draft_accepted_rows"][0]["basis"] == "ГЭСНм08-02-148-01"
    review_prompt = FakeClient.requests[1]["messages"][0]["content"]
    assert "ближайший защитимый" in review_prompt
    assert "Если по демонтажу кабеля нет" not in review_prompt


def test_smeta_structured_norm_review_can_replace_empty_finish_draft(monkeypatch):
    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}

    class FakeClient:
        responses = [
            (
                '{"rows":[{"lookup_index":1,"title":"Грунтование потолков",'
                '"unit":"100 м2","quantity":0.032,"norm_code":"",'
                '"reason":"нет полного совпадения материала"}]}'
            ),
            (
                '{"rows":[{"lookup_index":1,"decision":"replace","norm_code":"ГЭСН15-04-006-02",'
                '"title":"Грунтование потолков","unit":"100 м2","quantity":0.032,'
                '"reason":"same-operation потолочная грунтовка, совместимая единица"}]}'
            ),
        ]

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse(FakeClient.responses.pop(0))

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    lookup_trace = {
        "results": [
            {
                "call": {"tool": "search_norm", "args": {"work_description": "грунтование потолков 3,2 м2", "unit_hint": "100 м2"}},
                "result": {
                    "candidates": [
                        {
                            "norm_code": "ГЭСН15-04-006-02",
                            "title": "Покрытие поверхности потолков грунтовкой",
                            "measure_unit": "100 м2",
                            "unit_compatible": True,
                            "applicability_status": "accepted",
                        }
                    ]
                },
            }
        ]
    }

    packet = _smeta_direct_structured_norm_choice("грунтование потолков 3,2 м2", lookup_trace)

    assert packet["rows"][0]["basis"] == "ГЭСН15-04-006-02"
    assert packet["rows"][0]["title"] == "грунтование потолков 3,2 м2"
    assert packet["rows"][0]["quantity"] == 0.032
    assert packet["trace"]["review"]["status"] == "ok"
    assert packet["trace"]["review"]["replaced"] == 1
    assert packet["trace"]["draft_unbound_rows_added"] == 1


def test_smeta_action_title_score_penalizes_demolition_vs_installation():
    assert _action_title_score("демонтаж", "монтаж электропроводки кабелем") < 0
    assert _action_title_score("демонтаж", "демонтаж электропроводки") > 0


def test_smeta_direct_raw_vor_lsr_goes_to_pricing_stage(monkeypatch):
    monkeypatch.setattr("proxy.services.fgis_price_service.available_pricebooks", lambda *args, **kwargs: [])

    prompt = _smeta_direct_user_prompt(
        "Сделай ЛСР по ВОР: прокладка кабеля 100 м",
        "MODEL-SELECTED NORM LOOKUP RESULTS: ГЭСНм:10-06-048-06",
        "",
        light=True,
    )

    assert _smeta_direct_norm_candidate_stage_required("Сделай ЛСР по ВОР: прокладка кабеля 100 м") is False
    assert "ЛСР-черновик" in prompt
    assert "Строка ВСЕГО по смете обязательна" in prompt
    assert "Не считай деньги" not in prompt
    assert "не делай ЛСР" not in prompt


def test_smeta_direct_explicit_candidate_table_stays_stage_one():
    question = (
        "Сделай сметный этап 1 по ВОР: 1) Прокладка кабеля UTP 100 м. "
        "Верни таблицу кандидатов ГЭСН."
    )

    assert _smeta_direct_norm_candidate_stage_required(question) is True


def test_smeta_direct_prices_previous_candidates_request_detects_followup():
    assert _smeta_direct_prices_previous_candidates_request("Теперь деньги по ним.") is True
    assert _smeta_direct_prices_previous_candidates_request("Посчитай ЛСР по этим кандидатам") is True
    assert _smeta_direct_prices_previous_candidates_request("Дай кандидатов ГЭСН") is False
    assert _smeta_direct_norm_candidate_stage_required("Теперь деньги по ним.") is False


def test_smeta_direct_previous_norm_lookup_trace_reuses_latest_session_candidates(monkeypatch):
    traces = [
        {"mode": "smeta", "smeta_norm_lookup": {"enabled": True, "results": []}},
        {
            "mode": "smeta",
            "smeta_norm_lookup": {
                "enabled": True,
                "results": [
                    {
                        "call": {"tool": "search_norm", "args": {"work_description": "кабель"}},
                        "result": {"candidates": [{"norm_code": "ГЭСНм10-06-034-01"}]},
                    }
                ],
            },
        },
    ]
    monkeypatch.setattr("proxy.routers.chat.session_recent_retrieval_traces", lambda *args, **kwargs: traces)

    lookup = _smeta_direct_previous_norm_lookup_trace("s1")

    assert lookup is not None
    assert lookup["reused_from_session"] is True
    assert lookup["results"][0]["result"]["candidates"][0]["norm_code"] == "ГЭСНм10-06-034-01"


def test_smeta_direct_followup_prefers_previous_candidate_trace(monkeypatch):
    traces = [
        {
            "mode": "smeta",
            "smeta_norm_lookup": {
                "enabled": True,
                "results": [
                    {
                        "call": {
                            "tool": "search_norm",
                            "args": {"work_description": "монтаж БАП", "unit_hint": "шт"},
                        },
                        "result": {
                            "candidates": [
                                {
                                    "norm_code": "ГЭСН08-03-481-01",
                                    "title": "Установка блока аварийного питания",
                                    "measure_unit": "шт",
                                }
                            ]
                        },
                    }
                ],
            },
        },
    ]
    monkeypatch.setattr("proxy.routers.chat.session_recent_retrieval_traces", lambda *args, **kwargs: traces)

    packet = _smeta_direct_previous_norm_lookup_packet_for_followup("Теперь деньги по ним.", "s1")

    assert packet is not None
    assert packet["trace"]["reused_from_session"] is True
    assert packet["trace"]["results"][0]["call"]["args"]["work_description"] == "монтаж БАП"
    assert "ГЭСН08-03-481-01" in packet["text"]
    assert _smeta_direct_previous_norm_lookup_packet_for_followup("Сделай ЛСР по БАП", "s1") is None


def test_smeta_workflow_decision_routes_previous_candidates_without_selector(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("workflow selector must not run for explicit money-by-candidates turns")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise AssertionError("workflow selector must not run for explicit money-by-candidates turns")

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "proxy.routers.chat._smeta_direct_previous_norm_lookup_trace",
        lambda session_id: {"results": [{"result": {"candidates": [{"norm_code": "ГЭСН08-03-481-01"}]}}]},
    )

    decision = _smeta_direct_workflow_decision("Теперь деньги по ним.", "context", "s1")

    assert decision["model_owns_workflow"] is False
    assert decision["status"] == "explicit_pricing_route"
    assert decision["stage"] == "pricing"
    assert decision["use_previous_candidates"] is True
    assert decision["source"] == "literal_user_request"


def test_smeta_workflow_decision_routes_explicit_lsr_without_selector(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("workflow selector must not run for explicit LSR turns")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise AssertionError("workflow selector must not run for explicit LSR turns")

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    monkeypatch.setattr("proxy.routers.chat._smeta_direct_previous_norm_lookup_trace", lambda session_id: None)

    decision = _smeta_direct_workflow_decision(
        "Сделай оценку стоимости и ЛСР по ВОР. Верни все строки.",
        "ВОР: прокладка кабеля 100 м",
        "s1",
    )

    assert decision["stage"] == "pricing"
    assert decision["status"] == "explicit_pricing_route"
    assert decision["model_owns_workflow"] is False


def test_smeta_workflow_decision_timeout_still_fails_open_for_non_literal_lsr(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise TimeoutError("timed out")

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    monkeypatch.setattr("proxy.routers.chat._smeta_direct_previous_norm_lookup_trace", lambda session_id: None)

    decision = _smeta_direct_workflow_decision(
        "Нужно понять, нужен ли расчёт или кандидаты.",
        "ВОР: монтаж БАП 16 шт",
        "s1",
    )

    assert decision["status"] == "selector_error"
    assert decision["stage"] == ""
    assert decision["fallback_reason"] == ""
    assert decision["model_owns_workflow"] is False


def test_smeta_user_prompt_respects_model_explanation_stage(monkeypatch):
    monkeypatch.setattr("proxy.services.fgis_price_service.available_pricebooks", lambda *args, **kwargs: [])

    prompt = _smeta_direct_user_prompt(
        "Объясни, как ты работаешь по сметам и ЛСР",
        "",
        "",
        light=True,
        workflow_stage="explanation",
    )

    assert "Этот запрос не является командой посчитать" in prompt
    assert "Строка ВСЕГО по смете обязательна" not in prompt


def test_smeta_norm_lookup_max_calls_does_not_cut_source_rows_to_ten(monkeypatch):
    monkeypatch.delenv("LES_SMETA_NORM_LOOKUP_MAX_CALLS", raising=False)
    rows = ", ".join(
        f'{{"source_no":"{idx}","name":"Работа {idx}","qty":"1","unit":"шт"}}'
        for idx in range(1, 20)
    )

    assert _smeta_norm_lookup_max_calls(f"[{rows}]") >= 19
    assert _smeta_norm_lookup_max_calls(f"[{rows}]") == 38


def test_smeta_source_row_count_reads_markdown_pdf_vor_rows(monkeypatch):
    monkeypatch.delenv("LES_SMETA_NORM_LOOKUP_MAX_CALLS", raising=False)
    table = """
| № пп | Наименование | Ед. изм. | Кол-во | Примечание |
| --- | --- | --- | --- | --- |
| 1 | 2 | 3 | 4 | 5 |
| Раздел 1. Демонтажные работы ЭОМ |  |  |  |  |
| 1 | Защитное укрытие | м² | 116 | Пленка техническая |
| Раздел 2. Демонтажные работы ЭОМ |  |  |  |  |
| 1 | Демонтаж кабельных линий 3х1,5 в гофр. трубе | м | 160 |  |
| Раздел 3. Монтажные работы АР |  |  |  |  |
| 1 | Разработка проема в ГКЛ потолке | шт. | 10 |  |
| 2 | Монтаж ревизионного лючка | шт. | 10 |  |
| 3 | Подготовка к восстановлению отделки | м² | 3,2 |  |
| 4 | Грунтование поверхности потолков ГКЛ | м² | 3,2 |  |
| 5 | Шпатлевка поверхности потолков ГКЛ | м² | 3,2 |  |
| 6 | Оклейка обоями поверхности потолков ГКЛ | м² | 3,2 |  |
| 7 | Покрытие поверхностей потолков ГКЛ грунтовкой | м² | 3,2 |  |
| 8 | Шпатлевка финишная потолков ГКЛ | м² | 3,2 |  |
| 9 | Демонтаж реечного потолка | м² | 15,0 | С сохранением |
| 10 | Монтаж реечного потолка | м² | 15,0 | Ранее дем. |
| 11 | Окраска потолков | м² | 3,2 |  |
| 12 | Окраска потолков запотолочного пространства | м² | 7,5 |  |
| Раздел 4. Монтажные работы ЭОМ |  |  |  |  |
| 1 | Монтаж блока аварийного питания | шт. | 16 |  |
| 2 | Прокладка кабеля силового | м | 160 |  |
| 3 | Прокладка трубы ПВХ гибкой гофрированной | м | 160 |  |
| 4 | Монтаж Скоб металлических однолапковых | шт. | 320 |  |
| 5 | Коробка огнестойкая для о/п | шт. | 8 |  |
"""

    assert _smeta_source_row_count(table) == 19
    assert _smeta_norm_lookup_max_calls(table) == 38


def test_smeta_direct_checked_norm_table_allows_pricing_stage(monkeypatch):
    monkeypatch.setattr("proxy.services.fgis_price_service.available_pricebooks", lambda *args, **kwargs: [])

    question = (
        "Рассчитай по проверенной таблице соответствия ВОР-ГЭСН: "
        "ВОР 1 прокладка кабеля 100 м -> ГЭСНм:10-06-048-06"
    )
    prompt = _smeta_direct_user_prompt(question, "", "", light=True)

    assert _smeta_direct_norm_candidate_stage_required(question) is False
    assert "ЛСР-черновик" in prompt
    assert "Строка ВСЕГО по смете обязательна" in prompt


def test_smeta_direct_prompt_requires_source_row_coverage_for_tabular_vor(monkeypatch):
    monkeypatch.setattr("proxy.services.fgis_price_service.available_pricebooks", lambda *args, **kwargs: [])
    rows = ", ".join(
        f'{{"section":"Раздел 4. Монтажные работы ЭОМ","source_no":"{idx}","name":"Работа {idx}",'
        f'"basis":"ГЭСНм:10-06-048-06","unit":"шт.","qty":"1"}}'
        for idx in range(1, 20)
    )

    prompt = _smeta_direct_user_prompt(
        f"Рассчитай по проверенной таблице соответствия ВОР-ГЭСН: [{rows}]",
        "",
        "",
        light=True,
    )

    assert "19 исходных строк" in prompt
    assert "contract coverage" in prompt
    assert "[SRC: <Раздел>; <source_no>]" in prompt
    assert "Не сокращай таблицу" in prompt
    assert "денежные графы поставь 0.00" in prompt
    assert "ЛСР всё равно выведи полностью" in prompt


def test_smeta_direct_max_tokens_scales_for_long_tabular_vor(monkeypatch):
    monkeypatch.delenv("LES_SMETA_DIRECT_MODEL_MAX_TOKENS", raising=False)
    rows = ", ".join(
        f'{{"source_no":"{idx}","name":"Работа {idx}"}}'
        for idx in range(1, 20)
    )

    assert _smeta_direct_max_tokens(f"[{rows}]", runtime_provider="mlx") == 3600
    assert _smeta_direct_max_tokens(f"[{rows}]", runtime_provider="openai") == 6000


def test_smeta_direct_light_prompt_allows_followup_norm_numbers(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "| Работа | Кандидат ГЭСН | Что проверить |\n"
                "|---|---|---|\n"
                "| Монтаж ярусов | ГЭСН на монтаж стальных конструкций | тип конструкции и кран |\n"
            )}}]}

    class FakeClient:
        last_json = None

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            FakeClient.last_json = kwargs.get("json")
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)
    monkeypatch.delenv("LES_SMETA_DIRECT_LIGHT_PROMPT", raising=False)

    text = _smeta_direct_model_answer(
        "Контекст текущего диалога:\n"
        "- Сделай оценку столпа по РИМ и рынку\n"
        "- ВОР: контрольная сборка; упаковка; монтаж ярусов краном; болтовая сборка\n\n"
        "Текущий запрос:\nдобавь номера ГЭСН",
        "Проверяемые фрагменты из выбранного RAG-корпуса:\nГЭСН на монтаж стальных конструкций.",
    )

    assert "Кандидат ГЭСН" in text
    prompt_payload = FakeClient.last_json["messages"][1]["content"]
    assert "ВОР -> кандидаты ГЭСН" in prompt_payload
    assert "Не считай деньги" in prompt_payload
    assert "таблицу доступных candidates" in prompt_payload
    assert "это новая задача или продолжение текущей сметы" not in prompt_payload
    assert "Используй короткие жирные метки секций" not in prompt_payload
    assert "Обязательно заверши разделом «Итог»" not in prompt_payload


def test_smeta_harness_question_includes_previous_answer_for_followups(monkeypatch):
    monkeypatch.setattr(
        "proxy.routers.chat._smeta_recent_dialog_context",
        lambda session_id: (
            "Предыдущий сметный диалог.\n"
            "Ответ ЛЕС:\n| Работа | РИМ сумма |\n| Монтаж ярусов | 46 млн |"
        ),
    )
    monkeypatch.setattr(
        "proxy.routers.chat.session_user_questions",
        lambda session_id, max_turns=6: ["Дай оценку столпа"],
    )
    monkeypatch.setattr("proxy.routers.chat.session_recent_retrieval_traces", lambda *args, **kwargs: [])

    text = _smeta_harness_question(
        ChatRequest(question="добавь номера ГЭСН", mode="smeta", session_id="s1")
    )

    assert "Ответ ЛЕС" in text
    assert "Монтаж ярусов" in text
    assert "46 млн" in text
    assert "Текущий запрос:\nдобавь номера ГЭСН" in text


def test_smeta_active_state_extracts_bor_from_direct_answer():
    answer = (
        "| № | Наименование работ | Ед. изм. | Кол-во | Примечание |\n"
        "|---|---|---:|---:|---|\n"
        "| 1 | Контрольная сборка смежных ярусов | стык | 10 | пары ярусов |\n"
        "| 2 | Монтаж ярусов гусеничным краном | т | 696,892 | с колес |\n"
        "\n"
        "Открытая развилка: вариант А — 664,71172 т; вариант Б — 696,89172 т.\n"
        "РИМ/ГЭСН-сценарий и рыночная оценка даны как предварительные ориентиры.\n"
        "Допущение: монтаж считается по укрупнённой ставке за тонну.\n"
        "- этап 3: погрузка/перевозка/выгрузка = 0 руб., исключено.\n"
        "Статус: предварительная сценарная оценка, не финальная смета."
    )

    state = _smeta_active_state_from_answer("Дай оценку столпа", answer)
    formatted = _format_active_smeta_state(state)

    assert state["schema"] == "active_smeta_state_v1"
    assert state["status"] == "scenario_estimate"
    assert state["methodology"] == "РИМ/ГЭСН + рынок"
    assert state["last_action"] == "предварительная оценка стоимости"
    assert state["last_table"] == "таблица ВОР"
    assert "вариант А" in state["open_conflicts"][0]
    assert any("укрупнённой ставке" in item for item in state["assumptions"])
    assert state["works"][0]["title"] == "Контрольная сборка смежных ярусов"
    assert state["works"][0]["quantity"] == 10
    assert state["works"][1]["unit"] == "т"
    assert "погрузка/перевозка/выгрузка" in state["excluded"][0]
    assert "Активная смета" in formatted
    assert "Методика: РИМ/ГЭСН + рынок" in formatted
    assert "Открытые развилки" in formatted
    assert "Принятые допущения" in formatted
    assert "Монтаж ярусов гусеничным краном" in formatted
    assert "Монтаж ярусов гусеничным краном — 696,892 т" in formatted


def test_smeta_harness_question_prefers_active_smeta_state_for_followups(monkeypatch):
    active_state = {
        "schema": "active_smeta_state_v1",
        "task": "оценка стоимости 11 ярусов",
        "accepted_variant": "вариант Б: 696,89172 т",
        "excluded": ["давальческое сырьё = 0 руб"],
        "works": [{"title": "Монтаж ярусов гусеничным краном", "unit": "т", "quantity": 696.89172}],
        "status": "scenario_estimate",
    }
    monkeypatch.setattr("proxy.routers.chat._smeta_recent_dialog_context", lambda session_id: "")
    monkeypatch.setattr("proxy.routers.chat.session_user_questions", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "proxy.routers.chat.session_recent_retrieval_traces",
        lambda *args, **kwargs: [{"active_smeta_state": active_state}],
    )

    text = _smeta_harness_question(
        ChatRequest(question="номера ГЭСН подпиши", mode="smeta", session_id="s1")
    )

    assert "Активная смета" in text
    assert "вариант Б" in text
    assert "Монтаж ярусов гусеничным краном" in text
    assert "Текущий запрос:\nномера ГЭСН подпиши" in text


def test_smeta_active_state_preserves_long_lsr_rows_and_amounts():
    rows = "\n".join(
        f"| {idx} | Работа {idx} | {idx} | м | ГЭСНм 08, кандидат | {idx * 100} руб./м | {idx * 1000} руб. | scenario_assumption |"
        for idx in range(1, 20)
    )
    answer = (
        "**Оценка стоимости работ**\n"
        "| № | Работа | Кол-во | Ед. | Норма/источник | Ставка/допущение | Сумма | Комментарий |\n"
        "|---:|---|---:|---:|---|---:|---:|---|\n"
        f"{rows}\n"
        "| Итого |  |  |  |  |  | 190 000 руб. |  |\n"
    )

    state = _smeta_active_state_from_answer("сделай ЛСР", answer)
    formatted = _format_active_smeta_state(state)

    assert len(state["works"]) == 19
    assert state["works"][18]["title"] == "Работа 19"
    assert state["works"][18]["unit_price"] == "1900 руб./м"
    assert state["works"][18]["amount"] == "19000 руб."
    assert "Работа 19" in formatted
    assert "сумма: 19000 руб." in formatted
    assert "сохраняй уже принятые строки, ставки и итоги" in formatted


@pytest.mark.asyncio
async def test_smeta_direct_rag_context_builds_compact_context(monkeypatch):
    chunk = SimpleNamespace(
        content="Монтаж кабеля СКС Cat.6A, количество 120 м, прокладка в лотке.",
        doc_name="СКС.xlsx",
        score=0.91,
        meta={"dataset_id": "ds-sks", "doc_type": "estimate"},
    )

    async def fake_resolve_dataset_ids(*args, **kwargs):
        return ["ds-sks"]

    async def fake_retrieve_chat_chunks(**kwargs):
        assert kwargs["dataset_ids"] == ["ds-sks"]
        assert kwargs["return_trace"] is True
        quality = SimpleNamespace(status="good", top_score=0.91, detail="")
        trace = SimpleNamespace(payload=lambda: {"mode": "fake", "merged_count": 1})
        return SimpleNamespace(chunks=[chunk], quality=quality, payload=lambda: {"mode": "fake", "merged_count": 1}, trace=trace)

    def fake_expand_context_windows(chunks, **kwargs):
        return SimpleNamespace(chunks=list(chunks))

    monkeypatch.setattr("proxy.routers.chat.resolve_dataset_ids", fake_resolve_dataset_ids)
    monkeypatch.setattr("proxy.routers.chat.retrieve_chat_chunks", fake_retrieve_chat_chunks)
    monkeypatch.setattr("proxy.routers.chat.expand_context_windows", fake_expand_context_windows)
    monkeypatch.setattr("proxy.routers.chat.dataset_memory_prompt_excerpt", lambda ids: "СКС: таблицы и сметные строки")

    packet = await _smeta_direct_rag_context(
        ChatRequest(question="сделай смету по СКС", mode="smeta", dataset_ids=["ds-sks"]),
        rag_backend=SimpleNamespace(collection_name="test"),
        dataset_ids=["ds-sks"],
        state=SimpleNamespace(reranker_available=False, reranker_cls=None, llm_semaphore=None),
    )

    assert packet["trace"]["status"] == "ready"
    assert packet["trace"]["dataset_memory"] is True
    assert "Проверяемые фрагменты" in packet["text"]
    assert "СКС.xlsx" in packet["text"]
    assert "120 м" in packet["text"]
    assert packet["sources"] == ["СКС.xlsx"]
    assert packet["source_map"][0]["doc_name"] == "СКС.xlsx"


@pytest.mark.asyncio
async def test_smeta_direct_rag_context_skips_without_explicit_scope(monkeypatch):
    async def fail_resolve_dataset_ids(*args, **kwargs):
        raise AssertionError("direct smeta must not infer broad/table RAG without explicit scope")

    monkeypatch.setattr("proxy.routers.chat.resolve_dataset_ids", fail_resolve_dataset_ids)

    packet = await _smeta_direct_rag_context(
        ChatRequest(question="сделай смету по приложенному Excel СКС", mode="smeta"),
        rag_backend=SimpleNamespace(collection_name="test"),
        dataset_ids=None,
        state=SimpleNamespace(reranker_available=False, reranker_cls=None, llm_semaphore=None),
    )

    assert packet["text"] == ""
    assert packet["trace"]["status"] == "skipped"
    assert packet["trace"]["reason"] == "no_explicit_scope"
    assert packet["sources"] == []


def test_harness_voice_allows_visible_estimator_reasoning(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Я вижу объектный запрос, а не готовую ВОР: бетонная дача сама по себе ещё не объём.\n"
                "Кровлю и отделку можно обсуждать как разделы, но считать их без площади дома — это уже цирк с калькулятором.\n"
                "Сначала нужны площадь или габариты, дальше можно разложить фундамент, стены, перекрытия и кровлю.\n"
                "После этого инструмент нормально подберёт нормы и посчитает, а не будет изображать смету на салфетке."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({
        "total_status": "blocked",
        "computed": [],
        "needs_input": [{"work": "Устройство кровли", "missing_slots": ["area_total_m2"]}],
    }, "хочу построить бетонную двухэтажную дачу")

    assert "объектный запрос" in text
    assert "площадь" in text
    assert len(text) > 250


def test_harness_voice_trims_model_table_rewrite(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Понимаю запрос как объектную смету, но исходных ещё мало.\n"
                "Сначала нужны габариты и конструктив, иначе смета будет гаданием.\n\n"
                "Таблица расчётного слоя (статус: blocked)\n"
                "1) Устройство кровли — pending"
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({"total_status": "blocked", "needs_input": [{}]}, "вопрос")

    assert "Понимаю запрос" in text
    assert "Таблица расчётного слоя" not in text
    assert "Устройство кровли" not in text


def test_harness_voice_allows_exact_payload_facts(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "По ГЭСН:10-02-017-03 расчётная часть есть, 1 200.00 ₽ вижу в таблице.\n"
                "Остальное без гадания держу в уточнении."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({
        "computed": [{"code": "ГЭСН:10-02-017-03"}],
        "final_total": {"grand_total": 1200.0, "smr": 1000.0},
    }, "вопрос")

    assert "ГЭСН:10-02-017-03" in text
    assert "1 200.00 ₽" in text


def test_harness_voice_rejects_partial_money_even_when_partial_total_exists(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Часть расчёта есть: 1 200.00 ₽, но финал держу в уточнении."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({
        "computed": [{"code": "ГЭСН:10-02-017-03"}],
        "needs_input": [{"work": "Параметры"}],
        "partial_total": {"grand_total": 1200.0, "smr": 1000.0},
        "final_total": None,
    }, "вопрос")

    assert text == ""


def test_harness_voice_rejects_partial_contradiction_when_partial_total_visible(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "Деньги сейчас не считаю: без региона это будет художественная литература."
            )}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    text = _harness_voice_comment({
        "total_status": "partial",
        "computed": [{"work": "Каркас", "code": "ГЭСН:10-02-017-03"}],
        "needs_input": [{"work": "Фундамент", "reason": "нет типа основания"}],
        "partial_total": {"grand_total": 1200.0, "smr": 1000.0},
        "final_total": None,
    }, "дай смету на дачу")

    assert text == ""


@pytest.mark.parametrize("bad_text", [
    "Получилось 1 200 ₽, жить можно.",
    "Беру ГЭСН:10-02-017-03, дальше видно.",
    "НР 109% оставляю как есть.",
])
def test_harness_voice_rejects_numbers_codes_and_percents(monkeypatch, bad_text):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": bad_text}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("proxy.routers.chat._llm_runtime", lambda: SimpleNamespace(
        model="test-model", provider="openai", chat_url="http://127.0.0.1/test", api_key="",
    ))
    monkeypatch.setattr("proxy.routers.chat.httpx.Client", FakeClient)

    assert _harness_voice_comment({"computed": [{}]}, "вопрос") == ""


def test_harness_answer_shows_candidate_table_without_tool_trace():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": 150},
        "total_status": "blocked",
        "computed": [],
        "needs_input": [],
        "rejected": [{
            "work": "Сваи",
            "code": "ГЭСН:05-01-089-03",
            "reason": "нужны параметры",
            "candidates": [
                {"norm_code": "ГЭСН:05-01-089-03", "measure_unit": "шт"},
                {"norm_code": "ГЭСН:05-01-089-06", "measure_unit": "шт"},
            ],
            "selection": {"reason": "есть применимый лидер, но отрыв от альтернатив мал"},
        }],
        "partial_total": None,
        "final_total": None,
        "trace": [{"tool": "search_norm"}],
        "steps": 1,
    })

    assert "| Работа | Норма |" in text
    assert "ГЭСН:05-01-089-03" in text
    assert "Число не показываю" in text
    assert "search_norm" not in text
    assert "кандидат" not in text.lower()


def test_harness_answer_humanizes_missing_object_area_slot():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": None},
        "total_status": "blocked",
        "computed": [],
        "needs_input": [{
            "work": "Устройство кровли",
            "missing_slots": ["area_total_m2"],
            "reason": "нет исходной площади/габаритов объекта",
        }],
        "rejected": [],
        "partial_total": None,
        "final_total": None,
    })

    assert "площадь/габариты объекта" in text
    assert "area_total_m2" not in text


def test_harness_answer_humanizes_internal_technical_terms():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": None},
        "total_status": "blocked",
        "computed": [],
        "needs_input": [{
            "work": "Монолитные стены",
            "missing_slots": ["wall_length_m", "wall_height_m", "wall_thickness_m"],
            "reason": "нет расчётной формулы для element_type=monolithic_wall; нет параметров: wall_length_m",
        }],
        "rejected": [],
        "partial_total": None,
        "final_total": None,
    })

    assert "длина/периметр стен" in text
    assert "высота стен" in text
    assert "толщина стен" in text
    assert "для типа работ: монолитные стены" in text
    assert "element_type" not in text
    assert "wall_length_m" not in text


def test_smeta_humanize_replaces_internal_selection_terms():
    from proxy.routers.chat import _smeta_humanize_text

    text = _smeta_humanize_text("shortlist пришёл из harness, slots в raw JSON, role-pack через tool-loop")

    assert "кандидаты норм" in text
    assert "расчётный слой" in text
    assert "параметры" in text
    assert "служебный JSON" in text
    assert "сметный контракт" in text
    assert "расчётный цикл" in text
    assert "shortlist" not in text
    assert "harness" not in text
    assert "raw JSON" not in text


def test_harness_answer_marks_assumption_scenario():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": 200},
        "assumption_mode": True,
        "scenario_assumptions": ["площадь принята по допущению"],
        "total_status": "partial",
        "computed": [{
            "work": "Устройство кровли",
            "code": "ГЭСН:12-01-024-01",
            "qty": 1.25,
            "norm_unit": "100 м2",
            "phys_qty": 125,
            "physical_unit": "м2",
        }],
        "needs_input": [{"work": "Фундамент", "reason": "нет типа основания"}],
        "rejected": [],
        "partial_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "final_total": None,
    })

    assert "Сценарий по допущениям" in text
    assert "площадь принята по допущению" in text
    assert "не проектная смета" in text


def test_harness_partial_total_does_not_contradict_visible_number():
    text = _format_harness({
        "schema": {"object_type": "house", "area_total_m2": 150},
        "total_status": "partial",
        "computed": [{
            "work": "Каркасные стены",
            "code": "ГЭСН:10-02-017-03",
            "qty": 1.5,
            "norm_unit": "100 м2",
            "phys_qty": 150,
            "physical_unit": "м2",
        }],
        "needs_input": [{"work": "Земляные работы", "reason": "нет параметров"}],
        "rejected": [],
        "partial_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "final_total": None,
        "trace": [],
        "steps": 1,
    })

    assert "~1 200.00 ₽" in text
    assert "Число не показываю" not in text
    assert "Финальную сумму не показываю" in text


def test_harness_summary_points_to_resource_artifact():
    result = {
        "schema": {"object_type": "metal_structure"},
        "total_status": "partial",
        "computed": [{
            "work": "Монтаж металлоконструкций",
            "code": "ГЭСНм:38-01-001-01",
            "qty": 664.71112,
            "norm_unit": "т",
            "phys_qty": 664.71112,
            "physical_unit": "т",
        }],
        "needs_input": [],
        "rejected": [],
        "partial_total": {"smr": 110519705.74, "grand_total": 135276119.83, "positions": 1},
        "final_total": None,
        "estimate": {
            "positions": [{
                "code": "ГЭСНм:38-01-001-01",
                "name": "Монтаж металлоконструкций",
                "unit": "т",
                "qty": 664.71112,
                "total": 110519705.74,
                "base": {
                    "ozp": 36405429.06,
                    "em": 16216870.11,
                    "zpm": 4992641.90,
                    "mat": 2010010.78,
                    "direct": 54632309.95,
                    "fot": 41398070.96,
                    "nr": 37258263.86,
                    "sp": 18629131.93,
                    "total": 110519705.74,
                },
                "adjusted": {
                    "ozp": 36405429.06,
                    "em": 16216870.11,
                    "zpm": 4992641.90,
                    "mat": 2010010.78,
                    "direct": 54632309.95,
                    "fot": 41398070.96,
                    "nr": 37258263.86,
                    "sp": 18629131.93,
                    "total": 110519705.74,
                },
                "resources": [
                    {
                        "kind": "labor",
                        "code": "1-1",
                        "name": "Средний разряд работы",
                        "unit": "чел.-ч",
                        "qty": 123.456,
                        "price_used": 100.0,
                        "cost": 12345.6,
                    },
                    {
                        "kind": "machine",
                        "code": "91.05.01-001",
                        "name": "Краны",
                        "unit": "маш.-ч",
                        "qty": 7.5,
                        "price_used": 2000.0,
                        "cost": 15000.0,
                    },
                    {
                        "kind": "material",
                        "code": "101-0001",
                        "name": "Электроды",
                        "unit": "кг",
                        "qty": 90.0,
                        "price_used": 10.0,
                        "cost": 900.0,
                    },
                    {
                        "kind": "material",
                        "name": "Нестандартный материал",
                        "unit": "шт",
                        "qty": 1,
                        "price_used": None,
                        "price_action": "needs_kac",
                        "cost": 0.0,
                    },
                ],
                "price_requirements": [{
                    "action": "needs_kac",
                    "resource_name": "Нестандартный материал",
                    "message": "нужен КАЦ: Нестандартный материал",
                }],
            }],
            "summary": {
                "price_requirements": [{
                    "action": "needs_kac",
                    "resource_name": "Нестандартный материал",
                    "message": "нужен КАЦ: Нестандартный материал",
                }],
            },
        },
    }

    summary = _format_harness(result)
    artifact = _format_harness_artifact(result)

    assert "Расчётный протокол и незакрытые позиции" in summary
    assert "Средний разряд работы" not in summary
    assert "# Частичный расчётный протокол" in artifact
    assert "Учтено в частичном расчёте" in artifact
    assert "110 519 705.74" in artifact
    assert "## Ценовой добор" in artifact
    assert "нужен КАЦ: Нестандартный материал" in artifact


def test_smeta_dialog_state_preserves_tool_result_for_next_turn():
    result = {
        "schema": {"object_type": "concrete_house", "area_total_m2": None, "floors": 2},
        "total_status": "blocked",
        "computed": [],
        "needs_input": [{
            "work": "Устройство кровли",
            "status": "needs_input",
            "missing_slots": ["area_total_m2"],
            "reason": "нет исходной площади/габаритов объекта",
        }],
        "rejected": [],
    }

    state = _smeta_dialog_state(result)
    text = _format_smeta_dialog_state(state)

    assert state["schema"] == "smeta_dialog_state_v1"
    assert state["pending"][0]["missing_slots"] == ["площадь/габариты объекта"]
    assert "Предыдущий результат smeta-инструментов" in text
    assert "Устройство кровли" in text
    assert "площадь/габариты объекта" in text
    assert "area_total_m2" not in text


def test_smeta_dialog_state_humanizes_missing_slots_for_model_memory():
    state = _smeta_dialog_state({
        "total_status": "blocked",
        "schema": {"object_type": "house"},
        "computed": [],
        "needs_input": [{
            "work": "Стены",
            "reason": "нет параметров: wall_length_m, wall_height_m",
            "missing_slots": ["wall_length_m", "wall_height_m"],
        }],
        "rejected": [],
    })
    formatted = _format_smeta_dialog_state(state)

    assert "длина/периметр стен" in formatted
    assert "высота стен" in formatted
    assert "wall_length_m" not in formatted
    assert "wall_height_m" not in formatted


def test_harness_direct_quantity_title_does_not_show_planner_area():
    text = _format_harness({
        "schema": {"object_type": "metal_structure", "area_total_m2": 150},
        "direct_quantity_estimate": True,
        "total_status": "complete",
        "computed": [{
            "work": "Монтаж металлоконструкций",
            "code": "ГЭСНм:38-01-001-01",
            "qty": 664.71112,
            "norm_unit": "т",
            "phys_qty": 664.71112,
            "physical_unit": "т",
        }],
        "needs_input": [],
        "rejected": [],
        "partial_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "final_total": {"smr": 1000, "grand_total": 1200, "positions": 1},
        "trace": [],
        "steps": 1,
    })

    assert "Монтаж металлоконструкций" in text
    assert "150 м²" not in text
