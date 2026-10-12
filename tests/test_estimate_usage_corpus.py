"""Корпус применённых расценок: перевод ТЕР→ГЭСН, вес раздела, границы применения.

Основание — разбор архива готовых смет 09.09.2026: 9 655 строк с кодами ТЕР, из них
95 % нашлись в ФСНБ-2022 по тому же номеру и 91 % совпали названием. Раздел связи
закрывается 130 нормами вместо 49 747 в базе.
"""

from __future__ import annotations

import json
import re

import pytest

from proxy.smeta_core.estimate_usage import (
    section_examples,
    usage_evidence,
    usage_reason,
)
from proxy.smeta_core.section_taxonomy import classify_estimate
from tools.build_estimate_usage_corpus import document_kind, norm_code_of, read_header


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        ("ТЕРм10-03-001-01", "ГЭСНм10-03-001-01"),
        ("ФЕРм08-02-148-01", "ГЭСНм08-02-148-01"),
        ("ТЕР15-01-092-02", "ГЭСН15-01-092-02"),
        ("ТЕРр65-04-006-14", "ГЭСНр65-04-006-14"),
        ("ТЕРп02-02-003-01", "ГЭСНп02-02-003-01"),
        ("ТЕРм10-03-001-01 ИНДЕКС К ПОЗИЦИИ", "ГЭСНм10-03-001-01"),
        ("ГЭСНм10-03-001-01", ""),
        ("ФССЦ-25.2.01.01", ""),
        ("", ""),
    ],
)
def test_rate_code_translates_to_the_federal_norm(rate: str, expected: str) -> None:
    """Территориальная расценка отличается от нормы только семейством в префиксе."""
    assert norm_code_of(rate) == expected


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("02-05-03 СКС МФЗ2 v3.xlsx", "communications"),
        ("01-01-17.1 СКС.СС Э25.2 v1.xlsx", "communications"),
        ("01-01-13.1 КИТСО СКУД кн1 Э25.2 v1.xlsx", "security"),
        ("01-01-14.1 КИТСО СОТ Э25.2 v1.xlsx", "security"),
        # Шифр комплекса сильнее шифра подраздела: «КИТСО ЭС» — электроснабжение
        # внутри охранного комплекса, и нормы там ближе к охранным системам.
        ("01-01-15 КИТСО ЭС Э25.2 v1.xlsx", "security"),
        ("05-03 ЭОМ Б4 v3.xlsx", "electrical"),
        ("05-02 ОВиК Б4 v3.xlsx", "hvac"),
        ("06-01 ВК Б4 v3.xlsx", "plumbing"),
        ("01-01-01.1и3 АР Д Э25.2 v5.xlsx", "architecture"),
        ("14-01-05 ЗИП СОУЭ Б1 v6 ВИСКО.xlsx", "fire_safety"),
        ("нечто безымянное.xlsx", ""),
    ],
)
def test_file_cipher_is_the_reserve_when_the_title_is_silent(file_name: str, expected: str) -> None:
    """Наименование «Демонтаж. Дополнительные работы» раздела не называет — его даёт шифр."""
    assert classify_estimate("", file_name) == expected


def test_title_outweighs_the_file_cipher() -> None:
    """Имя файла бывает унаследовано от соседней сметы, шапка — нет."""
    assert classify_estimate("Отопление", "02-03-02 ЭОМ Б4 v3.xlsx") == "hvac"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ № 02-05-03", "локальная"),
        ("ОБЪЕКТНЫЙ СМЕТНЫЙ РАСЧЕТ № 02-10", "объектная"),
        ("СВОДНЫЙ СМЕТНЫЙ РАСЧЕТ СТОИМОСТИ СТРОИТЕЛЬСТВА", "сводная"),
    ],
)
def test_summary_estimates_are_told_apart(line: str, expected: str) -> None:
    """Объектные и сводные расчёты складывают итоги локальных: их расценки — повтор."""
    assert document_kind(line) == expected


def test_header_gives_the_kind_and_the_title() -> None:
    """Шапка бланка: номер в одной строке, наименование до подписи «(наименование …)»."""
    rows = [
        ["СОГЛАСОВАНО:", "УТВЕРЖДАЮ:"],
        ["ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ № 01-01-01", ""],
        ["(локальная смета)", ""],
        ["", ""],
        ["на", "Демонтаж. Общестроительные работы. ЦДУ"],
        ["(наименование работ и затрат, наименование объекта)", ""],
        ["Основание: ОПГС-2018-МФК-СПБ-Э5-АР1.ЦДУ.Д", ""],
    ]
    assert read_header(rows) == ("локальная", "Демонтаж. Общестроительные работы. ЦДУ")


