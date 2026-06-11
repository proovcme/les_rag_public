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


def transform_query(raw_text: str) -> str:
    """Preprocessor for queries: layout correction, typo correction, and fail-safe fallback."""
    try:
        if not raw_text or not raw_text.strip():
            return raw_text

        # Lowercase layout mapping dictionary
        ENG_TO_RUS = {
            'q': 'й', 'w': 'ц', 'e': 'у', 'r': 'к', 't': 'е', 'y': 'н', 'u': 'г', 'i': 'ш', 'o': 'щ', 'p': 'з',
            '[': 'х', ']': 'ъ', 'a': 'ф', 's': 'ы', 'd': 'в', 'f': 'а', 'g': 'п', 'h': 'р', 'j': 'о', 'k': 'л',
            'l': 'д', ';': 'ж', "'": 'э', 'z': 'я', 'x': 'ч', 'c': 'с', 'v': 'м', 'b': 'и', 'n': 'т', 'm': 'ь',
            ',': 'б', '.': 'ю', '/': '.'
        }

        # Normalize layout mistakes containing punctuation first
        raw_text = re.sub(r"\'jv", "эом", raw_text, flags=re.IGNORECASE)
        raw_text = re.sub(r"'jv", "эом", raw_text, flags=re.IGNORECASE)

        LAYOUT_MISTAKES = {
            "cj": "сп",
            "ujcn": "гост",
            "jdb": "ов",
            "dr": "вк",
            "\'jv": "эом",
            "rj": "кж",
            "feu": "аупт",
            "cnye": "соуэ",
            "gmt": "пуэ",
        }

        CORRECTION_TARGETS = {
            "эвакуация", "пожарный", "пожарная", "пожаротушение", "огнестойкость", "противодымная",
            "сигнализация", "водоснабжение", "водоотведение", "канализация", "электрооборудование",
            "электроосвещение", "силовые", "железобетонные", "армирование", "отопление",
            "вентиляция", "кондиционирование", "воздухообмен", "конструкция", "нагрузка",
            "фундамент", "основание", "железобетон", "арматура", "перекрытие", "смета",
            "спецификация", "расценка", "объем", "объём", "безопасность", "документация",
            "требования"
        }

        EXCLUDED_FROM_CORRECTION = {
            "гост", "сп", "снип", "пуэ", "пп", "ов", "вк", "эом", "кж", "км", "кр", "аупт",
            "соуэ", "апс", "спс", "мгн", "иги", "пос", "ппр", "сс", "скс", "эм", "нвк"
        }

        def translate_word(word: str) -> str:
            translated = []
            for char in word.lower():
                translated.append(ENG_TO_RUS.get(char, char))
            return "".join(translated)

        def get_closest_match(word: str) -> str:
            word_lower = word.lower()
            if word_lower in EXCLUDED_FROM_CORRECTION or word_lower in CORRECTION_TARGETS or len(word_lower) < 4:
                return word
            
            best_match = word
            min_dist = 999
            
            for target in CORRECTION_TARGETS:
                if abs(len(target) - len(word_lower)) > 2:
                    continue
                
                dist = levenshtein_distance(word_lower, target)
                if dist < min_dist:
                    min_dist = dist
                    best_match = target
            
            # Acceptance thresholds
            if len(word_lower) <= 6 and min_dist == 1:
                if word.isupper():
                    return best_match.upper()
                if word[0].isupper():
                    return best_match.capitalize()
                return best_match
            elif len(word_lower) >= 7 and min_dist <= 2:
                if word.isupper():
                    return best_match.upper()
                if word[0].isupper():
                    return best_match.capitalize()
                return best_match
                
            return word

        def levenshtein_distance(s1: str, s2: str) -> int:
            if len(s1) < len(s2):
                return levenshtein_distance(s2, s1)
            if len(s2) == 0:
                return len(s1)
            
            previous_row = list(range(len(s2) + 1))
            for i, c1 in enumerate(s1):
                current_row = [i + 1]
                for j, c2 in enumerate(s2):
                    insertions = previous_row[j + 1] + 1
                    deletions = current_row[j] + 1
                    substitutions = previous_row[j] + (c1 != c2)
                    current_row.append(min(insertions, deletions, substitutions))
                previous_row = current_row
            return previous_row[-1]

        # Process text token by token, keeping non-alphanumeric separators intact
        tokens = re.split(r"(\W+)", raw_text)
        new_tokens = []
        for token in tokens:
            if not token or not token.strip() or not token[0].isalnum():
                new_tokens.append(token)
                continue
            
            # 1. Layout Correction
            token_lower = token.lower()
            if token_lower in LAYOUT_MISTAKES:
                corrected_token = LAYOUT_MISTAKES[token_lower]
                if token.isupper():
                    corrected_token = corrected_token.upper()
                elif token[0].isupper():
                    corrected_token = corrected_token.capitalize()
                new_tokens.append(corrected_token)
                continue
                
            # Check if it consists of letters that are purely QWERTY layout mistake
            if re.match(r"^[a-zA-Z\[\]\\;',./]+$", token):
                if token_lower not in {"bim", "tim", "email", "mail", "dropbox", "hvac", "aec", "cad"}:
                    translated = translate_word(token)
                    translated_match = get_closest_match(translated)
                    if translated_match != translated or translated in CORRECTION_TARGETS:
                        if token.isupper():
                            translated_match = translated_match.upper()
                        elif token[0].isupper():
                            translated_match = translated_match.capitalize()
                        new_tokens.append(translated_match)
                        continue
            # 2. Typo Correction (only for alphabetic words)
            if token.isalpha():
                corrected = get_closest_match(token)
                new_tokens.append(corrected)
            else:
                new_tokens.append(token)
            
        return "".join(new_tokens)
        
    except Exception:
        return raw_text


