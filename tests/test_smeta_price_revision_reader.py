"""Actual price bytes, metadata and ambiguity stay pinned through reader caching."""
import hashlib
import os

import pandas as pd
import pytest

from proxy.services import fgis_price_service as prices


@pytest.fixture(autouse=True)
def clear_books():
    prices.get_pricebook.cache_clear()
    yield
    prices.get_pricebook.cache_clear()


def source(path,amount=10,**changes):
    record=dict(code='R',name='Synthetic cable',unit='1000 м',price_current=amount,
        price_current_eff=amount,region='Synthetic region',quarter='2026-Q2',version='synthetic-v1')
    record.update(changes)
    pd.DataFrame([record]).to_parquet(path,index=False)
    return path


def test_file_identity_and_lookup_provenance_are_actual_independent_copies(tmp_path):
    path=source(tmp_path/'book.parquet')
    book=prices.get_pricebook(str(path))
    identity=book.identity
    assert identity==dict(schema='les.pricebook-revision.v1',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        pricebook_id='book',region='Synthetic region',period='2026-Q2',version='synthetic-v1')
    identity['region']='modified'
    row=book.lookup('R')
    assert row['price_record_identity']['pricebook_identity']==book.identity
    assert row['price_record_identity']['source_row']==1
    row['price_current']=999
    row['price_record_identity']['pricebook_identity']['region']='modified'
    assert book.lookup('R')['price_current']==10 and book.identity['region']=='Synthetic region'
    browsed=book.browse('Synthetic cable')[0]
    assert browsed['price_record_identity']==book.lookup('R')['price_record_identity']
    browsed['price_record_identity']['pricebook_identity']['region']='modified'
    assert book.lookup('R')['price_record_identity']['pricebook_identity']['region']=='Synthetic region'


@pytest.mark.parametrize('clear',[False,True])
def test_replaced_book_retains_exact_snapshot_or_explicitly_conflicts(tmp_path,clear):
    path=source(tmp_path/'book.parquet',10)
    first=prices.get_pricebook(str(path))
    identity=first.identity
    source(tmp_path/'replacement.parquet',90).replace(path)
    if clear:
        prices.get_pricebook.cache_clear()
        with pytest.raises(prices.PriceBookRevisionConflict) as failure:
            prices.get_pricebook(str(path),expected_identity=identity)
        assert failure.value.expected==identity and failure.value.actual['sha256']!=identity['sha256']
    else:
        assert prices.get_pricebook(str(path),expected_identity=identity).lookup('R')['price_current']==10
    assert prices.get_pricebook(str(path)).lookup('R')['price_current']==90


