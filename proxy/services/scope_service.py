"""scope_service (v0.21) — нормализованная ОБЛАСТЬ ПОИСКА чата (Scope).

Конец путаницы «весь RAG / проект / датасет / project_id / dataset_filter». Единый Scope:
  scope_type: all | project | projects | dataset | datasets | mixed
Резолвится в resolved_dataset_ids. Старые поля (project_id/dataset_ids/dataset_filter) принимаются и
приводятся к Scope (back-compat). Project = именованная группа датасетов (НЕ папка). Dataset = источник.

Чистые функции (резолвер/опции-билдер тестируемы без БД); живые данные передаются аргументами.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

_VALID_TYPES = ("all", "project", "projects", "dataset", "datasets", "mixed")

# роли датасета в проекте (для отображения; не влияют на ретрив)
DATASET_ROLES = ("docs", "norms", "mail", "estimate", "vor", "asbuilt", "resource_workbook",
                 "reference", "unknown")


def _default_project_resolver(pid: int) -> list[str]:
    try:
        from proxy.services.project_service import project_dataset_ids
        return list(project_dataset_ids(int(pid)) or [])
    except Exception:  # noqa: BLE001
        return []


def _project_label(pid: int) -> str:
    try:
        from proxy.services.project_service import build_registry
        for p in build_registry().get("projects", []):
            if int(p.get("id", -1)) == int(pid):
                return str(p.get("name") or f"проект #{pid}")
    except Exception:  # noqa: BLE001
        pass
    return f"проект #{pid}"


def resolve_scope(*, scope: dict | None = None, project_id: int | None = None,
                  dataset_ids: list[str] | None = None, dataset_filter: str | None = None,
                  label: str | None = None,
                  project_resolver: Optional[Callable[[int], list[str]]] = None,
                  dataset_catalog: list[dict] | None = None,
                  project_label_fn: Optional[Callable[[int], str]] = None) -> dict:
    """request-поля → нормализованный Scope c resolved_dataset_ids. Явный `scope` приоритетнее legacy.
    Никогда не теряет область молча: пустой проект/нерезолвенный фильтр → warning."""
    presolve = project_resolver or _default_project_resolver
    plabel = project_label_fn or _project_label
    warnings: list[str] = []

    def _name_to_id(name: str) -> str | None:
        for d in dataset_catalog or []:
            if str(d.get("name", "")) == name or str(d.get("id", "")) == name:
                return str(d.get("id"))
        return None

    # ── 1) явный scope ────────────────────────────────────────────────────────────────────
    if isinstance(scope, dict) and scope.get("scope_type"):
        st = str(scope["scope_type"]).strip().lower()
        if st not in _VALID_TYPES:
            warnings.append(f"unknown_scope_type:{st}")
            st = "all"
        pids = [int(x) for x in (scope.get("project_ids") or []) if str(x).strip()]
        dids = [str(x) for x in (scope.get("dataset_ids") or []) if str(x).strip()]
        source = "ui_scope"
    else:
        # ── 2) legacy-поля → Scope ──────────────────────────────────────────────────────────
        pids, dids = [], []
        if dataset_ids:
            dids = [str(x) for x in dataset_ids if str(x).strip()]
            st, source = ("dataset" if len(dids) == 1 else "datasets"), "legacy_dataset_ids"
        elif project_id and int(project_id) > 0:
            pids = [int(project_id)]
            st, source = "project", "legacy_project_id"
        elif dataset_filter and dataset_filter.strip() and dataset_filter != "(все датасеты)":
            did = _name_to_id(dataset_filter)
            if did:
                dids = [did]
                st, source = "dataset", "legacy_dataset_filter"
            else:
                st, source = "all", "legacy_dataset_filter"
                warnings.append(f"dataset_filter_unresolved:{dataset_filter}")
        else:
            st, source = "all", "default_all"

    # ── резолв в dataset_ids ────────────────────────────────────────────────────────────────
    resolved: list[str] = []
    if st in ("project", "projects", "mixed"):
        for pid in pids:
            pd = presolve(pid)
            if not pd:
                warnings.append(f"project_without_datasets:{pid}")
            resolved.extend(pd)
    if st in ("dataset", "datasets", "mixed"):
        resolved.extend(dids)
    resolved = list(dict.fromkeys(resolved))   # дедуп, порядок

    # ── label ───────────────────────────────────────────────────────────────────────────────
    if label:
        lbl = label
    elif st == "all":
        lbl = "Весь RAG"
    elif st == "project" and pids:
        lbl = plabel(pids[0])
    elif st == "projects":
        lbl = f"{len(pids)} проекта · {len(resolved)} датасетов"
    elif st == "dataset" and dids:
        lbl = _catalog_name(dids[0], dataset_catalog) or dids[0]
    elif st == "datasets":
        lbl = f"{len(dids)} датасета"
    elif st == "mixed":
        lbl = f"{len(pids)} проект(ов) + {len(dids)} датасет(ов)"
    else:
        lbl = "Весь RAG"

    return {
        "scope_type": st, "project_ids": pids, "dataset_ids": dids,
        "resolved_dataset_ids": resolved, "label": lbl, "source": source, "warnings": warnings,
    }


def _catalog_name(did: str, catalog: list[dict] | None) -> str | None:
    for d in catalog or []:
        if str(d.get("id", "")) == did:
            return str(d.get("name") or did)
    return None


# ── /api/scope/options builder (чистый — живые данные передаём аргументами) ────────────────

# датасеты, которые помечаем как системные/служебные (не скрываем — отдельная группа + reason)
_SYSTEM_HINTS = ("_shard_", "speckle", "revit-api", "cad_bim", "fop20", "system", "_tmp", "scratch")


def _is_system_dataset(name: str, did: str) -> str | None:
    n = (name or "").lower() + " " + (did or "").lower()
    for h in _SYSTEM_HINTS:
        if h in n:
            return f"служебный ({h})"
    return None


def scope_options(datasets: list[dict], projects: list[dict],
                  project_links: dict[int, list[str]]) -> dict:
    """Все датасеты + проекты → группы для ScopeSelector. Админский датасет ОБЯЗАН быть здесь.
    datasets: [{id,name,source_type?,file_count?,sidecar_status?,...}]; projects: [{id,name,aliases?}];
    project_links: {project_id: [dataset_id,...]}. Ничего не скрывает молча."""
    ds_by_id: dict[str, dict] = {}
    assigned: set[str] = set()
    for pid, dids in (project_links or {}).items():
        for d in dids:
            assigned.add(str(d))
    out_ds: list[dict] = []
    system_ds: list[dict] = []
    for d in datasets or []:
        did = str(d.get("id"))
        name = str(d.get("name") or did)
        pids = [int(pid) for pid, dids in (project_links or {}).items() if did in [str(x) for x in dids]]
        rec = {
            "id": did, "name": name,
            "source_type": d.get("source_type") or d.get("origin") or "unknown",
            "file_count": d.get("file_count", d.get("files", d.get("document_count", 0))),
            "sidecar_status": d.get("sidecar_status", "unknown"),
            "lexical_status": d.get("lexical_status", "unknown"),
            "qdrant_status": d.get("qdrant_status", d.get("chunk_count", 0) and "indexed" or "unknown"),
            "project_ids": pids,
        }
        sysreason = _is_system_dataset(name, did)
        ds_by_id[did] = rec
        if sysreason:
            rec["hidden_reason"] = sysreason
            system_ds.append(rec)
        else:
            out_ds.append(rec)

    proj_out: list[dict] = []
    for p in projects or []:
        pid = int(p.get("id", -1))
        dids = [str(x) for x in (project_links or {}).get(pid, [])]
        roles = sorted({str(ds_by_id.get(d, {}).get("source_type", "unknown")) for d in dids}) or []
        warn = ["project_without_datasets"] if not dids else []
        proj_out.append({
            "id": pid, "name": str(p.get("name") or f"проект #{pid}"),
            "aliases": p.get("aliases") or [], "dataset_count": len(dids),
            "dataset_ids": dids, "dataset_roles": roles, "warnings": warn,
        })

    unassigned = [r for r in out_ds if str(r["id"]) not in assigned]
    return {
        "all": {"scope_type": "all", "label": "Весь RAG"},
        "projects": proj_out,
        "datasets": out_ds,
        "unassigned_datasets": unassigned,
        "system_datasets": system_ds,
        "counts": {
            "datasets_total": len(out_ds) + len(system_ds),
            "datasets_assigned": len([r for r in out_ds if str(r["id"]) in assigned]),
            "datasets_unassigned": len(unassigned),
            "datasets_system": len(system_ds),
            "projects_total": len(proj_out),
            "projects_with_datasets": len([p for p in proj_out if p["dataset_count"] > 0]),
            "projects_without_datasets": len([p for p in proj_out if p["dataset_count"] == 0]),
        },
    }
