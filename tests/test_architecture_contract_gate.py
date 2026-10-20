from pathlib import Path

from tools.architecture_contract_gate import scan_architecture


def _write(root: Path, relative_path: str, text: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _codes(root: Path) -> set[str]:
    return {item.code for item in scan_architecture(root)}


def test_rejects_active_code_query_producers_even_under_disabled_branch(tmp_path: Path) -> None:
    _write(tmp_path, "proxy/services/chat_evidence_application_service.py", '''
from proxy.services.lsr_candidate_query_service import candidate_queries_for_packet as build
async def _execute_chat_evidence_application():
    if False:
        await _execute_system_candidate_queries()
        build()
        legacy.merge_candidate_queries()
''')
    assert "ACTIVE_CODE_AUTHORED_QUERY" in _codes(tmp_path)


def test_allows_historical_query_helper_without_active_chat_caller(tmp_path: Path) -> None:
    _write(tmp_path, "proxy/services/chat_evidence_application_service.py", '''
async def _execute_system_candidate_queries():
    return candidate_queries_for_packet()
async def _execute_chat_evidence_application():
    return model_queries
''')
    assert "ACTIVE_CODE_AUTHORED_QUERY" not in _codes(tmp_path)


def test_rejects_parallel_estimate_workbook_name(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/bad.py",
        'NAME = "estimate_build_lsr_workbook"\n',
    )

    assert _codes(tmp_path) == {"PARALLEL_WORKBOOK_TOOL"}


def test_rejects_forced_workbook_regex(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/bad.py",
        """import re

def route(question: str) -> None:
    if re.search("лср", question):
        call("build_lsr_workbook")
""",
    )

    assert "FORCED_WORKBOOK_CALL" in _codes(tmp_path)


def test_rejects_forced_workbook_language_membership(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/bad.py",
        """def route(question: str) -> None:
    if "лср" in question.lower():
        call("build_lsr_workbook")
""",
    )

    assert "FORCED_WORKBOOK_CALL" in _codes(tmp_path)


def test_rejects_regex_inside_model_result_decoder(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """import re

def parse_model_rag_result(answer: str):
    return re.search('norm', answer)
""",
    )

    assert "MODEL_RESULT_REGEX" in _codes(tmp_path)


def test_allows_schema_membership_assertion_near_workbook_lookup(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_projection.py",
        """def test_projection(registry, projected):
    registry.require("build_vor_workbook")
    assert "handler" not in projected
""",
    )

    assert "FORCED_WORKBOOK_CALL" not in _codes(tmp_path)


def test_rejects_implicit_profile_activation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/startup.py",
        "activate_profile_revision('estimator', revision)\n",
    )

    assert "IMPLICIT_PROFILE_ACTIVATION" in _codes(tmp_path)


def test_allows_explicit_profile_activation_boundary(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/routers/profiles.py",
        "activate_profile_revision('estimator', revision)\n",
    )

    assert "IMPLICIT_PROFILE_ACTIVATION" not in _codes(tmp_path)


def test_rejects_unregistered_direct_model_http_call(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/new_model_path.py",
        """import httpx

def generate(base_url: str, payload: dict):
    return httpx.post(f"{base_url}/v1/chat/completions", json=payload)
""",
    )

    assert "INFERENCE_GOVERNOR_BYPASS" in _codes(tmp_path)


def test_allows_non_inference_chat_data_subroute(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_patch_rows_behavior.py",
        """from fastapi.testclient import TestClient


def test_patch_rows(client: TestClient):
    return client.post("/api/chat/patch-lsr-rows", json={"session_id": "s"})
""",
    )

    assert "INFERENCE_GOVERNOR_BYPASS" not in _codes(tmp_path)


def test_rejects_direct_chat_generation_route(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/sneaky_chat.py",
        """import httpx


def answer(payload: dict):
    return httpx.post("http://127.0.0.1:8050/api/chat", json=payload)
""",
    )

    assert "INFERENCE_GOVERNOR_BYPASS" in _codes(tmp_path)


def test_inference_baseline_is_exact_path_and_function(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/ocr_parser.py",
        """import httpx

def ocr_page(base_url: str, payload: dict):
    return httpx.post(f"{base_url}/v1/chat/completions", json=payload)

def new_ocr_route(base_url: str, payload: dict):
    return httpx.post(f"{base_url}/v1/chat/completions", json=payload)
""",
    )

    findings = scan_architecture(tmp_path)
    bypasses = [item for item in findings if item.code == "INFERENCE_GOVERNOR_BYPASS"]
    assert [(item.path, item.detail) for item in bypasses] == [
        ("backend/ocr_parser.py", "direct model HTTP call in new_ocr_route()"),
    ]


