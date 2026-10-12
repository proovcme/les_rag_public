import asyncio
import hashlib
import inspect
import json
import sqlite3
import time
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from proxy.smeta_core.calculation_receipt import receipt_context

from proxy.routers import chat
from proxy.services import chat_evidence_application_service as service
from proxy.services.chat_attachment_service import preserve_read_attachment
from proxy.services.tool_harness_service import ToolHarness
from proxy.services.web_research_config_service import WebResearchConfig


def test_model_answer_format_applies_only_to_terminal_content_and_reads_remain_optional():
    clarification = (
        'Требования к Markdown, первой строке и запрет вывода JSON относятся только '
        'к итоговому пользовательскому ответу. До него при необходимости можешь использовать '
        'native search_sources, если этот инструмент доступен; решение о дополнительном чтении принимаешь ты.'
    )
    driven = service.model_answer_request('Fixture question', model_driven=True)
    ordinary = service.model_answer_request('Fixture question', model_driven=False)
    assert clarification in driven
    assert clarification not in ordinary
    assert driven.index(clarification) < driven.index('Первой строкой — базовая шапка')
    assert '| source_row | work_id | title | unit | quantity | norm_code | evidence_refs |' in driven
    assert 'Не выводи JSON.' in driven


@pytest.mark.parametrize('mode,model_driven,estimator',[
    ('legacy',True,True), ('shadow',True,True), ('active',False,True), ('active',True,False),
])
def test_p915_answer_adapter_leaves_other_paths_byte_identical(mode,model_driven,estimator):
    from tests.test_chat_profile_service import _p915_factory_snapshot
    snapshot = _p915_factory_snapshot()
    if not estimator:
        snapshot['mode'] = 'agent'
    prefix, request, trace = service.prepare_estimator_answer_contract(
        snapshot, canonical_mode=mode, model_driven=model_driven, tools_enabled=True,
        original_prefix='original-prefix', original_request='original-request', question='Fixture')
    assert (prefix,request,trace) == ('original-prefix','original-request',None)


@pytest.mark.parametrize('tools_enabled',[True,False])
def test_p915_active_answer_has_available_tools_and_qrefs_only_in_owned_contract(tools_enabled):
    from tests.test_chat_profile_service import _p915_factory_snapshot
    snapshot = _p915_factory_snapshot()
    query_before = service.profile_query_prompt(snapshot)
    prefix, request, trace = service.prepare_estimator_answer_contract(
        snapshot, canonical_mode='active', model_driven=True, tools_enabled=tools_enabled,
        original_prefix='unused',original_request='unused',question='Fixture',
        instruction='Preserved output style',output_directive='Preserved GUI directive')
    assert '[Источник N]' not in prefix+request
    assert 'skills/smeta/SKILL.md' not in prefix
    assert 'read_source' not in prefix
    assert ('native search_sources' in request) is tools_enabled
    assert 'Qn.Hm' in prefix and 'Qn.Hm' in request
    assert 'Preserved output style' in prefix and 'Preserved GUI directive' in prefix
    assert service.profile_query_prompt(snapshot) == query_before
    assert trace['original_prompt_sha256'] == snapshot['prompt_sha256']


def test_p915_custom_authored_instructions_are_preserved_and_mismatch_visible():
    snapshot = {'mode':'estimator','is_factory':False,'prompt_text':'Custom read_source [Источник N]',
                'skill_text':'Custom skills/smeta/SKILL.md'}
    prefix, _, trace = service.prepare_estimator_answer_contract(
        snapshot,canonical_mode='active',model_driven=True,tools_enabled=True,
        original_prefix='unused',original_request='unused',question='Fixture')
    assert snapshot['prompt_text'] in prefix and snapshot['skill_text'] in prefix
    assert trace['factory_verified'] is False
    assert trace['unavailable_references'] == ['read_source','skills/smeta/SKILL.md']


@pytest.fixture(autouse=True)
def isolated_chat_state(tmp_path, monkeypatch):
    """A repeated run must not reuse another test's attachment idempotency keys."""
    monkeypatch.setenv("LES_WINDOWS_STATE_ROOT", str(tmp_path / "state"))


def test_web_reader_is_visible_only_in_explicit_extended_request_snapshot():
    tools = ["web_search", "web_read", "filesystem_search"]

    simple = service.web_tools_for_request(
        tools,
        WebResearchConfig("simple", "", "", ""),
    )
    extended = service.web_tools_for_request(
        tools,
        WebResearchConfig(
            "extended",
            "http://127.0.0.1:8888",
            "http://127.0.0.1:11235",
            "",
        ),
    )

    assert simple == ["web_search", "filesystem_search"]
    assert extended == tools


def test_web_tool_sources_replace_search_snippet_with_read_page_provenance():
    tool_results = [
        {
            "tool": "web_search",
            "result": {
                "results": [
                    {
                        "title": "Каталог",
                        "snippet": "Краткая выдача",
                        "url": "https://public.example/material",
                        "domain": "public.example",
                    }
                ]
            },
            "sources": [
                {
                    "kind": "web",
                    "title": "Каталог",
                    "url": "https://public.example/material",
                    "domain": "public.example",
                }
            ],
        },
        {
            "tool": "web_read",
            "result": {
                "title": "Каталог материалов",
                "text": "Полный текст страницы",
                "final_url": "https://public.example/material",
                "retrieved_at": "2026-09-02T10:00:00+00:00",
            },
            "sources": [
                {
                    "kind": "web_page",
                    "title": "Каталог материалов",
                    "url": "https://public.example/material",
                }
            ],
        },
    ]

    source_map = service.web_source_map_from_tool_results(tool_results)

    assert len(source_map) == 1
    assert source_map[0]["label"] == "Источник 1"
    assert source_map[0]["snippet"] == "Полный текст страницы"
    assert source_map[0]["locator"] == {
        "kind": "web_result",
        "url": "https://public.example/material",
        "title": "Каталог материалов",
        "retrieved_at": "2026-09-02T10:00:00+00:00",
        "excerpt": "Полный текст страницы",
    }


def test_attachment_workbook_tools_survive_restrictive_model_shortlist():
    tools = [
        "dataset_map",
        "search_sources",
        "read_source",
        "read_excel_source",
        "search_project_tables",
        "read_project_table",
        "build_lsr_workbook",
        "build_vor_workbook",
    ]

    ordered = service.prioritize_workbook_tools(tools, workbook_phase=True)
    shortlist = ToolHarness().shortlist(
        "Собери ЛСР",
        allowed_tools=ordered,
        limit=5,
        dataset_ids=("selected",),
        workflow_phase="draft",
        model_preset="qwen-9b-restrictive",
        runtime_available=frozenset(tools),
        attachment_ids=("read_123456abcdef",),
    )

    assert ordered[:2] == ["build_lsr_workbook", "build_vor_workbook"]
    assert set(ordered) == set(tools)
    assert [item["name"] for item in shortlist["tools"][:2]] == [
        "build_lsr_workbook",
        "build_vor_workbook",
    ]


def test_tool_selector_request_declares_bound_attachment_without_copying_its_text():
    payload = service.tool_selector_request_payload(
        question="build workbook",
        mode="estimator",
        dataset_ids=[],
        target_file_ref={},
        round_no=1,
        attachment_id="read_123456abcdef",
    )

    assert payload["attachment"] == {
        "bound": True,
        "attachment_id": "read_123456abcdef",
    }
    assert "attachment_context" not in payload


def test_native_model_tool_schemas_preserve_registered_contract():
    schemas = service.native_model_tool_schemas(
        [
            {
                "name": "search_sources",
                "summary": "Search selected sources",
                "input_schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                    "additionalProperties": False,
                },
            }
        ]
    )

    assert schemas == [
        {
            "type": "function",
            "function": {
                "name": "search_sources",
                "description": "Search selected sources",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                    "additionalProperties": False,
                },
            },
        }
    ]


def test_model_authored_search_batch_is_not_cut_to_five_calls():
    raw = json.dumps(
        {
            "calls": [
                {"tool": "search_sources", "args": {"q": f"work item {index}"}}
                for index in range(10)
            ]
        }
    )

    calls = chat._parse_model_tool_calls(
        raw,
        allowed_tools={"search_sources"},
        max_calls=48,
    )

    assert [call["args"]["q"] for call in calls] == [
        f"work item {index}" for index in range(10)
    ]


def test_model_rag_batch_does_not_accept_a_legacy_json_protocol():
    queries = [f"точный запрос {index}" for index in range(30)]

    assert service.parse_model_rag_queries(
        json.dumps({"queries": queries}, ensure_ascii=False)
    ) == []


def test_model_rag_batch_reads_plain_model_authored_lines_without_a_row_limit():
    queries = [f"точный запрос {index}" for index in range(30)]

    assert service.parse_model_rag_queries("\n".join(queries)) == queries


def test_existing_estimator_profile_keeps_model_authored_query_workflow_without_new_flag():
    assert service.profile_uses_model_driven_retrieval(
        {
            "revision_id": "user:profile:estimator:legacy",
            "mode": "estimator",
            "rag_policy": {"grounded": True, "system_datasets": ["smeta"]},
        }
    ) is True
    assert service.profile_uses_model_driven_retrieval(
        {"mode": "search", "rag_policy": {"grounded": True}}
    ) is False


def test_only_estimator_model_rag_uses_the_dedicated_smeta_catalog():
    assert service.profile_uses_smeta_norm_retrieval({"mode": "estimator"}) is True
    assert service.profile_uses_smeta_norm_retrieval(
        {
            "mode": "search",
            "rag_policy": {"model_authored_initial_query": True},
        }
    ) is False


def test_model_rag_evidence_keeps_configured_candidates_whole_for_the_queries_that_fit():
    """Каждый вошедший запрос несёт свои карточки целиком; остальные объявлены, а не обрезаны.

    До 10.10 тест закреплял обратное: все 30 запросов в пакете, тела урезаны поровну.
    Живой контроль .199 показал цену — 0 целых карточек из 102, выбор нормы по заголовку.
    """
    def hits_for(query_index):
        return [
            SimpleNamespace(
                content=(
                    f"Шифр: ГЭСН{query_index:02d}-00-000-{hit_index:02d} "
                    f"Наименование: кандидат {hit_index} " + "состав работ " * 80
                ),
                doc_id=f"doc-{query_index}-{hit_index}",
                doc_name="smeta_norm_cards.v1",
                score=1.0 / hit_index,
                meta={"dataset_id": "smeta"},
            )
            for hit_index in range(1, 9)
        ]

    query_hits = [(f"работа {query_index}", hits_for(query_index)) for query_index in range(1, 31)]

    groups, chunks = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=70_000,
        hits_per_query=4,
    )

    rendered = "\n\n".join(groups)
    assert len(rendered) <= 70_000
    # Вошли первые запросы по порядку модели, у каждого ровно настроенные четыре кандидата.
    assert 1 < len(groups) < 30
    assert len(chunks) == 4 * len(groups)
    assert [group.split("]", 1)[0] for group in groups] == [
        f"[Поисковый запрос Q{index}" for index in range(1, len(groups) + 1)
    ]
    assert "ГЭСН01-00-000-04" in rendered and "ГЭСН01-00-000-05" not in rendered
    assert not any(chunk.meta.get("model_evidence_truncated") for chunk in chunks)
    coverage = service.model_rag_evidence_coverage(query_hits, groups)
    assert coverage["queries_dropped"] == 30 - len(groups) and coverage["complete"] is False

    # Когда целые карточки помещаются, до модели доходят все запросы.
    groups, chunks = service.build_model_rag_evidence_groups(
        query_hits,
        max_chars=160_000,
        hits_per_query=4,
    )
    assert len(groups) == 30 and len(chunks) == 120
    assert "[Q30.H4 | smeta_norm_cards.v1" in "\n\n".join(groups)
    assert not any(chunk.meta.get("model_evidence_truncated") for chunk in chunks)


def test_model_rag_source_map_preserves_typed_locator_and_evidence_handle():
    chunk = service._ModelRagEvidenceChunk(
        content="Шифр и состав работы",
        doc_id="",
        doc_name="smeta_norm_cards.v1",
        score=0.75,
        meta={
            "dataset_id": "smeta-dataset",
            "norm_code": "ГЭСН01-01-001-01",
            "source_ref": "fsnb#norm=ГЭСН01-01-001-01",
            "model_evidence_ref": "Q3.H2",
        },
    )

    source_map = service._model_rag_source_map([chunk])

    assert source_map[0]["evidence_ref"] == "Q3.H2"
    assert source_map[0]["source_ref"] == "fsnb#norm=ГЭСН01-01-001-01"
    assert source_map[0]["locator"]["kind"] == "norm_card"
    assert source_map[0]["locator"]["card_code"] == "ГЭСН01-01-001-01"


def test_model_rag_result_preserves_all_rows_and_domain_fields_unchanged():
    rows = [
        {
            "source_row": index,
            "title": f"Работа {index}",
            "unit": "шт.",
            "quantity": index,
            "norm_code": f"ГЭСНм00-00-000-{index:02d}",
            "evidence_refs": [f"Источник {index}"],
        }
        for index in range(1, 31)
    ]

    answer = "\n".join(
        [
            "Готово",
            "",
            "| source_row | section | title | unit | quantity | norm_code | analogue | coverage | coefficient | evidence_refs |",
            "|---:|---|---|---|---:|---|---|---|---:|---|",
            *[
                f"| {index} | | Работа {index} | шт. | {index} | "
                f"ГЭСНм00-00-000-{index:02d} | | | | Источник {index} |"
                for index in range(1, 31)
            ],
        ]
    )

    assert service.parse_model_rag_result(answer) == (answer, rows)


def test_model_rag_result_decoder_has_no_regex_or_language_router():
    source = inspect.getsource(service.parse_model_rag_result)

    assert "re." not in source
    assert "question" not in source
    assert "query" not in source


def test_chat_application_does_not_replace_the_configured_model_for_memory_pressure():
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "memory_aware_provider" not in source


def test_model_rag_result_preserves_explicit_row_identity_and_norm_code_verbatim():
    answer = """| source_row | title | unit | quantity | norm_code | evidence_refs |
|---:|---|---|---:|---|---|
| 42 | Работа модели | шт. | 3 | ГЭСН:26-01-055-01 (выбор Qwen) | Q2.H4 |
| 7 | Другая работа | м | 8 | CUSTOM-NORM-A | Q1.H2 |
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    assert parsed[0] == answer
    assert parsed[1] == [
        {
            "source_row": 42,
            "title": "Работа модели",
            "unit": "шт.",
            "quantity": 3,
            "norm_code": "ГЭСН:26-01-055-01 (выбор Qwen)",
            "evidence_refs": ["Q2.H4"],
        },
        {
            "source_row": 7,
            "title": "Другая работа",
            "unit": "м",
            "quantity": 8,
            "norm_code": "CUSTOM-NORM-A",
            "evidence_refs": ["Q1.H2"],
        },
    ]


def test_model_rag_result_preserves_string_source_row_verbatim():
    answer = """### Строка 1
* **source_row**: СМР!R9
* **title**: Работа модели
* **unit**: шт.
* **quantity**: 3
* **norm_code**: ГЭСН26-01-055-01
* **evidence_refs**: Q2.H4
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    assert parsed[0] == answer
    assert parsed[1][0]["source_row"] == "СМР!R9"


