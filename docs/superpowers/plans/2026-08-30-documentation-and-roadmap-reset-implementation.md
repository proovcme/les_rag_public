# Documentation and Roadmap Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Отделить текущую документационную правду ЛЕС от исторического слоя и заменить 1920-строчный roadmap коротким продуктовым путём до v1.

**Architecture:** Каноническая цепочка из `AGENTS.md` остаётся единственным источником текущей правды. Машинная проверка защищает существование и локальные ссылки канона; очевидно исторические документы перемещаются через `git mv` в индексированный архив; неоднозначные файлы остаются активными с явной очередью ручной проверки.

**Tech Stack:** Markdown, Python 3.12+, pytest, `uv`, Git, существующий `make verify`.

**Spec:** `docs/superpowers/specs/2026-08-30-documentation-and-roadmap-reset-design.md`

## Global Constraints

- Не менять product/runtime behavior.
- Не удалять документы: история перемещается только через `git mv`.
- Не архивировать действующий `ALGO-*`, module contract или файл со ссылкой из кода без исправления ссылки.
- Не считать название или возраст доказательством устаревания.
- Текущая установленная версия Legion остаётся `0.30.1 / build 641` до отдельного релиза.
- В конце изменения выполнить version/ledger discipline как для следующего dev candidate, не публикуя и не деплоя его автоматически.

---

### Task 1: Машинный контракт канонической документации

**Files:**
- Create: `tools/documentation_contract.py`
- Create: `tests/test_documentation_contract.py`
- Modify: `Makefile`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/MODULE_INDEX.md`

**Interfaces:**
- Consumes: repository root `Path`, канонический список из `AGENTS.md`, Markdown local links.
- Produces: `audit_documentation(root: Path) -> list[str]` и CLI exit `0/1`; pytest-контракт входит в `make verify`/`make test`.

- [ ] **Step 1: Write the failing contract tests**

Создать фикстуру mini-repo и проверить три поведения:

```python
def test_documentation_contract_accepts_existing_canonical_chain(tmp_path):
    _write_complete_canonical_fixture(tmp_path)
    assert audit_documentation(tmp_path) == []


def test_documentation_contract_reports_missing_local_target(tmp_path):
    _write_complete_canonical_fixture(tmp_path)
    (tmp_path / "AGENTS.md").write_text("[broken](docs/missing.md)", encoding="utf-8")
    assert audit_documentation(tmp_path) == ["AGENTS.md -> docs/missing.md: missing"]


def test_documentation_contract_rejects_talmud_roadmap(tmp_path):
    _write_complete_canonical_fixture(tmp_path)
    (tmp_path / "ROADMAP_TO_V1.md").write_text("\n".join(["line"] * 301), encoding="utf-8")
    assert "ROADMAP_TO_V1.md: exceeds 300 lines" in audit_documentation(tmp_path)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run pytest --basetemp=.test-tmp/documentation-red -q tests/test_documentation_contract.py
```

Expected: collection/import failure because `tools.documentation_contract` does not exist.

- [ ] **Step 3: Implement the minimal documentation contract**

Реализовать:

```python
CANONICAL_PATHS = (
    "AGENTS.md",
    "SKILL.md",
    "docs/MODULE_INDEX.md",
    "docs/CODE_MAP.md",
    "docs/SOFTWARE_VERSIONS.md",
    "ROADMAP_TO_V1.md",
    "docs/RELEASE_LEDGER.md",
    "docs/unified_harness_failure_ledger.md",
    "docs/TEST_INVENTORY.md",
)


def audit_documentation(root: Path) -> list[str]:
    """Return deterministic findings for missing canon, broken canonical links and roadmap bloat."""