def test_rejects_fixture_claimed_as_live_acceptance(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "reports/result.md",
        "Synthetic fixture — live model quality accepted.\n",
    )

    assert "FAKE_LIVE_ACCEPTANCE" in _codes(tmp_path)


def test_never_reads_private_archive(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "local_private_archive/secret.py",
        'NAME = "estimate_build_lsr_workbook"\n',
    )

    assert scan_architecture(tmp_path) == []


def test_gate_self_test_fixtures_are_not_product_findings(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_architecture_contract_gate.py",
        'MUTATION = "estimate_build_lsr_workbook"\n',
    )
    _write(
        tmp_path,
        "tools/architecture_contract_gate.py",
        'PATTERN = r"estimate_.*workbook"\n',
    )

    assert scan_architecture(tmp_path) == []


def test_rejects_engine_name_routing_in_provider_neutral_chat_boundary(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/canonical_route_service.py",
        """def complete(connection):
    if connection.display_name == "Ollama":
        return native_call(connection)
    return common_call(connection)
""",
    )

    assert "ENGINE_NAME_ROUTING" in _codes(tmp_path)


def test_allows_provider_names_only_inside_legacy_importer(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/model_connection_resolver_service.py",
        """class LegacyConnectionImporter:
    def import_effective(self, provider):
        if provider == "Ollama":
            return "legacy:ollama"
""",
    )

    assert "ENGINE_NAME_ROUTING" not in _codes(tmp_path)


def _adr16_probe(tmp_path: Path, relative: str, body: str) -> set[str]:
    _write(tmp_path, relative, "import re\n\n" + body)
    return _codes(tmp_path)


def test_rejects_derived_query_composition_with_regex(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def _candidates(catalog, packet):
    rows = [r for r in catalog if re.search("монтаж", r.line)]
    return candidate_queries_for_packet(rows)
""",
    )
    assert "DERIVED_QUERY_SEMANTIC_INVENTION" in codes


def test_rejects_semantic_invention_inside_the_candidate_module(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_candidate_query_service.py",
        """
def candidate_queries_for_rows(rows):
    return [re.sub(r"вручную", "механизированный", row.line) for row in rows]
""",
    )
    assert "DERIVED_QUERY_SEMANTIC_INVENTION" in codes


def test_rejects_derived_provenance_authored_elsewhere(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/estimate_harness_service.py",
        """
def build(rows):
    return [
        CandidateQuery(text=row.line, locator=row.locator, provenance="derived")
        for row in rows
    ]
""",
    )
    assert "DERIVED_QUERY_SEMANTIC_INVENTION" in codes


def test_rejects_evidence_builder_without_query_provenance(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def assemble(queries, hits, budget):
    return build_model_rag_evidence_groups(queries, hits, budget)
""",
    )
    assert "QUERY_PROVENANCE_MISSING" in codes


def test_rejects_estimate_pricebook_without_explicit_only(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_workbook_adapter_service.py",
        """
async def build(args):
    return resolve_pricebook_path(args.get("pricebook") or None)
""",
    )
    assert "PRICE_BASIS_SILENT_DEFAULT" in codes


def test_rejects_unowned_norm_card_price_without_its_label(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/rim_lsr_trace_service.py",
        """
def _resolve(res):
    return PriceTrace(price=res["price"], source="card_price", basis="norm_card_price")
""",
    )
    assert "UNOWNED_PRICE_SOURCE" in codes


