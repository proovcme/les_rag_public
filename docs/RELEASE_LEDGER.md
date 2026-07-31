# RELEASE_LEDGER — текущий выпуск

Канон «где мы сейчас» для агентов и релизной дисциплины.

| Поле | Значение |
|------|----------|
| product_version | **0.25.1** |
| build_number | **474** |
| desktop_version | 5.1.474 |
| base | `origin/main` @ `1fde2ea` (0.25.0 / build 473) |
| branch | `feature/smeta-local-ollama-stability` |

## 0.25.1 — local Ollama/Qwen LSR stability (2026-07-29)

**Зачем:** после 0.25.0 локальный `qwen3.5:9b` часто ронял PDF→ЛСР на hard-reject
`invalid unbound_evidence` / truncated structured JSON / catalog-only turns. На 0.24.48
неполный evidence шёл в `precalculation_blockers`, и XLSX всё равно собирался.

**Что вошло:**
- soft-accept incomplete unbound/bind evidence → `precalculation_blockers` (default для
  local Ollama+Qwen; env `LES_SMETA_DOCUMENT_SOFT_ACCEPT`);
- mapping transport: parse thinking / one `think=false` retry / higher token budget on
  `done_reason=length`;
- local batch_size=1; max tool turns 6; global review off by default on local;
- search/open-cards preflight before forced mapping; align truncated `queries_used` /
  `opened_norm_codes` to tool trace;
- Windows helper scripts `scripts/windows/LES-START|STOP` + `config/local/windows-cuda.env`.

**Проверки:** `uv run pytest tests/test_smeta_core.py -k "soft_accept or unbound_fills or batch_agent_opens or batch_agent_searches or unbound_aligns"`;
`make verify` перед merge.

**Не в коммите:** `tools/bin/qdrant.exe` (локальный бинарь).

## Предыдущий якорь

| product_version | build | commit | note |
|-----------------|-------|--------|------|
| 0.25.0 | 473 | `1fde2ea` | почта вручную + лёгкая проверка выпуска |
| 0.25.0 | 472 | `65aa9a9` | Outlook освобождён до разбора снимков |
| 0.25.0 | 470 | `3b8eb35` | mail Outlook + Windows packaging поверх выпуска 0.25.0 |
| 0.25.0 | 470 | `4f1a305` | полный исходный код и документация 0.25.0 |
