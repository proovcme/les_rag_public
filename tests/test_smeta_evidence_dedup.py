"""Exact evidence aliases preserve sources, budgets, and the provider-bound request."""
import ast
import asyncio
import inspect
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as chat
from proxy.services.model_execution_preset_service import ModelExecutionPreset


def hit(code="norm-A", revision="rev-A", **meta):
    return SimpleNamespace(doc_id="doc-A", doc_name="canonical cards", score=1.0,
        content=f"Шифр: {code}\nИзмеритель: шт\n" + ("Полный нормативный текст. " * 28).rstrip(),
        meta={"norm_code": code, "norm_id": f"{revision}|{code}", "source_ref": "doc#row=17", **meta})


@pytest.mark.parametrize("scope", ["", " по строкам 984–990", " по строкам 17, 21-23"])
@pytest.mark.parametrize("numbered", [True, False])
@pytest.mark.parametrize("prefix", ["Вот ", ""])
def test_presentation_header_is_not_a_search_query(scope, numbered, prefix):
    queries = "1. оконцовка кабеля\n2. поиск запросов в архиве" if numbered else "оконцовка кабеля\nпоиск запросов в архиве"
    text = f"{prefix}поисковые запросы к выбранным датасетам для подбора evidence{scope}:\n\n{queries}"
    assert chat.parse_model_rag_queries(text) == ["оконцовка кабеля", "поиск запросов в архиве"]


def test_unwrapped_query_about_search_queries_is_literal():
    text = "поисковые запросы по строкам 17–21: примеры\nмонтаж кабеля"
    assert chat.parse_model_rag_queries(text) == text.splitlines()


def test_numbered_query_labels_are_unwrapped_before_exact_deduplication():
    text = 'Запрос 1: монтаж шкафа\nзапрос 2: оконцовка кабеля\nЗапрос 31: монтаж шкафа'
    assert chat.parse_model_rag_queries(text) == ['монтаж шкафа', 'оконцовка кабеля']


@pytest.mark.parametrize('text', [
    'Запрос на монтаж шкафа\nмонтаж кабеля',
    '"Запрос 1: монтаж шкафа"\n"монтаж кабеля"',
    'search_sources("Запрос 1: монтаж шкафа")\nsearch_sources("монтаж кабеля")',
])
def test_query_label_unwrapping_preserves_literal_search_text(text):
    expected = ['Запрос на монтаж шкафа', 'монтаж кабеля'] if text.startswith('Запрос на') else ['Запрос 1: монтаж шкафа', 'монтаж кабеля']
    assert chat.parse_model_rag_queries(text) == expected


def test_empty_query_list_has_no_groups():
    assert chat.build_model_rag_evidence_groups([], max_chars=100, hits_per_query=6) == ([], [])


def test_query_portion_uses_original_selected_rows_without_answer_instructions():
    source = 'Файл: source.xlsx\nS!R1: № | Наименование | Ед. изм | Количество\nS!R2: 1 | Панель | шт | 2\nS!R3: 2 | Кабель | м | 12'
    rows = chat.query_attachment_context(source, {'state': 'portion', 'shown': ['S!2']})
    assert '2 | Кабель | м | 12' in rows
    assert 'S!2' in rows
    assert 'Наименование | Ед. изм | Количество' in rows
    assert 'Панель' not in rows
    assert 'decision_kind' not in rows and 'resource_review_status' not in rows
    assert chat.query_attachment_context('Обычное письмо', {'state': 'not-a-vor'}) == 'Обычное письмо'
    complete = chat.query_attachment_context(source, {'state': 'complete', 'shown': []})
    assert 'Панель' not in complete and 'Кабель' not in complete
    with pytest.raises(ValueError, match='QUERY_PORTION_SOURCE_MISMATCH'):
        chat.query_attachment_context(source, {'state': 'portion', 'shown': ['S!3']})


def test_query_profile_keeps_role_and_skill_without_final_answer_prompt():
    prompt = chat.profile_query_prompt({'mode': 'estimator', 'prompt_text': 'FINAL_ANSWER_STYLE',
        'skill_text': 'Ищи только в выбранных источниках.'})
    assert 'estimator' in prompt and 'Ищи только в выбранных источниках.' in prompt
    assert 'FINAL_ANSWER_STYLE' not in prompt
    assert 'поисков' in prompt and 'native tools' not in prompt