def test_model_rag_result_reads_natural_parenthetical_table_headers():
    answer = """| source_row | section | title (Наименование) | unit | quantity | norm_code (Выбранная норма) | analogue / coverage (Обоснование/Аналог) | coefficient | evidence_refs (Источник) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **СМР!R9** | Общие условия | Итоговая строка | руб. | *(нет)* | *(Нет)* | Не является нормируемой работой. | 1.0 | [Q1.H2] |
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed == (
        answer,
        [
            {
                "source_row": "СМР!R9",
                "section": "Общие условия",
                "title": "Итоговая строка",
                "unit": "руб.",
                "norm_code": "*(Нет)*",
                "analogue": "Не является нормируемой работой.",
                "coefficient": 1,
                "evidence_refs": ["Q1.H2"],
            }
        ],
    )


def test_model_rag_packaging_requires_unique_rows_and_real_matching_evidence():
    evidence = [
        SimpleNamespace(
            meta={"model_evidence_ref": "Q1.H2", "norm_code": "ГЭСН26-01-055-01"}
        ),
        SimpleNamespace(
            meta={"model_evidence_ref": "Q2.H4", "norm_code": "ГЭСНм08-02-146-01"}
        ),
    ]
    rows = [
        {"source_row": 1, "norm_code": "ГЭСН:26-01-055-01", "evidence_refs": ["Q1.H2"]},
        {"source_row": 2, "norm_code": "ГЭСНм08-02-146-01", "evidence_refs": ["Q2.H4"]},
    ]

    assert service.validate_model_rag_result_structure(
        rows,
        evidence,
        expected_source_rows=2,
    ) == []

    errors = service.validate_model_rag_result_structure(
        [
            {"source_row": 1, "norm_code": "ГЭСН26-01-055-99", "evidence_refs": ["Q1.H2"]},
            {"source_row": 1, "norm_code": "ГЭСНм08-02-146-01", "evidence_refs": ["Q9.H9"]},
        ],
        evidence,
        expected_source_rows=2,
    )

    assert "duplicate_source_row:1" in errors
    assert "unknown_evidence_ref:Q9.H9" in errors
    assert "norm_code_not_in_referenced_evidence:1" in errors


def test_model_rag_packaging_keeps_model_wording_and_treats_code_link_mismatch_as_advisory():
    evidence = [
        SimpleNamespace(
            meta={"model_evidence_ref": "Q1.H2", "norm_code": "ГЭСНм08-04-751-02"}
        )
    ]

    assert service.validate_model_rag_result_structure(
        [
            {
                "source_row": "ВОР!R5",
                "norm_code": "ГЭСНм08-04-751-02 (Аналог: прокладка в коробах)",
                "evidence_refs": ["Q1.H2"],
            }
        ],
        evidence,
        expected_source_rows=1,
    ) == []

    advisory = service.validate_model_rag_result_structure(
        [
            {
                "source_row": "ВОР!R5",
                "norm_code": "ГЭСНм08-04-751-01 (выбор модели)",
                "evidence_refs": ["Q1.H2"],
            }
        ],
        evidence,
        expected_source_rows=1,
    )

    assert advisory == ["norm_code_not_in_referenced_evidence:ВОР!R5"]
    assert service.blocking_model_rag_result_errors(advisory) == []
    # С 17.09 (проход 3 на IQ2_M) ссылка на несуществующую карточку отказывает строке, а не
    # порции: норму без показанной карточки не считает withhold_unreferenced_norms.
    assert service.blocking_model_rag_result_errors(
        advisory + ["unknown_evidence_ref:Q9.H9"]
    ) == []


def test_model_rag_packaging_accepts_unique_string_source_rows_without_count_gate():
    evidence = [
        SimpleNamespace(
            meta={"model_evidence_ref": "Q1.H1", "norm_code": "ГЭСН26-01-055-01"}
        ),
        SimpleNamespace(
            meta={"model_evidence_ref": "Q2.H1", "norm_code": "ГЭСНм08-02-146-01"}
        ),
    ]
    rows = [
        {
            "source_row": "СМР!R9",
            "norm_code": "ГЭСН26-01-055-01",
            "evidence_refs": ["Q1.H1"],
        },
        {
            "source_row": "Комментарии!R2",
            "norm_code": "ГЭСНм08-02-146-01",
            "evidence_refs": ["Q2.H1"],
        },
    ]

    assert service.validate_model_rag_result_structure(
        rows,
        evidence,
        expected_source_rows=99,
    ) == []

    duplicate_errors = service.validate_model_rag_result_structure(
        [rows[0], {**rows[1], "source_row": "СМР!R9"}],
        evidence,
        expected_source_rows=2,
    )

    assert "duplicate_source_row:СМР!R9" in duplicate_errors


def test_model_rag_packaging_preserves_explicit_missing_norm_marker():
    evidence = [
        SimpleNamespace(
            meta={"model_evidence_ref": "Q1.H2", "norm_code": "ГЭСН26-01-055-01"}
        )
    ]

    assert service.validate_model_rag_result_structure(
        [
            {
                "source_row": "СМР!R9",
                "norm_code": "*(Нет)*",
                "evidence_refs": ["Q1.H2"],
            }
        ],
        evidence,
        expected_source_rows=19,
    ) == []


def test_model_rag_result_does_not_infer_rows_from_prose():
    answer = """### Раздел 1. Демонтажные работы ЭОМ
**Строка 1: Защитное укрытие пленкой, 116 м².**
* **Выбранный аналог:** `ГЭСН26-01-055-01` (Установка пароизоляционного слоя из пленки).
* **Обоснование:** Ближайший по составу работ аналог [Q1.H2].

### Раздел 2. Монтажные работы ЭОМ
**Строка 1: Монтаж блока аварийного питания, 16 шт.**
* **Выбранный аналог:** `ГЭСНм34-01-071-01` (Светильник с аварийным питанием).
* **Обоснование:** Аналог по сложности монтажа Q7.H1; Q7.H3.
"""

    assert service.parse_model_rag_result(answer) is None


def test_model_rag_result_reads_explicit_multiline_labelled_blocks():
    answer = """**Строка 1**
* **source_row**: 1
* **section**: Демонтаж
* **title**: Демонтаж керамической плитки со стен
* **unit**: м2
* **quantity**: 24
* **norm_code**: ГЭСНр63-03-001-05
* **analogue**: Нет
* **coverage**: Полное соответствие
* **coefficient**: 1.0
* **evidence_refs**: Q6.H4, Q13.H5

**Строка 2**
- **source_row**: 2
- **title**: Окраска стен
- **unit**: м2
- **quantity**: 60
- **norm_code**: ГЭСН15-04-007-05
- **coverage**: Полное соответствие
- **evidence_refs**: Q3.H2; Q8.H5
"""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [
            {
                "source_row": 1,
                "section": "Демонтаж",
                "title": "Демонтаж керамической плитки со стен",
                "unit": "м2",
                "quantity": 24,
                "norm_code": "ГЭСНр63-03-001-05",
                "analogue": "Нет",
                "coverage": "Полное соответствие",
                "coefficient": 1,
                "evidence_refs": ["Q6.H4", "Q13.H5"],
            },
            {
                "source_row": 2,
                "title": "Окраска стен",
                "unit": "м2",
                "quantity": 60,
                "norm_code": "ГЭСН15-04-007-05",
                "coverage": "Полное соответствие",
                "evidence_refs": ["Q3.H2", "Q8.H5"],
            },
        ],
    )


def test_model_rag_result_reads_titled_blocks_and_keeps_explicit_missing_quantity():
    """Regression: a natural model heading must not hide its explicit row fields."""

    answer = """### Строка 984: Шкаф Hyperline (2 шт.)
* **source_row:** 984
* **section:** Оборудование
* **title:** Шкаф напольный 19-дюймовый
* **unit:** шт.
* **quantity:** 2
* **norm_code:** ГЭСНм10-01-055-01 (выбор Qwen)
* **analogue:** Шкаф металлический
* **coverage:** Монтаж шкафа
* **evidence_refs:** Q1.H3, Q4.H2

### Строка 1024: Кабельнесущая продукция
* **source_row:** 1024
* **section:** Подзаголовок
* **title:** Кабельнесущая продукция
* **unit:** —
* **quantity:** —
* **norm_code:** —
* **analogue:** —
* **coverage:** Группировка материалов
* **evidence_refs:** Q3.H1
"""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [
            {
                "source_row": 984,
                "section": "Оборудование",
                "title": "Шкаф напольный 19-дюймовый",
                "unit": "шт.",
                "quantity": 2,
                "norm_code": "ГЭСНм10-01-055-01 (выбор Qwen)",
                "analogue": "Шкаф металлический",
                "coverage": "Монтаж шкафа",
                "evidence_refs": ["Q1.H3", "Q4.H2"],
            },
            {
                "source_row": 1024,
                "section": "Подзаголовок",
                "title": "Кабельнесущая продукция",
                "unit": "—",
                "norm_code": "—",
                "analogue": "—",
                "coverage": "Группировка материалов",
                "evidence_refs": ["Q3.H1"],
            },
        ],
    )


def test_model_rag_result_reads_source_row_explicit_in_block_heading():
    answer = """### Строка 1 (source_row=1)
* **section:** Демонтаж
* **title:** Разборка облицовки стен
* **unit:** м2
* **quantity:** 24
* **norm_code:** ГЭСНр63-03-001-05
* **coverage:** Полное покрытие
* **coefficient:** 1.0 (без дополнительных коэффициентов)
* **evidence_refs:** Q4.H1
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    assert parsed[0] == answer
    assert parsed[1] == [{
        "source_row": 1,
        "section": "Демонтаж",
        "title": "Разборка облицовки стен",
        "unit": "м2",
        "quantity": 24,
        "norm_code": "ГЭСНр63-03-001-05",
        "coverage": "Полное покрытие",
        "coefficient": 1,
        "evidence_refs": ["Q4.H1"],
    }]


def test_model_rag_result_reads_explicit_labelled_lines_without_semantic_repair():
    answer = """Строка 1 — Прокладка контрольного кабеля; раздел: Монтаж; ед. изм.: м; количество: 120; norm_code: ГЭСНм08-02-146-01; аналог: Кабель контрольный; обоснование: прямое соответствие составу; коэффициент: 1; evidence: Q1.H2.
Строка 2 — Монтаж шкафа управления; раздел: Автоматика; ед. изм.: шт.; количество: 2; norm_code: ГЭСНм11-03-001-01; аналог: Шкаф управления; обоснование: совпадают измеритель и операции; evidence_refs: Q2.H1, Q2.H3."""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [
            {
                "source_row": 1,
                "title": "Прокладка контрольного кабеля",
                "section": "Монтаж",
                "unit": "м",
                "quantity": 120,
                "norm_code": "ГЭСНм08-02-146-01",
                "analogue": "Кабель контрольный",
                "coverage": "прямое соответствие составу",
                "coefficient": 1,
                "evidence_refs": ["Q1.H2"],
            },
            {
                "source_row": 2,
                "title": "Монтаж шкафа управления",
                "section": "Автоматика",
                "unit": "шт.",
                "quantity": 2,
                "norm_code": "ГЭСНм11-03-001-01",
                "analogue": "Шкаф управления",
                "coverage": "совпадают измеритель и операции",
                "evidence_refs": ["Q2.H1", "Q2.H3"],
            },
        ],
    )


def test_model_rag_queries_ignore_only_plain_text_presentation_wrappers():
    raw = (
        "Вот список поисковых запросов.\n"
        "```text\n"
        '"демонтаж кабеля в гофре"\n'
        '"монтаж аварийного светильника"\n'
        "```"
    )

    assert service.parse_model_rag_queries(raw) == [
        "демонтаж кабеля в гофре",
        "монтаж аварийного светильника",
    ]


def test_model_rag_queries_liberally_unwrap_model_written_search_call_lines():
    raw = (
        "Сейчас сформирую запросы.\n"
        'search_sources "демонтаж штукатурки со стен"\n'
        'search_sources("монтаж воздуховодов круглого сечения")\n'
        "Это все запросы."
    )

    assert service.parse_model_rag_queries(raw) == [
        "демонтаж штукатурки со стен",
        "монтаж воздуховодов круглого сечения",
    ]


def test_model_rag_result_reads_an_ordinary_russian_table_with_combined_norm_cell():
    answer = """| № п/п | Наименование работ (из ВОР) | Ед. изм. | Кол-во | Нормативная база (Шифр нормы) | Обоснование выбора и аналог | Примечания к составу работ |
|:---:|:---|:---:|:---:|:---|:---|:---|
| **Раздел 1. Демонтажные работы** | | | | | | |
| 1 | Защитное укрытие | м² | 116 | **ГЭСН26-01-055-01**<br>[Q3.H2] | Аналог: пароизоляционный слой | Материал отдельно |
| 2 | Разработка проема | шт. | 10 | *(Нет прямого аналога)*<br>Аналог: **ГЭСН15-02-035-03**<br>[Q6.H1] | Аналог по составу | Обратная операция |
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    assert parsed[0] == answer
    assert parsed[1] == [
        {
            "source_row": 1,
            "section": "Раздел 1. Демонтажные работы",
            "title": "Защитное укрытие",
            "unit": "м²",
            "quantity": 116,
            "norm_code": "ГЭСН26-01-055-01<br>[Q3.H2]",
            "analogue": "Аналог: пароизоляционный слой",
            "coverage": "Материал отдельно",
            "evidence_refs": ["Q3.H2"],
        },
        {
            "source_row": 2,
            "section": "Раздел 1. Демонтажные работы",
            "title": "Разработка проема",
            "unit": "шт.",
            "quantity": 10,
            "norm_code": "*(Нет прямого аналога)*<br>Аналог: ГЭСН15-02-035-03<br>[Q6.H1]",
            "analogue": "Аналог по составу",
            "coverage": "Обратная операция",
            "evidence_refs": ["Q6.H1"],
        },
    ]


def test_model_rag_result_collects_every_ordinary_table_across_sections():
    answer = """### Раздел 1. Демонтаж
| № пп | Наименование работ | Ед. изм. | Кол-во | Нормативная база (Norm Code) | Обоснование выбора и аналог | Примечания к выбору |
|:---|:---|:---:|:---:|:---|:---|:---|
| 1 | Работа 1 | м² | 116 | **ГЭСН26-02-010-02** | Аналог 1 | **Evidence:** Q1.H3 |

### Раздел 2. Монтаж
| № пп | Наименование работ | Ед. изм. | Кол-во | Нормативная база (Norm Code) | Обоснование выбора и аналог | Примечания к выбору |
|:---|:---|:---:|:---:|:---|:---|:---|
| 1 | Работа 2 | шт. | 10 | **ГЭСН17-01-010-01** | Аналог 2 | **Evidence:** Q3.H3 |
| 2 | Работа 3 | м | 160 | **ГЭСНм08-02-146-02** | Аналог 3 | **Evidence:** Q9.H4 |
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    assert parsed[0] == answer
    assert [row["source_row"] for row in parsed[1]] == [1, 1, 2]
    assert [row["section"] for row in parsed[1]] == [
        "Раздел 1. Демонтаж",
        "Раздел 2. Монтаж",
        "Раздел 2. Монтаж",
    ]
    assert [row["norm_code"] for row in parsed[1]] == [
        "ГЭСН26-02-010-02",
        "ГЭСН17-01-010-01",
        "ГЭСНм08-02-146-02",
    ]
    assert [row["evidence_refs"] for row in parsed[1]] == [
        ["Q1.H3"],
        ["Q3.H3"],
        ["Q9.H4"],
    ]


def test_model_rag_result_accepts_the_models_short_ordinary_column_names():
    answer = """### Раздел 1. Работы
| № пп | Наименование | Ед. изм. | Кол-во | Примечание | norm_code (Шифр) | Аналог/Обоснование | Coverage (Соответствие) | Coefficient (Кэф.) | Evidence_refs |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| 1 | Работа | м² | 116 | Текст модели | ГЭСН26-01-055-01 | Аналог модели | Частичное | 1.0 | [Q1.H2] |
"""

    parsed = service.parse_model_rag_result(answer)

    assert parsed is not None
    assert parsed[1] == [
        {
            "source_row": 1,
            "section": "Раздел 1. Работы",
            "title": "Работа",
            "unit": "м²",
            "quantity": 116,
            "norm_code": "ГЭСН26-01-055-01",
            "analogue": "Аналог модели",
            "coverage": "Частичное",
            "coefficient": 1,
            "evidence_refs": ["Q1.H2"],
        }
    ]


def test_model_rag_result_accepts_maxim_explicit_headers_and_missing_numbers():
    answer = """| № | Наименование | Ед. изм. | Кол-во | Нормативный код (ГЭСН/ЕР) | Коэфф. | Примечание | Evidence_refs |
|---:|---|---|---:|---|---|---|---|
| 1 | Кабель модели | м | 12 | CUSTOM-NORM-A | — | Текст Qwen | Q3.H2 |
| 2 | Плёнка модели | м2 |  | CUSTOM-NORM-B | 1/100 | Нет прямого аналога | Q4.H1 |
"""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [
            {
                "source_row": 1,
                "title": "Кабель модели",
                "unit": "м",
                "quantity": 12,
                "norm_code": "CUSTOM-NORM-A",
                "coverage": "Текст Qwen",
                "evidence_refs": ["Q3.H2"],
            },
            {
                "source_row": 2,
                "title": "Плёнка модели",
                "unit": "м2",
                "norm_code": "CUSTOM-NORM-B",
                "coefficient": 0.01,
                "coverage": "Нет прямого аналога",
                "evidence_refs": ["Q4.H1"],
            },
        ],
    )


def test_model_rag_result_preserves_non_numeric_coefficient_text_unchanged():
    answer = """| source_row | title | unit | quantity | norm_code | coefficient | evidence_refs |
|---:|---|---|---:|---|---|---|
| 1 | Работа модели | м2 | 24 | ГЭСНр63-03-001-05 | 1/100 = 0.24 | Q4.H1 |
"""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [{
            "source_row": 1,
            "title": "Работа модели",
            "unit": "м2",
            "quantity": 24,
            "norm_code": "ГЭСНр63-03-001-05",
            "coefficient": "1/100 = 0.24",
            "evidence_refs": ["Q4.H1"],
        }],
    )


def test_model_rag_result_pads_only_missing_trailing_optional_cells():
    answer = """| № | Наименование | Ед. изм. | Кол-во | Нормативный код (ГЭСН/ЕР) | Коэфф. | Примечание |
|---:|---|---|---:|---|---|---|
| 7 | Работа модели | шт. | 3 | CUSTOM-NORM-A |
"""

    assert service.parse_model_rag_result(answer) == (
        answer,
        [{
            "source_row": 7,
            "title": "Работа модели",
            "unit": "шт.",
            "quantity": 3,
            "norm_code": "CUSTOM-NORM-A",
        }],
    )


def test_estimator_draft_projection_never_invents_source_row_or_decision():
    rows = service.compact_estimator_draft_rows([
        {
            "source_row": 42,
            "title": "Кабель",
            "quantity": 12,
            "unit": "м",
            "norm_code": "CUSTOM-NORM-A",
            "analogue": "Аналог Qwen",
        },
        {
            "title": "Строка без идентичности",
            "norm_code": "CUSTOM-NORM-B",
        },
    ])

    assert rows == [{
        "work_id": "42",
        "source_row": 42,
        "section": "",
        "title": "Кабель",
        "quantity": 12,
        "unit": "м",
        "norm_code": "CUSTOM-NORM-A",
        "analogue": "Аналог Qwen",
    }]


def test_workbook_filename_projection_keeps_basename_and_drops_paths():
    assert service._safe_workbook_filename("LSR_source_2026-09-01_2147.xlsx") == (
        "LSR_source_2026-09-01_2147.xlsx"
    )
    assert service._safe_workbook_filename("C:/private/workbook.xlsx") == ""
    assert service._safe_workbook_filename("artifact.xlsx") == ""


async def _async_append(target, value):
    target.append(value)