def test_allows_adr16_literal_composition_and_explicit_basis(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_candidate_query_service.py",
        """
def candidate_queries_for_rows(rows):
    return [" | ".join(row.values) for row in rows]
""",
    )
    _write(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def assemble(queries, hits, budget, provenance):
    return build_model_rag_evidence_groups(
        queries, hits, budget, query_provenance=provenance
    )
""",
    )
    _write(
        tmp_path,
        "proxy/services/lsr_workbook_adapter_service.py",
        """
async def build(args):
    return resolve_pricebook_path(
        args.get("pricebook") or None, explicit_only=True
    )
""",
    )
    _write(
        tmp_path,
        "proxy/services/rim_lsr_trace_service.py",
        """
def _resolve(res):
    return PriceTrace(
        price=res["price"],
        source="card_price",
        basis="norm_card_price",
        action="card_price_without_basis",
    )
""",
    )
    assert _codes(tmp_path).isdisjoint(
        {
            "DERIVED_QUERY_SEMANTIC_INVENTION",
            "QUERY_PROVENANCE_MISSING",
            "PRICE_BASIS_SILENT_DEFAULT",
            "UNOWNED_PRICE_SOURCE",
        }
    )


def test_rejects_artifact_revision_built_from_model_supplied_parent(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/workbook_tool_service.py",
        """
async def _build(args, ctx):
    normalized = dict(args)
    return ArtifactRevisionRequest(
        artifact_kind="lsr_workbook",
        file_path=normalized["file_path"],
        parent_revision_id=normalized["parent_revision_id"],
    )
""",
    )
    assert "DOCUMENT_LINEAGE_UNOWNED" in codes


def test_allows_code_resolved_document_lineage(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/workbook_tool_service.py",
        """
def _packaging_parent(ctx, *, tool_name, attachment_id, explicit):
    return (
        ctx.checkpoints.last_completed_revision(
            session_id=ctx.session_id,
            attachment_id=attachment_id,
            tool_name=tool_name,
        ),
        "session_lineage",
    )


async def _build(args, ctx):
    normalized = dict(args)
    parent, _source = _packaging_parent(
        ctx,
        tool_name="build_lsr_workbook",
        attachment_id=normalized["attachment_id"],
        explicit=normalized["parent_revision_id"],
    )
    return ArtifactRevisionRequest(
        artifact_kind="lsr_workbook",
        file_path=normalized["file_path"],
        parent_revision_id=parent,
    )
""",
    )
    assert "DOCUMENT_LINEAGE_UNOWNED" not in codes


def test_rejects_a_carrier_that_drops_the_operator_questions(tmp_path: Path) -> None:
    """The 816 defect: identifiers survived, the basis and its questions did not."""

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def safe_workbook_history_projection(payload):
    safe = {"schema": payload["schema"], "status": payload["status"]}
    safe["missing"] = list(payload.get("missing") or [])
    return safe
""",
    )
    assert "BASIS_QUESTIONS_NOT_CARRIED" in codes


def test_accepts_a_carrier_that_keeps_basis_gaps_and_conflicts(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def safe_workbook_history_projection(payload):
    safe = {"schema": payload["schema"], "status": payload["status"]}
    safe["price_basis"] = dict(payload.get("price_basis") or {})
    for field in ("price_gaps", "norm_conflicts"):
        safe[field] = list(payload.get(field) or [])
    return safe
""",
    )
    assert "BASIS_QUESTIONS_NOT_CARRIED" not in codes


def test_rejects_a_packaging_call_that_loses_the_documents_basis(tmp_path: Path) -> None:
    """The 820 defect: the continuation re-derived the basis from its own text."""

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def _package(service, job_id, tool, decisions):
    events = service.list_events(job_id)
    basis = workbook_document_price_basis(events, tool=tool)
    return workbook_packaging_args(
        packaging_tool=tool,
        attachment_id="att",
        question="Продолжи это же задание",
        decisions=decisions,
        operator_overrides={},
    )
""",
    )
    assert "DOCUMENT_BASIS_NOT_CARRIED" in codes


def test_accepts_a_packaging_call_that_reuses_the_documents_basis(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def _package(service, job_id, tool, decisions):
    events = service.list_events(job_id)
    basis = workbook_document_price_basis(events, tool=tool)
    return workbook_packaging_args(
        packaging_tool=tool,
        attachment_id="att",
        question="Продолжи это же задание",
        decisions=decisions,
        operator_overrides={},
        document_price_basis=basis,
    )
""",
    )
    assert "DOCUMENT_BASIS_NOT_CARRIED" not in codes


def test_rejects_a_packaging_route_that_delivers_a_file_without_recording_it(
    tmp_path: Path,
) -> None:
    """The model may call the packager — the document still has to keep its history."""

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def workbook_packaging_args(**kwargs):
    return kwargs


def workbook_document_price_basis(events, *, tool=""):
    return {}


async def _route(workbook_tool_executor, tool, decisions):
    basis = workbook_document_price_basis([], tool=tool)
    args = workbook_packaging_args(
        packaging_tool=tool,
        attachment_id="att",
        question="Добери нормы",
        decisions=decisions,
        operator_overrides={},
        document_price_basis=basis,
    )
    payload = await workbook_tool_executor({"tool": tool, "args": args}, {}, None)
    return payload
""",
    )
    assert "PACKAGING_ROUTE_NOT_DURABLE" in codes


def test_accepts_a_packaging_route_that_records_what_it_delivered(
    tmp_path: Path,
) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def workbook_packaging_args(**kwargs):
    return kwargs


def workbook_document_price_basis(events, *, tool=""):
    return {}


def document_price_basis_arguments(basis):
    return dict(basis or {})


def model_packaging_document_basis(job):
    return document_price_basis_arguments((job or {}).get("document", {}))


def model_packaging_record_arguments(**kwargs):
    return kwargs


