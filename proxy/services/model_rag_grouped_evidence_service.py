"""Lossless evidence transport: identities first, then indivisible card bodies.

This module never searches or judges a candidate. Capacity is the only reason
for deferral. Shared text is byte-exact and always travels with its pointers.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    if meta.get("normative_base_sha256"):
        fields["normative_base_sha256"] = meta["normative_base_sha256"]
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
    preview_content: str | None = None
    preview_meta: Mapping[str, Any] | None = None


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
    meta_by_ref: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    complete_card_deferred_refs: list[str] = field(default_factory=list)


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
            "resource_code", "pricebook", "pricebook_sha256", "unit",
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
    metadata: dict[str, Mapping[str, Any]] = {}
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
            metadata[card.ref] = card.meta
            parts.append(pointer)
            source = str(card.meta.get("source_ref") or card.meta.get("doc_id") or "")
            if source:
                sources.setdefault(_source_id(source), source)
            if not full:
                deferred.append(card.ref)
                continue
            body_refs.append(card.ref)
            bodies[card.ref] = card.content
            facts = card_delivery_facts(card.meta, raw_body_shown=True)
            if facts["evidence_body_kind"] == "norm_card":
                marker = {"evidence_ref": card.ref, "card_delivery_facts": {
                    "normative_card_complete": facts["normative_card_complete"],
                    "normative_resources_status": facts["normative_resources_status"],
                }}
                if facts["normative_resources_status"] in ("preview", "unknown"):
                    marker["available_read"] = {"tool": "read_norm_card", "args": {"evidence_ref": card.ref}}
                parts.append(json.dumps(marker, ensure_ascii=False, separators=(",", ":")))
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
                        inventory, unshown, pointers, chars, metadata)


def plan_full_group_page(groups: Sequence[EvidenceGroup], max_chars: int) -> EvidencePage:
    """Show the bounded identity index first, then complete prefix query groups.