async def _fake_workbook_execution(call, context, progress, _events):
    assert call["tool"] in {"build_lsr_workbook", "build_vor_workbook"}
    assert context["attachment_id"] == "read_123456abcdef"
    await progress({
        "call_id": call.get("call_id") or "workbook-call-1",
        "checkpoint_id": "cp-1",
        "phase": "rows",
        "completed": 3,
        "total": 10,
        "label": "Собираю строки ВОР",
    })
    return {
        "schema": "les.workbook_tool_result.v1",
        "tool": call["tool"],
        "status": "complete",
        "artifact": {
            "revision_id": "rev-2",
            "artifact_id": "artifact-1",
            "revision_no": 2,
            "filename": "vor-r2.xlsx",
            "download_url": "/api/artifacts/rev-2/download",
            "source_scope": ["attachment:read_123456abcdef"],
            "decision_checkpoint_id": "cp-1",
        },
        "source": {"attachment_id": "read_123456abcdef", "sha256": "a" * 64},
        "checkpoint": {"checkpoint_id": "cp-1", "status": "complete"},
        "missing": [],
        "blockers": [],
    }


async def _tracked_workbook_execution(call, context, progress, events, calls):
    calls.append(call)
    return await _fake_workbook_execution(call, context, progress, events)


async def _failing_workbook_execution(call, calls):
    """Сборка книги упала — так ведёт себя занятый диск или битый шаблон."""
    calls.append(call)
    raise RuntimeError("workbook packaging failed")


async def _rejected_workbook_execution(call, calls):
    calls.append(call)
    return {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_vor_workbook",
        "status": "rejected",
        "code": "TOOL_SCOPE_VIOLATION",
        "message": "foreign attachment must not execute",
        "missing": [],
        "blockers": [],
    }


def test_workbook_result_harvests_revision_retry_and_checkpoint():
    harvested = service.harvest_workbook_tool_result(
        {
            "schema": "les.workbook_tool_result.v1",
            "tool": "build_vor_workbook",
            "status": "complete",
            "artifact": {
                "revision_id": "rev-2",
                "artifact_id": "artifact-1",
                "revision_no": 2,
                "filename": "vor-r2.xlsx",
                "download_url": "/api/artifacts/rev-2/download",
                "source_scope": ["attachment:read_123456abcdef"],
                "decision_checkpoint_id": "cp-1",
            },
            "source": {"attachment_id": "read_123456abcdef", "sha256": "a" * 64},
            "checkpoint": {"checkpoint_id": "cp-1", "status": "complete"},
        }
    )

    assert harvested["artifact"]["revision_id"] == "rev-2"
    assert harvested["attachment_retry"]["attachment_id"] == "read_123456abcdef"
    assert harvested["source"] == {
        "attachment_id": "read_123456abcdef",
        "sha256": "a" * 64,
    }
    assert harvested["attachment_retry"]["preserved"] is True
    assert harvested["checkpoint"]["checkpoint_id"] == "cp-1"


def test_workbook_harvest_rejects_artifact_without_bound_attachment_checkpoint_lineage():
    harvested = service.harvest_workbook_tool_result(
        {
            "schema": "les.workbook_tool_result.v1",
            "tool": "build_vor_workbook",
            "status": "complete",
            "artifact": {
                "revision_id": "rev-2",
                "artifact_id": "artifact-1",
                "source_scope": ["attachment:read_foreign"],
                "decision_checkpoint_id": "cp-other",
            },
            "source": {"attachment_id": "read_123456abcdef"},
            "checkpoint": {"checkpoint_id": "cp-1", "status": "complete"},
        }
    )

    assert harvested == {}


def test_workbook_history_projection_redacts_failures_paths_and_unbounded_results():
    raw = {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_vor_workbook",
        "status": "failed",
        "code": "WORKBOOK_GENERATION_FAILED",
        "message": "adapter failed at C:/private/workbook.xlsx",
        "artifact": {
            "artifact_id": "art-1",
            "revision_id": "rev-1",
            "download_url": "/api/artifacts/rev-1/download",
            "source_scope": ["attachment:read_123456abcdef"],
            "decision_checkpoint_id": "cp-1",
            "filename": "C:/private/workbook.xlsx",
            "tool_calls": [{"private": "unbounded result"}],
        },
        "checkpoint": {"checkpoint_id": "cp-1", "status": "failed"},
        "source": {"attachment_id": "read_123456abcdef", "name": "C:/private/source.xlsx"},
        "blockers": ["RuntimeError: private filesystem detail"],
        "result": {"raw": "unbounded result"},
    }

    safe = service.safe_workbook_history_projection(raw)

    assert safe == {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_vor_workbook",
        "status": "failed",
        "code": "WORKBOOK_GENERATION_FAILED",
        "artifact": {
            "artifact_id": "art-1",
            "revision_id": "rev-1",
            "download_url": "/api/artifacts/rev-1/download",
            "source_scope": ["attachment:read_123456abcdef"],
            "decision_checkpoint_id": "cp-1",
        },
        "checkpoint": {"checkpoint_id": "cp-1", "status": "failed"},
        "source": {"attachment_id": "read_123456abcdef"},
    }
    serialized = json.dumps(safe, ensure_ascii=False)
    assert "private" not in serialized
    assert "unbounded result" not in serialized
    assert "RuntimeError" not in serialized


@pytest.mark.asyncio
async def test_chat_workbook_executor_builds_revision_and_streams_checkpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LES_WINDOWS_STATE_ROOT", raising=False)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Раздел", "Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["ОВ", "Воздуховод", "м", 12.5])
    workbook.save(source)
    workbook.close()
    attachment = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )
    progress = []

    async def on_progress(event):
        progress.append(event)

    result = await chat._execute_chat_workbook_tool(
        {
            "call_id": "call-1",
            "tool": "build_vor_workbook",
            "args": {"attachment_id": attachment["attachment_id"]},
        },
        {
            "session_id": "session-1",
            "question": "Собери ВОР",
            "attachment_id": attachment["attachment_id"],
            "dataset_ids": [],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        on_progress,
    )

    assert result["status"] == "complete"
    assert result["artifact"]["revision_no"] == 1
    assert result["source"]["attachment_id"] == attachment["attachment_id"]
    assert f"attachment:{attachment['attachment_id']}" in result["artifact"]["source_scope"]
    assert result["artifact"]["decision_checkpoint_id"] == result["checkpoint"]["checkpoint_id"]
    assert progress[-1]["checkpoint_id"] == result["checkpoint"]["checkpoint_id"]
    assert progress[-1]["label"] == "Собираю строки ВОР"
    assert Path("storage/artifacts/meta.db").is_file()


@pytest.mark.asyncio
async def test_chat_workbook_resolves_overflow_before_projecting_calculation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows = [{"source_row": str(i), "status": "bound"} for i in range(70)]
    payload = {
        "schema": "les.workbook_tool_result.v1", "tool": "build_lsr_workbook",
        "status": "complete", "bound_rows": 70, "row_calculation": rows,
        "artifact": {"revision_id": "rev-full", "download_url": "/api/artifacts/rev-full/download",
                     "source_scope": ["attachment:read_123456abcdef"], "decision_checkpoint_id": "cp-full",
                     "tool_calls": [{"row_calculation": rows}]},
        "source": {"attachment_id": "read_123456abcdef"},
        "checkpoint": {"checkpoint_id": "cp-full", "status": "complete"},
        "missing": [f"row:{i}:coefficient_needs_basis" for i in range(70)], "blockers": [],
    }

    async def build(_args, _context):
        return payload

    monkeypatch.setattr("proxy.services.workbook_tool_service.build_lsr_workbook", build)
    result = await chat._execute_chat_workbook_tool(
        {"tool": "build_lsr_workbook", "args": {"attachment_id": "read_123456abcdef", "decisions": [{"source_row": 1}]}},
        {"session_id": "overflow-owner", "attachment_id": "read_123456abcdef", "dataset_ids": []},
        lambda _event: asyncio.sleep(0),
    )
    assert result["execution"]["status"] == "overflow"
    projected = service.harvest_workbook_tool_result(service.safe_workbook_history_projection(result))
    assert projected["artifact"]["revision_id"] == "rev-full"
    assert service.workbook_row_statuses(projected) == {str(i): "bound" for i in range(70)}


@pytest.mark.asyncio
async def test_chat_lsr_executor_runs_thin_model_decision_adapter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Воздуховод", "м", 12.5])
    workbook.save(source)
    workbook.close()
    attachment = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )
    decisions = [{
        "source_row": "СМР!R9",
        "section": "ОВ",
        "title": "Монтаж воздуховода",
        "unit": "м",
        "quantity": 12.5,
        "norm_code": "ГЭСН20-01-001-01",
        "evidence_refs": ["dataset:fsnb:card:20-01-001-01"],
    }]

    def calculate(rows, **_kwargs):
        assert rows == decisions
        return {
            "schema": "rim_lsr_v1",
            "sections": [],
            "summary": {"input_rows": 1, "bound_rows": 1, "flags": []},
            "row_bindings": [{"row": "СМР!R9", "status": "bound"}],
        }

    def render(_trace, output_path, **_kwargs):
        workbook = openpyxl.Workbook()
        workbook.active.append(["ЛСР"])
        workbook.save(output_path)
        workbook.close()
        return output_path

    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.build_lsr_trace_from_visible_rows",
        calculate,
    )
    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.render_lsr_xlsx",
        render,
    )

    result = await chat._execute_chat_workbook_tool(
        {
            "call_id": "call-lsr-1",
            "tool": "build_lsr_workbook",
            "args": {"attachment_id": attachment["attachment_id"], "decisions": decisions},
        },
        {
            "session_id": "session-1",
            "question": "Собери ЛСР",
            "attachment_id": attachment["attachment_id"],
            "dataset_ids": ["fsnb"],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        lambda _event: asyncio.sleep(0),
    )

    assert result["status"] == "complete"
    assert result["tool"] == "build_lsr_workbook"
    assert result["source"]["rows"] == 1
    assert "dataset:fsnb" in result["artifact"]["source_scope"]
    assert result["blockers"] == []


@pytest.mark.asyncio
async def test_chat_workbook_executor_rejects_model_dataset_outside_chat_scope(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Кабель", "м", 2])
    workbook.save(source)
    workbook.close()
    preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )

    async def on_progress(_event):
        raise AssertionError("rejected execution must not start")

    result = await chat._execute_chat_workbook_tool(
        {
            "tool": "build_vor_workbook",
            "args": {
                "attachment_id": "read_123456abcdef",
                "dataset_ids": ["foreign-dataset"],
            },
        },
        {
            "session_id": "session-1",
            "question": "Собери ВОР",
            "attachment_id": "read_123456abcdef",
            "dataset_ids": [],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        on_progress,
    )

    assert result["code"] == "TOOL_SCOPE_VIOLATION"
    assert "artifact" not in result
    assert not Path("storage/workbook_checkpoints.db").exists()
    assert not Path("storage/artifacts/meta.db").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_dataset_ids", "expected_status"),
    ((["selected-a"], "rejected"), (["selected-b", "selected-a"], "complete")),
)
async def test_chat_workbook_executor_binds_exact_request_dataset_scope(
    tmp_path, monkeypatch, model_dataset_ids, expected_status
):
    """A workbook artifact always records the full server-owned request scope."""
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Кабель", "м", 2])
    workbook.save(source)
    workbook.close()
    attachment = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="source.xlsx",
        root=attachment_root,
    )

    async def on_progress(_event):
        return None

    result = await chat._execute_chat_workbook_tool(
        {
            "tool": "build_vor_workbook",
            "args": {
                "attachment_id": attachment["attachment_id"],
                "dataset_ids": model_dataset_ids,
            },
        },
        {
            "session_id": "session-1",
            "question": "Собери ВОР",
            "attachment_id": attachment["attachment_id"],
            "dataset_ids": ["selected-a", "selected-b"],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        on_progress,
    )

    assert result["status"] == expected_status
    if expected_status == "rejected":
        assert result["code"] == "TOOL_SCOPE_VIOLATION"
        assert "artifact" not in result
        return
    assert result["artifact"]["source_scope"] == [
        f"attachment:{attachment['attachment_id']}",
        "dataset:selected-a",
        "dataset:selected-b",
    ]


@pytest.mark.asyncio
async def test_chat_workbook_executor_rejects_foreign_preserved_attachment_before_execution(
    tmp_path, monkeypatch
):
    """A model cannot switch a request to another server-owned attachment."""
    monkeypatch.chdir(tmp_path)
    attachment_root = tmp_path / "attachments"
    monkeypatch.setenv("LES_CHAT_ATTACHMENT_ROOT", str(attachment_root))
    source = tmp_path / "source.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Наименование", "Ед. изм.", "Количество"])
    workbook.active.append(["Кабель", "м", 2])
    workbook.save(source)
    workbook.close()
    bound = preserve_read_attachment(
        source,
        attachment_id="read_111111111111",
        original_name="bound.xlsx",
        root=attachment_root,
    )
    foreign = preserve_read_attachment(
        source,
        attachment_id="read_222222222222",
        original_name="foreign.xlsx",
        root=attachment_root,
    )

    result = await chat._execute_chat_workbook_tool(
        {
            "tool": "build_vor_workbook",
            "args": {"attachment_id": foreign["attachment_id"]},
        },
        {
            "session_id": "session-1",
            "question": "Собери ВОР",
            "attachment_id": bound["attachment_id"],
            "dataset_ids": [],
            "project_id": None,
            "profile_revision_id": "profile-1",
            "model_identity": "qwen-local",
            "model_preset": "qwen-9b",
        },
        lambda _event: None,
    )

    assert result["status"] == "rejected"
    assert result["code"] == "TOOL_SCOPE_VIOLATION"
    assert not Path("storage/workbook_checkpoints.db").exists()
    assert not Path("storage/artifacts/meta.db").exists()