def normalize_question(question: str) -> str:
    question = transform_query(question)
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
    question = transform_query(question)
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
    question = transform_query(question)
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


def expand_query_synonyms(question: str) -> str:
    """Dynamically expand any terms in the question using the synonyms dictionary from kot_terms.yaml."""
    try:
        cfg = load_kot_config()
        q_norm = normalize_question(question)
        words = re.findall(r"[a-zа-яё0-9-]+", q_norm, flags=re.IGNORECASE)
        
        # Build a global mapping of lowercase alias -> list of synonyms
        syn_map = {}
        for domain in cfg.get("domains", []):
            synonyms = domain.get("synonyms") or {}
            for alias, val in synonyms.items():
                alias_clean = alias.casefold().replace("ё", "е").strip()
                vals = [v.strip().casefold().replace("ё", "е") for v in val.split(",") if v.strip()]
                all_group = list(dict.fromkeys([alias_clean, *vals]))
                for term in all_group:
                    syn_map[term] = all_group
                    
        # Find any matching words in the query and gather expansions.
        # W2.7: помимо точного совпадения — префиксное (≥5 общих символов):
        # «дымоудалениЮ» находит ключ «дымоудаление», «приточкИ» → «приточка».
        def _lookup(word_clean: str):
            hit = syn_map.get(word_clean)
            if hit:
                return hit
            if len(word_clean) < 5:
                return None
            for alias, group in syn_map.items():
                if len(alias) >= 5 and (
                    word_clean.startswith(alias[: max(5, len(alias) - 3)])
                    or alias.startswith(word_clean[: max(5, len(word_clean) - 3)])
                ):
                    return group
            return None

        expansions = []
        for word in words:
            word_clean = word.casefold().replace("ё", "е")
            group = _lookup(word_clean)
            if group:
                for syn in group:
                    if syn not in q_norm and syn not in expansions:
                        expansions.append(syn)
                        
        if expansions:
            return question + "\n" + " ".join(expansions)
        return question
    except Exception:
        return question
