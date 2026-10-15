"""Regression for build 943: метаданные ЛСР не должны штамповться временем сборки.

Замерено сегодня на установленном 942 при проверке § 7 («пересчёт скачанных байтов») и § 1
(«скачивать актуальную ревизию без повторного выполнения завершённой работы»). Одно и то же
завершённое задание было пересобрано через `POST /api/chat/repack-lsr`:

    та же сессия, повтор      → тот же revision_id, те же 39 708 байт, sha `466159a87e6a18e0…`
    разные сессии             → 39 707 и 39 708 байт, sha `b0da81fd…` и `45ace3cc…`

Расхождение локализовано в одном элементе архива: `docProps/core.xml`
(«differing parts: ['docProps/core.xml']») — openpyxl писал туда текущее время. Арифметика,
строки, формулы и заявленные даты в листе не отличались вовсе. Правка фиксирует свойства
документа постоянной эпохой: дата, которую читает оператор, приходит из трассы и остаётся в
листе. Проверка сравнивает содержимое всех частей архива, а не сырые байты: метки времени
записей ZIP принадлежат упаковщику и ничего не значат для документа, тогда как `core.xml` —
это уже метаданные самого файла, и именно они делали «тот же документ» несовпадающим по
содержимому.
"""
from __future__ import annotations

import hashlib
import re
import zipfile

from proxy.services import rim_trace_xlsx_service as rim_xlsx
from tests.test_rim_trace_xlsx import _lsr_trace

PINNED_EPOCH = "2000-01-01T00:00:00Z"


def _members(path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in sorted(archive.namelist())}


def test_two_renders_of_one_trace_differ_by_no_content(tmp_path, monkeypatch):
    """Содержимое всех частей архива не зависит от того, во сколько собрали файл.

    openpyxl штамдует `dcterms:modified` в момент сохранения (writer/excel.py:292), поэтому тест
    сдвигает часы именно на сохранениях: без фиксации метаданных два рендера различались бы
    содержимым `docProps/core.xml`, а в пределах одной секунды тест прошёл бы случайно.
    Метки времени записей ZIP принадлежат упаковщику и в содержимое частей не входят, поэтому
    сравнение по частям — это сравнение документа, а не архивной обёртки.
    """
    import datetime as real_datetime
    from types import SimpleNamespace

    import openpyxl.writer.excel as excel_writer

    stamps = iter([real_datetime.datetime(2026, 10, 15, 9, 0),
                   real_datetime.datetime(2026, 10, 15, 10, 0)])

    class _ShiftedDateTime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            shifted = next(stamps)
            return shifted.replace(tzinfo=tz) if tz else shifted

    # openpyxl обращается к модулю datetime (datetime.datetime.now(...)), поэтому подменяется
    # именно имя модуля в этом пространстве имён, а не сам класс.
    monkeypatch.setattr(excel_writer, "datetime", SimpleNamespace(
        datetime=_ShiftedDateTime, timezone=real_datetime.timezone))
    trace = _lsr_trace()
    first = _members(rim_xlsx.render_lsr_xlsx(trace, tmp_path / "first.xlsx"))
    second = _members(rim_xlsx.render_lsr_xlsx(trace, tmp_path / "second.xlsx"))
    differing = [name for name in first if first[name] != second.get(name)]
    assert not differing, (
        "одна и та же трасса дала разное содержимое в частях архива "
        f"{differing}: метаданные файла штампуются текущим временем, и повторную доставку "
        "того же документа нельзя сверить по хешу")


def test_document_metadata_carries_no_wall_clock_timestamp(tmp_path):
    out = rim_xlsx.render_lsr_xlsx(_lsr_trace(), tmp_path / "meta.xlsx")
    with zipfile.ZipFile(out) as archive:
        core = archive.read("docProps/core.xml").decode("utf-8")
    assert PINNED_EPOCH in core, (
        "docProps/core.xml снова содержит метку времени сборки, а не зафиксированную эпоху; "
        "это делает пересборку невоспроизводимой")
    assert not re.search(r">20\d\d-\d\d-\d\dT(?!00:00:00Z)\d\d:", core), (
        f"в метаданных осталась не-эпохальная метка времени: {core[:400]}")
