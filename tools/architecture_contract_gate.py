from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable, Sequence


_PARALLEL_WORKBOOK_RE = re.compile(
    r"estimate_(?:build_)?(?:lsr|vor).*|estimate_.*workbook",
    re.IGNORECASE,
)
_WORKBOOK_NAMES = {"build_lsr_workbook", "build_vor_workbook"}
_MODEL_ENDPOINT_MARKERS = (
    "/api/generate",
    "/v1/chat/completions",
    "/v1/responses",
)
# The chat-generation route is ``/api/chat`` exactly. Match it only as a whole
# endpoint so sibling data routes (e.g. ``/api/chat/patch-lsr-rows``), which
# persist model-authored rows and never call a model, are not mistaken for a
# governor bypass. External model transports above stay substring-matched.
_MODEL_CHAT_ROUTE_RE = re.compile(r"/api/chat(?:[\"'\s?]|$)")


def _calls_model_endpoint(call_text: str) -> bool:
    if any(marker in call_text for marker in _MODEL_ENDPOINT_MARKERS):
        return True
    return bool(_MODEL_CHAT_ROUTE_RE.search(call_text))
_ACTIVATION_BOUNDARIES = {
    "proxy/routers/profiles.py",
    "proxy/services/chat_profile_service.py",
    "tests/test_chat_profile_service.py",
    "tests/test_profiles_router.py",
}
_GATE_SELF_PATHS = {
    "tests/test_architecture_contract_gate.py",
    "tools/architecture_contract_gate.py",
}
_PROVIDER_NEUTRAL_MODEL_PATHS = {
    "proxy/services/canonical_route_service.py",
    "proxy/services/chat_evidence_application_service.py",
    "proxy/services/openai_compatible_transport_service.py",
}
_ENGINE_NAMES = {
    "freetoken",
    "lemonade",
    "lm studio",
    "lmstudio",
    "mlx",
    "ollama",
}

# ADR-16: on the estimate path code guarantees candidate *retrieval*, the model
# still decides. Three boundaries make that rule mechanical instead of prose.
SANCTIONED_CANDIDATE_QUERY_MODULE = "proxy/services/lsr_candidate_query_service.py"
DERIVED_COMPOSITION_HELPERS = frozenset(
    {
        "candidate_queries_for_packet",
        "candidate_queries_for_rows",
        "merge_candidate_queries",
    }
)
QUERY_PROVENANCE_BUILDERS = frozenset(
    {
        "build_model_rag_evidence_groups",
        "select_model_rag_query_hits_for_budget",
        "model_rag_evidence_header_chars",
    }
)
EXPLICIT_PRICEBOOK_PATHS = frozenset(
    {"proxy/services/lsr_workbook_adapter_service.py"}
)

# Task 2026-09-28 § 4: one source document stays one downloadable document.
# The packaging module owns the revision chain; the model never has to name an
# internal revision id, and a continuation may not start a second file.
WORKBOOK_PACKAGING_MODULE = "proxy/services/workbook_tool_service.py"
DOCUMENT_LINEAGE_RESOLVER = "_packaging_parent"

# Task 2026-09-28 § 7: a price basis the operator never sees is a silent default
# seen from the other end.  The chat-side projection is the single copy shared by
# the stored history row, the readiness block and the tool result handed back to
# the model, and it is a whitelist by construction — which is how build 816 lost
# the basis, the price holes and the reversed-operation rows on the way to the
# «Выберите регион и уровень цен» bubble.  Both carriers are therefore pinned.
BASIS_CARRIER_MODULES = (
    WORKBOOK_PACKAGING_MODULE,
    "proxy/services/chat_evidence_application_service.py",
)
OPERATOR_FIELDS_MUST_REACH_CHAT = frozenset(
    {"price_basis", "price_gaps", "norm_conflicts"}
)

# Task 2026-09-28 § 4, § 7: the region and period a document was priced in belong
# to that document, not to the wording of the next reply.  Build 820 priced
# revision 1 of «ВОР — Общая по Каменке» in sankt-peterburg_3kv2026 and revisions
# 2..6 of the same document in nothing at all, because every turn re-derived the
# basis from its own question text — live proof in
# ``stage_b/live_820/basis_continuation/basis_continuation.json``.  Three modules
# close that hole and any one of them can reopen it silently: the job that stores
# the basis with the packaged revision, the carrier that reads it back into the
# next packaging call, and the repack route that rebuilds the file without a model.
DOCUMENT_BASIS_STORAGE_MODULE = "proxy/services/workbook_research_job_service.py"
DOCUMENT_BASIS_CARRIER_MODULE = "proxy/services/chat_evidence_application_service.py"
DOCUMENT_BASIS_REPACK_MODULE = "proxy/routers/chat.py"
DOCUMENT_BASIS_PACKAGING_ARG = "document_price_basis"
DOCUMENT_BASIS_EVENT_KEY = "price_basis"
DOCUMENT_BASIS_ARGS_BUILDER = "workbook_packaging_args"
DOCUMENT_BASIS_READER = "workbook_document_price_basis"
DOCUMENT_BASIS_ARG_KEEPER = "document_price_basis_arguments"
DOCUMENT_BASIS_RECORDER = "record_packaging"
PRICED_PACKAGING_TOOL = "build_lsr_workbook"
#: the seam the route where the model itself asks for the file has to use
WORKBOOK_TOOL_EXECUTOR_CALL = "workbook_tool_executor"
MODEL_PACKAGING_BASIS_READER = "model_packaging_document_basis"
MODEL_PACKAGING_EVENT_BUILDER = "model_packaging_record_arguments"
#: …and it is read back across *every* research of that document: a continuation
#: reply opens a new job (the durable identity covers the question), so a basis the
#: next job never wrote has to come from the document's own history (build 822,
#: live ``B0_camenka``: revisions 2..5 reported no book over a priced document).
DOCUMENT_BASIS_SCOPE_EVENTS = "document_packaging_events"
DOCUMENT_BASIS_SCOPE_READER = "document_priced_basis"

# Blocker 2026-09-29 § 1: «Состояние очереди/попыток сохранять при рестарте» and
# «Не повторять один и тот же набор без новых данных/evidence» speak about the
# *document*, not about one research row.  «Продолжи это же задание…» changes the
# question and the question digest is part of the durable identity, so it opens a
# new job — and a new job that reads its offer ledger from its own checkpoints
# starts that ledger at zero.  Measured live on build 824 over the customer's ВОР
# (``stage_b/live_824/b1_lineage_824_continuation.json``): 177 rows the previous
# research had already decided were put to the model again, all 32 rows it had
# deferred were re-offered, 275 cached queries re-issued and 277 evidence records
# re-derived.  Three links of one seam, each of which can reopen that hole alone:
# the loop that reads the ledger, the reader that spans the lineage, and the
# writer that carries the document's state into the next research of it.
OFFER_LEDGER_HELPERS = frozenset({"packet_offer_counts", "packet_attempt_seed"})
OFFER_LEDGER_LINEAGE_READER = "list_events_with_lineage"
OFFER_LEDGER_SINGLE_JOB_READER = "list_events"
DOCUMENT_LINEAGE_WALKER = "lineage_job_ids"
CONTINUATION_LINEAGE_COLUMN = "continues_job_id"
CONTINUATION_PROGRESS_WRITER = "_inherit_document_progress"
CONTINUATION_PROGRESS_RESUMER = "begin_or_resume"
PACKET_CHECKPOINT_EVENT = "packet_checkpoint"

# Task 2026-09-28 § 7: the operator's own result line has to name the basis the
# estimate was computed in and the identifier of the price book.  Build 822 spoke
# about a basis only when it was wrong, so «ЛСР собрана частично…» carried no book
# while the delivered XLSX printed «Книга цен: …» — two surfaces, one document (§ 10).
LSR_BASIS_NOTICE_MODULE = "proxy/services/lsr_result_readiness_service.py"
LSR_BASIS_NOTICE_FORMATTER = "format_lsr_readiness_notice"
LSR_BASIS_SUFFIX_BUILDER = "_lsr_basis_suffix"
LSR_BASIS_VISIBILITY_FLAG = "basis_visible"
LSR_BASIS_MATCHED_STATE = "exact"

