"""Sequential crash/retry of real checkpoint and immutable artifact stores."""
import asyncio
import copy
import json
import sqlite3
from dataclasses import replace

import openpyxl
import pytest

from proxy.services.artifact_revision_service import ArtifactRevisionStore
from proxy.services.chat_attachment_service import preserve_read_attachment
from proxy.services.workflow_checkpoint_service import WorkflowCheckpointService
from proxy.services.workbook_tool_service import WorkbookExecutionContext, build_lsr_workbook


def fixture(tmp_path):
    source=tmp_path/'source.xlsx'
    book=openpyxl.Workbook(); book.active.append(['Synthetic source',2]); book.save(source); book.close()
    attachment=preserve_read_attachment(source,attachment_id='read_123456abcdef',original_name='source.xlsx',root=tmp_path/'attachments')
    calls=[]
    receipts=[dict(source_row='1',work_id='w',status='resource_review_required',calculation_ref='exact-receipt')]
    def adapter(path,args,out,progress):
        calls.append(copy.deepcopy(args))
        book=openpyxl.Workbook(); book.active.append(['Model-authored operation',2]); book.save(out); book.close()
        return dict(file_path=out,source_rows=1,bound_rows=0,row_calculation=copy.deepcopy(receipts),missing=['unknown price'])
    ctx=WorkbookExecutionContext(session_id='session',idempotency_key='operation',model_decision_revision='decision',
        profile_revision_id='profile',model_identity='model',model_preset='preset',attachment_root=tmp_path/'attachments',
        work_dir=tmp_path/'work',checkpoints=WorkflowCheckpointService(tmp_path/'checkpoints.sqlite'),
        artifacts=ArtifactRevisionStore(tmp_path/'artifacts.sqlite',tmp_path/'artifacts'),lsr_adapter=adapter,
        document_price_basis=dict(schema='les.document-price-basis.v1',status='not_configured',path=None,identity=None),
        source_revision='source',source_attachment_sha256=attachment['sha256'])
    args=dict(attachment_id=attachment['attachment_id'],decisions=[dict(source_row='1',work_id='w',
        title='Model choice',quantity=2,unit='шт',norm_code='ГЭСН01-01-001-01',evidence_refs=['Q1.H1'])])
    return ctx,args,calls,receipts


def rows(ctx):
    with sqlite3.connect(ctx.artifacts.db_path) as conn:
        return conn.execute('SELECT revision_id,metadata_json FROM artifact_revisions ORDER BY rowid').fetchall()


def fail_complete_once(monkeypatch,ctx,*,after_commit=False):
    original=ctx.checkpoints.complete
    fired=[]
    def fail(checkpoint_id,revision_id):
        if not fired:
            fired.append(True)
            if after_commit:
                original(checkpoint_id,revision_id)
            raise OSError('Synthetic checkpoint completion interruption')
        return original(checkpoint_id,revision_id)
    monkeypatch.setattr(ctx.checkpoints,'complete',fail)


def test_artifact_commit_before_checkpoint_failure_recovers_without_adapter_after_restart(tmp_path,monkeypatch):
    ctx,args,calls,receipts=fixture(tmp_path)
    fail_complete_once(monkeypatch,ctx)
    first=asyncio.run(build_lsr_workbook(args,ctx))
    assert first['status']=='failed' and len(rows(ctx))==1
    committed=ctx.artifacts.get_revision(rows(ctx)[0][0])
    restarted=replace(ctx,checkpoints=WorkflowCheckpointService(ctx.checkpoints.db_path),
        artifacts=ArtifactRevisionStore(ctx.artifacts.db_path,ctx.artifacts.root))
    recovered=asyncio.run(build_lsr_workbook(args,restarted))
    repeated=asyncio.run(build_lsr_workbook(args,restarted))
    assert recovered['artifact']['revision_id']==repeated['artifact']['revision_id']==committed.revision_id
    assert recovered['artifact']['sha256']==committed.sha256 and len(calls)==len(rows(ctx))==1
    assert recovered['row_calculation']==receipts and recovered['missing']==['unknown price']
    assert calls[0]['decisions']==args['decisions']
    assert calls[0]['_document_price_basis']==ctx.document_price_basis


def test_failure_after_checkpoint_commit_does_not_try_to_fail_completed_checkpoint(tmp_path,monkeypatch):
    ctx,args,calls,receipts=fixture(tmp_path)
    fail_complete_once(monkeypatch,ctx,after_commit=True)
    result=asyncio.run(build_lsr_workbook(args,ctx))
    assert result['status']=='complete' and result['row_calculation']==receipts
    assert len(calls)==len(rows(ctx))==1
    assert ctx.checkpoints.get(result['checkpoint']['checkpoint_id']).status=='complete'


