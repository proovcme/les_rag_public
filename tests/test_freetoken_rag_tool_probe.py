from tools.freetoken_rag_tool_probe import run_tool_loop


def test_tool_loop_requires_search_then_read_before_grounded_answer():
    responses = iter([
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "Нужно найти кандидатов.",
                    "tool_calls": [{
                        "id": "search-1",
                        "type": "function",
                        "function": {
                            "name": "search_norm",
                            "arguments": '{"work_description":"монтаж шкафа","top_k":4}',
                        },
                    }],
                },
            }],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
        },
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "Открою наиболее близкую карточку.",
                    "tool_calls": [{
                        "id": "read-1",
                        "type": "function",
                        "function": {
                            "name": "read_norm",
                            "arguments": '{"norm_code":"ГЭСНм10-04-087-05"}',
                        },
                    }],
                },
            }],
            "usage": {"prompt_tokens": 200, "completion_tokens": 40},
        },
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Выбрана открытая карточка нормы.",
                    "reasoning_content": "Карточка подтверждает операцию.",
                    "tool_calls": [],
                },
            }],
            "usage": {"prompt_tokens": 300, "completion_tokens": 50},
        },
    ])
    request_bodies = []

    def post_json(_url, body, *, timeout):
        request_bodies.append((body, timeout))
        return next(responses)

    def execute_tool(name, arguments):
        if name == "search_norm":
            return {
                "status": "ambiguous",
                "candidates": [{
                    "norm_code": "ГЭСНм10-04-087-05",
                    "title": "Монтаж телекоммуникационного оборудования",
                    "source_ref": "fsnb://10-04-087-05",
                }],
            }
        return {
            "norm_code": arguments["norm_code"],
            "title": "Монтаж телекоммуникационного оборудования",
            "source_ref": "fsnb://10-04-087-05",
        }

    result = run_tool_loop(
        "Подбери норму для монтажа напольного шкафа 42U",
        post_json=post_json,
        execute_tool=execute_tool,
        thinking=True,
    )

    assert result["ok"] is True
    assert [item["tool"] for item in result["tool_trace"]] == [
        "search_norm",
        "read_norm",
    ]
    assert result["answer"] == "Выбрана открытая карточка нормы."
    assert all(
        body["chat_template_kwargs"] == {"enable_thinking": True}
        for body, _timeout in request_bodies
    )
    assert [body["tool_choice"] for body, _timeout in request_bodies] == [
        {"type": "function", "function": {"name": "search_norm"}},
        {"type": "function", "function": {"name": "read_norm"}},
        "none",
    ]
    assert request_bodies[-1][0]["messages"][-1]["role"] == "tool"
