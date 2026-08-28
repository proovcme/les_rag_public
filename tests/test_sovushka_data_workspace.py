from pathlib import Path

import pytest

from sovushka_ng import _canonical_workspace_tab


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("data", "data"),
        ("documents", "data"),
        ("datasets", "data"),
        ("mail", "chat"),
        ("studio", "chat"),
        ("cad_bim", "chat"),
        ("", "chat"),
    ],
)
def test_canonical_workspace_tab(requested, expected):
    assert _canonical_workspace_tab(requested) == expected


def test_legacy_redirect_preserves_the_complete_query_and_canonicalizes_storage():
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert "request.query_params.multi_items()" in shell
    assert 'if key != "tab"' in shell
    assert 'query_items.append(("tab", _canonical_tab))' in shell
    assert "urlencode(query_items, doseq=True)" in shell
    for old, current in (
        ("Документы", "Данные"),
        ("Датасеты", "Данные"),
        ("Почта", "AI ЧАТ"),
        ("Студия", "AI ЧАТ"),
        ("CAD/BIM", "AI ЧАТ"),
    ):
        assert f'"{old}": "{current}"' in shell


def test_production_shell_builds_no_dormant_mail_studio_or_cad_panel():
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert "build_data_workspace(is_admin=is_admin)" in shell
    assert "build_mail()" not in shell
    assert "build_mail_settings()" not in shell
    assert 'build_documents(surface="studio")' not in shell
    assert 'build_documents(surface="cad_bim")' not in shell
