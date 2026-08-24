from tools.rag_advanced_synthetic_benchmark import run


def test_advanced_rag_synthetic_ab_gate():
    result = run()
    assert result["passed"] is True
    assert result["colbert_mrr"] > result["baseline_mrr"]
    assert result["raptor_exact_leaf_coverage"] is True
    assert result["raptor_navigation_citable"] is False
