"""W3.1/W3.4: общий rules-валидатор и каскад rules→LLM (без LLM)."""

from backend.inference import rules_pre_verdict, rules_validate
from backend.inference.providers import ChatProvider, EmbedProvider, ValidatorProvider


def test_empty_context_is_no_data():
    v = rules_validate("вопрос", "ответ", "")
    assert v["status"] == "NO_DATA" and v["raw"] == "empty_context"


def test_answer_in_context_verified():
    v = rules_validate("q", "ширина 0.8 м", "минимальная ширина 0.8 м по СП")
    assert v["status"] == "VERIFIED"


def test_numeric_violation_is_hallucination():
    # ответ заявляет 1200 мм, контекст знает только 800 мм
    v = rules_validate("q", "ширина 1200 мм обязательна", "ширина прохода 800 мм минимум")
    assert v["status"] == "HALLUCINATION"
    assert v["raw"] == "answer_numeric_claim_not_in_context"


def test_lexical_overlap_verified():
    v = rules_validate(
        "q",
        "эвакуационный выход коридор лестница",
        "эвакуационный выход через коридор и лестничную клетку наружу",
    )
    assert v["status"] == "VERIFIED"


# ── каскад rules→LLM (W3.4): pre-verdict отсекает только уверенные случаи ──

def test_pre_verdict_short_circuits_empty_and_numeric():
    assert rules_pre_verdict("q", "любой ответ", "") == "NO_DATA"
    assert rules_pre_verdict("q", "значение 9999 кг", "масса 50 кг") == "HALLUCINATION"


def test_pre_verdict_defers_positive_to_llm():
    # лексическое перекрытие НЕ должно давать VERIFIED в каскаде — это работа LLM
    assert rules_pre_verdict(
        "q",
        "эвакуационный выход коридор лестница",
        "эвакуационный выход через коридор и лестничную клетку",
    ) is None


def test_protocols_are_runtime_checkable():
    # структурный протокол: класс с нужными атрибутами проходит isinstance
    class _Stub:
        provider = "mlx"; base_url = "x"; chat_url = "x"; model = "m"; api_key = ""; supports_validation = True
    assert isinstance(_Stub(), ChatProvider)
    assert issubclass(EmbedProvider, object) and issubclass(ValidatorProvider, object)
