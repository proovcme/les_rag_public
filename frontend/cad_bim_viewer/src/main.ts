import "./style.css";
import { CadBimViewer } from "./viewer-core";
import type { CadBimElement, CadBimSourceResponse, ViewerStats } from "./types";

const app = document.getElementById("app");
if (!app) throw new Error("Missing #app");

app.innerHTML = `
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <strong>LES CAD/BIM Viewer</strong>
        <span>cad_bim_graph.json</span>
      </div>
      <form class="toolbar" id="load-form">
        <input id="source-path" placeholder="source_path или latest" autocomplete="off" />
        <button type="submit">Load</button>
        <button type="button" id="fit-btn">Fit</button>
        <button type="button" id="reload-btn">Reload</button>
      </form>
      <div class="status" id="status">initializing...</div>
    </header>

    <section class="viewport-wrap">
      <div id="viewer"></div>
      <div class="hud" id="hud"></div>
    </section>

    <aside class="side">
      <section class="panel">
        <h2>Graph</h2>
        <div class="stats" id="stats"></div>
      </section>
      <section class="panel">
        <h2>Layers</h2>
        <div class="list" id="layers"></div>
      </section>
      <section class="panel">
        <h2>Selected</h2>
        <div id="selected" class="empty">Click geometry in the viewer.</div>
      </section>
    </aside>
  </main>
`;

const viewerNode = document.getElementById("viewer")!;
const statusNode = document.getElementById("status")!;
const sourceInput = document.getElementById("source-path") as HTMLInputElement;
const statsNode = document.getElementById("stats")!;
const layersNode = document.getElementById("layers")!;
const selectedNode = document.getElementById("selected")!;
const hudNode = document.getElementById("hud")!;
const form = document.getElementById("load-form") as HTMLFormElement;

const params = new URLSearchParams(window.location.search);
const initialSource = params.get("source_path") || params.get("source") || "";
const highlightIds = new Set(
  (params.get("highlight") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean),
);
sourceInput.value = initialSource;

let viewer: CadBimViewer;
let latestSource = initialSource;

async function boot(): Promise<void> {
  viewer = await CadBimViewer.create(viewerNode);
  (window as unknown as { __lesCadBimViewer?: CadBimViewer }).__lesCadBimViewer = viewer;
  viewer.onSelect = renderSelected;
  await loadGraph(initialSource);
}

async function loadGraph(sourcePath: string): Promise<void> {
  setStatus("loading...");
  try {
    latestSource = sourcePath;
    const data = await requestCadBimSource(sourcePath);
    const result = viewer.render(data.payload, highlightIds);
    renderStats(result.stats);
    renderLayers(result.stats);
    renderSelected(null);
    renderHud(data, result.stats);
    setStatus(`${data.source || "latest"} | ${formatNumber(data.element_count || result.stats.elements)} elements`);
    const focusId = params.get("focus") || [...highlightIds][0] || "";
    if (focusId) viewer.focusElement(focusId);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus(message, true);
    selectedNode.innerHTML = `<div class="empty error">${escapeHtml(message)}</div>`;
  }
}

async function requestCadBimSource(sourcePath: string): Promise<CadBimSourceResponse> {
  const query = new URLSearchParams({ max_elements: "50000" });
  if (sourcePath.trim()) query.set("source_path", sourcePath.trim());
  const response = await fetch(`/lite-api/cad-bim/source?${query.toString()}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`CAD/BIM source ${response.status}: ${text.slice(0, 240)}`);
  }
  return (await response.json()) as CadBimSourceResponse;
}

function renderStats(stats: ViewerStats): void {
  statsNode.innerHTML = [
    statCard("Elements", stats.elements),
    statCard("Drawable", stats.drawable),
    statCard("Relations", stats.relations),
  ].join("");
}

function renderLayers(stats: ViewerStats): void {
  const rows = [...stats.layers.entries()].sort((a, b) => b[1] - a[1]);
  if (!rows.length) {
    layersNode.innerHTML = `<div class="empty">No layers in current graph.</div>`;
    return;
  }
  layersNode.innerHTML = rows
    .map(
      ([layer, count], index) => `
        <label class="layer-row" title="${escapeHtml(layer)}">
          <input type="checkbox" data-layer="${escapeHtml(layer)}" checked />
          <span class="name">${escapeHtml(layer)}</span>
          <span class="count">${formatNumber(count)}</span>
        </label>
      `,
    )
    .join("");
  layersNode.querySelectorAll<HTMLInputElement>("input[data-layer]").forEach((input) => {
    input.addEventListener("change", () => viewer.setLayerVisible(input.dataset.layer || "", input.checked));
  });
}

function renderSelected(element: CadBimElement | null): void {
  if (!element) {
    selectedNode.innerHTML = `<div class="empty">Click geometry in the viewer.</div>`;
    return;
  }
  const props = flattenProperties(element.properties || {});
  const baseRows: [string, unknown][] = [
    ["id", element.id || ""],
    ["type", element.type || element.object_type || ""],
    ["name", element.name || ""],
    ["layer", element.layer || ""],
    ["category", element.category || ""],
    ["family", element.family || ""],
    ["level", element.level || ""],
    ["material", element.material || ""],
  ];
  const rows = baseRows.concat(props.slice(0, 28)).filter(([, value]) => value !== "");

  selectedNode.innerHTML = `
    <div class="list">
      ${rows
        .map(
          ([key, value]) => `
          <div class="prop-row">
            <span class="key">${escapeHtml(key)}</span>
            <span class="value">${escapeHtml(formatValue(value))}</span>
          </div>
        `,
        )
        .join("")}
    </div>
  `;
}

function renderHud(data: CadBimSourceResponse, stats: ViewerStats): void {
  const payload = data.payload && !Array.isArray(data.payload) ? data.payload : undefined;
  const chips = [
    payload?.name || "CAD/BIM JSON",
    payload?.source_format || "json",
    `${formatNumber(stats.drawable)} drawable`,
    data.truncated ? "truncated" : "full",
  ];
  hudNode.innerHTML = chips.map((chip) => `<span class="chip">${escapeHtml(chip)}</span>`).join("");
}

function statCard(label: string, value: number): string {
  return `<div class="stat"><span>${label}</span><strong>${formatNumber(value)}</strong></div>`;
}

function flattenProperties(value: Record<string, unknown>, prefix = ""): [string, unknown][] {
  const out: [string, unknown][] = [];
  for (const [key, item] of Object.entries(value)) {
    const name = prefix ? `${prefix}.${key}` : key;
    if (item && typeof item === "object" && !Array.isArray(item)) {
      const nested = flattenProperties(item as Record<string, unknown>, name);
      if (nested.length) {
        out.push(...nested);
      } else {
        out.push([name, item]);
      }
    } else {
      out.push([name, item]);
    }
  }
  return out;
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(formatValue).join(", ")}]`;
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => {
    const replacements: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return replacements[char] || char;
  });
}

function setStatus(message: string, error = false): void {
  statusNode.textContent = message;
  statusNode.classList.toggle("error", error);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadGraph(sourceInput.value.trim());
});

document.getElementById("fit-btn")?.addEventListener("click", () => viewer.fit());
document.getElementById("reload-btn")?.addEventListener("click", () => loadGraph(latestSource));

boot().catch((error) => {
  setStatus(error instanceof Error ? error.message : String(error), true);
});
