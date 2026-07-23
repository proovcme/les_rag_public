from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from tools import smeta_ru_norm_download as dl


HTML = """
<a href="https://obs.smeta.ru/smetaru/norm/norma/FSNB/FSNB-2022_i18_24.06.2026.zip">latest</a>
<a href="https://obs.smeta.ru/smetaru/norm/norma/FSNB/FSNB-2022_i17_22.05.2026.zip">old</a>
<a href="/download/norm">not zip</a>
<a href="https://obs.smeta.ru/smetaru/norm/norma/FSNB/red-2020/gesn_i9_2020_22.05.2026.zip">2020</a>
"""


def test_extract_zip_links_keeps_obs_zip_links_only():
    links = dl.extract_zip_links(HTML)

    assert len(links) == 3
    assert all(link.startswith("https://obs.smeta.ru/") for link in links)


def test_archive_metadata_parses_category_issue_and_date():
    item = dl.archive_from_url("https://obs.smeta.ru/smetaru/norm/norma/FSNB/FSNB-2022_i18_24.06.2026.zip")

    assert item.category == "fsnb2022"
    assert item.issue == 18
    assert item.date == "2026-06-24"


def test_select_latest_prefers_highest_issue_and_date():
    archives = [dl.archive_from_url(url) for url in dl.extract_zip_links(HTML)]

    latest = dl.select_latest(archives, "fsnb2022")

    assert latest is not None
    assert latest.filename == "FSNB-2022_i18_24.06.2026.zip"


def test_filter_archives_matches_url_or_filename():
    archives = [dl.archive_from_url(url) for url in dl.extract_zip_links(HTML)]

    matches = dl.filter_archives(archives, r"red-2020/gesn_i9")

    assert len(matches) == 1
    assert matches[0].category == "red2020"


def test_run_writes_manifest_without_downloading(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(dl, "discover_archives", lambda **kwargs: [dl.archive_from_url(url) for url in dl.extract_zip_links(HTML)])
    args = Namespace(
        runtime_root=str(tmp_path),
        out=Path("storage/downloads/smeta_ru_norm"),
        extract_to=Path("storage/extracted/smeta_ru_norm"),
        page_url=dl.PAGE_URL,
        latest="fsnb2022",
        pattern=None,
        url=[],
        with_head=False,
        download=False,
        extract=False,
        overwrite=False,
        timeout=1,
        download_timeout=1,
    )

    result = dl.run(args)

    assert result["discovered"] == 3
    assert result["selected"][0]["filename"] == "FSNB-2022_i18_24.06.2026.zip"
    assert Path(result["manifest"]).is_file()
