"""Lossless evidence transport: identities first, then indivisible card bodies.

This module never searches or judges a candidate. Capacity is the only reason
for deferral. Shared text is byte-exact and always travels with its pointers.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


_NRSP_HEADER = "НР/СП: варианты каталога для сборника; выбор модели по условиям объекта, не готовая ставка:"


def normative_card_identity(meta: Mapping[str, Any]) -> str:
    """Exact normative pointer identity, independent of query/turn aliases.

    A parent cipher, different edition or different source cannot discharge
    this identity. Missing provenance remains missing; nothing is inferred.
    """
    code = str(meta.get("norm_code") or "").strip().upper()
    if not code and not meta.get("norm_key"):
        return ""
    for dash in ("–", "—", "‑", "−"):
        code = code.replace(dash, "-")
    fields = {name: meta.get(name) for name in (
        "norm_key", "source_ref", "source_sha256", "edition", "base_type",
    )}
    fields["norm_code"] = code
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str)
    return "norm_card_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def card_delivery_facts(meta: Mapping[str, Any], *, raw_body_shown: bool) -> dict[str, Any]:
    """A whole RAG preview is distinct from a complete typed normative card."""
    is_norm = bool(meta.get("norm_key") or meta.get("norm_code"))
    if not is_norm:
        return {"raw_hit_body_shown": raw_body_shown, "card_body_shown": raw_body_shown,
                "evidence_body_kind": "document"}
    resources = meta.get("resources")
    returned = meta.get("resources_returned")
    count = meta.get("resource_count")
    complete = (raw_body_shown and meta.get("resources_complete") is True
                and isinstance(resources, (list, tuple))
                and isinstance(returned, int) and not isinstance(returned, bool)
                and returned == len(resources)
                and (count is None or count == returned))
    status = ("not_read" if not raw_body_shown else "complete" if complete else
              "preview" if "resource_preview" in meta or meta.get("resources_complete") is False
              or isinstance(count, int) else "unknown")
    return {"raw_hit_body_shown": raw_body_shown, "card_body_shown": raw_body_shown,
            "normative_card_complete": complete, "normative_resources_status": status,
            "normative_conditions_shown": raw_body_shown, "evidence_body_kind": "norm_card"}


@dataclass(frozen=True)
class LosslessBody:
    original: str
    content: str
    catalog_id: str = ""
    catalog_text: str = ""


def lossless_nrsp_body(content: str, meta: Mapping[str, Any]) -> LosslessBody:
    """Share only the exact producer-owned block and exact ordered metadata."""
    rules = meta.get("nr_sp_candidates")
    if not isinstance(rules, (list, tuple)) or not rules:
        return LosslessBody(content, content)
    try:
        block = "\n".join([_NRSP_HEADER, *[
            f"{r['rule_id']}: {r['label']}; НР {r['nr_pct']}%; СП {r['sp_pct']}%; "
            f"{r['basis']}; источник {r['source_ref']}" for r in rules
        ]])
    except (KeyError, TypeError):
        return LosslessBody(content, content)
    # A mismatch remains ordinary full text. Do not reconstruct missing facts.
    if content.count(block) != 1:
        return LosslessBody(content, content)
    start = content.index(block)
    end = start + len(block)
    if (start and content[start - 1] != "\n") or (end < len(content) and content[end] != "\n"):
        return LosslessBody(content, content)
    identity = json.dumps({"text": block, "candidates": rules}, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"), default=str)
    catalog_id = "nrsp_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    marker = f"НР/СП: общий буквальный каталог [{catalog_id}]."
    return LosslessBody(content, content[:start] + marker + content[end:], catalog_id, block)


def restore_nrsp_body(body: LosslessBody) -> str:
    if not body.catalog_id:
        return body.content
    marker = f"НР/СП: общий буквальный каталог [{body.catalog_id}]."
    return body.content.replace(marker, body.catalog_text, 1)


@dataclass(frozen=True)
class EvidenceCard:
    ref: str
    header: str
    identity: str
    content: str
    meta: Mapping[str, Any]


@dataclass(frozen=True)
class EvidenceGroup:
    header: str
    cards: Sequence[EvidenceCard]


@dataclass(frozen=True)
class EvidencePage:
    included_count: int
    groups: list[str]
    body_refs: list[str]
    shared_refs: dict[str, str]
    body_by_ref: dict[str, str]
    deferred_refs: list[str]
    inventory_refs: list[str]
    unshown_refs: list[str]
    pointer_by_ref: dict[str, str]
    rendered_chars: int


def _source_id(source: str) -> str:
    return "source_" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _literal_title(card: EvidenceCard) -> str:
    title = card.meta.get("title")
    if title is not None:
        return str(title)
    prefix = "Наименование: "
    return next((line[len(prefix):] for line in card.content.splitlines()
                 if line.startswith(prefix)), card.header)


def inventory_pointer(card: EvidenceCard, *, full: bool = False) -> str:
    """A shown identity does not assert that conditions/resources were read."""
    source = str(card.meta.get("source_ref") or card.meta.get("doc_id") or "")
    fields = [card.ref, "full" if full else "deferred_capacity",
              str(card.meta.get("norm_key") or ""), str(card.meta.get("norm_code") or ""),
              _literal_title(card), str(card.meta.get("measure_unit") or ""),
              _source_id(source) if source else ""]
    if not card.meta.get("norm_key") and not card.meta.get("norm_code"):
        fields.append({name: card.meta[name] for name in (
            "doc_id", "dataset_id", "doc_name", "source_locator", "page", "sheet", "row",
        ) if card.meta.get(name) is not None})
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":"))


def _render(groups: Sequence[EvidenceGroup], visible: set[str], full_count: int) -> EvidencePage:
    rendered: list[str] = []
    sources: dict[str, str] = {}
    catalogs: dict[str, str] = {}
    owners: dict[tuple[str, str], str] = {}
    body_refs: list[str] = []
    shared_refs: dict[str, str] = {}
    bodies: dict[str, str] = {}
    pointers: dict[str, str] = {}
    deferred: list[str] = []
    inventory: list[str] = []
    unshown: list[str] = []
    for index, group in enumerate(groups):
        parts = [group.header]
        if not group.cards and index < full_count:
            parts.append("hits=0")
        for card in group.cards:
            if card.ref not in visible:
                unshown.append(card.ref)
                deferred.append(card.ref)
                continue
            full = index < full_count
            pointer = inventory_pointer(card, full=full)
            pointers[card.ref] = pointer
            inventory.append(card.ref)
            parts.append(pointer)
            source = str(card.meta.get("source_ref") or card.meta.get("doc_id") or "")
            if source:
                sources.setdefault(_source_id(source), source)
            if not full:
                deferred.append(card.ref)
                continue
            body_refs.append(card.ref)
            bodies[card.ref] = card.content
            identity = (card.identity, card.content)
            owner = owners.setdefault(identity, card.ref)
            if owner != card.ref:
                shared_refs[card.ref] = owner
                parts.append(f"{card.header}:\nТо же содержимое и источник, что у {owner}; см. показанный там текст.")
                continue
            body = lossless_nrsp_body(card.content, card.meta)
            if body.catalog_id:
                catalogs.setdefault(body.catalog_id, body.catalog_text)
            parts.append(f"{card.header}:\n{body.content}")
        if len(parts) > 1:
            rendered.append("\n\n".join(parts))
    if rendered:
        shared = ["Индекс: [ref,body_status,norm_key,norm_code,title,unit,source,read_source?]. "
                  "full = целое найденное тело, возможен обзор ресурсов; deferred_capacity = только указатель. "
                  "Доступно read_norm_card/read_source."]
        shared.append(json.dumps({"returned_hits": sum(len(group.cards) for group in groups),
                                  "identities_shown": len(inventory), "full_body_aliases_shown": len(body_refs),
                                  "deferred_body_aliases": len(deferred), "identities_unshown": len(unshown),
                                  "unshown_cursor": unshown[0] if unshown else None},
                                 ensure_ascii=False, separators=(",", ":")))
        if sources:
            shared.append("Буквальные источники индекса:\n" + "\n".join(
                json.dumps([key, value], ensure_ascii=False, separators=(",", ":"))
                for key, value in sources.items()))
        if catalogs:
            shared.extend(f"Общий буквальный каталог [{key}]:\n{value}" for key, value in catalogs.items())
        rendered[0] = "\n\n".join([*shared, rendered[0]])
    chars = len("\n\n".join(rendered))
    return EvidencePage(full_count, rendered, body_refs, shared_refs, bodies, deferred,
                        inventory, unshown, pointers, chars)


def plan_full_group_page(groups: Sequence[EvidenceGroup], max_chars: int) -> EvidencePage:
    """Show the bounded identity index first, then complete prefix query groups.

