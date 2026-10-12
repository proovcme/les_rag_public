"""Раздел документа и область сборников должны называться одинаково.

Вес практики (`estimate_usage`) ищет раздел по имени, а подбор нормы приводит его к
имени дисциплины сборников. Пока словари звали одно и то же по-разному, для охранных
и пожарных систем практика молча весила ноль.
"""

from __future__ import annotations

import pytest
import yaml

from pathlib import Path


def _load(name: str) -> dict:
    path = Path(__file__).resolve().parents[1] / "config" / "domain" / name
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# Разделы, у которых собственных сборников нет: сметы там состоят из прайсовых
# позиций и прочих затрат, а не из элементных норм.
WITHOUT_COLLECTIONS = frozenset({"engineering_networks", "organization", "furnishing"})


def test_every_section_with_norms_has_a_collection_scope() -> None:
    sections = set(_load("smeta_section_taxonomy.yaml").get("sections") or {})
    disciplines = set(_load("smeta_collection_scope.yaml").get("disciplines") or {})
    assert sections - WITHOUT_COLLECTIONS <= disciplines


@pytest.mark.parametrize("discipline", ["concrete", "earthworks"])
def test_scope_may_know_disciplines_that_no_section_produces(discipline: str) -> None:
    """По ним распознаётся дисциплина текста, когда раздел документа неизвестен."""
    assert discipline in (_load("smeta_collection_scope.yaml").get("disciplines") or {})
