"""Read-only actions in the existing model turn; no professional decisions here."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from proxy.services.model_lsr_result_contract import model_lsr_resource_decision_instruction

def model_evidence_read_tool_schemas() -> list[dict[str, Any]]:
    definitions = (
        ("search_sources", "Search norms or explicitly selected documents. The query is executed verbatim.",
         {"q": {"type": "string"}, "target": {"type": "string", "enum": ["norms", "documents"]}}, ["q"]),
        ("read_norm_card", "Read all resources and consumption of one previously shown exact norm card.",
         {"norm_key": {"type": "string"}, "norm_code": {"type": "string"}}, []),
        ("search_pricebook_resources", "Search resource candidates in the application's bound region/quarter pricebook; this does not choose applicability.",
         {"q": {"type": "string"}}, ["q"]),
        ("read_resource_price", "Read price, unit and origin of one literal code in the bound pricebook.",
         {"code": {"type": "string"}}, ["code"]),
        ("read_source", "Read a current attachment row (source_row only), or a shown/named document in selected datasets.",
         {"doc_id": {"type": "string"}, "dataset_id": {"type": "string"},
          "doc_name": {"type": "string"}, "q": {"type": "string"}, "source_row": {"type": "string"}}, []),
    )
    return [{"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required,
                       "additionalProperties": False},
    }} for name, description, properties, required in definitions]


MODEL_EVIDENCE_READ_INSTRUCTION = (
    "До итогового ответа проверь выбранную карточку по показанным условиям и составу. "
    "Индекс/указатель не является полной карточкой. Если показанного содержания "
    "не хватает для сравнения или определения расхода, вызови read_norm_card "
    "с буквальным norm_key или norm_code уже показанной карточки. Для подбора поставки "
    "используй search_pricebook_resources, для цены выбранного кода — read_resource_price. "
    "Книга региона и периода закреплена приложением, сам другую не выбирай. "
    "Для коммерческого предложения или другого документа в выбранном датасете используй "
    "search_sources с target=documents и read_source. Нормы ищутся с target=norms. "
    "Для строки текущего вложения используй read_source с source_row — точным адресом показанного каталога. "
    "Можно вызвать несколько независимых чтений одновременно. Чтения выполняются "
    "в твоём текущем ходе до итоговых строк; при достаточном уже показанном содержании "
    "повторное чтение не требуется. Используй вызов инструмента, а не описание вызова "
    "в пояснении. Выполненный поиск/чтение подтверждается ответом инструмента. "
    "Цена ресурса не подтверждает соответствие изделия: его выбираешь и обосновываешь ты. "
    "Пустой объём группы исходника не заменяй единицей или объёмом варианта; "
    "сохрани пустой quantity и конкретно объясни пробел."
    + " " + model_lsr_resource_decision_instruction()
)


def shown_evidence_registry(chunks: Sequence[Any]) -> dict[str, Any]:
    """Retain literal shown bodies; share only verified views of one norm card.

    This is storage deduplication, not candidate selection. Document and price
    hits with different immutable identities always retain separate bodies.
    """
    records = []
    seen = set()
    for chunk in chunks:
        raw = chunk if isinstance(chunk, Mapping) else vars(chunk)
        meta = raw.get("meta") or {}
        if not isinstance(meta, Mapping):
            meta = {}
        identity = str(meta.get("global_evidence_id") or raw.get("global_evidence_id") or "")
        ref = str(meta.get("model_evidence_ref") or raw.get("model_evidence_ref") or raw.get("ref") or "")
        content = str(raw.get("content") or "")
        pointer = {name: meta.get(name, raw.get(name)) for name in (
            "norm_key", "norm_code", "source_ref", "edition", "base_type",
            "doc_id", "dataset_id", "resource_code", "pricebook",
        ) if meta.get(name, raw.get(name)) is not None}
        shared = str(meta.get("shared_evidence_ref") or raw.get("shared_evidence_ref")
                     or meta.get("shared_body_ref") or raw.get("shared_body_ref") or "")
        marker = "То же содержимое и источник, что у "
        suffix = "; см. показанный там текст."
        if content.startswith(marker) and content.endswith(suffix):
            shared = shared or content[len(marker):-len(suffix)]
            content = ""
        key = (identity, ref, content, shared, tuple((name, str(value)) for name, value in pointer.items()))
        if key in seen:
            continue
        seen.add(key)
        records.append({"evidence_ref": ref, "global_evidence_id": identity,
                        "doc_name": raw.get("doc_name", ""), **pointer,
                        "content": content, "_shared": shared,
                        "_namespace": str(meta.get("evidence_namespace") or "")})

    def same_source(left, right):
        fields = ("norm_key", "norm_code", "source_ref", "edition", "base_type",
                  "doc_id", "dataset_id", "resource_code", "pricebook")
        return all(str(left.get(name) or "") == str(right.get(name) or "") for name in fields)

    def resolve(record, visited):
        if record["content"]:
            return record["content"], ""
        target = record["_shared"]
        if not target:
            return "", "shown_body_unavailable"
        token = target.removeprefix("global_evidence_id=")
        candidates = [item for item in records if item is not record and (
            item["global_evidence_id"] == token or item["evidence_ref"] == token
        ) and same_source(record, item)]
        if record["_namespace"]:
            candidates = [item for item in candidates if item["_namespace"] == record["_namespace"]]
        bodies = set()
        for item in candidates:
            if id(item) not in visited:
                body, _ = resolve(item, {*visited, id(item)})
                if body:
                    bodies.add(body)
        if len(bodies) == 1:
            return bodies.pop(), ""
        return "", "shared_body_unavailable" if not bodies else "shared_body_ambiguous"

    def card_key(record):
        pointer = record.get("norm_key") or record.get("norm_code")
        if not pointer or not record.get("source_ref"):
            return None
        return tuple(str(record.get(name) or "") for name in (
            "norm_key", "norm_code", "source_ref", "edition", "base_type",
        ))

    def longest_verified_view(left, right):
        if left == right:
            return left
        shorter, longer = sorted((left, right), key=len)
        prefix = shorter[:-1].rstrip() if shorter.endswith("…") else shorter
        return longer if prefix and longer.startswith(prefix) else None

    rows = []
    groups = {}
    for record in records:
        content, missing = resolve(record, {id(record)})
        alias = {"evidence_ref": record["evidence_ref"], "global_evidence_id": record["global_evidence_id"]}
        key = card_key(record)
        target = None
        if key is not None and content:
            for candidate in groups.get(key, ()):
                body = longest_verified_view(candidate["content"], content)
                if body is not None:
                    candidate["content"] = body
                    target = candidate
                    break
        if target is None:
            target = {name: value for name, value in record.items() if not name.startswith("_")}
            target.update(content=content, body_available=bool(content), aliases=[],
                          evidence_refs=[], global_evidence_ids=[])
            if missing:
                target["body_missing"] = missing
                if record["_shared"]:
                    target["shared_body_ref"] = record["_shared"]
            rows.append(target)
            if key is not None and content:
                groups.setdefault(key, []).append(target)
        if alias not in target["aliases"]:
            target["aliases"].append(alias)
        for field, value in (("evidence_refs", alias["evidence_ref"]),
                             ("global_evidence_ids", alias["global_evidence_id"])):
            if value and value not in target[field]:
                target[field].append(value)
    return {"previously_shown_evidence_registry": rows,
            "body_delivery": "Literal previously shown bodies are included. Aliases share a body only for the same norm pointer, source and edition with an identical or verified prefix view. Missing bodies are explicit."}


def read_result_receipt(call: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Avoid duplicating full card bodies both in tool exchange and evidence."""
    return {"call": dict(call), "status": payload.get("status"),
            "missing": list(payload.get("missing") or []),
            "warnings": list(payload.get("warnings") or []),
            "trace": dict(payload.get("trace") or {}),
            "result_body": "Shown as cited evidence in this frame"}
