from proxy.services.smeta_chat_adapter_service import (
    _smeta_direct_light_system_prompt,
    _smeta_direct_user_prompt,
)


def test_smeta_direct_prompt_passes_inputs_without_prescribing_workflow():
    system = _smeta_direct_light_system_prompt()
    user = _smeta_direct_user_prompt(
        "Сделай ЛСР по приложенной спецификации",
        "Источник: spec.pdf, строка 7",
        "7 * 3 = 21",
        light=True,
    )

    assert "Самостоятельно реши задачу пользователя" in system
    assert "Профессиональные решения принимает модель" in system
    assert "ВОР -> кандидаты" not in system
    assert "ГЭСНм10" not in system
    assert "pricing-stage" not in system
    assert "Сделай ЛСР по приложенной спецификации" in user
    assert "Источник: spec.pdf, строка 7" in user
    assert "7 * 3 = 21" in user
    assert "следующий ход" not in user
    assert "Строка ВСЕГО" not in user