```

Локальные Markdown-ссылки разрешать относительно файла-источника; игнорировать `http:`, `https:`,
`mailto:`, чистые anchors и содержимое code fences. Проверять только канон, `README.md`,
`docs/index.md` и `docs/archive/README.md`, чтобы исторический архив не блокировал разработку.

- [ ] **Step 4: Register the test in canonical gates and docs**

Добавить `tests/test_documentation_contract.py` в явный список `CURRENT_LES_TESTS`/эквивалентный
канонический список `Makefile`. В `TEST_INVENTORY.md` добавить строку про канонические пути,
локальные ссылки и лимит roadmap. В `MODULE_INDEX.md` добавить `ops/documentation-contract` с
точками входа `tools/documentation_contract.py`, `tests/test_documentation_contract.py`.

- [ ] **Step 5: Run GREEN and commit**

```powershell
uv run pytest --basetemp=.test-tmp/documentation-green -q tests/test_documentation_contract.py
git add tools/documentation_contract.py tests/test_documentation_contract.py Makefile docs/TEST_INVENTORY.md docs/MODULE_INDEX.md
git commit -m "test(docs): enforce canonical documentation contract"
```

Expected: all documentation contract tests pass.

---

### Task 2: Переписать продуктовый roadmap

**Files:**
- Replace: `ROADMAP_TO_V1.md`
- Modify: `README.md`
- Modify: `docs/index.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: product decisions in the approved spec, installed/public `0.30.1 / build 641` state.
- Produces: roadmap under 300 lines with one product promise, four workstreams and measurable v1 acceptance.

- [ ] **Step 1: Extend the failing roadmap contract**

Добавить в `tests/test_documentation_contract.py`:

```python
def test_real_roadmap_has_product_contract_and_four_workstreams():
    text = (ROOT / "ROADMAP_TO_V1.md").read_text(encoding="utf-8")
    assert "помощник ГИП/РП" in text
    assert "## 1. RAG и evidence" in text
    assert "## 2. Работа ГИП/РП" in text
    assert "## 3. Агент" in text
    assert "## 4. Надёжность" in text
    assert "## v0.19" not in text
```

- [ ] **Step 2: Run RED**

```powershell
uv run pytest --basetemp=.test-tmp/roadmap-red -q tests/test_documentation_contract.py::test_real_roadmap_has_product_contract_and_four_workstreams
```

Expected: failure because the current roadmap is historical and uses the old milestone structure.

- [ ] **Step 3: Replace the roadmap**

Новый документ должен содержать ровно эти разделы:

1. `Что такое ЛЕС` — локальный помощник ГИП/РП, выбранные документы как источник истины;
2. `Где мы сейчас` — опубликованная 0.30.1 и подтверждённые возможности без списка внутренних модулей;
3. `Архитектура продукта` — модель + RAG + prompt/skill + tools + task code;
4. четыре workstream из спецификации;
5. `Порядок` — сначала доказуемое качество RAG, затем evidence UI, затем рабочие инструменты и стабилизация;
6. `Definition of v1` — пользовательские результаты и live acceptance;
7. `Не входит в roadmap` — количество модулей, переписывание модели кодом, скрытый scope и новые самостоятельные продукты.

Не переносить в новый файл исторические release trains, дневники сессий, закрытые пункты и smoke-команды.

- [ ] **Step 4: Align entry pages**

В `README.md` и `docs/index.md` оставить одну и ту же короткую формулировку продукта и ссылку на
roadmap. В `AGENTS.md` заменить описание старого `ROADMAP_TO_V1.md` на «короткий продуктовый путь
до v1; история релизов находится в archive/ledger».

- [ ] **Step 5: Run GREEN and commit**

```powershell
uv run pytest --basetemp=.test-tmp/roadmap-green -q tests/test_documentation_contract.py
uv run python tools/documentation_contract.py
git add ROADMAP_TO_V1.md README.md docs/index.md AGENTS.md tests/test_documentation_contract.py
git commit -m "docs: replace historical roadmap with product path to v1"
```

---

### Task 3: Перенести очевидный исторический слой из корня

**Files:**
- Move to `docs/archive/root-legacy/`:
  - `ARTICLE_INDEXING_LESSONS.md`
  - `ARTICLE_SAFERAG.md`
  - `DICTIONARY_LES_v2.0.md`
  - `LES_SIMPLE_OVERVIEW.md`
  - `LES_SYSTEM_BUSINESS_NOVEL.md`
  - `PROGRAMMA_ISPYTANIY_v2.0.md`
  - `RAG_MODERNIZATION_PLAN.md`
- Modify: `docs/archive/README.md`
- Modify: all active Markdown files returned by exact backlink search.

**Interfaces:**
- Consumes: `rg` backlinks and canonical link contract.
- Produces: корень без параллельных overview/roadmap/article документов; архивный индекс с актуальной заменой.

- [ ] **Step 1: Prove each candidate has no unresolved code dependency**

Для каждого имени выполнить exact search по tracked files, исключая сам файл и `docs/archive/`:

