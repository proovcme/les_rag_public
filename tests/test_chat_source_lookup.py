from types import SimpleNamespace

from proxy.routers.chat import _is_source_lookup_question, _source_lookup_answer


def test_source_lookup_question_markers():
    assert _is_source_lookup_question("Где смотреть требования к воздухообмену?")
    assert _is_source_lookup_question("Какие нормы применяются к СОУЭ?")
    assert not _is_source_lookup_question("Посчитай количество строк")


def test_source_lookup_answer_lists_unique_sources():
    chunks = [
        SimpleNamespace(
            doc_name="NTD/СП 60.13330.2020.docx",
            content="Требования к отоплению, вентиляции и кондиционированию воздуха.",
        ),
        SimpleNamespace(
            doc_name="NTD/СП 60.13330.2020.docx",
            content="Повтор того же источника.",
        ),
        SimpleNamespace(
            doc_name="NTD/СП 124.13330.2012.docx",
            content="Требования к тепловым сетям.",
        ),
    ]

    answer = _source_lookup_answer("Где смотреть требования к вентиляции?", chunks)

    assert answer is not None
    assert "СП 60.13330.2020.docx" in answer
    assert "СП 124.13330.2012.docx" in answer
    assert answer.count("СП 60.13330.2020.docx") == 1