async def _route(workbook_tool_executor, service, job, tool, decisions):
    basis = workbook_document_price_basis([], tool=tool)
    args = workbook_packaging_args(
        packaging_tool=tool,
        attachment_id="att",
        question="Добери нормы",
        decisions=decisions,
        operator_overrides={},
        document_price_basis=basis,
    )
    payload = await workbook_tool_executor({"tool": tool, "args": args}, {}, None)
    event = model_packaging_record_arguments(
        job=job, tool=tool, harvested=payload.get("harvested") or {}
    )
    job_id = event.pop("job_id")
    service.record_packaging(job_id, **event)
    # and the code-owned pass over the same document records its own event
    service.record_packaging(args["attachment_id"], tool=tool)
    return payload
""",
    )
    assert "PACKAGING_ROUTE_NOT_DURABLE" not in codes


def test_rejects_a_model_route_that_parses_a_basis_on_its_own(
    tmp_path: Path,
) -> None:
    """Two parsers of one contract drift: the card and the file would disagree."""

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def workbook_packaging_args(**kwargs):
    return kwargs


def workbook_document_price_basis(events, *, tool=""):
    return {}


def model_packaging_document_basis(job):
    return {"pricebook": (job or {}).get("document", {}).get("book", "")}


def model_packaging_record_arguments(**kwargs):
    return kwargs


async def _route(workbook_tool_executor, service, job, tool, decisions):
    args = workbook_packaging_args(
        packaging_tool=tool,
        attachment_id="att",
        question="Добери нормы",
        decisions=decisions,
        operator_overrides={},
        document_price_basis=workbook_document_price_basis([], tool=tool),
    )
    payload = await workbook_tool_executor({"tool": tool, "args": args}, {}, None)
    service.record_packaging("job", tool=tool)
    service.record_packaging("job2", tool=tool)
    return payload
""",
    )
    assert "PACKAGING_ROUTE_NOT_DURABLE" in codes


def test_rejects_a_job_that_never_stores_the_basis_it_packaged(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/workbook_research_job_service.py",
        """
class Service:
    def record_packaging(self, job_id, *, tool, revision_id, draft):
        return self._append_event(
            "workbook_packaged",
            {"tool": tool, "revision_id": revision_id, "draft": draft},
        )
""",
    )
    assert "DOCUMENT_BASIS_NOT_CARRIED" in codes


def test_accepts_a_job_that_stores_the_basis_with_its_revision(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/workbook_research_job_service.py",
        """
class Service:
    def record_packaging(self, job_id, *, tool, revision_id, draft, price_basis=None):
        basis = _packaged_price_basis(price_basis)
        return self._append_event(
            "workbook_packaged",
            {"tool": tool, "revision_id": revision_id, "draft": draft,
             "price_basis": basis},
        )
""",
    )
    assert "DOCUMENT_BASIS_NOT_CARRIED" not in codes


def test_rejects_a_repack_route_that_rebuilds_the_priced_file_blind(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/routers/chat.py",
        """
async def repack_lsr(req):
    args = {
        "attachment_id": req.attachment_id,
        "decisions": req.decisions,
        "parent_revision_id": parent,
    }
    return await execute("build_lsr_workbook", args)
""",
    )
    assert "DOCUMENT_BASIS_NOT_CARRIED" in codes


def test_accepts_a_repack_route_that_carries_the_basis_without_a_model(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/routers/chat.py",
        """
async def repack_lsr(req, job):
    args = {"attachment_id": req.attachment_id, "decisions": req.decisions}
    basis = document_price_basis_arguments(job["document"]["price_basis"])
    if basis:
        args["document_price_basis"] = basis
    return await execute("build_lsr_workbook", args)
""",
    )
    assert "DOCUMENT_BASIS_NOT_CARRIED" not in codes


def test_rejects_an_accrual_label_the_adapter_has_never_heard_of(tmp_path: Path) -> None:
    """A new ownership label the gap builder does not know closes the position."""

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/rim_lsr_trace_service.py",
        """
def build_position_trace(position):
    nr_sp_ownership = {"label": "", "nr_source": "explicit"}
    if nr_source == "norm_card":
        nr_sp_ownership["label"] = "nr_sp_taken_for_granted"
    return nr_sp_ownership
""",
    )
    assert "ACCRUAL_LABEL_NOT_ASKED" in codes


def test_accepts_the_two_owned_accrual_labels(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/rim_lsr_trace_service.py",
        """
def build_position_trace(position):
    nr_sp_ownership = {"label": "", "nr_source": "explicit"}
    if nr_source == "norm_card":
        nr_sp_ownership["label"] = "nr_sp_without_basis"
    if nr_pct is None:
        nr_sp_ownership["label"] = "nr_sp_unresolved"
    return nr_sp_ownership
""",
    )
    assert "ACCRUAL_LABEL_NOT_ASKED" not in codes


