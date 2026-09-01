from __future__ import annotations

import json
import sqlite3

import pytest

from proxy.services.chat_profile_service import (
    PROFILE_PROMPT_MAX_CHARS,
    PROFILE_SKILL_MAX_CHARS,
    activate_profile_revision,
    canonical_profile_mode,
    delete_revision,
    import_legacy_prompt_overrides,
    publish_profile_revision,
    publish_text_revision,
    registry_snapshot,
    resolve_profile_system_dataset_ids,
    resolve_chat_profile,
)


def test_factory_seed_is_idempotent_and_activates_four_base_profiles(tmp_path):
    db = tmp_path / "meta.db"

    first = registry_snapshot(db_path=db)
    second = registry_snapshot(db_path=db)

    assert [item["mode"] for item in first["profiles"]] == [
        "search",
        "agent",
        "estimator",
        "engineer",
    ]
    assert all(item["active_revision_id"].endswith(":base") for item in first["profiles"])
    assert first == second
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM les_profile_revisions").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM les_prompt_revisions").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM les_skill_revisions").fetchone()[0] == 4


def test_estimator_profile_system_dataset_is_added_to_frozen_scope():
    resolved = resolve_profile_system_dataset_ids(
        {
            "mode": "estimator",
            "rag_policy": {
                "system_datasets": ["smeta"],
                "model_authored_initial_query": True,
            },
        },
        current_dataset_ids=["project-dataset"],
        module_resolver=lambda module_id: (
            ["fsnb-dataset", "project-dataset"] if module_id == "smeta" else []
        ),
    )

    assert resolved == ["project-dataset", "fsnb-dataset"]


def test_legacy_user_estimator_profile_gets_effective_model_authored_query_policy(tmp_path):
    db = tmp_path / "meta.db"
    snapshot = registry_snapshot(db_path=db)
    estimator = next(
        item for item in snapshot["profiles"] if item["mode"] == "estimator"
    )["active"]
    revision = publish_profile_revision(
        mode="estimator",
        name="Старый пользовательский профиль",
        prompt_revision_id=estimator["prompt_revision_id"],
        skill_revision_id=estimator["skill_revision_id"],
        tools=estimator["tools"],
        model_policy=estimator["model_policy"],
        rag_policy={"grounded": True, "system_datasets": ["smeta"]},
        db_path=db,
    )
    activate_profile_revision("estimator", revision["revision_id"], db_path=db)

    resolved = resolve_chat_profile(
        session_id="legacy-estimator-chat",
        requested_mode="estimator",
        db_path=db,
    )

    assert resolved["rag_policy"]["model_authored_initial_query"] is True
    with sqlite3.connect(db) as conn:
        stored = json.loads(
            conn.execute(
                "SELECT snapshot_json FROM les_profile_revisions WHERE revision_id=?",
                (revision["revision_id"],),
            ).fetchone()[0]
        )
    assert "model_authored_initial_query" not in stored["rag_policy"]


def test_estimator_factory_exposes_only_model_rag_and_result_tools(tmp_path):
    snapshot = registry_snapshot(db_path=tmp_path / "meta.db")
    estimator = next(item for item in snapshot["profiles"] if item["mode"] == "estimator")

    assert estimator["active"]["tools"] == [
        "search_sources",
        "read_source",
        "build_lsr_workbook",
        "build_vor_workbook",
    ]


def test_factory_seed_refreshes_stale_factory_contract_and_bound_session(tmp_path):
    db = tmp_path / "meta.db"
    registry_snapshot(db_path=db)
    stale_tools = ["dataset_map", "search_sources", "read_source"]
    with sqlite3.connect(db) as conn:
        raw = conn.execute(
            "SELECT snapshot_json FROM les_profile_revisions WHERE revision_id=?",
            ("factory:profile:estimator:base",),
        ).fetchone()[0]
        stale_snapshot = json.loads(raw)
        stale_snapshot["tools"] = stale_tools
        stale_json = json.dumps(stale_snapshot, ensure_ascii=False)
        conn.execute(
            "UPDATE les_profile_revisions SET tools_json=?,snapshot_json=? WHERE revision_id=?",
            (
                json.dumps(stale_tools, ensure_ascii=False),
                stale_json,
                "factory:profile:estimator:base",
            ),
        )
        conn.execute(
            """INSERT INTO les_chat_profile_bindings
               (session_id,mode,profile_revision_id,snapshot_json,bound_at,updated_at)
               VALUES(?,?,?,?,?,?)""",
            (
                "stale-estimator-chat",
                "estimator",
                "factory:profile:estimator:base",
                stale_json,
                "2026-08-24T00:00:00+00:00",
                "2026-08-24T00:00:00+00:00",
            ),
        )
        conn.commit()

    refreshed = registry_snapshot(db_path=db)
    estimator = next(item for item in refreshed["profiles"] if item["mode"] == "estimator")
    assert {"build_lsr_workbook", "build_vor_workbook"} <= set(estimator["active"]["tools"])

    rebound = resolve_chat_profile(
        session_id="stale-estimator-chat",
        requested_mode="estimator",
        db_path=db,
    )
    assert {"build_lsr_workbook", "build_vor_workbook"} <= set(rebound["tools"])


