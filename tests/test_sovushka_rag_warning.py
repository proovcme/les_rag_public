from sovushka.pages import documents


def test_smeta_revision_mismatch_is_a_visible_blocking_warning():
    result = documents.smeta_readiness_presentation(
        {
            "state": "blocked",
            "reason": "base_index_revision_mismatch",
            "warnings": [
                {
                    "code": "SMETA_BASE_INDEX_REVISION_MISMATCH",
                    "message": "Активная сметная база и индекс карточек относятся к разным ревизиям.",
                }
            ],
        }
    )

    assert result == {
        "label": "База и индекс рассогласованы",
        "tone": "blocked",
        "warning": "Активная сметная база и индекс карточек относятся к разным ревизиям.",
    }