```powershell
rg -n "ARTICLE_INDEXING_LESSONS\.md|ARTICLE_SAFERAG\.md|DICTIONARY_LES_v2\.0\.md|LES_SIMPLE_OVERVIEW\.md|LES_SYSTEM_BUSINESS_NOVEL\.md|PROGRAMMA_ISPYTANIY_v2\.0\.md|RAG_MODERNIZATION_PLAN\.md" -g '!docs/archive/**'
```

Если ссылка идёт из кода, файл не переносить и внести в manual-review очередь архива. Если ссылка
идёт из активного Markdown, заменить её на канонический документ, который действительно содержит
утверждение.

- [ ] **Step 2: Move the proven historical files**

Использовать `git mv` для каждого подтверждённого кандидата. В `docs/archive/README.md` добавить
таблицу `root-legacy`: прежний файл, причина архивации, актуальная замена (`README.md`,
`ROADMAP_TO_V1.md`, `docs/CODE_MAP.md` или `docs/ALGO-rag-best-practices.md`).

- [ ] **Step 3: Verify links and commit**

```powershell
uv run python tools/documentation_contract.py
git diff --check
git add -A
git commit -m "docs: archive superseded root narratives"
```

---

### Task 4: Перенести завершённые планы, аудиты и старые release notes

**Files:**
- Move to `docs/archive/plans/`:
  - `docs/BASIC_FUNCTIONS_AUTOTEST_PLAN.md`
  - `docs/DOC_REVIEW_GOST_R_21_101_2026_PLAN.md`
  - `docs/LES3_PLAN.md`
  - `docs/PLAN_DODELKA.md`
  - `docs/PLAN_EVIDENCE_CORE.md`
  - `docs/TODO_EVIDENCE_CORE.md`
  - `docs/TODO_LOCAL_INFERENCE_BENCHMARK.md`
  - `docs/TODO_SMETA_CORE.md`
  - `docs/TODO_WINDOWS_PRODUCTION.md`
  - `docs/UI_IMPROVEMENT_PLAN.md`
- Move to `docs/archive/audits/`:
  - `docs/ACCESSIBILITY_AUDIT.md`
  - `docs/ANSWER_LIMIT_AUDIT.md`
  - `docs/LOCAL_INFERENCE_OPTIQ_MTP_M4_2026-07-13.md`
  - `docs/MAC_REINSTALL_STRESS.md`
  - `docs/MODULE_AUDIT_2026-06-26.md`
  - `docs/RAG_TEST_PROGRAM_AUDIT.md`
  - `docs/SMETA_MODULE_BASE_AUDIT_2026-07-09.md`
  - `docs/SMETA_REQUIRED_SOURCE_AUDIT_2026-07-11.md`
  - `docs/SMETA_RIM_MODULE_HANDOFF_CLAUDE.md`
  - `docs/TEST_ARCHITECTURE_AUDIT_2026-07-14.md`
- Move to `docs/archive/releases/`: all eight `docs/RELEASE_NOTES_0.24*.md`.
- Modify: `docs/archive/README.md`
- Modify: active backlinks discovered before moving.

**Interfaces:**
- Consumes: exact backlink evidence for every candidate.
- Produces: active `docs/` without completed execution narratives; retained history grouped by type.

- [ ] **Step 1: Generate deterministic backlink report**

Использовать `git grep -n` по каждому basename. Кандидат со ссылкой из `.py`, `.toml`, `Makefile`,
`AGENTS.md`, `SKILL.md`, `MODULE_INDEX.md` или `CODE_MAP.md` не перемещать автоматически. Записать
его в секцию `Оставлены для ручной проверки` в `docs/archive/README.md` с найденной ссылкой.

- [ ] **Step 2: Move only proven historical candidates**

Создать три архивные группы через `git mv`. Исправить Markdown backlinks на roadmap, module doc,
release ledger или archive path в зависимости от смысла ссылки.

- [ ] **Step 3: Index archive decisions**

В `docs/archive/README.md` для каждой группы указать:

```text
прежний путь | почему историческое | текущий источник истины
```

Не добавлять внутрь активного канона отдельный отчёт об уборке.

- [ ] **Step 4: Verify and commit**

```powershell
uv run python tools/documentation_contract.py
uv run pytest --basetemp=.test-tmp/docs-archive -q tests/test_documentation_contract.py tests/test_test_profiles.py
git diff --check
git add -A
git commit -m "docs: archive completed plans audits and release notes"
```

---

### Task 5: Свести входные страницы и ручную очередь

