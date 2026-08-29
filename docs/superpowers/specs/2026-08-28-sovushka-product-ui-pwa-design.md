# Sovushka Product UI and PWA Design

**Status:** owner-approved design
**Release:** `0.29.0`
**Scope:** shared Sovushka shell, mobile/PWA surface and frontend/backend deployment boundary

## Product intent

Sovushka is the primary LES interface, not an administrative dashboard around
another chat product. Chat, files, evidence, memory, tools and artifacts use one
coherent interface. Configuration remains the only surface where operational
controls may be dense.

The visual direction is a precise engineering workspace with a distinct LES
identity: sharp system typography, strong graphite-on-warm-neutral contrast, one
forest-green accent, restrained borders, minimal depth and one consistent set
of concise outline icons. Decorative gradients, emoji controls, competing
button rows and page-local visual systems are excluded.

## One frontend, separate backend

Sovushka and LES have independent responsibilities:

```text
browser / installed PWA / Tauri WebView
                  -> Sovushka UI server
                  -> stable LES API + event stream
                  -> LES execution node
                  -> files, RAG, memory, tools, models and artifacts
```

Sovushka never reads an execution node's filesystem, process table, secrets or
model endpoints directly. It consumes authenticated LES APIs and safe capability
projections. The execution node owns all domain data, model connections and
side effects.

NiceGUI means Sovushka is currently a server-backed frontend/BFF rather than a
fully static SPA. The PWA is an installable shell for that frontend; it does not
move LES execution into the browser.

## Deployment modes

The same frontend and API contract support two first-class system modes:

1. **Co-located desktop/local.** Sovushka and LES run on the same Mac or Legion.
   Local API traffic uses loopback. This mode requires neither VPS nor tunnel.
2. **Split headless.** Sovushka runs on a VPS while LES, user files, memory and
   models remain on Mac or Legion. The execution node establishes an
   authenticated outbound channel; no home ingress port is published.

Accessing a locally hosted Sovushka from another trusted device is an access
path, not a third functional architecture.

The VPS control-plane to headless LES-node protocol is a separate planned
module. This UI/PWA work must preserve the boundary but must not claim the
remote connector exists before its own design, authentication, reconnect and
acceptance gates are implemented.

## Tauri boundary

Tauri is the canonical Windows desktop lifecycle shell over the same Sovushka:

- installs and verifies the bundled LES runtime;
- starts, stops and repairs the local Sovushka and LES processes;
- owns tray, single-instance and native update lifecycle;
- opens the local Sovushka origin in WebView2.

Tauri contains no second product interface, chat implementation, model
registry, tool logic or domain behavior. Its pre-NiceGUI bootstrap catalogue is
limited to setup and recovery. Browser, PWA and Tauri render the same Sovushka
after the runtime is ready.

VPS/headless use does not require Tauri. Opening a remote Sovushka inside Tauri
is not part of this release.

## App shell and information hierarchy

Desktop keeps a narrow labelled rail. It has three layers only:

1. product identity and current execution-node state;
2. primary destinations;
3. quiet utility actions at the bottom.

Chat is the default and visually dominant product surface. Studio contains
document work. Configuration contains models, datasets, access, diagnostics
and other operator controls. Secondary destinations must not duplicate primary
navigation.

Outside Configuration there is one primary action per decision point. Repeated
or rare operations move into a disclosure, overflow menu or settings sheet.

## Mobile and PWA contract

Mobile is a first-class working mode, not a compressed desktop rail.

- One vertical content column; no page-level horizontal overflow at 390 px.
- The top bar contains product identity and honest execution-node connectivity.
- Primary navigation uses at most three labelled destinations in a stable
  mobile navigation area; technical sections live under Configuration.
- Tap targets are at least 44 by 44 px.
- The chat composer exposes the prompt, attachment and send action. Mode and
  response options live in one compact selector/sheet.
- Suggested prompts are collapsed by default after onboarding and never cover
  the conversation or composer.
- Loss of the backend preserves the local draft but does not automatically
  replay a request.

The PWA manifest names Sovushka/LES, declares standalone display, theme colors,
icons and a stable start URL. Its service worker caches only versioned static
shell assets. API responses, evidence, documents, secrets, event streams and
mutation requests are never runtime-cached. Offline state explains that the
execution node is unavailable and permits draft editing only.

## Typography, color and icons

- Windows uses `Segoe UI Variable Text`/`Segoe UI`; Apple platforms use the
  system San Francisco family; Linux falls back to the system sans-serif.
- Body copy is 16 px; dense controls may use 14 px; metadata is never below
  12 px. Mono is limited to identifiers, versions and numeric diagnostics.
- Text and interactive states meet WCAG 2.2 AA in light and dark themes.
- Green identifies LES and the primary action; it is not applied to every
  heading, border or status.
- Icons use one shared outline registry with a 20 px optical box and accessible
  names. Emoji are not controls. The LES tree and Sovushka owl remain the
  distinctive product marks.

## Model configuration surface

`Configuration -> Models` consumes the safe model-connections API. It is a
vertical operator surface with role bindings, connection health, capability
evidence and create/edit/test actions. It does not contain provider-specific
inference branches and does not become a node registry.

Model endpoints, secret references and model execution stay on the LES backend
node. A split frontend receives only safe projections. A future node selector
selects a registered LES execution node, never an arbitrary model URL.

## Acceptance

- Desktop inspection at 1280 and 1440 px.
- Mobile inspection at 390 by 844 px and 375 px width.
- No horizontal overflow; visible keyboard focus; reduced-motion support.
- Light/dark WCAG AA checks for body, secondary, status and primary-action text.
- PWA manifest and service-worker cache-boundary tests.
- Existing Tauri bootstrap and local lifecycle tests stay green.
- UI contract tests prove that model configuration uses the API and that
  ordinary chat does not expose a provider secret or direct endpoint.
