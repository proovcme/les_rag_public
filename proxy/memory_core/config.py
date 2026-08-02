"""Runtime configuration contract for Memory Core.

Environment variables are explicit operator locks.  Otherwise root-admin
settings persisted in MetaDB become effective after a controlled restart.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from proxy.memory_core.contracts import MemoryMode, SmetaRecallMode
from proxy.memory_core.store import MemoryStore


@dataclass(frozen=True)
class MemoryConfig:
    mode: MemoryMode = MemoryMode.OFF
    smeta_capture: bool = True
    smeta_recall: SmetaRecallMode = SmetaRecallMode.OFF
    sources: dict[str, str] | None = None


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def load_memory_config(store: MemoryStore) -> MemoryConfig:
    saved = store.get_config()
    sources: dict[str, str] = {}

    def configured(key: str, env_key: str, default: str) -> str:
        # Root-admin GUI values are explicit operator choices and must be able
        # to override the shipped environment default after a restart.
        if key in saved:
            sources[key] = "metadb"
            return saved[key]
        if env_key in os.environ:
            sources[key] = "environment"
            return os.environ[env_key]
        sources[key] = "default"
        return default

    raw_mode = configured("mode", "LES_MEMORY_MODE", MemoryMode.OFF.value).strip().casefold()
    raw_recall = configured(
        "smeta_recall", "LES_MEMORY_SMETA_RECALL", SmetaRecallMode.OFF.value
    ).strip().casefold()
    raw_capture = configured("smeta_capture", "LES_MEMORY_SMETA_CAPTURE", "true")
    try:
        mode = MemoryMode(raw_mode)
    except ValueError:
        mode = MemoryMode.OFF
    try:
        recall = SmetaRecallMode(raw_recall)
    except ValueError:
        recall = SmetaRecallMode.OFF
    if mode != MemoryMode.ON:
        recall = SmetaRecallMode.OFF
    return MemoryConfig(
        mode=mode,
        smeta_capture=_bool(raw_capture, True),
        smeta_recall=recall,
        sources=sources,
    )


def update_memory_config(store: MemoryStore, *, mode: str, smeta_capture: bool, smeta_recall: str) -> None:
    parsed_mode = MemoryMode(mode.strip().casefold())
    parsed_recall = SmetaRecallMode(smeta_recall.strip().casefold())
    store.set_config({
        "mode": parsed_mode.value,
        "smeta_capture": "true" if smeta_capture else "false",
        "smeta_recall": parsed_recall.value,
    })