# A refusal to choose and an absent book are two different answers, and only the
# derivation that looked at the whole source text knows which one it gave.  Build
# 822 answered the live cell ``B3_bap_pdf`` — task says Москва, the object address
# inside the PDF says Санкт-Петербург — with «Запрошенная ценовая база … локально
# не найдена» over an installed ``moskva_3kv2026``.  The carrier and the summary
# live in one module, so the gate keeps them wired together.
BASIS_REFUSAL_MODULE = "proxy/services/lsr_workbook_adapter_service.py"
BASIS_REFUSAL_DERIVER = "explicit_estimate_pricebook"
BASIS_REFUSAL_SUMMARY = "summarize_lsr_price_basis"
BASIS_REFUSAL_CARRIED_ARGS = (
    "basis_contradictions",
    "basis_refusal",
    "basis_candidates",
)
BASIS_REFUSAL_DERIVER_KEYS = (
    "contradicting_regions",
    "contradicting_quarters",
    "refusal",
    "matching_books",
)
#: what may only be said about a basis that really is not in the catalogue
BASIS_REFUSAL_ABSENT_PHRASE = "локально не найдена"

# A rate that nobody chose may still be calculated, but only under the label the
# readiness state, the price gaps and the confirmed/preliminary split key on.
# Dropping that label would silently return the defect ADR-16 § 7 closes: a
# norm-card number counted as a confirmed amount of a chosen price basis.
UNOWNED_PRICE_SOURCES = {
    # PriceTrace source token -> the action label that must accompany it
    "card_price": "card_price_without_basis",
}

# Task 2026-09-29 § 3 (tracker #63): the two LSR calculators walk ONE price ladder,
# and the question «does this rate have an owner?» has exactly one implementation.
# ``lsr_assembly_service._resource_price`` used to return any explicit ``price`` as
# "manual" before the chosen book was asked, so a norm-card number counted as
# operator money there while the РИМ trace labelled the same row a draft: one card,
# two sums, and a ценовая база the operator picked that never reached the position.
PRICE_OWNERSHIP_LADDER = {
    "proxy/services/rim_lsr_trace_service.py": "_resolve_price_trace",
    "proxy/services/lsr_assembly_service.py": "_resource_price",
}
PRICE_OWNERSHIP_GUARD_FUNCTION = "price_is_attributed"
PRICE_OWNERSHIP_UNOWNED_TOKENS = frozenset({"card_price", "CARD_PRICE_SOURCE"})

# Task 2026-09-28 § 8, § 11 № 8: a price book row is a price *per the unit the
# row states*.  The book answers to a шифр, so an engine that took the number
# without comparing units could price a position that states «л» off a row that
# says «кг» and still report it as complete (the 818 probe sent exactly that:
# ``stage_b/live_818/markup_price_path.json``).  No card in the sample disagrees
# with its own book row, so the hole is latent on the current base (135 rows read
# by шифр over the 818 matrix sample, 0 of them naming another unit —
# ``stage_b/live_818/book_unit_gap.json``), which is
# exactly why it is closed by a rule and a gate rather than by an example.  Both
# LSR calculators read the same book, so every function that looks a resource up
# has to pass the row through the one shared rule; a hole that rule opens has to
# stay named in the two services that speak to the operator, or the readiness card
# would call it "подтверждённая цена" and ask for a price the book already has.
BOOK_LOOKUP_MODULES = (
    "proxy/services/rim_lsr_trace_service.py",
    "proxy/services/lsr_assembly_service.py",
)
BOOK_UNIT_GUARD_FUNCTION = "book_price_unit_conflict"
BOOK_UNIT_QUESTION_MODULES = (
    "proxy/services/lsr_workbook_adapter_service.py",
    "proxy/services/lsr_result_readiness_service.py",
)
BOOK_UNIT_HOLE_TOKENS = frozenset({"book_unit_conflict", "BOOK_UNIT_CONFLICT_ACTION"})

# Task 2026-09-28 § 11 № 6: НР/СП copied off the norm card is money with no owner.
# The trace service names the owner, the workbook adapter turns that name into one
# operator question per position.  Both halves can regress silently and both are
# the same defect: a label the adapter has never heard of makes ``_nr_sp_gap``
# return nothing, and a collection that stopped calling it drops the question —
# either way the position closes and the estimate is announced without asking who
# owns the accrual rate.
ACCRUAL_OWNERSHIP_MODULE = "proxy/services/rim_lsr_trace_service.py"
ACCRUAL_OWNERSHIP_DICT = "nr_sp_ownership"
ACCRUAL_QUESTION_MODULE = "proxy/services/lsr_workbook_adapter_service.py"
ACCRUAL_GAP_FUNCTION = "_nr_sp_gap"
ACCRUAL_GAP_COLLECTION_FUNCTION = "collect_lsr_price_gaps"
ACCRUAL_LABELS = frozenset({"nr_sp_without_basis", "nr_sp_unresolved"})

# Task 2026-09-30 § 3 (installed 929): a шифр was chosen from an inventory pointer, its card
# was never delivered, and the position was still priced.  One seam, three links: the sheet
# pass must ask the model to prove the choice (`norm_card_proof_reads_needed` + the message +
# the visible record), the proof module must state the missing fact without proposing a norm
# (`read_norm_card` named, шифр not chosen for the model), and the delivery facts must be read
# out of the text that was actually rendered (`_pointer_body`, the composition block) instead
# of echoed from the caller.  Breaking any link silently returns 929: pointer, guess, money.
NORM_PROOF_CHAT_MODULE = "proxy/services/chat_evidence_application_service.py"
NORM_PROOF_PACKET_FUNCTION = "run_chat_evidence_application"
NORM_PROOF_ASK_NEIGHBOURS = ("bind_row_evidence_ids", "admit_model_result_packet")
NORM_PROOF_REQUIRED_CALLS = (
    "norm_card_proof_reads_needed",
    "norm_card_proof_request_message",
    "norm_card_unread_rows",
    "record_norm_card_proof_request",
)
# Installed 930 measured why the ask must be counted from rows and the verdict must be total:
# 15 of the 17 БАП rows that named a шифр cited no card at all, so a refs-only view saw one
# debt, no verdict was written for the other fourteen, and the calculator paid for them.
NORM_PROOF_VERDICT_FIELD = "card_body_shown"
NORM_PROOF_VERDICT_SOURCE = "delivered_cipher_keys"
NORM_PROOF_SERVICE_MODULE = "proxy/services/norm_card_proof_service.py"
NORM_PROOF_MESSAGE_FUNCTION = "proof_request_message"
NORM_PROOF_READ_TOOL = "read_norm_card"
NORM_PROOF_UNREAD_FUNCTION = "unread_chosen_norm_refs"
NORM_PROOF_UNREAD_ROWS_FUNCTION = "unread_chosen_norm_rows"
DELIVERY_FACTS_MODULE = "proxy/services/model_rag_grouped_evidence_service.py"
DELIVERY_FACTS_FUNCTION = "card_delivery_facts"
DELIVERY_FACTS_REQUIRED_REFS = ("_pointer_body", "Состав работы:")

# Existing direct transports are migration debt, pinned by exact path + function.
# New callsites must use ContextGovernor instead of expanding this baseline.
INFERENCE_CALLSITE_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("backend/mail_profile.py", "_vlm_image_bytes"),
        ("backend/ocr_parser.py", "ocr_page"),
        ("backend/raptor_summarizer.py", "__call__"),
        ("backend/reranker.py", "_call_llm"),
        ("lemonade_host.py", "chat_completions"),
        ("mlx_host.py", "chat_completions"),
        ("mlx_host.py", "generate_ollama"),
        ("proxy/app.py", "_warmup_models"),
        ("proxy/routers/runtime.py", "warmup_models"),
        ("proxy/services/memory_worker_service.py", "_extract_local"),
        ("proxy/services/smeta_agent_runner_service.py", "_structured_terminal_mapping"),
        ("proxy/services/tool_harness_service.py", "_tool_look_at_pdf_page"),
        ("tools/basic_function_smoke.py", "_chat"),
        ("tools/smeta_model_quality_benchmark.py", "_unload_model"),
        ("tools/smeta_model_quality_benchmark.py", "_warm_model"),
    }
)


