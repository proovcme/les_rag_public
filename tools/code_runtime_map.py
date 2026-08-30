"""Build a conservative, machine-generated map of the LES Python runtime.

The map answers "what can we prove from the repository?".  It deliberately does
not call an unreferenced module dead: dynamic imports, subprocess entrypoints and
external integrations require a human check before deletion.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Iterable


SCHEMA = "les.code-runtime-map.v1"
PRODUCT_ENTRYPOINTS = (
    "proxy_server.py",
    "sovushka_ng.py",
    "mlx_host.py",
    "lemonade_host.py",
)
FOCUS_MODULES = ("proxy/smeta_core/document_workflow.py",)
ROUTE_METHODS = {"delete", "get", "head", "options", "patch", "post", "put"}


def _tracked_python_files(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    tracked = (line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip())
    return sorted(path for path in tracked if (root / path).is_file())


def _module_name(path: str) -> str:
    pure = PurePosixPath(path)
    parts = list(pure.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_for(path: str) -> str:
    module = _module_name(path)
    if path.endswith("/__init__.py"):
        return module
    return module.rpartition(".")[0]


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _resolve_candidate(name: str, known_modules: set[str]) -> str | None:
    candidate = name
    while candidate:
        if candidate in known_modules:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def _resolve_from_base(node: ast.ImportFrom, package: str) -> str:
    if not node.level:
        return node.module or ""
    parts = package.split(".") if package else []
    remove = max(node.level - 1, 0)
    if remove:
        parts = parts[:-remove] if remove <= len(parts) else []
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(part for part in parts if part)


def _imports_for(tree: ast.AST, path: str, known_modules: set[str]) -> set[str]:
    imports: set[str] = set()
    package = _package_for(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _resolve_candidate(alias.name, known_modules)
                if resolved:
                    imports.add(resolved)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from_base(node, package)
            for alias in node.names:
                candidate = f"{base}.{alias.name}" if base else alias.name
                resolved = _resolve_candidate(candidate, known_modules) or _resolve_candidate(base, known_modules)
                if resolved:
                    imports.add(resolved)
    return imports


def _reachable(roots: Iterable[str], graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    queue = deque(sorted(set(roots)))
    while queue:
        module = queue.popleft()
        if module in seen or module not in graph:
            continue
        seen.add(module)
        queue.extend(sorted(graph[module] - seen))
    return seen


def _parent_packages(module: str, known_modules: set[str]) -> set[str]:
    """Return package initializers Python executes before importing a module."""
    parts = module.split(".")
    return {".".join(parts[:index]) for index in range(1, len(parts)) if ".".join(parts[:index]) in known_modules}


def _join_route(prefix: str, route: str) -> str:
    value = "/" + "/".join(part for part in (prefix, route) for part in part.split("/") if part)
    return value if value != "" else "/"


def _router_prefixes(tree: ast.AST) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        targets: list[ast.expr] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        if not isinstance(value, ast.Call):
            continue
        function = value.func
        name = function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else ""
        if name not in {"APIRouter", "FastAPI"}:
            continue
        prefix = ""
        for keyword in value.keywords:
            if keyword.arg == "prefix":
                prefix = _literal_string(keyword.value) or "<dynamic>"
        for target in targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix
    return prefixes


def _routes_for(tree: ast.AST, path: str) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    prefixes = _router_prefixes(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.lower()
            owner = decorator.func.value
            if method not in ROUTE_METHODS or not isinstance(owner, ast.Name) or owner.id not in prefixes:
                continue
            route = _literal_string(decorator.args[0]) if decorator.args else ""
            routes.append(
                {
                    "method": method.upper(),
                    "path": _join_route(prefixes[owner.id], route or ""),
                    "handler": node.name,
                    "source": path,
                }
            )
    return routes


def _imported_symbol_consumers(
    trees: dict[str, ast.AST], module_to_path: dict[str, str], focus_module: str
) -> dict[str, list[str]]:
    consumers: dict[str, set[str]] = defaultdict(set)
    focus_name = _module_name(focus_module)
    for consumer_path, tree in trees.items():
        package = _package_for(consumer_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if _resolve_from_base(node, package) != focus_name:
                continue
            for alias in node.names:
                if alias.name != "*":
                    consumers[alias.name].add(consumer_path)
    return {name: sorted(paths) for name, paths in sorted(consumers.items())}


def _explicit_runtime_modules(root: Path, module_to_path: dict[str, str]) -> set[str]:
    manifest_path = root / "config" / "windows_runtime_manifest.json"
    if not manifest_path.exists():
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = {str(path).replace("\\", "/") for path in manifest.get("include_files", [])}
    return {module for module, path in module_to_path.items() if path in paths}


def build_inventory(root: Path) -> dict:
    root = root.resolve()
    paths = _tracked_python_files(root)
    module_to_path = {_module_name(path): path for path in paths}
    path_to_module = {path: module for module, path in module_to_path.items()}
    known_modules = set(module_to_path)
    trees: dict[str, ast.AST] = {}
    parse_warnings: list[dict[str, str]] = []
    line_counts: dict[str, int] = {}
    for path in paths:
        source = (root / path).read_text(encoding="utf-8-sig")
        line_counts[path] = len(source.splitlines())
        try:
            trees[path] = ast.parse(source, filename=path)
        except SyntaxError as exc:
            parse_warnings.append({"path": path, "error": f"{exc.msg} (line {exc.lineno})"})

    graph: dict[str, set[str]] = {module: set() for module in known_modules}
    for path, tree in trees.items():
        module = path_to_module[path]
        graph[module] = _imports_for(tree, path, known_modules) | _parent_packages(module, known_modules)

    product_roots = [path_to_module[path] for path in PRODUCT_ENTRYPOINTS if path in path_to_module]
    product_reachable = _reachable(product_roots, graph)
    test_roots = [module for module, path in module_to_path.items() if path.startswith("tests/")]
    test_reachable = _reachable(test_roots, graph)
    explicit_runtime = _explicit_runtime_modules(root, module_to_path)
    inbound: dict[str, set[str]] = {module: set() for module in known_modules}
    for source, targets in graph.items():
        for target in targets:
            inbound[target].add(source)

    modules: list[dict] = []
    counts: dict[str, int] = defaultdict(int)
    for path in paths:
        module = path_to_module[path]
        if module in product_reachable:
            status = "PRODUCT_REACHABLE"
        elif module in explicit_runtime:
            status = "RUNTIME_SUPPORT"
        elif (
            path.startswith(("tests/", "tools/", "scripts/", "legacy/scripts/"))
            or PurePosixPath(path).name.startswith("test_")
            or module in test_reachable
        ):
            status = "TEST_OR_TOOL_ONLY"
        else:
            status = "DORMANT_CANDIDATE"
        counts[status] += 1
        modules.append(
            {
                "path": path,
                "module": module,
                "status": status,
                "lines": line_counts[path],
                "inbound": sorted(module_to_path[item] for item in inbound[module]),
                "outbound": sorted(module_to_path[item] for item in graph[module]),
                "windows_runtime_explicit": module in explicit_runtime,
            }
        )

    routes: list[dict[str, str]] = []
    for module in sorted(product_reachable):
        path = module_to_path[module]
        tree = trees.get(path)
        if tree is not None:
            routes.extend(_routes_for(tree, path))
    routes.sort(key=lambda item: (item["path"], item["method"], item["source"], item["handler"]))

    focus: dict[str, dict] = {}
    for path in FOCUS_MODULES:
        if path not in path_to_module:
            continue
        module_record = next(item for item in modules if item["path"] == path)
        focus[path] = {
            "status": module_record["status"],
            "lines": module_record["lines"],
            "direct_importers": module_record["inbound"],
            "symbols": _imported_symbol_consumers(trees, module_to_path, path),
        }

    return {
        "schema": SCHEMA,
        "summary": {
            "tracked_python_files": len(paths),
            "tracked_python_lines": sum(line_counts.values()),
            "product_reachable": counts["PRODUCT_REACHABLE"],
            "runtime_support": counts["RUNTIME_SUPPORT"],
            "test_or_tool_only": counts["TEST_OR_TOOL_ONLY"],
            "dormant_candidates": counts["DORMANT_CANDIDATE"],
            "registered_api_routes": len(routes),
            "parse_warnings": len(parse_warnings),
        },
        "entrypoints": list(PRODUCT_ENTRYPOINTS),
        "routes": routes,
        "modules": modules,
        "focus": focus,
        "warnings": parse_warnings,
    }


def _markdown_table(headers: list[str], rows: Iterable[Iterable[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |" for row in rows)
    return lines


def render_markdown(inventory: dict) -> str:
    summary = inventory["summary"]
    modules = inventory["modules"]
    lines = [
        "# Карта исполняемого кода ЛЕС",
        "",
        "> Сгенерировано `tools/code_runtime_map.py`. Не редактировать вручную.",
        "",
        "Это консервативная статическая карта импортов и зарегистрированных FastAPI-маршрутов. "
        "Статус `DORMANT_CANDIDATE` означает только отсутствие доказанного пути от продуктовых entrypoint, "
        "явного runtime-helper или теста; он **не является доказательством мёртвого кода**.",
        "",
        "Полный построчный inventory находится в `docs/generated/code_runtime_map.json`.",
        "",
        "## Статусы",
        "",
    ]
    lines.extend(
        _markdown_table(
            ["Статус", "Что доказано"],
            [
                ("PRODUCT_REACHABLE", "Есть статический путь от боевой точки входа"),
                ("RUNTIME_SUPPORT", "Явно перечислен как отдельный helper Windows runtime"),
                ("TEST_OR_TOOL_ONLY", "Тест, служебный скрипт или достигается только из такого кода"),
                ("DORMANT_CANDIDATE", "Статический потребитель не найден; требуется ручная проверка"),
            ],
        )
    )
    lines.extend([
        "",
        "## Сводка",
        "",
    ])
    lines.extend(
        _markdown_table(
            ["Метрика", "Значение"],
            [
                ("Python-файлов под git", summary["tracked_python_files"]),
                ("Строк Python", summary["tracked_python_lines"]),
                ("PRODUCT_REACHABLE", summary["product_reachable"]),
                ("RUNTIME_SUPPORT", summary["runtime_support"]),
                ("TEST_OR_TOOL_ONLY", summary["test_or_tool_only"]),
                ("DORMANT_CANDIDATE", summary["dormant_candidates"]),
                ("Зарегистрированных API-маршрутов", summary["registered_api_routes"]),
                ("Ошибок разбора", summary["parse_warnings"]),
            ],
        )
    )
    lines.extend(["", "## Крупнейшие продуктовые модули", ""])
    largest = sorted(
        (item for item in modules if item["status"] == "PRODUCT_REACHABLE"),
        key=lambda item: (-item["lines"], item["path"]),
    )[:30]
    lines.extend(_markdown_table(["Файл", "Строк", "Прямых потребителей"], ((m["path"], m["lines"], len(m["inbound"])) for m in largest)))

    lines.extend(["", "## Сметный монолит: фактические потребители", ""])
    for path, details in inventory["focus"].items():
        lines.extend([f"### `{path}`", "", f"Статус: `{details['status']}`; строк: {details['lines']}.", ""])
        rows = []
        for symbol, consumers in details["symbols"].items():
            rows.append((f"`{symbol}`", "<br>".join(f"`{consumer}`" for consumer in consumers)))
        lines.extend(_markdown_table(["Импортируемый символ", "Потребители"], rows or [("—", "—")]))

    lines.extend(["", "## Кандидаты на проверку", ""])
    dormant = [item for item in modules if item["status"] == "DORMANT_CANDIDATE"]
    lines.extend(
        _markdown_table(
            ["Файл", "Строк", "Почему только кандидат"],
            ((item["path"], item["lines"], "Нет доказанного статического пути; проверить dynamic/subprocess/external use") for item in dormant),
        )
        if dormant
        else ["Кандидатов нет."]
    )
    lines.extend(["", "## Ограничения", "", "- Карта видит обычные Python-импорты и декораторы `APIRouter`, но не доказывает фактическую частоту вызова.", "- Строковые импорты, plugin discovery, subprocess и внешние entrypoint требуют ручной проверки.", "- Удаление возможно только после отдельного поиска потребителей, теста и проверки установленного Windows runtime.", ""])
    return "\n".join(lines)


def _render_json(inventory: dict) -> str:
    return json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_or_check(root: Path, *, check: bool) -> int:
    inventory = build_inventory(root)
    outputs = {
        root / "docs" / "CODE_RUNTIME_MAP.md": render_markdown(inventory),
        root / "docs" / "generated" / "code_runtime_map.json": _render_json(inventory),
    }
    stale: list[str] = []
    for path, content in outputs.items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(root).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    if stale:
        print("Runtime map is stale: " + ", ".join(stale))
        return 1
    if not check:
        print(f"Generated runtime map: {inventory['summary']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated maps differ from the repository")
    args = parser.parse_args()
    return _write_or_check(Path(__file__).resolve().parents[1], check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
