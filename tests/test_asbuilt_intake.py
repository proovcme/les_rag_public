"""Юниты приёмки смонтированного объёма из исполнительных схем.

Проверяем ДЕТЕРМИНИРОВАННЫЕ части (имя→контекст, нормализация чисел, фильтр строк, разбор
JSON, маппинг в журнал, свод). Vision-OCR замокан — живой gemma/облако в гейте не нужны.
"""
from __future__ import annotations

import pytest

from proxy.services import asbuilt_intake_service as svc
from proxy.services.asbuilt_ocr import parse_rows_json


# ── имя файла → контекст ──

def test_parse_filename_aups():
    ctx = svc.parse_asbuilt_filename("МФЗ_Б4_АУПС _L5 _ОП_ОКЛ_13.06.2023 г.pdf")
    assert ctx["building"] == "Б4"
    assert ctx["system"] == "АУПС"
    assert ctx["floor"] == "L5"
    assert ctx["line"] == "ОП"
    assert ctx["date"] == "13.06.2023"


def test_parse_filename_souye():
    ctx = svc.parse_asbuilt_filename("МФЗ_Б4_СОУЭ _L5 _РО_ОКЛ_13.06.2023 г.pdf")
    assert ctx["system"] == "СОУЭ"
    assert ctx["line"] == "РО"


def test_parse_filename_soft_degrade():
    ctx = svc.parse_asbuilt_filename("случайное_имя.pdf")
    assert ctx == {"building": "", "system": "", "floor": "", "line": "", "date": ""}


def test_zahvatka_tag():
    assert svc.zahvatka_tag({"floor": "L5", "system": "АУПС", "line": "ОП"}) == "L5/АУПС/ОП"
    assert svc.zahvatka_tag({"floor": "L5", "system": "", "line": ""}) == "L5"


# ── нормализация чисел ──

@pytest.mark.parametrize("raw,expected", [
    ("1003", 1003.0), ("502,5", 502.5), ("1 003", 1003.0), ("8", 8.0),
    ("", None), ("шт", None), ("—", None), (None, None), ("1.5.2", None),
])
def test_num(raw, expected):
    assert svc._num(raw) == expected


# ── фильтр строк ──

def test_is_kept_filters_headers_and_nodes():
    rows = svc._to_rows([
        {"name": 'Кабельная линия "Спецкаблайн - Гф20" в составе:', "qty": ""},
        {"name": "кабель симметричный огнестойкий", "type": "КПСЭнг(А)-FRHF 1x2x0,75", "unit": "м", "qty": "1003"},
        {"name": "Узел 3", "unit": "шт", "qty": "0"},
        {"name": "Узел 1", "unit": "шт", "qty": "67"},
        {"name": "", "qty": "5"},
    ])
    kept = [r for r in rows if svc._is_kept(r)]
    names = {r.name for r in kept}
    assert names == {"кабель симметричный огнестойкий", "Узел 1"}


# ── разбор JSON-ответа модели ──

def test_parse_rows_json_plain():
    raw = '[{"name":"кабель","unit":"м","qty":"1003"}]'
    assert parse_rows_json(raw)[0]["qty"] == "1003"


def test_parse_rows_json_fenced_with_preamble():
    raw = 'Вот таблица:\n```json\n[{"name":"кабель","qty":"1003"}]\n```\nготово'
    rows = parse_rows_json(raw)
    assert len(rows) == 1 and rows[0]["name"] == "кабель"


def test_parse_rows_json_dict_wrapped():
    raw = '{"rows": [{"name":"кабель","qty":"1003"}]}'
    assert parse_rows_json(raw)[0]["name"] == "кабель"


def test_parse_rows_json_garbage():
    assert parse_rows_json("не json вовсе") == []


# ── extract_rows: авто-поворот + OCR (замокан) ──

def _fake_image():
    from PIL import Image
    return Image.new("RGB", (120, 90), "white")


def test_extract_rows_autorotate(monkeypatch):
    calls = []

    def fake_ocr(image, engine, **kw):
        # «таблицу видно» только когда лист повёрнут на 90° (как реальные сканы)
        calls.append(image.size)
        if image.size[0] < image.size[1]:  # после поворота 90° стороны меняются местами
            return '[{"name":"кабель","type":"КПСЭнг","unit":"м","qty":"1003"},' \
                   '{"name":"труба","unit":"м","qty":"1003"}]'
        return "[]"

    monkeypatch.setenv("LES_ASBUILT_STRATEGY", "tiles")  # locate требует bbox-вызов, тут проверяем сетку
    monkeypatch.setattr(svc, "_render_page", lambda p, dpi: [_fake_image()])
    monkeypatch.setattr(svc, "vision_ocr_tables", fake_ocr)

    res = svc.extract_rows("МФЗ_Б4_АУПС_L5_ОП_ОКЛ_13.06.2023.pdf", rotate="auto", engine="local")
    assert res.rotation_used == 90
    assert len(res.kept) == 2
    assert res.kept[0].qty == 1003.0


