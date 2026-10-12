"""Exact SQL resource addresses around the existing calculation dedupe rule."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Mapping

from proxy.smeta_core.norm_revision import IDENTITY_FIELDS, IDENTITY_SCHEMA


def labor_tariff_code(name: Any) -> str | None:
    match = re.search(r'разряд\D*(\d)[.,](\d)', str(name or '').lower())
    return f'1-100-{match.group(1)}{match.group(2)}' if match else None


def normalise_resource(resource: Mapping[str, Any]) -> dict[str, Any]:
    """Shape a SQL row exactly as the existing reader, including tariff fallback."""
    row = dict(resource)
    if 'resource_name' not in row:
        return deepcopy(row)
    result = dict(kind=row.get('kind'), name=row.get('resource_name') or '',
        unit=row.get('resource_unit') or '', per_unit=row.get('per_unit'),
        source_code=row.get('resource_code') or '')
    code = row.get('resource_code')
    if not code and row.get('kind') == 'labor':
        code = labor_tariff_code(row.get('resource_name'))
    if code:
        result['code'] = code
    if row.get('price') not in (None, ''):
        result['price'] = row['price']
    if row.get('row_id') is not None:
        result['source_resource_ids'] = [str(int(row['row_id']))]
    return result


def _text(value: Any) -> str:
    return ' '.join(str(value or '').replace('\xa0', ' ').split()).casefold()


def _number(value: Any) -> str:
    if value in (None, ''):
        return ''
    try:
        parsed = float(str(value).replace('\xa0', '').replace(' ', '').replace(',', '.'))
    except (TypeError, ValueError):
        parsed = 0.0
    return format(parsed, '.12g')


def resource_dedupe_key(resource: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    code, name = _text(resource.get('code')), _text(resource.get('name'))
    return (_text(resource.get('kind')), 'code' if code else 'name', code or name,
        _text(resource.get('unit')), f"{_number(resource.get('per_unit'))}|{_number(resource.get('price'))}")


def dedupe_resources(resources: list[dict[str, Any]], *, normative_identity: Mapping[str, Any] | None = None) -> tuple[list[dict[str, Any]], int]:
    groups: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for source in resources:
        key = resource_dedupe_key(source)
        if key not in groups:
            groups[key] = deepcopy(source)
        target = groups[key]
        ids = [str(int(item)) for item in (*target.get('source_resource_ids', []), *source.get('source_resource_ids', []))]
        if ids:
            target['source_resource_ids'] = sorted(set(ids), key=int)
        target.pop('source_resource_group_id', None)
    pinned = normative_identity is not None and normative_identity.get('schema') == IDENTITY_SCHEMA and all(normative_identity.get(field) for field in IDENTITY_FIELDS)
    for target in groups.values():
        ids = target.get('source_resource_ids') or []
        if pinned and len(ids) > 1:
            payload = dict(normative_identity={field: normative_identity[field] for field in IDENTITY_FIELDS}, source_resource_ids=ids)
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
            target['source_resource_group_id'] = 'group:' + digest
    return list(groups.values()), len(resources) - len(groups)


def resource_selector(resource: Mapping[str, Any]) -> str | None:
    ids = resource.get('source_resource_ids') or []
    if len(ids) == 1:
        return 'row:' + str(ids[0])
    return resource.get('source_resource_group_id') if len(ids) > 1 else None
