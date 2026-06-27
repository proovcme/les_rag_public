"""Алгоритмический детект таблиц по линиям сетки (OpenCV)."""

from __future__ import annotations

from PIL import Image, ImageDraw

from proxy.services.table_detect import detect_table_regions


def _grid_image(w=400, h=300, box=(50, 40, 300, 260)):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    for x in range(x0, x1 + 1, 50):
        d.line([(x, y0), (x, y1)], fill="black", width=2)
    for y in range(y0, y1 + 1, 30):
        d.line([(x0, y), (x1, y)], fill="black", width=2)
    return img


def test_detects_grid_region():
    regs = detect_table_regions(_grid_image())
    assert len(regs) >= 1
    r = regs[0]
    # регион покрывает нарисованную сетку (нормировано 0..1)
    assert r[0] < 0.30 and r[2] > 0.60 and r[1] < 0.30 and r[3] > 0.70


def test_blank_has_no_tables():
    assert detect_table_regions(Image.new("RGB", (400, 300), "white")) == []


def test_regions_normalized_and_sane():
    for r in detect_table_regions(_grid_image()):
        assert len(r) == 4
        assert all(0.0 <= v <= 1.0 for v in r)
        assert r[2] > r[0] and r[3] > r[1]
