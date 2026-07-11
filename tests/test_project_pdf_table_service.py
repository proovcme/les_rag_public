import pytest

from proxy.services.project_pdf_table_service import (
    PROJECT_PDF_TABLE_ALGO_VERSION,
    _drawing_annotation_candidates,
    classify_project_table,
    classify_project_table_semantic,
    extract_project_pdf_table_manifest,
    merge_adjacent_project_table_fragments,
    normalize_hvs_table,
    normalize_room_explication_table,
    normalize_water_balance_table,
    summarize_project_table_manifests,
)


def test_table_manifest_exposes_algorithm_version(tmp_path):
    manifest = extract_project_pdf_table_manifest(tmp_path / "missing.pdf")

    assert manifest["algo_version"] == PROJECT_PDF_TABLE_ALGO_VERSION


def test_cable_journal_fragments_merge_repeated_and_inherited_headers():
    fragments = [
        {
            "matrix": [["Имя панели", "Помещение"], ["N1", "Серверная 044"]],
            "table_indices": [2],
            "context": "Кабельный журнал",
        },
        {
            "matrix": [["Имя панели", "Помещение"], ["N2", "Ниша СС 1, 01"]],
            "table_indices": [3],
            "context": "",
        },
        {
            "matrix": [["N3", "Ниша СС 2, 02"], ["N4", "Ниша СС 3, 03"]],
            "table_indices": [4],
            "context": "",
        },
    ]

    result = merge_adjacent_project_table_fragments(fragments)

    assert len(result) == 1
    assert result[0]["matrix"] == [
        ["Имя панели", "Помещение"],
        ["N1", "Серверная 044"],
        ["N2", "Ниша СС 1, 01"],
        ["N3", "Ниша СС 2, 02"],
        ["N4", "Ниша СС 3, 03"],
    ]
    assert result[0]["table_indices"] == [2, 3, 4]
    assert result[0]["inherited_header"] is True


def test_semantic_classifier_marks_panel_room_grid_as_cable_journal():
    table = [
        ["Имя панели", "Помещение"],
        ["N1", "Серверная 044"],
        ["N2", "Ниша СС 1, 01"],
    ]

    result = classify_project_table_semantic(table, source_ref="project/СС.pdf#page=15#tables=2-6")

    assert result["semantic_type"] == "ELEC/CABLE_JOURNAL: панели и помещения кабельного журнала"
    assert result["category"] == "engineering"


def test_semantic_classifier_marks_section_name_executor_as_project_composition():
    table = [
        ["Раздел", "Наименование", "Исполнитель"],
        ["10", "Состав проекта", "ООО Проект"],
    ]

    result = classify_project_table_semantic(table, source_ref="project/00.pdf#page=3#table=1")

    assert result["semantic_type"] == "NAV: состав/содержание/ведомости документации"
    assert result["category"] == "navigation"