@dataclass(frozen=True)
class ArchitectureViolation:
    code: str
    path: str
    line: int
    detail: str


def _tracked_sources(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", "*.py", "*.md"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return [
            root / line
            for line in completed.stdout.splitlines()
            if line and _source_path_is_allowed(Path(line))
        ]
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix.lower() in {".py", ".md"}
        and _source_path_is_allowed(path.relative_to(root))
    )


def _source_path_is_allowed(relative: Path) -> bool:
    if relative.as_posix() in _GATE_SELF_PATHS:
        return False
    excluded = {
        ".git",
        ".venv",
        "data",
        "dist",
        "local_private_archive",
        "logs",
        "RAG_Content",
        "storage",
    }
    parts = set(relative.parts)
    if parts & excluded:
        return False
    return not ("exporters" in parts and "artifacts" in parts)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _string_value(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else "{}"
            for value in node.values
        )
    return ""


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        owner = node.func.value
        if isinstance(owner, ast.Name):
            return f"{owner.id}.{node.func.attr}"
        return node.func.attr
    return ""


def _enclosing_function_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return "<module>"


def _enclosing_class_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.ClassDef):
            return current.name
        current = parents.get(current)
    return None


def _engine_name_literals(node: ast.AST) -> set[str]:
    return {
        item.value.strip().lower()
        for item in ast.walk(node)
        if isinstance(item, ast.Constant)
        and isinstance(item.value, str)
        and item.value.strip().lower() in _ENGINE_NAMES
    }


def _contains_context_governor(function: ast.AST) -> bool:
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and "context_governor" in node.id.lower():
            return True
        if isinstance(node, ast.Attribute) and "context_governor" in node.attr.lower():
            return True
        if isinstance(node, ast.Name) and node.id == "ContextGovernor":
            return True
    return False


def _function_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parents.get(current)
    return node


def _has_language_matcher(function: ast.AST) -> bool:
    language_subject_markers = ("question", "query", "prompt", "message", "user_input", "text")

    def is_language_subject(node: ast.AST) -> bool:
        return any(
            isinstance(item, ast.Name)
            and any(marker in item.id.casefold() for marker in language_subject_markers)
            for item in ast.walk(node)
        )

    for node in ast.walk(function):
        if isinstance(node, ast.Call) and _call_name(node) in {
            "re.search",
            "re.match",
            "re.fullmatch",
            "re.compile",
        }:
            return True
        if (
            isinstance(node, ast.Compare)
            and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
            and is_language_subject(node)
        ):
            return True
    return False


def _has_workbook_call(function: ast.AST) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node).split(".")[-1] in _WORKBOOK_NAMES:
            return True
        if any(_string_value(arg) in _WORKBOOK_NAMES for arg in node.args):
            return True
    return False


def _adr16_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """ADR-16 boundaries: who may author a query, and what may bind a price book."""

    for scope in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        calls = [node for node in ast.walk(scope) if isinstance(node, ast.Call)]
        names = {_call_name(node) for node in calls}
        short_names = {name.split(".")[-1] for name in names}
        inline_regex = any(name.startswith("re.") for name in names)
        vocabulary_swap = bool(short_names & {"sub", "subn", "replace"})
        composes = bool(short_names & DERIVED_COMPOSITION_HELPERS)
        sanctioned = relative == SANCTIONED_CANDIDATE_QUERY_MODULE
        if (sanctioned or composes) and (inline_regex or vocabulary_swap):
            yield ArchitectureViolation(
                "DERIVED_QUERY_SEMANTIC_INVENTION",
                relative,
                scope.lineno,
                f"{scope.name}() composes candidate queries with regex or substitution "
                "instead of literal source text",
            )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        short_name = _call_name(node).split(".")[-1]
        if short_name == "CandidateQuery" and not relative.startswith("tests/"):
            # Same scoping as the provenance rule above: the guard exists so that
            # no production path can author a ``derived`` query somewhere the
            # literalness check does not run.  An isolated test may build one by
            # hand precisely to prove that check rejects it.
            for keyword in node.keywords:
                if keyword.arg == "provenance" and _string_value(keyword.value) == "derived":
                    if relative != SANCTIONED_CANDIDATE_QUERY_MODULE:
                        yield ArchitectureViolation(
                            "DERIVED_QUERY_SEMANTIC_INVENTION",
                            relative,
                            node.lineno,
                            "derived query authored outside the sanctioned candidate-query module",
                        )
        if short_name in QUERY_PROVENANCE_BUILDERS and not relative.startswith("tests/"):
            # The rule guards the sheet-pass wiring: production evidence builders must
            # name the provenance of every query they present. Isolated tests may
            # exercise the builders through their documented model-only default.
            provenance = next(
                (item.value for item in node.keywords if item.arg == "query_provenance"),
                "absent",
            )
            if provenance == "absent" or (
                isinstance(provenance, ast.Constant) and provenance.value is None
            ):
                yield ArchitectureViolation(
                    "QUERY_PROVENANCE_MISSING",
                    relative,
                    node.lineno,
                    "evidence builder called without a query_provenance map",
                )
        if (
            relative in EXPLICIT_PRICEBOOK_PATHS
            and short_name == "resolve_pricebook_path"
        ):
            explicit = any(
                item.arg == "explicit_only"
                and isinstance(item.value, ast.Constant)
                and item.value.value is True
                for item in node.keywords
            )
            if not explicit:
                yield ArchitectureViolation(
                    "PRICE_BASIS_SILENT_DEFAULT",
                    relative,
                    node.lineno,
                    "estimate path resolves a pricebook without explicit_only=True",
                )
        if short_name == "PriceTrace":
            # ADR-16 § 7: an unowned rate is only allowed together with the
            # label every downstream check keys on.
            source = next(
                (
                    _string_value(item.value)
                    for item in node.keywords
                    if item.arg == "source"
                ),
                "",
            )
            required_action = UNOWNED_PRICE_SOURCES.get(source)
            if required_action:
                action = next(
                    (
                        _string_value(item.value)
                        for item in node.keywords
                        if item.arg == "action"
                    ),
                    "",
                )
                if action != required_action:
                    yield ArchitectureViolation(
                        "UNOWNED_PRICE_SOURCE",
                        relative,
                        node.lineno,
                        f"PriceTrace(source={source!r}) is built without "
                        f"action={required_action!r}, so the rate would count as an owned price",
                    )


def _document_lineage_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """Task 2026-09-28 § 4: the artifact revision chain is code-owned identity.

    A continuation of the same source document has to stay the same downloadable
    document.  The packaging module therefore resolves the parent revision from
    the durable session lineage; reading it straight out of the tool arguments
    leaves the chain at the mercy of whatever the model happened to remember,
    which is how build 815 split one ВОР into two separate documents.
    """
    if relative != WORKBOOK_PACKAGING_MODULE:
        return
    requests = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "ArtifactRevisionRequest"
    ]
    if not requests:
        return
    resolver_defined = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == DOCUMENT_LINEAGE_RESOLVER
        for node in ast.walk(tree)
    )
    resolver_called = any(
        isinstance(node, ast.Call) and _call_name(node) == DOCUMENT_LINEAGE_RESOLVER
        for node in ast.walk(tree)
    )
    if not (resolver_defined and resolver_called):
        yield ArchitectureViolation(
            "DOCUMENT_LINEAGE_UNOWNED",
            relative,
            requests[0].lineno,
            f"artifact revision published without {DOCUMENT_LINEAGE_RESOLVER}()"
            " resolving the session lineage",
        )
        return
    for request in requests:
        parent = next(
            (item.value for item in request.keywords if item.arg == "parent_revision_id"),
            None,
        )
        if not isinstance(parent, ast.Name):
            yield ArchitectureViolation(
                "DOCUMENT_LINEAGE_UNOWNED",
                relative,
                request.lineno,
                "parent_revision_id taken straight from tool arguments instead of"
                " the code-owned lineage resolver",
            )


