from proxy.services.smeta_user_message_service import (
    format_document_lsr_message,
    format_rub,
)


def test_partial_lsr_message_is_human_and_uses_russian_money_format():
    message = format_document_lsr_message(
        "ВОР монтаж БАП П1 13.05.pdf",
        {
            "input_rows": 19,
            "bound_rows": 14,
            "covered_rows": 0,
            "open_rows": 5,
            "total_without_vat": 290765.73,
            "total_with_vat": 354734.19,
            "result_status": "priced_partial",
        },
    )

    assert message == (
        "Смету собрал с нуля по ведомости «ВОР монтаж БАП П1 13.05.pdf». "
        "Из 19 позиций рассчитаны 14, 5 позиций оставлены незакрытыми. "
        "Стоимость рассчитанной части составляет 290 765,73 руб. без НДС и "
        "354 734,19 руб. с НДС. Формульная ЛСР приложена в Excel, замечания и "
        "позиции, требующие уточнения, вынесены на лист «Проверка»."
    )
    for internal_word in ("priced_partial", "blockers", "trace", "mapping", "unresolved"):
        assert internal_word not in message


def test_complete_lsr_message_calls_total_the_estimate():
    message = format_document_lsr_message(
        "ВОР.xlsx",
        {
            "input_rows": 3,
            "bound_rows": 2,
            "covered_rows": 1,
            "open_rows": 0,
            "total_without_vat": 1000,
            "total_with_vat": 1220,
        },
    )

    assert "Все 3 позиции учтены: 2 рассчитаны, 1 позиция учтена в составе других работ" in message
    assert "Стоимость сметы составляет 1 000,00 руб." in message
    assert "Стоимость рассчитанной части" not in message


def test_partial_lsr_message_mentions_covered_rows_without_hiding_open_rows():
    message = format_document_lsr_message(
        "ВОР.pdf",
        {
            "input_rows": 19,
            "bound_rows": 13,
            "covered_rows": 2,
            "open_rows": 4,
            "total_without_vat": 100,
        },
    )

    assert "рассчитаны 13, ещё 2 позиции учтены в составе других работ, 4 позиции оставлены незакрытыми" in message
    assert "Стоимость рассчитанной части без НДС составляет 100,00 руб." in message


def test_partial_lsr_message_uses_singular_for_one_covered_position():
    message = format_document_lsr_message(
        "ВОР.pdf",
        {
            "input_rows": 19,
            "bound_rows": 16,
            "covered_rows": 1,
            "open_rows": 2,
            "total_without_vat": 100,
        },
    )

    assert "ещё 1 позиция учтена в составе других работ" in message


def test_format_rub_uses_spaces_and_decimal_comma():
    assert format_rub(290765.73) == "290 765,73 руб."