@pytest.mark.parametrize(
    ("table", "source_ref", "expected", "category"),
    [
        (
            [[str(value) for value in range(1, 12)], ["24", "ТССЦ-301-1527", "Светильник", "61", "8762,5"]],
            "/project/Сметы/PDF/локальная-смета.pdf#page=6#table=1",
            "ESTIMATE: сметные расчёты и ресурсные строки",
            "engineering",
        ),
        (
            [["Модель", "Количество", "блок", "Описание"], ["LUM-HE252", "1", "шт", "Наружный блок"]],
            "/project/ОВ.pdf#page=10#table=1",
            "HVAC/EQUIPMENT: подбор и характеристики оборудования",
            "engineering",
        ),
        (
            [["Изделие", "Поправочный коэффициент"], ["Трубопровод (охлаждение)", "0,948"]],
            "/project/ОВ.pdf#page=11#table=1",
            "HVAC/CALC: поправочные коэффициенты подбора",
            "engineering",
        ),
        (
            [["№", "Длина(m)", "Диаметр трубопровода"], ["1", "26,00", "Φ22.2/Φ12.7"]],
            "/project/ОВ.pdf#page=12#table=1",
            "HVAC/PIPE: длины и диаметры трубопроводов",
            "engineering",
        ),
        (
            [["Номер", "Наименование изделия", "Комплектность"], ["110102", "Колодец ККС", "Верхний элемент"]],
            "/project/ЛКС.pdf#page=15#table=1",
            "SPEC: спецификации оборудования/изделий/материалов",
            "engineering",
        ),
        (
            [["Обозначение", "Наименование", "Примечание"], ["ГОСТ Р 53295-2009", "Средства огнезащиты", ""]],
            "/project/ОЗР.pdf#page=2#table=1",
            "NORM: перечни нормативных документов",
            "navigation",
        ),
        (
            [["Обозначение", "Наименование", "Примечание"], ["395.01/B481.120100.1.6-КЖ", "Конструкции железобетонные", ""]],
            "/project/КЖ.pdf#page=5#table=1",
            "NAV: состав/содержание/ведомости документации",
            "navigation",
        ),
        (
            [["ИНН 7814723298", "КПП 781401001"], ["Банк получателя", "Сч. № 40702810455000010281"]],
            "/project/КП.pdf#page=1#table=1",
            "SERVICE: банковские реквизиты/счета",
            "service",
        ),
        (
            [["Поз.", "Эскиз"], ["4", "505 805"], ["5", "440"]],
            "/project/КЖ.pdf#page=8#table=2",
            "NOISE: фрагменты схем/выноски без табличной структуры",
            "noise",
        ),
        (
            [["NN п.п.", "Перечень актов освидетельствования скрытых работ", "Примечание"], ["1", "Акт на подготовку основания", ""]],
            "/project/КЖ.pdf#page=5#table=4",
            "NAV: перечень актов скрытых работ",
            "navigation",
        ),
        (
            [["Лист", "Наименование", "Примечание"], ["3", "Спецификация к схеме расположения элементов", ""]],
            "/project/КЖ.pdf#page=5#table=5",
            "NAV: ведомость листов комплекта",
            "navigation",
        ),
        (
            [["№", "Товары (работы, услуги)", "Количество", "Цена", "Сумма"], ["1", "Кабель", "300 м", "66,14", "19 841,02"]],
            "/project/Сметы/КП.pdf#page=2#table=1",
            "COMMERCIAL: коммерческие предложения и цены",
            "engineering",
        ),
        (
            [["Изделие", "Функциональные возможности", "Фактическое значение"], ["Общая длина трубопровода", "250 м", "89 м"]],
            "/project/ОВ.pdf#page=205#table=2",
            "HVAC/CALC: проверка ограничений трассы",
            "engineering",
        ),
        (
            [["(9)", "3,00", "Φ12.7/Φ6.35"], ["(10)", "5,00", "Φ25.4/Φ12.7"]],
            "/project/ОВ.pdf#page=194#table=1",
            "HVAC/PIPE: длины и диаметры трубопроводов",
            "engineering",
        ),
        (
            [["Обозначение", "Профиль", "Предел огнестойкости, мин", "Плита ТЕХНО ОЗМ, м3"], ["Б1", "I35Ш1", "90", "24,7"]],
            "/project/ОЗР.pdf#page=13#table=1",
            "FIRE/STRUCT: огнезащита металлоконструкций",
            "engineering",
        ),
        (
            [["Марка элемента", "Изделия арматурные", "Всего"], ["Фм3", "A500C ∅16", "3575"]],
            "/project/КЖ2.pdf#page=19#table=9",
            "STRUCT/REINF: арматура, сечения, материалы",
            "engineering",
        ),
        (
            [["Код сокращения", "Описание"], ["Tmp-C", "Indoor temperature in cooling"]],
            "/project/ОВ.pdf#page=207#table=5",
            "NAV: условные обозначения и сокращения",
            "navigation",
        ),
    ],
)
def test_semantic_classifier_recovers_high_signal_unknown_families(table, source_ref, expected, category):
    result = classify_project_table_semantic(table, source_ref=source_ref)

    assert result["semantic_type"] == expected
    assert result["category"] == category


def test_zero_level_mark_is_emitted_as_drawing_annotation_not_title_block_data():
    table = [
        ["ОТМ. 0.000 =", "Уровень чистого пола"],
        ["Изм. Кол. уч. Лист № док.", "Подпись", "Дата"],
    ]

    annotations = _drawing_annotation_candidates(table, source_ref="project/АР.pdf#page=1#table=2")

    assert len(annotations) == 1
    assert annotations[0]["semantic_type"] == "ANNOTATION: нулевая отметка чертежа"
    assert annotations[0]["category"] == "drawing_annotation"
    assert annotations[0]["sample"] == "отм. 0.000 ="
    assert annotations[0]["source_ref"] == "project/АР.pdf#page=1#table=2#row=1#cell=1"