def _continuation_lineage_violations(
    relative: str, tree: ast.AST
) -> Iterable[ArchitectureViolation]:
    """Blocker § 1: the next research of a document continues its queue.

    Three links of one seam — the loop that counts offers, the reader that has to
    span the document's lineage, and the writer that carries the durable state into
    the research that continues it.  Any one of them can restart the ledger at zero
    silently, and on build 824 they did: a continuation turn over the customer's ВОР
    put 282 rows the previous research had already decided back to the model,
    re-offered all 32 deferred rows, re-issued 417 cached queries and re-derived 463
    evidence records, and added four rows to the document in 42 minutes
    (``stage_b/live_824/b1_lineage_824_continuation_final.json``).
    """

    if relative == DOCUMENT_BASIS_CARRIER_MODULE:
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            helper = _call_name(call).split(".")[-1]
            if helper not in OFFER_LEDGER_HELPERS:
                continue
            assigned = _reader_assignments(_function_scope(call, parents))
            readers: list[ast.Call] = []
            for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
                if isinstance(argument, ast.Call):
                    readers.append(argument)
                elif isinstance(argument, ast.Name):
                    readers.extend(assigned.get(argument.id, ()))
            if not readers:
                yield ArchitectureViolation(
                    "OFFER_LEDGER_READ_AT_JOB_SCOPE",
                    relative,
                    call.lineno,
                    f"{helper}() is fed from no durable event read: a counter that "
                    "lives in the loop restarts on every turn, so «не повторять один "
                    "и тот же набор без новых данных» cannot be enforced at all",
                )
                continue
            if not any(
                _call_name(reader).split(".")[-1] == OFFER_LEDGER_LINEAGE_READER
                for reader in readers
            ):
                yield ArchitectureViolation(
                    "OFFER_LEDGER_READ_AT_JOB_SCOPE",
                    relative,
                    call.lineno,
                    f"{helper}() reads the {PACKET_CHECKPOINT_EVENT} events of one "
                    "research job: «Продолжи это же задание…» opens a new job "
                    "over the same document, so its offer history starts at zero and "
                    "rows the previous research already decided go back to the model",
                )
        return

    if relative != DOCUMENT_BASIS_STORAGE_MODULE:
        return
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    lineage_reader = functions.get(OFFER_LEDGER_LINEAGE_READER)
    if lineage_reader is None:
        yield ArchitectureViolation(
            "OFFER_LEDGER_READ_AT_JOB_SCOPE",
            relative,
            1,
            f"the durable store exposes no {OFFER_LEDGER_LINEAGE_READER}(), so every "
            "offer ledger of a continuation is read from the one row it was given",
        )
    else:
        called = {
            _call_name(node).split(".")[-1]
            for node in ast.walk(lineage_reader)
            if isinstance(node, ast.Call)
        }
        if DOCUMENT_LINEAGE_WALKER not in called:
            yield ArchitectureViolation(
                "OFFER_LEDGER_READ_AT_JOB_SCOPE",
                relative,
                lineage_reader.lineno,
                f"{OFFER_LEDGER_LINEAGE_READER}() does not walk "
                f"{DOCUMENT_LINEAGE_WALKER}(): under that name it would still return "
                "the events of a single research job",
            )
    walker = functions.get(DOCUMENT_LINEAGE_WALKER)
    if walker is not None and not _mentions(walker, CONTINUATION_LINEAGE_COLUMN):
        yield ArchitectureViolation(
            "OFFER_LEDGER_READ_AT_JOB_SCOPE",
            relative,
            walker.lineno,
            f"{DOCUMENT_LINEAGE_WALKER}() never reads the "
            f"{CONTINUATION_LINEAGE_COLUMN} column, so the chain it walks is invented "
            "instead of the one the continuation was recorded from",
        )
    resumer = functions.get(CONTINUATION_PROGRESS_RESUMER)
    if resumer is not None:
        called = {
            _call_name(node).split(".")[-1]
            for node in ast.walk(resumer)
            if isinstance(node, ast.Call)
        }
        if CONTINUATION_PROGRESS_WRITER not in called:
            yield ArchitectureViolation(
                "OFFER_LEDGER_READ_AT_JOB_SCOPE",
                relative,
                resumer.lineno,
                f"{CONTINUATION_PROGRESS_RESUMER}() starts a new research without "
                f"{CONTINUATION_PROGRESS_WRITER}(): the document's decisions, "
                "evidence, query cache and deferrals stay on the previous row",
            )
    writer = functions.get(CONTINUATION_PROGRESS_WRITER)
    if writer is not None and not _mentions(writer, CONTINUATION_LINEAGE_COLUMN):
        yield ArchitectureViolation(
            "OFFER_LEDGER_READ_AT_JOB_SCOPE",
            relative,
            writer.lineno,
            f"{CONTINUATION_PROGRESS_WRITER}() carries progress without recording "
            f"{CONTINUATION_LINEAGE_COLUMN}, so the next continuation cannot tell "
            "which research it continues and the ledger cannot be read across it",
        )


def _reader_assignments(scope: ast.AST) -> dict[str, list[ast.Call]]:
    """``events = service.list_events_with_lineage(…)`` — what a name was bound to.

    The loop reads the ledger once and passes the variable to both helpers, so the
    seam has to be followed through the binding instead of only through literals.
    """

    assigned: dict[str, list[ast.Call]] = {}
    for node in ast.walk(scope):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets, value = [node.target], node.value
        if not isinstance(value, ast.Call):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assigned.setdefault(target.id, []).append(value)
    return assigned


def _mentions(node: ast.AST, token: str) -> bool:
    for item in ast.walk(node):
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            if token in item.value:
                return True
        elif isinstance(item, ast.Attribute) and item.attr == token:
            return True
        elif isinstance(item, ast.Name) and item.id == token:
            return True
    return False


def _basis_carrier_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """Task 2026-09-28 § 7: the basis and its questions must reach the operator.

    Build 816 computed everything correctly and still could not show the bubble:
    the adapter's ``price_basis``, ``price_gaps`` and ``norm_conflicts`` were
    dropped by the two carriers between the calculation and the chat answer, so
    ``dimensions.prices.basis`` stayed empty and the GUI projector had nothing to
    render.  A whitelist that forgets a field is exactly this defect, so the
    whitelist itself is now checked.
    """
    if relative not in BASIS_CARRIER_MODULES:
        return
    strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    missing = sorted(OPERATOR_FIELDS_MUST_REACH_CHAT - strings)
    if missing:
        yield ArchitectureViolation(
            "BASIS_QUESTIONS_NOT_CARRIED",
            relative,
            1,
            "carrier drops " + ", ".join(missing) + " — the estimate would report a "
            "draft that asks no question, and the price-basis bubble could never open",
        )


