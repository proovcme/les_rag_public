from tools.publication_check import forbidden_tracked, secret_hits


def test_forbidden_tracked_runtime_paths():
    bad = forbidden_tracked(["README.md", "data/les_meta.db", "storage/datasets/x", ".env"])
    assert bad == ["data/les_meta.db", "storage/datasets/x", ".env"]


def test_secret_scan_ignores_placeholders_and_flags_real_values(tmp_path):
    safe = tmp_path / "safe.env"
    safe.write_text(
        "OPENAI_API_KEY=\nJWT_SECRET=change_me_to_random_string_32chars\napi_key=self.api_key\n",
        encoding="utf-8",
    )
    risky = tmp_path / "risky.env"
    risky.write_text("OPENAI_API_KEY=sk-" + "a" * 40 + "\n", encoding="utf-8")

    hits = secret_hits(tmp_path, ["safe.env", "risky.env"])
    assert len(hits) == 1
    assert hits[0][0] == "risky.env"