def test_inplace_same_inode_restored_mtime_does_not_reuse_old_book(tmp_path):
    path=source(tmp_path/'book.parquet',10)
    before=path.stat()
    prices.get_pricebook(str(path))
    source(path,90)
    os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
    assert path.stat().st_ino==before.st_ino
    assert path.stat().st_size==before.st_size
    current=prices.get_pricebook(str(path))
    assert current.lookup('R')['price_current']==90
    assert current.identity['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()


def test_conflicting_exact_records_never_return_first_price():
    book=prices.PriceBook([dict(code='R',name='Synthetic',unit='м',price_current=10),
        dict(code='R',name='Synthetic',unit='м',price_current=20)])
    assert book.lookup('R') is None
    diagnostic=book.lookup_diagnostic('R')
    assert diagnostic['status']=='ambiguous' and len(diagnostic['candidates'])==2
    assert [r['price_current'] for r in diagnostic['candidates']]==[10,20]
    assert len({r['price_record_identity']['record_id'] for r in diagnostic['candidates']})==2


def test_identical_duplicates_resolve_and_memory_book_does_not_claim_file_sha():
    row=dict(code='R',name='Synthetic',unit='м',price_current=10)
    book=prices.PriceBook([row,dict(row)],region='Memory region',quarter='Memory period')
    row['price_current']=90
    assert book.lookup('R')['price_current']==10
    assert book.lookup_diagnostic('R')['status']=='resolved'
    assert book.identity['sha256'] is None
    assert book.lookup_diagnostic('missing')['status']=='missing'


@pytest.mark.parametrize('field',['region','quarter','version'])
def test_mixed_file_metadata_fails_instead_of_taking_first_row(tmp_path,field):
    path=source(tmp_path/'mixed.parquet')
    frame=pd.read_parquet(path)
    other=frame.iloc[0].to_dict()
    other[field]='different'
    pd.concat([frame,pd.DataFrame([other])],ignore_index=True).to_parquet(path,index=False)
    with pytest.raises(prices.PriceBookRevisionConflict,match='metadata'):
        prices.get_pricebook(str(path))


def test_race_during_decode_cannot_assign_old_sha_to_new_rows(tmp_path,monkeypatch):
    path=source(tmp_path/'race.parquet')
    original=pd.read_parquet
    def changed(value,*args,**kwargs):
        source(path,90)
        return original(value,*args,**kwargs)
    monkeypatch.setattr(pd,'read_parquet',changed)
    with pytest.raises(prices.PriceBookRevisionConflict,match='revision'):
        prices.get_pricebook(str(path))


def test_decode_race_with_colliding_file_metadata_is_detected(tmp_path, monkeypatch):
    path = source(tmp_path / 'same-stamp-race.parquet')
    stamp = path.stat()
    old_bytes = path.read_bytes()
    original = pd.read_parquet
    fingerprint = prices._price_stamp(path)
    # Model a metadata collision deterministically; the Parquet bytes really change.
    monkeypatch.setattr(prices, '_price_stamp', lambda _path: fingerprint)

    def changed(value, *args, **kwargs):
        source(path, 90)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert path.stat().st_size == stamp.st_size
        assert path.read_bytes() != old_bytes
        return original(value, *args, **kwargs)

    monkeypatch.setattr(pd, 'read_parquet', changed)
    with pytest.raises(prices.PriceBookRevisionConflict, match='revision'):
        prices.get_pricebook(str(path))


def test_document_basis_never_resolves_later_default(tmp_path,monkeypatch):
    path=source(tmp_path/'book.parquet')
    monkeypatch.setattr(prices,'resolve_pricebook_path',lambda *_:str(path))
    basis=prices.capture_price_basis()
    assert basis['schema']=='les.document-price-basis.v1' and basis['status']=='pinned'
    assert basis['path']==str(path.resolve()) and basis['identity']==prices.get_pricebook(str(path)).identity
    monkeypatch.setattr(prices,'resolve_pricebook_path',lambda *_:pytest.fail('Existing basis consulted default'))
    assert prices.pricebook_for_basis(basis).lookup('R')['price_current']==10
    assert prices.pricebook_for_basis(dict(schema='les.document-price-basis.v1',status='not_configured',path=None,identity=None)) is None
    assert prices.pricebook_for_basis(dict(schema='les.document-price-basis.v1',status='legacy_unpinned',path=None,identity=None)) is None


def test_missing_expected_file_after_cache_clear_is_a_conflict(tmp_path):
    path=source(tmp_path/'missing.parquet')
    identity=prices.get_pricebook(str(path)).identity
    path.unlink()
    prices.get_pricebook.cache_clear()
    with pytest.raises(prices.PriceBookRevisionConflict):
        prices.get_pricebook(str(path),expected_identity=identity)


def test_actual_bytes_win_even_if_filesystem_fingerprint_collides(tmp_path,monkeypatch):
    path=source(tmp_path/'collision.parquet',10)
    stamp=prices._price_stamp(path)
    monkeypatch.setattr(prices,'_price_stamp',lambda *_:stamp)
    first=prices.get_pricebook(str(path))
    source(path,90)
    current=prices.get_pricebook(str(path))
    assert current.lookup('R')['price_current']==90
    assert current.identity['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert current.identity!=first.identity


def test_corrupt_parquet_is_a_typed_conflict(tmp_path):
    path=tmp_path/'corrupt.parquet'
    path.write_bytes(b'PAR1 truncated invalid source')
    with pytest.raises(prices.PriceBookRevisionConflict,match='source_invalid') as failure:
        prices.get_pricebook(str(path))
    assert failure.value.__cause__ is not None


def test_disappearance_after_initial_stamp_is_a_typed_conflict(tmp_path,monkeypatch):
    path=source(tmp_path/'disappearing.parquet')
    original=prices._price_stamp
    def vanished(value):
        stamp=original(value)
        path.unlink()
        return stamp
    monkeypatch.setattr(prices,'_price_stamp',vanished)
    with pytest.raises(prices.PriceBookRevisionConflict,match='source_unreadable') as failure:
        prices.get_pricebook(str(path))
    assert failure.value.__cause__ is not None