def test_rejects_a_price_gap_collection_that_drops_the_accrual_question(
    tmp_path: Path,
) -> None:
    """The adapter may name the label and still forget to ask about it."""

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_workbook_adapter_service.py",
        """
_PRICE_SOURCE_LABEL = {
    "nr_sp_without_basis": "нормативное основание или явный выбор ставки",
    "nr_sp_unresolved": "нормативное основание или явный выбор ставки",
}


def _nr_sp_gap(position):
    return {"resource": "НР и СП"}


def collect_lsr_price_gaps(trace):
    return [
        {"resource": str(row.get("code"))}
        for row in trace.get("rows") or []
    ]
""",
    )
    assert "ACCRUAL_LABEL_NOT_ASKED" in codes


def test_accepts_a_price_gap_collection_that_asks_about_the_accrual_rate(
    tmp_path: Path,
) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_workbook_adapter_service.py",
        """
_PRICE_SOURCE_LABEL = {
    "nr_sp_without_basis": "нормативное основание или явный выбор ставки",
    "nr_sp_unresolved": "нормативное основание или явный выбор ставки",
}


def _nr_sp_gap(position):
    return {"resource": "НР и СП"}


def collect_lsr_price_gaps(trace):
    gaps = [{"resource": str(row.get("code"))} for row in trace.get("rows") or []]
    for position in trace.get("positions") or []:
        accrual_gap = _nr_sp_gap(position)
        if accrual_gap is not None:
            gaps.append(accrual_gap)
    return gaps
""",
    )
    assert "ACCRUAL_LABEL_NOT_ASKED" not in codes


def test_rejects_a_price_book_row_read_without_the_unit_rule(tmp_path: Path) -> None:
    """A book row is a price per the unit it states; a шифр match alone is not one.

    Both LSR calculators may take the row only through the shared rule, so a
    lookup that lost the check cannot hand out money the unit does not support.
    """

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/rim_lsr_trace_service.py",
        """
def _resolve_price_trace(res, pricebook=None):
    rec = pricebook.lookup(res["code"])
    if rec is not None:
        return PriceTrace(price=rec["price_current"], source="fgis_current")
    return PriceTrace(price=None, source="needs_kac")
""",
    )
    assert "BOOK_PRICE_UNIT_UNCHECKED" in codes


def test_accepts_a_price_book_row_that_passed_the_unit_rule(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/rim_lsr_trace_service.py",
        """
def _resolve_price_trace(res, pricebook=None):
    rec = pricebook.lookup(res["code"])
    if rec is not None and not book_price_unit_conflict(
        rec.get("unit"), res.get("unit")
    ):
        return PriceTrace(price=rec["price_current"], source="fgis_current")
    return PriceTrace(
        price=None, source=BOOK_UNIT_CONFLICT_ACTION, action=BOOK_UNIT_CONFLICT_ACTION
    )
""",
    )
    assert "BOOK_PRICE_UNIT_UNCHECKED" not in codes


def test_rejects_an_operator_channel_that_never_heard_of_the_book_unit_hole(
    tmp_path: Path,
) -> None:
    """A hole named only inside the trace is a hole nobody answers."""

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_result_readiness_service.py",
        """
_PRICE_SOURCE_LABEL = {"needs_kac": "КАЦ или выбранная ценовая книга"}
""",
    )
    assert "BOOK_PRICE_UNIT_UNCHECKED" in codes


def test_accepts_the_operator_channel_that_names_the_book_unit_hole(
    tmp_path: Path,
) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_result_readiness_service.py",
        """
from proxy.services.rim_lsr_trace_service import BOOK_UNIT_CONFLICT_ACTION

_PRICE_SOURCE_LABEL = {
    "needs_kac": "КАЦ или выбранная ценовая книга",
    BOOK_UNIT_CONFLICT_ACTION: "цена за единицу ресурса в позиции",
}
""",
    )
    assert "BOOK_PRICE_UNIT_UNCHECKED" not in codes


def test_rejects_a_basis_read_scoped_to_one_research(tmp_path: Path) -> None:
    """The 822 live defect: recorded correctly, inherited only inside one research."""

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def _package(service, job_id, attachment_id, tool, decisions):
    events = service.list_events(job_id)
    basis = workbook_document_price_basis(events, tool=tool)
    return workbook_packaging_args(
        packaging_tool=tool,
        attachment_id=attachment_id,
        question="Продолжи это же задание",
        decisions=decisions,
        operator_overrides={},
        document_price_basis=basis,
    )
