# Security Policy

Л.Е.С. is a local-first construction evidence harness. Treat project files,
mailboxes, estimates, indexes, logs, and runtime databases as private data.

## Supported Branch

The public-ready branch is expected to track the current local release line:

| Line | Status |
|---|---|
| `0.24.x` | active local field build |
| older lines | best-effort only |

## Reporting

Do not open public issues with secrets, project documents, mail excerpts, or
customer data. Report security problems privately to the repository owner.

Include:

- affected version from `GET /api/version`;
- whether the issue affects local-only, ZeroTier, or public reverse-proxy access;
- minimal reproduction without private documents;
- logs with secrets and document text redacted.

## Public Repository Rules

Before making a repository public, run the publication checklist:

```bash
make public-check
```

Manual review is still required. The check is a guardrail, not a legal or
security certification.

Never commit:

- `.env`, API keys, admin passwords, JWT secrets, mail credentials;
- `data/`, `storage/`, `RAG_Content/`, `logs/`, `artifacts/`;
- private project PDFs/DOCX/XLSX/mail archives;
- Qdrant/SQLite indexes or backups;
- generated model caches or proprietary normative corpora.

## Runtime Exposure

External access must require authentication unless the client is explicitly
inside the trusted private network. Public clients without a key must receive
`401` for API calls. Keep `TRUSTED_PROXY_NETWORKS` narrow and explicit.
