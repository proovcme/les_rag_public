---
name: agnostis
description: Use when working on the АРТЕЛЬ repository, Revit family development platform, BIM/RFA catalog, backend/OpenAPI, GitHub Pages UI prototype, OpenRouter orchestration, or АРТЕЛЬ-to-LES RAG integration.
---

# АРТЕЛЬ Operator Skill

## Workspace

Use `/Users/ovc/Projects/LES_v2/products/artel` as the АРТЕЛЬ product root inside LES.

The legacy standalone repository still exists at `/Users/ovc/Projects/Agnosis`.
Treat LES `products/artel` as the current boxed source of truth unless the user
explicitly asks to update the standalone mirror.

Primary public surfaces:

- GitHub mirror: `https://github.com/proovcme/Agnostis`
- GitHub Pages UI mirror: `https://proovcme.github.io/Agnostis/`
- Backend skeleton: `backend/Agnostis.Api`
- OpenAPI contract: `openapi/agnostis-mvp.yaml`

Related runtime:

- LES root: `/Users/ovc/Projects/LES_v2`
- LES local proxy: `http://127.0.0.1:8050`
- LES ZeroTier URL from Legion: `http://10.195.146.98:8050`
- Windows/Revit/.NET test host: SSH alias `legion`

When changing or diagnosing LES itself, also use the `les` skill.

## Product Boundaries

АРТЕЛЬ owns:

- family development tasks;
- source files, templates and FOP/shared parameter profiles;
- AI-generated family specifications;
- Revit add-in workflow;
- OpenRouter orchestration;
- validation reports, acceptance and publishing;
- internal family catalog.

LES owns:

- local RAG and retrieval;
- Qdrant/SQLite indexes;
- CAD/BIM canonical JSON ingestion;
- object-level CAD/BIM graph context;
- local model runtime;
- dataset routing and validation.

Core rule: Revit add-in calls АРТЕЛЬ; АРТЕЛЬ calls LES/OpenRouter. Revit should not call LES or OpenRouter directly in MVP.

## First Reads

Before non-trivial work, inspect the relevant files:

```bash
cd /Users/ovc/Projects/LES_v2/products/artel
sed -n '1,220p' README.md
sed -n '1,220p' docs/about.md
sed -n '1,220p' docs/technical-stack.md
sed -n '1,240p' docs/les-integration.md
sed -n '1,220p' docs/bim-rfa-rag.md
```

For backend/API work, also read:

```bash
sed -n '1,240p' backend/README.md
sed -n '1,260p' backend/Agnostis.Api/Program.cs
sed -n '1,260p' openapi/agnostis-mvp.yaml
```

## BIM RFA RAG Position

Treat the model as secondary. The durable advantage is data quality:

- accepted RFA metadata;
- task specifications;
- FOP/shared parameter patterns;
- templates;
- validation reports;
- catalog cards;
- RFA/CAD/BIM-derived canonical JSON;
- known failure patterns and acceptance checklists.

The product loop is:

```text
task -> specification -> Revit family -> validation -> catalog -> LES-indexed knowledge -> better next task
```

## LES Handshake

Before relying on LES, check health:

```bash
cd /Users/ovc/Projects/LES_v2
curl -fsS http://127.0.0.1:8050/api/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8080/api/health | python3 -m json.tool
launchctl list | grep -E 'les|sovushka|qdrant|mlx'
```

АРТЕЛЬ MVP endpoints for LES:

- `GET /api/integrations/les/status` -> LES `/api/health`
- `POST /api/tasks/{taskId}/rag-context` -> LES `/api/search`

`rag-context` uses LES retrieval-only search and should not trigger local model generation. Use LES `/api/chat` only as a separate optional summarization step.

Backend LES config:

```text
LES_BASE_URL=http://127.0.0.1:8050
LES_API_KEY=
LES_TIMEOUT_SECONDS=120
```

## Implementation Rules

- Keep OpenAPI, backend DTOs and docs in sync.
- Update documentation in the same change as code.
- Preserve tasks and catalog as first-class UI workspaces.
- Keep OpenRouter behind the backend orchestration layer.
- Do not introduce secrets into docs, examples or commits.
- Do not run full LES reindex, delete LES data, or change LES runtime behavior unless explicitly requested.
- Prefer small, reviewable changes with a clear commit message.

## Checks

Run local checks when relevant:

```bash
npx --yes @redocly/cli lint openapi/agnostis-mvp.yaml
node --check app/app.js
```

If local `dotnet` is unavailable, build backend on Legion:

```bash
COPYFILE_DISABLE=1 tar -czf /tmp/artel-build.tgz backend openapi docs README.md RUNBOOK_HAND_TEST.md app
scp /tmp/artel-build.tgz legion:artel-build.tgz
ssh legion 'powershell -NoProfile -Command "$archive = Join-Path $env:USERPROFILE ''artel-build.tgz''; $dest = Join-Path $env:TEMP ''artel-build''; if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }; New-Item -ItemType Directory -Path $dest | Out-Null; tar -xzf $archive -C $dest; dotnet build (Join-Path $dest ''backend/Agnostis.Api/Agnostis.Api.csproj'') --configuration Release"'
```

After pushing, check GitHub Pages:

```bash
gh run list --repo proovcme/Agnostis --limit 5
gh run watch <run-id> --repo proovcme/Agnostis --exit-status
```

## Documentation Closeout

For meaningful changes, update at least one of:

- `README.md`
- `docs/technical-stack.md`
- `docs/les-integration.md`
- `docs/bim-rfa-rag.md`
- `backend/README.md`
- `openapi/agnostis-mvp.yaml`

Final responses should include commit hash, pushed branch, checks run, and any remaining architecture limitation.