@pytest.fixture()
def corpus(tmp_path):
    payload = {
        "schema": "les.smeta.estimate-usage-corpus.v1",
        "sections": {
            "communications": {
                "files": 51,
                "applications": 1307,
                "norms": [
                    {"norm_code": "ГЭСНм10-02-051-01", "count": 48,
                     "unit": "100 перемычек", "title": "Перемычки кабельные длиной: до 6 м", "in_base": True},
                    {"norm_code": "ГЭСНм10-06-065-03", "count": 23,
                     "unit": "участок", "title": "Измерение на смонтированном участке ВОК", "in_base": True},
                    {"norm_code": "ГЭСНм11-04-028-01", "count": 65,
                     "unit": "шт", "title": "Включение в аппаратуру разъемов штепсельных", "in_base": True},
                    {"norm_code": "ГЭСНм10-04-087-02", "count": 1,
                     "unit": "шт", "title": "Устройство антенное развязывающее", "in_base": True},
                ],
            }
        },
    }
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_frequent_and_rare_are_told_apart(corpus):
    """Свидетельство различает единичный случай и постоянную практику."""
    frequent = usage_evidence("ГЭСНм11-04-028-01", "communications", path=corpus)
    rare = usage_evidence("ГЭСНм10-04-087-02", "communications", path=corpus)
    assert frequent["applications"] == 65
    assert rare["applications"] == 1
    assert "единичный случай" in rare["note"]


def test_absence_from_the_corpus_is_never_a_penalty(corpus):
    """Архив покрывает не все работы: о неизвестной норме просто нет свидетельства.

    В сметах применялись не все допустимые позиции — корпус задаёт вектор раздела,
    а не перечень разрешённого, и молчание архива ничего не доказывает.
    """
    assert usage_evidence("ГЭСНм10-06-016-01", "communications", path=corpus) == {}
    assert usage_evidence("ГЭСН15-03-002-01", "communications", path=corpus) == {}
    assert usage_evidence("ГЭСНм10-02-051-01", "hvac", path=corpus) == {}
    assert usage_evidence("ГЭСНм10-02-051-01", "", path=corpus) == {}


def test_missing_corpus_file_disables_the_hint_quietly(tmp_path):
    absent = str(tmp_path / "нет-такого.json")
    assert usage_evidence("ГЭСНм10-02-051-01", "communications", path=absent) == {}
    assert section_examples("communications", path=absent) == []


def test_reason_names_the_practice_for_the_check_sheet(corpus):
    reason = usage_reason("ГЭСНм10-02-051-01", "communications", path=corpus)
    assert "48 раз" in reason
    assert "100 перемычек" in reason
    assert usage_reason("ГЭСН15-03-002-01", "communications", path=corpus) == ""


def test_examples_are_ordered_by_practice(corpus):
    examples = section_examples("communications", limit=3, path=corpus)
    assert [item["norm_code"] for item in examples] == [
        "ГЭСНм11-04-028-01",
        "ГЭСНм10-02-051-01",
        "ГЭСНм10-06-065-03",
    ]
    assert examples[0]["unit"] == "шт"


def test_search_norm_shows_the_practice_without_reordering(monkeypatch, corpus):
    """Практика раздела объясняет кандидата, но очередь не переставляет.

    Живой случай: для патч-кордов лексический поиск предлагает прокладку кабеля, тогда
    как в 48 сметах связи эту работу закрывают «Перемычками кабельными до 6 м». Раньше
    практика поднимала вторую норму наверх; ревью 10.09 показало, что таким весом из
    выдачи вытеснялись редкие верные нормы, поэтому теперь порядок остаётся за текстом,
    а модель видит основание рядом с кандидатом.
    """
    from proxy.services import estimate_harness_service as harness
    from proxy.smeta_core import estimate_usage
    import proxy.smeta_core.norm_browser as browser

    monkeypatch.setattr(estimate_usage, "corpus_path", lambda: __import__("pathlib").Path(corpus))
    estimate_usage._load_corpus_cached.cache_clear()
    estimate_usage._section_index_cached.cache_clear()

    cards = [
        {"norm_code": "ГЭСНм10-01-055-02", "title": "Прокладка кабеля по стене", "measure_unit": "100 м"},
        {"norm_code": "ГЭСНм10-02-051-01", "title": "Перемычки кабельные до 6 м", "measure_unit": "100 перемычек"},
    ]
    monkeypatch.setattr(browser, "browse_norms", lambda *a, **k: {"cards": cards})

    result = harness.search_norm("Монтаж патч-корда 2 м", top_k=2, discipline="communications")
    codes = [c["norm_code"] for c in result["candidates"]]
    assert codes == ["ГЭСНм10-01-055-02", "ГЭСНм10-02-051-01"]

    practised = result["candidates"][1]
    assert practised["usage_evidence"]["applications"] == 48
    assert "48 раз" in practised["usage_reason"]
    # Порядок задаёт только текстовое сходство.
    assert result["candidates"][0]["score_total"] > practised["score_total"]