def test_exact_duplicate_is_rendered_once_but_snapshot_contains_visible_card():
    a = hit()
    blocks, chunks = chat.build_model_rag_evidence_groups([("first", [a]), ("second", [a])], max_chars=9000, hits_per_query=6)
    assert "\n".join(blocks).count("Шифр: norm-A") == 1
    assert "См. Q1.H1" in blocks[1]
    assert chunks[1].content == chunks[0].content == a.content
    snapshot = chat.evidence_snapshot([{"source_row": "S!2", "evidence_refs": ["Q2.H1"]}], chunks)["S!2"][0]
    assert snapshot["sent_text"] == a.content
    assert snapshot["source_meta"]["source_ref"] == "doc#row=17"
    assert snapshot["source_meta"]["norm_id"] == "rev-A|norm-A"


def test_equal_text_with_different_revision_or_provenance_is_not_aliased():
    a, b, c = hit(), hit(revision="rev-B"), hit(source_ref="other#row=18")
    blocks, _ = chat.build_model_rag_evidence_groups([("a", [a]), ("b", [b]), ("c", [c])], max_chars=9000, hits_per_query=6)
    assert "\n".join(blocks).count("Шифр: norm-A") == 3


def test_norm_identity_and_measure_survive_long_title_and_all_card_routes(monkeypatch):
    from proxy.services import model_research_tool_service as research
    monkeypatch.setattr(research, "norm_table_variants", lambda _: ())
    card = dict(norm_code="NORM", norm_id="edition-A|family|NORM", edition="edition-A", base_type="family",
                measure_unit="100 м", source_ref="source#guid=17", title="Long normative title " * 200)
    service = research.ModelResearchToolService(retrieve=None, frozen_dataset_ids=(), retrieval_kwargs={},
        fallback=None, smeta_norm_retrieve=lambda *_args, **_kwargs: {"cards": [card],
            "retrieval_trace": {"rag": {"status": "ok", "collection": "fixture"}}})
    result = asyncio.run(service.execute({"tool": "search_sources", "args": {"q": "model query"}}))
    routes = [result.chunks[0], chat._PracticeChunk(card), chat._MaterialChunk(card, {}, research.smeta_card_text)]
    for candidate in routes:
        # A title longer than the budget must not become an apparently complete
        # normative header. Retry with room for the whole identity/title.
        with pytest.raises(ValueError, match="EVIDENCE_BUDGET"):
            chat.build_model_rag_evidence_groups([("query", [candidate])], max_chars=450, hits_per_query=1)
        blocks, chunks = chat.build_model_rag_evidence_groups([("query", [candidate])], max_chars=5000, hits_per_query=1)
        assert card["norm_id"] in blocks[0]
        assert "Измеритель: 100 м" in blocks[0]
        assert card["title"].rstrip() in blocks[0]
        assert chunks[0].meta["norm_id"] == card["norm_id"]
        assert chunks[0].meta["model_evidence_truncated"] is False


@pytest.mark.parametrize("budget", [1900, 3500, 7000])
def test_aliases_are_rebuilt_after_practice_groups_are_removed(budget):
    practice = [hit(f"practice-{i}", practice_candidate=True) for i in range(5)]
    a = hit()
    blocks, chunks = chat.build_model_rag_evidence_groups(
        [("archive", practice), ("first search", [a]*6), ("second search", [a]*6)],
        max_chars=budget, hits_per_query=6)
    refs = {c.meta["model_evidence_ref"] for c in chunks}
    assert len("\n".join(blocks)) <= budget
    for chunk in chunks:
        alias = chunk.meta.get("model_evidence_alias_of")
        if alias:
            assert alias in refs
            original = next(c for c in chunks if c.meta["model_evidence_ref"] == alias)
            assert not original.meta.get("model_evidence_alias_of")
            assert original.content == chunk.content


