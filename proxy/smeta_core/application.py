"""Public application boundary for every LES estimate workflow.

Callers enter the smeta module here.  The model owns decomposition, norm and
resource decisions; the functions below only connect that model-owned result to
typed validation, calculation, revision persistence and rendering.

``estimate_harness_service`` is still used behind this boundary while its tool
loop is being split into smaller services.  It is an implementation adapter,
not a second application entrypoint.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


SMETA_APPLICATION_ID = "smeta_application_v1"
_RIM_SESSION_STORE: Any | None = None


def run_smeta_workflow(
    question: str,
    complete: Callable[[list[dict[str, str]]], str],
    *,
    max_steps: int = 16,
) -> dict[str, Any]:
    """Run the model-first smeta tool loop through one public boundary."""
    from proxy.services.estimate_harness_service import run_estimate_harness

    result = run_estimate_harness(question, complete, max_steps=max_steps)
    if isinstance(result, dict):
        result.setdefault("application", SMETA_APPLICATION_ID)
    return result


def calculate_visible_rows(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Calculate rows whose professional decisions were already supplied."""
    from proxy.smeta_core.workflow import calculate_visible_rows as calculate

    return calculate(*args, **kwargs)


def calculate_visible_rows_revision(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Calculate and persist an immutable model/user-owned revision."""
    from proxy.smeta_core.workflow import calculate_visible_rows_revision as calculate

    return calculate(*args, **kwargs)


def finalize_estimate_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply the shared evidence/finality contract without changing decisions."""
    from proxy.smeta_core.workflow import finalize_estimate_result as finalize

    return finalize(*args, **kwargs)


def get_rim_session_store():
    """Return the process-local handle for the persistent RIM session registry."""
    global _RIM_SESSION_STORE
    if _RIM_SESSION_STORE is None:
        from proxy.smeta_core.rim_session import RimSessionStore

        root = Path(os.getenv("LES_RIM_SESSION_ROOT", "storage/rim_sessions"))
        _RIM_SESSION_STORE = RimSessionStore(root)
    return _RIM_SESSION_STORE


def set_rim_session_store(store: Any | None) -> None:
    """Test/application-factory hook; production callers use the default store."""
    global _RIM_SESSION_STORE
    _RIM_SESSION_STORE = store