from proxy.services.canonical_route_service import CanonicalRouteMode
from proxy.services.context_governor_service import (
    ContextKind,
    ContextObject,
    ContextRequiredSectionOverflow,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset


def _governor_preset(
    *, input_tokens: int = 6000, preset_id: str = "fixture-restrictive"
) -> ModelExecutionPreset:
    return ModelExecutionPreset(
        preset_id=preset_id,
        model_family="fixture",
        input_token_limit=input_tokens,
        generation_reserve_tokens=20,
        safety_reserve_tokens=20,
        normal_tool_count=3,
        max_tools=5,
        max_batch_items=5,
        parallel_read_limit=1,
        reasoning_enabled=False,
        source_chain=("test",),
    )


def test_governed_inference_trace_exposes_exact_evidence_but_not_private_memory() -> None:
    messages, packet = service.govern_inference_messages(
        preset=_governor_preset(),
        profile_prefix="bound profile",
        request_payload={"question": "current request"},
        shortlist=[{"name": "read_source"}],
        checkpoint=[ContextObject("checkpoint:1", {"status": "continue"})],
        working_memory=[
            ContextObject("memory:1", {"context_role": "advisory_state", "secret": "hidden"})
        ],
        evidence=[{"source": "evidence payload"}],
        source_map=[{"label": "Источник 1"}],
        tool_exchange=[{"status": "ok"}],
        dialogue=["prior turn"],
    )

    assert [section.kind for section in packet.sections] == list(ContextKind)
    assert [message["role"] for message in messages] == ["system", "user"]
    trace = service.context_packet_trace(packet, purpose="answer")
    assert trace["purpose"] == "answer"
    assert [section["kind"] for section in trace["sections"]] == [kind.value for kind in ContextKind]
    assert "hidden" not in json.dumps(trace)
    evidence = next(section for section in trace["sections"] if section["kind"] == "evidence")
    source_map = next(section for section in trace["sections"] if section["kind"] == "source_map")
    assert evidence["objects"][0]["payload"] == {"source": "evidence payload"}
    assert evidence["objects"][0]["text"] == '{"source":"evidence payload"}'
    assert len(evidence["objects"][0]["sha256"]) == 64
    assert source_map["objects"][0]["payload"] == {"label": "Источник 1"}


def test_context_trace_records_exact_omitted_evidence_ids_and_cursor() -> None:
    _messages, packet = service.govern_inference_messages(
        preset=_governor_preset(input_tokens=90),
        profile_prefix="p",
        request_payload="q",
        evidence=["x" * 200],
        source_map=[{"label": "Источник 1"}],
    )

    trace = service.context_packet_trace(packet, purpose="tool_decision")
    omitted = next(item for item in trace["omissions"] if item["kind"] == "evidence")

    assert omitted["object_ids"] == ["evidence:0"]
    assert omitted["cursor"].startswith("ctx:evidence:")


def test_context_trace_fingerprints_private_request_and_complete_messages():
    import hashlib
    messages, packet = service.govern_inference_messages(
        preset=_governor_preset(), profile_prefix='private profile',
        request_payload='original user request', evidence=['source'],
    )
    trace = service.context_packet_trace(packet, purpose='answer')
    request = next(s for s in trace['sections'] if s['kind'] == 'request')
    assert request['object_fingerprints'][0]['sha256'] == hashlib.sha256(b'original user request').hexdigest()
    assert trace['message_fingerprints'] == [dict(
        role=m['role'], chars=len(m['content']),
        sha256=hashlib.sha256(m['content'].encode('utf-8')).hexdigest()) for m in messages]
    assert 'original user request' not in json.dumps(trace)
    assert 'private profile' not in json.dumps(trace)


def test_governed_inference_rejects_required_overflow_before_provider_call() -> None:
    provider_calls = []

    with pytest.raises(ContextRequiredSectionOverflow):
        messages, _packet = service.govern_inference_messages(
            preset=_governor_preset(input_tokens=50),
            profile_prefix="profile is too large for this deliberately tiny fixture",
            request_payload={"question": "also required"},
        )
        provider_calls.append(messages)

    assert provider_calls == []


def test_cloud_fallback_re_resolves_and_repacks_before_local_provider() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    resolve_at = source.index("fallback_preset = resolve_transport_execution_profile(")
    repack_at = source.index("fallback_messages, fallback_packet = govern_inference_messages(")
    send_at = source.index("fallback_body = {")
    assert resolve_at < repack_at < send_at
    assert '"messages": fallback_messages' in source
    assert "fallback_preset.generation_reserve_tokens" in source
    assert 'purpose="answer_fallback"' in source


def test_general_evidence_execution_is_outside_http_router():
    router_source = inspect.getsource(chat._run_chat)
    evidence_source = inspect.getsource(service._execute_chat_evidence_application)

    assert "retrieval_trace = retrieval.payload()" not in router_source
    assert "build_retrieval_evidence_packet(" not in router_source
    assert "async with gen_semaphore" not in router_source
    assert "retrieval_trace = retrieval.payload()" in evidence_source
    assert "build_retrieval_evidence_packet(" in evidence_source
    assert "async with acquire_generation_slot" in evidence_source


def test_evidence_boundary_is_typed_and_does_not_capture_namespaces():
    router_source = inspect.getsource(chat._run_chat)
    service_source = inspect.getsource(service)

    assert "globals()" not in router_source
    assert "locals()" not in router_source
    assert "global_scope" not in service_source
    assert "local_scope" not in service_source
    assert {field.name for field in fields(service.EvidenceRequestContext)} >= {
        "req", "dataset_ids", "query_route_payload", "target_file_ref", "topic_retrieval_plan"
    }
    assert {field.name for field in fields(service.EvidenceRuntimeDeps)} >= {
        "state", "rag_backend", "cache", "llm_runtime", "table_query_response"
    }
    assert {field.name for field in fields(service.ResponseBoundary)} == {
        "save_chat_history", "token_sink", "version_stamp"
    }


def test_router_builds_explicit_evidence_contracts():
    router_source = inspect.getsource(chat._run_chat)

    assert "EvidenceRequestContext(" in router_source
    assert "EvidenceRuntimeDeps(" in router_source
    assert "ResponseBoundary(" in router_source
    assert "run_chat_evidence_application(" in router_source


@pytest.mark.asyncio
async def test_typed_contract_maps_every_internal_binding(monkeypatch):
    dummy = lambda *_args, **_kwargs: None
    request = service.EvidenceRequestContext(
        req=SimpleNamespace(question="test"),
        dataset_ids=["ds"],
        effective_dataset_filter="DS",
        resolved_dataset_names=["Dataset"],
        dataset_name_by_id={"ds": "Dataset"},
        query_route_payload={"channel": "rag"},
        target_doc_filter=[],
        target_file_ref=None,
        topic_doc_filter=[],
        topic_retrieval_plan=None,
        inventory_requested=False,
        study_requested=False,
        memory_block="",
        session_block="",
        class_suggestions=[],
        use_semantic_cache=False,
        use_validation=False,
        validation_skip_reason="test",
        route=SimpleNamespace(intent="rag"),
        table_result=None,
        request_started_at=1.0,
    )
    runtime = service.EvidenceRuntimeDeps(
        state="state", rag_backend="rag", cache="cache", cache_embedding=None,
        cache_marker="miss", cache_scope="scope",
        assistant_text=dummy, augment_model_tool_args=dummy,
        chat_model_final_answer=dummy, cloud_body_for_model=dummy,
        compact_tool_result_for_prompt=dummy, dataset_ids_from_chunks=dummy,
        dataset_sensitivities=dummy, env_bool=dummy, env_float=dummy, env_int=dummy,
        expand_context_windows=dummy,
        format_tool_results_for_model=dummy, generation_token_budget=dummy,
        llm_runtime=dummy, local_context_budget=dummy, mlx_runtime=dummy,
        names_for_dataset_ids=dummy, notebook_study_validation_status=dummy,
        ollama_native_complete=dummy, parse_model_tool_calls=dummy,
        prepare_notebook_reader_memory=dummy, record_cloud_cost=dummy,
        retrieve_chat_chunks=dummy,
        source_excerpts=dummy, table_query_response=dummy,
        cloud_fallback_models=dummy, cloud_model_timeout=dummy,
    )
    boundary = service.ResponseBoundary(
        save_chat_history=dummy,
        token_sink=None,
        version_stamp=dummy,
    )
    captured = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return {"answer": "ok"}

    monkeypatch.setattr(service, "_execute_chat_evidence_application", fake_execute)

    result = await service.run_chat_evidence_application(request, runtime, boundary)

    assert result == {"answer": "ok"}
    assert captured["req"] is request.req
    assert captured["_dataset_ids"] == ["ds"]
    assert captured["state"] == "state"
    assert captured["source_excerpts"] is dummy
    assert captured["save_chat_history"] is dummy


@pytest.mark.asyncio
async def test_shadow_candidate_executes_only_one_decision_and_redacts_result() -> None:
    calls = []

    class FakeHarness:
        async def call_async(self, tool, args, **policy):
            calls.append((tool, args, policy))
            return {
                "schema": "les_tool_result_v1",
                "status": "ok",
                "result": {"secret_text": "must not enter shadow trace"},
                "execution": {
                    "schema": "les_tool_execution_v1",
                    "status": "ok",
                    "code": "TOOL_OK",
                },
            }

    trace = await service.execute_canonical_shadow_decision(
        proposed_calls=[
            {"tool": "read_source", "args": {"doc_id": "d1"}},
            {"tool": "read_source", "args": {"doc_id": "d2"}},
        ],
        allowed_tools={"read_source"},
        dataset_ids=["selected"],
        tool_harness=FakeHarness(),
    )

    assert len(calls) == 1
    assert calls[0][2]["shadow"] is True
    assert trace["executed_calls"] == 1
    assert trace["pending_calls"] == 1
    assert trace["user_visible"] is False
    assert "secret_text" not in str(trace)


def test_grounded_application_never_uses_answer_cache_or_code_no_data_final() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "if document_grounding_enabled:" in source
    assert "use_semantic_cache = False" in source
    assert '"empty_retrieval_model_first_v1"' in source
    assert "empty_scoped_retrieval_no_data_v1" not in source
    assert "if not chunks and effective_dataset_filter:" not in source
    assert "if not chunks and target_file_ref" not in source


def test_plain_ai_scope_removes_only_document_evidence_tools() -> None:
    tools = service.tools_for_document_scope(
        ["search_sources", "read_source", "calculate", "send_mail"],
        enabled=False,
    )

    assert tools == ["calculate", "send_mail"]
    assert service.tools_for_document_scope(
        ["search_sources", "read_source", "calculate"], enabled=True
    ) == ["search_sources", "read_source", "calculate"]


def test_estimator_role_uses_model_authored_initial_rag_query() -> None:
    assert service.profile_uses_model_driven_retrieval(
        {
            "mode": "estimator",
            "rag_policy": {
                "system_datasets": ["smeta"],
                "model_authored_initial_query": True,
            },
        }
    ) is True


def test_native_tool_selector_keeps_attachment_rows_inside_9b_context() -> None:
    attachment = "\n".join(
        f"{row}. Работа {row} | шт. | {row}" for row in range(1, 31)
    )
    evidence = service.selector_evidence_payload(
        attachment_context=attachment,
        rendered_context="[ФРАГМЕНТЫ ИЗ ИСТОЧНИКОВ]\nНет найденных фрагментов.",
    )
    messages, packet = service.govern_inference_messages(
        preset=_governor_preset(input_tokens=6000, preset_id="qwen-9b-restrictive"),
        profile_prefix=("Роль сметчика. " * 380),
        request_payload={"question": "Собери ЛСР", "attachment_id": "read_123456abcdef"},
        shortlist=service.selector_context_shortlist(
            [
                {"name": "search_sources", "input_schema": {"type": "object"}},
                {"name": "build_lsr_workbook", "input_schema": {"type": "object"}},
            ],
            native_tool_schemas=True,
        ),
        evidence=evidence,
    )

    visible = str(messages)
    assert "1. Работа 1 | шт. | 1" in visible
    assert "5. Работа 5 | шт. | 5" in visible
    assert not any(section.kind is ContextKind.TOOL_SHORTLIST for section in packet.sections)


def test_model_authored_first_search_is_not_labelled_as_empty_retrieval() -> None:
    empty_status = "[СТАТУС ИСТОЧНИКОВ: ФРАГМЕНТЫ НЕ НАЙДЕНЫ]"

    assert service.initial_selector_context(
        empty_status,
        model_authored_initial_query=True,
    ) == ""
    assert service.initial_selector_context(
        empty_status,
        model_authored_initial_query=False,
    ) == empty_status


def test_tool_selector_uses_thin_role_contract_and_bound_skill() -> None:
    prompt = service.profile_tool_selector_prompt(
        {
            "mode": "estimator",
            "prompt_text": "LONG ANSWER PROMPT MUST NOT ENTER TOOL DECISION",
            "skill_text": "Сначала изучи ВОР, затем ищи нормы.",
        }
    )

    assert "профиль estimator" in prompt
    assert "Сначала изучи ВОР, затем ищи нормы." in prompt
    assert "LONG ANSWER PROMPT" not in prompt
    assert "предметные решения" in prompt
    assert service.profile_uses_model_driven_retrieval(
        {
            "mode": "estimator",
            "rag_policy": {"system_datasets": ["smeta"]},
        }
    ) is True
    assert service.profile_uses_model_driven_retrieval(
        {
            "mode": "search",
            "rag_policy": {"model_authored_initial_query": True},
        }
    ) is True


def test_application_routes_model_search_sources_through_canonical_research_service() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "ModelResearchToolService(" in source
    assert "model_research_tools.execute(call)" in source
    assert "retrieve=retrieve_chat_chunks" in source


def test_model_research_loop_is_evidence_first_and_model_stopped() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    initial_packet = source.index("initial_evidence_packet,")
    selector_loop = source.index(
        "while time.monotonic() < research_deadline and calls_remaining > 0:"
    )
    assert initial_packet < selector_loop
    assert "evidence=selector_evidence" in source
    assert "source_map=selector_source_map" in source
    assert "research_result.chunks" in source
    assert "seen_call_signatures" not in source
    assert 'stop_reason = "model_stop"' in source


def test_model_research_loop_enforces_call_budget_across_all_rounds() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "calls_remaining = max_calls" in source
    assert "while time.monotonic() < research_deadline and calls_remaining > 0:" in source
    assert "max_calls=calls_remaining" in source
    assert "calls_remaining -= 1" in source
    assert 'stop_reason = "calls_budget"' in source


def test_ordinary_chat_does_not_semantically_validate_or_rewrite_model_answer() -> None:
    source = inspect.getsource(service._execute_chat_evidence_application)

    assert "use_validation = False" in source
    assert "_chat_model_final_answer(answer" not in source
    assert "_notebook_study_validation_status(" not in source
    assert 'final_evidence_packet["evidence_status"] = "partial"' not in source
    assert 'crag_status = "UNVALIDATED"' not in source[source.index("citation_check ="):]


@pytest.mark.asyncio
async def test_shadow_failure_is_redacted_and_cannot_escape_to_legacy_path() -> None:
    class ThrowingHarness:
        async def call_async(self, *_args, **_kwargs):
            raise RuntimeError("secret candidate failure")

    trace = await service.safe_execute_canonical_shadow_decision(
        proposed_calls=[{"tool": "read_source", "args": {"doc_id": "d1"}}],
        allowed_tools={"read_source"},
        dataset_ids=["selected"],
        tool_harness=ThrowingHarness(),
    )

    assert trace["status"] == "error"
    assert trace["error_type"] == "RuntimeError"
    assert trace["attempted_calls"] == 1
    assert "secret candidate failure" not in str(trace)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        "normal",
        "normal_unscoped",
        "selector_overflow",
        "cloud_retry",
        "active",
        "active_web_research",
        "active_workbook",
        "active_workbook_private_arg",
        "active_workbook_rejected",
        "active_model_rag_result",
        "active_model_rag_full_read",
        "active_model_rag_full_read_fail",
        "active_model_rag_p915_factory_answer",
        "active_model_rag_p915_factory_read",
        "active_model_rag_labelled_queries",
        "active_model_rag_work_steps",
        "active_model_rag_full_attachment",
        "practice_none",
        "practice_frequency",
        "practice_similar",
        "practice_both",
        "practice_frequency_header",
        "smeta_budget_default",
        "smeta_budget_short",
        "active_model_rag_recovery",
        "active_model_rag_portion_pending",
        "active_model_rag_portion_invalid",
        "active_model_rag_portion_ambiguous",
        "active_model_rag_portion_packaging_error",
        "active_model_rag_portion_packaging_cancel",
        "active_model_rag_portion_delivery_cancel",
        "active_model_rag_portion_repackage",
        "active_model_rag_portion_operations_qualified",
        "active_model_rag_portion_operations_numeric",
        "active_model_rag_portion_named_aliases",
        "active_model_rag_portion_unnamed_aliases",
        "candidate_workbook",
        "shadow_workbook",
        "legacy_workbook",
        "repeat_failed",
        "active_output_control",
        "active_output_truncated",
    ],
)
async def test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count(
    monkeypatch,
    tmp_path,
    scenario,
) -> None:
    p915_factory = scenario in {'active_model_rag_p915_factory_answer','active_model_rag_p915_factory_read'}
    if p915_factory:
        scenario = 'active_model_rag_full_read' if scenario.endswith('_read') else 'active_model_rag_result'
    model_full_read_fail = scenario == "active_model_rag_full_read_fail"
    model_full_read = scenario in {"active_model_rag_full_read", "active_model_rag_full_read_fail"}
    if model_full_read:
        scenario = "active_model_rag_result"
    work_steps_delivery = scenario == 'active_model_rag_work_steps'
    if work_steps_delivery:
        scenario = 'active_model_rag_result'
    archive_header = scenario == 'practice_frequency_header'
    if archive_header:
        scenario = 'practice_frequency'
    labelled_queries = scenario == 'active_model_rag_labelled_queries'
    if labelled_queries:
        scenario = 'active_model_rag_result'
    full_attachment = scenario == 'active_model_rag_full_attachment'
    if full_attachment:
        scenario = 'active_model_rag_result'
    smeta_budget = scenario.removeprefix("smeta_budget_") if scenario.startswith("smeta_budget_") else None
    if smeta_budget:
        scenario = "active_model_rag_result"
    experiment = scenario.removeprefix("practice_") if scenario.startswith("practice_") else None
    if experiment:
        scenario = "active_model_rag_result"
    portion_case = scenario if scenario.startswith("active_model_rag_portion_") else ""
    if portion_case:
        scenario = "active_model_rag_result"
    selector_overflow = scenario == "selector_overflow"
    output_boundary = scenario.startswith("active_output_")
    cloud_retry = scenario == "cloud_retry"
    workbook_profile = scenario in {
        "active_workbook",
        "active_workbook_private_arg",
        "active_workbook_rejected",
        "active_model_rag_result",
        "active_model_rag_recovery",
        "candidate_workbook",
        "shadow_workbook",
        "legacy_workbook",
    }
    active_workbook = scenario in {
        "active_workbook",
        "active_workbook_private_arg",
        "active_workbook_rejected",
        "active_model_rag_result",
        "active_model_rag_recovery",
        "candidate_workbook",
    }
    candidate_acceptance = scenario == "candidate_workbook"
    rejected_workbook = scenario == "active_workbook_rejected"
    model_rag_recovery = scenario == "active_model_rag_recovery"
    model_rag_result = scenario in {
        "active_model_rag_result",
        "active_model_rag_recovery",
    }
    active_web_research = scenario == "active_web_research"
    active = scenario in {
        "active",
        "active_web_research",
        "active_workbook",
        "active_workbook_private_arg",
        "active_workbook_rejected",
        "active_model_rag_result",
        "active_model_rag_recovery",
        "candidate_workbook",
    }
    active = active or output_boundary
    inactive_workbook = workbook_profile and not active
    model_calls = []
    shortlist_policies = []
    shadow_calls = []
    executor_codes = []
    legacy_calls = []
    history_rows = []
    progress_events = []
    workbook_executor_calls = []
    captured_web_configs = []
    rag_queries = []
    research_executions = []
    full_read_code = "ГЭСНм08-02-401-01"
    full_resources = [
        {"row_id": 901, "kind": "labor", "code": "FULL-LABOR", "name": "FULL_LABOR_PROOF", "unit": "чел.-ч", "per_unit": 3.25},
        {"row_id": 902, "kind": "machine", "code": "FULL-MACHINE", "name": "FULL_MACHINE_PROOF", "unit": "маш.-ч", "per_unit": 0.5},
        {"row_id": 903, "kind": "material", "code": "FULL-MATERIAL", "name": "FULL_MATERIAL_PROOF", "unit": "кг", "per_unit": 7.125},
    ]
    from proxy.services.model_research_tool_service import ModelResearchToolService
    original_research_execute = ModelResearchToolService.execute

    async def track_research_execute(reader, call):
        research_executions.append((dict(call), reader._dataset_ids))
        return await original_research_execute(reader, call)

    monkeypatch.setattr(ModelResearchToolService, "execute", track_research_execute)
    exact_decisions = [
        {
            "source_row": 1,
            "section": "ЭОМ",
            "title": "монтаж шкафа управления",
            "unit": "шт.",
            "quantity": 2.0,
            "norm_code": "ГЭСНм08-02-401-01",
            "analogue": "Монтаж оборудования по найденной карточке нормы",
            "coverage": "прямое соответствие",
            "evidence_refs": ["Q1.H1"],
        }
    ]
    protected_db = tmp_path / "protected.db"
    with sqlite3.connect(protected_db) as conn:
        conn.execute("CREATE TABLE protected_events (value TEXT NOT NULL)")

    def protected_hash():
        with sqlite3.connect(protected_db) as conn:
            rows = conn.execute(
                "SELECT value FROM protected_events ORDER BY rowid"
            ).fetchall()
        return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()

    before_protected = protected_hash()

    class FakeResponse:
        status_code = 200

        def __init__(self, content):
            self._content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": self._content}}],
                "usage": {"completion_tokens": 7},
            }

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url, *, json, **_kwargs):
            system_text = str(json["messages"][0]["content"])
            if "исследовательским чтением LES" in system_text:
                model_calls.append("selector")
                if model_calls.count("selector") > 1 and scenario != "repeat_failed":
                    return FakeResponse('{"calls":[]}')
                return FakeResponse(
                    '{"calls":['
                    '{"tool":"read_source","args":{"doc_id":"d1"}},'
                    '{"tool":"read_source","args":{"doc_id":"d2"}}]}'
                )
            if cloud_retry and "cloud.fixture" in _url:
                model_calls.append("cloud_final")
                raise service.httpx.ConnectError("fixture cloud failure")
            if cloud_retry:
                model_calls.append("local_final")
                if model_calls.count("local_final") == 1:
                    return FakeResponse("")
                return FakeResponse("legacy visible answer")
            model_calls.append("final")
            return FakeResponse("legacy visible answer")

    from proxy.services.tool_contract_service import (
        EffectClass,
        IdempotencyPolicy,
        ResultBudget,
        RetryPolicy,
        ToolContract,
    )
    from proxy.services.tool_registry_service import ToolRegistration, ToolRegistry
    from proxy.services.trusted_executor_service import (
        ExecutionRequest,
        TrustedExecutor,
    )

    def persistence_probe_handler(args):
        with sqlite3.connect(protected_db) as conn:
            conn.execute("INSERT INTO protected_events VALUES (?)", (args["doc_id"],))
        return {
            "schema": "les_tool_result_v1",
            "tool": "read_source",
            "operation": "read",
            "inputs": [dict(args)],
            "status": "error" if scenario == "repeat_failed" else "ok",
            "result": {},
            "sources": [],
            "missing": [],
            "warnings": [],
            "trace": "persistence probe",
            "decision_required_from_model": True,
        }

    registry = ToolRegistry(
        [
            ToolRegistration(
                contract=ToolContract(
                    name="read_source",
                    version="1.0.0",
                    title="Read source",
                    category="source",
                    summary="Read one source",
                    input_schema={
                        "type": "object",
                        "required": ["doc_id"],
                        "properties": {"doc_id": {"type": "string"}},
                        "additionalProperties": False,
                    },
                    result_schema="les_tool_result_v1",
                    effect=EffectClass.READ,
                    scopes=("dataset",),
                    timeout_seconds=30,
                    retry=RetryPolicy.SAFE,
                    idempotency=IdempotencyPolicy.DERIVED,
                    result_budget=ResultBudget(max_chars=7000, max_items=20),
                    model_owned_fields=(),
                    provenance="source_refs_required",
                    tags=("shadow_validate_only",),
                ),
                handler=persistence_probe_handler,
            )
        ]
    )
    executor = TrustedExecutor(
        registry,
        scope_resolver=lambda _contract, _args: ("selected",),
    )

    class ExecutorBackedHarness:
        def shortlist(self, *_args, **kwargs):
            shortlist_policies.append(dict(kwargs))
            if active_web_research:
                return {
                    "schema": "les_tool_shortlist_v1",
                    "tools": [
                        {
                            "name": "web_search",
                            "summary": "Search public web",
                            "input_schema": {
                                "type": "object",
                                "properties": {"q": {"type": "string"}},
                                "required": ["q"],
                                "additionalProperties": False,
                            },
                        },
                        {
                            "name": "web_read",
                            "summary": "Read selected public page",
                            "input_schema": {
                                "type": "object",
                                "properties": {"url": {"type": "string"}},
                                "required": ["url"],
                                "additionalProperties": False,
                            },
                        },
                    ],
                }
            if model_rag_result:
                return {
                    "schema": "les_tool_shortlist_v1",
                    "tools": [
                        *(
                            [
                                {
                                    "name": "build_vor_workbook",
                                    "summary": "Extract a VOR workbook without estimating it",
                                    "input_schema": {
                                        "type": "object",
                                        "properties": {"attachment_id": {"type": "string"}},
                                        "required": ["attachment_id"],
                                        "additionalProperties": False,
                                    },
                                }
                            ]
                            if model_rag_recovery
                            else []
                        ),
                        {
                            "name": "search_sources",
                            "summary": "Search frozen datasets with native RRF",
                            "input_schema": {
                                "type": "object",
                                "properties": {"q": {"type": "string"}},
                                "required": ["q"],
                                "additionalProperties": False,
                            },
                        },
                        {
                            "name": "build_lsr_workbook",
                            "summary": "Render model decisions as XLSX",
                            "input_schema": {
                                "type": "object",
                                "properties": {
                                    "attachment_id": {"type": "string"},
                                    "decisions": {"type": "array"},
                                },
                                "required": ["attachment_id", "decisions"],
                                "additionalProperties": False,
                            },
                        },
                    ],
                }
            return {
                "schema": "les_tool_shortlist_v1",
                "tools": [{"name": "build_vor_workbook" if workbook_profile else "read_source"}],
            }

        async def call_async(self, tool, args, **policy):
            shadow_calls.append((tool, dict(args)))
            envelope = await executor.execute(
                ExecutionRequest(
                    call_id="shadow-call-1",
                    tool_name=tool,
                    arguments=args,
                    allowed_dataset_ids=tuple(policy["allowed_dataset_ids"]),
                    actor_id=str(policy["actor_id"]),
                    actor_role=str(policy["actor_role"]),
                    approval_receipt_id=None,
                    idempotency_key=None,
                    deadline_monotonic=float(
                        policy.get("deadline_monotonic", time.monotonic() + 120)
                    ),
                    shadow=bool(policy["shadow"]),
                )
            )
            executor_codes.append(envelope.code)
            if not workbook_profile:
                assert envelope.code == (
                    "TOOL_SCOPE_VIOLATION"
                    if scenario == "normal_unscoped"
                    else "TOOL_WOULD_EXECUTE"
                )
            raise RuntimeError("secret shadow failure")

        def call(self, tool, args):
            legacy_calls.append((tool, dict(args)))
            if active_web_research and tool == "web_search":
                return {
                    "schema": "les_tool_result_v1",
                    "tool": "web_search",
                    "operation": "search",
                    "inputs": [dict(args)],
                    "status": "ok",
                    "result": {
                        "query": args["q"],
                        "requested_mode": "extended",
                        "effective_mode": "extended",
                        "provider": "searxng",
                        "degraded": False,
                        "fallback_reason": "",
                        "results": [
                            {
                                "title": "Каталог материалов",
                                "snippet": "Цены на цемент и арматуру",
                                "url": "https://public.example/materials",
                                "domain": "public.example",
                            }
                        ],
                    },
                    "sources": [
                        {
                            "kind": "web",
                            "title": "Каталог материалов",
                            "url": "https://public.example/materials",
                            "domain": "public.example",
                        }
                    ],
                    "missing": [],
                    "warnings": [],
                    "trace": "fixture search",
                    "decision_required_from_model": True,
                }
            if active_web_research and tool == "web_read":
                return {
                    "schema": "les_tool_result_v1",
                    "tool": "web_read",
                    "operation": "read",
                    "inputs": [dict(args)],
                    "status": "ok",
                    "result": {
                        "requested_url": args["url"],
                        "final_url": args["url"],
                        "title": "Каталог материалов",
                        "text": "Цемент — 650 руб.; арматура — 72 000 руб./т.",
                        "text_truncated": False,
                        "retrieved_at": "2026-09-02T10:00:00+00:00",
                    },
                    "sources": [
                        {
                            "kind": "web_page",
                            "title": "Каталог материалов",
                            "url": args["url"],
                        }
                    ],
                    "missing": [],
                    "warnings": [],
                    "trace": "fixture read",
                    "decision_required_from_model": True,
                }
            return {
                "schema": "les_tool_result_v1",
                "tool": tool,
                "operation": "read",
                "inputs": [dict(args)],
                "status": "missing",
                "result": {},
                "sources": [],
                "missing": ["test fixture"],
                "warnings": [],
                "trace": "legacy fixture",
                "decision_required_from_model": True,
            }

    class FakeRetrieval:
        trace = SimpleNamespace(status="ok", error_code="")
        quality = SimpleNamespace(status="weak", top_score=0.0)

        def __init__(self, chunks=()):
            self.chunks = list(chunks)

        def payload(self):
            return {"schema": "retrieval_trace_v1", "status": "ok"}

    class FakeWindows:
        def __init__(self, chunks=()):
            self.chunks = list(chunks)

        def payload(self):
            return {"schema": "context_windows_v1", "count": 0}

    runtime_config = SimpleNamespace(
        provider="openai" if cloud_retry else "mlx",
        model="cloud-fixture-model" if cloud_retry else "fixture-model",
        base_url="http://cloud.fixture" if cloud_retry else "http://fixture.invalid",
        chat_url=(
            "http://cloud.fixture/v1/chat/completions"
            if cloud_retry else "http://fixture.invalid/v1/chat/completions"
        ),
        api_key="",
        supports_validation=not cloud_retry,
    )
    mlx_runtime_config = SimpleNamespace(
        provider="mlx",
        model="local-fixture-model",
        base_url="http://local.fixture",
        chat_url="http://local.fixture/v1/chat/completions",
        api_key="",
        supports_validation=True,
    )
    state = SimpleNamespace(
        reranker_available=False,
        reranker_cls=None,
        llm_semaphore=asyncio.Semaphore(1),
        metrics_cache={},
        crag_stats={"no_data": 0, "hallucination": 0, "verified": 0},
        chat_metrics={
            "latency_search": [],
            "latency_gen": [],
            "tokens": [],
            "crag_fail": 0,
        },
    )

    from proxy.services import tool_harness_service

    def fixture_harness(**kwargs):
        captured_web_configs.append(kwargs.get("web_config"))
        return ExecutorBackedHarness()

    monkeypatch.setattr(tool_harness_service, "harness", fixture_harness)
    if active_web_research:
        monkeypatch.setenv("LES_WEB_SEARCH_MODE", "extended")
        monkeypatch.setenv("LES_SEARXNG_URL", "http://127.0.0.1:8888")
        monkeypatch.setenv("LES_CRAWL4AI_URL", "http://127.0.0.1:11235")
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        service,
        "rules_pre_verdict",
        lambda *_args, **_kwargs: pytest.fail("ordinary chat must not invoke semantic validator"),
    )
    monkeypatch.setattr(
        service,
        "maybe_answer_table_query",
        lambda *_a, **_k: pytest.fail(
            "ordinary chat must not invoke the legacy table answer interceptor"
        ),
    )
    monkeypatch.setattr(service, "dataset_memory_prompt_excerpt", lambda *_a, **_k: "")
    active_transport = None
    active_connection = None
    if active:
        from proxy.services.canonical_route_service import (
            CanonicalRouteDecision,
            CanonicalRouteMode,
        )
        from proxy.services.model_connection_contracts import ConnectionLocality, ConnectionRole
        from proxy.services.openai_compatible_transport_service import InferenceResponse

        active_connection = SimpleNamespace(
            connection_id="conn:active",
            revision_id="conn:active:r3",
            display_name="Active fixture",
            model_id="active-model",
            locality=ConnectionLocality.LOOPBACK,
            base_url="http://127.0.0.1:1919/v1",
            secret_ref=None,
            effective_preset=_governor_preset(
                input_tokens=18000 if model_full_read or p915_factory else 6000,
                preset_id="active-preset",
            ),
        )
        if smeta_budget:
            from dataclasses import replace
            active_connection.effective_preset = replace(
                active_connection.effective_preset,
                input_token_limit=32768, generation_reserve_tokens=8192,
            )

        class ActiveResolver:
            def resolve(self, role, **_kwargs):
                assert role is ConnectionRole.ANSWER
                return active_connection

            def resolve_fallback(self, *_args, **_kwargs):
                raise AssertionError("fallback must not be used")

        class ActiveTransport:
            def __init__(self):
                self.revisions = []
                self.requests = []
                if active_web_research:
                    self.responses = [
                        InferenceResponse(
                            text="",
                            tool_calls=(
                                {
                                    "id": "web-search-1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"q":"цены цемента и арматуры"}',
                                    },
                                },
                            ),
                            finish_reason="tool_calls",
                            usage={},
                        ),
                        InferenceResponse(
                            text="",
                            tool_calls=(
                                {
                                    "id": "web-read-1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_read",
                                        "arguments": '{"url":"https://public.example/materials"}',
                                    },
                                },
                            ),
                            finish_reason="tool_calls",
                            usage={},
                        ),
                        InferenceResponse(
                            text="Исследование завершено",
                            tool_calls=(),
                            finish_reason="stop",
                            usage={},
                        ),
                        InferenceResponse(
                            text="Цемент — 650 руб.; арматура — 72 000 руб./т.",
                            tool_calls=(),
                            finish_reason="stop",
                            usage={"completion_tokens": 12},
                        ),
                    ]
                elif model_rag_result:
                    self.responses = [
                        InferenceResponse(
                            text=(
                                "монтаж шкафа управления\n"
                                "прокладка контрольного кабеля"
                            ) if not labelled_queries else (
                                "Запрос 1: монтаж шкафа управления\n"
                                "Запрос 2: прокладка контрольного кабеля\n"
                                "Запрос 3: монтаж шкафа управления"
                            ),
                            tool_calls=(),
                            finish_reason="stop",
                            usage={},
                        ),
                        InferenceResponse(
                            text=(
                                "active visible answer\n\n"
                                "| source_row | section | title | unit | quantity | norm_code | analogue | coverage | coefficient | evidence_refs |\n"
                                "|---:|---|---|---|---:|---|---|---|---:|---|\n"
                                "| 1 | ЭОМ | монтаж шкафа управления | шт. | 2 | ГЭСНм08-02-401-01 | "
                                "Монтаж оборудования по найденной карточке нормы | прямое соответствие | | Q1.H1 |"
                            ),
                            tool_calls=(),
                            finish_reason="stop",
                            usage={"completion_tokens": 5},
                        ),
                    ]
                else:
                    self.responses = [
                        InferenceResponse(
                            text="",
                            tool_calls=(
                                (
                                    {"id": "workbook-call-1", "type": "function", "function": {"name": "build_vor_workbook", "arguments": '{"attachment_id":"read_123456abcdef"}'} },
                                    {"id": "workbook-call-2", "type": "function", "function": {"name": "build_vor_workbook", "arguments": '{"attachment_id":"read_123456abcdef"}'} },
                                )
                                if rejected_workbook
                                    else ({"id": "workbook-call-1", "type": "function", "function": {"name": "build_vor_workbook", "arguments": ('{"attachment_id":"read_123456abcdef","question":"C:/private/les/SECRET_TRACE_TOKEN"}' if scenario == "active_workbook_private_arg" else '{"attachment_id":"read_123456abcdef"}')} },)
                            ) if active_workbook else (
                                {"id": "c1", "type": "function", "function": {"name": "read_source", "arguments": '{"doc_id":"d1"}'}},
                                {"id": "c2", "type": "function", "function": {"name": "read_source", "arguments": '{"doc_id":"d2"}'}},
                            ),
                            finish_reason="tool_calls",
                            usage={},
                        ),
                        InferenceResponse(
                            text=(
                                '{"calls":[]}'
                                if rejected_workbook or not active_workbook
                                else "active visible answer"
                            ),
                            tool_calls=(),
                            finish_reason="stop",
                            usage={"completion_tokens": 5},
                        ),
                        InferenceResponse(
                            text="active visible answer",
                            tool_calls=(),
                            finish_reason="stop",
                            usage={"completion_tokens": 5},
                        ),
                    ]

            async def complete(self, connection, _request):
                self.revisions.append(connection.revision_id)
                self.requests.append(_request)
                if model_full_read_fail and len(self.requests) == 3:
                    raise RuntimeError("continuation transport failure fixture")
                return self.responses.pop(0)

        active_transport = ActiveTransport()
        if model_full_read:
            active_transport.responses.insert(1, InferenceResponse(
                text="",
                tool_calls=({"id": "full-norm-read-1", "type": "function",
                             "function": {"name": "search_sources", "arguments": json.dumps({"q": full_read_code}, ensure_ascii=False)}},),
                finish_reason="tool_calls", usage={},
            ))
        if output_boundary:
            active_transport.responses[2] = InferenceResponse(
                text=('{"context_role":"advisory_state","item_id":"chat-checkpoint:x"}'
                      if scenario == "active_output_control" else "Расход 12.5 м3/ч [Источник 1]"),
                tool_calls=(), finish_reason="length" if scenario == "active_output_truncated" else "stop",
                usage={"completion_tokens": 128},
            )
            active_transport.responses.append(InferenceResponse(
                text="Чистый ответ [Источник 1]", tool_calls=(), finish_reason="stop", usage={"completion_tokens": 5},
            ))
        monkeypatch.setattr(
            service,
            "resolve_canonical_route",
            lambda **_kwargs: CanonicalRouteDecision(
                requested=(
                    CanonicalRouteMode.SHADOW
                    if candidate_acceptance
                    else CanonicalRouteMode.ACTIVE
                ),
                effective=(
                    CanonicalRouteMode.SHADOW
                    if candidate_acceptance
                    else CanonicalRouteMode.ACTIVE
                ),
                source="test",
                reason=("receipt_missing" if candidate_acceptance else "exact_test_receipt"),
                restart_required=False,
            ),
        )
    elif scenario == "legacy_workbook":
        from proxy.services.canonical_route_service import (
            CanonicalRouteDecision,
            CanonicalRouteMode,
        )

        monkeypatch.setattr(
            service,
            "resolve_canonical_route",
            lambda **_kwargs: CanonicalRouteDecision(
                requested=CanonicalRouteMode.LEGACY,
                effective=CanonicalRouteMode.LEGACY,
                source="test",
                reason="explicit_legacy",
                restart_required=False,
            ),
        )
    if cloud_retry:
        monkeypatch.setattr(
            service,
            "decide_provider",
            lambda *_a, **_k: SimpleNamespace(
                downgraded=False,
                sensitivity="P0",
                reason="fixture cloud route",
            ),
        )
        monkeypatch.setattr(
            service,
            "resolve_transport_execution_profile",
            lambda *, provider, **_kwargs: _governor_preset(
                input_tokens=12_000 if provider == "openai" else 6_000,
                preset_id="cloud-large" if provider == "openai" else "local-restrictive",
            ),
        )
    if selector_overflow:
        original_govern = service.govern_inference_messages

        def overflow_selector(**kwargs):
            if kwargs.get("shortlist"):
                raise ContextRequiredSectionOverflow(
                    object_ids=("profile:bound", "request:current"),
                    budget=10,
                    required_tokens=11,
                )
            return original_govern(**kwargs)

        monkeypatch.setattr(service, "govern_inference_messages", overflow_selector)

    def save_history(**row):
        history_rows.append(row)
        return "history-1"

    request = service.EvidenceRequestContext(
        req=SimpleNamespace(
            question=(
                "Найди текущие цены цемента и арматуры"
                if active_web_research
                else "Собери ЛСР; ВОР не создавай"
                if model_rag_result
                else "Проверь документы"
            ),
            mode="agent" if active_web_research else "estimator" if model_rag_result else "rag",
            response_length="short",
            output_directive="",
            session_id="session-1",
            dataset_filter=None,
                project_id=0,
                attachment_id="read_123456abcdef" if workbook_profile else None,
                attachment_context=(
                    "Строка 1: монтаж шкафа управления — 2 шт.\n"
                    + receipt_context([
                        {'source_row':'1','calculation_ref':'transport-receipt-fixture',
                         'calculation':{'resources':[{'code':'fixture-resource','quantity':6,'unit':'шт'}]}}
                    ])
                    if model_rag_result
                    else ""
                ),
            candidate_acceptance=candidate_acceptance,
            reranker_enabled=None,
        ),
        dataset_ids=None if scenario == "normal_unscoped" else ["selected"],
        effective_dataset_filter="",
        resolved_dataset_names=[],
        dataset_name_by_id={},
        query_route_payload={"channel": "rag"},
        target_doc_filter=[],
        target_file_ref=None,
        topic_doc_filter=[],
        topic_retrieval_plan=None,
        inventory_requested=False,
        study_requested=False,
        memory_block="",
        session_block="",
        class_suggestions=[],
        use_semantic_cache=False,
        use_validation=False,
        validation_skip_reason="test",
        route=SimpleNamespace(intent="rag"),
        table_result=None,
        request_started_at=1.0,
        profile_snapshot={
            "revision_id": "fixture-profile:1",
            "mode": "agent" if active_web_research else "estimator" if model_rag_result else "rag",
            "tools": (
                ["web_search", "web_read"]
                if active_web_research
                else ["search_sources", "build_lsr_workbook", "build_vor_workbook"]
                if model_rag_result
                else ["build_vor_workbook" if workbook_profile else "read_source"]
            ),
            "rag_policy": (
                {
                    "iterative": True,
                    "system_datasets": ["smeta"],
                    "model_authored_initial_query": True,
                }
                if model_rag_result
                else {"iterative": False}
            ),
            "prompt_text": "Answer only from evidence.",
        },
    )

    if p915_factory:
        from tests.test_chat_profile_service import _p915_factory_snapshot
        request.profile_snapshot.clear()
        request.profile_snapshot.update(_p915_factory_snapshot())

    if full_attachment:
        import openpyxl
        from proxy.services.chat_attachment_service import preserve_read_attachment
        from proxy.services.portion_cursor_service import PortionCursorService
        attachment_root = tmp_path/'read-attachments'
        monkeypatch.setenv('LES_CHAT_ATTACHMENT_ROOT', str(attachment_root))
        monkeypatch.setenv('LES_SMETA_PORTION_ROWS', '25')
        source = tmp_path/'full.xlsx'
        wb = openpyxl.Workbook()
        wb.active.title = 'S'
        wb.active.append(['№', 'Наименование', 'Ед. изм', 'Количество'])
        wb.active.append([1, 'монтаж шкафа управления ' + 'условия ' * 50 + 'FULL_TRAIT', 'шт.', 2])
        wb.active.append([2, 'LAST_SECTION_ITEM', 'м', 12.5])
        wb.save(source)
        wb.close()
        source_meta = preserve_read_attachment(source, attachment_id='read_123456abcdef', original_name='full.xlsx')
        request.req.attachment_id = source_meta['attachment_id']
        preview = 'Файл: full.xlsx\nS!R1: № | Наименование | Ед. изм | Количество\nS!R2: 1 | монтаж шкафа управления | шт. | 2'
        request.req.attachment_context = preview
        source_store = PortionCursorService(tmp_path/'full-source-portion.db')
        monkeypatch.setattr(service, 'portion_cursor_store', lambda: source_store)

    if portion_case:
        from proxy.services.portion_cursor_service import PortionCursorService

        portion_store = PortionCursorService(tmp_path / "portion-regression.db")
        monkeypatch.setattr(service, "portion_cursor_store", lambda: portion_store)
        request.req.turn_id = f"{scenario}-turn-1"
        request.req.attachment_context = (
            "Файл: fixture.xlsx\n"
            "S!R1: № | Наименование | Артикул | Ед. изм | Количество\n"
            "S!R2: 1 | монтаж шкафа управления | ART-KEEP | шт. | 2\n"
        )
        from dataclasses import replace

        reply = active_transport.responses[1]
        active_transport.responses[1] = replace(
            reply,
            text=("Ведомость уже разобрана, новых строк нет."
                  if portion_case.endswith("repackage") else reply.text.replace("ГЭСНм08-02-401-01", "—")
                  # Структурный отказ всей порции вызывает строка чужой позиции; ссылка на
                  # несуществующую карточку с 17.09 отказывает только своей строке.
                  if portion_case.endswith("pending") else reply.text.replace("| 1 | ЭОМ |", "| 7 | ЭОМ |")
                  if portion_case.endswith("invalid") else reply.text),
        )
        if portion_case.endswith("repackage"):
            # Ведомость уже закрыта прошлым проходом, а книги нет: упаковка тогда не
            # состоялась. Решения обязаны собраться в книгу без нового прохода модели.
            portion_store.record_pass(
                session_id="session-1",
                source_revision=service.smeta_portion_context(
                    request.req.attachment_context, session_id="session-1", limit=1, cursors=None,
                )[1]["source_revision"],
                completed={"S!1": {
                    "source_row": "1", "section": "ЭОМ", "title": "монтаж шкафа управления",
                    "unit": "шт.", "quantity": 2.0, "norm_code": "ГЭСНм08-02-401-01",
                }},
            )
        if portion_case.endswith("ambiguous"):
            request.req.attachment_context += (
                "T!R1: № | Наименование | Ед. изм | Количество\n"
                "T!R2: 1 | Another work | м | 12\n"
            )
            monkeypatch.setenv("LES_SMETA_PORTION_ROWS", "1")
        if portion_case.endswith(('operations_qualified', 'operations_numeric', 'unnamed_aliases', 'named_aliases')):
            label = '1' if portion_case.endswith('operations_numeric') else 'S!1'
            identifiers = ['mount', 'terminate']
            labels = [label, label]
            if portion_case.endswith('unnamed_aliases'):
                identifiers = ['', '']
            if portion_case.endswith('named_aliases'):
                labels = ['S!1', '1']
            operations_answer = '| source_row | work_id | title | unit | quantity | norm_code | evidence_refs |\n|---|---|---|---|---|---|---|\n'
            for number, (identity, source_label) in enumerate(zip(identifiers, labels), 1):
                operations_answer += f'| {source_label} | {identity} | operation {number} | шт. | {number * 2} | ГЭСНм08-02-401-01 | Q{number}.H1 |\n'
            active_transport.responses[1] = replace(reply, text=operations_answer)

    if model_rag_result and not full_attachment:
        # Existing transport scenarios use a textual attachment. Preserve those
        # exact fixture bytes; the XLSX source boundary has its own scenario above.
        from proxy.services.chat_attachment_service import preserve_read_attachment
        monkeypatch.setenv('LES_CHAT_ATTACHMENT_ROOT', str(tmp_path/'read-attachments'))
        text_source = tmp_path/'source.txt'
        text_source.write_text(request.req.attachment_context or 'fixture', encoding='utf-8')
        preserve_read_attachment(text_source, attachment_id='read_123456abcdef', original_name='source.txt')

    if smeta_budget:
        # Actual live failure: "сколько" inside "несколько" selected the value
        # form and cut a multi-row result at 256 tokens despite the 8192 reserve.
        request.req.question = "Составь смету. Несколько операций одной позиции требуют явных идентификаторов и количеств."
        request.req.response_length = None if smeta_budget == "default" else "short"

    if experiment:
        request.req.smeta_practice_mode = experiment
        practice_calls = []
        def frequency_group(**kwargs):
            practice_calls.append("frequency")
            if archive_header:
                card = {'norm_code': 'ГЭСНм08-02-401-01', 'norm_id': 'fixture-norm',
                        'title': 'Archive candidate', 'measure_unit': 'шт.', 'source_ref': 'fixture-source',
                        'usage_evidence': {'applications': 186, 'note': 'unmatched-source-proof ' * 10000}}
                return 'Archive candidates; applicability unconfirmed', (service._PracticeChunk(card),)
        def similar_group(**kwargs):
            practice_calls.append("similar")
        monkeypatch.setattr(service, "smeta_practice_group", frequency_group)
        monkeypatch.setattr(service, "smeta_material_group", similar_group)

    def retrieve_fixture(**kwargs):
        if not model_rag_result:
            return _async_value(FakeRetrieval())
        pytest.fail("estimator model-RAG must not call the general les_rag retriever")

    def retrieve_smeta_fixture(query, *, limit):
        assert limit == 6
        rag_queries.append(query)
        return {
            "backend": "typed_sqlite_fts+smeta_norm_qdrant_hybrid",
            "cards": [
                {
                    "norm_code": "ГЭСНм08-02-401-01",
                    "title": f"Карточка нормы для {query}",
                    **({"usage_evidence": {"note": "frequency-transport-proof"}} if experiment else {}),
                    "measure_unit": "шт.",
                    "work_steps": ["Монтаж оборудования"],
                    **({"resources": full_resources, "resources_complete": True,
                        "resource_count": len(full_resources),
                        "work_steps": ["FULL_OPERATION_PROOF"],
                        "norm_id": "full-norm-fixture", "edition": "2022"}
                       if model_full_read and query == full_read_code else {}),
                    **({'resource_preview': [{'kind': 'material', 'code': 'fixture-resource',
                         'name': 'Long resource description ' * 1000, 'unit': 'кг'}]}
                       if work_steps_delivery else {}),
                    "source_ref": f"fsnb#query={len(rag_queries)}",
                }
            ],
            "retrieval_trace": {
                "rag": {
                    "status": "ok",
                    "collection": "les_smeta_norm_cards",
                    "retrieval_channels": ["dense", "bm25_sparse"],
                    "fusion": "rrf",
                }
            },
        }

    monkeypatch.setattr(service, "retrieve_smeta_norm_cards", retrieve_smeta_fixture)

    runtime = service.EvidenceRuntimeDeps(
        state=state,
        rag_backend=SimpleNamespace(collection_name="fixture"),
        cache=SimpleNamespace(),
        cache_embedding=None,
        cache_marker="miss",
        cache_scope="",
        assistant_text=lambda message: str(message.get("content") or ""),
        augment_model_tool_args=lambda call, **_kwargs: call,
        chat_model_final_answer=lambda _answer, status: ("rewritten by code", status, {}),
        cloud_body_for_model=lambda body, *_args: body,
        compact_tool_result_for_prompt=lambda item, **_kwargs: item,
        dataset_ids_from_chunks=lambda _chunks: [],
        dataset_sensitivities=lambda _ids: [],
        env_bool=lambda _key, default=False: default,
        env_float=lambda _key, default=0.0: default,
        env_int=lambda _key, default=0: default,
        expand_context_windows=lambda chunks, *_args, **_kwargs: FakeWindows(chunks),
        format_tool_results_for_model=lambda rows: json.dumps(rows, ensure_ascii=False),
        generation_token_budget=lambda **_kwargs: 128,
        llm_runtime=lambda: runtime_config,
        local_context_budget=lambda **_kwargs: {
            "focus_max_chunks": 0,
            "context_max_chunks": 0,
            "context_chars_limit": 4000,
            "context_window_chars": 1000,
        },
        mlx_runtime=lambda: mlx_runtime_config if cloud_retry else runtime_config,
        names_for_dataset_ids=lambda *_args: [],
        notebook_study_validation_status=lambda status, **_kwargs: status,
        ollama_native_complete=lambda *_args, **_kwargs: None,
        parse_model_tool_calls=(
            lambda raw, *_args, **_kwargs: (
                    [{"tool": "build_vor_workbook", "args": {"attachment_id": "read_123456abcdef"}}]
                        if workbook_profile and not active
                        else json.loads(raw).get("calls", [])
                        if str(raw).lstrip().startswith("{")
                        else []
                )
            ),
        prepare_notebook_reader_memory=lambda *_args, **_kwargs: None,
        record_cloud_cost=lambda *_args, **_kwargs: None,
        retrieve_chat_chunks=retrieve_fixture,
        source_excerpts=lambda *_args, **_kwargs: [],
        table_query_response=lambda **_kwargs: None,
        cloud_fallback_models=lambda runtime: [runtime.model] if cloud_retry else [],
        cloud_model_timeout=lambda: 1.0,
        model_connection_resolver=(
            (lambda: (ActiveResolver(), object())) if active else None
        ),
        model_connection_transport=(
            (lambda _client, _secret_store: active_transport) if active else None
        ),
        workbook_tool_executor=(
            (lambda call, context, progress: _failing_workbook_execution(call, workbook_executor_calls))
            if portion_case.endswith("packaging_error")
            else (lambda call, context, progress: _rejected_workbook_execution(call, workbook_executor_calls))
            if rejected_workbook
            else (
                (
                    lambda call, context, progress: (
                        _rejected_workbook_execution(call, workbook_executor_calls)
                        if model_rag_recovery and call.get("tool") == "build_vor_workbook"
                        else _tracked_workbook_execution(
                            call, context, progress, progress_events, workbook_executor_calls
                        )
                    )
                )
                if active_workbook else None
            )
        ),
    )
    boundary = service.ResponseBoundary(
        save_chat_history=save_history,
        token_sink=(lambda event: _async_append(progress_events, event)) if active_workbook or output_boundary else None,
        version_stamp=lambda: {},
    )

    if portion_case.endswith(('packaging_cancel', 'delivery_cancel')):
        from dataclasses import replace
        original_executor = runtime.workbook_tool_executor

        async def cancel_packaging(call, context, progress):
            workbook_executor_calls.append(call)
            raise asyncio.CancelledError()

        async def cancel_delivery(event):
            if event.get('event') == 'reset':
                raise asyncio.CancelledError()

        interrupted_runtime = (replace(runtime, workbook_tool_executor=cancel_packaging)
            if portion_case.endswith('packaging_cancel') else runtime)
        interrupted_boundary = (replace(boundary, token_sink=cancel_delivery)
            if portion_case.endswith('delivery_cancel') else boundary)
        with pytest.raises(asyncio.CancelledError):
            await service.run_chat_evidence_application(request, interrupted_runtime, interrupted_boundary)
        calls_before = len(active_transport.requests)
        assert calls_before == 2
        restarted = PortionCursorService(tmp_path / 'portion-regression.db')
        _, saved = service.smeta_portion_context(request.req.attachment_context,
            session_id='session-1', limit=1, cursors=restarted)
        assert saved['prior_decisions']['S!1']['norm_code'] == 'ГЭСНм08-02-401-01'
        assert saved['prior_decisions']['S!1']['quantity'] == 2
        assert saved['prior_decisions']['S!1']['evidence_snapshot']
        progress = restarted.progress(session_id='session-1', source_revision=saved['source_revision'])
        assert progress.passes == 1 and not progress.artifact_revision_id
        basis = restarted.document_price_basis(session_id='session-1',
            source_revision=saved['source_revision'], capture=lambda: pytest.fail('basis lost'))
        assert basis
        monkeypatch.setattr(service, 'portion_cursor_store', lambda: restarted)
        recovered = await service.run_chat_evidence_application(request,
            replace(runtime, workbook_tool_executor=original_executor), boundary)
        assert len(active_transport.requests) == calls_before, 'Recovery must not ask the model to choose again'
        assert recovered['artifact']['revision_id']
        return

    if selector_overflow:
        with pytest.raises(service.HTTPException) as error:
            await service.run_chat_evidence_application(request, runtime, boundary)
        assert error.value.status_code == 422
        assert error.value.detail["code"] == "CONTEXT_REQUIRED_SECTION_OVERFLOW"
        assert model_calls == []
        assert history_rows == []
        assert protected_hash() == before_protected
        return

    if model_full_read_fail:
        monkeypatch.setattr(service, "mutable_path", lambda *parts: tmp_path.joinpath(*parts))
        with pytest.raises(Exception):
            await service.run_chat_evidence_application(request, runtime, boundary)
        receipts = list((tmp_path / "storage/model_read_receipts").glob("*.json"))
        assert len(receipts) == 1, "A successful read followed by transport failure must persist its full receipt"
        saved_bytes = receipts[0].read_bytes()
        saved = json.loads(saved_bytes.decode("utf-8"))
        assert saved["question"] == request.req.question
        assert saved["attachment_context"] == request.req.attachment_context
        assert saved["session_id"] == request.req.session_id
        assert "continuation transport failure fixture" in saved["error"]
        read_round = saved["trace"]["model_rag_reads"][0]
        assert read_round["text"] == ""
        assert read_round["calls"] == [{"id": "full-norm-read-1", "type": "function",
            "function": {"name": "search_sources", "arguments": json.dumps({"q": full_read_code}, ensure_ascii=False)}}]
        assert read_round["unexecuted_call_ids"] == []
        assert read_round["results"][0]["call_id"] == "full-norm-read-1"
        assert read_round["results"][0]["payload"]["status"] == "ok"
        assert "FULL_OPERATION_PROOF" in saved_bytes.decode("utf-8")
        for resource in full_resources:
            assert resource["name"] in saved_bytes.decode("utf-8")
            assert resource["code"] in saved_bytes.decode("utf-8")
            assert str(resource["per_unit"]) in saved_bytes.decode("utf-8")
        assert rag_queries == ["монтаж шкафа управления", "прокладка контрольного кабеля", full_read_code]
        assert len(active_transport.requests) == 3
        assert workbook_executor_calls == []
        assert history_rows == []
        assert not any(event.get("event") == "token" for event in progress_events)
        return

    result = await service.run_chat_evidence_application(request, runtime, boundary)

    if portion_case.endswith(('operations_qualified', 'operations_numeric', 'unnamed_aliases', 'named_aliases')):
        assert len(active_transport.requests) == 2
        query_messages = str(active_transport.requests[0].messages)
        final_messages = str(active_transport.requests[1].messages)
        assert 'decision_kind' not in query_messages and 'resource_review_status' not in query_messages
        assert 'Заголовки разделов используй как контекст' in query_messages
        assert 'Пустое количество само по себе не означает заголовок' in query_messages
        assert 'decision_kind' in final_messages and 'resource_review_status' in final_messages
        assert result['answer'].strip() == operations_answer.strip()
        if portion_case.endswith('named_aliases'):
            assert not workbook_executor_calls
            assert result['retrieval_trace']['model_result']['status'] == 'structural_error'
            errors = result['retrieval_trace']['model_result']['errors']
            expected = 'invalid_portion_source_row' if portion_case.endswith('unnamed_aliases') else 'inconsistent_portion_source_label'
            assert any(error.startswith(expected + ':') for error in errors)
            return
        assert len(workbook_executor_calls) == 1, result['retrieval_trace'].get('model_result')
        authored = workbook_executor_calls[0]['args']['decisions']
        assert [row['work_id'] for row in authored] == ['mount', 'terminate']
        assert [row['quantity'] for row in authored] == [2, 4]
        assert [row['evidence_refs'] for row in authored] == [['Q1.H1'], ['Q2.H1']]
        _, saved = service.smeta_portion_context(request.req.attachment_context, session_id='session-1', limit=1, cursors=portion_store)
        ops = saved['prior_decisions']['S!1']['operations']
        assert [op['work_id'] for op in ops] == ['mount', 'terminate']
        assert [[e['ref'] for e in op['evidence_snapshot']] for op in ops] == [['Q1.H1'], ['Q2.H1']]
        return

    if full_attachment:
        assert len(active_transport.requests) == 2
        for call in active_transport.requests:
            messages = str(call.messages)
            assert 'FULL_TRAIT' in messages, 'A cell cut in upload preview must reach actual model transport in full'
            assert 'LAST_SECTION_ITEM' in messages, 'Rows after the upload preview cap must be available to the portion'
        assert request.req.attachment_context == preview
        source_trace = result['retrieval_trace']['smeta_attachment_source']
        assert source_trace['sha256'] == source_meta['sha256']
        assert source_trace['source_rows'] == result['smeta_portion']['total'] == 2
        assert source_trace['preview_chars'] < source_trace['source_chars']
        return

    if portion_case.endswith("repackage"):
        # Ход заканчивается на пересборке: показывать нечего, значит и звать модель
        # незачем. Ревью Codex 11.09 замерило здесь два вызова транспорта — ранняя
        # ветка собирала книгу, а обработчик продолжал обычный маршрут.
        assert model_calls == [], "повтор упаковки обязан обойтись без модели"
        assert len(workbook_executor_calls) == 1, "книга обязана собраться из сохранённых решений"
        decisions = workbook_executor_calls[0]["args"]["decisions"]
        assert [row["source_row"] for row in decisions] == ["1"]
        assert decisions[0]["norm_code"] == "ГЭСНм08-02-401-01"
        assert result["artifact"]["revision_id"], "книга уходит в ответ"
        assert result["smeta_portion"]["decided"] == 1
        assert result["smeta_portion"]["unresolved"] == 0
        assert result["smeta_portion"]["remaining"] == 0
        assert result["history_id"] is not None, "ход обязан попасть в историю"
        assert "пересобрана" in result["answer"]

        _, after = service.smeta_portion_context(
            request.req.attachment_context, session_id="session-1", limit=1, cursors=portion_store,
        )
        assert after["state"] == "complete"
        assert after["artifact_revision_id"], "ревизия книги записана"
        # Production adds the independently persisted document basis after
        # portion planning; the freshness digest must use that same basis.
        after['document_price_basis'] = result['retrieval_trace']['document_price_basis']
        persisted = portion_store.document_price_basis(session_id='session-1',
            source_revision=after['source_revision'],
            capture=lambda: pytest.fail('A completed document must already have its basis'))
        assert after['document_price_basis'] == persisted
        assert service.stored_decisions_need_a_workbook(after) is False, (
            "только что собранная книга не должна числиться устаревшей"
        )
        return

    if portion_case:
        _, next_state = service.smeta_portion_context(
            request.req.attachment_context, session_id="session-1", limit=1, cursors=portion_store,
        )
        if portion_case.endswith("packaging_error"):
            # Решение модели и состояние упаковки разделены (ревью Codex 11.09): норма
            # выбрана — значит строка решена, даже если книга не собралась. Гонять модель
            # по уже разобранной строке из-за занятого диска не нужно; несобранная книга
            # видна по расхождению отпечатков и пересобирается детерминированно.
            from proxy.services.portion_cursor_service import decisions_revision

            assert workbook_executor_calls, "упаковка обязана была быть предпринята"
            assert next_state["prior_decisions"]["S!1"]["norm_code"] == "ГЭСНм08-02-401-01"
            progress = portion_store.progress(
                session_id="session-1", source_revision=next_state["source_revision"],
            )
            assert "S!1" in progress.completed, "норма выбрана — строка решена"
            assert progress.exhausted == frozenset()
            assert not progress.artifact_revision_id, "книги нет"
            assert progress.artifact_decisions_revision != decisions_revision(progress.decisions)
            assert service.stored_decisions_need_a_workbook(next_state) is True, (
                "книга обязана числиться устаревшей — её пересоберёт следующий запрос"
            )
            return
        assert next_state["shown"] == (["T!1"] if portion_case.endswith("ambiguous") else ["S!1"]), "Other source rows get a turn; rejected rows remain open"
        assert not portion_store.progress(session_id='session-1',source_revision=next_state['source_revision']).completed
        assert result["attachment_retry"]["preserved"] is True
        assert result["smeta_portion"]["remaining"] == (2 if portion_case.endswith("ambiguous") else 1)
        assert "ART-KEEP" in str(active_transport.requests[1].messages)
        if not portion_case.endswith("pending"):
            assert workbook_executor_calls == []
            assert next_state["prior_decisions"] == {}
        if portion_case.endswith("invalid"):
            from proxy.services.portion_feedback_service import PortionFeedbackService

            notice = result['model_result_notice']
            assert notice['status'] == 'structural_error'
            assert notice['saved'] is True
            assert 'Книга не собрана' in notice['message']
            stored = PortionFeedbackService(portion_store.db_path).last(
                session_id='session-1', source_revision=next_state['source_revision'],
            )
            assert stored['raw_answer'] == result['answer']
            assert stored['rows'][0]['source_row'] == 7
            assert stored['evidence'].get('portion_shown') == ['S!1'], 'A rejected final must preserve server-owned observed anchors for the next portion'
            assert service.stored_decisions_need_a_workbook(next_state) is False
            progress = portion_store.progress(session_id='session-1', source_revision=next_state['source_revision'])
            assert not progress.completed and not progress.exhausted and not progress.attempts
            request.req.turn_id = f"{scenario}-turn-2"
            active_transport.responses = [
                replace(reply, text='монтаж шкафа управления\nпрокладка контрольного кабеля'),
                reply,
            ]
            await service.run_chat_evidence_application(request, runtime, boundary)
            assert 'invalid_portion_source_row:7' in str(active_transport.requests[-1].messages)
        return

    after_protected = protected_hash()
    if output_boundary:
        visible = "".join(event["data"] for event in progress_events if event.get("event") == "token")
        assert "chat-checkpoint:" not in visible
        assert visible == result["answer"] == history_rows[0]["answer"]
        if scenario == "active_output_control":
            assert result["answer"] == "Чистый ответ [Источник 1]"
        else:
            assert result["answer"].startswith("Расход 12.5 м3/ч [Источник 1]")
            assert "усечён" in result["answer"]
        return
    if scenario == "repeat_failed":
        assert model_calls == ["selector", "selector", "final"]
        assert len(legacy_calls) == 2
        assert history_rows[0]["retrieval_trace"]["tool_loop"]["stop_reason"] == "repeated_failed_call"
        return
    if active_web_research:
        expected_answer = "Цемент — 650 руб.; арматура — 72 000 руб./т."
        assert result["answer"].encode("utf-8") == expected_answer.encode("utf-8")
        assert history_rows[0]["answer"].encode("utf-8") == expected_answer.encode("utf-8")
        assert [call[0] for call in legacy_calls] == ["web_search", "web_read"]
        assert legacy_calls[1][1] == {"url": "https://public.example/materials"}
        assert captured_web_configs[0].mode == "extended"
        tool_loop = history_rows[0]["retrieval_trace"]["tool_loop"]
        assert [call["tool"] for call in tool_loop["selected_calls"]] == [
            "web_search",
            "web_read",
        ]
        assert tool_loop["web_research"]["mode"] == "extended"
        assert result["source_map"][0]["locator"]["url"] == (
            "https://public.example/materials"
        )
        assert result["source_map"][0]["snippet"].startswith("Цемент — 650")
        assert len(active_transport.requests) == 4
        assert "Цемент — 650" in str(active_transport.requests[3].messages)
        return
    if model_rag_result:
        if p915_factory:
            query_messages = str(active_transport.requests[0].messages)
            assert 'read_source' in query_messages, 'Query-stage bound skill remains unchanged'
            for answer_request in active_transport.requests[1:]:
                text = '\n'.join(m['content'] for m in answer_request.messages)
                assert 'read_source' not in text and 'skills/smeta/SKILL.md' not in text
                assert '[Источник N]' not in text and 'Qn.Hm' in text
                assert answer_request.tools == tuple(service.model_rag_search_tool_schema())
            adaptation = result['retrieval_trace']['answer_contract_availability']
            assert adaptation['factory_verified'] is True
            assert adaptation['unavailable_references'] == []
            assert adaptation['original_prompt_sha256'] == request.profile_snapshot['prompt_sha256']
        if model_full_read:
            assert active_transport.requests[0].request_audit is None, "Query authoring is outside body audit"
            assert active_transport.requests[1].request_audit.purpose == "answer"
            assert active_transport.requests[2].request_audit.purpose == "answer_read"
            assert active_transport.requests[1].request_audit.refs is result["retrieval_trace"]["model_request_audit"]
            assert any(source.get("evidence_ref") == "Q3.H1" for source in result["source_map"])
            assert "Q3.H1" in json.dumps(result["evidence_packet"], ensure_ascii=False)
            assert result["retrieval_trace"]["model_rag_read_complete"] is True
            read_round = result["retrieval_trace"]["model_rag_reads"][0]
            assert read_round["unexecuted_call_ids"] == []
            assert read_round["results"][0]["payload"]["status"] == "ok"
            assert read_round["continuation_response"]["tool_calls"] == []
            assert rag_queries == [
                "монтаж шкафа управления", "прокладка контрольного кабеля", full_read_code,
            ], "The answer-stage native call must execute its exact norm query"
            assert research_executions[-1] == (
                {"tool": "search_sources", "args": {"q": full_read_code}}, ("selected",),
            ), "Addressed reading must retain the frozen dataset scope"
            assert active_transport.revisions == ["conn:active:r3"] * 3
            assert len(active_transport.requests) == 3
            assert result["answer"].startswith("active visible answer\n\n| source_row |")
            assert '"calls"' not in result["answer"]
            assert history_rows[0]["answer"] == result["answer"]
            final_messages = str(active_transport.requests[-1].messages)
            for model_request in active_transport.requests[1:]:
                messages = str(model_request.messages)
                assert request.req.question in messages
                assert "Строка 1: монтаж шкафа управления — 2 шт." in messages
                for index, query in enumerate(rag_queries[:2], 1):
                    assert query in messages
                    assert f"Карточка нормы для {query}" in messages
                    assert f"Q{index}.H1" in messages
            assert "FULL_OPERATION_PROOF" in final_messages
            for resource in full_resources:
                assert resource["name"] in final_messages
                assert resource["code"] in final_messages
                assert str(resource["per_unit"]) in final_messages
            assert workbook_executor_calls[-1]["tool"] == "build_lsr_workbook"
            assert workbook_executor_calls[-1]["args"]["decisions"][0]["norm_code"] == full_read_code
            tool_loop = history_rows[0]["retrieval_trace"]["tool_loop"]
            assert tool_loop["model_queries"] == rag_queries[:2]
            assert tool_loop["evidence_groups"] == ["Q1", "Q2"]
            return
        assert all(query != full_read_code for query in rag_queries), "No automatic norm reads"
        assert result["answer"].startswith("active visible answer\n\n| source_row |")
        assert rag_queries == [
            "монтаж шкафа управления",
            "прокладка контрольного кабеля",
        ]
        assert "Собери ЛСР" not in rag_queries
        calculated_decisions = workbook_executor_calls[-1]["args"]["decisions"]
        provenance_fields = {"normative_identity", "normative_identity_status",
                             "normative_identity_refs", "evidence_snapshot"}
        assert [{k: v for k, v in row.items() if k not in provenance_fields}
                for row in calculated_decisions] == exact_decisions
        # These older fixture cards have no database revision. Preserve every
        # authored field while explicitly refusing to manufacture a source SHA.
        for row, original in zip(calculated_decisions, exact_decisions, strict=True):
            assert row["normative_identity"] is None
            assert row["normative_identity_status"] == "unpinned"
            assert row["normative_identity_refs"] == original["evidence_refs"]
            assert all(card["delivered"] is True and card["sent_sha256"]
                       for card in row["evidence_snapshot"])
        assert workbook_executor_calls[-1]["tool"] == "build_lsr_workbook"
        assert workbook_executor_calls[-1]['args']['review_calculation'] is True
        assert active_transport.revisions == ["conn:active:r3"] * 2
        assert active_transport.requests[0].tools == ()
        assert active_transport.requests[1].tools == tuple(service.model_rag_search_tool_schema())
        assert "Строка 1: монтаж шкафа управления — 2 шт." in str(
            active_transport.requests[0].messages
        )
        final_messages = str(active_transport.requests[1].messages)
        if smeta_budget:
            assert active_transport.requests[1].max_output_tokens == (8192 if smeta_budget == "default" else 1024)
            assert "Форма ответа: ОДНА строка" not in final_messages
            assert ("Пользователь выбрал короткий ответ" in final_messages) == (smeta_budget == "short")
        if work_steps_delivery:
            assert 'Состав работы: Монтаж оборудования' in final_messages
        if archive_header:
            assert 'Archive candidate' in final_messages
            assert 'score=186.0000' not in final_messages
            assert 'архивный контекст не показан' in final_messages
            assert 'unmatched-source-proof' not in final_messages
            assert len(active_transport.requests) == 2
            assert history_rows[0]['retrieval_trace']['tool_loop']['model_queries'] == rag_queries
            assert all(query in final_messages for query in rag_queries)
            return
        assert 'transport-receipt-fixture' in final_messages
        if experiment:
            assert ("frequency-transport-proof" in final_messages) == (experiment in {"frequency", "both"})
            assert practice_calls == (["frequency"] if experiment == "frequency" else
                                      ["similar"] if experiment == "similar" else
                                      ["frequency", "similar"] if experiment == "both" else [])
            assert history_rows[0]["retrieval_trace"]["smeta_practice_experiment"]["mode"] == experiment
        assert 'fixture-resource' in final_messages
        assert 'resource_review_status=keep_all_confirmed' in final_messages
        # Проход 4 на 0.30.142: модель копировала в ссылку само слово из инструкции.
        assert 'в resource_review_ref — значение calculation_ref' in final_messages
        assert "К базовой шапке добавь отдельные колонки" in final_messages
        assert "conversion_factor, conversion_unit, conversion_source" in final_messages
        assert "resource_quantity, resource_unit" in final_messages
        assert "work_id и operation" in final_messages
        assert "полный набор её операций" in final_messages
        assert "not_covered" in final_messages
        assert "coefficient_basis" in final_messages
        assert "coefficient_target" in final_messages
        assert "ровно эта шапка" not in final_messages
        assert "Строка 1: монтаж шкафа управления — 2 шт." in final_messages
        assert "Карточка нормы для монтаж шкафа управления" in final_messages
        assert "Карточка нормы для прокладка контрольного кабеля" in final_messages
        assert "[Поисковый запрос Q1] монтаж шкафа управления" in final_messages
        assert "Q1.H1" in final_messages
        assert "[Поисковый запрос Q2] прокладка контрольного кабеля" in final_messages
        assert "Q2.H1" in final_messages
        first_messages = str(active_transport.requests[0].messages)
        assert "Строка 1: монтаж шкафа управления — 2 шт." in first_messages
        assert '"queries"' not in first_messages
        assert "верни только сами поисковые запросы" in first_messages
        query_budget = history_rows[0]['retrieval_trace']['tool_loop']['model_queries_budget']
        assert f"до {query_budget} первых запросов" in first_messages
        assert "фиксированного лимита нет" not in first_messages
        assert "для работ и материалов" in first_messages
        assert "Сначала охвати содержательные позиции работ и материалов порции" in first_messages
        assert "по всем фактическим строкам" not in first_messages
        assert "сохраняй язык и профессиональную терминологию исходных строк" in first_messages
        assert "не переводи и не транслитерируй" in first_messages
        assert "Код не подтверждает и не меняет твой выбор" in final_messages
        assert history_rows[0]["retrieval_trace"]["status"] == "model_driven"
        assert history_rows[0]["retrieval_trace"]["reason"] == (
            "awaiting_model_authored_query"
        )
        tool_loop = history_rows[0]["retrieval_trace"]["tool_loop"]
        assert tool_loop["schema"] == "les_model_rag_batch_v1"
        assert tool_loop["model_queries"] == rag_queries
        expected_raw = ("Запрос 1: монтаж шкафа управления\nЗапрос 2: прокладка контрольного кабеля\nЗапрос 3: монтаж шкафа управления"
                        if labelled_queries else "монтаж шкафа управления\nпрокладка контрольного кабеля")
        assert tool_loop["model_queries_raw"] == expected_raw
        assert tool_loop["evidence_groups"] == ["Q1", "Q2"]
        assert history_rows[0]["sources"] == ["smeta_norm_cards.v1"]
        manifest = history_rows[0]["retrieval_trace"]["evidence_manifest"]
        assert manifest["schema"] == "les.chat-evidence-manifest.v1"
        assert [item["id"] for item in manifest["model_visible"]] == ["Q1.H1", "Q2.H1"]
        assert manifest["cited_ids"] == ["Q1.H1"]
        assert history_rows[0]["retrieval_trace"]["source_map"] == result["source_map"]
        assert "rounds" not in tool_loop
        # Review field names are now legitimate model input (T119.6); the
        # invariant is no hidden reviewer/generation call, measured at transport.
        assert len(active_transport.requests) == 2
        assert 'review' not in tool_loop and 'confirm' not in tool_loop
        return
    if inactive_workbook:
        assert result["answer"] == "legacy visible answer"
        assert shortlist_policies == []
        assert shadow_calls == []
        assert legacy_calls == []
        assert executor_codes == []
        assert after_protected == before_protected
        return
    if active:
        assert result["answer"] == "active visible answer"
        assert result["model_connection"] == {
            "connection_id": "conn:active",
            "revision_id": "conn:active:r3",
            "display_name": "Active fixture",
            "model_id": "active-model",
                "locality": "loopback",
                "fallback_used": False,
                "pending_tool_calls": 0,
        }
        assert result["source_scope"] == {
            "requested": ["selected"],
            "resolved": ["selected"],
            "used": [],
            "used_names": [],
        }
        assert active_transport.revisions == ["conn:active:r3", "conn:active:r3"] + (
            ["conn:active:r3"]
            if rejected_workbook or not active_workbook
            else []
        )
        if active_workbook:
            assert len(workbook_executor_calls) == (2 if rejected_workbook else 1)
            if rejected_workbook:
                assert "artifact" not in result
                assert history_rows[0]["retrieval_trace"]["tool_loop"]["stop_reason"] == "model_stop"
                return
            assert result["artifact"]["revision_id"] == "rev-2"
            assert result["attachment_retry"]["attachment_id"] == "read_123456abcdef"
            assert history_rows[0]["artifact"]["revision_id"] == "rev-2"
            if scenario == "active_workbook_private_arg":
                selected_calls = result["retrieval_trace"]["tool_loop"]["selected_calls"]
                assert selected_calls == history_rows[0]["retrieval_trace"]["tool_loop"]["selected_calls"]
                assert selected_calls[0]["tool"] == "build_vor_workbook"
                assert selected_calls[0]["call_id"] == "workbook-call-1"
                assert len(selected_calls[0]["arguments_sha256"]) == 64
                assert "args" not in selected_calls[0]
                assert "SECRET_TRACE_TOKEN" not in json.dumps(result, ensure_ascii=False)
                assert "C:/private/les" not in json.dumps(history_rows[0], ensure_ascii=False)
            assert any(event.get("event") == "tool_progress" for event in progress_events)
            assert legacy_calls == []
            if candidate_acceptance:
                trace = history_rows[0]["retrieval_trace"]
                assert trace["canonical_route"]["effective"] == "shadow"
                assert trace["candidate_acceptance"] == {
                    "enabled": True,
                    "execution_mode": "active",
                    "promotion_receipt": "not_used",
                    "state_root": "process_cwd_isolated",
                }
                assert trace["route_comparison"]["candidate_acceptance"] is True
                assert trace["route_comparison"]["legacy_output_authoritative"] is False
        else:
            assert [call[1]["doc_id"] for call in legacy_calls] == ["d1", "d2"]
        assert history_rows[0]["retrieval_trace"]["context_governor"]["preset_id"] == "active-preset"
        assert after_protected == before_protected
        return
    assert result["answer"] == "legacy visible answer"
    if cloud_retry:
        assert model_calls == [
            "selector",
            "selector",
            "cloud_final",
            "local_final",
            "local_final",
        ]
        calls = history_rows[0]["retrieval_trace"]["context_governor"]["calls"]
        assert [call["purpose"] for call in calls] == [
            "tool_decision",
            "tool_decision",
            "answer",
            "answer_fallback",
            "answer",
        ]
        assert [call["preset_id"] for call in calls] == [
            "cloud-large",
            "cloud-large",
            "cloud-large",
            "local-restrictive",
            "local-restrictive",
        ]
        assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["persisted_effects"] == 0
        assert after_protected == before_protected
        return
    if scenario == "normal_unscoped":
        assert model_calls == ["final"]
        assert shortlist_policies == []
        assert shadow_calls == []
        assert executor_codes == []
        assert legacy_calls == []
        assert history_rows[0]["retrieval_trace"]["status"] == "skipped"
        assert history_rows[0]["retrieval_trace"]["reason"] == "scope_none"
        assert after_protected == before_protected
        return
    assert model_calls == ["selector", "selector", "final"]
    assert shortlist_policies == [
        {
            "mode": "rag",
            "allowed_tools": ["read_source"],
            "limit": 5,
            "dataset_ids": () if scenario == "normal_unscoped" else ("selected",),
            "workflow_phase": "research",
            "model_preset": "qwen-9b-restrictive",
            "runtime_available": frozenset({"read_source"}),
            "calls_remaining": 5,
            "result_chars_remaining": 35_000,
        }
    ]
    assert [call[1]["doc_id"] for call in shadow_calls] == ["d1"]
    assert executor_codes == [
        "TOOL_SCOPE_VIOLATION" if scenario == "normal_unscoped" else "TOOL_WOULD_EXECUTE"
    ]
    assert [call[1]["doc_id"] for call in legacy_calls] == ["d1", "d2"]
    assert len(history_rows) == 1
    assert history_rows[0]["answer"] == "legacy visible answer"
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["status"] == "error"
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["attempted_calls"] == 1
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["pending_calls"] == 1
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["persisted_effects"] == 0
    assert history_rows[0]["retrieval_trace"]["canonical_shadow"]["profile_revision"] == "fixture-profile:1"
    assert history_rows[0]["retrieval_trace"]["route_comparison"] == {
        "schema": "les.canonical-route-comparison.v1",
        "requested": "shadow",
        "effective": "shadow",
        "legacy_output_authoritative": True,
        "same_request": True,
        "profile_revision": "fixture-profile:1",
        "canonical_provider_calls_added": 0,
        "persisted_effects": 0,
    }
    governor_trace = history_rows[0]["retrieval_trace"]["context_governor"]
    assert governor_trace["preset_id"] == "qwen-9b-restrictive"
    assert [call["purpose"] for call in governor_trace["calls"]] == [
        "tool_decision",
        "tool_decision",
        "answer",
    ]
    assert "Проверь документы" not in json.dumps(governor_trace, ensure_ascii=False)
    assert "legacy fixture" not in json.dumps(governor_trace, ensure_ascii=False)
    assert "secret shadow failure" not in str(history_rows[0])
    assert after_protected == before_protected