def _production_post_llm(spy):
    # Use the actual nested provider-bound function, with its normal configured
    # runner branch. Only the expensive surrounding retrieval/application setup
    # and the external model are omitted from this offline transport boundary.
    tree = ast.parse(inspect.getsource(chat._execute_chat_evidence_application))
    post = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_post_llm")
    wrapper = ast.parse("def factory():\n active_model_result=None\n active_pending_tool_calls=0\n").body[0]
    wrapper.body += [post, ast.Return(ast.Name("_post_llm", ast.Load()))]
    namespace = dict(vars(chat))
    namespace.update(bound_runner=spy, token_sink=None, chunks=[], _dataset_ids=[],
                     _dataset_sensitivities=lambda _: set(), _dataset_ids_from_chunks=lambda _: set(),
                     _env_bool=lambda _name, default: default,
                     retrieval_trace={}, canonical_execution_mode=chat.CanonicalRouteMode.ACTIVE)
    exec(compile(ast.fix_missing_locations(ast.Module([wrapper], [])), "<production-post-llm>", "exec"), namespace)
    return namespace["factory"]()


@pytest.mark.parametrize('finish_reason', ['stop', 'length', None])
def test_final_generation_trace_preserves_provider_usage_separate_from_search(finish_reason):
    tree = ast.parse(inspect.getsource(chat._execute_chat_evidence_application))
    # Execute the real statement at the answer boundary without calling services.
    statements = [node for node in ast.walk(tree) if isinstance(node, ast.Expr)
                  and 'answer_generations' in ast.unparse(node)]
    assert len(statements) == 1, 'Final generation metadata must reach the response trace'
    usage = {'prompt_tokens': 123, 'completion_tokens': 0, 'total_tokens': 123}
    if finish_reason is not None:
        usage['finish_reason'] = finish_reason
    original = dict(usage)
    trace = {'tool_loop': {'query_usage': {'completion_tokens': 19, 'finish_reason': 'stop'}}}
    namespace = dict(retrieval_trace=trace, usage=usage, attempt=2,
                     llm_model='observed-model', generation_budget=8192)
    exec(compile(ast.fix_missing_locations(ast.Module([statements[0]], [])),
                 '<production-answer-trace>', 'exec'), namespace)
    assert trace['answer_generations'] == [{
        'attempt': 2, 'model': 'observed-model', 'output_budget': 8192,
        'finish_reason': finish_reason,
        'usage': {'prompt_tokens': 123, 'completion_tokens': 0, 'total_tokens': 123},
    }]
    assert trace['tool_loop']['query_usage']['completion_tokens'] == 19
    assert usage == original


def test_practice_and_original_input_reach_actual_provider_bound_messages():
    candidates = [hit(f"norm-{i}") for i in range(6)]
    archive = hit("archive-operation", material_candidate=True)
    query_hits = [("archive", [archive])] + [(f"query {i}", candidates) for i in range(12)]
    preset = ModelExecutionPreset(preset_id="fixture", model_family="fixture", input_token_limit=11000,
        generation_reserve_tokens=1000, safety_reserve_tokens=500, normal_tool_count=3,
        max_tools=5, max_batch_items=5, parallel_read_limit=1, reasoning_enabled=False, source_chain=("test",))
    prefix, request, attachment = "Estimator", "Original user question", "Original complete attachment"
    _, fixed = chat.govern_inference_messages(preset=preset, profile_prefix=prefix,
                                            request_payload=request, evidence=[attachment])
    budget = chat.model_rag_group_char_budget(input_budget_tokens=fixed.input_budget_tokens,
        included_tokens=fixed.included_tokens, query_count=len(query_hits), context_chars_limit=16000)
    blocks, chunks = chat.build_model_rag_evidence_groups(query_hits, max_chars=budget, hits_per_query=6)
    messages, _ = chat.govern_inference_messages(preset=preset, profile_prefix=prefix,
        request_payload=request, evidence=chat.answer_evidence_blocks(fixed_blocks=[attachment],
            group_blocks=blocks, coverage=chat.model_rag_evidence_coverage(query_hits, blocks)))
    sent = []
    class Spy:
        async def complete(self, *, request, **kwargs):
            sent.extend(request.messages)
            return SimpleNamespace(pending_tool_calls=0, response=SimpleNamespace(text="answer", tool_calls=(), usage={}),
                                   public_connection_payload=lambda: {})
    asyncio.run(_production_post_llm(Spy())(None, "fixture", {}, {"messages":messages, "max_tokens":1000}))
    rendered = "\n".join(m["content"] for m in sent)
    assert request in rendered and attachment in rendered
    assert "Шифр: archive-operation" in rendered
    for chunk in chunks:
        alias = chunk.meta.get("model_evidence_alias_of")
        if alias:
            assert f"[{alias} |" in rendered
