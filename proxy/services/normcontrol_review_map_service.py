"""Загрузка и валидация СПДС review-map (ГОСТ Р 21.101-2026 и будущие стандарты).

АРХИТЕКТУРА — RAG-led SPDS review, НЕ rule-engine и НЕ «ГОСТ в YAML»
(docs/DOC_REVIEW_GOST_R_21_101_2026_PLAN.md §3, §5):

  • review-map — это КАРТА: какие требования стандарта искать в RAG, какие document-evidence нужны
    и какие computed/layout-checks возможны.
  • сам факт строки в review-map НЕ даёт review-status. Итоговый статус замечания появляется только
    из computed evidence ИЛИ human decision. RAG ищет требования и evidence, код считает формализуемое,
    модель связывает/объясняет, инженер подтверждает/отклоняет.
  • полного текста ГОСТ здесь нет — только clause-ссылки и paraphrase-message.

Этот модуль делает ровно одно: грузит и ВАЛИДИРУЕТ схему review-map (fail-closed). Он намеренно НЕ
содержит ни одного check-движка и не возвращает вердиктов — это Phase 1 (skeleton). Движок (computed
checks + RAG requirement/evidence retrieval + human decision) — это doc_review_service (Phase 2-3).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# kind — НЕ «как судить», а «откуда возьмётся evidence»: из RAG (retrieval), из кода (computed),
# из layout-разбора листа (layout) или только вручную (manual_required).
VALID_KIND = {"retrieval", "computed", "layout", "manual_required"}
VALID_SCOPE = {"project_doc", "working_doc", "both"}
VALID_SEVERITY = {"error", "warning", "info"}

REVIEW_MAP_DIR = Path("config/normcontrol")


@dataclass(frozen=True)
class ReviewTarget:
    """Одна цель проверки в карте review. НАМЕРЕННО без поля status — карта не выносит вердикт."""

    id: str
    clause: str
    title: str
    kind: str  # retrieval | computed | layout | manual_required
    scope: str  # project_doc | working_doc | both
    severity: str  # error | warning | info
    check: str  # идентификатор проверки (диспетчеризуется doc_review на Phase 2-3)
    evidence_required: tuple[str, ...]
    message: str  # краткий paraphrase, НЕ вербатим ГОСТ


@dataclass(frozen=True)
class ReviewMap:
    name: str
    standard: str
    title: str
    version: str
    effective_date: str
    supersedes: str
    targets: tuple[ReviewTarget, ...]


def _need(rule: dict, key: str, ctx: str):
    value = rule.get(key)
    if value in (None, ""):
        raise ValueError(f"review-map {ctx}: пустое/отсутствует обязательное поле '{key}'")
    return value


def load_review_map(name: str, *, base: Path | str | None = None) -> ReviewMap:
    """Грузит и валидирует review-map по имени (без .yaml). Любая кривизна схемы → ValueError (fail-closed)."""
    base_dir = Path(base) if base else REVIEW_MAP_DIR
    path = base_dir / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"review-map не найден: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    meta = data.get("meta") or {}
    if not meta.get("standard"):
        raise ValueError(f"review-map {name}: meta.standard обязателен")

    raw = data.get("rules") or []
    if not raw:
        raise ValueError(f"review-map {name}: пустой список rules")

    targets: list[ReviewTarget] = []
    seen: set[str] = set()
    for i, rule in enumerate(raw):
        ctx = f"{name}[{i}]"
        if not isinstance(rule, dict):
            raise ValueError(f"review-map {ctx}: правило должно быть словарём")
        rid = str(_need(rule, "id", ctx))
        if rid in seen:
            raise ValueError(f"review-map {name}: дубль id '{rid}'")
        seen.add(rid)

        kind = str(_need(rule, "kind", ctx))
        if kind not in VALID_KIND:
            raise ValueError(f"{ctx}: kind '{kind}' ∉ {sorted(VALID_KIND)}")
        scope = str(_need(rule, "scope", ctx))
        if scope not in VALID_SCOPE:
            raise ValueError(f"{ctx}: scope '{scope}' ∉ {sorted(VALID_SCOPE)}")
        severity = str(_need(rule, "severity", ctx))
        if severity not in VALID_SEVERITY:
            raise ValueError(f"{ctx}: severity '{severity}' ∉ {sorted(VALID_SEVERITY)}")

        evidence = rule.get("evidence_required") or []
        if not isinstance(evidence, list):
            raise ValueError(f"{ctx}: evidence_required должно быть списком")

        targets.append(ReviewTarget(
            id=rid,
            clause=str(rule.get("clause", "")),
            title=str(rule.get("title", "")),
            kind=kind,
            scope=scope,
            severity=severity,
            check=str(_need(rule, "check", ctx)),
            evidence_required=tuple(str(x) for x in evidence),
            message=str(rule.get("message", "")),
        ))

    return ReviewMap(
        name=str(meta.get("name", name)),
        standard=str(meta["standard"]),
        title=str(meta.get("title", "")),
        version=str(meta.get("version", "")),
        effective_date=str(meta.get("effective_date", "")),
        supersedes=str(meta.get("supersedes", "")),
        targets=tuple(targets),
    )


def list_review_maps(*, base: Path | str | None = None) -> list[str]:
    """Имена доступных review-map (stem .yaml) в каталоге config/normcontrol."""
    base_dir = Path(base) if base else REVIEW_MAP_DIR
    if not base_dir.exists():
        return []
    return sorted(p.stem for p in base_dir.glob("*.yaml"))
