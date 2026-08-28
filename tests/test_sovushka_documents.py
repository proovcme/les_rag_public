import inspect

from sovushka.pages.documents import build_documents


def test_data_detail_accepts_explicit_dataset_and_hides_duplicate_picker():
    signature = inspect.signature(build_documents)
    assert "initial_dataset_id" in signature.parameters
    assert "show_dataset_picker" in signature.parameters
    assert "can_manage" in signature.parameters

    source = inspect.getsource(build_documents)
    assert 'surface not in {"documents", "data", "studio", "cad_bim"}' in source
    assert "initial_dataset = str(initial_dataset_id or \"\").strip()" in source
    assert "datasets_column.set_visibility(show_dataset_picker" in source
    assert '"Назад ко всем данным"' in source
    assert "sov-data-detail--focused" in source


def test_data_detail_keeps_chat_scope_exact_and_mutations_role_gated():
    source = inspect.getsource(build_documents)
    assert '"scope": f"ds:{dataset_id}"' in source
    assert '"target_file": file_name' in source
    assert "_is_system_dataset() and can_manage" in source
    assert "if can_manage and not _is_system_dataset(row):" in source
