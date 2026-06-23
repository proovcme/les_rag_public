"""Доменная онтология сметного дела — чтобы ЛЕС ПОНИМАЛ ВОР/КАЦ/ЛСР/КС и их связи.

Знание (что/зачем/из чего выходит) живёт в `config/domain/smeta_ontology.yaml`
(редактируемо, цитируемо), а не в весах модели (ADR-11/LLM-минимализм — не fine-tune).
Сервис даёт: поиск концепта по термину/синониму, цепочку деривации (граф inputs/outputs),
рендер глоссария (для RAG/промпта) и mermaid-граф. 0 LLM.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path("config/domain/smeta_ontology.yaml")

_KIND_LABEL = {
    "input": "вход (документ/данные)",
    "base": "нормативная база / цены",
    "method": "метод",
    "charge": "начисление",
    "coefficient": "коэффициент / налог",
    "output": "выходной документ",
    "act": "акт / исполнительная",
}


def _norm(s: Any) -> str:
    return " ".join(str(s or "").split()).lower().replace("ё", "е")


@lru_cache(maxsize=4)
def load_ontology(path: str | None = None) -> dict[str, Any]:
    """Загружает онтологию → {'by_id': {id: node}, 'order': [id,...]}. Кешируется."""
    import yaml

    p = Path(path) if path else DEFAULT_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for node in data.get("concepts", []):
        cid = node.get("id")
        if not cid:
            continue
        by_id[cid] = node
        order.append(cid)
    return {"by_id": by_id, "order": order, "version": data.get("version")}


def _index_aliases(onto: dict[str, Any]) -> dict[str, str]:
    """{нормализованный термин/синоним → id}."""
    idx: dict[str, str] = {}
    for cid, node in onto["by_id"].items():
        idx.setdefault(_norm(cid), cid)
        term = node.get("term") or ""
        idx.setdefault(_norm(term), cid)
        # аббревиатура до тире («КАЦ — …» → «кац») — частый способ спросить
        abbr = re.split(r"[—–]", term)[0].strip()
        if abbr:
            idx.setdefault(_norm(abbr), cid)
        for alias in node.get("aliases", []) or []:
            idx.setdefault(_norm(alias), cid)
    return idx


def get_concept(term: str, *, path: str | None = None) -> Optional[dict[str, Any]]:
    """Концепт по id/термину/синониму (точное совпадение, затем подстрока)."""
    onto = load_ontology(path)
    q = _norm(term)
    if not q:
        return None
    idx = _index_aliases(onto)
    if q in idx:
        return onto["by_id"][idx[q]]
    # подстрока: берём САМЫЙ КОРОТКИЙ (специфичный) ключ, содержащий запрос —
    # иначе «кац» матчит «специфиКАЦия». Длина ключа = мера специфичности.
    candidates = [(key, cid) for key, cid in idx.items() if q in key or key in q]
    if candidates:
        _key, cid = min(candidates, key=lambda kc: len(kc[0]))
        return onto["by_id"][cid]
    return None


def derivation(term: str, *, path: str | None = None) -> Optional[dict[str, Any]]:
    """Цепочка деривации концепта: upstream (из чего) и downstream (во что)."""
    onto = load_ontology(path)
    node = get_concept(term, path=path)
    if node is None:
        return None
    by_id = onto["by_id"]

    def _walk(start: str, edge: str) -> list[str]:
        seen: list[str] = []
        stack = list(by_id.get(start, {}).get(edge, []) or [])
        guard: set[str] = set()
        while stack:
            cur = stack.pop(0)
            if cur in guard or cur not in by_id:
                continue
            guard.add(cur)
            seen.append(cur)
            stack.extend(by_id[cur].get(edge, []) or [])
        return seen

    def _label(cid: str) -> dict[str, str]:
        n = by_id.get(cid, {})
        return {"id": cid, "term": n.get("term", cid)}

    return {
        "id": node["id"],
        "term": node.get("term"),
        "upstream": [_label(c) for c in _walk(node["id"], "inputs")],
        "downstream": [_label(c) for c in _walk(node["id"], "outputs")],
        "direct_inputs": [_label(c) for c in (node.get("inputs") or [])],
        "direct_outputs": [_label(c) for c in (node.get("outputs") or [])],
    }


def validate(path: str | None = None) -> list[str]:
    """Целостность графа: висячие ссылки inputs/outputs. Пусто = ок (для теста)."""
    onto = load_ontology(path)
    by_id = onto["by_id"]
    problems: list[str] = []
    for cid, node in by_id.items():
        for edge in ("inputs", "outputs"):
            for ref in node.get(edge, []) or []:
                if ref not in by_id:
                    problems.append(f"{cid}.{edge} → неизвестный концепт {ref!r}")
    return problems


def glossary_markdown(path: str | None = None) -> str:
    """Полный глоссарий в Markdown — для индексации в RAG и для людей."""
    onto = load_ontology(path)
    by_id = onto["by_id"]
    lines = [
        "# Глоссарий сметного дела (доменная онтология ЛЕС)",
        "",
        "Что такое каждый документ/понятие, зачем он, из чего выходит и во что превращается.",
        "Источник истины: `config/domain/smeta_ontology.yaml`.",
        "",
    ]
    for cid in onto["order"]:
        n = by_id[cid]
        lines.append(f"## {n.get('term', cid)}")
        kind = _KIND_LABEL.get(n.get("kind", ""), n.get("kind", ""))
        lines.append(f"*Тип:* {kind}")
        if n.get("aliases"):
            lines.append(f"*Синонимы:* {', '.join(n['aliases'])}")
        lines.append("")
        lines.append(f"**Что это:** {n.get('what', '')}")
        lines.append(f"**Зачем:** {n.get('why', '')}")
        if n.get("inputs"):
            terms = ", ".join(by_id.get(i, {}).get("term", i) for i in n["inputs"])
            lines.append(f"**Из чего выходит:** {terms}")
        if n.get("outputs"):
            terms = ", ".join(by_id.get(o, {}).get("term", o) for o in n["outputs"])
            lines.append(f"**Во что превращается / что питает:** {terms}")
        if n.get("basis"):
            lines.append(f"**Нормативная основа:** {n['basis']}")
        lines.append("")
    return "\n".join(lines)


def mermaid_graph(path: str | None = None) -> str:
    """Граф деривации в формате mermaid (flowchart) — для GUI/визуализации."""
    onto = load_ontology(path)
    by_id = onto["by_id"]
    lines = ["flowchart LR"]
    for cid in onto["order"]:
        short = by_id[cid].get("term", cid).split("—")[0].strip().replace('"', "'")
        lines.append(f'  {cid}["{short}"]')
    for cid in onto["order"]:
        for o in by_id[cid].get("outputs", []) or []:
            if o in by_id:
                lines.append(f"  {cid} --> {o}")
    return "\n".join(lines)