def test_norm_outside_the_corpus_keeps_its_place(monkeypatch, corpus):
    """Отсутствие в корпусе не отбрасывает кандидата: архив покрывает не все работы."""
    from proxy.services import estimate_harness_service as harness
    from proxy.smeta_core import estimate_usage
    import proxy.smeta_core.norm_browser as browser

    monkeypatch.setattr(estimate_usage, "corpus_path", lambda: __import__("pathlib").Path(corpus))
    estimate_usage._load_corpus_cached.cache_clear()
    estimate_usage._section_index_cached.cache_clear()

    cards = [
        {"norm_code": "ГЭСНм10-06-016-01", "title": "Разделка концов ВОК", "measure_unit": "1 разделка"},
        {"norm_code": "ГЭСНм10-04-087-02", "title": "Устройство антенное", "measure_unit": "шт"},
    ]
    monkeypatch.setattr(browser, "browse_norms", lambda *a, **k: {"cards": cards})

    result = harness.search_norm("Разделка оптического кабеля", top_k=2, discipline="communications")
    codes = [c["norm_code"] for c in result["candidates"]]
    # Норма вне корпуса первая в выдаче и остаётся первой: молчание архива не штрафует.
    assert codes[0] == "ГЭСНм10-06-016-01"
    assert not result["candidates"][0]["usage_evidence"]


def test_exclusion_is_by_path_not_by_name(tmp_path, monkeypatch):
    """Отбор по имени вычистил бы чужие проекты, оставив свой — это утечка.

    В архиве одно и то же имя файла («01-01-01 АР Д …») встречается в разных проектах.
    Разделение обучения и проверки идёт по каталогам, поэтому исключение сопоставляет
    относительный путь.
    """
    from tools import build_estimate_usage_corpus as builder

    root = tmp_path / "архив"
    for project in ("проект-А", "проект-Б"):
        (root / project).mkdir(parents=True)
        (root / project / "01-01-01 АР Д.xlsx").write_bytes(b"")

    seen: list[str] = []

    def fake_scan(path):
        seen.append(str(path.relative_to(root)).replace("\\", "/"))
        return []

    monkeypatch.setattr(builder, "scan_workbook", fake_scan)
    builder.build_corpus(root, base_path=tmp_path / "нет.sqlite", exclude={"проект-Б"})

    assert seen == ["проект-А/01-01-01 АР Д.xlsx"]


def test_corpus_marks_the_base_as_unchecked_when_it_is_missing(tmp_path, monkeypatch):
    """Без базы «есть в базе» неизвестно — это третье состояние, а не «да»."""
    from tools import build_estimate_usage_corpus as builder

    root = tmp_path / "архив"
    (root).mkdir(parents=True)
    (root / "02-05-03 СКС.xlsx").write_bytes(b"")
    monkeypatch.setattr(
        builder, "scan_workbook",
        lambda path: [{"kind": builder.LOCAL, "title": "Монтаж СКС", "section": "communications",
                       "norms": [("ГЭСНм10-01-055-02", "Прокладка кабеля", "100 м")]}],
    )

    corpus = builder.build_corpus(root, base_path=tmp_path / "нет.sqlite")
    assert corpus["base_checked"] is False
    assert corpus["sections"]["communications"]["norms"][0]["in_base"] is None
    assert corpus["revision"]


