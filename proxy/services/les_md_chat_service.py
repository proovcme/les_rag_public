"""les_md_chat_service.py — чат-канал LES.md: «пойми папку» / «сделай LES.md».

Совушка сама понимает папку, когда просят: «пойми/разбери папку «<путь>»», «прочитай LES.md из
«<путь>»», «сделай/собери LES.md для «<путь>»». 0 LLM на разбор (regex). Привязка к проекту +
контекст — `les_md_service`.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from proxy.services.asbuilt_chat_service import extract_path
from proxy.services.les_md_service import read_and_bind

logger = logging.getLogger(__name__)

_DRAFT = ("сдела", "собери", "создай", "сгенери", "черновик", "набросай")
_READ = ("пойми", "разбери", "прочита", "понять", "изучи папк", "les.md", "лес.md", "контекст папк")


def is_les_md_query(question: str) -> bool:
    q = " " + (question or "").lower().replace("ё", "е") + " "
    if "les.md" in q or "лес.md" in q.replace("ё", "е"):
        return True
    has_folder = "папк" in q
    return has_folder and any(w in q for w in (_READ + _DRAFT))


def maybe_handle_les_md_query(question: str, *, project_id: int = 0) -> Optional[dict[str, Any]]:
    if not is_les_md_query(question):
        return None
    raw = extract_path(question)
    if not raw:
        return {"answer": "Укажи папку в кавычках: «пойми папку «/путь/к/папке»» "
                          "(или «сделай LES.md для «…»»).", "operation": "les_md_need_path"}
    path = Path(raw).expanduser()
    if not path.exists():
        return {"answer": f"Путь не найден: {raw}", "operation": "les_md_no_path"}

    q = question.lower().replace("ё", "е")
    # auto-init: нет LES.md → ЛЕС сам его собирает (не руками). «внимательно/подробно» → LLM-обогащение.
    enrich = any(w in q for w in ("внимательн", "подробн", "глубже", "прочита", "разберись хорош"))
    res = read_and_bind(path, write_draft=True, enrich=enrich)

    meta = res.get("meta") or {}
    head = "Сам собрал LES.md" if res.get("drafted") else "Прочитал LES.md"
    bound = (f"привязал к проекту «{res['project']}» (#{res['project_id']})"
             if res.get("project_id") else "режим global (без привязки к объекту)")
    bits = [f"{head} в «{path.name}», {bound}."]
    facts = [f"{k}: {meta[k]}" for k in ("object", "stage", "cipher", "address") if meta.get(k)]
    if facts:
        bits.append("· " + " · ".join(str(f) for f in facts))
    if res.get("pipelines"):
        bits.append("директивы: " + ", ".join(f"{k}→{v}" for k, v in dict(res["pipelines"]).items()))
    if res.get("drafted"):
        bits.append(f"Файл лежит в {res['path']} — руками ничего не надо, при желании поправь.")
        if not meta.get("address"):
            bits.append("Адрес не вывел из имён — скажи «разберись внимательно», прочту титул/договор.")
    else:
        bits.append("Запросы по этому проекту теперь идут с этим контекстом.")
    return {
        "answer": " ".join(bits),
        "operation": "les_md_drafted" if res.get("drafted") else "les_md_bound",
        "les_md": {k: res.get(k) for k in ("path", "project_id", "project", "pipelines", "ignore")},
    }
