"""K.O.T. deterministic terminology routing."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "kot_terms.yaml"


@dataclass(frozen=True)
class KotDomainMatch:
    id: str
    label: str
    dataset_filter: str
    score: float
    terms: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KotDecision:
    dataset_filter: str | None
    matched_domains: tuple[KotDomainMatch, ...]
    matched_terms: tuple[str, ...]
    norm_refs: tuple[str, ...]
    confidence: float
    reason: str
    ambiguous: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "dataset_filter": self.dataset_filter,
            "matched_domains": [match.payload() for match in self.matched_domains],
            "matched_terms": list(self.matched_terms),
            "norm_refs": list(self.norm_refs),
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "ambiguous": self.ambiguous,
        }


def _config_path() -> Path:
    return Path(os.getenv("KOT_TERMS_PATH", str(DEFAULT_CONFIG_PATH)))


@lru_cache(maxsize=4)
def load_kot_config(path: str | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else _config_path()
    if not cfg_path.exists():
        return {"domains": [], "norm_refs": [], "confidence": {"confident": 0.62, "ambiguous_gap": 0.12}}
    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("domains", [])
    data.setdefault("norm_refs", [])
    data.setdefault("confidence", {})
    return data


def clear_kot_config_cache() -> None:
    load_kot_config.cache_clear()


def normalize_question(question: str) -> str:
    q = question.casefold().replace("ё", "е")
    q = re.sub(r"\s+", " ", q)
    return q.strip()


def _term_matches(term: str, question: str) -> bool:
    if not term:
        return False
    if " " in term:
        return term in question
    if len(term) <= 3:
        return bool(re.search(rf"(?<![a-zа-я0-9]){re.escape(term)}(?![a-zа-я0-9])", question, flags=re.IGNORECASE))
    if len(term) == 4:
        return bool(re.search(rf"(?<![a-zа-я0-9]){re.escape(term)}[a-zа-я0-9-]*", question, flags=re.IGNORECASE))
    return term in question


def extract_norm_refs(question: str) -> tuple[str, ...]:
    cfg = load_kot_config()
    q = normalize_question(question)
    refs: list[str] = []
    for item in cfg.get("norm_refs", []):
        pattern = str(item.get("pattern") or "")
        if not pattern:
            continue
        for match in re.findall(pattern, q, flags=re.IGNORECASE):
            value = match if isinstance(match, str) else " ".join(part for part in match if part)
            value = re.sub(r"\s+", " ", value.strip())
            if value and value not in refs:
                refs.append(value)
    return tuple(refs)


def analyze_question(
    question: str,
    *,
    dataset_filter: str | None = None,
    dataset_ids: list[str] | None = None,
) -> KotDecision:
    if dataset_ids:
        return KotDecision(dataset_filter, (), (), extract_norm_refs(question), 1.0, "explicit_dataset_ids")
    if dataset_filter:
        return KotDecision(dataset_filter, (), (), extract_norm_refs(question), 1.0, "explicit_filter")

    cfg = load_kot_config()
    q = normalize_question(question)
    domain_matches: list[KotDomainMatch] = []
    matched_terms: list[str] = []

    for domain in cfg.get("domains", []):
        terms = [str(term).casefold().replace("ё", "е") for term in domain.get("terms", [])]
        patterns = [str(pattern) for pattern in domain.get("patterns", []) if str(pattern or "").strip()]
        synonyms = {
            str(alias).casefold().replace("ё", "е"): str(value).casefold().replace("ё", "е")
            for alias, value in (domain.get("synonyms") or {}).items()
        }
        found: list[str] = []
        pattern_found = False
        for term in terms:
            if _term_matches(term, q):
                found.append(term)
        for alias, canonical in synonyms.items():
            if _term_matches(alias, q):
                found.append(canonical or alias)
        for pattern in patterns:
            try:
                if re.search(pattern, q, flags=re.IGNORECASE):
                    pattern_found = True
                    found.append(str(domain.get("id") or domain.get("dataset_filter") or "pattern").casefold())
            except re.error:
                continue
        if not found:
            continue
        unique_terms = tuple(dict.fromkeys(found))
        matched_terms.extend(unique_terms)
        score = min(1.0, 0.38 + len(unique_terms) * 0.18)
        if any(term.isdigit() or "-" in term for term in unique_terms):
            score = min(1.0, score + 0.12)
        if pattern_found:
            score = min(1.0, score + 0.12)
        domain_matches.append(
            KotDomainMatch(
                id=str(domain.get("id") or domain.get("dataset_filter") or ""),
                label=str(domain.get("label") or domain.get("id") or ""),
                dataset_filter=str(domain.get("dataset_filter") or ""),
                score=score,
                terms=unique_terms,
            )
        )

    domain_matches.sort(key=lambda item: item.score, reverse=True)
    norm_refs = extract_norm_refs(question)
    if not domain_matches:
        return KotDecision(None, (), (), norm_refs, 0.0, "no_kot_match")

    top = domain_matches[0]
    second = domain_matches[1] if len(domain_matches) > 1 else None
    confident = float(cfg.get("confidence", {}).get("confident", 0.62))
    ambiguous_gap = float(cfg.get("confidence", {}).get("ambiguous_gap", 0.12))
    ambiguous = bool(second and top.score - second.score < ambiguous_gap)
    if top.score < confident:
        reason = "weak_kot_match"
        dataset = None
    elif ambiguous:
        reason = "ambiguous_kot_match"
        dataset = None
    else:
        reason = f"kot_{top.label or top.id}"
        dataset = top.dataset_filter or None

    return KotDecision(
        dataset,
        tuple(domain_matches),
        tuple(dict.fromkeys(matched_terms)),
        norm_refs,
        top.score,
        reason,
        ambiguous=ambiguous,
    )
