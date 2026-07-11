from tools.smeta_embedding_parity import _cosine, _sample


def test_cosine_and_even_sample_contract():
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    rows = [{"norm_key": str(index)} for index in range(10)]

    assert [row["norm_key"] for row in _sample(rows, 3)] == ["0", "4", "9"]