def test_two_committed_orphans_are_explicitly_ambiguous_without_adapter(tmp_path,monkeypatch):
    ctx,args,calls,_=fixture(tmp_path); fail_complete_once(monkeypatch,ctx)
    asyncio.run(build_lsr_workbook(args,ctx))
    with sqlite3.connect(ctx.artifacts.db_path) as conn:
        record=conn.execute('SELECT * FROM artifact_revisions').fetchone()
        names=[r[1] for r in conn.execute('PRAGMA table_info(artifact_revisions)')]
        duplicate=dict(zip(names,record)); duplicate.update(revision_id='rev_duplicate',artifact_id='art_duplicate',relative_path='duplicate.xlsx')
        conn.execute('INSERT INTO artifact_revisions VALUES('+','.join('?' for _ in names)+')',[duplicate[n] for n in names])
    result=asyncio.run(build_lsr_workbook(args,ctx))
    assert result['code']=='WORKBOOK_ARTIFACT_RECOVERY_AMBIGUOUS'
    assert len(calls)==1 and len(rows(ctx))==2


@pytest.mark.parametrize('field,value', [('session_id','other-session'),('attachment_sha256','f'*64),
    ('normalized_args_sha256','f'*64),('name','build_vor_workbook')])
def test_orphan_provenance_mismatch_is_not_silently_regenerated(tmp_path,monkeypatch,field,value):
    ctx,args,calls,_=fixture(tmp_path); fail_complete_once(monkeypatch,ctx)
    asyncio.run(build_lsr_workbook(args,ctx))
    revision_id,raw=rows(ctx)[0]; meta=json.loads(raw); meta['tool_calls'][0][field]=value
    with sqlite3.connect(ctx.artifacts.db_path) as conn:
        conn.execute('UPDATE artifact_revisions SET metadata_json=? WHERE revision_id=?',(json.dumps(meta),revision_id))
    result=asyncio.run(build_lsr_workbook(args,ctx))
    assert result['code']=='WORKBOOK_ARTIFACT_RECOVERY_CONFLICT' and len(calls)==len(rows(ctx))==1


@pytest.mark.parametrize('damage', ['missing','corrupt'])
def test_unavailable_orphan_uses_one_repair_child_and_recovers_child_commit(tmp_path,monkeypatch,damage):
    ctx,args,calls,receipts=fixture(tmp_path); fail_complete_once(monkeypatch,ctx)
    asyncio.run(build_lsr_workbook(args,ctx))
    old=ctx.artifacts.get_revision(rows(ctx)[0][0]); path=ctx.artifacts.resolve_path(old.revision_id)
    if damage=='missing': path.unlink()
    else: path.write_bytes(b'Synthetic corruption')
    # Interrupt the new repair child after its immutable revision is committed.
    fail_complete_once(monkeypatch,ctx)
    repaired=asyncio.run(build_lsr_workbook(args,ctx))
    assert repaired['status']=='failed' and len(rows(ctx))==2 and len(calls)==2
    recovered=asyncio.run(build_lsr_workbook(args,ctx))
    assert recovered['status']=='complete' and recovered['row_calculation']==receipts
    assert recovered['artifact']['parent_revision_id']==old.revision_id
    assert len(rows(ctx))==len(calls)==2


def test_cancellation_is_persisted_and_propagated_without_artifact(tmp_path):
    ctx,args,_,_=fixture(tmp_path)
    async def cancelled(*a,**k): raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(build_lsr_workbook(args,replace(ctx,lsr_adapter=cancelled)))
    with sqlite3.connect(ctx.checkpoints.db_path) as conn:
        status,blockers=conn.execute('SELECT status,blockers_json FROM workflow_checkpoints').fetchone()
    assert status=='blocked' and 'WORKBOOK_CANCELLED' in json.loads(blockers)
    assert rows(ctx)==[]


def test_repeated_checkpoint_storage_failure_never_regenerates_committed_artifact(tmp_path,monkeypatch):
    ctx,args,calls,_=fixture(tmp_path)
    def unavailable(*a,**k): raise OSError('Synthetic storage unavailable')
    monkeypatch.setattr(ctx.checkpoints,'complete',unavailable)
    first=asyncio.run(build_lsr_workbook(args,ctx))
    assert first['status']=='failed'
    for _ in range(2):
        retry=asyncio.run(build_lsr_workbook(args,ctx))
        assert retry['code']=='WORKBOOK_CHECKPOINT_RECOVERY_FAILED'
    assert len(calls)==len(rows(ctx))==1


def test_cancel_remains_cancel_when_checkpoint_cleanup_storage_fails(tmp_path,monkeypatch):
    ctx,args,_,_=fixture(tmp_path)
    async def cancelled(*a,**k): raise asyncio.CancelledError('Synthetic transport cancel')
    def unavailable(*a,**k): raise OSError('Synthetic checkpoint cleanup unavailable')
    monkeypatch.setattr(ctx.checkpoints,'record_status',unavailable)
    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(build_lsr_workbook(args,replace(ctx,lsr_adapter=cancelled)))
    assert isinstance(caught.value.__cause__,OSError)
    assert rows(ctx)==[]
