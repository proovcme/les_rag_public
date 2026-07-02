from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_rag_search_skill_keeps_search_model_first():
    text = (REPO_ROOT / "skills" / "rag_search" / "SKILL.md").read_text(encoding="utf-8")

    assert "Модель работает исследователем" in text
    assert "Код работает как поисковый и проверочный слой" in text
    assert "Missing evidence не является отрицательным фактом" in text
    assert "Если пользователь указал конкретный файл, ответ строится строго по нему" in text
    assert "детерминированный табличный путь" in text
    assert "Не отвечать из памяти" in text
    assert "Не считать таблицы вручную" in text


def test_normcontrol_skill_keeps_review_model_first():
    text = (REPO_ROOT / "skills" / "normcontrol" / "SKILL.md").read_text(encoding="utf-8")

    assert "Модель работает инженером нормоконтроля" in text
    assert "Код работает как проверочный и трассировочный слой" in text
    assert "Missing evidence не является pass и не является fail" in text
    assert "Каждое замечание должно иметь" in text
    assert "Разделять computed и RAG-led проверки" in text
    assert "Не выдумывать пункт нормы" in text
    assert "Не выдавать финальное заключение по всему комплекту" in text
