"""Алгоритмический детект таблиц на стройскане — по линиям сетки (OpenCV, без LLM).

LLM-минимализм (ADR-11): таблицу на листе находит детерминированный CV (морфология
горизонтальных+вертикальных линий → блоки сетки), а не vision. Это разблокирует
батч-обработку чертежей: машина сама выделяет таблицы-регионы (где оператор тащил
бы рамку), дальше каждый регион классифицируется и извлекается.

detect_table_regions(image) → список [x0,y0,x1,y1] (нормировано 0..1), крупные первыми.
"""

from __future__ import annotations

import os


def detect_table_regions(pil_img, max_regions: int = 12) -> list[list[float]]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return []

    img = np.array(pil_img.convert("L"))
    H, W = img.shape
    if H < 50 or W < 50:
        return []

    # линии таблицы = тёмные штрихи; инвертируем и бинаризуем
    inv = 255 - img
    bw = cv2.adaptiveThreshold(inv, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)

    # горизонтальные и вертикальные линии (морфология вытянутыми ядрами)
    hlen = max(15, W // 40)
    vlen = max(15, H // 40)
    horiz = cv2.dilate(cv2.erode(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (hlen, 1))),
                       cv2.getStructuringElement(cv2.MORPH_RECT, (hlen, 1)))
    vert = cv2.dilate(cv2.erode(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vlen))),
                      cv2.getStructuringElement(cv2.MORPH_RECT, (1, vlen)))

    grid = cv2.add(horiz, vert)
    # склеиваем линии в сплошные блоки-таблицы
    grid = cv2.dilate(grid, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)), iterations=2)

    cnts, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = float(os.getenv("TABLE_DETECT_MIN_AREA", "0.004")) * W * H
    regions: list[tuple] = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w * h < min_area:
            continue
        if w < W * 0.04 or h < H * 0.015:  # слишком узкое/низкое — не таблица
            continue
        # доля «линейных» пикселей внутри блока — отсекаем сплошные пятна (печати/планы)
        sub = grid[y:y + h, x:x + w]
        if sub.mean() < 8:  # почти пусто
            continue
        pad_x, pad_y = int(w * 0.01), int(h * 0.02)  # лёгкий паддинг под шапку/край
        x0 = max(0, x - pad_x); y0 = max(0, y - pad_y)
        x1 = min(W, x + w + pad_x); y1 = min(H, y + h + pad_y)
        regions.append((x0 / W, y0 / H, x1 / W, y1 / H, w * h))

    regions.sort(key=lambda r: -r[4])
    cands = [list(r[:4]) for r in regions[: max_regions * 3]]

    # фрейм-фильтр: near-full-page = рамка листа-чертежа. Если есть таблицы поменьше —
    # рамку отбрасываем; если кандидат один и он во весь лист — это таблица (чек-лист).
    def _full(r) -> bool:
        return (r[2] - r[0]) > 0.92 and (r[3] - r[1]) > 0.92

    smalls = [r for r in cands if not _full(r)]
    cands = smalls if smalls else cands[:1]

    # дедуп: выкидываем регион, в основном вложенный в уже принятый (больший)
    def _mostly_inside(r, k) -> bool:
        ix = max(0.0, min(r[2], k[2]) - max(r[0], k[0]))
        iy = max(0.0, min(r[3], k[3]) - max(r[1], k[1]))
        inter = ix * iy
        area = (r[2] - r[0]) * (r[3] - r[1])
        return area > 0 and inter / area > 0.6

    out: list[list[float]] = []
    for r in cands:
        if any(_mostly_inside(r, k) for k in out):
            continue
        out.append(r)
    return out[:max_regions]
