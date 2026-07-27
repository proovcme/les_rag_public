from proxy.services.tool_trace_policy import make_tool_trace, validate_tool_result


def test_tool_result_has_trace_not_magic_answer():
    trace = make_tool_trace(
        tool="quantity_audit",
        operation="sum_and_compare",
        inputs=[1, 2, 3],
        result={"sum": 6},
        trace="1 + 2 + 3 = 6",
        status="ok",
    ).to_dict()
    report = validate_tool_result(trace)
    assert report["ok"] is True
    assert report["has_trace"] is True


def test_tool_result_without_trace_is_rejected():
    payload = {"tool": "lookup", "operation": "price", "inputs": ["x"], "result": 10, "status": "ok"}
    report = validate_tool_result(payload)
    assert report["ok"] is False
    assert "trace" in report["missing"]


def test_tool_cannot_turn_missing_into_zero():
    payload = {
        "tool": "price_lookup",
        "operation": "lookup",
        "inputs": ["missing-code"],
        "result": 0,
        "trace": "code not found",
        "status": "missing",
    }
    report = validate_tool_result(payload)
    assert report["ok"] is False
    assert "missing_as_zero" in report["forbidden_decisions"]


def test_tool_cannot_select_domain_decision_final():
    payload = {
        "tool": "norm_search",
        "operation": "search",
        "inputs": ["монтаж"],
        "result": [{"code": "x"}],
        "trace": "candidate found",
        "status": "ok",
        "decisions": ["select_norm_final"],
    }
    report = validate_tool_result(payload)
    assert report["ok"] is False
    assert "select_norm_final" in report["forbidden_decisions"]
