from pathlib import Path
from types import SimpleNamespace

import pytest

from proxy.services.retrieval_service import resolve_dataset_ids
from tools import seed_artel_learning_cases as seed


ROOT = Path(__file__).resolve().parents[1]


def test_artel_learning_case_projection_contains_retrieval_terms():
    case = seed.load_case(ROOT / "examples" / "artel" / "family_learning_case.metal_cabinet.json")
    markdown = seed.render_learning_case_markdown(case)

    assert "ARTEL FamilyLearningCase" in markdown
    assert "ARTEL_DEMO_MetalCabinet" in markdown
    assert "ADSK_Наименование" in markdown
    assert "Known failures:" in markdown
    assert "FOP profile: ARTEL_DEMO_FOP_v1" in markdown
    assert "Шкаф управления металлический" in markdown


def test_artel_learning_case_projection_writes_under_artel_rag_content(tmp_path):
    case = seed.load_case(ROOT / "examples" / "artel" / "family_learning_case.metal_cabinet.json")
    target = seed.write_projection(case, tmp_path)

    assert target == tmp_path / "RAG_Content" / "ARTEL" / "family_learning_cases" / "demo_metal_cabinet_001.md"
    assert target.exists()
    assert "FamilyLearningCase" in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_artel_filter_resolves_to_artel_index():
    backend = SimpleNamespace(
        list_datasets=lambda: None,
    )

    async def list_datasets():
        return [SimpleNamespace(id="artel", name="ARTEL_Index")]

    backend.list_datasets = list_datasets
    logger = SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)

    ids = await resolve_dataset_ids(
        backend,
        dataset_ids=None,
        dataset_filter="ARTEL",
        logger=logger,
    )

    assert ids == ["artel"]