def test_workbook_projection_keeps_bounded_conflict_diagnostics():
    raw = {
        "schema": "les.workbook_tool_result.v1",
        "tool": "build_lsr_workbook",
        "status": "complete",
        "missing": ["row:2:unit_conflict"],
        "blockers": [],
        "artifact": {"revision_id": "rev-2"},
    }

    safe = service.safe_workbook_history_projection(raw)

    assert safe["status"] == "partial"
    assert safe["missing"] == ["row:2:unit_conflict"]
    assert safe["blockers"] == []


async def _async_value(value):
    return value


def test_answer_contract_names_a_header_the_parser_accepts() -> None:
    """Промпт и разборщик обязаны сходиться на одном формате таблицы.

    Живой прогон 10.09, 21:24: контракт просил «обычным текстом» и перечислял поля,
    а разборщик принимает только Markdown-таблицу с шапкой и вертикальными чертами по
    краям. Модель повторила вид показанной ей порции — «984 | … | Q10.H2» — и ответ
    был законно отброшен как неструктурированный: ни строк, ни книги, ни прогресса.

    Проверяется не текст промпта, а его следствие: шапку, названную в контракте,
    разборщик должен принять.
    """
    source = service.model_answer_request('Fixture question', model_driven=True)
    marker = "| source_row |"
    assert marker in source, "контракт обязан называть шапку таблицы буквально"
    raw = source[source.index(marker):]
    raw = raw[: raw.index("evidence_refs |") + len("evidence_refs |")]
    header_line = " ".join(
        raw.replace(chr(34), "").replace(chr(92) + "n", " ").split()
    )
    assert header_line.startswith("|") and header_line.endswith("|")

    columns = [cell.strip() for cell in header_line.strip("|").split("|")]
    assert "norm_code" in columns and "evidence_refs" in columns
    separator = source.split("второй строкой — разделитель ", 1)[1].split(",", 1)[0]
    assert len(separator.strip("|").split("|")) == len(columns)
    table = chr(10).join([
        header_line,
        separator,
        # С 0.30.133 work_id входит в базовую шапку; с 0.30.152 она сузилась до семи
        # обязательных колонок (проходы 18–19, 18.09).
        "| 984 | install | Шкаф напольный | шт. | 2 | ГЭСНм10-01-055-01 | Q1.H1 |",
    ])
    parsed = service.parse_model_rag_result(table)
    assert parsed is not None, "разборщик не принимает шапку, которую требует контракт"
    _answer, rows = parsed
    assert len(rows) == 1
    assert rows[0]["source_row"] == 984
    assert rows[0]["work_id"] == "install"
    assert rows[0]["norm_code"] == "ГЭСНм10-01-055-01"
    assert rows[0]["evidence_refs"] == ["Q1.H1"]


