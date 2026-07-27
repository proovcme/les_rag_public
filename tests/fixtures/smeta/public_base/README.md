# Public synthetic smeta base

Licensing-safe fixture pack for clean clones. Not FSNB.

- `norms.json` — source of truth
- rebuild: `uv run python -m tools.build_smeta_public_fixture`
- pytest auto-wires it via `tests/conftest.py` when `data/smeta_base/les_smeta_base.sqlite` is absent

Integrity intentionally fails `missing_provenance` on resources so navigation is trusted and pricing stays quarantined.
