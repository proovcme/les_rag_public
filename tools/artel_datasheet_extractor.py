"""W10.1 (детерминированная часть) — извлечение family_spec из таблицы техлиста БЕЗ модели.

Ответ на «а если тебя нет»: для структурированного каталога (как KORF MPU — чистая
таблица типоразмеров) спецификация собирается алгоритмом, а не LLM (ADR-11). Ядро
`table_to_spec` берёт матрицу ячеек (модель + габаритные колонки) и выдаёт
`family_spec` с типоразмерами; `datasheet_to_spec` достаёт таблицы из PDF (pdfplumber).
Малая/облачная модель нужна лишь там, где вход неструктурирован (классификация,
маппинг колонок) — но числа всегда из таблицы, не выдумываются.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# Габаритная роль колонки → имя параметра в спецификации (канон РФ).
_ROLE_PARAM = {"length": "Длина", "width": "Ширина", "depth": "Глубина", "height": "Высота"}
# Полнословные ключи заголовков габаритных колонок.
_DIM_WORDS = [
    ("length", ("длина", "length")),
    ("width", ("ширина", "width")),
    ("depth", ("глубина", "depth")),
    ("height", ("высота", "height")),
]
# Однобуквенные оси (КORF: А=длина, Б=глубина, В=высота).
_AXIS_LETTER = {"а": "length", "б": "depth", "в": "height"}
_MODEL_WORDS = ("модель", "типоразмер", "наименование", "марка", "артикул", "model", "тип ")
# Канонический GUID ADSK_Наименование (совпадает с conformance fop_reference).
_NAME_GUID = "4f5cb6a1-0000-0000-0000-000000000000"


def _num(value: Any) -> float | None:
    """Число из ячейки; '1580/1730' → 1580 (первое значение)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().split("/")[0].replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _col_role(text: str) -> str | None:
    t = (text or "").strip().lower().replace("ё", "е")
    if not t:
        return None
    first = t.split(",")[0].split()[0] if t.split(",")[0].split() else ""
    if first in _AXIS_LETTER:
        return _AXIS_LETTER[first]
    for role, keys in _DIM_WORDS:
        if any(k in t for k in keys):
            return role
    return None


def _is_model_col(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(k in t for k in _MODEL_WORDS)


def table_to_spec(
    matrix: list[list[Any]], *, family_name: str, category: str, unit: str = "mm",
) -> dict[str, Any] | None:
    """Матрица ячеек (заголовок + строки) → family_spec с типоразмерами. 0 LLM.

    Возвращает None, если габаритную таблицу распознать не удалось.
    """
    header_idx = -1
    cols: dict[str, int] = {}
    model_idx: int | None = None
    for i, row in enumerate(matrix):
        roles: dict[str, int] = {}
        mcol: int | None = None
        for j, cell in enumerate(row):
            role = _col_role(str(cell or ""))
            if role and role not in roles:
                roles[role] = j
            if mcol is None and _is_model_col(str(cell or "")):
                mcol = j
        if len(roles) >= 2:
            header_idx, cols, model_idx = i, roles, (mcol if mcol is not None else 0)
            break
    if header_idx < 0:
        return None

    types: list[dict[str, Any]] = []
    for row in matrix[header_idx + 1:]:
        values: dict[str, float] = {}
        for role, j in cols.items():
            v = _num(row[j]) if j < len(row) else None
            if v is not None:
                values[_ROLE_PARAM[role]] = v
        if not values:  # строка без габаритов (раздел/итог/пусто) — пропускаем
            continue
        name = str(row[model_idx]).strip() if model_idx is not None and model_idx < len(row) else ""
        types.append({"id": f"t{len(types) + 1}", "name": name or f"Тип {len(types) + 1}", "values": values})
    if not types:
        return None

    dim_params = [_ROLE_PARAM[r] for r in ("length", "width", "depth", "height") if r in cols]
    params: list[dict[str, Any]] = [{
        "id": "p_name", "name": "ADSK_Наименование", "source": "shared_parameter",
        "sharedParameterGuid": _NAME_GUID, "dataType": "Text", "group": "Identity Data",
        "isInstance": False, "isRequired": True,
    }]
    for k, pname in enumerate(dim_params, 1):
        params.append({
            "id": f"p{k}", "name": pname, "source": "family_parameter", "dataType": "Length",
            "group": "Dimensions", "isInstance": False, "isRequired": True,
        })

    return {
        "id": "spec_extracted",
        "status": "draft",
        "familyName": family_name,
        "revitCategory": category,
        "parameters": params,
        "types": types,
        "materials": [],
        "_extracted": {"source": "datasheet_table", "unit": unit, "types": len(types)},
    }


def extract_tables(pdf_path: str | Path) -> list[list[list[Any]]]:
    """Все таблицы PDF как матрицы (pdfplumber). Best-effort."""
    import pdfplumber

    tables: list[list[list[Any]]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if table:
                    tables.append(table)
    return tables


def datasheet_to_spec(
    pdf_path: str | Path, *, family_name: str, category: str,
) -> dict[str, Any] | None:
    """PDF техлиста → family_spec по первой распознанной габаритной таблице. 0 LLM."""
    for matrix in extract_tables(pdf_path):
        spec = table_to_spec(matrix, family_name=family_name, category=category)
        if spec:
            return spec
    return None


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Техлист (PDF) → family_spec по габаритной таблице (0 LLM).")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--name", required=True, help="Наименование семейства.")
    parser.add_argument("--category", default="Specialty Equipment", help="Категория Revit.")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    spec = datasheet_to_spec(args.pdf, family_name=args.name, category=args.category)
    if spec is None:
        print("Габаритная таблица не распознана.")
        return 1
    rendered = json.dumps(spec, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote {args.out} ({len(spec['types'])} типоразмеров)")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
