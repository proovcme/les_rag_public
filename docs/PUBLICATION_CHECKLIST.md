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

3. Public access boundary, when a public host is exposed:

```bash
uv run python tools/runtime_smoke.py \
  --proxy-url https://<public-host> \
  --ui-url https://<public-host> \
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
- Link to public-facing docs first: `docs/index.md`, `docs/public/overview.md`,
  `docs/public/demo-workflows.md`, `docs/public/privacy-and-data-boundaries.md`,
  `docs/public/windows-troubleshooting.md`, `docs/public/developer-guide.md`,
  and `docs/public/smeta-expert-review.md`.
- Keep internal runbooks available for developers, but do not make private hostnames,
  keys, private paths, or private dataset names part of required public setup.
- If GitHub Pages is enabled, use `docs/index.md` as the curated entry point.

## Current 0.28.1 public-release gate

- Public README, Windows troubleshooting and developer guide are required files.
- `LES-Setup.exe` must prove a clean offline first launch using only its bundled runtime.
- Missing Ollama/FreeToken/Lemonade/Qdrant must remain visible warnings, not installer failures.
- The exact source commit must pass `make verify`, `make test`, `make public-check`, Tauri checks,
  and installed Windows smoke before `main` and the GitHub Release tag are updated.
- Release assets are the verified installer, its SHA-256 and `latest.json`; no runtime/user data.
