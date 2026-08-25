from __future__ import annotations

import json
import sqlite3

import pytest

from proxy.services.chat_profile_service import (
    activate_profile_revision,
    canonical_profile_mode,
    delete_revision,
    ensure_estimator_workbook_profile,
    import_legacy_prompt_overrides,
    publish_profile_revision,
    publish_text_revision,
    registry_snapshot,
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


def test_factory_estimator_keeps_rag_skill_and_adds_file_tools(tmp_path):
    registry = registry_snapshot(db_path=tmp_path / "meta.db")
    estimator = next(item for item in registry["profiles"] if item["mode"] == "estimator")
    base = estimator["active"]

    assert "native RRF" in base["skill_text"]
    assert "search_sources" in base["tools"]
    assert "build_lsr_workbook" in base["tools"]
    assert "build_vor_workbook" in base["tools"]
    assert "build_lsr_workbook" in base["skill_text"]
    assert "build_vor_workbook" in base["skill_text"]
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


def test_ensure_estimator_workbook_profile_upgrades_old_active_snapshot(tmp_path):
    db = tmp_path / "meta.db"
    registry_snapshot(db_path=db)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM les_profile_migrations")
        row = conn.execute(
            "SELECT revision_id, snapshot_json FROM les_profile_revisions "
            "WHERE mode='estimator' AND is_factory=1"
        ).fetchone()
        snapshot = json.loads(row[1])
        snapshot["tools"] = [
            name for name in snapshot["tools"]
            if name not in {"build_lsr_workbook", "build_vor_workbook"}
        ]
        snapshot["skill_text"] = snapshot["skill_text"].split("\n6.")[0].rstrip()
        conn.execute(
            "UPDATE les_profile_revisions SET snapshot_json=? WHERE revision_id=?",
            (json.dumps(snapshot, ensure_ascii=False), row[0]),
        )
        conn.commit()

    result = ensure_estimator_workbook_profile(db_path=db)
    estimator = next(
        item for item in registry_snapshot(db_path=db)["profiles"] if item["mode"] == "estimator"
    )

    assert result["status"] == "applied"
    assert "build_lsr_workbook" in estimator["active"]["tools"]
    assert "build_vor_workbook" in estimator["active"]["tools"]
    assert "build_lsr_workbook" in estimator["active"]["skill_text"]
    assert estimator["active"]["is_factory"] is False