@pytest.mark.parametrize(
    ("kind", "limit"),
    [("prompt", PROFILE_PROMPT_MAX_CHARS), ("skill", PROFILE_SKILL_MAX_CHARS)],
)
def test_text_revision_accepts_limit_rejects_limit_plus_one_and_normalizes_whitespace(
    tmp_path, kind, limit
):
    db = tmp_path / "meta.db"
    accepted = publish_text_revision(
        kind, name="Граница", text="  " + ("x" * limit) + "  ", db_path=db
    )
    assert len(accepted["text"]) == limit

    with pytest.raises(ValueError, match="profile_text_too_long"):
        publish_text_revision(
            kind, name="Слишком длинный", text="x" * (limit + 1), db_path=db
        )


def test_registry_keeps_old_oversized_revision_readable_and_reports_limits(tmp_path):
    db = tmp_path / "meta.db"
    registry_snapshot(db_path=db)
    oversized = "legacy" * 3000
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO les_prompt_revisions
               (revision_id,name,revision_no,text_value,sha256,is_factory,created_at)
               VALUES('legacy:oversized','Старая редакция',999,?,'legacy',0,'2026-01-01')""",
            (oversized,),
        )
    snapshot = registry_snapshot(db_path=db)

    item = next(row for row in snapshot["prompt_revisions"] if row["revision_id"] == "legacy:oversized")
    assert item["text"] == oversized
    assert snapshot["text_limits"] == {
        "prompt": PROFILE_PROMPT_MAX_CHARS,
        "skill": PROFILE_SKILL_MAX_CHARS,
    }


def test_factory_estimator_is_pure_rag_skill_not_legacy_lsr_workflow(tmp_path):
    registry = registry_snapshot(db_path=tmp_path / "meta.db")
    estimator = next(item for item in registry["profiles"] if item["mode"] == "estimator")
    base = estimator["active"]

    assert "native RRF" in base["skill_text"]
    assert "search_sources" in base["tools"]
    assert "submit_lsr_mapping" not in base["skill_text"]
    assert "smeta_agent_v2" not in base["prompt_text"]


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (None, "agent"),
        ("", "agent"),
        ("text", "agent"),
        ("free", "agent"),
        ("rag", "search"),
        ("smeta", "estimator"),
        ("smeta_harness", "estimator"),
        ("review", "engineer"),
        ("doc_review", "engineer"),
        ("unknown", "agent"),
    ],
)
def test_legacy_mode_aliases_have_no_auto_fallback(requested, expected):
    assert canonical_profile_mode(requested) == expected


def test_publish_activate_and_bind_immutable_profile_snapshot(tmp_path):
    db = tmp_path / "meta.db"
    seeded = registry_snapshot(db_path=db)
    search = next(item for item in seeded["profiles"] if item["mode"] == "search")

    prompt = publish_text_revision(
        "prompt",
        name="Поиск по рабочей документации",
        text="Отвечай только после итеративного чтения источников.",
        db_path=db,
    )
    skill = publish_text_revision(
        "skill",
        name="Глубокий поиск",
        text="# Глубокий поиск\n\nСначала составь карту документов.",
        db_path=db,
    )
    revision = publish_profile_revision(
        mode="search",
        name="Рабочая документация",
        prompt_revision_id=prompt["revision_id"],
        skill_revision_id=skill["revision_id"],
        tools=["dataset_map", "search_sources", "read_source"],
        model_policy={"temperature": 0.1},
        rag_policy={"grounded": True},
        source_revision_id=search["active_revision_id"],
        db_path=db,
    )
    activate_profile_revision("search", revision["revision_id"], db_path=db)

    bound = resolve_chat_profile(
        session_id="chat-1",
        requested_mode="search",
        db_path=db,
    )

    assert bound["mode"] == "search"
    assert bound["revision_id"] == revision["revision_id"]
    assert bound["prompt_text"] == "Отвечай только после итеративного чтения источников."
    assert bound["skill_text"].startswith("# Глубокий поиск")
    assert bound["tools"] == ["dataset_map", "search_sources", "read_source"]
    assert len(bound["prompt_sha256"]) == 64
    assert len(bound["skill_sha256"]) == 64

    newer = publish_profile_revision(
        mode="search",
        name="Новая настройка",
        prompt_revision_id=prompt["revision_id"],
        skill_revision_id=skill["revision_id"],
        tools=["dataset_map"],
        model_policy={},
        rag_policy={"grounded": True},
        db_path=db,
    )
    activate_profile_revision("search", newer["revision_id"], db_path=db)

    assert resolve_chat_profile(
        session_id="chat-1", requested_mode="search", db_path=db
    )["revision_id"] == revision["revision_id"]
    assert resolve_chat_profile(
        session_id="chat-1",
        requested_mode="search",
        requested_revision_id=newer["revision_id"],
        apply_revision=True,
        db_path=db,
    )["revision_id"] == newer["revision_id"]


def test_profile_publication_does_not_activate_or_rebind(tmp_path):
    db = tmp_path / "meta.db"
    seeded = registry_snapshot(db_path=db)
    agent = next(item for item in seeded["profiles"] if item["mode"] == "agent")
    bound = resolve_chat_profile(session_id="chat-1", requested_mode="agent", db_path=db)

    published = publish_profile_revision(
        mode="agent",
        name="Новая неактивная редакция",
        prompt_revision_id=agent["active"]["prompt_revision_id"],
        skill_revision_id=agent["active"]["skill_revision_id"],
        tools=agent["active"].get("tools") or [],
        model_policy=agent["active"].get("model_policy") or {},
        rag_policy=agent["active"].get("rag_policy") or {},
        source_revision_id=agent["active_revision_id"],
        db_path=db,
    )
    refreshed = registry_snapshot(db_path=db)
    current = next(item for item in refreshed["profiles"] if item["mode"] == "agent")

    assert published["revision_id"] != current["active_revision_id"]
    assert resolve_chat_profile(
        session_id="chat-1", requested_mode="agent", db_path=db
    )["revision_id"] == bound["revision_id"]


def test_profile_rejects_unknown_tool_and_cross_mode_activation(tmp_path):
    db = tmp_path / "meta.db"
    snap = registry_snapshot(db_path=db)
    search = next(item for item in snap["profiles"] if item["mode"] == "search")
    agent = next(item for item in snap["profiles"] if item["mode"] == "agent")

    with pytest.raises(ValueError, match="Неизвестные инструменты"):
        publish_profile_revision(
            mode="search",
            name="Сломанный",
            prompt_revision_id=search["active"]["prompt_revision_id"],
            skill_revision_id=search["active"]["skill_revision_id"],
            tools=["invent_norm_code"],
            model_policy={},
            rag_policy={},
            db_path=db,
        )

    with pytest.raises(ValueError, match="другому режиму"):
        activate_profile_revision("search", agent["active_revision_id"], db_path=db)


def test_base_cannot_be_deleted_and_referenced_user_revision_is_tombstoned(tmp_path):
    db = tmp_path / "meta.db"
    snap = registry_snapshot(db_path=db)
    agent = next(item for item in snap["profiles"] if item["mode"] == "agent")

    with pytest.raises(ValueError, match="Заводскую"):
        delete_revision("profile", agent["active_revision_id"], db_path=db)

    prompt = publish_text_revision(
        "prompt", name="Пользовательский", text="Действуй аккуратно.", db_path=db
    )
    delete_revision("prompt", prompt["revision_id"], db_path=db)
    refreshed = registry_snapshot(db_path=db)

    assert prompt["revision_id"] not in {
        item["revision_id"] for item in refreshed["prompt_revisions"]
    }
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT deleted_at IS NOT NULL FROM les_prompt_revisions WHERE revision_id=?",
            (prompt["revision_id"],),
        ).fetchone()[0] == 1


def test_legacy_prompt_overrides_import_once_as_user_profile_revisions(tmp_path):
    db = tmp_path / "meta.db"
    overrides = tmp_path / "prompt_overrides.json"
    overrides.write_text(
        '{"schema":"prompt_overrides_v1","prompts":{'
        '"common":"ОБЩИЙ OVERRIDE",'
        '"tone":"ТОН OVERRIDE",'
        '"modes.rag":"ПОИСК OVERRIDE"}}',
        encoding="utf-8",
    )

    first = import_legacy_prompt_overrides(overrides_path=overrides, db_path=db)
    second = import_legacy_prompt_overrides(overrides_path=overrides, db_path=db)
    snapshot = registry_snapshot(db_path=db)
    search = next(item for item in snapshot["profiles"] if item["mode"] == "search")

    assert first["status"] == "imported"
    assert second["status"] == "already_imported"
    assert search["active"]["is_factory"] is False
    assert "ОБЩИЙ OVERRIDE" in search["active"]["prompt_text"]
    assert "ТОН OVERRIDE" in search["active"]["prompt_text"]
    assert "ПОИСК OVERRIDE" in search["active"]["prompt_text"]
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM les_profile_revisions WHERE mode='search'"
        ).fetchone()[0] == 2
