from types import SimpleNamespace

from tools.build_smeta_norm_rag import _complete_keys


def test_hybrid_build_resume_keeps_only_exact_complete_projection():
    class Client:
        def __init__(self):
            self.calls = 0

        def scroll(self, **kwargs):
            self.calls += 1
            assert kwargs["with_vectors"] is False
            assert kwargs["with_payload"] == ["norm_key"]
            if self.calls == 1:
                return (
                    [
                        SimpleNamespace(payload={"norm_key": "ГЭСН:01-01-001-01"}),
                        SimpleNamespace(payload={"norm_key": ""}),
                    ],
                    "next",
                )
            return (
                [SimpleNamespace(payload={"norm_key": "ГЭСНм:08-02-001-01"})],
                None,
            )

    result = _complete_keys(
        Client(),
        "smeta_v4",
        base_sha256="base",
        embedding_fingerprint="fp",
    )

    assert result == {"ГЭСН:01-01-001-01", "ГЭСНм:08-02-001-01"}
