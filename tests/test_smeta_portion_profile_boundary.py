"""Execute the production portion boundary without starting inference or storage."""

import ast
import asyncio
import inspect
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service


class PortionReached(Exception):
    pass


def calls_function(node, name):
    return any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
               and child.func.id == name for child in ast.walk(node))


def portion_guard(function):
    candidates = [node for node in function.body if isinstance(node, ast.If)
                  and calls_function(node.test, 'profile_uses_smeta_norm_retrieval')
                  and calls_function(node, 'fit_smeta_portion_context')
                  and any(isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                          and test.left.id == 'portion_rows' and len(test.ops) == 1
                          and isinstance(test.ops[0], ast.Gt)
                          and isinstance(test.comparators[0], ast.Constant)
                          and test.comparators[0].value == 0 for test in ast.walk(node.test))]
    assert len(candidates) == 1, 'Expected the actual guarded portion-planning branch'
    return candidates[0]


def run_portion_boundary(profile, attachment, limit):
    # Compile actual portion initializers and its complete guard. Price-basis
    # persistence is a separate legitimate storage boundary without a portion limit.
    function = ast.parse(inspect.getsource(service._execute_chat_evidence_application)).body[0]
    start = next(i for i, node in enumerate(function.body)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "portion_rows" for t in node.targets))
    guard = portion_guard(function)
    initializers = [node for node in function.body[start:function.body.index(guard)]
                    if isinstance(node, (ast.Assign, ast.AnnAssign))
                    and any(isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
                            and child.id in {'portion_rows', 'portion_cursors', 'portion_state', 'document_price_basis'}
                            for child in ast.walk(node))]
    block = ast.AsyncFunctionDef(
        name="boundary", args=ast.arguments(posonlyargs=[], args=[ast.arg(arg="attachment_context")], kwonlyargs=[],
                                           kw_defaults=[], defaults=[]),
        body=initializers + [guard], decorator_list=[],
    )
    calls = []

    def store():
        calls.append("store")
        return None  # Existing supported unavailable-store fallback.

    def prepare(*args, **kwargs):
        assert kwargs['preset'] is preset
        assert 'boundary question' in kwargs['request_payload']
        assert kwargs['profile_prefix'] == 'boundary profile'
        calls.append("portion")
        raise PortionReached

    def source_limit(source):
        assert source == attachment  # Execute the production call with the full source.
        return limit

    preset = object()
    namespace = dict(vars(service))
    namespace.update(profile_snapshot=profile, attachment_context=attachment,
                     model_driven_retrieval=service.profile_uses_model_driven_retrieval(profile),
                     smeta_portion_rows=source_limit, portion_cursor_store=store,
                     fit_smeta_portion_context=prepare,
                     execution_preset=preset, sys_normal='boundary profile',
                     answer_form=SimpleNamespace(instruction=''), target_doc_filter=[],
                     req=SimpleNamespace(session_id="boundary", question='boundary question', output_directive=None))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[block], type_ignores=[])),
                 "<production-portion-boundary>", "exec"), namespace)
    try:
        asyncio.run(namespace["boundary"](attachment))
    except PortionReached:
        pass
    return calls


@pytest.mark.parametrize("profile, attachment, limit", [
    ({"mode": "chat"}, "complete attachment", 25),
    ({"mode": "chat", "rag_policy": {"model_authored_initial_query": True}}, "complete attachment", 25),
    ({"mode": "estimator"}, "", 25),
    ({"mode": "estimator"}, "complete attachment", 0),
    ({"mode": "estimator"}, "complete attachment", -1),
])
def test_ineligible_chat_never_opens_smeta_storage_or_prepares_a_portion(profile, attachment, limit):
    assert run_portion_boundary(profile, attachment, limit) == []


def test_estimator_with_attachment_keeps_existing_portion_and_store_path():
    assert run_portion_boundary({"mode": "estimator"}, "complete attachment", 25) == ["store", "portion"]


