"""Persistent, immutable chat profile revisions.

The installed Windows runtime is replaceable while MetaDB is persistent.  This
module therefore owns operator-created prompt, skill and profile revisions in
SQLite and binds each chat session to an exact embedded snapshot.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.rag_config import rag_meta_db_path


SCHEMA = "les.chat_profiles.v1"
PROFILE_MODES = ("search", "agent", "estimator", "engineer")
MODE_LABELS = {
    "search": "Поиск",
    "agent": "Агент",
    "estimator": "Сметчик",
    "engineer": "Инженер",
}
MODE_ALIASES = {
    "search": "search",
    "rag": "search",
    "agent": "agent",
    "text": "agent",
    "free": "agent",
    "auto": "agent",
    "estimator": "estimator",
    "smeta": "estimator",
    "smeta_harness": "estimator",
    "engineer": "engineer",
    "review": "engineer",
    "doc_review": "engineer",
    "normcontrol": "engineer",
}


def canonical_profile_mode(mode: str | None) -> str:
    """Return a canonical explicit profile id; Agent is the safe default."""

    return MODE_ALIASES.get(str(mode or "").strip().casefold(), "agent")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _db_path(db_path: str | Path | None) -> Path:
    path = Path(db_path) if db_path is not None else Path(rag_meta_db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect(db_path: str | Path | None) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(db_path))
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    _seed_factory(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS les_prompt_revisions (
            revision_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            revision_no INTEGER NOT NULL,
            text_value TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            is_factory INTEGER NOT NULL DEFAULT 0,
            source_revision_id TEXT,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS les_skill_revisions (
            revision_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            revision_no INTEGER NOT NULL,
            text_value TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            is_factory INTEGER NOT NULL DEFAULT 0,
            source_revision_id TEXT,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS les_profile_revisions (
            revision_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            name TEXT NOT NULL,
            revision_no INTEGER NOT NULL,
            prompt_revision_id TEXT NOT NULL,
            skill_revision_id TEXT NOT NULL,
            tools_json TEXT NOT NULL,
            model_policy_json TEXT NOT NULL,
            rag_policy_json TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            is_factory INTEGER NOT NULL DEFAULT 0,
            source_revision_id TEXT,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS les_active_profiles (
            mode TEXT PRIMARY KEY,
            profile_revision_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS les_chat_profile_bindings (
            session_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            profile_revision_id TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            bound_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )


def _factory_contracts() -> dict[str, dict[str, Any]]:
    from proxy.services.prompt_registry_service import (
        build_factory_mode_system_prompt,
        normcontrol_role_pack,
        rag_search_role_pack,
    )
    from proxy.services.tool_harness_service import harness

    registered = {item["name"] for item in harness().registry()["tools"]}
    search_tools = [
        name
        for name in (
            "dataset_map",
            "search_sources",
            "read_source",
            "read_pdf_source",
            "look_at_pdf_page",
            "read_excel_source",
            "search_project_tables",
            "read_project_table",
            "assemble_project_volume",
        )
        if name in registered
    ]
    agent_tools = sorted(registered)
    estimator_tools = [
        name
        for name in (
            "dataset_map",
            "search_sources",
            "read_source",
            "read_excel_source",
            "search_project_tables",
            "read_project_table",
            "build_lsr_workbook",
            "build_vor_workbook",
        )
        if name in registered
    ]
    engineer_tools = [
        name
        for name in (
            "dataset_map",
            "search_sources",
            "read_source",
            "read_pdf_source",
            "look_at_pdf_page",
            "search_project_tables",
            "read_project_table",
        )
        if name in registered
    ]
    return {
        "search": {
            "prompt": build_factory_mode_system_prompt("rag"),
            "skill": "# Итеративный поиск\n\n```json\n" + json.dumps(
                rag_search_role_pack(), ensure_ascii=False, indent=2
            ) + "\n```",
            "tools": search_tools,
            "model_policy": {"temperature": 0.1},
            "rag_policy": {"grounded": True, "iterative": True},
        },
        "agent": {
            "prompt": build_factory_mode_system_prompt(
                "rag",
                extra=(
                    "Ты универсальный агент ЛЕС. Сам выбирай последовательность доступных "
                    "инструментов, но профессиональные выводы формулируй сам по evidence."
                ),
            ),
            "skill": (
                "# Универсальный агент\n\n"
                "1. Определи результат, который нужен пользователю.\n"
                "2. Используй только разрешённые профилем инструменты.\n"
                "3. Отделяй источники, вычисления, допущения и недостающие данные.\n"
                "4. Не выполняй действие с побочным эффектом без подтверждения."
            ),
            "tools": agent_tools,
            "model_policy": {"temperature": 0.2},
            "rag_policy": {"grounded": True, "iterative": True},
        },
        "estimator": {
            "prompt": build_factory_mode_system_prompt(
                "rag",
                extra=(
                    "Работай как опытный инженер-сметчик. Подбирай нормы и аналоги только "
                    "по найденным карточкам выбранных датасетов. Сверяй измеритель и состав "
                    "работ, отделяй подтверждённое от допущений и не выдумывай шифры."
                ),
            ),
            "skill": (
                "# Сметчик по обычному RAG\n\n"
                "1. Разложи запрос на самостоятельные работы и объёмы.\n"
                "2. Через общий native RRF найди карточки норм в выбранной сметной базе.\n"
                "3. При необходимости используй `search_sources` и `read_source` повторно, "
                "пока не проверены шифр, измеритель и состав работ.\n"
                "4. Для каждой позиции покажи норму, обоснование, ограничения и пробелы.\n"
                "5. Не подменяй неподтверждённую норму похожим кодом и не рассчитывай цену "
                "без ценовых evidence.\n"
                "6. Если оператор просит готовый файл ЛСР (xlsx сметы) по вложению PDF/XLSX — "
                "вызови `build_lsr_workbook` с `attachment_id`. Не составляй расценённую таблицу "
                "вручную и не выдумывай цены: файл пишет код существующего document workflow.\n"
                "7. Если оператор просит ВОР / ведомость объёмов работ как xlsx без расценки — "
                "вызови `build_vor_workbook`. Не путай с ЛСР: ВОР — объёмы, ЛСР — расценка кодом."
            ),
            "tools": estimator_tools,
            "model_policy": {"temperature": 0.0},
            "rag_policy": {"grounded": True, "system_datasets": ["smeta"]},
        },
        "engineer": {
            "prompt": build_factory_mode_system_prompt("review"),
            "skill": "# Инженерная проверка\n\n```json\n" + json.dumps(
                normcontrol_role_pack(), ensure_ascii=False, indent=2
            ) + "\n```",
            "tools": engineer_tools,
            "model_policy": {"temperature": 0.1},
            "rag_policy": {"grounded": True, "require_citations": True},
        },
    }


def _seed_factory(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT COUNT(*) FROM les_profile_revisions WHERE is_factory=1"
    ).fetchone()[0]
    if existing == len(PROFILE_MODES):
        return
    contracts = _factory_contracts()
    created = _now()
    for mode in PROFILE_MODES:
        contract = contracts[mode]
        prompt_id = f"factory:prompt:{mode}:base"
        skill_id = f"factory:skill:{mode}:base"
        profile_id = f"factory:profile:{mode}:base"
        prompt_text = str(contract["prompt"]).strip()
        skill_text = str(contract["skill"]).strip()
        conn.execute(
            """INSERT OR IGNORE INTO les_prompt_revisions
               (revision_id,name,revision_no,text_value,sha256,is_factory,created_at)
               VALUES(?,?,?,?,?,1,?)""",
            (prompt_id, f"{MODE_LABELS[mode]} · Base", 1, prompt_text, _sha(prompt_text), created),
        )
        conn.execute(
            """INSERT OR IGNORE INTO les_skill_revisions
               (revision_id,name,revision_no,text_value,sha256,is_factory,created_at)
               VALUES(?,?,?,?,?,1,?)""",
            (skill_id, f"{MODE_LABELS[mode]} · Base", 1, skill_text, _sha(skill_text), created),
        )
        snapshot = _make_snapshot(
            revision_id=profile_id,
            mode=mode,
            name=f"{MODE_LABELS[mode]} · Base",
            revision_no=1,
            prompt_revision_id=prompt_id,
            prompt_text=prompt_text,
            skill_revision_id=skill_id,
            skill_text=skill_text,
            tools=list(contract["tools"]),
            model_policy=dict(contract["model_policy"]),
            rag_policy=dict(contract["rag_policy"]),
            is_factory=True,
            created_at=created,
        )
        conn.execute(
            """INSERT OR IGNORE INTO les_profile_revisions
               (revision_id,mode,name,revision_no,prompt_revision_id,skill_revision_id,
                tools_json,model_policy_json,rag_policy_json,snapshot_json,is_factory,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,1,?)""",
            (
                profile_id,
                mode,
                snapshot["name"],
                1,
                prompt_id,
                skill_id,
                _json(snapshot["tools"]),
                _json(snapshot["model_policy"]),
                _json(snapshot["rag_policy"]),
                _json(snapshot),
                created,
            ),
        )
        conn.execute(
            """INSERT OR IGNORE INTO les_active_profiles(mode,profile_revision_id,updated_at)
               VALUES(?,?,?)""",
            (mode, profile_id, created),
        )
    conn.commit()


def _make_snapshot(
    *,
    revision_id: str,
    mode: str,
    name: str,
    revision_no: int,
    prompt_revision_id: str,
    prompt_text: str,
    skill_revision_id: str,
    skill_text: str,
    tools: list[str],
    model_policy: dict[str, Any],
    rag_policy: dict[str, Any],
    is_factory: bool,
    created_at: str,
) -> dict[str, Any]:
    return {
        "schema": "les.chat_profile_snapshot.v1",
        "revision_id": revision_id,
        "mode": mode,
        "label": MODE_LABELS[mode],
        "name": name,
        "revision_no": revision_no,
        "prompt_revision_id": prompt_revision_id,
        "prompt_text": prompt_text,
        "prompt_sha256": _sha(prompt_text),
        "skill_revision_id": skill_revision_id,
        "skill_text": skill_text,
        "skill_sha256": _sha(skill_text),
        "tools": list(dict.fromkeys(tools)),
        "model_policy": model_policy,
        "rag_policy": rag_policy,
        "is_factory": bool(is_factory),
        "created_at": created_at,
    }


def _text_table(kind: str) -> str:
    if kind == "prompt":
        return "les_prompt_revisions"
    if kind == "skill":
        return "les_skill_revisions"
    raise ValueError(f"Неизвестный тип редакции: {kind}")


def _text_revision(conn: sqlite3.Connection, kind: str, revision_id: str) -> sqlite3.Row:
    table = _text_table(kind)
    row = conn.execute(
        f"SELECT * FROM {table} WHERE revision_id=? AND deleted_at IS NULL",  # noqa: S608
        (revision_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Редакция {kind} не найдена: {revision_id}")
    return row


def _tool_names() -> set[str]:
    from proxy.services.tool_harness_service import harness

    return {str(item["name"]) for item in harness().registry()["tools"]}


def publish_text_revision(
    kind: str,
    *,
    name: str,
    text: str,
    source_revision_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    value = str(text or "").strip()
    title = str(name or "").strip()
    if not title:
        raise ValueError("Название редакции не задано")
    if not value:
        raise ValueError("Текст редакции не может быть пустым")
    table = _text_table(kind)
    with _connect(db_path) as conn:
        if source_revision_id:
            _text_revision(conn, kind, source_revision_id)
        revision_no = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) + 1  # noqa: S608
        revision_id = f"user:{kind}:{uuid4()}"
        created = _now()
        conn.execute(
            f"""INSERT INTO {table}
                (revision_id,name,revision_no,text_value,sha256,is_factory,source_revision_id,created_at)
                VALUES(?,?,?,?,?,0,?,?)""",  # noqa: S608
            (revision_id, title, revision_no, value, _sha(value), source_revision_id, created),
        )
        conn.commit()
    return {
        "revision_id": revision_id,
        "name": title,
        "revision_no": revision_no,
        "text": value,
        "sha256": _sha(value),
        "is_factory": False,
        "source_revision_id": source_revision_id,
        "created_at": created,
    }


def publish_profile_revision(
    *,
    mode: str,
    name: str,
    prompt_revision_id: str,
    skill_revision_id: str,
    tools: list[str],
    model_policy: dict[str, Any] | None,
    rag_policy: dict[str, Any] | None,
    source_revision_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    canonical = canonical_profile_mode(mode)
    title = str(name or "").strip()
    if not title:
        raise ValueError("Название версии профиля не задано")
    selected_tools = list(dict.fromkeys(str(item).strip() for item in tools if str(item).strip()))
    unknown = sorted(set(selected_tools) - _tool_names())
    if unknown:
        raise ValueError("Неизвестные инструменты: " + ", ".join(unknown))
    with _connect(db_path) as conn:
        prompt = _text_revision(conn, "prompt", prompt_revision_id)
        skill = _text_revision(conn, "skill", skill_revision_id)
        if source_revision_id:
            source = conn.execute(
                "SELECT mode FROM les_profile_revisions WHERE revision_id=? AND deleted_at IS NULL",
                (source_revision_id,),
            ).fetchone()
            if source is None:
                raise ValueError("Исходная версия профиля не найдена")
            if source["mode"] != canonical:
                raise ValueError("Исходная версия относится другому режиму")
        revision_no = int(conn.execute(
            "SELECT COUNT(*) FROM les_profile_revisions WHERE mode=?", (canonical,)
        ).fetchone()[0]) + 1
        revision_id = f"user:profile:{canonical}:{uuid4()}"
        created = _now()
        snapshot = _make_snapshot(
            revision_id=revision_id,
            mode=canonical,
            name=title,
            revision_no=revision_no,
            prompt_revision_id=prompt_revision_id,
            prompt_text=prompt["text_value"],
            skill_revision_id=skill_revision_id,
            skill_text=skill["text_value"],
            tools=selected_tools,
            model_policy=dict(model_policy or {}),
            rag_policy=dict(rag_policy or {}),
            is_factory=False,
            created_at=created,
        )
        conn.execute(
            """INSERT INTO les_profile_revisions
               (revision_id,mode,name,revision_no,prompt_revision_id,skill_revision_id,
                tools_json,model_policy_json,rag_policy_json,snapshot_json,is_factory,
                source_revision_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (
                revision_id,
                canonical,
                title,
                revision_no,
                prompt_revision_id,
                skill_revision_id,
                _json(selected_tools),
                _json(model_policy or {}),
                _json(rag_policy or {}),
                _json(snapshot),
                source_revision_id,
                created,
            ),
        )
        conn.commit()
    return snapshot


