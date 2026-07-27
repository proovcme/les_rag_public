from backend.inference.bm25_sparse import encode_bm25, tokenize


def test_project_drawing_designations_keep_native_sparse_vector():
    text = "BB_63\nА\nPE,N,\nС,В,А"

    tokens = tokenize(text)

    assert "bb_63" in tokens
    assert encode_bm25(text)


def test_compact_technical_fallback_does_not_change_normal_prose_tokens():
    assert tokenize("Кабель силовой PE N") == tokenize("Кабель силовой")