""",
    )
    assert "DOCUMENT_BASIS_READ_AT_JOB_SCOPE" in codes


def test_accepts_a_basis_read_over_the_documents_researches(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def _package(service, job_id, attachment_id, tool, decisions):
    events = service.list_events(job_id)
    document_events = service.document_packaging_events(attachment_id=attachment_id)
    basis = workbook_document_price_basis(document_events, tool=tool)
    return workbook_packaging_args(
        packaging_tool=tool,
        attachment_id=attachment_id,
        question="Продолжи это же задание",
        decisions=decisions,
        operator_overrides={},
        document_price_basis=basis,
    )
""",
    )
    assert "DOCUMENT_BASIS_READ_AT_JOB_SCOPE" not in codes


def test_rejects_a_model_route_that_only_reads_the_job_it_was_given(
    tmp_path: Path,
) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def model_packaging_document_basis(job):
    document = job.get("document") or {}
    return document_price_basis_arguments(document.get("price_basis"))


def _package(job, tool, decisions):
    basis = model_packaging_document_basis(job)
    return workbook_packaging_args(
        packaging_tool=tool,
        attachment_id="read_1",
        question="Продолжи это же задание",
        decisions=decisions,
        operator_overrides={},
        document_price_basis=basis,
    )
""",
    )
    assert "DOCUMENT_BASIS_READ_AT_JOB_SCOPE" in codes


def test_accepts_a_model_route_that_falls_back_to_the_document(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/chat_evidence_application_service.py",
        """
def model_packaging_document_basis(job):
    document = job.get("document") or {}
    record = document_price_basis_arguments(document.get("price_basis"))
    if record:
        return record
    return document_priced_basis(attachment_id="read_1")


def _package(job, tool, decisions):
    basis = model_packaging_document_basis(job)
    return workbook_packaging_args(
        packaging_tool=tool,
        attachment_id="read_1",
        question="Продолжи это же задание",
        decisions=decisions,
        operator_overrides={},
        document_price_basis=basis,
    )
""",
    )
    assert "DOCUMENT_BASIS_READ_AT_JOB_SCOPE" not in codes


def test_rejects_a_document_event_read_that_still_keys_on_the_job(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/workbook_research_job_service.py",
        """
def record_packaging(job_id, *, tool, revision_id, draft, price_basis=None):
    return _append(job_id, {"price_basis": price_basis})


def document_packaging_events(job_id):
    return list_events(job_id)
""",
    )
    assert "DOCUMENT_BASIS_READ_AT_JOB_SCOPE" in codes


def test_accepts_a_document_event_read_over_the_researches_of_one_attachment(
    tmp_path: Path,
) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/workbook_research_job_service.py",
        """
def record_packaging(job_id, *, tool, revision_id, draft, price_basis=None):
    return _append(job_id, {"price_basis": price_basis})


def document_packaging_events(*, attachment_id, source_sha256=""):
    rows = execute(
        "SELECT rowid, job_id, identity_json FROM workbook_research_jobs"
        " ORDER BY updated_at DESC"
    )
    return [
        event
        for row in rows
        if row.identity.get("attachment_id") == attachment_id
        for event in events_of(row.job_id)
    ]
""",
    )
    assert "DOCUMENT_BASIS_READ_AT_JOB_SCOPE" not in codes


def test_rejects_a_notice_that_names_only_a_broken_basis(tmp_path: Path) -> None:
    """§ 7: an applied basis is a result the operator has to be able to read."""

    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_result_readiness_service.py",
        """
def format_lsr_readiness_notice(readiness, *, filename=""):
    basis_note = "Ценовая база совпадает с запросом: 3 квартал 2026 г."
    basis_match = "exact"
    basis_visible = bool(basis_note) and basis_match in {
        "mismatch",
        "unspecified",
        "no_book",
    }
    if not basis_visible:
        return "ЛСР собрана."
    return _lsr_basis_suffix(basis_match, basis_note)
""",
    )
    assert "APPLIED_BASIS_NOT_NAMED" in codes


def test_rejects_a_notice_that_drops_the_price_book_identifier(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_result_readiness_service.py",
        """
def format_lsr_readiness_notice(readiness, *, filename=""):
    basis_note = "Ценовая база совпадает с запросом"
    basis_match = "exact"
    basis_visible = bool(basis_note)
    return _lsr_basis_suffix(basis_match, basis_note) if basis_visible else ""
""",
    )
    assert "APPLIED_BASIS_NOT_NAMED" in codes


def test_accepts_a_notice_that_names_the_applied_basis_and_its_book(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        "proxy/services/lsr_result_readiness_service.py",
        """
def format_lsr_readiness_notice(readiness, *, filename=""):
    basis_note = "Ценовая база совпадает с запросом: 3 квартал 2026 г."
    basis_match = "exact"
    basis_book = "sankt-peterburg_3kv2026"
    basis_visible = bool(basis_note or basis_book)
    if not basis_visible:
        return "ЛСР собрана."
    return _lsr_basis_suffix(basis_match, basis_note, basis_book)