The same plan is used by direct and paged routes. Unshown identities have an
explicit cursor/count; no truncated card can masquerade as a delivered body.
"""
    limit = max(0, int(max_chars))
    visible: set[str] = set()
    for group in groups:
        for card in group.cards:
            trial = {*visible, card.ref}
            if _render(groups, trial, 0).rendered_chars > limit:
                break
            visible = trial
        else:
            continue
        break
    page = _render(groups, visible, 0)
    for count, group in enumerate(groups, 1):
        if any(card.ref not in visible for card in group.cards):
            break
        trial = _render(groups, visible, count)
        if trial.rendered_chars > limit:
            break
        page = trial
    if not page.included_count and groups:
        # Index delivery must not consume all room and stall an otherwise
        # physically fitting first whole group at the same durable offset.
        first = {card.ref for card in groups[0].cards}
        trial = _render(groups, first, 1)
        if trial.rendered_chars <= limit:
            visible = first
            for group in groups[1:]:
                for card in group.cards:
                    candidate = {*visible, card.ref}
                    trial = _render(groups, candidate, 1)
                    if trial.rendered_chars > limit:
                        break
                    visible = candidate
                else:
                    continue
                break
            page = _render(groups, visible, 1)
    return page


def share_registry_catalogs(records: Sequence[Mapping[str, Any]], metadata: Mapping[str, Mapping[str, Any]]) -> list[Any]:
    """Replay literal shown views with their exact shared catalogs in read turns."""
    catalogs: dict[str, str] = {}
    sources: dict[str, str] = {}
    rows = []
    for record in records:
        row = dict(record)
        ref = str(row.get("evidence_ref") or "")
        meta = metadata.get(ref, {})
        body = lossless_nrsp_body(str(row.get("content") or ""), meta)
        row["content"] = body.content
        row["body_status"] = str(meta.get("body_status") or "full")
        row["body_available"] = row["body_status"] == "full" and bool(body.original)
        row.update(card_delivery_facts(meta, raw_body_shown=row["body_available"]))
        row["normative_card_identity"] = normative_card_identity(meta)
        if body.catalog_id:
            catalogs.setdefault(body.catalog_id, body.catalog_text)
        source = str(row.get("source_ref") or "")
        if source:
            key = _source_id(source)
            sources.setdefault(key, source)
            row["source_ref"] = {"shared_source_pointer": key}
        rows.append(row)
    return [{"literal_source_catalog": sources, "literal_nrsp_catalog": catalogs}, rows]
