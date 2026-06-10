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
- External: `https://les.ovc.me` through P.A.U.K. reverse SSH tunnel and V.O.L.K. API keys; on 2026-06-01 external smoke passes `12/12`.
- Speckle BIM/CAD bridge: `https://speckle.ovc.me`, GraphQL `https://speckle.ovc.me/graphql`, managed by `/api/settings` and `/api/speckle/status`; live after token setup on 2026-06-02 is `status=ok`, `http_status=200`, `api_token_set=true`; `502/503/504` means `sleeping`, not LES failure.
- ZeroTier trusted GUI/API access: `TRUSTED_NETWORKS=127.0.0.0/8,::1/128,10.195.146.0/24`, `TRUSTED_NETWORK_ROLE=admin`. Trusted clients should open `/les` and `/lite-api/*` without a key; stale browser keys fallback to `trusted-network`, while public clients still receive `401`.

## First Checks

Before changing runtime behavior, inspect:

```bash
cd /Users/ovc/Projects/LES_v2
curl -fsS http://127.0.0.1:8050/api/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8080/api/health | python3 -m json.tool
launchctl list | grep -E 'les|sovushka|qdrant|mlx'
```

Live baseline on 2026-06-01:

- Local consistency is closed: `1212` files, `1212` indexed, `0` pending, `0` errors.
- `143150` SQLite chunks match `143150` Qdrant points; `points_match_sqlite_chunks=true`, local proxy health is `ok`.
- Main model: `mlx-community/Qwen3.5-4B-MLX-4bit`.
- Embedder: Core ML `Qwen/Qwen3-Embedding-0.6B`, `qwen3_embedding_06b_b1_s512_static.mlpackage`, `compute_units=all`, isolated worker, fallback disabled.
- Validator live default: deterministic `rules`. Core ML `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` package exists for measured compare/probe, not current production default.
- Visual OCR: MLX-native `mlx-community/GLM-OCR-4bit` (via `mlx-vlm`, lazy-loaded with explicit Metal cache clearing after processing).
- Office Ingestion: Microsoft MarkItDown with graceful fallbacks to mammoth/pandas.
- Structured Rules: Google LangExtract schema extraction to SQLite `structured_rules` table with exact character offsets; active table is expected to be empty until targeted `NORMATIVE`/`SPEC` reindex populates it.
- Speckle bridge is configured for DWG/RVT/IFC and Excel/Power BI handoff. LES admits `.dwg`, `.rvt`, `.ifc`, `.ifczip` at upload boundary, but full BIM/CAD conversion remains in Speckle/connectors. `/api/speckle/import` supports source profiles `AUTO`, `AutoCAD/DWG`, `Revit/RVT`, `IFC`, `Excel/Power BI`, `Generic`, builds `data/cad_bim_graph.db`, stores properties in `cad_bim_properties`, and writes markdown projections under `RAG_Content/CAD_BIM/exports/`; Lite Admin `SYNC CAD/BIM` registers those projections in `CAD_BIM_Index`. Current imported model: Speckle project `36`, model `шпалерная 36_отсоединено_oleg`, import `432aa0b18f2a`, `956` graph elements, `955` relations, `44` properties, `957` indexed chunks.

## Guardrails

- Do not run a full reindex unless the user explicitly asks and the reason is documented.
- Do not delete `data/qdrant/`, `data/les_meta_qwen.db`, `storage/`, or `RAG_Content/`.
- Do not resurrect old BGE or unused MLX validator caches unless a focused benchmark needs them.
- Keep secrets out of git docs. Use environment variables or the operator password manager for V.O.L.K. keys.
- Treat `VALIDATOR_BACKEND=rules` as the current stable live default; re-evaluate Core ML validator only after golden accuracy, latency and confidence-threshold gates are clean.
- Keep `cpu_and_ne` Core ML experiments behind a focused stability gate; previous canaries showed native crash risk.
- Treat FIRE/HVAC quality as a domain acceptance problem, not as one-off answer fixes. Run `uv run python tools/rag_golden_set.py --cases golden/domain_fire_hvac_set.json` after retrieval/router changes; current baseline is `16/16`.
- Preserve the SQLite `structured_rules` table. Do not drop or wipe it unless explicitly executing a targeted structured index rebuild.
- Keep the `_parse_with_markitdown` fallback pipeline intact to guarantee clean mammoth/pandas conversion if python dependencies are altered.
- **MLX VLM / GLM-OCR Operational Safeguards**:
  - **AutoImageProcessor / Torchvision Requirement**: Hugging Face `transformers`' `AutoImageProcessor` silently falls back to a plain `TokenizersBackend` if `torchvision` (and `torch`) is missing. This completely disables image feature processing and results in blank OCR. Always list both packages as explicit dependencies in `pyproject.toml` to lock perfectly matched versions (`torchvision==0.25.0`, `torch==2.10.0` on M-series chips) and prevent C++ operator registry mismatches (`RuntimeError: operator torchvision::nms does not exist`).
  - **Template Formatting**: For `GLM-OCR` visual models, always apply the chat template using `apply_chat_template` on the task prompt (e.g. `"Text Recognition:"`) to correctly format and align visual token placeholders `<|image|>` for the language model.
  - **Repetition Mitigation**: In dense document OCR tasks, always pass `repetition_penalty=1.2`, `repetition_context_size=64`, and explicit length constraints like `max_tokens=1024` to prevent infinite token loops at the end of the page text.

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

Generate a bill of quantities (ВОР) from indexed specifications (deterministic, no LLM; needs proxy restart after first deploy):

```bash
curl -fsS -X POST http://127.0.0.1:8050/api/bor/<dataset_id>/generate | python3 -m json.tool
# preview: GET /api/bor/<dataset_id>/preview?limit=50 · download: GET /api/bor/<dataset_id>/download
```

## Documentation

When closing a LES session, update at least:

- `README.md`
- `RAG_MODERNIZATION_PLAN.md`
- `INFRASTRUCTURE_v2.0.md`
- newest `SESSION_SUMMARY_*.md`

Record exact dates, test counts, index counts, model ids, Core ML package names, fallback state, and external smoke state.
