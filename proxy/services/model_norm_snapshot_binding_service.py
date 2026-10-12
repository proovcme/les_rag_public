"""Application-owned binding to a cited normative generation, never applicability."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from proxy.services.lsr_norm_quality_gate_service import qualified_norm_key

_SHA256 = re.compile(r'[0-9a-f]{64}')


def _digest(value) -> str:
    text = str(value or '').lower()
    return text if _SHA256.fullmatch(text) else ''


def cited_norm_snapshot_stamp(
    row: Mapping,
    bindings: Mapping[str, str],
    metadata_by_identity: Mapping[str, Sequence[Mapping]],
    *,
    prior_check: Mapping | None = None,
) -> dict:
    """Pin only full item identities and actual SHA values from issued evidence.

    A prior check is admitted only by the application's trusted replay caller.
    Missing evidence remains missing; no family, hash or source is invented.
    """
    key = qualified_norm_key(row.get('norm_code'))
    if not key:
        return {}
    snapshots: set[tuple[str, str]] = set()
    for identity in set(bindings.values()):
        for meta in metadata_by_identity.get(identity, ()):
            if qualified_norm_key(meta.get('norm_code')) != key:
                continue
            observed_key = qualified_norm_key(meta.get('norm_key') or meta.get('norm_code'))
            digest = _digest(meta.get('normative_base_sha256'))
            if observed_key != key or not digest:
                continue
            snapshots.add((observed_key, digest))
    prior = prior_check if isinstance(prior_check, Mapping) else {}
    prior_key = qualified_norm_key(prior.get('norm_key'))
    prior_digest = _digest(prior.get('normative_base_sha256'))
    if prior_key == key and prior_digest:
        snapshots.add((prior_key, prior_digest))
    if len(snapshots) > 1 or prior.get('normative_snapshot_conflict') is True:
        return {'norm_key': key, 'normative_snapshot_conflict': True}
    if len(snapshots) == 1:
        observed_key, digest = next(iter(snapshots))
        return {'norm_key': observed_key, 'normative_base_sha256': digest}
    return {}
