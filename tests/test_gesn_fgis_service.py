"""ФГИС ЦС источник ГЭСН: вывод тарифного кода труда по разряду (без сети)."""
from __future__ import annotations
from proxy.services.gesn_fgis_service import _derive_labor_code, _is_real_code


def test_derive_labor_code_from_razryad():
    assert _derive_labor_code("Средний разряд работы 2,5") == "1-100-25"
    assert _derive_labor_code("Средний разряд работы 3.6") == "1-100-36"
    assert _derive_labor_code("Бруски обрезные хвойных пород") is None


def test_is_real_code():
    assert _is_real_code("91.05.01-017") and _is_real_code("1-100-36")
    assert not _is_real_code("—") and not _is_real_code("2") and not _is_real_code("")