def test_a_row_left_without_a_norm_needs_no_evidence_ref() -> None:
    """Пустой norm_code — предусмотренный ответ, ссылаться в нём не на что.

    Живой прогон 10.09, 22:31: модель вернула 25 строк, по девятнадцати подобрала
    нормы, а шесть честно оставила пустыми — именно так, как просит инструкция «если
    подходящих карточек в пакете нет, оставь norm_code пустым». Проверка потребовала
    evidence_refs и от них тоже, ошибка оказалась блокирующей, и весь проход был
    отброшен: ни книги, ни записанного прогресса.

    Ссылка обязательна ровно там, где норма выбрана.
    """
    class _Chunk:
        def __init__(self, ref: str, code: str) -> None:
            self.meta = {"model_evidence_ref": ref, "norm_code": code}

    chunks = [_Chunk("Q5.H5", "ГЭСНм10-06-037-01")]
    rows = [
        {"source_row": 984, "title": "Шкаф", "unit": "шт.",
         "norm_code": "ГЭСНм10-06-037-01", "evidence_refs": ["Q5.H5"]},
        {"source_row": 987, "title": "Блок розеток", "unit": "шт.",
         "norm_code": "", "evidence_refs": []},
        {"source_row": 991, "title": "Патч-корд", "unit": "шт.",
         "norm_code": "—", "evidence_refs": []},
    ]
    errors = service.validate_model_rag_result_structure(
        rows, chunks, expected_source_rows=3
    )
    assert errors == [], f"строки без нормы не должны блокировать проход: {errors}"

    with_norm_without_ref = [
        {"source_row": 988, "title": "Патч-панель", "unit": "шт.",
         "norm_code": "ГЭСНм10-01-001-01", "evidence_refs": []},
    ]
    errors = service.validate_model_rag_result_structure(
        with_norm_without_ref, chunks, expected_source_rows=1
    )
    assert "missing_evidence_ref:988" in errors, "выбранная норма обязана на что-то опираться"