def _document_basis_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """Task 2026-09-28 § 4, § 7: a continuation keeps the basis of its document.

    The basis is data the operator chose once, so it has to be stored with the
    packaged revision and read back from there.  Re-deriving it from the text of
    the new reply is the 820 defect: «Продолжи это же задание…» names no region
    and no quarter, and the next six revisions printed «Ценовая база не задана
    явно» over a document that had already been priced.
    """
    if relative == DOCUMENT_BASIS_CARRIER_MODULE:
        builders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _call_name(node) == DOCUMENT_BASIS_ARGS_BUILDER
        ]
        if not builders:
            return
        model_basis = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == MODEL_PACKAGING_BASIS_READER
        ]
        # Checked ahead of the rest of this branch: build 822 failed on the route
        # where the *model* asked for the file, and that route can carry a basis
        # perfectly well while still reading only the job it was handed.
        if model_basis:
            if not any(
                isinstance(node, ast.Call)
                and _call_name(node) == DOCUMENT_BASIS_ARG_KEEPER
                for node in ast.walk(model_basis[0])
            ):
                yield ArchitectureViolation(
                    "PACKAGING_ROUTE_NOT_DURABLE",
                    relative,
                    model_basis[0].lineno,
                    f"{MODEL_PACKAGING_BASIS_READER}() parses a basis on its own instead of "
                    f"reusing {DOCUMENT_BASIS_ARG_KEEPER}(): two routes would disagree about "
                    "the basis of one document",
                )
            if not any(
                isinstance(node, ast.Call)
                and _call_name(node).split(".")[-1] == DOCUMENT_BASIS_SCOPE_READER
                for node in ast.walk(model_basis[0])
            ):
                yield ArchitectureViolation(
                    "DOCUMENT_BASIS_READ_AT_JOB_SCOPE",
                    relative,
                    model_basis[0].lineno,
                    f"{MODEL_PACKAGING_BASIS_READER}() reads only the job it was given: "
                    f"without {DOCUMENT_BASIS_SCOPE_READER}() the route where the model asks "
                    "for the file repeats the 822 failure on the next continuation",
                )
        reader_called = any(
            isinstance(node, ast.Call) and _call_name(node) == DOCUMENT_BASIS_READER
            for node in ast.walk(tree)
        )
        if not reader_called:
            yield ArchitectureViolation(
                "DOCUMENT_BASIS_NOT_CARRIED",
                relative,
                builders[0].lineno,
                f"{DOCUMENT_BASIS_ARGS_BUILDER}() is called without reading the basis "
                f"back through {DOCUMENT_BASIS_READER}()",
            )
            return
        for call in builders:
            if not any(
                item.arg == DOCUMENT_BASIS_PACKAGING_ARG for item in call.keywords
            ):
                yield ArchitectureViolation(
                    "DOCUMENT_BASIS_NOT_CARRIED",
                    relative,
                    call.lineno,
                    f"packaging call built without {DOCUMENT_BASIS_PACKAGING_ARG}= — the "
                    "priced continuation would lose the region and period it must reuse",
                )
        # Task 2026-09-28 § 5, § 11 № 9: the seam belongs to the document, not to
        # whichever route asked for the file.  The model is allowed to call the
        # packager itself under the ACTIVE canonical route, and that call site
        # delivered a priced ЛСР while writing no ``workbook_packaged`` event:
        # a document first packaged there had nothing to inherit, so its next
        # continuation reported «Ценовая база не задана явно» over a priced file.
        executors = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _call_name(node) == WORKBOOK_TOOL_EXECUTOR_CALL
        ]
        recorders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _call_name(node).split(".")[-1] == DOCUMENT_BASIS_RECORDER
        ]
        # one durable event per packaging route: the code-owned sheet pass and
        # the model-authored call are two routes over one document.
        if executors and len(recorders) < len(executors) + len(builders):
            yield ArchitectureViolation(
                "PACKAGING_ROUTE_NOT_DURABLE",
                relative,
                executors[-1].lineno,
                f"a route executes {PRICED_PACKAGING_TOOL} through "
                f"{WORKBOOK_TOOL_EXECUTOR_CALL}() without recording its own "
                f"{DOCUMENT_BASIS_RECORDER}() event: the file exists but the "
                "document carries no basis and no revision parent",
            )
        if executors and not any(
            isinstance(node, ast.Call)
            and _call_name(node) == MODEL_PACKAGING_EVENT_BUILDER
            for node in ast.walk(tree)
        ):
            yield ArchitectureViolation(
                "PACKAGING_ROUTE_NOT_DURABLE",
                relative,
                executors[-1].lineno,
                f"the model-authored packaging call does not build its durable event "
                f"through {MODEL_PACKAGING_EVENT_BUILDER}()",
            )
        for call in (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node) == DOCUMENT_BASIS_READER
        ):
            if not _basis_events_read_across_researches(tree, call):
                yield ArchitectureViolation(
                    "DOCUMENT_BASIS_READ_AT_JOB_SCOPE",
                    relative,
                    call.lineno,
                    f"{DOCUMENT_BASIS_READER}() is handed the events of one research job: "
                    "a continuation is a new job over the same document, so the basis the "
                    "first research recorded would be read as «no basis»",
                )
        return
    if relative == DOCUMENT_BASIS_REPACK_MODULE:
        strings = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        if PRICED_PACKAGING_TOOL not in strings:
            return
        recorder_called = any(
            isinstance(node, ast.Call)
            and _call_name(node) in {DOCUMENT_BASIS_ARG_KEEPER, DOCUMENT_BASIS_READER}
            for node in ast.walk(tree)
        )
        if DOCUMENT_BASIS_PACKAGING_ARG not in strings or not recorder_called:
            yield ArchitectureViolation(
                "DOCUMENT_BASIS_NOT_CARRIED",
                relative,
                1,
                f"the no-model repack packages {PRICED_PACKAGING_TOOL} without "
                f"{DOCUMENT_BASIS_PACKAGING_ARG}: a rebuilt file would re-ask, or quietly "
                "drop, the basis the document was priced in",
            )
        return
    if relative != DOCUMENT_BASIS_STORAGE_MODULE:
        return
    recorders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == DOCUMENT_BASIS_RECORDER
    ]
    if not recorders:
        return
    stored = any(
        argument.arg == DOCUMENT_BASIS_EVENT_KEY
        for argument in recorders[0].args.kwonlyargs + recorders[0].args.args
    )
    keyed = DOCUMENT_BASIS_EVENT_KEY in {
        node.value
        for node in ast.walk(recorders[0])
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    if not (stored and keyed):
        yield ArchitectureViolation(
            "DOCUMENT_BASIS_NOT_CARRIED",
            relative,
            recorders[0].lineno,
            f"{DOCUMENT_BASIS_RECORDER}() does not persist the price basis beside the "
            "revision, so a restart or a continuation has nothing to inherit",
        )
    scope_readers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == DOCUMENT_BASIS_SCOPE_EVENTS
    ]
    if not scope_readers:
        return
    scope_text = " ".join(
        node.value
        for node in ast.walk(scope_readers[0])
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )
    if "attachment_id" not in scope_text or "workbook_research_jobs" not in scope_text:
        yield ArchitectureViolation(
            "DOCUMENT_BASIS_READ_AT_JOB_SCOPE",
            relative,
            scope_readers[0].lineno,
            f"{DOCUMENT_BASIS_SCOPE_EVENTS}() does not gather the researches of one "
            "attachment: under that name a single job would still answer «no basis» to "
            "the continuation that opened the next one",
        )