def test_normalize_hvs_table_extracts_air_system_characteristics():
    table = [
        ["Система", "Обслуживаемые помещения", "Расход воздуха, м3/ч", "Давление, Па", "Тепловая мощность, кВт"],
        ["П1", "Лаборатории 2 этажа", "12000", "450", "38,5"],
    ]

    result = normalize_hvs_table(table, source_ref="ov.pdf#page=3#table=1")

    assert result["schema"] == "hvs_air_system_table_v1"
    row = result["rows"][0]
    assert row["schema"] == "hvs_air_system_row_v1"
    assert row["system_id"] == "П1"
    assert row["served_zone"] == "Лаборатории 2 этажа"
    assert row["airflow_m3h"] == 12000
    assert row["pressure_pa"] == 450
    assert row["heat_load_kw"] == 38.5
    assert row["source_ref"] == "ov.pdf#page=3#table=1#row=2"


def test_normalize_water_balance_table_extracts_vk_balances():
    table = [
        ["Потребитель", "Холодная вода, м3/сут", "Горячая вода, м3/сут", "Водоотведение, м3/сут"],
        ["Здание ИЦ", "12,4", "4.2", "15,8"],
    ]

    result = normalize_water_balance_table(table, source_ref="vk.pdf#page=5#table=2")

    assert result["schema"] == "vk_water_balance_table_v1"
    row = result["rows"][0]
    assert row["schema"] == "vk_water_balance_row_v1"
    assert row["consumer"] == "Здание ИЦ"
    assert row["cold_water_m3_day"] == 12.4
    assert row["hot_water_m3_day"] == 4.2
    assert row["wastewater_m3_day"] == 15.8


def test_normalize_room_explication_table_extracts_rooms():
    table = [
        ["Номер помещения", "Наименование помещения", "Площадь, м2", "Категория"],
        ["101", "Котельная", "24,6", "Г"],
        ["102", "Насосная", "18.1", "Д"],
    ]

    result = normalize_room_explication_table(table, source_ref="ar.pdf#page=10#table=1")

    assert result["schema"] == "room_explication_table_v1"
    assert len(result["rows"]) == 2
    assert result["rows"][0]["room_number"] == "101"
    assert result["rows"][0]["room_name"] == "Котельная"
    assert result["rows"][0]["area_m2"] == 24.6
    assert result["rows"][0]["category"] == "Г"


def test_summarize_project_table_manifests_builds_navigation():
    manifest = {
        "schema": "project_pdf_table_manifest_v1",
        "file_name": "АР/plans.pdf",
        "summary": {
            "detected_tables": 2,
            "hvs_rows": 0,
            "water_balance_rows": 0,
            "room_explication_rows": 2,
            "semantic_table_types": {
                "ROOM: экспликации помещений": 1,
                "SERVICE: штампы/основные надписи/рамки": 1,
            },
        },
        "pages": [
            {
                "source_ref": "plans.pdf#page=1",
                "room_explication_rows_total": 2,
                "table_type_candidates": [
                    {
                        "source_ref": "plans.pdf#page=1#table=1",
                        "semantic_type": "ROOM: экспликации помещений",
                    },
                    {
                        "source_ref": "plans.pdf#page=1#table=2",
                        "semantic_type": "SERVICE: штампы/основные надписи/рамки",
                    },
                ],
            }
        ],
    }

    summary = summarize_project_table_manifests([manifest])

    assert summary["schema"] == "project_pdf_table_summary_v1"
    assert summary["summary"]["detected_tables"] == 2
    assert summary["summary"]["room_explication_rows"] == 2
    assert summary["summary"]["semantic_table_types"]["ROOM: экспликации помещений"] == 1
    assert summary["source_navigation"][0]["role"] == "экспликация помещений"
    assert summary["source_navigation"][0]["source_refs"] == ["plans.pdf#page=1"]
    assert any(row["role"] == "ROOM: экспликации помещений" for row in summary["source_navigation"])


def test_common_project_composition_table_is_not_misread_as_domain_table():
    table = [
        ["Обозначение", "Наименование", "Примечание"],
        ["1", "Пояснительная записка", "1 лист"],
        ["2", "Система водоснабжения", "4 листа"],
    ]

    assert normalize_hvs_table(table, source_ref="contents.pdf#page=1#table=1") is None
    assert normalize_water_balance_table(table, source_ref="contents.pdf#page=1#table=1") is None
    assert normalize_room_explication_table(table, source_ref="contents.pdf#page=1#table=1") is None
    assert classify_project_table(table, page_text_norm="состав проектной документации")["table_type"] == "unknown"


