"""Seed Revit family guide sources into LES ARTEL_Index."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from textwrap import dedent
from typing import Any


DEFAULT_PROXY_URL = "http://127.0.0.1:8050"
DEFAULT_TARGET_NAME = "revit_family_creation_guide_autodesk_2017.pdf"
REQUIREMENTS_NAME = "revit_family_quality_requirements_autodesk_2017.md"


QUALITY_REQUIREMENTS_MARKDOWN = dedent(
    """
    # ARTEL Revit Family Requirements And Quality Basis

    Source title: Руководство по созданию семейств Autodesk Revit
    Source URL: https://www.autodesk.com/akn-aknsite-article-attachments/1858ea62-e6ba-4782-a7d6-aca350219b7c.pdf
    Source version: 1.02
    Source year/place: Москва 2017
    Product: ARTEL
    Document type: FAMILY_GUIDE
    Purpose: operational requirements for creating, reviewing and accepting Revit RFA families.

    ## Retrieval Hints

    ARTEL Revit family requirements RFA качество семейства создание семейств
    проверка семейств требования к семействам опорные плоскости каркас семейства
    параметры типа параметры экземпляра общие параметры ФОП shared parameters
    ADSK_Наименование ADSK_Обозначение ADSK_Код изделия типоразмер каталог
    LOD уровень детализации подкатегории материалы формулы вложенные семейства
    точка вставки точка расчета помещения technical description validation checklist.

    ## LES Usage Contract

    Use this source when ARTEL needs to produce or review a Revit family task,
    family specification, acceptance checklist, validation report, catalog card,
    FOP/shared-parameter comparison, or quality explanation. Pair it with
    `FOP_PROFILE` chunks for exact ADSK names and GUIDs.

    ## Requirements

    ### ARF-SCOPE-001 Family Purpose

    A family must have a defined usage purpose, category, project stage, LOD
    target, and expected schedule/tag behavior before modeling starts.
    Evidence: task/specification states category, family name, use case, LOD,
    discipline, required parameters and acceptance checks.

    ### ARF-TEMPLATE-001 Template And Category

    A loadable family must start from the correct Revit family template and
    category. The category controls behavior, available parameters, graphics,
    scheduling and interaction with the project.
    Evidence: selected `.rft` template and category are recorded in the task.

    ### ARF-SKELETON-001 Reference Skeleton

    The family skeleton must be built with reference planes and reference lines
    before detailed geometry. Parameters should drive the skeleton, and the
    skeleton should drive geometry and symbolic graphics.
    Evidence: key dimensions flex by moving reference planes/lines without
    breaking constraints.

    ### ARF-ORIGIN-001 Insertion And Room Behavior

    Origin, insertion point, host behavior and room calculation point must be
    deliberate. Families that belong to rooms or room boundaries must be checked
    for correct room association.
    Evidence: loaded family inserts in the expected position and reports room
    relation correctly where relevant.

    ### ARF-GEOM-001 Reasonable Geometry

    Geometry must be sufficient for the task and not excessive. Avoid hidden
    internals, unnecessary threads, small chamfers, over-detailed fittings and
    manufacturing detail unless explicitly required.
    Evidence: family file size and view behavior remain appropriate for project
    use.

    ### ARF-DETAIL-001 Detail Levels

    Low, medium and high detail levels must be controlled intentionally. Large
    elements can appear broadly; small or detailed geometry should appear only
    where it is useful.
    Evidence: plan, section, elevation and 3D views display correctly at all
    target detail levels.

    ### ARF-GRAPHICS-001 Symbolic Graphics

    Plan symbols should use symbolic/detail/annotation graphics where that is
    lighter and clearer than model geometry.
    Evidence: plans are readable and do not rely on heavy 3D geometry for simple
    symbols.

    ### ARF-SUBCATEGORY-001 Subcategories

    Subcategories must be used deliberately so project teams can control object
    graphics. Do not create random or duplicate subcategories.
    Evidence: technical description lists subcategories and their intended use.

    ### ARF-PARAM-001 Parameter Intent

    Separate type parameters, instance parameters, shared parameters and internal
    family parameters. Family-only parameters are suitable for internal geometry
    and graphics; shared parameters are required for schedules, tags and
    cross-project exchange.
    Evidence: parameter list marks type/instance behavior and shared/FOP status.

    ### ARF-FOP-001 Shared Parameter Profile

    Required ADSK/shared parameters must be checked against the indexed FOP
    profile before acceptance. Use `FOP_PROFILE` for exact GUID, datatype,
    visibility and user-modifiable flags.
    Evidence: validation report lists required ADSK parameters and whether each
    parameter is present, correctly typed and populated.

    ### ARF-FORMULA-001 Formula Minimalism

    Formulas, arrays and voids must be kept to the minimum needed for stable
    behavior. Excessive formulas and arrays increase maintenance and performance
    risk.
    Evidence: parameter flex tests pass and formulas remain readable.

    ### ARF-NESTED-001 Nested Families

    Nested families should be used only when a component is genuinely reusable or
    must be counted/tagged independently. Large numbers of nested families are a
    performance and maintainability risk.
    Evidence: nested components have a documented reason.

    ### ARF-CATALOG-001 Type Catalogs

    Families with many type sizes should use a type catalog instead of bloating
    the family with embedded types.
    Evidence: type catalog exists when the type set is large and loading only
    needed types is expected.

    ### ARF-MATERIAL-001 Materials

    Materials and material parameters must be intentional. When project teams
    control appearance by category/subcategory, document that behavior instead of
    hardcoding unnecessary materials.
    Evidence: material behavior is described and schedule/tag needs are met.

    ### ARF-VALIDATION-001 Acceptance Testing

    A family is not accepted until it opens, loads, flexes, displays, schedules
    and tags correctly for the target workflow.
    Evidence: validation report includes open/load test, parameter flex test,
    view/detail test, schedule/tag/shared-parameter test and known limitations.

    ### ARF-DOC-001 Technical Description

    Accepted families need a technical description: purpose, LOD, display
    behavior, parameters, subcategories, type catalog behavior, usage notes and
    known limitations.
    Evidence: catalog card or technical description is attached to the accepted
    learning case.

    ### ARF-VERSION-001 Change And Versioning

    Family changes must preserve traceability: version, author/reviewer role,
    reason for change, validation result and compatibility notes.
    Evidence: catalog/learning case records version and acceptance notes.

    ## ARTEL Quality Checklist

    - Correct template and category selected.
    - Family purpose, LOD, discipline and project stage are explicit.
    - Reference skeleton exists and flexes.
    - Geometry is constrained to the skeleton.
    - Detail levels and symbolic graphics are checked.
    - Type and instance parameters are separated.
    - Shared parameters are verified against FOP_PROFILE.
    - Materials and subcategories are intentional.
    - Type catalog is used for large type sets.
    - Family opens, loads and inserts without blocking warnings.
    - Tags and schedules return expected values.
    - File size and nested/formula complexity are reasonable.
    - Technical description and validation report are attached.

    ## Reject Patterns

    - Unclear family category or wrong template.
    - Geometry controlled by loose dimensions instead of a reference skeleton.
    - Excessive high-detail geometry for ordinary project use.
    - Heavy 3D geometry used for simple plan symbols.
    - Missing shared parameters required by the task/FOP.
    - Large embedded type list where a type catalog is expected.
    - Unexplained nested families, voids, arrays or formulas.
    - No parameter flex test.
    - No schedule/tag validation.
    - No technical description or acceptance notes.

    ## ARTEL Workflow

    1. Read the task and retrieve `FAMILY_GUIDE` chunks for methodology.
    2. Retrieve `FOP_PROFILE` chunks for exact shared parameter names and GUIDs.
    3. Produce a family specification with template, category, LOD, geometry,
       parameters, validation checks and catalog metadata.
    4. Validate the resulting RFA against this checklist.
    5. Save accepted results as `LEARNING_CASE` so LES improves future work.
    """
).strip() + "\n"


def _target_dir(runtime_root: Path) -> Path:
    return runtime_root / "RAG_Content" / "ARTEL" / "family_guides"


def write_family_guide(guide_pdf: Path, runtime_root: Path, target_name: str = DEFAULT_TARGET_NAME) -> list[Path]:
    if not guide_pdf.is_file():
        raise FileNotFoundError(f"guide PDF not found: {guide_pdf}")
    target_dir = _target_dir(runtime_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_target = target_dir / target_name
    requirements_target = target_dir / REQUIREMENTS_NAME
    shutil.copy2(guide_pdf, pdf_target)
    requirements_target.write_text(QUALITY_REQUIREMENTS_MARKDOWN, encoding="utf-8")
    return [pdf_target, requirements_target]


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
        if any("family_guides/" in str(chunk.get("doc_name", "")) for chunk in chunks):
            return last
        time.sleep(poll_sec)
    raise RuntimeError(f"ARTEL family guide search did not return family_guides after {timeout_sec:.0f}s: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Revit family guide and ARTEL quality requirements into LES.")
    parser.add_argument("--guide-pdf", type=Path, required=True, help="Path to the Revit family creation guide PDF.")
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd(), help="LES runtime root that owns RAG_Content.")
    parser.add_argument("--target-name", default=DEFAULT_TARGET_NAME, help="PDF file name under RAG_Content/ARTEL/family_guides.")
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL, help="LES proxy URL.")
    parser.add_argument("--api-key", default=os.getenv("LES_ADMIN_KEY", ""), help="LES admin API key; localhost trusted access can omit it.")
    parser.add_argument("--no-sync", action="store_true", help="Only write files; do not call LES sync.")
    parser.add_argument("--verify-search", action="store_true", help="Poll /api/search until family_guides chunks are returned.")
    parser.add_argument("--timeout-sec", type=float, default=180.0)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    args = parser.parse_args()

    written = write_family_guide(args.guide_pdf, args.runtime_root, args.target_name)
    for target in written:
        print(f"written={target}")

    if not args.no_sync:
        sync_result = sync_artel(args.proxy_url, api_key=args.api_key)
        print("sync=" + json.dumps(sync_result, ensure_ascii=False, sort_keys=True))

    if args.verify_search:
        query = "ARTEL требования качество Revit семейство опорные плоскости FOP shared parameters validation"
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
