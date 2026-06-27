# PUBLICATION_CHECKLIST — public-ready gate

This repository can be shown publicly only after a separate publication gate.
Public visibility is not the same thing as open-source distribution: the
current license is source-available and does not include private datasets,
normative corpora, mail, project documents, generated indexes, or model caches.

## Required Checks

1. Secrets and private data:

```bash
make public-check
git status --short
```

2. Runtime/product health:

```bash
make ship-full-check
curl -fsS http://127.0.0.1:8050/api/version | python3 -m json.tool
curl -fsS http://127.0.0.1:8050/api/service-sources | python3 -m json.tool
```

3. Public access boundary, when `les.ovc.me` is exposed:

```bash
uv run python tools/runtime_smoke.py \
  --proxy-url https://les.ovc.me \
  --ui-url https://les.ovc.me \
  --qdrant-url http://127.0.0.1:6333 \
  --admin-key "$LES_ADMIN_KEY" \
  --expect-external-auth
```

## Must Not Be Published

- `.env`, credentials, API keys, passwords, JWT/admin secrets.
- `data/`, `storage/`, `RAG_Content/`, `logs/`, `artifacts/`, backups.
- Customer/project source files, mail archives, proprietary workbooks.
- Qdrant snapshots, SQLite runtime databases, generated indexes.
- Full texts of standards unless the repository has a clear right to publish them.

## Public README Requirements

- Say that LLM connects evidence and language, while code computes numbers.
- Say that final engineering/normcontrol decisions remain human decisions.
- Show service-source requirements for smeta/normcontrol.
- Link to `AGENTS.md`, `SKILL.md`, `ROADMAP_TO_V1.md`, `docs/MODULE_INDEX.md`,
  and `docs/RELEASE_LEDGER.md`.
- Do not include hostnames, keys, private paths, or private dataset names as
  required public setup.

## Current 0.24 Public-Ready Status

`0.24.0.0` is a local-field public candidate:

- SPDS doc-review baseline is in code and deployed locally.
- JSON/HTML/XLSX reports are available.
- `normalized_remarks` is exposed for future checklist/DOCX/PDF renderers.
- Service sources are visible through `/api/service-sources` and the Admin GUI.
- Full publication still requires owner approval and a final secret/data scrub.
