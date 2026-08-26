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
    "/api/chat",
    "/api/generate",
    "/v1/chat/completions",
    "/v1/responses",
)
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
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and _call_name(node) in {
            "re.search",
            "re.match",
            "re.fullmatch",
            "re.compile",
        }:
            return True
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
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


def _python_violations(root: Path, path: Path, text: str) -> Iterable[ArchitectureViolation]:
    relative = _relative(root, path)
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError:
        return

    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
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
        if is_http_post and any(marker in call_text for marker in _MODEL_ENDPOINT_MARKERS):
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
