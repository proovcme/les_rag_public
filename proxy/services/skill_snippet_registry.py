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
        "Keep source-derived work and quantity decisions traceable.",
        "Самостоятельно определи, какие расчётные строки следуют из источника; сохрани связь с исходными данными.",
        ("specification", "bor"),
    ),
    "smeta.quantity_conflict": SkillSnippet(
        "smeta.quantity_conflict",
        "smeta",
        "Keep quantity decisions traceable.",
        "Количества и их преобразования должны сохранять ссылку на источник или явное допущение модели.",
        ("quantity", "conflict"),
    ),
    "smeta.rim_scenario_estimate": SkillSnippet(
        "smeta.rim_scenario_estimate",
        "smeta",
        "Let the model choose the estimating method.",
        "Метод расчёта и необходимость допущений выбирает модель по задаче и доступным источникам.",
        ("rim", "scenario"),
    ),
    "smeta.gesn_pricing_workflow": SkillSnippet(
        "smeta.gesn_pricing_workflow",
        "smeta",
        "Use available estimating tools without code-side professional decisions.",
        "Модель выбирает работы, нормы и применимость; инструменты ищут источники, раскрывают данные и считают.",
        ("gesn", "rim", "pricing", "sources"),
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
