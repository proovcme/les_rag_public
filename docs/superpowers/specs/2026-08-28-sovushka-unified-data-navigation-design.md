# Sovushka Unified Data Navigation Design

**Status:** owner-approved design
**Release:** `0.29.0`
**Scope:** product navigation, unified data workspace, dormant Mail and CAD/BIM surfaces

## Product decision

Sovushka presents datasets and their documents as one product concept: **Data**.
A dataset is the container and indexing boundary; documents are its contents.
They must not appear as two peer destinations that force a user to switch
screens to understand one object.

The product-visible workspace therefore has one `Данные` destination. The old
`Документы` and `Датасеты` destinations are compatibility names, not separate
information architecture.

Mail remains an ingestion source, not a product destination. Studio and CAD/BIM
remain preserved code behind honest unavailable placeholders until their flows
meet release quality.

## Navigation contract

The primary product navigation remains intentionally small:

1. `Чат` — questions, tasks, evidence and generated artifacts;
2. `Студия · скоро` — disabled placeholder;
3. `Конфигурация` — operational settings.

The secondary working destinations expose:

- `Данные`;
- `История`;
- `CAD/BIM · скоро` as a disabled placeholder.

The following product-visible buttons are removed:

- `Документы`;
- `Датасеты`;
- `Почта`;
- `Настройка почты`.

`Конфигурация -> Датасеты` also disappears because a second dataset destination
would recreate the same split. Authorized dataset operations move into the
unified Data workspace. Mail configuration and mail browsing pages stay in the
repository but have no production navigation entry.

Disabled placeholders are non-interactive, use the shared placeholder style,
carry an accessible unavailable label and do not create a live tab panel. A
placeholder must not look selected, healthy or ready.

## Unified Data workspace

`Данные` is a master-detail workflow built from the existing dataset registry
and document explorer rather than a third independent implementation.

### Dataset overview

The entry view answers three questions in this order:

1. What data collections exist?
2. Which collections are usable now?
3. How do I open or add material?

It contains one search/filter row and one collection list. Each collection row
shows its human name, source type, readiness in text plus icon, file count and
last meaningful activity. The row has one primary action: open the collection.
Rare operator actions live in one overflow menu.

There is no dashboard of equal KPI cards and no duplicate navigation to a
separate file page.

### Dataset detail

Opening a collection keeps its identity visible and shows:

- breadcrumb/back action to all data;
- readiness and indexing state;
- searchable file list;
- document metadata and provenance when selected;
- `Спросить в чате` with exact dataset/file scope;
- upload/import actions when the current role permits them.

Desktop may use a list-and-detail composition when enough width exists. Mobile
uses sequential screens: collections -> files -> file details. Mobile must not
compress a desktop split pane or introduce horizontal scrolling.

### Role boundary

All users with read permission can inspect available collections and files.
Administrative controls are progressively disclosed and remain protected by
the existing backend authorization:

- create or connect a collection;
- add files;
- start bounded processing;
- inspect technical failures;
- disable or remove a registration when separately authorized.

The UI never treats hidden controls as authorization. Existing APIs remain the
enforcement boundary.

## Mail boundary

Removing Mail from navigation must not stop, reconfigure or delete mail
ingestion. Existing collectors, schedules, APIs, credentials, pages and data
remain intact.

Mail continues to write into its own typed dataset. That dataset appears in
`Данные` with a source badge such as `Почта`; its messages and attachments are
ordinary evidence-bearing documents inside that collection. No separate mail
inbox workflow is promised in this release.

Secrets remain masked and are not moved into the unified Data page. Re-exposing
mail setup or mailbox browsing requires a later explicit product decision.

## Studio and CAD/BIM boundary

Studio and CAD/BIM implementation files remain available for future work but
are not production surfaces.

- `Студия · скоро` keeps its existing disabled product placeholder.
- `CAD/BIM · скоро` becomes the same class of disabled placeholder.
- Neither placeholder builds the heavy documents surface or starts its timers.
- Direct requests for the old Studio or CAD/BIM tabs fall back to a working
  destination without claiming the unfinished surface loaded.

This change does not edit the separate CAD/BIM viewer engine or generated
frontend bundles.

## Compatibility and URLs

The canonical working URL is `/classic?tab=data` (and the equivalent `/les`
prefix route). Existing links remain safe:

- `tab=documents` redirects or resolves to `tab=data`;
- `tab=datasets` redirects or resolves to `tab=data`;
- `tab=mail`, `tab=studio` and `tab=cad_bim` resolve to a working fallback;
- an existing `dataset_id` query value is preserved when moving from an old
  document or dataset link into Data.

Stored last-tab values using old names are migrated at read time. The code does
not keep building hidden panels merely to support compatibility URLs.

## Implementation boundary

The first implementation should compose and extract from the existing
`sovushka.pages.samovar` and `sovushka.pages.documents` flows. It must not copy
their API logic into another large page. Shared dataset summary, dataset detail
and file-list builders receive explicit inputs and expose pauseable timers under
the existing lazy-panel contract.

No new dependency is required. This navigation work does not change retrieval,
indexing contracts, datasets, document contents, mail collection behavior or
backend permissions.

## Error and empty states

- No collections: explain how an authorized user can add data; do not show a
  false system failure.
- Collection unavailable: retain its identity, state the blocker and expose a
  retry only when retry is a real supported action.
- File list unavailable: keep collection context and distinguish API failure
  from an empty collection.
- Mail collector failure: reflect the mail dataset's degraded state in Data;
  do not restore a separate Mail button as an error workaround.
- Legacy URL: resolve deterministically and replace history with the canonical
  URL so refresh does not re-enter a dead surface.

## Acceptance

- Desktop checks at 1280 and 1440 px show one Data destination and no separate
  Documents, Datasets or Mail navigation buttons.
- Mobile checks at 390 by 844 px show no page-level horizontal overflow and a
  sequential collections-to-files flow.
- Studio and CAD/BIM are visibly unavailable placeholders and create no heavy
  panel.
- Mail and mail-settings pages are unreachable from production navigation while
  collector/API contracts and their offline tests remain green.
- Old `documents` and `datasets` URLs land in Data and preserve `dataset_id`.
- Role tests prove ordinary users do not receive operator mutations.
- Existing dataset, document, mail, lazy-panel, PWA and Tauri contract tests
  remain green.
- `make verify` and `make test` pass before the implementation is called ready.
