"""Успешный поиск без совпадений — это ответ модели, а не отказ всего прохода.

0.30.125 сделал причину отказа видимой, но `model_rag_failure_detail` по-прежнему
считал любой `status != ok` ошибкой: запрос, который выполнился и не нашёл ни одной
карточки, ронял весь проход с 503 (аудит Codex 17.09, P2). Пустая выдача — законный
результат поиска: модель сформулировала запрос, база ответила «нет», и решать, что
с этим делать, должна та же модель. Технический отказ (`blocked`: сметный RRF не готов)
и некорректный запрос (пустой `q`) остаются остановкой.
"""
from types import SimpleNamespace

from proxy.services.model_research_tool_service import model_rag_empty_queries, model_rag_failure_detail


EXECUTED_EMPTY = {'status': 'missing', 'operation': 'smeta_norm_native_rrf',
                  'inputs': [{'q': 'монтаж ковровой плитки'}],
                  'missing': ['no smeta norm cards matched query'],
                  'trace': {'rag': {'status': 'ok', 'collection': 'les_smeta_norm_cards'}}}
BLOCKED = {'status': 'blocked', 'operation': 'smeta_norm_native_rrf',
           'missing': ['dedicated smeta native RRF is not ready'],
           'trace': {'rag': {'status': 'not_ready'}}}
EMPTY_QUERY = {'status': 'missing', 'operation': 'native_rrf',
               'inputs': [{'q': ''}], 'missing': ['q'], 'trace': {}}


def test_executed_search_with_no_matches_does_not_stop_the_pass():
    assert model_rag_failure_detail([{'status': 'ok'}, EXECUTED_EMPTY]) is None


def test_blocked_search_still_stops_the_pass():
    detail = model_rag_failure_detail([{'status': 'ok'}, EXECUTED_EMPTY, BLOCKED])
    assert detail['code'] == 'MODEL_RAG_SEARCH_INCOMPLETE'
    assert detail['blocked_queries'] == [3], 'пустая выдача не входит в число отказов'


def test_empty_query_is_an_invalid_request_not_an_empty_result():
    detail = model_rag_failure_detail([EMPTY_QUERY])
    assert detail['blocked_queries'] == [1]
    assert detail['query_failures'][0]['reason'] == 'empty_query'


def test_empty_queries_are_reported_for_the_trace():
    assert model_rag_empty_queries([{'status': 'ok'}, EXECUTED_EMPTY, BLOCKED, EMPTY_QUERY]) == [2]


def test_model_sees_an_explicit_empty_result_marker():
    """Голый заголовок запроса неотличим от обрезанных карточек — пустоту надо назвать."""
    from proxy.services.chat_evidence_application_service import build_model_rag_evidence_groups

    card = SimpleNamespace(doc_name='smeta_norm_cards.v1', score=1.0, meta={},
                           content='Шифр: ГЭСН11-01-037-06\nУстройство покрытий из готовых ковровых изделий')
    groups, _chunks = build_model_rag_evidence_groups(
        [('ковровые покрытия', [card]), ('монтаж ковровой плитки на клей', [])],
        max_chars=4000, hits_per_query=6)
    empty = next(group for group in groups if 'Q2' in group)
    assert 'совпадений нет' in empty, empty
    assert 'не доказывает' in empty, 'пустая выдача не доказывает отсутствие нормы во всей базе'
    found = next(group for group in groups if 'Q1' in group)
    assert 'совпадений нет' not in found


def test_answer_contract_requires_a_disposition_for_the_product_of_each_row():
    """Контракт требует решения по изделию строки, не подменяя выбор модели правилом.

    Разбор 76 позиций (15.09) и аудит Codex 17.09: у монтажных норм изделие в норму
    не входит, а отдельной операции не было ни у одной строки (0 из 198). При этом
    автоматически добавлять изделие нельзя — среди таких позиций есть демонтажи.
    Поэтому от модели требуется явное решение из трёх, а выбор остаётся её.
    """
    from proxy.services.chat_evidence_application_service import model_answer_request

    text = model_answer_request('Смета по ведомости', model_driven=True)
    assert 'отдельной операцией' in text, 'поставка изделия отдельной операцией'
    assert 'included_in' in text and 'resource_action=included' in text, 'включение в ресурс работы'
    assert 'демонтаж' in text, 'обоснованное отсутствие потребности, например демонтаж'
    assert 'не добавляй изделие' in text.lower() or 'не добавляй' in text, (
        'и запрет добавлять изделие без потребности')


def test_payload_without_proof_of_execution_is_not_an_empty_result():
    """Пустая выдача пропускается только при доказанно выполненном поиске (проверка Codex 17.09)."""
    unproven = {'status': 'missing', 'operation': 'native_rrf',
                'inputs': [{'q': 'запрос'}], 'missing': ['no indexed chunks matched query'],
                'trace': {'status': 'blocked', 'error_code': 'native_rrf_unavailable'}}
    detail = model_rag_failure_detail([unproven])
    assert detail is not None and detail['blocked_queries'] == [1]
    assert model_rag_empty_queries([unproven]) == []


def test_general_rag_without_native_rrf_is_a_technical_failure():
    """Настоящий общий retrieval без native RRF — отказ, а не «совпадений нет»."""
    import asyncio
    import logging
    from proxy.services.retrieval_service import retrieve_chat_chunks
    from proxy.services.model_research_tool_service import ModelResearchToolService

    async def search():
        tool = ModelResearchToolService(
            retrieve=retrieve_chat_chunks, frozen_dataset_ids=('fixture-dataset',),
            retrieval_kwargs=dict(rag_backend=object(), reranker_enabled=False, reranker_available=False,
                                  reranker_cls=None, mlx_url='', logger=logging.getLogger('empty-search'),
                                  return_trace=True),
            fallback=lambda *_: {})
        return (await tool.execute({'tool': 'search_sources', 'args': {'q': 'fixture lookup'}})).payload

    payload = asyncio.run(search())
    assert payload['status'] == 'blocked', payload.get('status')
    assert model_rag_failure_detail([payload]) is not None
    assert model_rag_empty_queries([payload]) == []

