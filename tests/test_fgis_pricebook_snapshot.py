"""The official price reader caches source bytes, never a replaceable path."""

import hashlib
import os
import copy

import pandas as pd
import pytest

from proxy.services import fgis_price_service as prices
from proxy.services.model_pricebook_evidence_service import read_pricebook_evidence
from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows


CODE = "20.4.01.01-0001"


def _write_book(path, price, *, region="Fixture region"):
    # Fixed-width prices and no compression let the stronger regression preserve
    # both the byte size and mtime while replacing the actual source contents.
    pd.DataFrame([{"code": CODE, "name": "Literal chosen resource", "unit": "m",
                   "price_current": float(price), "region": region,
                   "quarter": "3 квартал 2026"}]).to_parquet(path, index=False, compression=None)


@pytest.fixture(autouse=True)
def _clear_book_cache():
    prices.get_pricebook.cache_clear()
    yield
    prices.get_pricebook.cache_clear()


def test_unchanged_file_reuses_one_official_snapshot_with_its_whole_source_hash(tmp_path):
    path = tmp_path / "chosen.parquet"
    _write_book(path, 100)
    first = prices.get_pricebook(str(path))
    second = prices.get_pricebook(str(path))
    assert first is second
    assert first.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert first.source_name == path.name and first.source_byte_size == path.stat().st_size
    assert prices.get_pricebook.cache_info().hits == 1
    assert first.lookup(CODE)["price_current"] == 100


def test_same_path_size_and_mtime_with_changed_bytes_cannot_serve_old_prices(tmp_path):
    path = tmp_path / "chosen.parquet"
    _write_book(path, 100)
    original_stat = path.stat()
    old = prices.get_pricebook(str(path))
    _write_book(path, 200)
    assert path.stat().st_size == original_stat.st_size
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert path.stat().st_mtime_ns == original_stat.st_mtime_ns
    new = prices.get_pricebook(str(path))
    assert new is not old and new.source_sha256 != old.source_sha256
    assert new.lookup(CODE)["price_current"] == 200
    assert old.lookup(CODE)["price_current"] == 100


def test_typed_evidence_and_real_calculation_use_the_updated_official_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "chosen.parquet"
    _write_book(path, 100)
    prices.get_pricebook(str(path))  # the former path-only cache is now populated
    _write_book(path, 200)
    monkeypatch.setattr(prices, "resolve_pricebook_path", lambda book, **kwargs: str(path))
    evidence = read_pricebook_evidence("read_resource_price", {"code": CODE}, price_basis={
        "pricebook": "chosen", "region": "Fixture region", "quarter": "3 квартал 2026"})
    hit = evidence["result"]["hits"][0]
    row = {"source_row": "S!R2", "row_role": "material", "title": "Literal chosen resource",
           "unit": "m", "quantity": 3, "resource_code": CODE, "evidence_refs": ["Q1.H1"],
           "evidence_bindings": {"Q1.H1": hit["meta"]["global_evidence_id"]}}
    book = prices.get_pricebook(str(path))
    trace = build_lsr_trace_from_visible_rows([row], pricebook=book)
    assert book.source_sha256 == hit["meta"]["pricebook_sha256"]
    resource = next(row for row in trace["sections"][0]["positions"][0]["rows"] if row["type"] == "resource_material")
    assert resource["columns"]["10"] == 200 and resource["columns"]["12"] == 600
    assert trace["summary"]["confirmed_amount"] == 600
    assert trace["summary"]["preliminary_amount"] == 0


def test_source_change_during_official_decode_does_not_cache_a_false_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "chosen.parquet"
    _write_book(path, 100)
    official_reader = prices.PriceBook.from_parquet

    def changing_reader(cls, source):
        old = official_reader(source)
        _write_book(path, 200)
        return old

    with monkeypatch.context() as patch:
        patch.setattr(prices.PriceBook, "from_parquet", classmethod(changing_reader))
        with pytest.raises(prices.PriceBookSourceChanged, match="changed during read"):
            prices.get_pricebook(str(path))
    assert prices.get_pricebook.cache_info().currsize == 0
    assert prices.get_pricebook(str(path)).lookup(CODE)["price_current"] == 200