def test_empty_source_never_overwrites_a_working_corpus(tmp_path, capsys):
    """Отключённый диск не должен стирать корпус.

    10.09: архив на съёмном диске отпал после сна ноутбука, обход дал ноль строк, и
    рабочий корпус был перезаписан пустым файлом. Пустой результат — это отказ, а не
    результат.
    """
    from tools import build_estimate_usage_corpus as builder

    out = tmp_path / "corpus.json"
    out.write_text('{"schema": "старый", "sections": {"communications": {}}}', encoding="utf-8")
    missing = tmp_path / "нет-такого-каталога"

    code = builder.main(["--source", str(missing), "--out", str(out), "--base", str(tmp_path / "нет.sqlite")])

    assert code != 0
    assert "старый" in out.read_text(encoding="utf-8")
    assert "не найден" in capsys.readouterr().out.casefold()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Покрытие поверхностей грунтовкой: за 1 раз стен\nИНДЕКС К ПОЗИЦИИ:\n"
            "ТЕР15-04-006-03 01.2019 ОЗП=19",
            "Покрытие поверхностей грунтовкой: за 1 раз стен",
        ),
        (
            "Обеспыливание поверхности\nИНДЕКС К ПОЗИЦИИ:\nТЕР13-06-004-01 01.2019 ОЗП=19,069\n"
            "НР (2894 руб.): 77%",
            "Обеспыливание поверхности",
        ),
        ("Установка туалетных полочек\n(МАТ=0 к расх.)", "Установка туалетных полочек"),
        ("Прокладка кабеля, масса 1 м: до 1 кг", "Прокладка кабеля, масса 1 м: до 1 кг"),
        ("", ""),
    ],
)
def test_norm_title_drops_the_estimator_tail(raw: str, expected: str) -> None:
    """Наименование не должно тащить служебный хвост сметной программы.

    Владелец заметил риск: в архиве расценки территориальные, и хвост «ИНДЕКС К
    ПОЗИЦИИ: ТЕР15-04-006-03» попадал в корпус вместе с названием. Такой текст,
    дойдя до модели свидетельством, подсказывает ей несуществующий в базе шифр —
    в базе LES только ГЭСН, территориальных расценок там нет вовсе.
    """
    from tools.build_estimate_usage_corpus import clean_norm_title

    assert clean_norm_title(raw) == expected


def test_corpus_carries_no_territorial_codes(tmp_path, monkeypatch):
    """Страж: в собранном корпусе не должно остаться ни ТЕР, ни ФЕР."""
    from tools import build_estimate_usage_corpus as builder

    root = tmp_path / "архив"
    root.mkdir(parents=True)
    (root / "02-05-03 СКС.xlsx").write_bytes(b"")
    monkeypatch.setattr(
        builder, "scan_workbook",
        lambda path: [{
            "kind": builder.LOCAL, "title": "Монтаж СКС", "section": "communications",
            "norms": [(
                "ГЭСНм10-01-055-02",
                "Прокладка кабеля\nИНДЕКС К ПОЗИЦИИ:\nТЕР10-01-055-02 01.2019 ОЗП=19",
                "100 м",
            )],
        }],
    )

    corpus = builder.build_corpus(root, base_path=tmp_path / "нет.sqlite")
    dumped = json.dumps(corpus, ensure_ascii=False)
    # Ищем именно шифр расценки. Ссылка на техчасть сборника — «(ТЧ ТЕР 46 п.1.46.12)» —
    # часть официального названия нормы и остаётся на месте.
    assert not re.search(r"(?:ТЕР|ФЕР)[а-яa-z]*\d{2}-\d{2}-\d{3}", dumped)
    assert corpus["sections"]["communications"]["norms"][0]["title"] == "Прокладка кабеля"


def test_technical_part_reference_survives_the_cleanup() -> None:
    """«(ТЧ ТЕР 46 п.1.46.12)» — часть названия нормы, а не хвост сметной программы."""
    from tools.build_estimate_usage_corpus import clean_norm_title

    title = "Установка и разборка внутренних трубчатых инвентарных лесов: при высоте помещений до 6 м (ТЧ ТЕР 46 п.1.46.12)"
    assert clean_norm_title(title) == title


def test_unreadable_files_are_counted_and_block_a_silent_overwrite(tmp_path, monkeypatch):
    """Битые книги считаются, и корпус не переписывается молча неполным сводом.

    Ревью Codex 10.09: защита ловила только полностью пустой результат. Один читаемый
    файл и один повреждённый давали успешную перезапись неполным корпусом без единой
    зарегистрированной ошибки — а рабочий свод при этом терял часть архива.
    """
    from tools import build_estimate_usage_corpus as builder

    root = tmp_path / "архив"
    root.mkdir(parents=True)
    (root / "02-05-03 СКС.xlsx").write_bytes(b"")
    (root / "02-05-04 битая.xlsx").write_bytes(b"")

    def scan(path):
        if "битая" in path.name:
            raise ValueError("файл повреждён")
        return [{
            "kind": builder.LOCAL, "title": "Монтаж СКС", "section": "communications",
            "norms": [("ГЭСНм10-01-055-02", "Прокладка кабеля", "100 м")],
        }]

    monkeypatch.setattr(builder, "scan_workbook", scan)
    corpus = builder.build_corpus(root, base_path=tmp_path / "нет.sqlite")

    assert corpus["unreadable"] == ["02-05-04 битая.xlsx"]
    assert corpus["rows_total"] == 1


