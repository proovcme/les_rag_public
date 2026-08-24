from proxy.services.rag_catalog_guard_service import infer_recovered_dataset_name


def test_recovered_name_uses_only_common_preserved_path_root():
    assert infer_recovered_dataset_name(
        {
            "dataset_id": "abc",
            "sample_files": [
                "ПД Инновационный центр/1/a.pdf",
                "ПД Инновационный центр/2/b.pdf",
            ],
        }
    ) == "ПД Инновационный центр"


def test_recovered_name_falls_back_to_stable_dataset_identity():
    assert infer_recovered_dataset_name(
        {"dataset_id": "12345678-dead-beef", "sample_files": ["A/a.pdf", "B/b.pdf"]}
    ) == "Восстановленный датасет 12345678"