def test_waste_table_is_not_misread_as_water_balance_from_page_text():
    table = [
        ["Наименование образующихся отходов", "Код по ФККО", "Класс опасности", "Количество, т", "м3"],
        ["Мусор от офисных помещений", "7 33 100", "IV", "1,2", "3,4"],
    ]

    classification = classify_project_table(table, page_text_norm="водопотребление водоотведение")

    assert classification["table_type"] == "unknown"
    assert normalize_water_balance_table(table, source_ref="oos.pdf#page=56#table=2") is None


def test_classify_project_table_reads_header_before_content():
    table = [
        ["Номер помещения", "Наименование помещения", "Площадь, м2", "Категория"],
        ["101", "Котельная", "24,6", "Г"],
    ]

    classification = classify_project_table(table, context_norm="Экспликация помещений")

    assert classification["table_type"] == "room_explication"
    assert classification["basis"] == "header_context"


def test_hvs_skips_column_number_and_section_rows():
    table = [
        ["Обозначение системы", "Наименование обслуживаемого помещения", "Тип установки", "L, м3/ч"],
        ["1", "2", "3", "4"],
        ["Отопление", "", "", ""],
        ["П1", "Производственный цех", "Приточная установка", "12000"],
    ]

    result = normalize_hvs_table(table, source_ref="ov.pdf#page=1#table=1")

    assert result["row_count"] == 1
    assert result["rows"][0]["system_id"] == "П1"


def test_semantic_classifier_detects_structural_calculation_table():
    table = [
        ["Результаты расчета", "Пролет", "Участок", "Коэффициент использования", "Проверка"],
        ["", "1", "1", "0,256", "Прочность"],
    ]

    result = classify_project_table_semantic(table, source_ref="kr.pdf#page=43#table=1")

    assert result["semantic_type"] == "STRUCT/CALC: результаты расчётов и проверки конструкций"
    assert result["category"] == "engineering"


def test_semantic_classifier_detects_environment_noise_table():
    table = [
        ["№ п/п", "Наименование ИШ", "Описание ИШ", "Примечания"],
        ["1", "Вентилятор", "Источник шума", ""],
    ]

    result = classify_project_table_semantic(table, source_ref="oos.pdf#page=17#table=2")

    assert result["semantic_type"] == "ENV/ACOUSTIC: источники шума и акустические расчёты"


def test_semantic_classifier_detects_acoustic_calculation_grid():
    table = [
        ["1", "2", "3", "4", "5", "6", "7", "8"],
        ["Октавные уровни звуковой мощности вентилятора, LwA, дБА", "0", "52", "60", "67", "71", "65", "62"],
    ]

    result = classify_project_table_semantic(table, source_ref="noise.pdf#page=3#table=1")

    assert result["semantic_type"] == "ENV/ACOUSTIC: источники шума и акустические расчёты"


