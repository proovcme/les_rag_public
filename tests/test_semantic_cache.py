from dataclasses import dataclass

from proxy.services.semantic_cache import (
    SemanticCache,
    cosine_similarity,
    dataset_scope_key,
    normalize_question,
)


@dataclass
class Dataset:
    id: str
    name: str
    status: str
    chunk_count: int


def test_normalize_question_collapses_case_and_spaces():
    assert normalize_question("  Сколько   кабеля? ") == "сколько кабеля?"


def test_dataset_scope_key_changes_when_chunk_count_changes():
    datasets = [Dataset("ds-1", "NTD", "COMPLETED", 10)]
    old_scope = dataset_scope_key(datasets, ["ds-1"])
    datasets[0].chunk_count = 11

    assert dataset_scope_key(datasets, ["ds-1"]) != old_scope


def test_semantic_cache_returns_verified_near_match(tmp_path):
    cache = SemanticCache(str(tmp_path / "data" / "les_meta.db"))
    scope = "scope"
    cache.store(
        "Сколько кабеля?",
        scope,
        [1.0, 0.0, 0.0],
        "12 метров",
        ["spec.csv"],
        "VERIFIED",
    )

    hit = cache.lookup("сколько нужно кабеля", scope, [0.99, 0.01, 0.0], threshold=0.98)

    assert hit is not None
    assert hit.answer == "12 метров"
    assert hit.sources == ["spec.csv"]


def test_semantic_cache_ignores_non_verified_entries(tmp_path):
    cache = SemanticCache(str(tmp_path / "data" / "les_meta.db"))
    cache.store("q", "scope", [1.0], "answer", [], "NO_DATA")

    assert cache.lookup("q", "scope", [1.0], threshold=0.1) is None


def test_unvalidated_session_cache_is_exact_and_session_scoped(tmp_path):
    cache = SemanticCache(str(tmp_path / "data" / "les_meta.db"))
    cache.store_session_unvalidated(
        "q",
        "scope",
        "fp",
        "draft answer",
        ["doc"],
        "UNVALIDATED",
        "session-a",
    )

    hit = cache.lookup_session_unvalidated("q", "scope", "fp", "session-a")

    assert hit is not None
    assert hit.answer == "draft answer"
    assert hit.cache_type == "session_unvalidated"
    assert cache.lookup_session_unvalidated("q", "scope", "fp", "session-b") is None
    assert cache.lookup("q", "scope", [1.0], threshold=0.1) is None


def test_semantic_cache_default_uses_active_meta_db_path(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "les_meta_qwen.db"
    monkeypatch.setenv("RAG_META_DB_PATH", str(db_path))

    cache = SemanticCache()
    cache.store("q", "scope", [1.0], "answer", [], "VERIFIED")

    assert db_path.exists()


def test_cosine_similarity_handles_zero_vectors():
    assert cosine_similarity([0.0], [1.0]) == 0.0