**Files:**
- Modify: `docs/archive/README.md`
- Modify: `docs/AGENT_NOTES.md`
- Modify: `docs/DOCUMENTATION_PLAYBOOK.md`
- Modify: `docs/index.md`

**Interfaces:**
- Consumes: итоговый active/archive inventory.
- Produces: один маршрут чтения для человека и агента; bounded manual-review queue без нового Markdown-файла.

- [ ] **Step 1: Add the manual-review queue**

В `docs/archive/README.md` добавить секцию `Оставлены активными до ручного решения`. Для каждого
неоднозначного файла указать причину: code backlink, действующий модуль, незакрытый acceptance или
неясная замена. Это очередь решения, а не новая инструкция.

- [ ] **Step 2: Make the reading order consistent**

В `docs/index.md`, `docs/AGENT_NOTES.md` и `DOCUMENTATION_PLAYBOOK.md` зафиксировать один порядок:
канон → module/algorithm doc → archive только для истории. Удалить советы читать старые планы как
текущий backlog.

- [ ] **Step 3: Add a repository-level acceptance test**

Расширить `tests/test_documentation_contract.py` проверками:

```python
def test_active_root_has_no_superseded_narratives():
    forbidden = {"RAG_MODERNIZATION_PLAN.md", "LES_SIMPLE_OVERVIEW.md"}
    assert forbidden.isdisjoint(path.name for path in ROOT.glob("*.md"))


def test_archive_has_an_indexed_manual_review_queue():
    text = (ROOT / "docs/archive/README.md").read_text(encoding="utf-8")
    assert "Оставлены активными до ручного решения" in text
```

- [ ] **Step 4: Run focused acceptance and commit**

```powershell
uv run pytest --basetemp=.test-tmp/docs-entry -q tests/test_documentation_contract.py
uv run python tools/documentation_contract.py
git add docs/archive/README.md docs/AGENT_NOTES.md docs/DOCUMENTATION_PLAYBOOK.md docs/index.md tests/test_documentation_contract.py
git commit -m "docs: establish one canonical reading path"
```

---

### Task 6: Версия, итоговый ledger и полный гейт

**Files:**
- Modify: `config/version.json`
- Modify mechanically: `desktop/tauri/src-tauri/Cargo.toml`
- Modify mechanically: `desktop/tauri/src-tauri/Cargo.lock`
- Modify mechanically: `desktop/tauri/src-tauri/tauri.conf.json`
- Modify mechanically: `docs/SOFTWARE_VERSIONS.md`
- Modify mechanically: `docs/VERSIONING.md`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: completed documentation reset commits.
- Produces: `0.30.2 / build 642` dev candidate with explicit statement that Legion/public remain `0.30.1 / build 641` until a separate authorized release.

- [ ] **Step 1: Bump the development contract**

В `config/version.json` установить:

```json
{
  "product_version": "0.30.2",
  "build_number": 642,
  "desktop_version": "5.1.642"
}
```

Сохранить существующие `schema` и `harness_schema_version`, затем выполнить:

```powershell
uv run python tools/sync_version_contract.py
```

- [ ] **Step 2: Record exact truth in the ledger**

В `RELEASE_LEDGER.md` разделить:

```text
dev candidate: 0.30.2 / build 642 / documentation reset
installed Legion: 0.30.1 / build 641 / commit 2a02084d
public release: v0.30.1 immutable GitHub patch
```

Не объявлять 0.30.2 опубликованной или установленной.

- [ ] **Step 3: Run full gates**

```powershell
uv run python tools/documentation_contract.py
make verify
make test
make test-tauri
make public-check
git diff --check
```

Expected:

```text
documentation contract: OK
make verify: 0
make test: all current LES tests pass
cargo check: 0
public-check: OK
git diff --check: no errors
```

`make ship-full-check` может считать активные сметные артефакты отсутствующими в изолированном
worktree; в таком случае отдельно выполнить `tools.smeta_release_baseline verify-root` на
`%LOCALAPPDATA%\Programs\LES\runtime` и не копировать пользовательские данные в git.

- [ ] **Step 4: Review the final diff and commit**

```powershell
git diff --stat 2a02084d..HEAD
git status --short
git add config/version.json desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json docs/SOFTWARE_VERSIONS.md docs/VERSIONING.md docs/RELEASE_LEDGER.md
git commit -m "docs: complete canonical documentation reset"
```

Не деплоить и не публиковать 0.30.2 в рамках этого плана: пользователь вручную проверяет
установленную 0.30.1, а следующий release требует отдельного решения.
