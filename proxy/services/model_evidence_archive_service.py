"""Immutable, task-local source archive separate from a model's working frame.

No retrieval, professional ranking, summarization or source reopening happens
here. The durable job still owns storage; this view is rebuilt from its exact
records and serves literal rereads through the existing read_source tool.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping, Sequence

from proxy.services.model_rag_grouped_evidence_service import (
    ModelReadReplay, prepare_model_read_replay,
)


class EvidenceArchiveConflict(ValueError):
    pass


class ModelEvidenceArchive:
    def __init__(self, chunks: Sequence[Any]):
        records = [deepcopy(dict(c) if isinstance(c, Mapping) else vars(c)) for c in chunks]
        self._records = records
        self.archive_id = 'evidence:' + hashlib.sha256(json.dumps(
            records, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode('utf-8')).hexdigest()

    def matches(self, chunks: Sequence[Any]) -> bool:
        return self._records == [dict(c) if isinstance(c, Mapping) else vars(c) for c in chunks]

    @staticmethod
    def reference(record):
        meta = record.get('meta') or {}
        return str(meta.get('model_evidence_ref') or record.get('model_evidence_ref') or '')

    def manifest(self):
        return {'evidence_archive': {'archive_id': self.archive_id, 'record_count': len(self._records),
            'reader': 'read_source', 'inventory_arguments': {
                'evidence_archive_id': self.archive_id, 'evidence_offset': 0},
            'body_arguments': {'evidence_archive_id': self.archive_id, 'evidence_ref': 'literal inventory reference'},
            'visibility': 'Archived bodies not included in this frame remain available unchanged. '
                          'Absence from working context is not missing data. Index pages preserve source order.'}}

    def page(self, offset: int):
        if type(offset) is not int or offset < 0 or (offset >= len(self._records) and offset != 0):
            raise EvidenceArchiveConflict('evidence_offset is outside this archive')
        page = []
        for record in self._records[offset:offset + 12]:
            meta = record.get('meta') or {}
            page.append({'evidence_ref': self.reference(record), 'doc_name': record.get('doc_name'),
                **{name: meta.get(name, record.get(name)) for name in (
                    'global_evidence_id', 'source_ref', 'source_sha256', 'norm_code', 'norm_key',
                    'normative_base_sha256', 'dataset_id', 'doc_id', 'resource_code', 'pricebook_sha256')
                   if meta.get(name, record.get(name)) is not None}})
        next_offset = offset + len(page)
        return {'archive_id': self.archive_id, 'record_count': len(self._records), 'offset': offset,
                'records': page, 'next_offset': next_offset if next_offset < len(self._records) else None}

    def read(self, reference: str):
        if not isinstance(reference, str) or not reference:
            raise EvidenceArchiveConflict('evidence_ref must be a nonempty literal reference')
        matches = [r for r in self._records if self.reference(r) == reference]
        distinct = {json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(',', ':')): r for r in matches}
        if len(distinct) != 1:
            raise EvidenceArchiveConflict('evidence_ref must identify exactly one immutable archive record')
        return deepcopy(next(iter(distinct.values())))

    def working_replay(self, *, current_refs: Sequence[str]) -> ModelReadReplay:
        wanted = set(current_refs)
        variants: dict[str, set[str]] = {}
        for record in self._records:
            variants.setdefault(self.reference(record), set()).add(json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        current = []
        for record in self._records:
            meta = record.get('meta') or {}
            ref = self.reference(record)
            # An explicitly requested read that has not been delivered must not
            # become optional merely because an earlier attempt ran out of space.
            pending_exact = (meta.get('model_delivery_status') == 'prepared'
                and meta.get('model_read_tool') in {'read_norm_card', 'read_source', 'read_resource_price'})
            fresh_discovery = (meta.get('model_inventory_delivery_status') == 'prepared'
                and meta.get('model_read_tool') in {'search_sources', 'search_pricebook_resources'})
            # A legacy record without a usable unique alias cannot be paged out
            # under a promise that the model can reread it by that alias.
            rereadable = bool(ref) and len(variants[ref]) == 1
            if ref in wanted or meta.get('global_evidence_id') in wanted or pending_exact or fresh_discovery or not rereadable:
                current.append(record)
                if ref and not fresh_discovery:
                    wanted.add(ref)
        active = prepare_model_read_replay(current, required_refs=list(wanted))
        # Historical cardinality must not create one remote token-count request
        # per old body. No historical card is selected for unsolicited replay;
        # the model can page/reread any record itself. Fresh discovery keeps the
        # existing whole-query inventory/body admission contract.
        return ModelReadReplay([self.manifest(), *active.required], active.optional,
            [self.reference(r) for r in self._records if self.reference(r)], active.exact_body_refs,
            active.optional_body_refs, active.required_inventory_refs, active.optional_inventory_refs)
