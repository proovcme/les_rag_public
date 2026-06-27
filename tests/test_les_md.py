"""LES.md — файл-контекст папки: парс frontmatter, поиск (оба имени), черновик, чат-детектор."""
from __future__ import annotations

from pathlib import Path

from proxy.services import les_md_service as lm
from proxy.services import les_md_chat_service as lmc


def test_parse_frontmatter_ru_en_keys():
    text = (
        "---\n"
        "проект: Лесной64\n"
        "стадия: РД\n"
        "шифр: ОПГС-2020\n"
        "адрес: СПб\n"
        "---\n"
        "# Котельная\n\nТело контекста.\n"
    )
    meta, body = lm.parse_les_md(text)
    assert meta["project"] == "Лесной64"
    assert meta["stage"] == "РД"
    assert meta["cipher"] == "ОПГС-2020"
    assert meta["address"] == "СПб"
    assert "Тело контекста." in body and body.startswith("# Котельная")


def test_parse_no_frontmatter():
    meta, body = lm.parse_les_md("просто текст без шапки")
    assert meta == {} and body == "просто текст без шапки"


def test_find_both_names(tmp_path):
    (tmp_path / "ЛЕС.md").write_text("---\nпроект: X\n---\nтело", encoding="utf-8")
    found = lm.find_les_md(tmp_path)
    assert found is not None and found.name == "ЛЕС.md"


def test_find_latin_name(tmp_path):
    (tmp_path / "LES.md").write_text("body", encoding="utf-8")
    assert lm.find_les_md(tmp_path).name == "LES.md"


def test_find_absent(tmp_path):
    assert lm.find_les_md(tmp_path) is None


def test_generate_draft_scans_types(tmp_path):
    (tmp_path / "ОПГС-2020-АУПС лист.pdf").write_bytes(b"%PDF")
    (tmp_path / "смета.xlsx").write_bytes(b"x")
    (tmp_path / "чертёж.bak").write_bytes(b"x")
    draft = lm.generate_draft(tmp_path)
    assert draft.startswith("---") and "project:" in draft
    assert ".pdf" in draft and ".xlsx" in draft
    assert "ignore:" in draft  # есть секция исключений


def test_draft_infers_object_and_stage(tmp_path):
    obj_dir = tmp_path / "00_Лесной 64_Котельная"
    (obj_dir / "05_РД").mkdir(parents=True)
    (obj_dir / "02_ИРД").mkdir()
    (obj_dir / "05_РД" / "ОПГС-2020 ИД лист.pdf").write_bytes(b"%PDF")
    meta, _ = lm.parse_les_md(lm.generate_draft(obj_dir))
    assert meta["object"] == "Лесной 64 Котельная"      # снят «00_», _→пробел
    assert "РД" in str(meta["stage"]) and "ИРД" in str(meta["stage"])  # стадии из подпапок


def test_infer_object_strips_leading_number():
    from pathlib import Path
    assert lm._infer_object(Path("00_Лесной 64_Котельная")) == "Лесной 64 Котельная"
    assert lm._infer_object(Path("Просто_Папка")) == "Просто Папка"


def test_read_and_bind_auto_init(tmp_path):
    obj = tmp_path / "12_Тест Объект"
    (obj / "01_РД").mkdir(parents=True)
    (obj / "01_РД" / "шифр.pdf").write_bytes(b"%PDF")
    res = lm.read_and_bind(obj, write_draft=True)        # enrich=False → без LLM
    assert res["found"] and res["drafted"]
    assert (obj / "LES.md").exists()                     # ЛЕС сам написал файл
    assert res["project_id"] > 0 and res["project"] == "Тест Объект"


def test_canon_maps_aliases():
    assert lm._canon({"Объект": "Котельная", "код": "Ш-1"}) == {"object": "Котельная", "cipher": "Ш-1"}


# ── чат-детектор ──

import pytest  # noqa: E402


@pytest.mark.parametrize("q,hit", [
    ("пойми папку «/tmp/x»", True),
    ("сделай LES.md для «/tmp/x»", True),
    ("разбери папку «/tmp/x»", True),
    ("прочитай лес.md из «/tmp/x»", True),
    ("дай сводку проекта", False),
    ("сколько кабеля на L5", False),
])
def test_is_les_md_query(q, hit):
    assert lmc.is_les_md_query(q) is hit


def test_chat_need_path():
    res = lmc.maybe_handle_les_md_query("пойми папку")
    assert res and res["operation"] == "les_md_need_path"


def test_chat_no_path():
    res = lmc.maybe_handle_les_md_query("пойми папку «/нет/такой»")
    assert res["operation"] == "les_md_no_path"


def test_chat_not_intent():
    assert lmc.maybe_handle_les_md_query("привет") is None
