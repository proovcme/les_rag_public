"""A model-authored query wrapper never becomes trusted application facts."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services import model_lsr_result_contract as contract
from proxy.services.model_query_declaration_transport_service import query_declaration_response_text


# Exact visible repair from corrected962 B1. This is authored model output,
# not an application runtime-facts object, despite its chosen schema label.
ACTUAL_REPAIR = '{"schema":"les.model-runtime-facts.v1","kind":"declare_research_queries_result","data":{"queries":["Монтаж композитных панелей наружных облицовки","Монтаж трёхслойных стеновых сэндвич-панелей","Устройство кладки из полнотелого керамического кирпича наружной","Армирование кладки из кирпича кладочной сеткой","Устройство тонкослойной штукатурки фасадной по армирующей стеклосетке","Монтаж теплоизоляции из экструдированного пенополистирола наружной","Устройство металлического каркаса наружной облицовки"],"artifact_kind":"vor","commentary":"Исходник: спецификация материалов (DOCX_T1, лист 1/2). Выделены 6 групп монтажных операций, требующих подбора норм на монтаж (монтаж панелей, кладка, армирование кладки, штукатурка, утепление, каркас). По ним сформированы поисковые запросы."}}'


def wrapper(data=..., **overrides):
    body = {"schema": "les.model-runtime-facts.v1", "kind": "declare_research_queries_result",
            "data": {"queries": ["  Literal Ω \\\\ quoted \"x\"  ", "Repeated", "Repeated"],
                     "artifact_kind": "vor", "commentary": "Literal note"} if data is ... else data}
    body.update(overrides)
    return body


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def query_texts(raw, finish="stop"):
    return [item.text for item in service.read_model_query_response(raw, finish_reason=finish)["queries"]]


def test_actual_visible_repair_keeps_all_seven_literal_queries_kind_and_commentary():
    assert len(ACTUAL_REPAIR) == 784
    assert hashlib.sha256(ACTUAL_REPAIR.encode("utf-8")).hexdigest() == "d31833cd5ff9d6f224bff762dc8bb0aa2d28d913860ad9b74cf534ccd5e77e58"
    data = json.loads(ACTUAL_REPAIR)["data"]
    before = deepcopy(data)
    decoded = contract.decode_model_query_envelope(ACTUAL_REPAIR)
    assert decoded is not None
    assert decoded == {"queries": data["queries"], "commentary": data["commentary"]}
    declared = service.read_model_query_response(ACTUAL_REPAIR, finish_reason="stop")
    assert [item.text for item in declared["queries"]] == data["queries"]
    assert declared["artifact_kind_declaration"] == {
        "status": "declared", "artifact_kind": "vor", "declarations": ["vor"], "errors": []}
    assert declared["commentary"] == data["commentary"]
    assert not declared["accompanying_answer"] and not declared["intentional_empty"]
    assert json.loads(ACTUAL_REPAIR)["data"] == before
    diagnostic = service.declared_query_output_diagnostics(ACTUAL_REPAIR, declared)
    assert diagnostic["accepted_count"] == 7 and diagnostic["rejected_count"] == 0
    assert diagnostic["output_shape"] == "query_envelope"
    assert "schema" not in decoded and "kind" not in decoded and "data" not in decoded


@pytest.mark.parametrize("kind", [None, "vor", "lsr"])
@pytest.mark.parametrize("fenced", [False, True])
def test_wrapper_preserves_literal_order_spaces_duplicates_and_only_explicit_model_kind(kind, fenced):
    data = wrapper()["data"]
    if kind is None:
        data.pop("artifact_kind")
    else:
        data["artifact_kind"] = kind
    raw = encoded(wrapper(data))
    if fenced:
        raw = "```json\n" + raw + "\n```"
    assert contract.decode_model_query_envelope(raw)["queries"] == data["queries"]
    declared = service.read_model_query_response(raw, finish_reason="stop")
    # The transport adds no trimming/deduplication. The unchanged declared-query
    # reader applies exactly the same mechanics to its ordinary representation.
    canonical = service.read_model_query_response(encoded(data), finish_reason="stop")
    assert declared == canonical
    assert declared["artifact_kind_declaration"]["status"] == ("declared" if kind else "missing")
    assert declared["artifact_kind_declaration"]["artifact_kind"] == (kind or "")
    assert declared["commentary"] == data["commentary"]


@pytest.mark.parametrize("kind, intentional", [(None, False), ("vor", True), ("lsr", False)])
def test_empty_wrapper_keeps_existing_intent_rule_and_does_not_choose_a_type(kind, intentional):
    data = {"queries": []}
    if kind is not None:
        data["artifact_kind"] = kind
    declared = service.read_model_query_response(encoded(wrapper(data)), finish_reason="stop")
    assert declared["queries"] == [] and declared["intentional_empty"] is intentional
    assert not declared["accompanying_answer"]


@pytest.mark.parametrize("overrides", [
    {"schema": "other"}, {"kind": "other"}, {"origin": "application"},
    {"rows": []}, {"results": []}, {"artifact_kind": "vor"},
    {"queries": ["Must not be selected from extra wrapper metadata"]},
    {"data": []}, {"data": None}, {"data": {"queries": ["Literal"], "rows": []}},
    {"data": {"queries": ["Literal"], "result": {}}},
    {"data": {"queries": ["Literal"], "price_basis": {}}},
    {"data": {"queries": ["Literal"], "trusted": True}},
    {"data": {"queries": ["Literal"], "artifact_kind": "unsupported"}},
    {"data": {"queries": ["Literal"], "commentary": {"text": "x"}}},
    {"data": {"queries": ["Literal"], "commentary": None}},
    {"data": {"queries": [12]}}, {"data": {"queries": ["  "]}},
    {"data": {"queries": ["Literal\nnext"]}},
    {"data": {"queries": ["Literal\rnext"]}},
])
def test_unknown_or_business_metadata_and_invalid_inner_values_are_never_unwrapped(overrides):
    raw = encoded(wrapper(**overrides))
    assert contract.decode_model_query_envelope(raw) is None
    assert query_texts(raw) == []


@pytest.mark.parametrize("raw", [
    ACTUAL_REPAIR.replace('"schema":"les.model-runtime-facts.v1"', '"schema":"les.model-runtime-facts.v1","schema":"les.model-runtime-facts.v1"'),
    ACTUAL_REPAIR.replace('"data":{', '"data":{},"data":{'),
    ACTUAL_REPAIR.replace('"queries":[', '"queries":[],"queries":['),
    ACTUAL_REPAIR.replace('"artifact_kind":"vor"', '"artifact_kind":"vor","artifact_kind":"vor"'),
    ACTUAL_REPAIR.replace('"artifact_kind":"vor"', '"artifact_kind":"lsr","artifact_kind":"vor"'),
    ACTUAL_REPAIR[:-1],
    ACTUAL_REPAIR + "trailing",
    ACTUAL_REPAIR + "\n" + ACTUAL_REPAIR,
    ACTUAL_REPAIR + '\n{"queries":["Other"]}',
    ACTUAL_REPAIR + '\n{"commentary":"Other"}',
    ACTUAL_REPAIR + '\n{"rows":[]}',
    ACTUAL_REPAIR + '\nartifact_kind: lsr',
    ACTUAL_REPAIR + '\nartifact_kind: vor',
])
def test_duplicate_incomplete_ambiguous_and_separate_metadata_stay_rejected_whole(raw):
    assert contract.decode_model_query_envelope(raw) is None
    assert query_texts(raw) == []


@pytest.mark.parametrize("arguments_as_object", [False, True])
def test_same_model_owned_carrier_is_accepted_through_existing_native_and_plain_readers(arguments_as_object):
    arguments = json.loads(ACTUAL_REPAIR) if arguments_as_object else ACTUAL_REPAIR
    before = deepcopy(arguments)
    call = {"id": "wrapper963", "type": "function", "function": {
        "name": "declare_research_queries", "arguments": arguments}}
    response = SimpleNamespace(tool_calls=(call,), text="", reasoning_content="PRIVATE_NOT_VISIBLE")
    carrier, trace = query_declaration_response_text("native", response=response, advertised=True)
    assert trace["channel"] == "native_function"
    assert query_texts(carrier) == json.loads(ACTUAL_REPAIR)["data"]["queries"]
    assert contract.decode_model_artifact_kind(carrier)["artifact_kind"] == "vor"
    assert json.loads(carrier) == json.loads(ACTUAL_REPAIR)
    assert "PRIVATE_NOT_VISIBLE" not in carrier and arguments == before


def test_arbitrary_payload_wrappers_remain_unsupported():
    for body in [{"data": json.loads(ACTUAL_REPAIR)["data"]},
                 {"schema": "les.model-runtime-facts.v1", "data": json.loads(ACTUAL_REPAIR)["data"]},
                 {"kind": "declare_research_queries_result", "data": json.loads(ACTUAL_REPAIR)["data"]},
                 {"schema": "les.model-runtime-facts.v1", "kind": "declare_research_queries_result",
                  "payload": json.loads(ACTUAL_REPAIR)["data"]}]:
        raw = encoded(body)
        assert contract.decode_model_query_envelope(raw) is None
        assert query_texts(raw) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_producer_executes_only_the_seven_authored_queries_without_another_turn(
        tmp_path, monkeypatch, variant):
    from tests.test_model_rag_sheet_evidence_reads import _run_sheet

    rows = [{"source_row": source, "row_role": "work", "work_row": "", "title": title,
             "unit": "m", "quantity": quantity, "open_gap": ""}
            for source, title, quantity in (("S!R2", "Install Cable A", 12), ("S!R3", "Install Cable B", 3))]
    before = deepcopy(rows)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=ACTUAL_REPAIR,
        final_answer=encoded({"artifact_kind": "vor", "rows": rows}))
    assert run.queries == json.loads(ACTUAL_REPAIR)["data"]["queries"]
    assert len(run.requests) == 2 and not run.responses
    assert len(run.executions) == 1 and run.executions[0][0]["tool"] == "build_vor_workbook"
    saved = run.executions[0][0]["args"]["decisions"]
    assert [{key: row[key] for key in old} for row, old in zip(saved, before)] == before
    query_output = run.result["retrieval_trace"]["model_query_outputs"][0]
    assert query_output["declared_parse"]["accepted_count"] == 7
    assert query_output["artifact_kind_declaration"]["artifact_kind"] == "vor"