def test_no_http_client_in_the_chat_path_trusts_the_system_proxy() -> None:
    """Клиенты сметного пути обязаны игнорировать системный прокси.

    Живой прогон 11.09, 10:34: оператор включил VPN, и запрос упал ещё до модели —
    `ValueError: Unknown scheme for proxy URL socks4://127.0.0.1:10808`. Системный
    SOCKS перехватывает и localhost, а весь сметный путь идёт по петле: внешнему
    прокси в нём делать нечего. Тот же дефект уже чинили по всему проекту 07.06,
    и один клиент остался незакрытым.
    """
    import re
    from pathlib import Path

    source = Path(service.__file__).read_text(encoding="utf-8")
    clients = [
        line.strip()
        for line in source.splitlines()
        if re.search(r"httpx\.(Async)?Client\(", line)
    ]
    assert clients, "клиенты в модуле должны быть — иначе тест бессмысленен"
    unguarded = [line for line in clients if "trust_env=False" not in line]
    assert unguarded == [], (
        "эти клиенты доверяют системному прокси и упадут при включённом VPN: "
        + "; ".join(unguarded)
    )


def test_contract_lists_the_coefficient_columns_it_asks_for() -> None:
    """Перечень колонок обязан содержать те, о которых контракт же и просит.

    Проход 25 (18.09): по строке демонтажа модель написала, что нормы на демонтаж нет,
    а ГЭСНм10-04-101-07 — про монтаж. Демонтаж по монтажной норме считают коэффициентом,
    расчёт его принимает (coefficient_basis/coefficient_target), и контракт про него
    говорит — но в перечне добавляемых колонок этих полей не было, а всё, чего нет в
    перечне, запрещено. Применять коэффициент или нет, решает модель.
    """
    source = service.model_answer_request('Fixture question', model_driven=True)
    listed = source.split("полей строго в этом порядке: ", 1)[1].split(". Колонку", 1)[0]
    columns = [item.strip() for item in listed.replace(chr(34), "").replace(chr(92) + "n", " ").split(",")]
    for name in ("coefficient", "coefficient_basis", "coefficient_target"):
        assert name in columns, name