def activate_profile_revision(
    mode: str,
    revision_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    canonical = canonical_profile_mode(mode)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT mode,snapshot_json FROM les_profile_revisions WHERE revision_id=? AND deleted_at IS NULL",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Версия профиля не найдена")
        if row["mode"] != canonical:
            raise ValueError("Версия профиля относится другому режиму")
        conn.execute(
            """INSERT INTO les_active_profiles(mode,profile_revision_id,updated_at)
               VALUES(?,?,?) ON CONFLICT(mode) DO UPDATE SET
               profile_revision_id=excluded.profile_revision_id,updated_at=excluded.updated_at""",
            (canonical, revision_id, _now()),
        )
        conn.commit()
    return _loads(row["snapshot_json"], {})


def _profile_snapshot(conn: sqlite3.Connection, revision_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT snapshot_json FROM les_profile_revisions WHERE revision_id=? AND deleted_at IS NULL",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Версия профиля не найдена")
    snapshot = _loads(row["snapshot_json"], {})
    if not isinstance(snapshot, dict) or not snapshot.get("prompt_text") or not snapshot.get("skill_text"):
        raise ValueError("Snapshot профиля повреждён")
    return snapshot


def ensure_estimator_workbook_profile(
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Add LSR/VOR file tools to an already-seeded estimator profile once.

    Factory Base is immutable. Existing MetaDB therefore gets a user revision;
    fresh installs already have the tools in factory seed and only record the
    migration as already present.
    """

    from proxy.services.smeta_workbook_tools import (
        ESTIMATOR_SKILL_WORKBOOK_APPENDIX,
        LSR_TOOL,
        VOR_TOOL,
    )

    migration_key = "estimator_workbook_tools_v1"
    needed_tools = (LSR_TOOL, VOR_TOOL)
    with _connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS les_profile_migrations (
                   migration_key TEXT PRIMARY KEY,
                   result_json TEXT NOT NULL,
                   created_at TEXT NOT NULL
               )"""
        )
        previous = conn.execute(
            "SELECT result_json FROM les_profile_migrations WHERE migration_key=?",
            (migration_key,),
        ).fetchone()
        if previous is not None:
            result = _loads(previous["result_json"], {})
            return {**result, "status": "already_applied"}
        active = conn.execute(
            "SELECT profile_revision_id FROM les_active_profiles WHERE mode=?",
            ("estimator",),
        ).fetchone()
        if active is None:
            return {"status": "no_estimator"}
        snapshot = _profile_snapshot(conn, active["profile_revision_id"])
        tools = list(snapshot.get("tools") or [])
        skill_text = str(snapshot.get("skill_text") or "")
        missing_tools = [name for name in needed_tools if name not in tools]
        need_skill = LSR_TOOL not in skill_text
        if not missing_tools and not need_skill:
            result = {
                "status": "already_present",
                "revision_id": snapshot.get("revision_id"),
            }
            conn.execute(
                "INSERT INTO les_profile_migrations(migration_key,result_json,created_at) VALUES(?,?,?)",
                (migration_key, _json(result), _now()),
            )
            conn.commit()
            return result
        prompt_revision_id = str(snapshot.get("prompt_revision_id") or "")
        skill_revision_id = str(snapshot.get("skill_revision_id") or "")
        source_revision_id = str(snapshot.get("revision_id") or "")
        model_policy = dict(snapshot.get("model_policy") or {})
        rag_policy = dict(snapshot.get("rag_policy") or {})

    if need_skill:
        skill = publish_text_revision(
            "skill",
            name="Сметчик · файлы ЛСР/ВОР",
            text=skill_text.rstrip() + ESTIMATOR_SKILL_WORKBOOK_APPENDIX,
            source_revision_id=skill_revision_id,
            db_path=db_path,
        )
        skill_revision_id = skill["revision_id"]
    profile = publish_profile_revision(
        mode="estimator",
        name="Сметчик · файлы ЛСР и ВОР",
        prompt_revision_id=prompt_revision_id,
        skill_revision_id=skill_revision_id,
        tools=tools + missing_tools,
        model_policy=model_policy,
        rag_policy=rag_policy,
        source_revision_id=source_revision_id,
        db_path=db_path,
    )
    activate_profile_revision("estimator", profile["revision_id"], db_path=db_path)
    result = {
        "status": "applied",
        "revision_id": profile["revision_id"],
        "added_tools": missing_tools,
        "skill_updated": need_skill,
    }
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO les_profile_migrations(migration_key,result_json,created_at) VALUES(?,?,?)",
            (migration_key, _json(result), _now()),
        )
        conn.commit()
    return result


