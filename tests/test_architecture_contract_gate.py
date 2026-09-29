from pathlib import Path

from tools.architecture_contract_gate import scan_architecture


def _write(root: Path, relative_path: str, text: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _codes(root: Path) -> set[str]:
    return {item.code for item in scan_architecture(root)}


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
