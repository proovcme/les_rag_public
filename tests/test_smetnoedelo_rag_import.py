from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from tools import smetnoedelo_rag_import as imp


def test_normalize_entries_accepts_common_section_shapes():
    payload = {
        "SECTIONS": [
            "Сборник 11. Полы",
            {"section": "11-01", "name": "Раздел 1. Полы"},
            {"CODE": "11-01-011-01", "NAME": "Устройство стяжек"},
        ]
    }

    rows = imp.normalize_entries(payload)

    assert rows[0].section == "11"
    assert rows[1].section == "11-01"
    assert rows[2].code == "11-01-011-01"


def test_render_code_card_contains_jobs_resources_and_no_token():
    payload = {
        "SECTIONS": ["Сборник 11. Полы", "Таблица 11-01-011. Устройство стяжек"],
        "CODE": "ГЭСН 11-01-011-01",
        "NAME": "Устройство стяжек: цементных толщиной 20 мм — 100 м2",
        "COMPOSITION": {
            "JOBS": ["Подготовка основания."],
            "RESOURCES": [
                {"CODE": "1-100-22", "NAME": "Затраты труда рабочих", "QUAN": "35.6", "UNIT": "чел.-ч"}
            ],
        },
        "URL": "cs.smetnoedelo.ru/gesn/gesn11-01-011-01.html",
        "REQUESTS": {"USED": 1, "BALANCE": 99},
    }

    text = imp.render_code_card("gesn2", payload)

    assert "11-01-011-01" in text
    assert "Подготовка основания" in text
    assert "| 1-100-22 |" in text
    assert "LES_SMETNOE_TOKEN" not in text
    assert "token=" not in text


class FakeClient:
    def __init__(self, payloads: dict[tuple[str, str, str], object]):
        self.payloads = payloads
        self.requests_used = 0
        self.cache_hits = 0

    def fetch(self, base: str, *, section: str = "", code: str = ""):
        self.requests_used += 1
        return self.payloads[(base, section, code)]


def test_importer_writes_code_and_manifest(tmp_path: Path):
    client = FakeClient({
        ("gesn2", "", "11-01-011-01"): {
            "CODE": "ГЭСН 11-01-011-01",
            "NAME": "Устройство стяжек — 100 м2",
            "COMPOSITION": {"JOBS": ["Подготовка основания."], "RESOURCES": []},
        }
    })
    importer = imp.Importer(client=client, out_dir=tmp_path)

    importer.write_code("gesn2", "11-01-011-01")
    summary = {
        "bases": ["gesn2"],
        "requests_used": client.requests_used,
        "cache_hits": client.cache_hits,
        "files_written": len(importer.written),
        "errors": importer.errors,
    }
    imp.write_manifest(tmp_path, summary)

    card = tmp_path / "gesn2/codes/11_01_011_01.md"
    assert card.is_file()
    assert "Устройство стяжек" in card.read_text(encoding="utf-8")
    assert (tmp_path / "00_import_manifest.md").is_file()


def test_run_stops_at_request_budget_and_still_writes_manifest(monkeypatch, tmp_path: Path):
    class BudgetClient:
        def __init__(self, **kwargs):
            self.requests_used = 0
            self.cache_hits = 0

        def fetch(self, base: str, *, section: str = "", code: str = ""):
            raise imp.RequestBudgetExceeded("cap")

    monkeypatch.setattr(imp, "SmetnoedeloClient", BudgetClient)
    args = Namespace(
        runtime_root=str(tmp_path),
        out=Path("RAG_Content/TABLE_SMETA/SMETA_SERVICE/smetnoedelo_api"),
        cache=Path("storage/cache/smetnoedelo_api"),
        base=["gesn2"],
        default_bases=False,
        code=[],
        section=[],
        crawl_sections=False,
        fetch_codes=False,
        max_depth=1,
        max_requests=0,
        sleep=0,
        timeout=1,
        no_cache=False,
        sync_rag=False,
        proxy_url="http://127.0.0.1:8050",
        sync_source_root="RAG_Content",
        parse=False,
        parse_limit=25,
    )

    summary = imp.run(args)

    assert summary["stopped_by_budget"] is True
    assert (tmp_path / "RAG_Content/TABLE_SMETA/SMETA_SERVICE/smetnoedelo_api/00_import_manifest.json").is_file()


def test_client_cache_does_not_need_token_for_cached_response(monkeypatch, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    key_path = cache_dir / "gesn2" / f"{imp._cache_key('gesn2', code='11-01-011-01')}.json"
    key_path.parent.mkdir(parents=True)
    key_path.write_text('{"CODE": "ГЭСН 11-01-011-01"}', encoding="utf-8")
    monkeypatch.delenv("LES_SMETNOE_TOKEN", raising=False)

    client = imp.SmetnoedeloClient(cache_dir=cache_dir, max_requests=0)

    assert client.fetch("gesn2", code="11-01-011-01")["CODE"] == "ГЭСН 11-01-011-01"
    assert client.cache_hits == 1