def test_a_norm_proved_by_saved_delivered_evidence_needs_no_fresh_reference() -> None:
    """Номера карточек живут один проход, а решение — до конца ведомости.

    Проход 26 (18.09): строка демонтажа была подтверждена в 24-м проходе по
    ГЭСНм10-04-101-07, а в 26-м та же норма отвергнута как
    norm_code_not_in_referenced_evidence — модель сослалась на Q3.H1, потому что в
    прошлый раз эта карточка была Q6.H1. Ссылка проверяется в тот проход, когда
    решение принимается; сохранённый чек и есть след той проверки.
    """
    row = {'source_row': 'СОУЭ!7.2', 'norm_code': 'ГЭСНм10-04-101-07', 'evidence_refs': []}

    without = service.withhold_unreferenced_norms([row], delivered_cards={})[0]
    assert without['evidence_error'] == 'missing_evidence_ref'

    proof = service.saved_norm_evidence({'СОУЭ!7.2': {**row, 'evidence_snapshot': [
        {'norm_code': row['norm_code'], 'delivered': True, 'sent_text': 'card', 'sent_sha256': 'hash'}]}})
    with_receipt = service.withhold_unreferenced_norms(
        [row], delivered_cards={}, prior_evidence=proof,
    )[0]
    assert 'evidence_error' not in with_receipt

    # Чужая строка своей нормы не подтверждает.
    other = service.withhold_unreferenced_norms(
        [{**row, 'source_row': 'АР!1.31'}], delivered_cards={}, prior_evidence=proof,
    )[0]
    assert other['evidence_error'] == 'missing_evidence_ref'


def test_receipt_without_delivery_evidence_does_not_prove_a_norm(tmp_path) -> None:
    """Сам факт расчёта не подтверждает источник; старые advisory-решения тоже имели чеки."""
    receipts = [{'source_row': 'СОУЭ!7.2', 'work_id': 'w1', 'calculation': {'norm_code': 'ГЭСНм10-04-101-07'}},
                {'source_row': 'СОУЭ!7.2', 'work_id': 'w2', 'calculation': {'norm_code': ''}}]

    assert service.saved_norm_evidence({'СОУЭ!7.2': {'source_row': 'СОУЭ!7.2',
        'norm_code': receipts[0]['calculation']['norm_code'], 'calculation_receipts': receipts}}) == []
    assert service.saved_norm_evidence({}) == []


def test_rows_are_checked_against_the_sheet_after_it_is_finished_too() -> None:
    """Проход 32: ведомость пройдена, и модель сочинила три позиции.

    На завершённой ведомости строки ответа не проверялись на принадлежность ей, и
    выдуманные «1/1.1», «2/2.1», «3/3.1» с ссылками вида calc_10_04_101_01 попали в
    книгу — лист «Проверка» получил их со статусом evidence_ref_unknown, а реестр
    источников — предупреждения source_binding_unresolved.
    """
    assert service.model_rows_must_belong_to_sheet({'state': 'portion'})
    assert service.model_rows_must_belong_to_sheet({'state': 'complete'})
    # Вложение, которое ведомостью не является, этой проверке не подлежит.
    assert not service.model_rows_must_belong_to_sheet({'state': 'raw'})
    assert not service.model_rows_must_belong_to_sheet({})

    errors = service.portion_structure_errors(
        [{'source_row': '1', 'work_id': '1.1', 'norm_code': 'ГЭСНм10-04-101-01'}],
        {'state': 'complete', 'source_anchors': ['АР!1.31'], 'shown': []},
    )
    assert errors == ['invalid_portion_source_row:1']
