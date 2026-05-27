from sovushka.pages.chat import should_skip_chat_resource_gate


def test_smeta_table_question_skips_resource_gate():
    assert should_skip_chat_resource_gate("посчитай общую стоимость по всем строкам сметы")


def test_mail_question_skips_resource_gate():
    assert should_skip_chat_resource_gate("найди последнее письмо про Dropbox")


def test_general_normative_question_keeps_resource_gate():
    assert not should_skip_chat_resource_gate("какая минимальная ширина эвакуационного выхода")