def test_extract_rows_unsupported(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("nope")
    res = svc.extract_rows(f)
    assert res.error and not res.kept


# ── маппинг в журнал (create_entry замокан) ──

def test_to_journal_maps_fields(monkeypatch):
    captured = []

    def fake_create(position, volume, unit, **kw):
        captured.append({"position": position, "volume": volume, "unit": unit, **kw})
        return {"id": len(captured)}

    monkeypatch.setattr("proxy.services.field_intake_service.create_entry", fake_create)

    res = svc.ExtractResult(
        pdf="МФЗ_Б4_АУПС_L5_ОП.pdf",
        ctx={"floor": "L5", "system": "АУПС", "line": "ОП", "date": "13.06.2023"},
        rotation_used=90, engine="local",
        kept=[svc.Row("T", "1", "кабель", "КПСЭнг", "м", 1003.0, "1003")],
    )
    out = svc.to_journal(res, status="pending")
    assert len(out) == 1
    rec = captured[0]
    assert rec["position"] == "кабель"
    assert rec["volume"] == 1003.0
    assert rec["zahvatka"] == "L5/АУПС/ОП"
    assert rec["status"] == "pending"
    assert rec["doc_id"] == "МФЗ_Б4_АУПС_L5_ОП.pdf"
    assert "КПСЭнг" in rec["notes"] and "ИД 13.06.2023" in rec["notes"]


# ── свод (SUM кодом) ──

def test_consolidate_sums_by_system_name_unit():
    rows = [
        {"system": "АУПС", "name": "кабель", "unit": "м", "qty": 1003.0, "floor": "L5", "line": "ОП"},
        {"system": "АУПС", "name": "кабель", "unit": "м", "qty": 1220.0, "floor": "L5", "line": "ПП"},
        {"system": "СОУЭ", "name": "кабель", "unit": "м", "qty": 491.0, "floor": "L5", "line": "РО"},
    ]
    con = svc.consolidate(rows)
    aups = [c for c in con if c["system"] == "АУПС"][0]
    assert aups["total"] == 2223.0 and aups["rows"] == 2


# ── чат-канал: детектор интента / путь / ack (OCR не запускаем) ──

from proxy.services import asbuilt_chat_service as chat  # noqa: E402


@pytest.mark.parametrize("q,hit", [
    ("вытащи смонтированный объём из «/tmp/ид»", True),
    ("прогни исполнительные сканы из /tmp/ид и сними объёмы", True),
    ("посчитай смонтированные объёмы по этажу L5", True),
    ("какой смонтированный объём кабеля?", True),
    ("сделай ВОР из спецификации", False),
    ("сколько кабеля по смете?", False),
])
def test_is_asbuilt_query(q, hit):
    assert chat.is_asbuilt_query(q) is hit


def test_extract_path_quoted_and_bare():
    assert chat.extract_path('вытащи объём из «/Users/ovc/RAG/АУПС»') == "/Users/ovc/RAG/АУПС"
    assert chat.extract_path("прогни сканы из /tmp/ид сейчас") == "/tmp/ид"
    assert chat.extract_path("без пути вовсе") == ""


def test_engine_from():
    assert chat._engine_from("вытащи объём облаком") == "cloud"
    assert chat._engine_from("вытащи объём") == "local"


def test_maybe_handle_need_path():
    res = chat.maybe_handle_asbuilt_query("вытащи смонтированный объём из исполнительных")
    assert res and res["operation"] == "asbuilt_need_path"


def test_maybe_handle_not_intent():
    assert chat.maybe_handle_asbuilt_query("привет, как дела") is None


def test_maybe_handle_starts_background(monkeypatch, tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4")
    started = {}
    monkeypatch.setattr(chat, "_run_async",
                        lambda path, *, engine, project_id: started.update(path=path, engine=engine))
    res = chat.maybe_handle_asbuilt_query(f'вытащи смонтированный объём из «{tmp_path}» облаком')
    assert res["operation"] == "asbuilt_started"
    assert res["asbuilt"]["files"] == 2 and res["asbuilt"]["engine"] == "cloud"
    assert started["engine"] == "cloud"
