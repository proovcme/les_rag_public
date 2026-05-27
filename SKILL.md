---
name: les
description: Use when working on the local LES_v2 repository, LES runtime, Core ML/MLX/Qdrant/Sovushka/PAUK/VOLK workflows, runtime health, indexing, external les.ovc.me access, docs, tests, or cleanup.
---

# LES Operator Skill

## Workspace

Use `/Users/ovc/Projects/LES_v2` as the project root.

Current production posture:

- Proxy: `http://127.0.0.1:8050`
- Sovushka Lite UI/admin: `http://127.0.0.1:8051`, `/les`
- MLX Host: `http://127.0.0.1:8080`
- Qdrant: `http://127.0.0.1:6333`
- External: `https://les.ovc.me` through P.A.U.K. reverse SSH tunnel and V.O.L.K. API keys

## First Checks

Before changing runtime behavior, inspect:

```bash
cd /Users/ovc/Projects/LES_v2
curl -fsS http://127.0.0.1:8050/api/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8080/api/health | python3 -m json.tool
launchctl list | grep -E 'les|sovushka|qdrant|mlx'
```

Expected closeout baseline on 2026-05-27:

- `1003/1003` indexed files, `0` pending, `0` errors.
- `248917` chunks and Qdrant points match SQLite chunks.
- Main model: `mlx-community/Qwen3.5-4B-OptiQ-4bit`.
- Embedder: Core ML `Qwen/Qwen3-Embedding-0.6B`, `qwen3_embedding_06b_b1_s512_static.mlpackage`, `cpu_and_gpu`, isolated worker, fallback disabled.
- Validator: Core ML `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`, `validator_minilm_l6_b1_s512.mlpackage`, `cpu_only`, isolated worker, fallback disabled.

## Guardrails

- Do not run a full reindex unless the user explicitly asks and the reason is documented.
- Do not delete `data/qdrant/`, `data/les_meta_qwen.db`, `storage/`, or `RAG_Content/`.
- Do not resurrect old BGE or unused MLX validator caches unless a focused benchmark needs them.
- Keep secrets out of git docs. Use environment variables or the operator password manager for V.O.L.K. keys.
- Treat `VALIDATOR_BACKEND=rules` as deterministic smoke only, not production quality.
- Keep `cpu_and_ne` Core ML experiments behind a focused stability gate; previous canaries showed native crash risk.
- Treat FIRE/HVAC quality as a domain acceptance problem, not as one-off answer fixes. Run `uv run python tools/rag_golden_set.py --cases golden/domain_fire_hvac_set.json` after retrieval/router changes; current baseline is `16/16`.

## Tests

Run these before finalizing meaningful changes:

```bash
uv run pytest -q
git diff --check
uv lock --check
```

For public access checks, use an admin key from the environment, not from committed docs:

```bash
uv run python tools/runtime_smoke.py \
  --proxy-url https://les.ovc.me \
  --ui-url https://les.ovc.me \
  --qdrant-url http://127.0.0.1:6333 \
  --admin-key "$LES_ADMIN_KEY" \
  --expect-external-auth
```

## Common Runtime Actions

Restart proxy after backend changes:

```bash
launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy
```

Restart MLX Host after model/env changes:

```bash
launchctl kickstart -k gui/$(id -u)/me.ovc.les.mlx
```

Restart Sovushka UI after frontend/static UI changes:

```bash
launchctl kickstart -k gui/$(id -u)/com.les.sovushka
```

If external `les.ovc.me` returns 502 while local services are healthy, check or restart P.A.U.K. reverse tunnel with the project runbook in `dev/TUNNELS_AND_REMOTE_ACCESS.md`.

## Documentation

When closing a LES session, update at least:

- `README.md`
- `RAG_MODERNIZATION_PLAN.md`
- `INFRASTRUCTURE_v2.0.md`
- newest `SESSION_SUMMARY_*.md`

Record exact dates, test counts, index counts, model ids, Core ML package names, fallback state, and external smoke state.