def test_missing_source_is_not_masked_by_a_previously_loaded_snapshot(tmp_path):
    path = tmp_path / "chosen.parquet"
    _write_book(path, 100)
    prices.get_pricebook(str(path))
    path.unlink()
    with pytest.raises(FileNotFoundError):
        prices.get_pricebook(str(path))


def test_public_cache_clear_remains_available_to_existing_importers(tmp_path):
    path = tmp_path / "chosen.parquet"
    _write_book(path, 100)
    old = prices.get_pricebook(str(path))
    prices.get_pricebook.cache_clear()
    assert prices.get_pricebook.cache_info().currsize == 0
    assert prices.get_pricebook(str(path)) is not old


def test_explicit_basis_keeps_stored_hash_only_for_the_same_literal_book():
    from proxy.services.lsr_workbook_adapter_service import explicit_estimate_pricebook
    basis = {"pricebook": "chosen", "pricebook_sha256": "a" * 64}
    same = explicit_estimate_pricebook(requested_book="chosen", document_basis=basis, pricebooks=["chosen"])
    changed = explicit_estimate_pricebook(requested_book="other", document_basis=basis, pricebooks=["chosen", "other"])
    assert same["pricebook_sha256"] == "a" * 64
    assert "pricebook_sha256" not in changed
    assert basis == {"pricebook": "chosen", "pricebook_sha256": "a" * 64}


@pytest.mark.asyncio
async def test_durable_book_hash_survives_real_workbook_contract_and_blocks_changed_file(tmp_path, monkeypatch):
    import openpyxl

    from proxy.routers import chat
    from proxy.services.chat_attachment_service import preserve_read_attachment
    from proxy.services.chat_evidence_application_service import document_price_basis_arguments
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    source_book = openpyxl.Workbook()
    source_book.active.title = "S"
    source_book.active.append(["Наименование", "Ед. изм.", "Количество"])
    source_book.active.append(["Literal chosen resource", "m", 3])
    source_book.save(source)
    source_book.close()
    attachment = preserve_read_attachment(source, attachment_id="read_123456abcdef",
                                         original_name="source.xlsx", root=attachment_root)
    price_path = tmp_path / "chosen.parquet"
    _write_book(price_path, 100, region="Санкт-Петербург")
    monkeypatch.setattr(prices, "available_pricebooks", lambda *args, **kwargs: [str(price_path)])
    monkeypatch.setattr(prices, "resolve_pricebook_path", lambda book, **kwargs: str(price_path) if book == "chosen" else None)
    evidence = read_pricebook_evidence("read_resource_price", {"code": CODE}, price_basis={"pricebook": "chosen"})
    identity = evidence["result"]["hits"][0]["meta"]["global_evidence_id"]
    decisions = [{"source_row": "S!R2", "row_role": "material", "title": "Literal chosen resource",
                  "unit": "m", "quantity": 3, "resource_code": CODE, "evidence_refs": ["Q1.H1"],
                  "evidence_bindings": {"Q1.H1": identity}}]
    original_decisions = copy.deepcopy(decisions)
    context = {"session_id": "frozen-book", "question": "Собери ЛСР", "dataset_ids": [],
               "attachment_id": attachment["attachment_id"], "profile_revision_id": "fixture",
               "model_identity": "offline-fixture", "model_preset": "fixture"}
    first = await chat._execute_chat_workbook_tool(
        {"call_id": "first", "tool": "build_lsr_workbook", "args": {
            "attachment_id": attachment["attachment_id"], "decisions": decisions, "pricebook": "chosen"}},
        context, None)
    assert first["status"] == "complete" and first["confirmed_amount"] == 300
    original_sha = prices.get_pricebook(str(price_path)).source_sha256
    assert first["price_basis"]["pricebook_sha256"] == original_sha
    jobs = WorkbookResearchJobService(tmp_path / "job-meta.db")
    job = jobs.begin_or_resume(jobs.identity(session_id="frozen-book", attachment_id=attachment["attachment_id"],
        source_sha256="a" * 64, dataset_ids=[], profile_revision_id="fixture", model_identity="offline-fixture",
        question="Собери ЛСР"))
    jobs.record_packaging(job["job_id"], tool="build_lsr_workbook", revision_id=first["artifact"]["revision_id"],
                          draft=False, price_basis=first["price_basis"])
    stored = jobs.get(job["job_id"])["price_basis"]
    assert stored["pricebook_sha256"] == original_sha

    _write_book(price_path, 200, region="Санкт-Петербург")
    assert prices.get_pricebook(str(price_path)).lookup(CODE)["price_current"] == 200
    continued = await chat._execute_chat_workbook_tool(
        {"call_id": "continued", "tool": "build_lsr_workbook", "args": {
            "attachment_id": attachment["attachment_id"], "decisions": decisions,
            "document_price_basis": document_price_basis_arguments(stored), "question": "Продолжи это же задание"}},
        context, None)
    assert continued["status"] == "failed"
    assert continued.get("code") != "TOOL_SCHEMA_INVALID"
    assert "PRICEBOOK_VERSION_CONFLICT" in str(continued.get("blockers"))
    assert "artifact" not in continued
    assert decisions == original_decisions


