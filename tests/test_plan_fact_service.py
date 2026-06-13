"""W11.2 — план/факт (ВОР ↔ журнал объёмов). Pure reconcile_lines, без LLM/БД."""

from __future__ import annotations

from proxy.services.plan_fact_service import reconcile_lines


def _plan(name, unit, qty, **kw):
    return {"name": name, "unit": unit, "qty": qty, "section": kw.get("section", ""),
            "code": kw.get("code", ""), "mark": kw.get("mark", "")}


def _fact(position, unit, total, entries=1):
    return {"position": position, "unit": unit, "total": total, "entries": entries}


def _by_name(result, name):
    return next(r for r in result["rows"] if r["name"] == name)


def test_matched_partial_progress():
    res = reconcile_lines(
        [_plan("Монолитная плита", "м3", 100.0)],
        [_fact("Монолитная плита", "м3", 40.0, entries=2)],
    )
    row = _by_name(res, "Монолитная плита")
    assert row["status"] == "matched"
    assert row["plan_qty"] == 100.0
    assert row["fact_qty"] == 40.0
    assert row["delta"] == -60.0
    assert row["remaining"] == 60.0
    assert row["done_pct"] == 40.0
    assert row["fact_entries"] == 2


def test_overrun_flagged():
    res = reconcile_lines(
        [_plan("Кладка", "м2", 50.0)],
        [_fact("Кладка", "м2", 65.0)],
    )
    row = _by_name(res, "Кладка")
    assert row["status"] == "over"
    assert row["delta"] == 15.0
    assert row["remaining"] == 0.0
    assert row["done_pct"] == 130.0
    assert res["totals"]["over"] == 1


def test_plan_only_when_no_fact():
    res = reconcile_lines([_plan("Стяжка", "м2", 200.0)], [])
    row = _by_name(res, "Стяжка")
    assert row["status"] == "plan_only"
    assert row["fact_qty"] == 0.0
    assert row["done_pct"] == 0.0
    assert row["remaining"] == 200.0


def test_fact_only_when_no_plan():
    res = reconcile_lines([], [_fact("Демонтаж перегородок", "м2", 12.0, entries=3)])
    row = _by_name(res, "Демонтаж перегородок")
    assert row["status"] == "fact_only"
    assert row["plan_qty"] is None
    assert row["fact_qty"] == 12.0
    assert res["totals"]["fact_only"] == 1


def test_unit_mismatch_does_not_match():
    res = reconcile_lines(
        [_plan("Труба", "м", 100.0)],
        [_fact("Труба", "шт", 5.0)],
    )
    # разные единицы → план остаётся не начатым, факт — вне плана
    assert _by_name(res, "Труба", )["status"] in ("plan_only",)  # план-строка
    fact_rows = [r for r in res["rows"] if r["status"] == "fact_only"]
    assert len(fact_rows) == 1 and fact_rows[0]["unit"] == "шт"


def test_name_containment_match():
    # факт «плита монолитная ж/б» матчится с планом «Плита монолитная» (вхождение)
    res = reconcile_lines(
        [_plan("Плита монолитная", "м3", 80.0)],
        [_fact("Плита монолитная ж/б осями 1-5", "м3", 30.0)],
    )
    row = _by_name(res, "Плита монолитная")
    assert row["status"] == "matched"
    assert row["fact_qty"] == 30.0


def test_unit_aliases_normalized_match():
    # план в «м3», факт в «куб.м» → нормализуются к «м³» и матчатся
    res = reconcile_lines(
        [_plan("Бетон", "м3", 10.0)],
        [_fact("Бетон", "куб.м", 4.0)],
    )
    row = _by_name(res, "Бетон")
    assert row["status"] == "matched"
    assert row["fact_qty"] == 4.0


def test_fact_not_double_counted_across_plans():
    # один факт-агрегат уходит только в одну план-строку (жадно, первая по сортировке)
    res = reconcile_lines(
        [_plan("Кладка", "м2", 50.0), _plan("Кладка", "м2", 30.0)],
        [_fact("Кладка", "м2", 20.0, entries=1)],
    )
    consumed = sum(r["fact_qty"] for r in res["rows"] if r["status"] in ("matched", "over"))
    assert consumed == 20.0  # не задвоился


def test_plan_qty_none_is_listed():
    res = reconcile_lines([_plan("Позиция без кол-ва", "шт", None)], [])
    row = _by_name(res, "Позиция без кол-ва")
    assert row["plan_qty"] is None
    assert row["status"] == "plan_only"


def test_totals_counts():
    res = reconcile_lines(
        [_plan("A", "м2", 10.0), _plan("B", "м3", 5.0)],
        [_fact("A", "м2", 4.0), _fact("C", "т", 1.0)],
    )
    t = res["totals"]
    assert t["lines"] == 3
    assert t["matched"] == 1   # A
    assert t["plan_only"] == 1  # B
    assert t["fact_only"] == 1  # C
