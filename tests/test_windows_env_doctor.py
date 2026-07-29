from __future__ import annotations

from pathlib import Path

from tools import windows_env_doctor


def test_env_doctor_repairs_repeated_content_without_exposing_values(tmp_path: Path):
    path = tmp_path / ".env"
    seed = tmp_path / "seed.env"
    seed.write_bytes(b"LES_LLM_PROVIDER=ollama\n")
    block = b"OLLAMA_MODEL=qwen3.5:9b\nSECRET_TOKEN=private-value\n"
    path.write_bytes(block * 30_000)

    inspection = windows_env_doctor.inspect(path)
    result = windows_env_doctor.repair(
        path,
        seed=seed,
        recovery_root=tmp_path / "recovery",
    )

    assert inspection["oversized"] is True
    assert result["original_bytes"] > result["repaired_bytes"]
    assert result["values_exposed"] is False
    assert Path(result["recovery_path"]).is_file()
    repaired = path.read_bytes()
    assert repaired.count(b"SECRET_TOKEN=") == 1
    assert b"LES_LLM_PROVIDER=ollama" in repaired


def test_env_doctor_rejects_sample_without_valid_entries(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_bytes(b"not-an-env-file")
    try:
        windows_env_doctor.repair(path)
    except RuntimeError as exc:
        assert "no valid environment entries" in str(exc)
    else:
        raise AssertionError("invalid environment was repaired")