@pytest.mark.asyncio
async def test_first_price_read_pins_book_before_packaging_and_restart(tmp_path, monkeypatch):
    from proxy.services.model_research_tool_service import ModelResearchToolService
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    path = tmp_path / "chosen.parquet"
    _write_book(path, 100)
    monkeypatch.setattr(prices, "resolve_pricebook_path", lambda book, **kwargs: str(path) if book == "chosen" else None)
    requested = {"pricebook": "chosen", "requested_region": "Fixture region", "requested_quarter": "3:2026"}

    def reader(basis):
        return ModelResearchToolService(retrieve=lambda **_: pytest.fail("no RAG query required"),
            frozen_dataset_ids=(), retrieval_kwargs={}, fallback=lambda *_: pytest.fail("no fallback required"),
            price_basis=basis)

    active = reader(requested)
    call = {"tool": "read_resource_price", "args": {"code": CODE}}
    first = await active.execute(call)
    assert first.payload["status"] == "ok"
    hit = first.payload["result"]["hits"][0]
    assert hit["meta"]["pricebook_sha256"] == prices.get_pricebook(str(path)).source_sha256
    assert '"price_current": 100.0' in hit["content"]
    snapshot = active.price_basis_snapshot
    assert snapshot == {**requested, "pricebook_sha256": hit["meta"]["pricebook_sha256"]}
    external = active.price_basis_snapshot
    external["pricebook_sha256"] = "0" * 64
    assert active.price_basis_snapshot == snapshot

    db = tmp_path / "job-meta.db"
    jobs = WorkbookResearchJobService(db)
    job = jobs.begin_or_resume(jobs.identity(session_id="before-package", attachment_id="read_123456abcdef",
        source_sha256="a" * 64, dataset_ids=[], profile_revision_id="fixture", model_identity="offline-fixture",
        question="Literal task"), task_context={"price_basis": requested})
    jobs.record_evidence_read(job["job_id"], packet_id="packet-1", price_basis=snapshot,
        evidence=[{"global_evidence_id": hit["meta"]["global_evidence_id"], "content": hit["content"], "meta": hit["meta"]}],
        read_receipts=[{"tool": call["tool"], "status": "ok", "args": call["args"]}])
    restarted = WorkbookResearchJobService(db).get(job["job_id"])
    assert restarted["task_context"]["price_basis"] == snapshot
    assert restarted["accepted_rows"] == [] and restarted["document"]["packaged"] is False

    _write_book(path, 200)
    assert prices.get_pricebook(str(path)).lookup(CODE)["price_current"] == 200
    for continuation in (active, reader(restarted["task_context"]["price_basis"])):
        changed = await continuation.execute(call)
        assert changed.payload["status"] == "conflict"
        assert "source hash" in str(changed.payload["missing"])
        assert changed.chunks == () and changed.payload["result"]["hits"] == []
        assert continuation.price_basis_snapshot == snapshot