def _basis_events_read_across_researches(tree: ast.AST, call: ast.Call) -> bool:
    """True when this basis read is fed the packaging events of the *document*.

    ``workbook_document_price_basis()`` answers from whatever event list it is
    handed, so the seam is the caller's source: the packaging history of the
    attachment (``document_packaging_events()``), not the events of the job this
    reply happens to run (``list_events(job_id)``).
    """

    argument = call.args[0] if call.args else next(
        (item.value for item in call.keywords if item.arg in {"events", "packaging_events"}),
        None,
    )
    if isinstance(argument, ast.Call):
        return _call_name(argument).split(".")[-1] == DOCUMENT_BASIS_SCOPE_EVENTS
    if isinstance(argument, ast.Name):
        assigned: list[ast.expr | None] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == argument.id
                for target in node.targets
            ):
                assigned.append(node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == argument.id:
                    assigned.append(node.value)
        if not assigned:
            # nothing in this module writes the name: not this check's business
            return True
        return any(
            DOCUMENT_BASIS_SCOPE_EVENTS in _read_source_names(value) for value in assigned
        )
    return True


def _read_source_names(value: ast.expr | None) -> set[str]:
    """Trailing call names this assignment could have been built from."""

    if value is None:
        return set()
    return {
        _call_name(node).split(".")[-1]
        for node in ast.walk(value)
        if isinstance(node, ast.Call)
    }


def _lsr_basis_notice_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """Task 2026-09-28 § 7: the operator's own line names the basis it was priced in.

    Build 822 told the operator everything about a basis that had gone wrong and
    nothing about one that had been applied, so «ЛСР собрана частично…» carried no
    book while the very file it announced printed «Книга цен: …» on its header.  § 10
    asks those two surfaces to agree, so the notice names the applied basis and the
    identifier of the book that produced it.
    """

    if relative != LSR_BASIS_NOTICE_MODULE:
        return
    formatters = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == LSR_BASIS_NOTICE_FORMATTER
    ]
    if not formatters:
        return
    formatter = formatters[0]
    visibility = [
        node
        for node in ast.walk(formatter)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == LSR_BASIS_VISIBILITY_FLAG
            for target in node.targets
        )
    ]
    if not visibility:
        yield ArchitectureViolation(
            "APPLIED_BASIS_NOT_NAMED",
            relative,
            formatter.lineno,
            f"{LSR_BASIS_NOTICE_FORMATTER}() has no {LSR_BASIS_VISIBILITY_FLAG} decision at "
            "all: the result line would not say which price basis it was computed in",
        )
    else:
        for compare in (
            node
            for node in ast.walk(visibility[0].value)
            if isinstance(node, ast.Compare)
            and isinstance(node.ops[0], ast.In)
            and isinstance(node.comparators[0], (ast.Set, ast.List, ast.Tuple))
        ):
            states = {
                item.value
                for item in compare.comparators[0].elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            if states and LSR_BASIS_MATCHED_STATE not in states:
                yield ArchitectureViolation(
                    "APPLIED_BASIS_NOT_NAMED",
                    relative,
                    visibility[0].lineno,
                    f"{LSR_BASIS_VISIBILITY_FLAG} enumerates only the broken states "
                    f"({', '.join(sorted(states))}): an applied {LSR_BASIS_MATCHED_STATE} "
                    "basis stays unnamed in the chat over a file that names its book",
                )
    for call in (
        node
        for node in ast.walk(formatter)
        if isinstance(node, ast.Call)
        and _call_name(node).split(".")[-1] == LSR_BASIS_SUFFIX_BUILDER
    ):
        if len(call.args) < 3 and not any(item.arg == "book" for item in call.keywords):
            yield ArchitectureViolation(
                "APPLIED_BASIS_NOT_NAMED",
                relative,
                call.lineno,
                f"{LSR_BASIS_SUFFIX_BUILDER}() is called without the price book "
                "identifier: § 7 asks every result to name the book it was priced in",
            )


def _basis_refusal_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """ADR-16 § 7 with the live 823 evidence from matrix cell ``B3_bap_pdf``.

    A task that names Москва and a source document whose own object address names
    Санкт-Петербург is a *refusal to choose*, while a named period nobody has a
    book for is a *missing basis*. The first is decided by
    ``explicit_estimate_pricebook``, which reads the whole source text; the answer
    the operator reads is written by ``summarize_lsr_price_basis``, which only sees
    what the call site hands it. Build 822 had the first right and the second
    wrong: «локально не найдена» over an installed ``moskva_3kv2026``, which is a
    false statement about the local catalogue (§ 7, «не объявляй всю базу
    отсутствующей»). The three links of that seam are checked together.
    """

    if relative != BASIS_REFUSAL_MODULE:
        return
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    deriver = functions.get(BASIS_REFUSAL_DERIVER)
    if deriver is not None:
        written: set[str] = set()
        for node in ast.walk(deriver):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        written.add(target.slice.value)
            elif isinstance(node, ast.Dict):
                written.update(
                    key.value
                    for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
        missing = [name for name in BASIS_REFUSAL_DERIVER_KEYS if name not in written]
        if missing:
            yield ArchitectureViolation(
                "CONTRADICTED_BASIS_ANNOUNCED_ABSENT",
                relative,
                deriver.lineno,
                f"{BASIS_REFUSAL_DERIVER}() no longer hands back what it refused "
                f"({', '.join(missing)}): the refusal is computed here and dies "
                "here, and the operator is told the base does not exist",
            )
    summary = functions.get(BASIS_REFUSAL_SUMMARY)
    if summary is not None:
        accepted = {
            item.arg
            for item in (*summary.args.posonlyargs, *summary.args.args, *summary.args.kwonlyargs)
            if item.arg
        }
        unwired = [name for name in BASIS_REFUSAL_CARRIED_ARGS if name not in accepted]
        if unwired:
            yield ArchitectureViolation(
                "CONTRADICTED_BASIS_ANNOUNCED_ABSENT",
                relative,
                summary.lineno,
                f"{BASIS_REFUSAL_SUMMARY}() takes no "
                + ", ".join(unwired)
                + ": it cannot tell a refused choice from an absent book",
            )
        for node in ast.walk(summary):
            if not (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "pricebook"
            ):
                continue
            guarded = min(
                (
                    item.lineno
                    for item in ast.walk(node)
                    if isinstance(item, ast.If)
                    and any(
                        name.id in {"contradictions", "refusal"}
                        for name in ast.walk(item.test)
                        if isinstance(name, ast.Name)
                    )
                ),
                default=0,
            )
            announced = min(
                (
                    item.lineno
                    for item in ast.walk(node)
                    if isinstance(item, ast.Constant)
                    and isinstance(item.value, str)
                    and BASIS_REFUSAL_ABSENT_PHRASE in item.value
                ),
                default=0,
            )
            if announced and not (guarded and guarded < announced):
                yield ArchitectureViolation(
                    "CONTRADICTED_BASIS_ANNOUNCED_ABSENT",
                    relative,
                    node.lineno,
                    "the no-basis answer states «"
                    + BASIS_REFUSAL_ABSENT_PHRASE
                    + "» without first deciding whether the explicit sources "
                    "contradict each other: a refused choice is reported as an "
                    "absent price book",
                )
            break
    for call in (
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _call_name(node).split(".")[-1] == BASIS_REFUSAL_SUMMARY
    ):
        passed = {item.arg for item in call.keywords if item.arg}
        unwired = [
            name for name in BASIS_REFUSAL_CARRIED_ARGS if name not in passed
        ]
        if unwired:
            yield ArchitectureViolation(
                "CONTRADICTED_BASIS_ANNOUNCED_ABSENT",
                relative,
                call.lineno,
                f"{BASIS_REFUSAL_SUMMARY}() is called without "
                + ", ".join(unwired)
                + "=: the derivation knew which bases it was shown and which "
                "installed books agree with them, and the operator is not told",
            )


def _accrual_label_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """Task 2026-09-28 § 11 № 6: an accrual rate without an owner stays a question.

    The trace service records who owns НР/СП, the workbook adapter converts that
    ownership into one operator question per position.  A label invented on the
    trace side is invisible to the adapter, and a collection that no longer calls
    the gap builder drops the question — in both cases the position closes with
    money nobody may claim to have chosen.
    """
    if relative == ACCRUAL_OWNERSHIP_MODULE:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [
                item.id
                for item in node.targets
                if isinstance(item, ast.Name) and item.id == ACCRUAL_OWNERSHIP_DICT
            ]
            subscripted = any(
                isinstance(item, ast.Subscript)
                and isinstance(item.value, ast.Name)
                and item.value.id == ACCRUAL_OWNERSHIP_DICT
                and isinstance(item.slice, ast.Constant)
                and item.slice.value == "label"
                for item in node.targets
            )
            pairs: list[tuple[int, str]] = []
            if subscripted and isinstance(node.value, ast.Constant):
                pairs.append((node.lineno, str(node.value.value)))
            if names and isinstance(node.value, ast.Dict):
                for key, value in zip(node.value.keys, node.value.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "label"
                        and isinstance(value, ast.Constant)
                    ):
                        pairs.append((node.lineno, str(value.value)))
            for line, label in pairs:
                if label in ACCRUAL_LABELS or label == "":
                    continue
                yield ArchitectureViolation(
                    "ACCRUAL_LABEL_NOT_ASKED",
                    relative,
                    line,
                    f"{ACCRUAL_OWNERSHIP_DICT}['label'] = {label!r} is unknown to "
                    f"{ACCRUAL_QUESTION_MODULE}, so the position would close without "
                    "asking the operator who owns НР/СП",
                )
        return

    if relative != ACCRUAL_QUESTION_MODULE:
        return
    known = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    missing = sorted(ACCRUAL_LABELS - known)
    if missing:
        yield ArchitectureViolation(
            "ACCRUAL_LABEL_NOT_ASKED",
            relative,
            1,
            "the adapter does not name " + ", ".join(missing) + ", so an accrual rate "
            "with no owner would produce no operator question",
        )
    collectors = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == ACCRUAL_GAP_COLLECTION_FUNCTION
    ]
    if not collectors:
        yield ArchitectureViolation(
            "ACCRUAL_LABEL_NOT_ASKED",
            relative,
            1,
            f"{ACCRUAL_GAP_COLLECTION_FUNCTION}() disappeared, so no price gap and no "
            "accrual question reaches the readiness card",
        )
        return
    called = any(
        isinstance(node, ast.Call) and _call_name(node) == ACCRUAL_GAP_FUNCTION
        for collector in collectors
        for node in ast.walk(collector)
    )
    if not called:
        yield ArchitectureViolation(
            "ACCRUAL_LABEL_NOT_ASKED",
            relative,
            collectors[0].lineno,
            f"{ACCRUAL_GAP_COLLECTION_FUNCTION}() no longer calls "
            f"{ACCRUAL_GAP_FUNCTION}(), so НР/СП without an owner would stay unasked",
        )


def _book_price_unit_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """Task 2026-09-28 § 8, § 11 № 8: a book price is a price for the row's own unit.

    ``PriceBook.lookup`` answers to a шифр.  An engine that reads the number
    straight away prices a resource the norm card gives in «л» off a row that
    states «кг», and the position still closes as complete — money no arithmetic
    supports.  Both LSR calculators therefore have to consult the one shared rule
    in the same function that looks the resource up, and the two services that
    speak to the operator have to keep naming the hole the rule opens: a label
    they have never heard of reads as "подтверждённая цена" and sends the customer
    to confirm a number instead of the unit behind it.
    """

    if relative in BOOK_LOOKUP_MODULES:
        for scope in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            calls = [node for node in ast.walk(scope) if isinstance(node, ast.Call)]
            lookups = [
                node
                for node in calls
                if _call_name(node).split(".")[-1] == "lookup"
            ]
            if not lookups:
                continue
            guarded = any(
                _call_name(node).split(".")[-1] == BOOK_UNIT_GUARD_FUNCTION
                for node in calls
            )
            if not guarded:
                yield ArchitectureViolation(
                    "BOOK_PRICE_UNIT_UNCHECKED",
                    relative,
                    lookups[0].lineno,
                    f"{scope.name}() uses a price book row without "
                    f"{BOOK_UNIT_GUARD_FUNCTION}(), so a шифр the book prices per "
                    "another unit would be multiplied by this position's quantity "
                    "and reported as a confirmed amount",
                )
        return

    if relative in BOOK_UNIT_QUESTION_MODULES:
        named = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        } | {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        if not named & BOOK_UNIT_HOLE_TOKENS:
            yield ArchitectureViolation(
                "BOOK_PRICE_UNIT_UNCHECKED",
                relative,
                1,
                "the module stopped naming the book-unit price hole, so the "
                "operator would be asked for a price the chosen book already "
                "carries in a unit the position does not use",
            )


def _price_ownership_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """Task 2026-09-29 § 3 (tracker #63): one ownership question decides a resource price.

    ``PriceBook.lookup`` answers by шифр, and a norm card carries its own rate for the
    same resource.  Whichever calculator takes that rate first decides whether the
    operator's chosen base is consulted at all and whether the number reads as confirmed
    money.  Both ladders therefore have to ask the one question — "does this rate have an
    owner?" — and keep returning the labelled card source, or the same card becomes two
    documents (ADR-16 § 7, § 10).
    """

    function_name = PRICE_OWNERSHIP_LADDER.get(relative)
    if function_name is None:
        return
    scope = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if scope is None:
        yield ArchitectureViolation(
            "UNOWNED_PRICE_SOURCE_ADOPTED",
            relative,
            1,
            f"{function_name}() is gone, so the price ladder no longer has one home and "
            "an engine could take a norm-card rate as its first answer",
        )
        return
    called = {
        _call_name(node).split(".")[-1]
        for node in ast.walk(scope)
        if isinstance(node, ast.Call)
    }
    if PRICE_OWNERSHIP_GUARD_FUNCTION not in called:
        yield ArchitectureViolation(
            "UNOWNED_PRICE_SOURCE_ADOPTED",
            relative,
            scope.lineno,
            f"{function_name}() reads a resource price without asking "
            f"{PRICE_OWNERSHIP_GUARD_FUNCTION}(), so a number the norm card carries would "
            "count as operator money and the ценовая база the operator chose would never be asked",
        )
    spelled = {
        node.value
        for node in ast.walk(scope)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    } | {node.id for node in ast.walk(scope) if isinstance(node, ast.Name)}
    if not spelled & PRICE_OWNERSHIP_UNOWNED_TOKENS:
        yield ArchitectureViolation(
            "UNOWNED_PRICE_SOURCE_ADOPTED",
            relative,
            scope.lineno,
            f"{function_name}() no longer returns the labelled card-price source, so the "
            "label the readiness state, the price gaps and the confirmed/preliminary split "
            "key on would be dropped",
        )


def _norm_card_proof_violations(relative: str, tree: ast.AST) -> Iterable[ArchitectureViolation]:
    """Task 2026-09-30 § 3: a chosen шифр cannot be priced without its own card being shown.

    Three links of one seam.  The sheet pass asks; the proof module states the missing fact
    without choosing a norm; the delivery facts are read out of the rendered text.  Dropping
    any of them silently returns build 929, where 125 pointers, 3 complete cards and 0 native
    reads produced money for 15 norms nobody had read (B0: 6 of 7, B1: 9 of 11).
    """

    if relative == NORM_PROOF_CHAT_MODULE:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called = {_call_name(item).split(".")[-1] for item in ast.walk(node)
                      if isinstance(item, ast.Call)}
            if not all(name in called for name in NORM_PROOF_ASK_NEIGHBOURS):
                continue
            missing = [name for name in NORM_PROOF_REQUIRED_CALLS if name not in called]
            if missing:
                yield ArchitectureViolation(
                    "NORM_CHOICE_PRICED_WITHOUT_CARD_PROOF",
                    relative,
                    node.lineno,
                    f"{node.name}() admits model decisions without asking for the proof of the "
                    f"chosen norm cards ({', '.join(missing)} is not called), so a шифр taken "
                    "from an inventory pointer would be priced as if its card had been read",
                )
        verdict_assignments = [
            item for item in ast.walk(tree)
            if isinstance(item, (ast.Assign, ast.AugAssign))
            and any(isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == NORM_PROOF_VERDICT_FIELD
                    for target in ([item.target] if isinstance(item, ast.AugAssign)
                                   else item.targets))
        ]
        if not any(NORM_PROOF_VERDICT_SOURCE in
                   {getattr(name, "id", "") for name in ast.walk(item.value)}
                   for item in verdict_assignments):
            yield ArchitectureViolation(
                "NORM_CHOICE_PRICED_WITHOUT_CARD_PROOF",
                relative,
                (verdict_assignments[0].lineno if verdict_assignments else 1),
                f"no `{NORM_PROOF_VERDICT_FIELD}` verdict is derived from "
                f"`{NORM_PROOF_VERDICT_SOURCE}`, so a row that names a шифр without citing any "
                "card keeps no verdict at all and is still priced for a card nobody showed "
                "(measured on installed 930: 15 of 17 БАП rows)",
            )
        return
    if relative == NORM_PROOF_SERVICE_MODULE:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name == NORM_PROOF_MESSAGE_FUNCTION:
                literals = {item.value for item in ast.walk(node)
                            if isinstance(item, ast.Constant) and isinstance(item.value, str)}
                if not any(NORM_PROOF_READ_TOOL in text for text in literals):
                    yield ArchitectureViolation(
                        "NORM_CHOICE_PRICED_WITHOUT_CARD_PROOF",
                        relative,
                        node.lineno,
                        f"{NORM_PROOF_MESSAGE_FUNCTION}() no longer names the {NORM_PROOF_READ_TOOL} "
                        "operation, so the proof request could only be answered by guessing "
                        "another norm instead of reading the cited one",
                    )
                asked = {_call_name(item).split(".")[-1] for item in ast.walk(node)
                         if isinstance(item, ast.Call)}
                if NORM_PROOF_UNREAD_ROWS_FUNCTION not in asked:
                    yield ArchitectureViolation(
                        "NORM_CHOICE_PRICED_WITHOUT_CARD_PROOF",
                        relative,
                        node.lineno,
                        f"{NORM_PROOF_MESSAGE_FUNCTION}() no longer walks "
                        f"{NORM_PROOF_UNREAD_ROWS_FUNCTION}(), so a row that named a шифр without "
                        "citing any card was left out of the proof request and kept its price",
                    )
            if node.name == NORM_PROOF_UNREAD_ROWS_FUNCTION:
                literals = {item.value for item in ast.walk(node)
                            if isinstance(item, ast.Constant) and isinstance(item.value, str)}
                if "card_body_shown" not in literals:
                    yield ArchitectureViolation(
                        "NORM_CHOICE_PRICED_WITHOUT_CARD_PROOF",
                        relative,
                        node.lineno,
                        f"{NORM_PROOF_UNREAD_ROWS_FUNCTION}() stopped reading `card_body_shown`, "
                        "so the debt would be judged by presence in the retrieval list rather "
                        "than by the body that was delivered",
                    )
            if node.name == NORM_PROOF_UNREAD_FUNCTION:
                called = {_call_name(item).split(".")[-1] for item in ast.walk(node)
                          if isinstance(item, ast.Call)}
                if NORM_PROOF_UNREAD_ROWS_FUNCTION not in called:
                    yield ArchitectureViolation(
                        "NORM_CHOICE_PRICED_WITHOUT_CARD_PROOF",
                        relative,
                        node.lineno,
                        f"{NORM_PROOF_UNREAD_FUNCTION}() no longer judges debt through "
                        f"{NORM_PROOF_UNREAD_ROWS_FUNCTION}(), so rows that name a шифр without "
                        "a cited ref would silently drop out of the proof request",
                    )
        return
    if relative == DELIVERY_FACTS_MODULE:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != DELIVERY_FACTS_FUNCTION:
                continue
            names = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
            literals = {item.value for item in ast.walk(node)
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)}
            missing = [token for token in DELIVERY_FACTS_REQUIRED_REFS
                       if token not in names and not any(token in text for text in literals)]
            if missing:
                yield ArchitectureViolation(
                    "NORM_CHOICE_PRICED_WITHOUT_CARD_PROOF",
                    relative,
                    node.lineno,
                    f"{DELIVERY_FACTS_FUNCTION}() no longer derives delivery from the rendered "
                    f"text ({', '.join(missing)}), so a pointer line could be reported as a "
                    "shown card and an unread norm could reach the calculator with a green fact",
                )
        return