def test_semantic_classifier_marks_volume_composition_as_navigation_not_service():
    table = [
        ["АКЦИОНЕРНОЕ ОБЩЕСТВО «РОСИНЖИНИРИНГ»"],
        ["№ тома", "Обозначение", "Наименование раздела, подраздела", "Приме- чание"],
        ["5.5.5", "395.01/B481.120100.2.4-ИОС.СС5", "Автоматизация комплексная. Здание инновационного центра", ""],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=9#table=1")

    assert result["semantic_type"] == "NAV: состав/содержание/ведомости документации"
    assert result["category"] == "navigation"


def test_semantic_classifier_marks_single_row_toc_fragment_as_navigation():
    table = [
        [
            "ПОЯСНИТЕЛЬНАЯ ЗАПИСКА ОГЛАВЛЕНИЕ 1 ОСНОВАНИЕ ДЛЯ ПРОЕКТИРОВАНИЯ "
            "............................................................. 2 2 ИСХОДНЫЕ ДАННЫЕ ДЛЯ ПРОЕКТИРОВАНИЯ"
        ]
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=6#table=1")

    assert result["semantic_type"] == "NAV: состав/содержание/ведомости документации"
    assert result["category"] == "navigation"


def test_semantic_classifier_marks_electrical_sheet_register_as_navigation():
    table = [
        ["ЩРО. Схема электрическая принципиальная", "Лист 23"],
        ["ЩО1.1.1. Схема электрическая принципиальная", "Лист 24 (7 листов)"],
    ]

    result = classify_project_table_semantic(table, source_ref="es.pdf#page=6#table=2")

    assert result["semantic_type"] == "NAV: состав/содержание/ведомости документации"
    assert result["category"] == "navigation"


def test_semantic_classifier_detects_automation_control_table():
    table = [
        ["Щит управления", "Системы", "Место установки щита"],
        ["ЩУВ-П1В1", "П1В1", "пом. 401"],
    ]

    result = classify_project_table_semantic(table, source_ref="ss5.pdf#page=1#table=2")

    assert result["semantic_type"] == "AUTOMATION: контакты, клеммы, цепи, I/O"


def test_semantic_classifier_marks_lowcurrent_diagram_labels_as_noise():
    table = [
        ["Сброс", "=24B"],
        ["Тревога модуля 1"],
        ["Тревога модуля 2"],
        ["Неисправность модуля 1"],
        ["Неисправность модуля 2"],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=55#table=6")

    assert result["semantic_type"] == "NOISE: фрагменты схем/выноски без табличной структуры"
    assert result["category"] == "noise"


def test_semantic_classifier_detects_fire_resistance_table():
    table = [
        ["№ п.п", "Наименование конструкции", "Пределы огнестойкости, не менее"],
        ["1", "Несущие элементы здания", "R 90"],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=28#table=2")

    assert result["semantic_type"] == "FIRE: эвакуация, АУПТ и пожарный риск"


def test_semantic_classifier_detects_fire_scenario_table():
    table = [
        ["Наименование сценария", "Расположение очага пожара", "Очаг пожара", "Параметры очага пожара"],
        ["Сценарий 1", "Этаж 1, Помещение 19", "Очаг пожара 1", "Горючая нагрузка: кабели и провода"],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=112#table=2")

    assert result["semantic_type"] == "FIRE: эвакуация, АУПТ и пожарный риск"


def test_semantic_classifier_detects_aupt_parameter_table():
    table = [
        ["Защищаемые помещения", "Производственные помещения"],
        ["Вид АУВПТ", "Водозаполненная спринклерная"],
        ["Интенсивность орошения", "0,12 л/(с*м2)"],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=24#table=2")

    assert result["semantic_type"] == "FIRE/AUPT: параметры автоматического пожаротушения"


def test_semantic_classifier_detects_fire_risk_presence_rows():
    table = [
        ["Сотрудник офиса 33", "8", "247", "1976"],
        ["Сотрудник производственного цеха", "8", "247", "1976"],
        ["Обслуживающий персонал", "6", "247", "1482"],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=106#table=2")

    assert result["semantic_type"] == "FIRE/RISK: исходные данные по присутствию людей"


def test_semantic_classifier_detects_spec_header_before_catalog_or_qty():
    table = [
        ["Поз.", "Обозначение", "Наименование", "Кол.", "Ед. изм.", "Примечание"],
        ["З.1-3.3", "", "Задвижка DN200 с обрезиненным клином Гранар серии К R14", "6", "шт.", "АДЛ или аналог"],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=67#table=2")

    assert result["semantic_type"] == "SPEC: спецификации оборудования/изделий/материалов"


def test_semantic_classifier_detects_hvac_heat_loss_table():
    table = [
        ["Тип ограждения", "Площадь [m2]", "K [Вт/m2K]", "dT [C]", "Q [Вт]"],
        ["Пол", "2,2", "0,2", "40", "17"],
        ["Теплопотери на инфильтрацию", "0,15", "[1/h]", "40", "16"],
    ]

    result = classify_project_table_semantic(table, source_ref="ov.pdf#page=64#table=2")

    assert result["semantic_type"] == "HVAC/HEAT: теплопотери и инфильтрация помещений"


def test_semantic_classifier_detects_hvac_heat_loss_rows_without_header():
    table = [
        ["Наружная стена", "НС2", "29,5", "0,31", "42", "391"],
        ["Окно", "НО2", "13,4", "2", "42", "1129"],
        ["Кровля", "НП2", "3301,5", "0,19", "41", "25719"],
    ]

    result = classify_project_table_semantic(table, source_ref="ov.pdf#page=68#table=2")

    assert result["semantic_type"] == "HVAC/HEAT: теплопотери и инфильтрация помещений"


def test_semantic_classifier_detects_air_exchange_table_from_short_headers():
    table = [
        [
            "Номер помещения",
            "Наименование помещения",
            "Площадь A, м2",
            "Кратн. притока",
            "Кратн. вытяжки",
            "Приток Lпр, м3/ч",
            "Вытяжка Lвыт, м3/ч",
        ],
        ["151", "Насосная", "24,5", "2", "3", "150", "220"],
    ]

    result = classify_project_table_semantic(table, source_ref="ov.pdf#page=46#table=1")

    assert result["semantic_type"] == "HVAC: таблицы воздухообменов"


def test_semantic_classifier_detects_acoustic_source_input_table():
    table = [
        ["1", "2", "3", "4", "5", "6", "7"],
        ["Режим работы источника:", "постоянный"],
        ["Продолжительность работы в дневной период (7.00-23.00):", "16 час"],
        ["Тип источника шума:", "вентиляционная система"],
        ["Тип вентсистемы:", "вытяжная"],
    ]

    result = classify_project_table_semantic(table, source_ref="noise.pdf#page=4#table=1")

    assert result["semantic_type"] == "ENV/ACOUSTIC: источники шума и акустические расчёты"


def test_semantic_classifier_detects_acoustic_uzd_pdu_rows():
    table = [
        ["РТ-14", "УЗД днём", "34,1", "29,1", "24,4", "19,2", "15,4"],
        ["", "ПДУ", "75", "66", "59", "54", "50"],
        ["", "превышение", "-40,9", "-36,9", "-34,6", "-34,8", "-34,6"],
    ]

    result = classify_project_table_semantic(table, source_ref="szz.pdf#page=23#table=2")

    assert result["semantic_type"] == "ENV/ACOUSTIC: источники шума и акустические расчёты"


def test_semantic_classifier_detects_acoustic_envelope_input_table():
    table = [
        ["Исходные данные", "Материал", "Толщина, м", "Плотность, кг/м3", "К", "mэкв, кг/м3"],
        ["несущая часть", "железобетон", "0,15", "2500", "1", "375"],
    ]

    result = classify_project_table_semantic(table, source_ref="oos2.pdf#page=36#table=3")

    assert result["semantic_type"] == "ENV/ACOUSTIC: источники шума и акустические расчёты"


def test_semantic_classifier_detects_acoustic_db_a_table():
    table = [
        ["Уровень акустической мощности [dB(A)]", "Частота", "63 [Hz]", "125 [Hz]", "Lw [dB(A)]"],
        ["", "", "70", "68", "75"],
    ]

    result = classify_project_table_semantic(table, source_ref="oos2.pdf#page=70#table=2")

    assert result["semantic_type"] == "ENV/ACOUSTIC: источники шума и акустические расчёты"


def test_semantic_classifier_detects_lighting_keo_table():
    table = [
        ["Разряд зрительных работ", "Нормативные значение КЕО eн, %"],
        ["V", "1,0", "0,3"],
    ]

    result = classify_project_table_semantic(table, source_ref="es.pdf#page=29#table=2")

    assert result["semantic_type"] == "ELEC/LIGHT: освещение, КЕО и светотехнические нормы"


def test_semantic_classifier_detects_energy_passport_table():
    table = [
        ["Наименование расчетных параметров", "Обозначение и единица измерения", "Расчетное значение"],
        ["Продолжительность отопительного периода", "zот, сут/год", "213"],
        ["Градусо-сутки отопительного периода", "ГСОП", "5380"],
    ]

    result = classify_project_table_semantic(table, source_ref="ee.pdf#page=37#table=2")

    assert result["semantic_type"] == "ENERGY: теплотехнические и энергоэффективные расчёты"


def test_semantic_classifier_detects_structural_element_sections_not_catalog():
    table = [
        ["№ констр. эл.", "Тип КЭ", "Сечение", "Материал", "Параметры конструирования"],
        ["43", "10", "37. Коробка прок. 140 x 140 x 8", "2. Ст. пр. БД (C345)", "12. Подстроп раскос"],
    ]

    result = classify_project_table_semantic(table, source_ref="kr.pdf#page=137#table=2")

    assert result["semantic_type"] == "STRUCT/REINF: арматура, сечения, материалы"


def test_semantic_classifier_detects_structural_load_rows():
    table = [
        ["Тип нагрузки", "Величина"],
        ["пролет 1, длина = 2 м", "0,756", "Т/м"],
        ["пролет 2, длина = 2 м", "0,756", "Т/м"],
    ]

    result = classify_project_table_semantic(table, source_ref="kr.pdf#page=27#table=3")

    assert result["semantic_type"] == "STRUCT/LOAD: нагрузки и сочетания"


def test_semantic_classifier_detects_environment_soil_table():
    table = [
        ["№ пробы (по акту отбора)", "Глуб. отбора, м", "Группа почв", "pH сол", "Zc", "Категория по Zc"],
        ["01/1-32", "0,0-0,2", "СГ", "4,9", "8,2", "Допустимая"],
    ]

    result = classify_project_table_semantic(table, source_ref="oos.pdf#page=34#table=3")

    assert result["semantic_type"] == "ENV/SOIL: почвы и загрязнение грунтов"


def test_semantic_classifier_detects_staff_shift_table():
    table = [
        ["№", "Наименование участка/помещения", "Наименование профессии", "Всего", "В том числе по сменам"],
        ["1", "Станок по производству сетки", "Рабочий", "6", "2 | 2 | 2"],
    ]

    result = classify_project_table_semantic(table, source_ref="oos.pdf#page=20#table=3")

    assert result["semantic_type"] == "TEP/STAFF: численность и сменность персонала"


def test_semantic_classifier_marks_drawing_fragments_as_noise():
    table = [
        ["PE", "40. 02", "40. 12", "N"],
        ["N", "PE", "N", "PE"],
    ]

    result = classify_project_table_semantic(table, source_ref="ss5.pdf#page=13#table=19")

    assert result["semantic_type"] == "NOISE: фрагменты схем/выноски без табличной структуры"


def test_semantic_classifier_marks_dotted_scheme_numbers_as_noise():
    table = [
        ["40. 12", "40. 410", "40. 310"],
        ["40. 32", "40. 410", "40. 510"],
    ]

    result = classify_project_table_semantic(table, source_ref="ss5.pdf#page=13#table=13")

    assert result["semantic_type"] == "NOISE: фрагменты схем/выноски без табличной структуры"


def test_semantic_classifier_marks_fire_lowcurrent_drawing_fragments_as_noise():
    table = [
        ["ШПС .1 17 Ач 17 Ач", "БК 24"],
        ["=24B", "=24B 1", "=24B 2"],
        ["РИП.1", "КДЛ", "СП2"],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=65#table=3")

    assert result["semantic_type"] == "NOISE: фрагменты схем/выноски без табличной структуры"


def test_semantic_classifier_marks_access_control_drawing_fragments_as_noise():
    table = [
        ["пом. 147 ИМ-1.1.1 ИМ-1.1.2"],
        ["UZ-1.1.1", "UZ-1.1.2"],
        ["ДПЛС 06 ППК-06 ШОС-06 ~220В"],
    ]

    result = classify_project_table_semantic(table, source_ref="ss2.pdf#page=44#table=2")

    assert result["semantic_type"] == "NOISE: фрагменты схем/выноски без табличной структуры"


def test_semantic_classifier_detects_room_list_fragment():
    table = [
        ["211", "Кладовая уборочного инвентаря", "3.49", "В4"],
        ["213", "Помещение СС", "8.29", "В4"],
        ["215", "Кладовая уборочного инвентаря", "3.49", "В4"],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=38#table=2")

    assert result["semantic_type"] == "ROOM: экспликации помещений"


def test_semantic_classifier_detects_room_area_fragment():
    table = [
        ["41", "раздевалка", "11,9"],
        ["42", "душевая", "1,6"],
        ["43", "умывальная", "1,7"],
        ["44", "туалет", "1,6"],
    ]

    result = classify_project_table_semantic(table, source_ref="iikeo.pdf#page=66#table=1")

    assert result["semantic_type"] == "ROOM: экспликации помещений"


def test_semantic_classifier_marks_extracted_paragraph_as_text_noise():
    table = [
        [
            "Аппаратура управления переходит в режим Неисправность при обнаружении неисправности, "
            "регистрации сигнала неисправности подключенного сигнального устройства, обрыве или "
            "коротком замыкании пожарного шлейфа сигнализации, а также получении сигнала "
            "неисправности устройств контроля оборудования пожаротушения."
        ],
        ["При формировании сигнала пожар система выполняет алгоритмы управления."],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=44#table=1")

    assert result["semantic_type"] == "TEXT: фрагменты пояснительной записки/абзацы"
    assert result["category"] == "noise"


def test_semantic_classifier_marks_single_row_extracted_paragraph_as_text_noise():
    table = [
        [
            "В соответствии с заданием на проектирование, для защиты помещений производственной части здания, "
            "проектом предусматривается спринклерная автоматическая установка водяного пожаротушения "
            "с водозаполненными кольцевыми питающими трубопроводами."
        ]
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=18#table=1")

    assert result["semantic_type"] == "TEXT: фрагменты пояснительной записки/абзацы"
    assert result["category"] == "noise"


def test_semantic_classifier_detects_fire_current_mojibake_table():
    table = [
        ["Ïðèáîð", "Ïîòðåáèòåëü", "Êîë-âî, øò.", "Òîê ïîòðåáëåíèÿ, ìÀ", "Ñóììàðíûé òîê"],
        ["Ñ2000", "ÄÏËÑ", "2", "40", "80"],
    ]

    result = classify_project_table_semantic(table, source_ref="pb.pdf#page=27#table=1")

    assert result["semantic_type"] == "FIRE/LOWCURRENT: расчёты токопотребления ПС/СОУЭ/АУПТ"


def test_semantic_classifier_marks_numeric_grid_as_noise():
    table = [
        ["1", "2", "3", "4", "5", "6"],
        ["1", "2", "3", "4", "5", "6"],
    ]

    result = classify_project_table_semantic(table, source_ref="plan.pdf#page=1#table=1")

    assert result["semantic_type"] == "NOISE: строки-нумераторы/разорванные табличные сетки"
    assert result["category"] == "noise"


def test_semantic_classifier_does_not_treat_generic_line_parameters_as_cable_table():
    table = [
        ["Параметр", "Описание", "Количество линий"],
        ["Шаблон линии", "Длина линии", "1"],
    ]

    result = classify_project_table_semantic(table, source_ref="revit-guide.pdf#page=12#table=1")

    assert result["semantic_type"] != "ELEC/LINE: кабельные и линейные таблицы"


def test_semantic_classifier_requires_work_unit_and_quantity_for_vor():
    table = [
        ["Параметр", "Описание", "Количество"],
        ["Типоразмер", "Количество экземпляров элемента", "2"],
    ]

    result = classify_project_table_semantic(table, source_ref="revit-guide.pdf#page=18#table=1")

    assert result["semantic_type"] != "QTY: ведомости объёмов/работ"


def test_semantic_navigation_skips_text_noise_rows():
    manifest = {
        "schema": "project_pdf_table_manifest_v1",
        "file_name": "ПЗ/pz.pdf",
        "summary": {
            "detected_tables": 1,
            "hvs_rows": 0,
            "water_balance_rows": 0,
            "room_explication_rows": 0,
            "semantic_table_types": {"TEXT: фрагменты пояснительной записки/абзацы": 1},
        },
        "pages": [
            {
                "source_ref": "pz.pdf#page=20",
                "table_type_candidates": [
                    {
                        "source_ref": "pz.pdf#page=20#table=1",
                        "semantic_type": "TEXT: фрагменты пояснительной записки/абзацы",
                    }
                ],
            }
        ],
    }

    summary = summarize_project_table_manifests([manifest])

    assert summary["summary"]["semantic_table_types"]["TEXT: фрагменты пояснительной записки/абзацы"] == 1
    assert summary["source_navigation"] == []


def test_summary_keeps_semantic_type_counts_from_manifest_pages():
    manifest = {
        "schema": "project_pdf_table_manifest_v1",
        "file_name": "ОВ/ov.pdf",
        "summary": {
            "detected_tables": 1,
            "hvs_rows": 1,
            "water_balance_rows": 0,
            "room_explication_rows": 0,
            "semantic_table_types": {"HVAC: характеристики воздушных систем ХВС": 1},
        },
        "pages": [
            {
                "source_ref": "ov.pdf#page=3",
                "hvs_rows_total": 1,
                "table_type_candidates": [
                    {
                        "source_ref": "ov.pdf#page=3#table=1",
                        "semantic_type": "HVAC: характеристики воздушных систем ХВС",
                    }
                ],
            }
        ],
    }

    summary = summarize_project_table_manifests([manifest])

    assert summary["summary"]["semantic_table_types"]["HVAC: характеристики воздушных систем ХВС"] == 1
    assert any(row["role"] == "HVAC: характеристики воздушных систем ХВС" for row in summary["source_navigation"])
