from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from zipfile import ZipFile

from tools import smeta_ru_norm_download as dl
from tools import smeta_ru_norm_rag_ingest as ingest


def _args(tmp_path: Path, **overrides):
    values = {
        "runtime_root": str(tmp_path),
        "page_url": dl.PAGE_URL,
        "out": Path("storage/downloads/smeta_ru_norm"),
        "extract_to": Path("storage/extracted/smeta_ru_norm"),
        "rag_out": Path("RAG_Content/TABLE_SMETA/SMETA_RU_NORM"),
        "state": Path("storage/state/smeta_ru_norm_rag_ingest_state.json"),
        "latest_per_category": True,
        "category": ["fsnb2022"],
        "latest": None,
        "pattern": None,
        "url": [],
        "all": False,
        "max_archives": 0,
        "with_head": False,
        "overwrite": False,
        "force": False,
        "timeout": 1,
        "download_timeout": 1,
        "max_source_files": 10,
        "max_source_file_mb": 1.0,
        "max_text_projections": 10,
        "max_text_file_mb": 1.0,
        "max_text_chars": 2000,
        "max_nested_archives": 5,
        "max_nested_files": 20,
        "max_nested_file_mb": 1.0,
        "max_nested_chars": 2000,
        "inventory_sample": 20,
        "sync_rag": False,
        "parse": False,
        "parse_limit": 25,
        "proxy_url": "http://127.0.0.1:8050",
        "sync_source_root": "RAG_Content",
        "stop_on_error": True,
    }
    values.update(overrides)
    return Namespace(**values)


def test_ingest_selects_latest_per_category(monkeypatch, tmp_path: Path):
    archives = [
        dl.archive_from_url("https://obs.smeta.ru/smetaru/norm/norma/FSNB/FSNB-2022_i17_22.05.2026.zip"),
        dl.archive_from_url("https://obs.smeta.ru/smetaru/norm/norma/FSNB/FSNB-2022_i18_24.06.2026.zip"),
    ]
    monkeypatch.setattr(ingest.dl, "discover_archives", lambda **kwargs: archives)

    selected = ingest._select_archives(_args(tmp_path))

    assert len(selected) == 1
    assert selected[0].filename == "FSNB-2022_i18_24.06.2026.zip"


def test_ingest_projects_archive_into_category_rag(monkeypatch, tmp_path: Path):
    archive = dl.archive_from_url("https://obs.smeta.ru/smetaru/norm/norma/FSNB/FSNB-2022_i18_24.06.2026.zip")
    monkeypatch.setattr(ingest.dl, "discover_archives", lambda **kwargs: [archive])

    def fake_download(item, out_dir, **kwargs):
        path = tmp_path / "storage/downloads/smeta_ru_norm" / item.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake zip bytes")
        return {"status": "downloaded", "path": path.as_posix(), "bytes": len(path.read_bytes()), "sha256": "abc", "url": item.url}

    def fake_extract(path, extract_root, **kwargs):
        root = tmp_path / "storage/extracted/smeta_ru_norm" / Path(path).stem
        root.mkdir(parents=True, exist_ok=True)
        (root / "norms.xml").write_text("<norm code='01-01-001-01'>ГЭСН земляные работы</norm>", encoding="utf-8")
        (root / "readme.txt").write_text("ФСНБ ГЭСН ФЕР расценка ресурс", encoding="utf-8")
        with ZipFile(root / "base.vnbx", "w") as zf:
            zf.writestr("A_SRF_F.json", '{"CODE":"01-01-001-01","NAME":"ГЭСН земляные работы"}')
        return {"archive": str(path), "extract_dir": root.as_posix(), "files": 3}

    monkeypatch.setattr(ingest.dl, "download_archive", fake_download)
    monkeypatch.setattr(ingest.dl, "extract_archive", fake_extract)

    summary = ingest.run(_args(tmp_path))

    assert len(summary["processed"]) == 1
    rag_root = tmp_path / "RAG_Content/TABLE_SMETA/SMETA_RU_NORM"
    assert (rag_root / "00_group_classifier.md").is_file()
    assert (rag_root / "fsnb2022/00_dataset_card.md").is_file()
    assert (rag_root / "fsnb2022/FSNB-2022_i18_24.06.2026/01_archive_manifest.md").is_file()
    assert list((rag_root / "fsnb2022/FSNB-2022_i18_24.06.2026/projected_text").rglob("*.md"))
    nested = list((rag_root / "fsnb2022/FSNB-2022_i18_24.06.2026/projected_nested").rglob("*.md"))
    assert nested
    assert any("A_SRF_F" in item.name for item in nested)


def test_ingest_skips_already_processed(monkeypatch, tmp_path: Path):
    archive = dl.archive_from_url("https://obs.smeta.ru/smetaru/norm/norma/FSNB/FSNB-2022_i18_24.06.2026.zip")
    monkeypatch.setattr(ingest.dl, "discover_archives", lambda **kwargs: [archive])
    state = tmp_path / "storage/state/smeta_ru_norm_rag_ingest_state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        ingest._json({"schema": "test", "archives": {archive.url: {"status": "indexed"}}, "categories": ["fsnb2022"]}),
        encoding="utf-8",
    )

    summary = ingest.run(_args(tmp_path))

    assert summary["processed"] == []
    assert summary["skipped"][0]["reason"] == "already_processed"
