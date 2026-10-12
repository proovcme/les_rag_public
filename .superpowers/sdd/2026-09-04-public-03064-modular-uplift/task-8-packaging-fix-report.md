# Task 8 report — exact storage-code packaging fix

## Status

Completed as the narrow bootstrap-blocking fix on
`codex/public-03064-modular-uplift`, based on `8a0312b0`. The source contract is
`0.30.80 / build 720 / desktop 5.1.720`. No installed runtime, service, process,
Qdrant, SQLite, corpus, `storage` or `RAG_Content` path was opened or changed.

## Root cause and scope audit

Task 2 correctly added a deny-by-segment guard, but it evaluated `storage` before
the existing `proxy/` application prefix. This dropped the tracked Python imports
needed by bootstrap:

- `proxy/storage/__init__.py`
- `proxy/storage/file_storage.py`

`git ls-files` audited against every forbidden segment found no other affected
tracked paths. The fix is an exact-file exception, not a `proxy/storage/` or
`storage/` subtree exception.

## RED → GREEN evidence

The regression was added first in `tests/test_extension_package_boundaries.py`.
It uses the actual `iter_files()` and Windows `stage_runtime()` path, then compares
the bytes of both staged files to their tracked sources. It also exercises each
Windows updater validator and rejects nontrusted storage payloads.

```text
RED:   3 failed, 17 passed in 1.01s
GREEN: 179 passed in 11.59s
```

GREEN command:

```powershell
uv run pytest -q tests/test_extension_package_boundaries.py tests/test_tauri_desktop.py tests/test_vps_patch.py tests/test_update_service.py tests/test_windows_application_update.py --basetemp=.test-tmp/task8-packaging-green
```

The rejection matrix includes `proxy/storage/anything.db`, `.env`, arbitrary JSON
and Python payloads, plus `extensions/storage/example.py`; existing persistent
root, absolute, traversal, cache and plugin tests remain in the focused suite.

## Files and documentation

The identical exact-file allowlist is applied in:

- `tools/build_tauri_app.py`
- `tools/vps_patch.py`
- `tools/vps_patch_apply.py`
- `proxy/services/update_service.py`

Version surfaces, package/update documentation, module index, release ledger,
test inventory, session log, Plan A constraints and Task 8's expected receipt
version were synchronized. The final generated-map command was
`uv run --frozen python tools/code_runtime_map.py`; it regenerated
`docs/CODE_RUNTIME_MAP.md` and its JSON inventory with 1059 tracked Python files,
325717 lines, 327 routes and 0 parse warnings.

## Follow-up

The aggregate Task 8 disposable-stage/double-bootstrap receipt remains a separate
acceptance step and must use `0.30.80/build720`.
