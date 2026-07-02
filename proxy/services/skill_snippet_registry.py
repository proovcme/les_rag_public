"""Short professional snippets selected per LES module/turn.

Snippets are intentionally small. They are not facts and do not replace the
domain model's decision; they only remind the model how to approach a class of
task.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from proxy.services.les_module_service import module_spec


@dataclass(frozen=True)
class SkillSnippet:
    snippet_id: str
    module_id: str
    purpose: str
    text: str
    tags: tuple[str, ...] = ()


SNIPPETS: dict[str, SkillSnippet] = {
    "core.source_grounding": SkillSnippet(
        "core.source_grounding",
        "core",
        "Separate facts, calculations, assumptions, and missing data.",
        (
            "Факты, числа и выводы отделяй от допущений. Источник данных — документ, "
            "строка таблицы, проверенный расчёт, lookup-запись или явное пользовательское "
            "подтверждение. Пример паттерна не является фактом текущего объекта."
        ),
        ("facts", "sources"),
    ),
    "core.active_continuation": SkillSnippet(
        "core.active_continuation",
        "core",
        "Continue active work instead of restarting.",
        (
            "Если есть активное состояние задачи, короткую команду применяй к нему. "
            "Не начинай заново, не проси повторно ВОР/таблицу/документ, если они уже есть "
            "в рабочей памяти."
        ),
        ("followup", "state"),
    ),
    "smeta.specification_to_bor": SkillSnippet(
        "smeta.specification_to_bor",
        "smeta",
        "Build BOR candidate from specification before norm selection and pricing.",
        (
            "Спецификация не является сметой. Сначала сделай мост спецификация -> ВОР: "
            "поставка отдельно, работы отдельно, parent/child количества сохраняй, missing "
            "quantity не превращай в 1, missing price не превращай в 0."
        ),
        ("specification", "bor"),
    ),
    "smeta.quantity_conflict": SkillSnippet(
        "smeta.quantity_conflict",
        "smeta",
        "Show source quantity split when quantities conflict.",
        (
            "Если исходные количества конфликтуют и влияют на стоимость, покажи развилку "
            "объёмов с источником, составом и статусом. Не выбирай договорный объём молча; "
            "сценарные деньги можно дать по вариантам, но не как финал."
        ),
        ("quantity", "conflict"),
    ),
    "smeta.rim_scenario_estimate": SkillSnippet(
        "smeta.rim_scenario_estimate",
        "smeta",
        "Give RIM-based scenario when final trace is not closed.",
        (
            "Если пользователь просит смету/оценку и не запретил допущения, измеримая ВОР "
            "должна получить попытку стоимости работ. При доступной нормативной базе основной "
            "ход — РИМ-сценарий по нормативным аналогам, с видимой базой и допуском."
        ),
        ("rim", "scenario"),
    ),
    "smeta.active_continuation": SkillSnippet(
        "smeta.active_continuation",
        "smeta",
        "Apply follow-up commands to the current BOR/estimate.",
        (
            "Команды вроде «добавь номера ГЭСН», «пересчитай», «убери строку», "
            "«сделай по варианту Б» применяй к текущей ВОР/оценке из active state."
        ),
        ("followup", "smeta"),
    ),
    "normcontrol.findings": SkillSnippet(
        "normcontrol.findings",
        "normcontrol",
        "Write check findings with object, rule, risk, and action.",
        "Замечание нормоконтроля должно иметь объект проверки, правило/источник, суть, риск и действие.",
        ("findings",),
    ),
    "docs_review.professional_review": SkillSnippet(
        "docs_review.professional_review",
        "docs_review",
        "Review project documents as an engineer.",
        "Сначала фактические замечания и риски, затем вопросы, затем краткий итог.",
        ("review",),
    ),
    "bim_qto.quantities": SkillSnippet(
        "bim_qto.quantities",
        "bim_qto",
        "Keep model quantities traceable.",
        "Объёмы модели показывай с элементом, свойством/геометрией, единицей, формулой и статусом проверки.",
        ("qto",),
    ),
    "procurement.offer_compare": SkillSnippet(
        "procurement.offer_compare",
        "procurement",
        "Compare commercial offers without inventing prices.",
        "КП сравнивай по цене, составу, условиям, НДС, срокам и пробелам; отсутствующая цена не равна нулю.",
        ("offers",),
    ),
    "contracts.risk_review": SkillSnippet(
        "contracts.risk_review",
        "contracts",
        "Review contract clauses and risks.",
        "Разделяй буквальное условие договора, риск, вопрос юристу и предлагаемую правку.",
        ("contracts",),
    ),
}


def get_snippet(snippet_id: str) -> SkillSnippet | None:
    return SNIPPETS.get(snippet_id)


def select_skill_snippets(
    module_id: str,
    *,
    turn_type: str = "new_task",
    user_input: str = "",
    limit: int = 4,
) -> list[SkillSnippet]:
    spec = module_spec(module_id)
    candidates: list[str] = ["core.source_grounding"]
    if turn_type == "active_continuation":
        candidates.append("core.active_continuation")
        if module_id == "smeta":
            candidates.append("smeta.active_continuation")
    candidates.extend(spec.skill_snippets)

    text = str(user_input or "").casefold()
    if module_id == "smeta":
        if any(word in text for word in ("спецификац", "оборудован", "кабель", "материал")):
            candidates.insert(1, "smeta.specification_to_bor")
        if any(word in text for word in ("рим", "гэсн", "смет", "стоим", "оцен")):
            candidates.insert(1, "smeta.rim_scenario_estimate")

    out: list[SkillSnippet] = []
    seen: set[str] = set()
    for snippet_id in candidates:
        if snippet_id in seen:
            continue
        snippet = get_snippet(snippet_id)
        if snippet is not None:
            out.append(snippet)
            seen.add(snippet_id)
        if len(out) >= limit:
            break
    return out


def render_snippets(snippets: list[SkillSnippet]) -> str:
    if not snippets:
        return ""
    lines = ["Короткие профессиональные правила для текущего хода:"]
    for snippet in snippets:
        lines.append(f"- {snippet.snippet_id}: {snippet.text}")
    return "\n".join(lines)


def snippet_registry_snapshot() -> dict[str, Any]:
    return {
        key: {
            "module_id": item.module_id,
            "purpose": item.purpose,
            "tags": list(item.tags),
            "text": item.text,
        }
        for key, item in SNIPPETS.items()
    }