def _python_violations(root: Path, path: Path, text: str) -> Iterable[ArchitectureViolation]:
    relative = _relative(root, path)
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError:
        return

    yield from _adr16_violations(relative, tree)
    yield from _document_lineage_violations(relative, tree)
    yield from _continuation_lineage_violations(relative, tree)
    yield from _basis_carrier_violations(relative, tree)
    yield from _document_basis_violations(relative, tree)
    yield from _lsr_basis_notice_violations(relative, tree)
    yield from _basis_refusal_violations(relative, tree)
    yield from _accrual_label_violations(relative, tree)
    yield from _norm_card_proof_violations(relative, tree)
    yield from _book_price_unit_violations(relative, tree)
    yield from _price_ownership_violations(relative, tree)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    if relative == "proxy/services/chat_evidence_application_service.py":
        for function in (
            item
            for item in ast.walk(tree)
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "parse_model_rag_result"
        ):
            for call in (item for item in ast.walk(function) if isinstance(item, ast.Call)):
                if _call_name(call).startswith("re."):
                    yield ArchitectureViolation(
                        "MODEL_RESULT_REGEX",
                        relative,
                        call.lineno,
                        "model result decoder must not interpret the answer with regex",
                    )
    scopes: dict[int, ast.AST] = {}
    for call in (item for item in ast.walk(tree) if isinstance(item, ast.Call)):
        scope = _function_scope(call, parents)
        scopes[id(scope)] = scope
    for scope in scopes.values():
        if _has_workbook_call(scope) and _has_language_matcher(scope):
            yield ArchitectureViolation(
                "FORCED_WORKBOOK_CALL",
                relative,
                getattr(scope, "lineno", 1),
                "language matching and workbook invocation share one function",
            )

    for node in ast.walk(tree):
        if (
            relative in _PROVIDER_NEUTRAL_MODEL_PATHS
            and isinstance(node, (ast.Compare, ast.MatchValue))
            and _enclosing_class_name(node, parents) != "LegacyConnectionImporter"
        ):
            engine_names = _engine_name_literals(node)
            if engine_names:
                yield ArchitectureViolation(
                    "ENGINE_NAME_ROUTING",
                    relative,
                    getattr(node, "lineno", 1),
                    "provider-neutral model path branches on engine name "
                    + ", ".join(sorted(engine_names)),
                )

        if isinstance(node, (ast.Name, ast.Constant)):
            value = node.id if isinstance(node, ast.Name) else node.value
            if isinstance(value, str) and _PARALLEL_WORKBOOK_RE.fullmatch(value):
                yield ArchitectureViolation(
                    "PARALLEL_WORKBOOK_TOOL",
                    relative,
                    getattr(node, "lineno", 1),
                    f"parallel workbook tool name {value!r}",
                )

        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        short_name = name.split(".")[-1]
        if short_name == "activate_profile_revision" and relative not in _ACTIVATION_BOUNDARIES:
            yield ArchitectureViolation(
                "IMPLICIT_PROFILE_ACTIVATION",
                relative,
                node.lineno,
                "profile activation outside the explicit profile boundary",
            )

        function = _function_scope(node, parents)
        call_text = " ".join(
            [_string_value(arg) for arg in node.args]
            + [_string_value(keyword.value) for keyword in node.keywords]
        ).lower()
        is_http_post = short_name in {"post", "urlopen"}
        if is_http_post and _calls_model_endpoint(call_text):
            function_name = _enclosing_function_name(node, parents)
            if (
                (relative, function_name) not in INFERENCE_CALLSITE_BASELINE
                and not _contains_context_governor(function)
            ):
                yield ArchitectureViolation(
                    "INFERENCE_GOVERNOR_BYPASS",
                    relative,
                    node.lineno,
                    f"direct model HTTP call in {function_name}()",
                )