def test_document_price_basis_is_independent_of_disabled_portion_planning():
    function = ast.parse(inspect.getsource(service._execute_chat_evidence_application)).body[0]
    guards = [node for node in function.body if isinstance(node, ast.If)
              and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                      and call.func.attr == 'to_thread' and call.args
                      and isinstance(call.args[0], ast.Name)
                      and call.args[0].id == 'document_price_basis_or_error' for call in ast.walk(node))]
    assert len(guards) == 1 and guards[0] is not portion_guard(function)
    guard = guards[0]
    assert not any(isinstance(node, ast.Name) and node.id == 'portion_rows' for node in ast.walk(guard.test))
    source_sha_initializer = next(node for node in function.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'document_source_attachment_sha256'
                for target in node.targets))
    block = ast.AsyncFunctionDef(name='price_boundary',
        args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=[source_sha_initializer, guard], decorator_list=[])
    calls = []
    namespace = dict(vars(service))
    namespace.update(profile_snapshot={'mode':'estimator'}, source_attachment_context='complete attachment',
        source_attachment_id='', document_source_attachment_sha256='', retrieval_trace={},
        req=SimpleNamespace(session_id='boundary'), portion_rows=0,
        portion_cursor_store=lambda: calls.append('price_store'),
        document_price_basis_or_error=lambda *a, **k: calls.append('price_basis'))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[block], type_ignores=[])),
                 '<production-price-boundary>', 'exec'), namespace)
    asyncio.run(namespace['price_boundary']())
    assert calls == ['price_store', 'price_basis']
    assert run_portion_boundary({'mode':'estimator'}, 'complete attachment', 0) == []


def run_source_boundary(profile, preview, attachment_id):
    function = ast.parse(inspect.getsource(service._execute_chat_evidence_application)).body[0]
    def assignment(node, name):
        return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    start = next(i for i,n in enumerate(function.body) if assignment(n, 'attachment_context'))
    stop = next(i for i,n in enumerate(function.body) if assignment(n, 'portion_rows'))
    trace = {}
    block = ast.AsyncFunctionDef(name='boundary', args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),
        body=function.body[start:stop] + [ast.Return(value=ast.Name(id='attachment_context',ctx=ast.Load()))], decorator_list=[])
    namespace = dict(vars(service))
    namespace.update(req=SimpleNamespace(attachment_context=preview,attachment_id=attachment_id),
                     profile_snapshot=profile,retrieval_trace=trace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[block],type_ignores=[])), '<actual-source-boundary>', 'exec'),namespace)
    return asyncio.run(namespace['boundary']()),trace


def test_non_estimate_never_resolves_a_server_file_from_attachment_id():
    text,trace = run_source_boundary({'mode':'chat'},'bounded preview','read_123456abcdef')
    assert text == 'bounded preview'
    assert 'smeta_attachment_source' not in trace


@pytest.mark.parametrize('corruption',['missing','size','hash'])
def test_estimate_rejects_unverified_source_instead_of_using_incomplete_preview(tmp_path,monkeypatch,corruption):
    from proxy.services.chat_attachment_service import preserve_read_attachment
    root=tmp_path/'attachments'
    monkeypatch.setenv('LES_CHAT_ATTACHMENT_ROOT',str(root))
    if corruption != 'missing':
        source=tmp_path/'source.xlsx'
        source.write_bytes(b'original source')
        metadata=preserve_read_attachment(source,attachment_id='read_123456abcdef',original_name='source.xlsx')
        (root/metadata['stored_name']).write_bytes(b'changed  source' if corruption=='hash' else b'x')
    with pytest.raises(service.HTTPException) as caught:
        run_source_boundary({'mode':'estimator'},'incomplete preview','read_123456abcdef')
    assert caught.value.status_code == 422
    assert caught.value.detail['code'] == 'SMETA_ATTACHMENT_SOURCE_UNAVAILABLE'
