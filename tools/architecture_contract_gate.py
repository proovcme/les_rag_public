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

# A rate that nobody chose may still be calculated, but only under the label the
# readiness state, the price gaps and the confirmed/preliminary split key on.
# Dropping that label would silently return the defect ADR-16 § 7 closes: a
# norm-card number counted as a confirmed amount of a chosen price basis.
UNOWNED_PRICE_SOURCES = {
    # PriceTrace source token -> the action label that must accompany it
    "card_price": "card_price_without_basis",
}

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


def _python_violations(root: Path, path: Path, text: str) -> Iterable[ArchitectureViolation]:
    relative = _relative(root, path)
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError:
        return

    yield from _adr16_violations(relative, tree)
    yield from _document_lineage_violations(relative, tree)
    yield from _basis_carrier_violations(relative, tree)
    yield from _accrual_label_violations(relative, tree)
    yield from _book_price_unit_violations(relative, tree)
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
