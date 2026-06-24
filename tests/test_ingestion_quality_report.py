"""Ingestion QA — чистые функции скоринга (Codex §10.4)."""

from tools.ingestion_quality_report import (
    build_report,
    br_noise,
    is_broken_table,
    is_language_noise,
    language_ratio,
    metadata_completeness,
)


def test_language_ratio():
    assert language_ratio("полностью русский текст") == 1.0
    assert language_ratio("full english text") == 0.0
    assert 0.4 < language_ratio("микс mixed текст text") < 0.6
    assert language_ratio("123 !!! ---") == 1.0  # нет букв → не штрафуем


def test_br_noise_and_broken_table():
    assert br_noise("215<br>1<br>5") == 2
    assert is_broken_table("215<br>1<br>5") is True
    assert is_broken_table("| | | | | | | | |") is True       # пайп-каша (≥8 пайпов)
    assert is_broken_table("обычный текст нормы") is False


def test_language_noise():
    revit = ("MepUpperTopElevation DimensionFailures EqualityConstraintsUnsatisfied property "
             "source page BuiltInFailures elevation centerline upper end top reference plane host")
    assert len(revit) >= 120 and is_language_noise(revit) is True
    assert is_language_noise("короткий en") is False           # короткий — не штрафуем
    assert is_language_noise("длинный нормальный русский текст про огнестойкость конструкций здания") is False


def test_metadata_completeness():
    assert metadata_completeness({"dataset_id": "d", "chunk_ord": 1, "content_hash": "h"}) == 1.0
    assert metadata_completeness({"dataset_id": "d"}) == round(1 / 3, 10) or metadata_completeness({"dataset_id": "d"}) < 0.5
    assert metadata_completeness({}) == 0.0


def test_build_report_aggregates_and_finds_cross_dataset_dups():
    pts = [
        {"payload": {"text": "норма про огнестойкость", "dataset_id": "A", "dataset_name": "A",
                     "chunk_ord": 1, "content_hash": "h1", "doc_type": "NORMATIVE"}},
        # тот же content_hash в другом датасете → кросс-датасетный дубль
        {"payload": {"text": "норма про огнестойкость", "dataset_id": "B", "dataset_name": "B",
                     "chunk_ord": 1, "content_hash": "h1", "doc_type": "NORMATIVE"}},
        {"payload": {"text": "215<br>1<br>5<br>2", "dataset_id": "A", "dataset_name": "A",
                     "chunk_ord": 2, "content_hash": "h2", "doc_type": "BOOK"}},
    ]
    rep = build_report(pts)
    assert rep["sampled"] == 3
    assert rep["duplicates"]["cross_dataset_clusters"] == 1
    assert rep["duplicates"]["duplicate_chunks_in_sample"] == 1   # одна лишняя копия h1
    assert rep["quality"]["broken_tables_pct"] > 0                # есть <br>-чанк


def test_build_report_empty():
    assert build_report([]) == {"sampled": 0}
