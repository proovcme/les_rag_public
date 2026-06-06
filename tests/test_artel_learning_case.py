from pathlib import Path

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
