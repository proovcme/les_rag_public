"""Unified product entry point for LES datasets and their documents."""
from __future__ import annotations

from nicegui import context

from sovushka.pages.documents import build_documents
from sovushka.pages.samovar import build_samovar


def requested_dataset_id() -> str:
    """Return the explicit dataset selection without depending on a live request in tests."""
    try:
        return str(context.client.request.query_params.get("dataset_id") or "").strip()
    except (AttributeError, RuntimeError):
        return ""


def build_data_workspace(*, is_admin: bool) -> dict[str, list[object]]:
    """Build one data destination; catalog and file detail are two levels of it."""
    dataset_id = requested_dataset_id()
    if dataset_id:
        build_documents(
            surface="data",
            initial_dataset_id=dataset_id,
            show_dataset_picker=False,
            can_manage=is_admin,
        )
        return {"timers": []}
    return build_samovar(
        can_manage=is_admin,
        open_tab="data",
        workspace_title="Данные",
    )