def test_main_refuses_to_overwrite_when_files_were_unreadable(tmp_path, monkeypatch, capsys):
    """Неполный обход — повод остановиться, а не переписать рабочий свод."""
    from tools import build_estimate_usage_corpus as builder

    root = tmp_path / "архив"
    root.mkdir(parents=True)
    (root / "02-05-03 СКС.xlsx").write_bytes(b"")
    (root / "02-05-04 битая.xlsx").write_bytes(b"")
    out = tmp_path / "corpus.json"
    out.write_text('{"schema": "рабочий свод"}', encoding="utf-8")

    def scan(path):
        if "битая" in path.name:
            raise ValueError("файл повреждён")
        return [{
            "kind": builder.LOCAL, "title": "Монтаж СКС", "section": "communications",
            "norms": [("ГЭСНм10-01-055-02", "Прокладка кабеля", "100 м")],
        }]

    monkeypatch.setattr(builder, "scan_workbook", scan)
    code = builder.main([
        "--source", str(root), "--out", str(out), "--base", str(tmp_path / "нет.sqlite"),
    ])

    assert code != 0
    assert "рабочий свод" in out.read_text(encoding="utf-8")
    assert "не прочитан" in capsys.readouterr().out.casefold()


def test_operator_can_accept_known_unreadable_files(tmp_path, monkeypatch, capsys):
    """Оператор может принять известные потери явным решением, а не молча.

    В архиве есть повреждённая книга «_Удельные показатели стоимости Б4 v3.xlsx» —
    справочная таблица, расценок не содержащая. Отказ по умолчанию верен, но должен
    существовать способ продолжить осознанно, оставив след в самом корпусе.
    """
    from tools import build_estimate_usage_corpus as builder

    root = tmp_path / "архив"
    root.mkdir(parents=True)
    (root / "02-05-03 СКС.xlsx").write_bytes(b"")
    (root / "битая.xlsx").write_bytes(b"")
    out = tmp_path / "corpus.json"

    def scan(path):
        if "битая" in path.name:
            raise ValueError("файл повреждён")
        return [{
            "kind": builder.LOCAL, "title": "Монтаж СКС", "section": "communications",
            "norms": [("ГЭСНм10-01-055-02", "Прокладка кабеля", "100 м")],
        }]

    monkeypatch.setattr(builder, "scan_workbook", scan)
    code = builder.main([
        "--source", str(root), "--out", str(out),
        "--base", str(tmp_path / "нет.sqlite"), "--allow-unreadable",
    ])

    assert code == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    # След остаётся в корпусе: потом видно, что свод собран не по всему архиву.
    assert written["unreadable"] == ["битая.xlsx"]
    assert written["rows_total"] == 1
    assert "битая.xlsx" in capsys.readouterr().out


def test_corpus_revision_notices_a_rebuild_within_one_second(tmp_path):
    """Посекундная точность не различала две пересборки одинакового размера подряд.

    Ревью Codex 10.09: кеш вариантов уже перешёл на наносекунды, кеш корпуса — нет,
    и повторная сборка того же объёма внутри секунды отдавала прежний свод.
    """
    import os
    from proxy.smeta_core.estimate_usage import corpus_revision

    target = tmp_path / "corpus.json"
    target.write_text('{"a": 1}', encoding="utf-8")
    first = corpus_revision(str(target))
    # Тот же размер, другое содержимое, то же время с точностью до секунды.
    stat = target.stat()
    target.write_text('{"a": 2}', encoding="utf-8")
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000))
    assert corpus_revision(str(target)) != first


def test_corpus_is_published_whole_or_not_at_all(tmp_path, monkeypatch):
    """Обрыв на середине не должен оставаться на диске под видом корпуса."""
    import importlib.util
    import json as _json

    spec = importlib.util.spec_from_file_location(
        "build_corpus_tool", "tools/build_estimate_usage_corpus.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    target = tmp_path / "nested" / "corpus.json"
    module._publish(target, {"schema": "les.smeta.estimate-usage.v1", "sections": {}})
    assert _json.loads(target.read_text(encoding="utf-8"))["schema"]
    assert list(target.parent.glob("*.partial")) == []

    previous = target.read_bytes()

    def _boom(*_args, **_kwargs):
        raise OSError("диск кончился на середине")

    monkeypatch.setattr(module.json, "dump", _boom)
    with pytest.raises(OSError):
        module._publish(target, {"schema": "другой", "sections": {}})
    assert target.read_bytes() == previous, "прежний корпус обязан пережить неудачную сборку"
    assert list(target.parent.glob("*.partial")) == []
