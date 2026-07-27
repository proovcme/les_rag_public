from pathlib import Path
from types import SimpleNamespace

from tools.coreml_embed_worker import _load_stable_compiled_model, _stable_compiled_path


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "embed.mlpackage"
    package.mkdir()
    (package / "Manifest.json").write_text("{}", encoding="utf-8")
    (package / "weights.bin").write_bytes(b"weights")
    return package


def test_compiled_path_is_stable_and_changes_with_package_revision(tmp_path, monkeypatch):
    package = _package(tmp_path)
    monkeypatch.setenv("LES_COREML_COMPILED_CACHE", str(tmp_path / "cache"))

    first = _stable_compiled_path(package)
    assert first == _stable_compiled_path(package)

    (package / "weights.bin").write_bytes(b"new-weights")
    assert _stable_compiled_path(package) != first


def test_compiles_once_and_reuses_stable_directory(tmp_path, monkeypatch):
    package = _package(tmp_path)
    monkeypatch.setenv("LES_COREML_COMPILED_CACHE", str(tmp_path / "cache"))
    compile_calls = []
    load_calls = []

    def compile_model(source, destination_path):
        compile_calls.append((source, destination_path))
        Path(destination_path).mkdir(parents=True)
        (Path(destination_path) / "model.bin").write_bytes(b"compiled")
        return destination_path

    def compiled_model(path, compute_units):
        load_calls.append((path, compute_units))
        return path

    fake_ct = SimpleNamespace(
        models=SimpleNamespace(
            utils=SimpleNamespace(compile_model=compile_model),
            CompiledMLModel=compiled_model,
        )
    )

    first = _load_stable_compiled_model(fake_ct, package, "all")
    second = _load_stable_compiled_model(fake_ct, package, "all")

    assert first == second
    assert len(compile_calls) == 1
    assert len(load_calls) == 2
    assert Path(first).is_dir()
