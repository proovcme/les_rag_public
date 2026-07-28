from types import SimpleNamespace

from tools.smeta_rag_quality_probe import _compact, _keys


def test_probe_reads_norm_identity_only_from_payload():
    points = [
        SimpleNamespace(payload={"norm_key": "ГЭСНм:10-01-001-01"}),
        SimpleNamespace(payload={"title": "noise"}),
    ]

    assert _keys(points) == ["ГЭСНм:10-01-001-01"]


def test_probe_compacts_cards_but_keeps_technology_evidence():
    result = _compact(
        [
            {
                "norm_key": "ГЭСНм:10-01-001-01",
                "norm_code": "ГЭСНм10-01-001-01",
                "base_type": "ГЭСНм",
                "title": "Монтаж оборудования",
                "measure_unit": "шт.",
                "work_steps": ["Операция 1", "Операция 2"],
                "resource_preview": [{"name": "Кран"}],
                "source_ref": "hidden",
            }
        ]
    )

    assert result[0]["work_steps"] == ["Операция 1", "Операция 2"]
    assert result[0]["resource_preview"] == [{"name": "Кран"}]
    assert "source_ref" not in result[0]
