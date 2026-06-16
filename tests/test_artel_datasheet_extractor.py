"""W10.1 (детерминированная часть) — техлист-таблица → family_spec без модели."""
from tools import artel_datasheet_extractor as ex
from tools import artel_family_action_plan as compiler


# Матрица как из техлиста KORF MPU (модель + А/Б/В + вес).
KORF_TABLE = [
    ["Модель", "А, мм", "Б, мм", "В, мм", "Вес, кг"],
    ["MPU 400", "1075", "525", "975", "120"],
    ["MPU 700", "1075", "600", "1100", "140"],
    ["MPU 1600", "1580/1730", "725", "1165/1400", "220/265"],
    ["MPU 3800", "1755", "1015", "1455", "330"],
]


def test_table_to_spec_korf():
    spec = ex.table_to_spec(KORF_TABLE, family_name="KORF MPU", category="Mechanical Equipment")
    assert spec is not None
    # типоразмеры из строк таблицы
    assert [t["name"] for t in spec["types"]] == ["MPU 400", "MPU 700", "MPU 1600", "MPU 3800"]
    # габариты: А→Длина, Б→Глубина, В→Высота; '1580/1730' → 1580
    assert spec["types"][2]["values"] == {"Длина": 1580.0, "Глубина": 725.0, "Высота": 1165.0}
    # параметры: shared ADSK_Наименование с GUID + габаритные
    names = [p["name"] for p in spec["parameters"]]
    assert names == ["ADSK_Наименование", "Длина", "Глубина", "Высота"]
    name_param = spec["parameters"][0]
    assert name_param["source"] == "shared_parameter" and name_param["sharedParameterGuid"]


def test_full_word_headers():
    table = [
        ["Наименование", "Длина", "Ширина", "Высота"],
        ["Изделие А", "800", "400", "1800"],
        ["Изделие Б", "1000", "500", "2000"],
    ]
    spec = ex.table_to_spec(table, family_name="Шкаф", category="Furniture")
    assert [t["name"] for t in spec["types"]] == ["Изделие А", "Изделие Б"]
    assert spec["types"][0]["values"] == {"Длина": 800.0, "Ширина": 400.0, "Высота": 1800.0}
    assert [p["name"] for p in spec["parameters"]] == ["ADSK_Наименование", "Длина", "Ширина", "Высота"]


def test_skips_non_dimension_rows():
    table = [
        ["Модель", "Длина", "Глубина", "Высота"],
        ["Раздел 1", "", "", ""],            # без габаритов — пропускается
        ["A1", "100", "200", "300"],
        ["Итого", "", "", ""],               # без габаритов — пропускается
    ]
    spec = ex.table_to_spec(table, family_name="X", category="Furniture")
    assert len(spec["types"]) == 1 and spec["types"][0]["name"] == "A1"


def test_unrecognized_table_returns_none():
    table = [["Цена", "Артикул"], ["100", "АБ-1"]]
    assert ex.table_to_spec(table, family_name="X", category="Y") is None


def test_extracted_spec_compiles_to_plan():
    """Сквозняк: таблица → спец → детерминированный план действий (0 LLM, 0 модели)."""
    spec = ex.table_to_spec(KORF_TABLE, family_name="KORF MPU", category="Mechanical Equipment")
    geometry = {
        "schema_version": "artel.family_geometry.v1",
        "archetype": "rect_cabinet",
        "bindings": {"width": "Длина", "depth": "Глубина", "height": "Высота"},
    }
    fop = compiler.build_fop_index(
        "*GROUP\tID\tNAME\nGROUP\t1\tИд\n"
        "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\n"
        "PARAM\t4f5cb6a1-0000-0000-0000-000000000000\tADSK_Наименование\tTEXT\t\t1\t1\tНаим\t1"
    )
    plan = compiler.compile_action_plan(spec, fop, geometry)
    assert plan["status"] == "ok"
    type_ops = [o for o in plan["operations"] if o["op"] == "create_type"]
    assert len(type_ops) == 4  # 4 типоразмера из таблицы
    compiler.validate_plan(plan)