""",
    )
    assert "APPLIED_BASIS_NOT_NAMED" not in codes


#: every link of the seam that answers «why is no book applied», wired together
BASIS_REFUSAL_MODULE = "proxy/services/lsr_workbook_adapter_service.py"

BASIS_REFUSAL_DERIVER = '''
def explicit_estimate_pricebook(**kwargs):
    result = {
        "pricebook": "",
        "contradicting_regions": [],
        "contradicting_quarters": [],
        "refusal": "",
        "matching_books": [],
    }
    if len(regions) > 1:
        result["contradicting_regions"] = sorted(regions)
        result["refusal"] = "contradiction"
        return result
    if len(quarters) > 1:
        result["contradicting_quarters"] = sorted(quarters)
        result["refusal"] = "contradiction"
        return result
    if not quarters:
        result["refusal"] = "unnamed_period"
        result["matching_books"] = [stem for stem in stems if region_of(stem) == region]
        return result
    matches = [stem for stem in stems if agrees(stem, region, quarter)]
    if not matches:
        result["refusal"] = "no_matching_book"
        return result
    if len(matches) > 1:
        result["refusal"] = "ambiguous_catalog"
        result["matching_books"] = matches
        return result
    result["pricebook"] = matches[0]
    return result
'''

BASIS_REFUSAL_ANSWER = '''
def summarize_lsr_price_basis(
    *, pricebook=None, basis_contradictions=(), basis_refusal="", basis_candidates=()
):
    contradictions = list(basis_contradictions or ())
    candidates = [str(item) for item in (basis_candidates or ())]
    refusal = str(basis_refusal or "")
    if pricebook is None:
        if contradictions:
            return {"note": "Явные источники называют разную ценовую базу"}
        if refusal == "unnamed_period":
            return {"note": "Субъект назван, периода нет. Подходят книги: " + ", ".join(candidates)}
        if refusal == "no_matching_book":
            return {"note": "Запрошенная ценовая база локально не найдена"}
        return {"note": "Ценовая база не задана явно"}
    return {"note": "Ценовая база совпадает с запросом"}


def build(args):
    choice = explicit_estimate_pricebook(**args)
    return summarize_lsr_price_basis(
        pricebook=None,
        basis_contradictions=(
            ["регион: " + ", ".join(choice["contradicting_regions"])]
            if choice["contradicting_regions"]
            else []
        ),
        basis_refusal=choice["refusal"],
        basis_candidates=choice["matching_books"],
    )
'''

#: what the answer looks like when it stops asking which refusal it received
BASIS_REFUSAL_GUARDS = '''        if contradictions:
            return {"note": "Явные источники называют разную ценовую базу"}
        if refusal == "unnamed_period":
            return {"note": "Субъект назван, периода нет. Подходят книги: " + ", ".join(candidates)}
        if refusal == "no_matching_book":
'''


def test_rejects_a_refusal_the_derivation_keeps_to_itself(tmp_path: Path) -> None:
    """§ 7: the module that refuses has to say what it refused between."""

    codes = _adr16_probe(
        tmp_path,
        BASIS_REFUSAL_MODULE,
        '''
def explicit_estimate_pricebook(**kwargs):
    result = {"pricebook": "", "origin": ""}
    if len(regions) > 1:
        result["reason"] = "регион назван по-разному"
        return result
    return result
'''
        + BASIS_REFUSAL_ANSWER,
    )
    assert "CONTRADICTED_BASIS_ANNOUNCED_ABSENT" in codes


def test_rejects_a_refused_choice_reported_as_an_absent_book(tmp_path: Path) -> None:
    """The live 823 defect itself: «локально не найдена» over an installed book."""

    assert BASIS_REFUSAL_GUARDS in BASIS_REFUSAL_ANSWER
    codes = _adr16_probe(
        tmp_path,
        BASIS_REFUSAL_MODULE,
        BASIS_REFUSAL_DERIVER
        + BASIS_REFUSAL_ANSWER.replace(BASIS_REFUSAL_GUARDS, "        if False:\n"),
    )
    assert "CONTRADICTED_BASIS_ANNOUNCED_ABSENT" in codes


def test_rejects_a_call_site_that_forgets_what_was_refused(tmp_path: Path) -> None:
    """Correct derivation and correct summary are still free to be unwired."""

    codes = _adr16_probe(
        tmp_path,
        BASIS_REFUSAL_MODULE,
        BASIS_REFUSAL_DERIVER
        + BASIS_REFUSAL_ANSWER.replace(
            '''        basis_refusal=choice["refusal"],
        basis_candidates=choice["matching_books"],
''',
            "",
        ),
    )
    assert "CONTRADICTED_BASIS_ANNOUNCED_ABSENT" in codes


def test_accepts_a_refusal_carried_from_the_derivation_to_the_answer(
    tmp_path: Path,
) -> None:
    codes = _adr16_probe(
        tmp_path,
        BASIS_REFUSAL_MODULE,
        BASIS_REFUSAL_DERIVER + BASIS_REFUSAL_ANSWER,
    )
    assert "CONTRADICTED_BASIS_ANNOUNCED_ABSENT" not in codes




# ── blocker § 1 (29.09): a continuation continues its document's offer ledger ──

CONTINUATION_CARRIER = "proxy/services/chat_evidence_application_service.py"
CONTINUATION_STORE = "proxy/services/workbook_research_job_service.py"

#: the reader the loop needs; every store-module fixture has to answer for it,
#: because without it every ledger of a continuation is job-scoped by definition.
LINEAGE_READER_OK = """
    def list_events_with_lineage(self, job_id, event_type=""):
        events = []
        for step in self.lineage_job_ids(job_id):
            events.extend(self.list_events(step, event_type))
        return events

    def lineage_job_ids(self, job_id):
        row = self._read(f"SELECT continues_job_id FROM jobs WHERE job_id=?", job_id)
        return [job_id, str(row["continues_job_id"])]