def _markdown_violations(root: Path, path: Path, text: str) -> Iterable[ArchitectureViolation]:
    relative = _relative(root, path)
    if relative.startswith("docs/archive/"):
        return
    for line_number, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        has_fixture_label = any(word in lowered for word in ("synthetic", "fixture", "mock"))
        has_live_claim = "live model quality" in lowered or "live acceptance" in lowered
        has_success_claim = any(word in lowered for word in ("accepted", "passed", "green", "зелён"))
        if has_fixture_label and has_live_claim and has_success_claim:
            yield ArchitectureViolation(
                "FAKE_LIVE_ACCEPTANCE",
                relative,
                line_number,
                "synthetic or fixture evidence labelled as passing live acceptance",
            )


def scan_architecture(root: Path) -> list[ArchitectureViolation]:
    """Scan tracked implementation/docs without reading runtime data or secrets."""
    root = root.resolve()
    violations: list[ArchitectureViolation] = []
    for path in _tracked_sources(root):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".py":
            violations.extend(_python_violations(root, path, text))
        elif path.suffix.lower() == ".md":
            violations.extend(_markdown_violations(root, path, text))
    return sorted(violations, key=lambda item: (item.path, item.line, item.code))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check canonical LES architecture boundaries")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    violations = scan_architecture(args.root)
    for item in violations:
        print(f"{item.code} {item.path}:{item.line} {item.detail}")
    return 1 if violations else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
