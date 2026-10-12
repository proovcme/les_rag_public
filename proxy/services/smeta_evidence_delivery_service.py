"""Observe source -> packed -> final-message delivery; never select a norm."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def card_delivery_metadata(card: Mapping[str, Any], body: str,
                           resources: Sequence[tuple[Mapping[str, Any], str]],
                           group_fragments: Sequence[tuple[Mapping[str, Any], str]] = ()) -> dict:
    """Offsets avoid duplicating normative text inside chunk metadata/model input."""
    def spans(parts, start, end):
        result = []
        cursor = start
        for identity, text in parts:
            offset = (cursor if start >= 0 and cursor + len(text) <= end
                      and body.startswith(text, cursor) else -1)
            result.append({**identity, 'start': offset, 'chars': len(text), 'sha256': _sha(text)})
            cursor += len(text) + 2  # The renderer joins items with '; '.
        return result

    full = isinstance(card.get('resources'), list)
    work_start = body.find('Состав работы: ')
    resource_start = body.find('Ресурсы нормы (' if full else 'Машины и материалы (')
    work_body = work_start + len('Состав работы: ') if work_start >= 0 else -1
    work_end = resource_start if resource_start >= 0 else len(body)
    resource_body = body.find('): ', resource_start) + 3 if resource_start >= 0 else -1
    manifest = {
        'body_sha256': _sha(body),
        'work_steps': spans([({'index': i}, str(step))
                            for i, step in enumerate(card.get('work_steps') or [])
                            if str(step).strip()], work_body, work_end),
        'resources': spans([({'index': i, 'row_id': row.get('row_id'),
                              'code': row.get('code'), 'kind': row.get('kind')}, text)
                            for i, (row, text) in enumerate(resources)], resource_body, len(body)),
        'database_resource_count': card.get('resource_count'),
        'resource_groups': [
            {'source_resource_group_id': item.get('source_resource_group_id'),
             'source_resource_ids': [str(v) for v in item.get('source_resource_ids') or []],
             'start': body.find(text), 'chars': len(text), 'sha256': _sha(text)}
            for item, text in group_fragments
        ],
    }
    return {
        'smeta_delivery_manifest': manifest,
        **({'normative_identity': dict(card['normative_identity'])}
           if isinstance(card.get('normative_identity'), Mapping) else {}),
        **({'smeta_full_read': True,
            'smeta_resources_complete': card.get('resources_complete') is True,
            'smeta_resource_rows': len(card['resources'])} if full else {}),
    }


_CARD = re.compile(r'\[(Q\d+\.H\d+) \|[^\]]*\]:?[ \t]*(.*?)(?=\n\[Q\d+\.H\d+ \||\n\[Поисковый запрос|\Z)', re.DOTALL)
_ALIAS = re.compile(r'^\s*См\. (Q\d+\.H\d+)')
_SECTION = re.compile(r'(?m)^(Состав работ(?:ы)?:|Машины и материалы \(|Ресурсы нормы \(|Практика раздела:|Применение:|Варианты таблицы )')


def resource_delivery_proofs(packet_text: str, chunks: Sequence[Any]) -> dict[str, dict]:
    """Prove exact resource fragments in actual sent bodies, never in source alone."""
    packet_sha = _sha(str(packet_text))
    bodies = {m[1]: m[2].strip() for m in _CARD.finditer(str(packet_text))}
    sources = {str((getattr(c, 'meta', {}) or {}).get('model_evidence_ref') or '').upper(): c for c in chunks}
    result = {}
    for ref, c in sources.items():
        meta = getattr(c, 'meta', {}) or {}
        pin = meta.get('normative_identity')
        if not isinstance(pin, Mapping) or not ref or ref not in bodies:
            continue
        target = ref
        seen = set()
        while target in bodies and _ALIAS.match(bodies[target]):
            if target in seen:
                target = ''
                break
            seen.add(target)
            target = _ALIAS.match(bodies[target])[1]
        original = sources.get(target)
        if original is None or target not in bodies:
            continue
        original_meta = getattr(original, 'meta', {}) or {}
        if original_meta.get('normative_identity') != pin:
            continue
        source = str(getattr(original, 'content', '') or '')
        manifest = original_meta.get('smeta_delivery_manifest') or {}
        if manifest.get('body_sha256') != _sha(source):
            continue
        # The final card matcher may include the following request prose when
        # this is the last card. Only its contiguous source prefix is evidence;
        # a quotation later in the prompt cannot repair an omitted resource tail.
        actual = bodies[target]
        prefix_length = 0
        for expected_char, actual_char in zip(source, actual):
            if expected_char != actual_char:
                break
            prefix_length += 1

        def fragment(item):
            start, size = item.get('start', -1), item.get('chars', 0)
            if not isinstance(start, int) or not isinstance(size, int) or start < 0 or size <= 0:
                return None
            text = source[start:start + size]
            return text if start + size <= prefix_length and _sha(text) == item.get('sha256') else None

        rows = []
        for item in manifest.get('resources') or []:
            if item.get('row_id') is not None and fragment(item):
                rows.append(dict(source_resource_id=str(item['row_id']), ref=ref,
                                 sha256=item['sha256'], packet_sha256=packet_sha))
        delivered_ids = {r['source_resource_id'] for r in rows}
        groups = []
        for item in manifest.get('resource_groups') or []:
            members = [str(v) for v in item.get('source_resource_ids') or []]
            address = str(item.get('source_resource_group_id') or '')
            if (members and set(members).issubset(delivered_ids)
                and re.fullmatch(r'group:[0-9a-fA-F]{64}', address) and fragment(item)):
                groups.append(dict(source_resource_group_id=address, source_resource_ids=members,
                                   ref=ref, sha256=item['sha256'], packet_sha256=packet_sha))
        result[ref] = dict(normative_identity=dict(pin), rows=rows, groups=groups)
    return result


def smeta_evidence_delivery_trace(query_hits: Sequence, packed_chunks: Sequence,
                                 packet_text: str) -> dict:
    """Count exact source content in final evidence bodies, not query/header receipts.

    Older saved previews lack item manifests: their sections are still checked, but
    item counts and database completeness remain unknown. Aliases require their
    original body and the same source/edition; a query mentioning a code is no proof.
    """
    sources = {f'Q{qi}.H{hi}': hit for qi, (_q, hits) in enumerate(query_hits, 1)
               for hi, hit in enumerate(hits, 1)}
    packed = {str(h.meta.get('model_evidence_ref')): h for h in packed_chunks}
    bodies = {}
    for match in _CARD.finditer(str(packet_text or '')):
        bodies.setdefault(match[1], match[2].strip())

    def same_source(a, b):
        return all(getattr(a, key, None) == getattr(b, key, None)
                   for key in ('content', 'doc_id', 'doc_name', 'meta'))

    def delivered(ref):
        body = bodies.get(ref, '')
        alias = _ALIAS.match(body)
        target = alias[1] if alias else ref
        if (target not in sources or ref not in sources or target not in bodies
                or _ALIAS.match(bodies[target]) or not same_source(sources[ref], sources[target])
                or target not in packed):
            return ''
        # Only the actual packed body prefix counts. Text in an appended question,
        # source map or another section cannot repair a missing resource tail.
        body = bodies[target]
        expected = str(packed[target].content)
        end = 0
        for a, b in zip(body, expected):
            if a != b:
                break
            end += 1
        return body[:end]

    cards = []
    for ref, hit in sources.items():
        meta = getattr(hit, 'meta', {}) or {}
        if not meta.get('norm_code'):
            continue
        source = str(hit.content).strip()
        pack = str(packed[ref].content) if ref in packed else ''
        final = delivered(ref)
        manifest = meta.get('smeta_delivery_manifest') or {}
        valid = manifest.get('body_sha256') == _sha(source)
        row = {key: meta.get(key) for key in ('norm_id', 'norm_code', 'edition', 'source_ref')}
        row.update(ref=ref, full_read=meta.get('smeta_full_read') is True,
                   database_resource_count=manifest.get('database_resource_count') if valid else None,
                   body_packed_complete=bool(source) and source in pack,
                   body_delivered_complete=bool(source) and source in final,
                   item_manifest_valid=valid, sections=[])
        boundaries = list(_SECTION.finditer(source))
        for i, match in enumerate(boundaries):
            end = boundaries[i + 1].start() if i + 1 < len(boundaries) else len(source)
            text = source[match.start():end].strip()
            row['sections'].append({'name': match[1], 'chars': len(text),
                                    'packed_complete': text in pack,
                                    'delivered_complete': text in final})
        for name in ('work_steps', 'resources'):
            items = manifest.get(name, []) if valid else []
            counts = {'source_items': len(items) if valid else None,
                      'rendered_items': 0 if valid else None,
                      'packed_items': 0 if valid else None,
                      'delivered_items': 0 if valid else None,
                      'delivered_row_ids': []}
            cursors = {'packed': 0, 'delivered': 0}
            for item in items:
                start, size = item['start'], item['chars']
                text = source[start:start + size] if start >= 0 else ''
                if not text or _sha(text) != item['sha256']:
                    continue
                counts['rendered_items'] += 1
                for stage, content in (('packed', pack), ('delivered', final)):
                    offset = content.find(text, cursors[stage])
                    if offset >= 0:
                        counts[stage + '_items'] += 1
                        cursors[stage] = offset + len(text)
                        if stage == 'delivered' and item.get('row_id') is not None:
                            counts['delivered_row_ids'].append(item['row_id'])
            row[name] = counts
        row['resource_set_complete'] = (
            valid and meta.get('smeta_resources_complete') is True
            and row['body_delivered_complete']
            and row['resources']['delivered_items'] == manifest.get('database_resource_count')
        )
        cards.append(row)
    return {'schema': 'les.smeta.evidence_delivery.v1', 'cards': cards,
            'cards_total': len(cards),
            'bodies_packed_complete': sum(c['body_packed_complete'] for c in cards),
            'bodies_delivered_complete': sum(c['body_delivered_complete'] for c in cards),
            'resource_sets_complete': sum(c['resource_set_complete'] for c in cards)}
