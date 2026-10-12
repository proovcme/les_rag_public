"""Regression from .185: optional archive cards must not starve model queries."""
from types import SimpleNamespace
import pytest
from proxy.services.chat_evidence_application_service import build_model_rag_evidence_groups


def hit(name, body, **meta):
    return SimpleNamespace(doc_name=name, doc_id=name, score=1.0, content=body, meta=meta)


@pytest.mark.parametrize('kind', ['practice_candidate', 'material_candidate'])
@pytest.mark.parametrize('practice_first', [True, False])
@pytest.mark.parametrize('full_read', [True, False])
@pytest.mark.parametrize('budget', [2200, 3500])
def test_optional_full_card_preserves_query_preview_resources(kind, practice_first, full_read, budget):
    preview = ('Шифр: TEST-Q\nСостав работы: ' + 'Операция. ' * 65
               + '\nМашины и материалы: ' + 'Ресурс; ' * 90 + 'END-QUERY-RESOURCE')
    archive = ('Шифр: TEST-P\nАрхивная практика: ' + 'Архивный контекст. ' * 135).rstrip()
    query = ('Буквальный запрос модели', [hit('norm-preview', preview)])
    optional = ('Дополнительная практика', [hit('archive-card', archive, smeta_full_read=full_read, **{kind: True})])
    alone, _ = build_model_rag_evidence_groups([query], max_chars=budget, hits_per_query=6)
    assert preview in '\n\n'.join(alone)
    inputs = [optional, query] if practice_first else [query, optional]
    blocks, _ = build_model_rag_evidence_groups(inputs, max_chars=budget, hits_per_query=6)
    rendered = '\n\n'.join(blocks)
    assert len(rendered) <= budget
    assert preview in rendered, 'Optional full card consumed capacity available to model query resources'
    assert query[0] in rendered
    assert query[1][0].content == preview and optional[1][0].content == archive
    roomy, _ = build_model_rag_evidence_groups(inputs, max_chars=8000, hits_per_query=6)
    assert preview in '\n\n'.join(roomy) and archive in '\n\n'.join(roomy)


@pytest.mark.parametrize('kind', ['practice_candidate', 'material_candidate'])
def test_oversized_query_keeps_query_only_capacity_with_optional_practice(kind):
    preview = 'Состав работы: ' + 'Подготовка и монтаж. ' * 240 + 'RESOURCE-END'
    query = ('Исходный запрос', [hit('norm-preview', preview)])
    optional = ('Архив', [hit('archive-card', 'Архивный пример. ' * 70,
                             smeta_full_read=True, **{kind: True})])
    _, baseline = build_model_rag_evidence_groups([query], max_chars=3500, hits_per_query=6)
    groups, candidate = build_model_rag_evidence_groups([query, optional], max_chars=3500, hits_per_query=6)
    assert [c.content for c in candidate] == [c.content for c in baseline]
    assert all(c.doc_name == 'norm-preview' for c in candidate)
    assert len('\n\n'.join(groups)) <= 3500
