"""Actual source revision survives reader caching, replacement and SQLite races."""
import hashlib
import os
from pathlib import Path
import sqlite3
from contextlib import closing

import pytest

from proxy.services import gesn_service as gs
from proxy.smeta_core import norm_browser as browser

CODE = 'ГЭСН01-01-001-01'


def base(path, consumption, *, wal=False):
    with closing(sqlite3.connect(path)) as conn, conn:
        if wal:
            conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
            CREATE TABLE norms(norm_key TEXT PRIMARY KEY,norm_id TEXT,edition TEXT,
            display_code TEXT,base_type TEXT,bare_code TEXT,norm_name TEXT,norm_unit TEXT,
            work_steps TEXT,source_doc TEXT,source_guid TEXT,resource_count INTEGER);
            CREATE TABLE resources(id INTEGER PRIMARY KEY,parent_norm_id TEXT,norm_key TEXT,
            kind TEXT,resource_code TEXT,resource_name TEXT,resource_unit TEXT,per_unit REAL,price REAL);
        ''')
        conn.execute('INSERT INTO norms VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('ГЭСН:01-01-001-01','fixture-norm','fixture-edition',CODE,'ГЭСН',
             '01-01-001-01','Synthetic operation','шт','[]','synthetic source','guid',1))
        conn.execute('INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?)',
            (1,'fixture-norm','ГЭСН:01-01-001-01','material','R','Synthetic resource','шт',consumption,10))
    return path


@pytest.fixture(autouse=True)
def clear_readers():
    gs.load_base_norms.cache_clear()
    gs.load_structured_base_norms.cache_clear()
    yield
    gs.load_base_norms.cache_clear()
    gs.load_structured_base_norms.cache_clear()


def expected(path):
    return dict(schema='les.norm-revision.v1',base_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        norm_id='fixture-norm',norm_key='ГЭСН:01-01-001-01',edition='fixture-edition',base_type='ГЭСН')


def test_card_and_reader_identity_matches_actual_bytes(tmp_path):
    path = base(tmp_path/'A.sqlite',1)
    card, = browser._code_listing('ГЭСН','01-01-001-01',base_path=path)
    norm = gs.get_norm(CODE,base_path=str(path))
    assert card.get('normative_identity')==expected(path)
    assert norm.get('normative_identity')==expected(path)


@pytest.mark.parametrize('reader', ['card', 'catalog'])
def test_identical_metadata_stamp_cannot_reuse_old_content_identity(tmp_path, monkeypatch, reader):
    from proxy.smeta_core import norm_revision as revision
    path = base(tmp_path/'active.sqlite', 1)
    replacement = base(tmp_path/'replacement.sqlite', 9)
    old_stat = path.stat()
    stamp = revision.revision_fingerprint(path)
    identity_a = expected(path)
    def read():
        if reader == 'card':
            return browser._code_listing('ГЭСН', '01-01-001-01', base_path=path)[0]
        return gs.get_norm(CODE, base_path=str(path))
    assert read()['resources'][0]['per_unit'] == 1
    path.write_bytes(replacement.read_bytes())
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert path.stat().st_size == old_stat.st_size
    identity_b = expected(path)
    assert identity_b != identity_a
    # Fault injection represents a filesystem metadata collision, not a reader mock.
    monkeypatch.setattr(revision, 'revision_fingerprint', lambda _: stamp)
    monkeypatch.setattr(gs, 'revision_fingerprint', lambda _: stamp)
    current = read()
    assert current['resources'][0]['per_unit'] == 9
    assert current['normative_identity'] == identity_b


def test_identical_metadata_stamp_mid_read_still_reports_content_conflict(tmp_path, monkeypatch):
    from proxy.smeta_core import norm_revision as revision
    path = base(tmp_path/'active.sqlite', 1)
    replacement = base(tmp_path/'replacement.sqlite', 9)
    stamp = revision.revision_fingerprint(path)
    original = browser._card
    def changed(conn, row, **kwargs):
        path.write_bytes(replacement.read_bytes())
        return original(conn, row, **kwargs)
    monkeypatch.setattr(revision, 'revision_fingerprint', lambda _: stamp)
    monkeypatch.setattr(browser, '_card', changed)
    with pytest.raises(revision.NormRevisionConflict, match='changed_during_read'):
        browser._code_listing('ГЭСН', '01-01-001-01', base_path=path)


def test_sql_writer_cannot_commit_while_read_revision_is_hashed(tmp_path, monkeypatch):
    from proxy.smeta_core import norm_revision as revision
    path = base(tmp_path/'locked.sqlite', 1)
    original = revision.revision_sha256
    attempts = []
    def checked_hash(filename, stamp):
        with closing(sqlite3.connect(path, timeout=0)) as writer:
            try:
                writer.execute('UPDATE resources SET per_unit=9')
                with pytest.raises(sqlite3.OperationalError, match='locked'):
                    writer.commit()
                attempts.append(True)
            finally:
                writer.rollback()
        return original(filename, stamp)
    checked_hash.cache_clear = original.cache_clear
    monkeypatch.setattr(revision, 'revision_sha256', checked_hash)
    card, = browser._code_listing('ГЭСН', '01-01-001-01', base_path=path)
    assert attempts and card['resources'][0]['per_unit'] == 1
    assert card['normative_identity'] == expected(path)


def test_catalog_connection_has_one_owner_and_one_validated_close(tmp_path, monkeypatch):
    path = base(tmp_path/'owner.sqlite', 1)
    original = gs._connect_structured_base_readonly
    closed = []
    def observed_connection(filename):
        conn = original(filename)
        close = conn.close
        def observed_close():
            closed.append(True)
            close()
        conn.close = observed_close
        return conn
    monkeypatch.setattr(gs, '_connect_structured_base_readonly', observed_connection)
    assert gs.get_norm(CODE, base_path=str(path))['resources'][0]['per_unit'] == 1
    assert len(closed) == 1


def test_concurrent_catalog_clear_cannot_split_insert_and_recency_update(tmp_path, monkeypatch):
    from collections import OrderedDict
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    path = base(tmp_path/'concurrent.sqlite', 1)
    inserted, cleared = Event(), Event()
    class ScheduledCatalogs(OrderedDict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            inserted.set()
            # Give a concurrent clear the exact old assignment/move race window.
            cleared.wait(0.1)
    monkeypatch.setattr(gs, '_retained_catalogs', ScheduledCatalogs())
    def clear_during_insert():
        assert inserted.wait(5)
        gs.load_base_norms.cache_clear()
        cleared.set()
    with ThreadPoolExecutor(max_workers=1) as workers:
        cleared_call = workers.submit(clear_during_insert)
        norm = gs.get_norm(CODE, base_path=str(path))
        cleared_call.result(timeout=5)
    assert norm['resources'][0]['per_unit'] == 1
    assert gs.load_structured_base_norms.cache_info().currsize == 0


@pytest.mark.parametrize('clear', [False,True])
def test_expected_revision_retained_or_conflicts_after_restart(tmp_path, clear):
    path = base(tmp_path/'active.sqlite',1)
    identity = expected(path)
    first = gs.get_norm(CODE,base_path=str(path))
    assert first['resources'][0]['per_unit']*2*10==20
    base(tmp_path/'B.sqlite',9).replace(path)
    if clear:
        gs.load_base_norms.cache_clear()
        from proxy.smeta_core.norm_revision import NormRevisionConflict
        with pytest.raises(NormRevisionConflict) as failure:
            gs.get_norm(CODE,base_path=str(path),expected_identity=identity)
        assert failure.value.expected==identity
        assert failure.value.actual['base_sha256']==expected(path)['base_sha256']
    else:
        retained = gs.get_norm(CODE,base_path=str(path),expected_identity=identity)
        assert retained['resources'][0]['per_unit']*2*10==20
        retained['resources'][0]['per_unit']=999
        assert gs.get_norm(CODE,base_path=str(path),expected_identity=identity)['resources'][0]['per_unit']==1
    current = gs.get_norm(CODE,base_path=str(path))
    assert current['resources'][0]['per_unit']*2*10==180


def test_same_path_replacement_same_size_mtime_is_not_stale(tmp_path):
    path=base(tmp_path/'active.sqlite',1)
    old_stat=path.stat()
    gs.get_norm(CODE,base_path=str(path))
    replacement=base(tmp_path/'replacement.sqlite',9)
    assert replacement.stat().st_size==old_stat.st_size
    os.utime(replacement,ns=(old_stat.st_atime_ns,old_stat.st_mtime_ns))
    replacement.replace(path)
    assert gs.get_norm(CODE,base_path=str(path))['resources'][0]['per_unit']==9


def test_expected_unknown_snapshot_does_not_fall_back_to_current(tmp_path):
    path=base(tmp_path/'A.sqlite',1)
    identity=expected(path)
    base(tmp_path/'B.sqlite',9).replace(path)
    from proxy.smeta_core.norm_revision import NormRevisionConflict
    with pytest.raises(NormRevisionConflict) as failure:
        gs.get_norm(CODE,base_path=str(path),expected_identity=identity)
    assert failure.value.expected==identity and failure.value.reason


def test_uncheckpointed_wal_is_not_signed_as_main_file(tmp_path):
    path=base(tmp_path/'wal.sqlite',1,wal=True)
    writer=sqlite3.connect(path)
    writer.execute('UPDATE resources SET per_unit=9')
    writer.commit()
    try:
        from proxy.smeta_core.norm_revision import NormRevisionConflict
        with pytest.raises(NormRevisionConflict,match='wal'):
            browser._code_listing('ГЭСН','01-01-001-01',base_path=path)
        with pytest.raises(NormRevisionConflict,match='wal'):
            gs.get_norm(CODE,base_path=str(path))
    finally:
        writer.close()


def test_card_race_cannot_mix_norm_and_new_resources(tmp_path,monkeypatch):
    path=base(tmp_path/'race.sqlite',1,wal=True)
    original=browser._card
    writers=[]
    def changed(conn,row,**kwargs):
        writer=sqlite3.connect(path)
        writer.execute('UPDATE resources SET per_unit=9')
        writer.commit()
        writers.append(writer)
        return original(conn,row,**kwargs)
    monkeypatch.setattr(browser,'_card',changed)
    try:
        from proxy.smeta_core.norm_revision import NormRevisionConflict
        with pytest.raises(NormRevisionConflict):
            browser._code_listing('ГЭСН','01-01-001-01',base_path=path)
    finally:
        for writer in writers:
            writer.close()


def test_manifest_sha_cache_detects_replacement_with_same_size_and_mtime(tmp_path):
    path=base(tmp_path/'active.sqlite',1)
    stat=path.stat()
    first=browser._sha256_for_stat(str(path),stat.st_mtime_ns,stat.st_size)
    replacement=base(tmp_path/'B.sqlite',9)
    os.utime(replacement,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    replacement.replace(path)
    second=browser._sha256_for_stat(str(path),stat.st_mtime_ns,stat.st_size)
    assert second==expected(path)['base_sha256'] and second!=first


def test_pinned_reads_reuse_snapshot_but_fresh_sql_reads_hash_content(tmp_path,monkeypatch):
    path=base(tmp_path/'A.sqlite',1)
    identity=expected(path)
    original=Path.open
    reads=[]
    def counted(self,*args,**kwargs):
        if self==path and args and args[0]=='rb':
            reads.append(self)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'open',counted)
    gs.get_norm(CODE,base_path=str(path))
    initial_reads = len(reads)
    assert initial_reads > 0
    for _ in range(10):
        assert gs.get_norm(CODE,base_path=str(path),expected_identity=identity)['resources'][0]['per_unit']==1
    assert len(reads) == initial_reads
    browser._code_listing('ГЭСН','01-01-001-01',base_path=path)
    assert len(reads) > initial_reads


@pytest.mark.parametrize('field', ['norm_id','norm_key','edition','base_type','schema'])
def test_expected_identity_checks_every_field(tmp_path,field):
    from proxy.smeta_core.norm_revision import NormRevisionConflict
    path=base(tmp_path/'A.sqlite',1)
    identity=expected(path)
    gs.get_norm(CODE,base_path=str(path))
    identity[field]='different'
    with pytest.raises(NormRevisionConflict) as failure:
        gs.get_norm(CODE,base_path=str(path),expected_identity=identity)
    assert failure.value.expected==identity and failure.value.actual==expected(path)


@pytest.mark.parametrize('loader', [gs.load_base_norms,gs.load_structured_base_norms])
def test_public_loader_cannot_modify_frozen_source_snapshot(tmp_path,loader):
    path=base(tmp_path/'A.sqlite',1)
    identity=expected(path)
    public=loader(str(path))
    public['ГЭСН:01-01-001-01']['resources'][0]['per_unit']=9
    assert gs.get_norm(CODE,base_path=str(path),expected_identity=identity)['resources'][0]['per_unit']==1
    assert gs.get_norm(CODE,base_path=str(path))['resources'][0]['per_unit']==1


@pytest.mark.parametrize('name', ['source.sqlite', "Нормативная база 'редакция'.sqlite"])
def test_inplace_update_same_inode_size_and_restored_mtime_has_actual_identity(tmp_path,name):
    path=base(tmp_path/name,1)
    before=path.stat()
    identity_a=expected(path)
    gs.get_norm(CODE,base_path=str(path))
    browser._code_listing('ГЭСН','01-01-001-01',base_path=path)
    with closing(sqlite3.connect(path)) as conn,conn:
        conn.execute('UPDATE resources SET per_unit=9')
    os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
    after=path.stat()
    assert (before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns)
    actual=expected(path)
    assert actual['base_sha256']!=identity_a['base_sha256']
    card,=browser._code_listing('ГЭСН','01-01-001-01',base_path=path)
    assert card['resources'][0]['per_unit']==9
    assert card['normative_identity']==actual
    assert gs.get_norm(CODE,base_path=str(path))['normative_identity']==actual
    assert gs.get_norm(CODE,base_path=str(path))['resources'][0]['per_unit']==9
    assert gs.get_norm(CODE,base_path=str(path),expected_identity=identity_a)['resources'][0]['per_unit']==1


def test_windows_metadata_open_failure_never_returns_a_fingerprint(tmp_path):
    from proxy.smeta_core import norm_revision as revision
    if os.name=='nt':
        with pytest.raises(revision.NormRevisionConflict,match='metadata_open') as failure:
            revision._windows_change_time(tmp_path/'missing.sqlite')
        assert failure.value.__cause__.winerror==2
    else:
        with pytest.raises(OSError):
            revision.revision_fingerprint(tmp_path/'missing.sqlite')


def test_windows_metadata_query_failure_closes_the_real_handle(tmp_path,monkeypatch):
    from proxy.smeta_core import norm_revision as revision
    if os.name!='nt':
        with pytest.raises(OSError):
            revision.revision_fingerprint(tmp_path/'missing.sqlite')
        return
    import ctypes
    path=base(tmp_path/'handle.sqlite',1)
    create,query,close=revision._windows_file_api()
    closed=[]
    def query_failure(*args):
        ctypes.set_last_error(31)
        return 0
    def observed_close(handle):
        closed.append(handle)
        return close(handle)
    monkeypatch.setattr(revision,'_windows_file_api',lambda:(create,query_failure,observed_close))
    with pytest.raises(revision.NormRevisionConflict,match='metadata_query') as failure:
        revision.revision_fingerprint(path)
    assert failure.value.__cause__.winerror==31 and len(closed)==1
    # The observer calls the real CloseHandle; the source remains usable afterward.
    path.replace(tmp_path/'closed.sqlite')


@pytest.mark.parametrize('restore_mtime',[False,True])
def test_committed_rollback_writer_still_open_cannot_stamp_new_bytes_with_old_sha(tmp_path,restore_mtime):
    path=base(tmp_path/'open-writer.sqlite',1)
    before=path.stat()
    identity_a=expected(path)
    gs.get_norm(CODE,base_path=str(path))
    writer=sqlite3.connect(path)
    try:
        assert writer.execute('PRAGMA journal_mode').fetchone()[0]=='delete'
        writer.execute('UPDATE resources SET per_unit=9')
        writer.commit()
        if restore_mtime:
            os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        actual=expected(path)
        assert actual['base_sha256']!=identity_a['base_sha256']
        card,=browser._code_listing('ГЭСН','01-01-001-01',base_path=path)
        assert card['resources'][0]['per_unit']==9 and card['normative_identity']==actual
        norm=gs.get_norm(CODE,base_path=str(path))
        assert norm['resources'][0]['per_unit']==9 and norm['normative_identity']==actual
    finally:
        writer.close()
