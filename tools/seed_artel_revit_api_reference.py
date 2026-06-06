"""Seed Revit API reference notes into LES ARTEL_Index."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from textwrap import dedent
from typing import Any


DEFAULT_PROXY_URL = "http://127.0.0.1:8050"
REFERENCE_NAME = "revit_api_family_automation_reference.md"


REVIT_API_REFERENCE_MARKDOWN = dedent(
    """
    # ARTEL Revit API Reference

    Product: ARTEL
    Document type: REVIT_API_REFERENCE
    Purpose: operational Revit API basis for automated RFA/template inspection,
    family creation, validation and catalog JSON extraction.

    ## Sources

    - Autodesk Revit API Developer Guide, Family Documents:
      https://help.autodesk.com/cloudhelp/2018/CHS/Revit-API/files/GUID-DC143EB8-43CB-48AB-938E-7ADE3A9D2E63.htm
    - Autodesk Revit API Developer Guide, Managing family types and parameters:
      https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Revit_Geometric_Elements/Family_Documents/Revit_API_Revit_API_Developers_Guide_Revit_Geometric_Elements_Family_Documents_Managing_family_types_and_parameters_html.html
    - RVTDocs Revit API 2026:
      https://rvtdocs.com/2026/
    - RevitAPIDocs Revit API 2026:
      https://www.revitapidocs.com/2026/

    ## Retrieval Hints

    Revit API ARTEL RFA FamilyManager FamilyParameter FamilyType FamilySymbol
    FamilyInstance FamilyCategory OwnerFamily IsFamilyDocument NewFamilyDocument
    OpenDocumentFile EditFamily LoadFamily IFamilyLoadOptions FilteredElementCollector
    Transaction TransactionGroup SubTransaction ExternalCommandData UIApplication
    UIDocument Document Element Parameter StorageType BuiltInParameter
    BuiltInCategory shared parameters ExternalDefinition GUID ConnectorManager
    MEPModel Connector subcategories Materials template extractor JSON.

    ## LES Usage Contract

    Use this source when ARTEL needs to write, review or debug:

    - Revit add-in commands;
    - batch extraction of `.rfa` and `.rft` metadata;
    - family/template JSON catalogs;
    - family validation reports;
    - FOP/shared-parameter checks;
    - Revit API implementation plans for Windows/Legion.

    Pair with `FAMILY_GUIDE` for modeling/quality methodology and with
    `FOP_PROFILE` for exact shared-parameter names, GUIDs and datatypes.

    ## Runtime Boundary

    Native Revit API extraction normally requires Autodesk Revit on Windows.
    Direct `.rfa`/`.rft` introspection without Revit is limited because family
    files are proprietary Revit documents, not an open JSON/SQLite format.
    Acceptable automation paths:

    1. Local Revit add-in or external command on Legion.
    2. RevitCoreConsole where the target workflow is supported.
    3. Autodesk Platform Services Design Automation for Revit.
    4. No-Revit filesystem manifest only: path, file name, size, modified time,
       template folder and naming signals.

    ## Entry Points

    ### External Command

    `IExternalCommand.Execute(ExternalCommandData commandData, ref string message,
    ElementSet elements)` is the common add-in command entry point.

    Access chain:

    - `commandData.Application` -> `UIApplication`;
    - `UIApplication.ActiveUIDocument` -> `UIDocument`;
    - `UIDocument.Document` -> active `Document`;
    - `UIApplication.Application` -> Revit application object for opening or
      creating documents.

    ARTEL rule: Revit add-in calls ARTEL backend. The backend calls LES. Revit
    should not call OpenRouter or LES directly in MVP.

    ### Document Opening And Creation

    For existing `.rfa` files use application-level document opening, then close
    the document after extraction.

    For new family creation use `Application.NewFamilyDocument(templatePath)` with
    an explicit `.rft` template. Record the template path in task/catalog JSON.

    For an already loaded project family use `Document.EditFamily(family)` to get
    a family document, then `LoadFamily()` to reload after edits when needed.

    Always check `Document.IsFamilyDocument` before using family-only APIs.

    ## Family Document Model

    `Document.OwnerFamily` represents the family in an open family document.
    `OwnerFamily.FamilyCategory` gives the Revit category that controls behavior,
    scheduling, graphics and available built-in parameters.

    Important extract fields:

    - `family_name`;
    - `family_category`;
    - `category_id`;
    - `is_work_plane_based`;
    - `template_path`;
    - `family_symbols`;
    - `family_types`;
    - `family_parameters`;
    - `nested_family_symbols`;
    - `subcategories`;
    - `materials`;
    - `connectors`;
    - `warnings`.

    ## FamilyManager

    `Document.FamilyManager` is the central API for family types and family
    parameters.

    Use it to inspect:

    - `FamilyManager.Types`;
    - `FamilyManager.CurrentType`;
    - `FamilyManager.Parameters` or `GetParameters()`;
    - parameter formula;
    - parameter group;
    - type-vs-instance behavior;
    - shared parameter status.

    Use it to modify:

    - `NewType(typeName)`;
    - `DeleteCurrentType()`;
    - `Set(FamilyParameter, value)`;
    - add/remove family parameters;
    - add/remove shared parameters;
    - formulas and ordering.

    ARTEL rule: any edit must be inside a transaction and followed by a flex/load
    validation step before the family is accepted.

    ## Parameters

    Parameter extraction must preserve both API identity and human labels.

    For ordinary element parameters:

    - `Parameter.Definition.Name`;
    - `Parameter.StorageType`;
    - `Parameter.AsString()`;
    - `Parameter.AsValueString()`;
    - `Parameter.AsDouble()`;
    - `Parameter.AsInteger()`;
    - `Parameter.AsElementId()`;
    - `Parameter.IsReadOnly`;
    - built-in parameter id when present.

    For family parameters:

    - name;
    - datatype/spec;
    - parameter group;
    - type or instance flag;
    - formula;
    - reporting flag;
    - shared flag;
    - GUID for shared parameters when accessible.

    ARTEL rule: compare required shared parameters against indexed `FOP_PROFILE`.
    The validation report must list missing, wrong-type and mismatched-GUID
    parameters separately.

    ## Collectors

    `FilteredElementCollector` is the primary way to enumerate elements in a
    Revit document.

    Efficient collector rules:

    - use `OfClass()` or `OfCategory()` first;
    - use `WhereElementIsNotElementType()` for instances;
    - use `WhereElementIsElementType()` for types;
    - use `ToElementIds()` when only ids are needed;
    - use `FirstElement()` when only one element is needed;
    - avoid materializing every element when count or ids are enough.

    Common ARTEL collectors:

    - `FamilySymbol` for loaded/nested symbols;
    - `FamilyInstance` for instances in test projects;
    - `Material` for material catalog;
    - `GraphicsStyle` for subcategories;
    - `FillPatternElement` and line styles for graphics checks;
    - MEP connector-bearing instances for connector validation.

    ## Transactions

    Revit model changes must run inside `Transaction`.

    Patterns:

    - `Transaction` for a single edit;
    - `SubTransaction` for scoped rollback inside a larger edit;
    - `TransactionGroup` for multi-step operations and one undo item;
    - rollback on validation failure;
    - never leave an open transaction after an exception.

    Extraction-only commands should not start transactions unless they need to
    create a temporary type, set temporary parameter values, or run a flex test.

    ## Loading And Reloading Families

    When editing a project family:

    1. Get `Family` from `FamilySymbol.Family`.
    2. Open family document via `Document.EditFamily(family)`.
    3. Edit inside a transaction.
    4. Use `LoadFamily(projectDocument, IFamilyLoadOptions)` to reload.
    5. Close the family document.

    `IFamilyLoadOptions` should make overwrite behavior explicit. ARTEL should
    record whether parameter values are overwritten during validation.

    ## MEP Connectors

    MEP families may expose connectors through `MEPModel.ConnectorManager` or a
    connector manager on the relevant instance/type API surface.

    Extract:

    - connector domain;
    - shape;
    - direction;
    - system type;
    - diameter/height/width;
    - origin and coordinate system;
    - flow-related settings where applicable.

    ARTEL rule: connector validation is required for families expected to connect
    to ducts, pipes, cable trays, conduits or equipment systems.

    ## Template JSON Extractor Shape

    A Revit-backed extractor should emit one JSON object per `.rfa` or `.rft`:

    ```json
    {
      "schema": "artel.revit_family_catalog.v1",
      "source_path": "C:/ProgramData/Autodesk/RVT 2026/Family Templates/...",
      "file_kind": "rft",
      "revit_version": "2026",
      "family_name": "Metric Generic Model",
      "category": "Generic Models",
      "template_path": "...",
      "parameters": [
        {
          "name": "ADSK_Наименование",
          "storage_type": "String",
          "is_shared": true,
          "guid": "..."
        }
      ],
      "types": [],
      "subcategories": [],
      "materials": [],
      "connectors": [],
      "warnings": []
    }
    ```

    JSON should be stable and diff-friendly:

    - sort arrays by name where possible;
    - store raw Revit ids only as diagnostics;
    - keep user-visible names;
    - normalize units deliberately;
    - preserve source file path and modified timestamp.

    ## Batch Extraction Algorithm

    1. Build a filesystem manifest of `.rfa` and `.rft` roots.
    2. Start Revit/API host once per batch, not once per file.
    3. Open each document read-only where possible.
    4. Detect `IsFamilyDocument`; skip or mark unsupported files.
    5. Extract category, types, parameters, symbols, materials, subcategories and
       connectors.
    6. Write one JSON file per source plus a run summary.
    7. Close every document without saving unless the task explicitly edits.
    8. Import JSON summaries into LES as ARTEL knowledge and accepted catalog
       evidence.

    ## Quality Checks For API Output

    Reject or flag extractor output when:

    - file failed to open;
    - document is not a family document;
    - category is missing or unexpected;
    - required FOP parameters are absent;
    - shared parameter GUID differs from FOP;
    - no type exists where type catalog is not used;
    - connector family has no connectors;
    - extraction emitted unstable ordering;
    - warning list contains load/blocking failures.

    ## Implementation Notes For ARTEL

    - Keep extraction separate from generation.
    - Keep validation reports as first-class artifacts.
    - Do not hide Revit API errors behind generic AI text.
    - Preserve source file paths for traceability.
    - Convert successful extractor output into `LEARNING_CASE` or catalog JSON
      only after review.
    - Use LES retrieval before drafting code: `REVIT_API_REFERENCE` for API,
      `FAMILY_GUIDE` for family methodology, `FOP_PROFILE` for parameters.
    """
).strip() + "\n"


def _target_dir(runtime_root: Path) -> Path:
    return runtime_root / "RAG_Content" / "ARTEL" / "revit_api"


def write_revit_api_reference(runtime_root: Path, target_name: str = REFERENCE_NAME) -> Path:
    target_dir = _target_dir(runtime_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / target_name
    target.write_text(REVIT_API_REFERENCE_MARKDOWN, encoding="utf-8")
    return target


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None, api_key: str = "") -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {body}") from exc


def sync_artel(proxy_url: str, api_key: str = "") -> dict[str, Any]:
    return _request_json("POST", f"{proxy_url.rstrip('/')}/api/rag/sync/ARTEL", api_key=api_key)


def search_artel(proxy_url: str, query: str, api_key: str = "") -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{proxy_url.rstrip('/')}/api/search",
        {"query": query, "dataset_filter": "ARTEL", "top_k": 8, "include_trace": True},
        api_key=api_key,
    )


def wait_for_search(proxy_url: str, query: str, timeout_sec: float, poll_sec: float, api_key: str = "") -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        last = search_artel(proxy_url, query, api_key=api_key)
        chunks = last.get("chunks") or []
        if any("revit_api/" in str(chunk.get("doc_name", "")) for chunk in chunks):
            return last
        time.sleep(poll_sec)
    raise RuntimeError(f"ARTEL Revit API search did not return revit_api after {timeout_sec:.0f}s: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed ARTEL Revit API reference into LES ARTEL_Index.")
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd(), help="LES runtime root that owns RAG_Content.")
    parser.add_argument("--target-name", default=REFERENCE_NAME, help="Markdown file name under RAG_Content/ARTEL/revit_api.")
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL, help="LES proxy URL.")
    parser.add_argument("--api-key", default=os.getenv("LES_ADMIN_KEY", ""), help="LES admin API key; localhost trusted access can omit it.")
    parser.add_argument("--no-sync", action="store_true", help="Only write files; do not call LES sync.")
    parser.add_argument("--verify-search", action="store_true", help="Poll /api/search until revit_api chunks are returned.")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    args = parser.parse_args()

    target = write_revit_api_reference(args.runtime_root, args.target_name)
    print(f"written={target}")

    if not args.no_sync:
        sync_result = sync_artel(args.proxy_url, api_key=args.api_key)
        print("sync=" + json.dumps(sync_result, ensure_ascii=False, sort_keys=True))

    if args.verify_search:
        query = "ARTEL Revit API FamilyManager FilteredElementCollector NewFamilyDocument FOP shared parameters"
        search_result = wait_for_search(
            args.proxy_url,
            query,
            timeout_sec=args.timeout_sec,
            poll_sec=args.poll_sec,
            api_key=args.api_key,
        )
        print("search_count=" + str(search_result.get("count", 0)))
        first = (search_result.get("chunks") or [{}])[0]
        print("first_doc=" + str(first.get("doc_name", "")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
