"""Read-only actions in the existing model turn; no professional decisions here."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from proxy.services.model_lsr_result_contract import model_lsr_resource_decision_instruction

def model_evidence_read_tool_schemas() -> list[dict[str, Any]]:
    definitions = (
        ("search_sources", "Search norms or explicitly selected documents. The query is executed verbatim.",
         {"q": {"type": "string"}, "target": {"type": "string", "enum": ["norms", "documents"]}}, ["q"]),
        ("read_norm_card", "Read a shown card by evidence_ref alone or norm_key; or request a full family-qualified norm_code alone. Never substitutes another norm.",
         {"evidence_ref": {"type": "string", "description": "Exact admitted inventory ref; use alone."},
          "norm_key": {"type": "string"}, "norm_code": {"type": "string"}}, []),
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
    "normative_card_complete означает полноту показанных состава и ресурсов типизированной карточки; "
    "это не подтверждение применимости и не доказательство показа всей техчасти. "
    "normative_composition_shown и normative_conditions_shown различают состав и условия; "
    "условия объекта и техчасти проверяй по их буквальным источникам, не выводи из признака полноты ресурсов. "
    "До итогового ответа проверь выбранную карточку по показанным условиям и составу. "
    "Индекс/указатель не является полной карточкой. Если показанного содержания "
    "достаточно для проверки применимости, это ещё не подтверждает расход ресурсов. "
    "Обзор ресурсов, даже N из N, перечисляет ресурсы, но не подтверждает их расходы. "
    "Если расход выбранной нормы не показан, прочитай её через read_norm_card. "
    "Для выбранного уже показанного кандидата с неполным составом или расходом "
    "выполни доступное read_norm_card до итоговых строк. "
    "Терминальный пробел допустим только после чтения без нужных данных либо фактической недоступности "
    "инструмента/остановки по бюджету или контексту; неизвестные условия объекта сохраняй отдельно. "
    "Отсутствие цены не означает отсутствие нормы; "
    "непрочитанный указатель не доказывает отсутствие подходящей нормы. Если содержания "
    "не хватает для сравнения или определения расхода, вызови read_norm_card "
    "с буквальным evidence_ref уже показанного указателя нормы отдельно, без norm_key/norm_code; "
    "либо с norm_key показанной карточки; либо с полным norm_code отдельно, даже если шифр не показан. Для подбора поставки "
    "используй search_pricebook_resources, для цены выбранного кода — read_resource_price. "
    "Книга региона и периода закреплена приложением, сам другую не выбирай. "
    "Для коммерческого предложения или другого документа в выбранном датасете используй "
    "search_sources с target=documents и read_source. Нормы ищутся с target=norms. "
    "Для строки текущего вложения используй read_source с source_row — точным адресом показанного каталога. "
    "Указатель нормы Qx.Hy передавай в read_norm_card.evidence_ref, а не в read_source.source_row. "
    "Можно вызвать несколько независимых чтений одновременно. Чтения выполняются "
    "в твоём текущем ходе до итоговых строк; при достаточном уже показанном содержании "
    "повторное чтение не требуется. Используй вызов инструмента, а не описание вызова "
    "в пояснении. Выполненный поиск/чтение подтверждается ответом инструмента. "
    "Цена ресурса не подтверждает соответствие изделия: его выбираешь и обосновываешь ты. "
    "Пустой объём группы исходника не заменяй единицей или объёмом варианта; "
    "сохрани пустой quantity и конкретно объясни пробел."
    + " " + model_lsr_resource_decision_instruction()
)


def model_evidence_read_instruction(*, artifact_kind: str = "") -> str:
    """Scope read guidance only by the model's explicit document declaration."""
    if artifact_kind != "vor":
        return MODEL_EVIDENCE_READ_INSTRUCTION
    return (
        "Для ВОР проверяй исходные работы, их связи, единицы и объёмы по показанному исходнику. "
        "Для строки текущего вложения используй read_source с source_row — точным буквальным адресом "
        "из полного манифеста/каталога. Для документов в явно выбранных датасетах доступны "
        "search_sources с target=documents и read_source с показанным doc_id либо dataset_id/doc_name. "
        "Внешний поиск и дополнительные чтения нужны только при недостаточном уже показанном основании; "
        "при достаточном содержании повторное чтение не требуется. Все показанные evidence и инструменты "
        "остаются доступны; необходимость и запросы определяешь ты. "
        "Достаточный исходник не требует поиска норм и цен: нормы, расценки, цены ресурсов и НР/СП "
        "не обязательны для ВОР. Их отсутствие не является пробелом ВОР. "
        "В open_gap укажи только конкретный нерешённый вопрос об исходных работах, их связях, единицах "
        "или объёмах; подтверждённое пояснение сохраняй в coverage. Не объявляй недостающими данные, "
        "которые доступны через чтение показанного источника. Неизвестный quantity сохраняй как null, "
        "явный исходный ноль — как 0; не придумывай объём вместо отсутствующего. "
        "Если ты добровольно выбираешь норму как обоснование ВОР, проверь её применимость по целой "
        "карточке, составу и буквальным условиям. Индекс/указатель не является полной карточкой; "
        "недостающий состав и расход прочитай через read_norm_card с буквальным evidence_ref "
        "уже показанного указателя отдельно либо с показанным norm_key; либо с полным norm_code отдельно, даже если шифр не показан. "
        "Полнота ресурсов не доказывает применимость или показ всей техчасти. Признаки action_match, "
        "object_match, condition_match, unit_compatible, composition_covers заполняй значениями "
        "yes/no/unknown; пояснение пиши в coverage, а не вместо признака. "
        "Цитируй только фактически показанное основание в evidence_refs. Указатель нормы Qx.Hy "
        "передавай в read_norm_card.evidence_ref, а не в read_source.source_row. "
        "Используй вызов инструмента, а не описание вызова: выполненное чтение подтверждается его ответом. "
        "Можно вызвать несколько независимых чтений одновременно в текущем ходе до итоговых строк."
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
            "result_body": "Index/full bodies are marked in this frame."}
