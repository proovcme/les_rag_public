from tools import model_matrix


def test_filter_candidates_by_role_and_disk():
    candidates = [
        model_matrix.ModelCandidate(
            id="small",
            family="Phi",
            roles=("chat", "validator"),
            tier="light",
            disk_gb=2.0,
            status="candidate",
        ),
        model_matrix.ModelCandidate(
            id="large",
            family="Mistral",
            roles=("chat",),
            tier="quality",
            disk_gb=4.5,
            status="candidate",
        ),
    ]

    filtered = model_matrix.filter_candidates(candidates, role="validator", max_disk_gb=3.0)

    assert [candidate.id for candidate in filtered] == ["small"]


def test_format_table_includes_model_ids():
    table = model_matrix.format_table(
        [
            model_matrix.ModelCandidate(
                id="mlx-community/example",
                family="Example",
                roles=("chat",),
                tier="light",
                disk_gb=1.0,
                status="candidate",
            )
        ]
    )

    assert "mlx-community/example" in table
    assert "role" in table
