"""W8.1/W8.4: журнал полевых объёмов — CRUD, regex-команда, SQL-агрегации (без LLM)."""

import pytest

import proxy.services.field_intake_service as F
from proxy.services.query_router import route_query


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "rag_meta_db_path", lambda: str(tmp_path / "meta.db"))


# ── CRUD (W8.1) ──

def test_create_get_list_cycle():
    entry = F.create_entry("монолитная плита", 50, "м3", zahvatka="3", entry_date="2026-06-10")
    assert entry["id"] == 1
    assert entry["status"] == "confirmed"
    assert entry["volume"] == 50.0
    assert len(F.list_entries()) == 1
    assert F.get_entry(1)["position"] == "монолитная плита"


def test_create_validates_status():
    with pytest.raises(ValueError):
        F.create_entry("x", 1, "м3", status="неведомый")


def test_update_and_delete():
    F.create_entry("кладка", 100, "м2")
    F.update_entry(1, volume=120, status="pending")
    assert F.get_entry(1)["volume"] == 120.0
    assert F.get_entry(1)["status"] == "pending"
    assert F.delete_entry(1) is True
    assert F.get_entry(1) == {}


def test_list_filters():
    F.create_entry("плита", 10, "м3", zahvatka="1", entry_date="2026-06-01")
    F.create_entry("плита", 20, "м3", zahvatka="2", entry_date="2026-07-01")
    assert len(F.list_entries(zahvatka="1")) == 1
    assert len(F.list_entries(date_from="2026-06-15")) == 1


# ── чат-команда записи (regex, без LLM) ──

def test_chat_record_command():
    reply = F.maybe_handle_field_command("запиши объём 50 м3 монолитная плита захватка 3")
    assert reply is not None and reply["operation"] == "field_record"
    entry = F.get_entry(reply["entry_id"])
    assert entry["volume"] == 50.0
    assert entry["unit"] == "м3"
    assert entry["zahvatka"] == "3"
    assert "монолитная плита" in entry["position"]


def test_chat_record_variants():
    assert F.maybe_handle_field_command("учти выполнение 120 м2 кирпичная кладка") is not None
    assert F.maybe_handle_field_command("запиши объём 5,5 т арматура") is not None  # запятая-десятичная
    assert F.maybe_handle_field_command("какая погода") is None  # не команда


# ── период из вопроса (regex) ──

def test_parse_period_month():
    a, b, label = F._parse_period("сколько за июнь 2026")
    assert (a, b) == ("2026-06-01", "2026-06-30")
    assert label == "июнь 2026"


def test_parse_period_range_and_none():
    a, b, _ = F._parse_period("с 01.06.2026 по 15.06.2026")
    assert (a, b) == ("2026-06-01", "2026-06-15")
    assert F._parse_period("сколько всего")[:2] == ("", "")


# ── агрегации и ответ (W8.4, только SQL) ──

def test_aggregate_sums_only_confirmed():
    F.create_entry("плита", 30, "м3", zahvatka="3", entry_date="2026-06-10")
    F.create_entry("плита", 50, "м3", zahvatka="3", entry_date="2026-06-12")
    F.create_entry("плита", 99, "м3", zahvatka="3", entry_date="2026-06-12", status="pending")
    rows = F.aggregate_volumes(zahvatka="3", date_from="2026-06-01", date_to="2026-06-30")
    assert len(rows) == 1
    assert rows[0]["total"] == 80.0  # pending не суммируется
    assert rows[0]["entries"] == 2


def test_field_volume_query_answer():
    F.create_entry("монолитная плита", 30, "м3", zahvatka="3", entry_date="2026-06-10")
    F.create_entry("монолитная плита", 50, "м3", zahvatka="3", entry_date="2026-06-12")
    result = F.maybe_answer_field_volume_query("сколько монолитная плита выполнено за июнь 2026 захватка 3")
    assert result["total_entries"] == 2
    assert "80" in result["answer"]
    assert "без LLM" in result["answer"]


def test_field_volume_query_empty():
    result = F.maybe_answer_field_volume_query("сколько уложено за июнь 2026")
    assert result["total_entries"] == 0
    assert "Записей нет" in result["answer"]


# ── маршрутизация канала (W8.4) ──

def test_router_field_channel():
    assert route_query("сколько монолитная плита выполнено захватка 3").channel == "field"
    assert route_query("забетонировано на захватке 5").channel == "field"
    assert route_query("какая минимальная ширина эвакуационного выхода").channel == "rag"
    assert route_query("итого по смете оборудование").channel == "table"