The same plan is used by direct and paged routes. Unshown identities have an
explicit cursor/count; no truncated card can masquerade as a delivered body.
"""
    page = _plan_single_body_page(groups, max_chars)
    if page.included_count or not any(card.preview_content is not None for group in groups for card in group.cards):
        return page
    # Full typed resources may not displace a whole preview that already fit.
    # Choose one entire old preview page, never mix or clip card bodies.
    previews = [EvidenceGroup(group.header, [
        EvidenceCard(card.ref, card.header, card.identity,
                     card.preview_content if card.preview_content is not None else card.content,
                     card.preview_meta if card.preview_meta is not None else card.meta)
        for card in group.cards
    ]) for group in groups]
    fallback = _plan_single_body_page(previews, max_chars)
    if not fallback.included_count:
        return page
    return replace(fallback, complete_card_deferred_refs=[
        card.ref for group in groups for card in group.cards if card.preview_content is not None
    ])


def _plan_single_body_page(groups: Sequence[EvidenceGroup], max_chars: int) -> EvidencePage:
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


def _compact_unread_pointer_records(
    records: Sequence[tuple[str, list[Any], Mapping[str, Any]]],
) -> tuple[list[str], bool]:
    """Share equal literal fields, never bodies or per-alias evidence identities."""
    ref_counts: dict[str, int] = {}
    for _, pointer, _ in records:
        ref_counts[pointer[0]] = ref_counts.get(pointer[0], 0) + 1
    owners: dict[str, str] = {}
    result = []
    shared = False
    for literal, pointer, provenance in records:
        ref = pointer[0]
        if not ref or ref_counts[ref] != 1:
            result.append(literal)
            continue
        try:
            key = json.dumps([pointer[1:], provenance], ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            result.append(literal)
            continue
        owner = owners.setdefault(key, ref)
        alias = json.dumps([ref, {"same_pointer_fields_as": owner}], ensure_ascii=False,
                           separators=(",", ":"))
        if owner != ref and len(alias) < len(literal):
            result.append(alias)
            shared = True
        else:
            result.append(literal)
    return result, shared


def compact_read_replay(chunks: Sequence[Any]) -> list[Any]:
    """Conserve shown bodies and compact unread pointers across native turns.

    Durable delivery flags are not evidence text. Repeating their verbose
    projections for every inventory entry must not consume the read frame.
    A deferred entry never exposes a stored body that was not shown.
    """
    from proxy.services.model_evidence_read_contract import shown_evidence_registry

    buckets: dict[str, list[Any]] = {}
    metadata: dict[tuple[str, str], Mapping[str, Any]] = {}
    pointer_records: list[tuple[str, list[Any], Mapping[str, Any]]] = []
    seen_pointers: set[str] = set()
    sources: dict[str, str] = {}
    for chunk in chunks:
        raw = chunk if isinstance(chunk, Mapping) else vars(chunk)
        meta = raw.get("meta") or {}
        ref = str(meta.get("model_evidence_ref") or raw.get("model_evidence_ref") or raw.get("ref") or "")
        content = str(raw.get("content") or "")
        source = str(meta.get("source_ref") or meta.get("doc_id") or raw.get("doc_id") or "")
        if source:
            sources.setdefault(_source_id(source), source)
        if meta.get("body_status") == "deferred_capacity":
            try:
                pointer = json.loads(content)
            except (ValueError, TypeError):
                pointer = None
            if not (isinstance(pointer, list) and len(pointer) >= 2
                    and pointer[:2] == [ref, "deferred_capacity"]):
                content = inventory_pointer(EvidenceCard(
                    ref, str(raw.get("doc_name") or ""), "", "", meta))
                pointer = json.loads(content)
            if content not in seen_pointers:
                # Global IDs belong to individual aliases and remain in raw
                # storage. Equal wire fields cannot discharge those identities.
                provenance = {name: meta.get(name, raw.get(name)) for name in (
                    "norm_key", "norm_code", "source_ref", "source_sha256", "edition", "base_type",
                    "doc_id", "dataset_id", "title", "measure_unit", "resource_code", "pricebook",
                    "pricebook_sha256", "source_locator", "page", "sheet", "row", "unit",
                ) if name in meta or name in raw}
                pointer_records.append((content, pointer, provenance))
                seen_pointers.add(content)
            continue
        metadata[(str(meta.get("global_evidence_id") or raw.get("global_evidence_id") or ""), ref)] = meta
        # The existing verified-view resolver may share only within this exact
        # provenance bucket; a changed SHA/edition cannot promote an old alias.
        identity = normative_card_identity(meta)
        bucket = json.dumps([identity, meta.get("doc_id", raw.get("doc_id")),
                             meta.get("dataset_id")], sort_keys=True, default=str)
        buckets.setdefault(bucket, []).append(chunk)
    records = [row for bucket in buckets.values()
               for row in shown_evidence_registry(bucket)["previously_shown_evidence_registry"]]
    catalogs = {"literal_source_catalog": {}, "literal_nrsp_catalog": {}}
    rows = []
    for row in records:
        ref = str(row.get("evidence_ref") or "")
        meta = metadata.get((str(row.get("global_evidence_id") or ""), ref), {})
        shared, result = share_registry_catalogs([row], {ref: meta})
        for name in catalogs:
            catalogs[name].update(shared[name])
        if meta.get("source_sha256") is not None:
            result[0]["source_sha256"] = meta["source_sha256"]
        rows.extend(result)
    catalogs["literal_source_catalog"].update(sources)
    keep = {"evidence_ref", "global_evidence_id", "doc_name", "norm_key", "norm_code",
            "source_ref", "source_sha256", "edition", "base_type", "doc_id", "dataset_id", "resource_code",
            "pricebook", "content", "body_available", "body_status", "body_missing",
            "shared_body_ref", "normative_card_complete", "normative_resources_status"}
    compact = []
    for row in rows:
        record = {key: value for key, value in row.items() if key in keep}
        aliases = [alias for alias in row.get("aliases", []) if alias != {
            "evidence_ref": row.get("evidence_ref"), "global_evidence_id": row.get("global_evidence_id")}]
        if aliases:
            record["aliases"] = aliases
        compact.append(record)
    pointers, shared_pointer_fields = _compact_unread_pointer_records(pointer_records)
    pointer_header = "Deferred identity pointers; read_norm_card/read_source remain available"
    if shared_pointer_fields:
        instruction = (". same_pointer_fields_as copies all owner pointer fields except ref; "
                       "distinct evidence identities, unread bodies")
        saved_chars = sum(len(record[0]) - len(pointer) for record, pointer in zip(pointer_records, pointers))
        if saved_chars > len(instruction):
            pointer_header += instruction
        else:
            pointers = [record[0] for record in pointer_records]
    return [catalogs, {"previously_shown_evidence_registry": compact,
                      "body_delivery": "Full literal bodies and exact shared catalogs. Deferred entries below are unread identity pointers only."},
            *([pointer_header + ":\n" + "\n".join(pointers)] if pointers else [])]


@dataclass(frozen=True)
class ModelReadReplay:
    required: list[Any]
    optional: list[str]
    inventory_refs: list[str]
    exact_body_refs: list[str]
    optional_body_refs: list[list[str]]


def prepare_model_read_replay(chunks: Sequence[Any], *, required_refs: Sequence[str] = ()) -> ModelReadReplay:
    """Keep exact reads required; budget whole discovery views without changing storage.

    Inventory admission and full-body admission are separate facts. Raw native
    results retain their content and immutable IDs even when only their index
    fits. Previously deferred views never manufacture an unseen stored body.
    """
    required_ids = set(required_refs)
    replay, inventory, exact = [], [], []
    groups: dict[str, list[EvidenceCard]] = {}
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        raw = dict(chunk) if isinstance(chunk, Mapping) else dict(vars(chunk))
        meta = dict(raw.get("meta") or {})
        ref = str(meta.get("model_evidence_ref") or raw.get("model_evidence_ref") or "")
        key = (str(meta.get("global_evidence_id") or raw.get("global_evidence_id") or ""), ref)
        if key in seen:
            continue
        seen.add(key)
        if ref:
            inventory.append(ref)
        is_exact = (meta.get("model_read_tool") in {"read_norm_card", "read_resource_price", "read_source"}
                    or meta.get("exact_card_read") is True or meta.get("source_read") is True
                    or ref in required_ids or key[0] in required_ids)
        content = str(raw.get("content") or "")
        has_body = bool(content) and (meta.get("body_status") != "deferred_capacity"
                                     or meta.get("model_raw_body_retained") is True)
        # A confirmed body is part of the model's evidence frontier, even when
        # it came from discovery and has not yet been cited. Inventory-only
        # delivery is a separate fact and cannot promote a retained unread body.
        was_body_delivered = meta.get("model_delivery_status") == "delivered" and has_body
        if is_exact or was_body_delivered:
            # Legacy deferred chunks can contain only an identity pointer. A
            # retained raw body may be replayed through this view clone, while
            # the stored chunk and its historical delivery flags stay intact.
            replay.append({**raw, "meta": {**meta, "body_status": "full"}} if has_body else raw)
            if ref and has_body:
                exact.append(ref)
            continue
        if has_body:
            group_key = str(meta.get("model_query_index") or ref)
            groups.setdefault(group_key, []).append(EvidenceCard(
                ref, f"[{ref} | {raw.get('doc_name') or ''}]", normative_card_identity(meta), content, meta))
        # This is a view clone. Neither raw bodies nor historical delivery flags
        # are overwritten by their present inventory-only representation.
        replay.append({**raw, "meta": {**meta, "body_status": "deferred_capacity"}})
    optional, optional_refs = [], []
    for cards in groups.values():
        query = str(cards[0].meta.get("model_query_text") or "")
        group = EvidenceGroup(f"Discovery query: {query}", cards)
        page = plan_full_group_page([group], 2**63 - 1)
        optional.append("\n\n".join(page.groups))
        optional_refs.append(list(page.body_refs))
    return ModelReadReplay(compact_read_replay(replay), optional, inventory, exact, optional_refs)


def native_read_growth_budget(*, available_tokens: int, generation_tokens: int,
                             groups: Sequence[EvidenceGroup], enabled: bool) -> dict[str, Any]:
    """Reserve native growth within the bound window, preserving a fitting group."""
    available = max(0, int(available_tokens))
    first = ((_render(groups, {card.ref for card in groups[0].cards}, 1).rendered_chars + 1) // 2 + 2
             if groups and enabled else 0)
    requested = min(max(0, int(generation_tokens)), available // 2) if enabled else 0
    reserved = min(requested, max(0, available - first))
    return {"requested_tokens": requested, "reserved_tokens": reserved,
            "remaining_group_tokens": available - reserved, "first_whole_group_tokens": first,
            "source": "bound_answer_generation_reserve; capped_by_first_whole_group"}
