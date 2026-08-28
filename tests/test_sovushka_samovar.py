import inspect

from sovushka.pages.samovar import _dataset_source_label, build_samovar


def test_mail_collection_is_a_data_source_not_a_destination():
    assert _dataset_source_label({"dataset_kind": "correspondence"}) == "Почта"
    assert _dataset_source_label({"source_type": "imap"}) == "Почта"
    assert _dataset_source_label({"name": "_SERVICE_MAIL_ARCHIVE"}) == "Почта"
    assert _dataset_source_label({"name": "MAIL_User_058d09cf_Index"}) == "Почта"
    assert _dataset_source_label({"dataset_scope": "system"}) == "Служебные данные"
    assert _dataset_source_label({"dataset_kind": "project"}) == "Проект"


def test_catalog_management_is_role_gated_in_builder_source():
    signature = inspect.signature(build_samovar)
    assert signature.parameters["can_manage"].default is True
    assert signature.parameters["open_tab"].default == "data"
    assert signature.parameters["workspace_title"].default == "Данные"

    source = inspect.getsource(build_samovar)
    assert "if can_manage:" in source
    assert "'tab': open_tab" in source
    assert "_dataset_source_label(r)" in source
    assert 'ui.label(workspace_title)' in source
