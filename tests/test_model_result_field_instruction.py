import pytest

from proxy.services.model_lsr_result_contract import model_lsr_result_field_instruction


@pytest.mark.parametrize("include_examples", [False, True])
def test_resource_condition_uses_row_role_values_and_a_real_field(include_examples):
    instruction = model_lsr_result_field_instruction(include_examples=include_examples)

    assert "Если row_role имеет значение material, equipment или resource, " in instruction
    assert "верни поле resource_code из карточки с evidence_refs либо пусто" in instruction
    assert "material/equipment/resource:" not in instruction


@pytest.mark.parametrize("include_examples", [False, True])
def test_source_row_must_copy_the_shown_source_coordinate_without_rebuilding_it(include_examples):
    instruction = model_lsr_result_field_instruction(include_examples=include_examples)

    assert "source_row дословно копируй из показанного адреса соответствующей исходной строки" in instruction
    assert "Не составляй новый адрес, не меняй его ключи или разделители" in instruction
    assert "не подставляй вместо адреса строки ID исходного файла" in instruction
    assert "соблюдай явно заданный пользователем формат" in instruction
    assert 'Без указания формата предпочти компактный JSON {"rows":[...]}; допустимы Markdown или текст' in instruction
