"""SafeRAG result policy."""

SAFE_FALLBACK = (
    "Система безопасности (Т.О.С.К.А.) не смогла подтвердить ответ из базы знаний. "
    "Попробуйте переформулировать вопрос или выбрать другой датасет."
)


def final_answer_for_status(answer: str, status: str) -> tuple[str, str]:
    if status in ("VERIFIED", "NO_DATA"):
        return answer, status
    if status in ("HALLUCINATION", "UNKNOWN"):
        return SAFE_FALLBACK, status
    return SAFE_FALLBACK, "UNKNOWN"