def resolve_chat_profile(
    *,
    session_id: str | None,
    requested_mode: str | None,
    requested_revision_id: str | None = None,
    apply_revision: bool = False,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    import_legacy_prompt_overrides(db_path=db_path)
    ensure_estimator_workbook_profile(db_path=db_path)
    canonical = canonical_profile_mode(requested_mode)
    sid = str(session_id or "").strip()
    with _connect(db_path) as conn:
        existing = None
        if sid:
            existing = conn.execute(
                "SELECT mode,snapshot_json FROM les_chat_profile_bindings WHERE session_id=?",
                (sid,),
            ).fetchone()
        if existing is not None and existing["mode"] == canonical and not apply_revision:
            snapshot = _loads(existing["snapshot_json"], {})
            if isinstance(snapshot, dict) and snapshot.get("prompt_text") and snapshot.get("skill_text"):
                return snapshot
        revision_id = str(requested_revision_id or "").strip()
        if not revision_id:
            active = conn.execute(
                "SELECT profile_revision_id FROM les_active_profiles WHERE mode=?", (canonical,)
            ).fetchone()
            if active is None:
                raise ValueError(f"Для профиля {canonical} не назначена активная версия")
            revision_id = active["profile_revision_id"]
        snapshot = _profile_snapshot(conn, revision_id)
        if snapshot.get("mode") != canonical:
            raise ValueError("Выбранная версия относится другому режиму")
        if sid:
            now = _now()
            conn.execute(
                """INSERT INTO les_chat_profile_bindings
                   (session_id,mode,profile_revision_id,snapshot_json,bound_at,updated_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                   mode=excluded.mode,profile_revision_id=excluded.profile_revision_id,
                   snapshot_json=excluded.snapshot_json,updated_at=excluded.updated_at""",
                (sid, canonical, revision_id, _json(snapshot), now, now),
            )
            conn.commit()
        return snapshot


def delete_revision(
    kind: str,
    revision_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    table = "les_profile_revisions" if kind == "profile" else _text_table(kind)
    with _connect(db_path) as conn:
        row = conn.execute(
            f"SELECT is_factory FROM {table} WHERE revision_id=? AND deleted_at IS NULL",  # noqa: S608
            (revision_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Редакция не найдена")
        if row["is_factory"]:
            raise ValueError("Заводскую Base-версию удалить нельзя")
        if kind == "profile":
            active = conn.execute(
                "SELECT mode FROM les_active_profiles WHERE profile_revision_id=?", (revision_id,)
            ).fetchone()
            if active is not None:
                raise ValueError("Сначала назначьте другую активную версию профиля")
        deleted = _now()
        conn.execute(
            f"UPDATE {table} SET deleted_at=? WHERE revision_id=?",  # noqa: S608
            (deleted, revision_id),
        )
        conn.commit()
    return {"status": "deleted", "kind": kind, "revision_id": revision_id, "deleted_at": deleted}


def _text_items(conn: sqlite3.Connection, kind: str) -> list[dict[str, Any]]:
    table = _text_table(kind)
    rows = conn.execute(
        f"""SELECT revision_id,name,revision_no,text_value,sha256,is_factory,
                   source_revision_id,created_at FROM {table}
            WHERE deleted_at IS NULL ORDER BY is_factory DESC, revision_no, created_at"""  # noqa: S608
    ).fetchall()
    return [
        {
            "revision_id": row["revision_id"],
            "name": row["name"],
            "revision_no": row["revision_no"],
            "text": row["text_value"],
            "sha256": row["sha256"],
            "is_factory": bool(row["is_factory"]),
            "source_revision_id": row["source_revision_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def registry_snapshot(*, db_path: str | Path | None = None) -> dict[str, Any]:
    ensure_estimator_workbook_profile(db_path=db_path)
    with _connect(db_path) as conn:
        active_by_mode = {
            row["mode"]: row["profile_revision_id"]
            for row in conn.execute("SELECT mode,profile_revision_id FROM les_active_profiles")
        }
        profiles: list[dict[str, Any]] = []
        for mode in PROFILE_MODES:
            revisions = [
                _loads(row["snapshot_json"], {})
                for row in conn.execute(
                    """SELECT snapshot_json FROM les_profile_revisions
                       WHERE mode=? AND deleted_at IS NULL
                       ORDER BY is_factory DESC,revision_no,created_at""",
                    (mode,),
                )
            ]
            active_id = active_by_mode.get(mode, "")
            profiles.append(
                {
                    "mode": mode,
                    "label": MODE_LABELS[mode],
                    "active_revision_id": active_id,
                    "active": next((item for item in revisions if item.get("revision_id") == active_id), {}),
                    "revisions": revisions,
                }
            )
        return {
            "schema": SCHEMA,
            "default_mode": "agent",
            "profiles": profiles,
            "prompt_revisions": _text_items(conn, "prompt"),
            "skill_revisions": _text_items(conn, "skill"),
            "tools": __import__(
                "proxy.services.tool_harness_service", fromlist=["harness"]
            ).harness().registry()["tools"],
        }


def import_legacy_prompt_overrides(
    *,
    overrides_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Import replaceable JSON overrides once as durable user profile revisions."""

    from proxy.services import prompt_registry_service as prompts

    path = Path(overrides_path) if overrides_path is not None else prompts._PROMPT_OVERRIDES_PATH
    migration_key = "prompt_overrides_v1_to_chat_profiles_v1"
    with _connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS les_profile_migrations (
                   migration_key TEXT PRIMARY KEY,
                   result_json TEXT NOT NULL,
                   created_at TEXT NOT NULL
               )"""
        )
        previous = conn.execute(
            "SELECT result_json FROM les_profile_migrations WHERE migration_key=?",
            (migration_key,),
        ).fetchone()
        if previous is not None:
            result = _loads(previous["result_json"], {})
            return {**result, "status": "already_imported"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "no_overrides", "imported_modes": []}
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Старые overrides не прочитаны: {error}") from error
    values = payload.get("prompts") if isinstance(payload, dict) else None
    if not isinstance(values, dict) or not values:
        return {"status": "no_overrides", "imported_modes": []}

    common = str(values.get("common") or prompts.LES_SYSTEM_PROMPT).strip()
    tone = str(values.get("tone") or prompts.LES_TONE_PROMPT).strip()
    legacy_mode = {
        "search": "rag",
        "agent": "free",
        "estimator": "smeta_direct",
        "engineer": "review",
    }
    global_changed = "common" in values or "tone" in values
    imported: list[str] = []
    snapshot = registry_snapshot(db_path=db_path)
    for mode, old_mode in legacy_mode.items():
        mode_key = f"modes.{old_mode}"
        if not global_changed and mode_key not in values:
            continue
        current = next(item for item in snapshot["profiles"] if item["mode"] == mode)["active"]
        mode_text = str(values.get(mode_key) or prompts.MODE_PROMPTS.get(old_mode, "")).strip()
        effective = "\n\n".join(item for item in (common, tone, mode_text) if item)
        prompt_revision = publish_text_revision(
            "prompt",
            name=f"{MODE_LABELS[mode]} · импорт прежних настроек",
            text=effective,
            source_revision_id=current["prompt_revision_id"],
            db_path=db_path,
        )
        profile_revision = publish_profile_revision(
            mode=mode,
            name=f"{MODE_LABELS[mode]} · импорт",
            prompt_revision_id=prompt_revision["revision_id"],
            skill_revision_id=current["skill_revision_id"],
            tools=current.get("tools") or [],
            model_policy=current.get("model_policy") or {},
            rag_policy=current.get("rag_policy") or {},
            source_revision_id=current["revision_id"],
            db_path=db_path,
        )
        activate_profile_revision(mode, profile_revision["revision_id"], db_path=db_path)
        imported.append(mode)
    result = {"status": "imported", "imported_modes": imported}
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO les_profile_migrations(migration_key,result_json,created_at) VALUES(?,?,?)",
            (migration_key, _json(result), _now()),
        )
        conn.commit()
    return result