@pytest.mark.parametrize("replacement", [
    {"pricebook": "chosen", "pricebook_sha256": "not-a-hash"},
    {"pricebook": "chosen", "pricebook_sha256": "b" * 64},
    {"pricebook": "other", "pricebook_sha256": "a" * 64},
])
def test_evidence_read_cannot_replace_a_durable_book_snapshot(tmp_path, replacement):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobError, WorkbookResearchJobService

    jobs = WorkbookResearchJobService(tmp_path / "read-basis.db")
    original = {"pricebook": "chosen", "requested_region": "Fixture region", "pricebook_sha256": "a" * 64}
    job = jobs.begin_or_resume(jobs.identity(session_id="price-proof", attachment_id="read_123456abcdef",
        source_sha256="a" * 64, dataset_ids=[], profile_revision_id="fixture", model_identity="offline-fixture",
        question="Literal task"), task_context={"price_basis": original})
    with pytest.raises(WorkbookResearchJobError, match="evidence price basis"):
        jobs.record_evidence_read(job["job_id"], packet_id="packet-1", evidence=[{"global_evidence_id": "new"}],
                                  read_receipts=[{"tool": "read_resource_price"}], price_basis=replacement)
    preserved = jobs.get(job["job_id"])
    assert preserved["task_context"]["price_basis"] == original
    assert preserved["evidence"] == []
    assert "model_evidence_reads" not in preserved["task_context"]


@pytest.mark.asyncio
async def test_missing_resource_still_pins_the_book_that_was_actually_read(tmp_path, monkeypatch):
    from proxy.services.model_research_tool_service import ModelResearchToolService

    path = tmp_path / "chosen.parquet"
    _write_book(path, 100)
    monkeypatch.setattr(prices, "resolve_pricebook_path", lambda book, **kwargs: str(path))
    reader = ModelResearchToolService(retrieve=lambda **_: pytest.fail("no RAG query required"),
        frozen_dataset_ids=(), retrieval_kwargs={}, fallback=lambda *_: pytest.fail("no fallback required"),
        price_basis={"pricebook": "chosen"})
    missing = await reader.execute({"tool": "read_resource_price", "args": {"code": "unknown-literal-code"}})
    assert missing.payload["status"] == "missing" and missing.chunks == ()
    original_sha = prices.get_pricebook(str(path)).source_sha256
    assert reader.price_basis_snapshot["pricebook_sha256"] == original_sha
    _write_book(path, 200)
    next_read = await reader.execute({"tool": "read_resource_price", "args": {"code": CODE}})
    assert next_read.payload["status"] == "conflict" and next_read.chunks == ()
    assert reader.price_basis_snapshot["pricebook_sha256"] == original_sha


@pytest.mark.parametrize("operator_request,changed", [
    ({"region": "СПб", "quarter": "III квартал 2026"}, False),
    ({"quarter": "IV квартал 2026"}, True),
    ({"region": "Москва"}, True),
])
def test_explicit_operator_dimensions_reset_old_book_only_when_they_change(tmp_path, operator_request, changed):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    jobs = WorkbookResearchJobService(tmp_path / "operator-basis.db")
    original = {"pricebook": "sankt-peterburg_3kv2026", "requested_region": "Санкт-Петербург",
                "requested_quarter": "3:2026", "pricebook_sha256": "a" * 64}

    def identity(question):
        return jobs.identity(session_id="operator-proof", attachment_id="read_123456abcdef",
            source_sha256="a" * 64, dataset_ids=[], profile_revision_id="fixture", model_identity="offline-fixture",
            question=question)

    jobs.begin_or_resume(identity("Original task"), task_context={"price_basis": original})
    resumed = jobs.begin_or_resume(identity("Operator continuation"), task_context={"price_basis": operator_request})
    basis = resumed["task_context"]["price_basis"]
    if changed:
        assert "pricebook_sha256" not in basis and "pricebook" not in basis
        if "quarter" in operator_request:
            assert basis["quarter"] == "4 квартал 2026" and "requested_quarter" not in basis
        if "region" in operator_request:
            assert basis["region"] == "Москва" and "requested_region" not in basis
        fresh = {**basis, "pricebook": "operator-selected-new-book", "pricebook_sha256": "b" * 64}
        jobs.record_evidence_read(resumed["job_id"], packet_id="p", evidence=[], read_receipts=[], price_basis=fresh)
        assert jobs.get(resumed["job_id"])["task_context"]["price_basis"] == fresh
    else:
        assert basis["pricebook_sha256"] == "a" * 64 and basis["pricebook"] == original["pricebook"]
        assert basis["region"] == "Санкт-Петербург" and basis["quarter"] == "3 квартал 2026"
