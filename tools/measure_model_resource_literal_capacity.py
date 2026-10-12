"""Offline byte/governor-token comparison; never writes source evidence or calls a model.

Run with ``python -m tools.measure_model_resource_literal_capacity --artifact <saved-job.json>``.
Token counts are the harness's conservative chars/2 estimates, not provider tokenization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from proxy.services.context_governor_service import conservative_token_estimate
from proxy.services.model_rag_grouped_evidence_service import normative_card_identity, share_registry_catalogs
from proxy.services.model_resource_literal_service import render_resource_literals, resource_jsonl
from proxy.services.model_resource_reference_service import resource_slot_records, shown_resource_record


def _cards(node):
    if isinstance(node, dict):
        if isinstance(node.get("content"), str) and isinstance(node.get("meta"), dict):
            if isinstance(node["meta"].get("resources"), list) and node["meta"]["resources"]:
                yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _cards(value)
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                yield from _cards(value)


def _cost(text):
    return {"bytes_utf8": len(text.encode("utf-8")), "governor_tokens": conservative_token_estimate(text)}


def measure(label, cards):
    seen, selected, projected, metadata = set(), [], [], {}
    body_old, body_new, resource_old, resource_new = [], [], [], []
    for card in cards:
        body, meta = card["content"], card["meta"]
        rows = resource_slot_records(meta)
        old, new = resource_jsonl(rows), render_resource_literals(rows)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        identity = (digest, normative_card_identity(meta))
        if identity in seen or not old or body.count(old) != 1:
            continue
        seen.add(identity)
        candidate = body.replace(old, new, 1)
        proof_meta = {**meta, "exact_card_read": True, "resources": rows}
        for slot, row in enumerate(rows, 1):
            original = {key: value for key, value in row.items() if key != "resource_slot"}
            if resource_jsonl([shown_resource_record(proof_meta, candidate, slot)]) != resource_jsonl([original]):
                raise AssertionError("nonexact projected resource proof")
        ref = f"Q{len(selected) + 1}.H1"
        selected.append({"evidence_ref": ref, "content": body, "source_ref": meta.get("source_ref", "")})
        projected.append({**selected[-1], "content": candidate})
        metadata[ref] = {**meta, "resources": rows}
        body_old.append(body)
        body_new.append(candidate)
        resource_old.append(old)
        resource_new.append(new)
    serialize = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    result = {"label": label, "unique_full_cards": len(selected),
        "resource_records": sum(len(meta["resources"]) for meta in metadata.values()),
        "resources_jsonl": _cost("\n".join(resource_old)), "resources_table": _cost("\n".join(resource_new)),
        "whole_cards_jsonl": _cost("\n".join(body_old)), "whole_cards_table": _cost("\n".join(body_new)),
        "shared_replay_jsonl": _cost(serialize(share_registry_catalogs(selected, metadata))),
        "shared_replay_table": _cost(serialize(share_registry_catalogs(projected, metadata)))}
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", action="append", type=Path, default=[])
    parser.add_argument("--trace", type=Path, help="Saved final trace; only existing read registry identities are measured")
    args = parser.parse_args()
    rows = [{"kind": "material", "code": f"literal-{index}", "name": "Full literal resource Ω",
             "unit": "m", "per_unit": 0 if index == 0 else index / 10,
             "price": None, "source_ref": f"document#guid=immutable-{index}"} for index in range(24)]
    meta = {"resources": rows, "exact_card_read": True, "resources_complete": True,
            "resources_returned": len(rows), "source_ref": "document#norm=immutable"}
    synthetic = [{"content": "Whole source card\n" + resource_jsonl(resource_slot_records(meta)), "meta": meta}]
    print(json.dumps(measure("synthetic-24", synthetic), ensure_ascii=False))
    saved_cards = []
    for path in args.artifact:
        cards = list(_cards(json.loads(path.read_text(encoding="utf-8"))))
        saved_cards.extend(cards)
        print(json.dumps(measure(path.name, cards), ensure_ascii=False))
    if args.trace:
        trace = json.loads(args.trace.read_text(encoding="utf-8")).get("retrieval_trace", {})
        reads = [call for call in trace.get("context_governor", {}).get("calls", [])
                 if call.get("purpose") == "sheet_pass_evidence_read"]
        by_id = {str(card.get("global_evidence_id") or card["meta"].get("global_evidence_id") or ""): card
                 for card in saved_cards}
        for index, call in enumerate(reads, 1):
            refs = [row["global_evidence_id"] for section in call.get("sections", [])
                    for obj in section.get("objects", []) if isinstance(obj.get("payload"), dict)
                    for row in obj["payload"].get("previously_shown_evidence_registry", [])]
            if refs and all(ref in by_id for ref in refs):
                result = measure(f"saved-read-{index}-registry-resource-projection", [by_id[ref] for ref in refs])
                result.update(saved_registry_refs=len(refs), saved_packet_included_tokens=call.get("included_tokens"),
                              scope="resource/card projection only; original packet and native exchanges unchanged")
                print(json.dumps(result, ensure_ascii=False))
        if len(reads) < 2:
            print(json.dumps({"label": "second-required-replay", "status": "N/A",
                "reason": "No second governed packet or native messages saved in the trace; cannot prove the blocked packet fits."}))


if __name__ == "__main__":
    main()