"""


def _loop_that_reads_its_ledger(reader: str) -> str:
    return f"""
def _sheet_pass(research_job_service, research_job):
    checkpoint_events = research_job_service.{reader}(
        str(research_job["job_id"]), "packet_checkpoint"
    )
    return (
        packet_attempt_seed(checkpoint_events),
        packet_offer_counts(checkpoint_events),
    )
"""


def test_rejects_an_offer_ledger_counted_from_one_research_job(tmp_path: Path) -> None:
    """The live 824 failure: the continuation restarts the document at zero offers."""

    codes = _adr16_probe(tmp_path, CONTINUATION_CARRIER, _loop_that_reads_its_ledger("list_events"))
    assert "OFFER_LEDGER_READ_AT_JOB_SCOPE" in codes


def test_accepts_an_offer_ledger_counted_across_the_documents_lineage(
    tmp_path: Path,
) -> None:
    codes = _adr16_probe(
        tmp_path, CONTINUATION_CARRIER, _loop_that_reads_its_ledger("list_events_with_lineage")
    )
    assert "OFFER_LEDGER_READ_AT_JOB_SCOPE" not in codes


def test_rejects_a_ledger_helper_fed_from_memory(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        CONTINUATION_CARRIER,
        """
def _sheet_pass(seen_locators):
    return packet_offer_counts(seen_locators), packet_attempt_seed(seen_locators)
""",
    )
    assert "OFFER_LEDGER_READ_AT_JOB_SCOPE" in codes


def test_rejects_a_lineage_reader_that_reads_one_job(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        CONTINUATION_STORE,
        """
class WorkbookResearchJobService:
    def list_events_with_lineage(self, job_id, event_type=""):
        return self.list_events(job_id, event_type)
""",
    )
    assert "OFFER_LEDGER_READ_AT_JOB_SCOPE" in codes


def test_accepts_a_lineage_reader_that_walks_the_chain(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        CONTINUATION_STORE,
        "class WorkbookResearchJobService:\n" + LINEAGE_READER_OK,
    )
    assert "OFFER_LEDGER_READ_AT_JOB_SCOPE" not in codes


def test_rejects_a_research_started_without_inheriting_the_document(tmp_path: Path) -> None:
    codes = _adr16_probe(
        tmp_path,
        CONTINUATION_STORE,
        """
class WorkbookResearchJobService:
"""
        + LINEAGE_READER_OK
        + """
    def begin_or_resume(self, identity):
        return self._insert(identity)

    def _inherit_document_progress(self, conn, *, job_id, identity):
        conn.execute("UPDATE jobs SET accepted_rows_json=? WHERE job_id=?", (job_id,))
        return {}
""",
    )
    assert "OFFER_LEDGER_READ_AT_JOB_SCOPE" in codes


def test_accepts_a_research_that_carries_and_records_the_documents_state(
    tmp_path: Path,
) -> None:
    codes = _adr16_probe(
        tmp_path,
        CONTINUATION_STORE,
        """
class WorkbookResearchJobService:
"""
        + LINEAGE_READER_OK
        + """
    def begin_or_resume(self, identity):
        self._insert(identity)
        return self._inherit_document_progress(self._conn, job_id=identity.job_id, identity=identity)

    def _inherit_document_progress(self, conn, *, job_id, identity):
        conn.execute(
            "UPDATE jobs SET accepted_rows_json=?, continues_job_id=? WHERE job_id=?",
            (job_id, identity.parent, job_id),
        )
        return {}
""",
    )
    assert "OFFER_LEDGER_READ_AT_JOB_SCOPE" not in codes
