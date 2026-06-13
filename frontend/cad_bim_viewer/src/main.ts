import "./style.css";
import { CadBimViewer } from "./viewer-core";
import type { ClipAxis, ClipDirection } from "./viewer-core";
import type {
  CadBimElement,
  CadBimElementContext,
  CadBimGraph,
  CadBimSourceResponse,
  IfcModelSource,
  IfcRenderResult,
  IfcSelection,
  ViewerModelRecord,
  ViewerStats,
} from "./types";

type LayerRow = { name: string; count: number; visible: boolean };
type QuickSource = { id: string; label: string; source: string; ifc?: never } | { id: string; label: string; ifc: string; source?: never };
type StructureModel = { id: string; label: string; elements: CadBimElement[] };
type LesChatResponse = {
  answer?: string;
  crag_status?: string;
  effective_dataset_filter?: string;
  history_id?: number | string | null;
  cache?: string;
  sources?: unknown[];
  source_ids?: string[];
  cad_bim?: { import_id?: string | null; source_ids?: string[] };
  retrieval_trace?: {
    mode?: string;
    vector_count?: number;
    lexical_count?: number;
    merged_count?: number;
    quality_status?: string;
  };
};
type DefaultModelResponse = {
  found?: boolean;
  name?: string;
  kind?: "json" | "ifc";
  url?: string;
  message?: string;
};

const isStandaloneViewer = !location.pathname.includes("/les/cad-bim-viewer");
const standaloneDefaultSource = viewerAssetUrl("models/demo.cad_bim_graph.json");
const exportersGithubUrl = "https://github.com/proovcme/les_rag_public/tree/main/exporters";

const BUILDINGSMART_DEMO_MODELS: IfcModelSource[] = [
  {
    id: "Building-Hvac",
    label: "Здание ОВ",
    url: viewerAssetUrl("ifc-sample/Building-Hvac.ifc"),
    jsonSourcePath: "JSON/Building-Hvac.cad_bim_graph.json",
  },
  {
    id: "Building-Architecture",
    label: "Здание архитектура",
    url: viewerAssetUrl("ifc-sample/Building-Architecture.ifc"),
    jsonSourcePath: "JSON/Building-Architecture.cad_bim_graph.json",
  },
  {
    id: "Building-Structural",
    label: "Здание конструкции",
    url: viewerAssetUrl("ifc-sample/Building-Structural.ifc"),
    jsonSourcePath: "JSON/Building-Structural.cad_bim_graph.json",
  },
  {
    id: "Building-Landscaping",
    label: "Здание благоустройство",
    url: viewerAssetUrl("ifc-sample/Building-Landscaping.ifc"),
    jsonSourcePath: "JSON/Building-Landscaping.cad_bim_graph.json",
  },
  {
    id: "Infra-Bridge",
    label: "Инфра мост",
    url: viewerAssetUrl("ifc-sample/Infra-Bridge.ifc"),
  },
  {
    id: "Infra-Plumbing",
    label: "Инфра сети",
    url: viewerAssetUrl("ifc-sample/Infra-Plumbing.ifc"),
  },
  {
    id: "Infra-Rail",
    label: "Инфра рельсы",
    url: viewerAssetUrl("ifc-sample/Infra-Rail.ifc"),
  },
  {
    id: "Infra-Road",
    label: "Инфра дорога",
    url: viewerAssetUrl("ifc-sample/Infra-Road.ifc"),
  },
];

const QUICK_SOURCES: QuickSource[] = [
  {
    id: "latest",
    label: "Последний",
    source: isStandaloneViewer ? standaloneDefaultSource : "",
  },
  {
    id: "demo-ifc",
    label: "Демо",
    ifc: "demo",
  },
];

const app = document.getElementById("app");
if (!app) throw new Error("Missing #app");

app.innerHTML = `
  <main class="shell" data-tab="inspect">
    <header class="topbar">
      <div class="brand">
        <strong>LES АТЛАС</strong>
        <span>IFC / JSON / RAG</span>
      </div>
      <form class="toolbar" id="load-form">
        <input id="source-path" placeholder="Путь к источнику" autocomplete="off" />
        <button type="submit" title="Загрузить источник">Загрузить</button>
        <button type="button" id="add-file-btn" title="Добавить JSON или IFC файл">Добавить</button>
        <input id="add-file-input" type="file" accept=".json,.ifc,.ifczip,application/json" multiple hidden />
      </form>
      <nav class="quickbar" aria-label="Быстрые источники">
        ${QUICK_SOURCES.map((item) => `<button type="button" data-source-id="${item.id}">${escapeHtml(item.label)}</button>`).join("")}
      </nav>
      <div class="toolstrip" aria-label="Управление сценой">
        <button type="button" id="load-default-model" class="default-model-btn" title="Загрузить модель по умолчанию из папки models">Модель</button>
        <button type="button" id="fit-btn" title="Вписать сцену">Вписать</button>
        <button type="button" id="reload-btn" title="Перезагрузить текущий источник">Обновить</button>
        <a href="${exportersGithubUrl}" target="_blank" rel="noopener noreferrer" title="Открыть JSON exporters на GitHub">Экспортеры JSON</a>
      </div>
      <div class="status" id="status">запуск...</div>
    </header>

    <section class="viewport-wrap">
      <div id="viewer"></div>
      <div class="hud" id="hud"></div>
    </section>

    <aside class="side">
      <section class="panel panel-hero">
        <div class="panel-title">
          <h2>Граф</h2>
          <span id="mode-pill" class="pill">JSON</span>
        </div>
        <div class="stats" id="stats"></div>
        <div class="source-meta" id="source-meta"></div>
      </section>

      <div class="tabs" role="tablist" aria-label="Панели">
        <button type="button" class="active" data-tab="inspect">Инфо</button>
        <button type="button" data-tab="tools">Инструменты</button>
        <button type="button" data-tab="models">Модели</button>
        <button type="button" data-tab="structure">Структура</button>
        <button type="button" data-tab="layers">Слои</button>
        <button type="button" data-tab="source">Источник</button>
      </div>

      <section class="panel tab-panel" data-panel="inspect">
        <h2>Выбрано</h2>
        <div id="selected" class="empty">Ничего не выбрано</div>
      </section>

      <section class="panel tab-panel" data-panel="tools">
        <h2>Инструменты</h2>
        <div class="tool-card">
          <div class="tool-title">Выбор</div>
          <div class="tool-grid">
            <button type="button" id="tool-fit-selected">Вписать</button>
            <button type="button" id="tool-isolate">Изолировать</button>
            <button type="button" id="tool-hide">Скрыть</button>
            <button type="button" id="tool-show-all">Показать все</button>
          </div>
          <div class="tool-info" id="tool-selection-info">Ничего не выбрано</div>
        </div>
        <div class="tool-card">
          <div class="tool-title">Замеры</div>
          <div class="tool-grid">
            <button type="button" id="measure-distance">Расстояние</button>
            <button type="button" id="measure-clear">Очистить</button>
          </div>
          <div class="tool-info" id="measure-info">Замер выключен</div>
        </div>
        <div class="tool-card">
          <div class="tool-title">Сечение</div>
          <label class="control-row">
            <span>Включено</span>
            <input id="clip-enabled" type="checkbox" />
          </label>
          <label class="control-row">
            <span>Ось</span>
            <select id="clip-axis">
              <option value="x">X</option>
              <option value="y">Y</option>
              <option value="z">Z</option>
            </select>
          </label>
          <label class="control-row">
            <span>Направление</span>
            <select id="clip-direction">
              <option value="1">+X вправо</option>
              <option value="-1">-X влево</option>
            </select>
          </label>
          <label class="control-row">
            <span>Позиция</span>
            <input id="clip-offset" type="range" min="0" max="100" value="50" />
          </label>
          <div class="tool-grid">
            <button type="button" id="clip-clear">Убрать сечение</button>
            <button type="button" id="clip-mid">По центру</button>
          </div>
          <div class="tool-info" id="clip-info">Сечение выключено</div>
        </div>
      </section>

      <section class="panel tab-panel" data-panel="models">
        <div class="panel-title">
          <h2>Модели</h2>
          <span class="muted" id="model-count">0</span>
        </div>
        <div class="tool-grid model-actions">
          <button type="button" id="models-show-all">Показать все</button>
          <button type="button" id="models-fit-all">Вписать все</button>
        </div>
        <div class="list" id="models"></div>
      </section>

      <section class="panel tab-panel" data-panel="structure">
        <div class="panel-title">
          <h2>Структура</h2>
          <span class="muted" id="structure-count">0</span>
        </div>
        <div class="layer-tools">
          <input id="structure-filter" placeholder="Фильтр" autocomplete="off" />
        </div>
        <div class="list structure-list" id="structure"></div>
      </section>

      <section class="panel tab-panel" data-panel="layers">
        <div class="panel-title">
          <h2>Слои</h2>
          <span class="muted" id="layer-count">0</span>
        </div>
        <div class="layer-tools">
          <input id="layer-filter" placeholder="Фильтр" autocomplete="off" />
          <button type="button" id="layers-all">Все</button>
          <button type="button" id="layers-none">Ничего</button>
        </div>
        <div class="chips-row" id="layer-solos"></div>
        <div class="list" id="layers"></div>
      </section>

      <section class="panel tab-panel" data-panel="source">
        <h2>Источник</h2>
        <div class="source-card" id="source-card"></div>
      </section>
    </aside>
  </main>
`;

const viewerNode = document.getElementById("viewer")!;
const statusNode = document.getElementById("status")!;
const sourceInput = document.getElementById("source-path") as HTMLInputElement;
const addFileInput = document.getElementById("add-file-input") as HTMLInputElement;
const statsNode = document.getElementById("stats")!;
const layersNode = document.getElementById("layers")!;
const modelsNode = document.getElementById("models")!;
const modelCountNode = document.getElementById("model-count")!;
const structureNode = document.getElementById("structure")!;
const structureFilterInput = document.getElementById("structure-filter") as HTMLInputElement;
const structureCountNode = document.getElementById("structure-count")!;
const selectedNode = document.getElementById("selected")!;
const hudNode = document.getElementById("hud")!;
const form = document.getElementById("load-form") as HTMLFormElement;
const sourceMetaNode = document.getElementById("source-meta")!;
const sourceCardNode = document.getElementById("source-card")!;
const modePillNode = document.getElementById("mode-pill")!;
const layerFilterInput = document.getElementById("layer-filter") as HTMLInputElement;
const layerCountNode = document.getElementById("layer-count")!;
const layerSolosNode = document.getElementById("layer-solos")!;
const toolSelectionInfoNode = document.getElementById("tool-selection-info")!;
const clipEnabledInput = document.getElementById("clip-enabled") as HTMLInputElement;
const clipAxisInput = document.getElementById("clip-axis") as HTMLSelectElement;
const clipDirectionInput = document.getElementById("clip-direction") as HTMLSelectElement;
const clipOffsetInput = document.getElementById("clip-offset") as HTMLInputElement;
const clipInfoNode = document.getElementById("clip-info")!;
const measureInfoNode = document.getElementById("measure-info")!;

const params = new URLSearchParams(window.location.search);
const initialSource = params.get("source_path") || params.get("source") || (isStandaloneViewer ? standaloneDefaultSource : "");
const initialIfc = params.get("ifc") || params.get("ifc_path") || "";
const highlightIds = new Set(
  (params.get("highlight") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean),
);
sourceInput.value = initialSource;

let viewer: CadBimViewer;
let latestSource = initialSource;
let currentMode: "json" | "ifc" = "json";
let currentLayers: LayerRow[] = [];
let currentSource: CadBimSourceResponse | null = null;
let currentStats: ViewerStats | null = null;
let selectedElement: CadBimElement | null = null;
let currentModels: ViewerModelRecord[] = [];
let measureEnabled = false;
let selectionContextToken = 0;
const semanticByGlobalId = new Map<string, CadBimElement>();
const structureModels = new Map<string, StructureModel>();

async function boot(): Promise<void> {
  viewer = await CadBimViewer.create(viewerNode);
  (window as unknown as { __lesCadBimViewer?: CadBimViewer }).__lesCadBimViewer = viewer;
  viewer.onSelect = renderSelected;
  viewer.onIfcSelect = renderIfcSelected;
  viewer.onModelsChange = renderModels;
  viewer.onMeasure = (message) => {
    measureInfoNode.textContent = message;
  };
  if (initialIfc) {
    await loadIfcSelection(initialIfc);
  } else {
    await loadGraph(initialSource);
  }
}

async function loadGraph(sourcePath: string): Promise<void> {
  currentMode = "json";
  setStatus("загрузка...");
  try {
    latestSource = sourcePath;
    const data = await requestCadBimSource(sourcePath);
    structureModels.clear();
    const result = viewer.render(data.payload, highlightIds, {
      source: data.source || sourcePath || "последний",
      label: sourceLabel(data.payload, data.source || sourcePath || "последний"),
    });
    registerStructureModel(result.modelId, sourceLabel(data.payload, data.source || sourcePath || "последний"), result.elements);
    currentSource = data;
    currentStats = result.stats;
    renderStats(result.stats);
    renderLayers(result.stats);
    renderStructure();
    renderSelected(null);
    renderHud(data, result.stats);
    renderSource(data, result.stats);
    setStatus(`${data.source || "последний"} | элементов: ${formatNumber(data.element_count || result.stats.elements)}`);
    const focusId = params.get("focus") || [...highlightIds][0] || "";
    if (focusId) viewer.focusElement(focusId);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus(message, true);
    selectedNode.innerHTML = `<div class="empty error">${escapeHtml(message)}</div>`;
    renderStandaloneEmpty();
  }
}

async function loadIfcSelection(selection: string): Promise<void> {
  const models = ifcModelsFromSelection(selection);
  await loadIfcModels(models);
}

async function loadIfcModels(models: IfcModelSource[]): Promise<void> {
  currentMode = "ifc";
  modePillNode.textContent = "IFC";
  setStatus("загрузка IFC...");
  try {
    renderSelected(null);
    currentSource = null;
    currentStats = null;
    currentLayers = [];
    structureModels.clear();
    renderStructure();
    layersNode.innerHTML = `<div class="empty">В IFC-режиме видимость управляется через вкладку моделей.</div>`;
    layerSolosNode.innerHTML = "";
    layerCountNode.textContent = "0";
    await loadSemanticModels(models);
    const result = await viewer.renderIfcModels(models, setStatus);
    renderIfcStats(result);
    renderIfcHud(result);
    renderIfcSource(result);
    setStatus(`IFC-сцена | загружено моделей: ${result.loaded}/${result.models.length}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus(message, true);
    selectedNode.innerHTML = `<div class="empty error">${escapeHtml(message)}</div>`;
  }
}

async function loadDefaultModel(): Promise<void> {
  setStatus("поиск модели по умолчанию...");
  try {
    const response = await fetch(viewerAssetUrl("api/default-model"), {
      headers: { Accept: "application/json" },
    });
    const data = (await response.json().catch(() => null)) as DefaultModelResponse | null;
    if (!response.ok || !data?.found || !data.url || !data.kind) {
      throw new Error(data?.message || `Модель по умолчанию не найдена (${response.status})`);
    }

    const sourceUrl = viewerAssetUrl(data.url);
    const label = data.name || "Модель по умолчанию";
    sourceInput.value = data.url;
    if (data.kind === "json") {
      await loadGraph(sourceUrl);
      return;
    }

    await loadIfcModels([
      {
        id: uniqueModelId(label),
        label,
        url: sourceUrl,
      },
    ]);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus(message, true);
    selectedNode.innerHTML = `<div class="empty error">${escapeHtml(message)}</div>`;
  }
}

async function addLocalFiles(files: FileList | File[]): Promise<void> {
  const items = Array.from(files);
  if (!items.length) return;
  setStatus(`добавление файлов: ${items.length}...`);
  for (const file of items) {
    const extension = file.name.split(".").pop()?.toLowerCase() || "";
    if (extension === "json") {
      await addLocalJson(file);
      continue;
    }
    if (extension === "ifc" || extension === "ifczip") {
      await addLocalIfc(file);
      continue;
    }
    setStatus(`неподдерживаемый файл: ${file.name}`, true);
  }
}

async function addLocalJson(file: File): Promise<void> {
  const payload = JSON.parse(await file.text()) as CadBimGraph | CadBimElement[];
  const modelId = uniqueModelId(file.name);
  const result = viewer.addJsonModel(payload, highlightIds, {
    id: modelId,
    label: file.name,
    source: `локально:${file.name}`,
    replace: false,
  });
  registerStructureModel(result.modelId, file.name, result.elements);
  currentMode = "json";
  currentStats = result.stats;
  currentSource = null;
  renderStats(result.stats);
  renderLayers(result.stats);
  renderStructure();
  renderFederatedHud();
  renderStandaloneSource();
  setStatus(`добавлено: ${file.name} | элементов: ${formatNumber(result.elements.length)}`);
}

async function addLocalIfc(file: File): Promise<void> {
  const url = URL.createObjectURL(file);
  const model: IfcModelSource = {
    id: uniqueModelId(file.name),
    label: file.name,
    url,
  };
  currentMode = "ifc";
  modePillNode.textContent = "FED";
  const result = await viewer.addIfcModels([model], setStatus);
  renderIfcStats(result);
  renderFederatedHud();
  renderStandaloneSource();
  setStatus(`добавлен IFC: ${file.name}`);
}

async function loadSemanticModels(models: IfcModelSource[]): Promise<void> {
  semanticByGlobalId.clear();
  for (const model of models) {
    if (!model.jsonSourcePath) continue;
    setStatus(`загрузка JSON: ${model.label}...`);
    const data = await requestCadBimSource(model.jsonSourcePath);
    const payload = data.payload && !Array.isArray(data.payload) ? data.payload : undefined;
    for (const element of payload?.elements || []) {
      const globalId = String(element.id || element.properties?.global_id || "");
      if (globalId) semanticByGlobalId.set(globalId, element);
    }
  }
}

async function requestCadBimSource(sourcePath: string): Promise<CadBimSourceResponse> {
  if (!sourcePath.trim() && isStandaloneViewer) {
    return requestDirectJsonSource(standaloneDefaultSource);
  }

  if (isDirectJsonSource(sourcePath)) {
    return requestDirectJsonSource(sourcePath);
  }

  const query = new URLSearchParams({ max_elements: "50000" });
  if (sourcePath.trim()) query.set("source_path", sourcePath.trim());
  try {
    const response = await fetch(`/lite-api/cad-bim/source?${query.toString()}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Источник CAD/BIM ${response.status}: ${text.slice(0, 240)}`);
    }
    return (await response.json()) as CadBimSourceResponse;
  } catch (error) {
    if (sourcePath.trim()) {
      return requestDirectJsonSource(sourcePath.trim());
    }
    throw new Error("LES API недоступен. Добавь локальный JSON/IFC через кнопку `Добавить`.");
  }
}

async function requestDirectJsonSource(sourcePath: string): Promise<CadBimSourceResponse> {
  const response = await fetch(sourcePath, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`JSON ${response.status}: ${text.slice(0, 240)}`);
  }
  const payload = (await response.json()) as CadBimGraph | CadBimElement[];
  return {
    source: sourcePath,
    payload,
    element_count: Array.isArray(payload) ? payload.length : payload.elements?.length || 0,
    truncated: false,
  };
}

function renderStats(stats: ViewerStats): void {
  statsNode.innerHTML = [
    statCard("Элементы", stats.elements),
    statCard("В сцене", stats.drawable),
    statCard("Связи", stats.relations),
  ].join("");
}

function renderIfcStats(result: IfcRenderResult): void {
  statsNode.innerHTML = [
    statCard("Модели", result.loaded),
    statCard("В наборе", result.models.length),
    statCard("Связи", 0),
  ].join("");
  layersNode.innerHTML = result.models
    .map(
      (model) => `
        <div class="layer-row" title="${escapeHtml(model.id)}">
          <span></span>
          <span class="name">${escapeHtml(model.label)}</span>
          <span class="count">IFC</span>
        </div>
      `,
    )
    .join("");
}

function renderLayers(stats: ViewerStats): void {
  currentLayers = [...stats.layers.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => ({ name, count, visible: true }));
  renderLayerRows();
}

function renderLayerRows(): void {
  const filter = layerFilterInput.value.trim().toLocaleLowerCase("ru-RU");
  const rows = currentLayers.filter((row) => row.name.toLocaleLowerCase("ru-RU").includes(filter));
  layerCountNode.textContent = formatNumber(currentLayers.length);
  layerSolosNode.innerHTML = currentLayers
    .slice(0, 6)
    .map((row) => `<button type="button" data-layer-solo="${escapeHtml(row.name)}">${escapeHtml(shortLabel(row.name))}</button>`)
    .join("");
  if (!rows.length) {
    layersNode.innerHTML = `<div class="empty">Слоёв нет</div>`;
    return;
  }
  layersNode.innerHTML = rows
    .map(
      (row) => `
        <label class="layer-row" title="${escapeHtml(row.name)}">
          <input type="checkbox" data-layer="${escapeHtml(row.name)}" ${row.visible ? "checked" : ""} />
          <span class="swatch" style="--swatch:${layerColor(row.name)}"></span>
          <span class="name">${escapeHtml(row.name)}</span>
          <span class="count">${formatNumber(row.count)}</span>
        </label>
      `,
    )
    .join("");
  layersNode.querySelectorAll<HTMLInputElement>("input[data-layer]").forEach((input) => {
    input.addEventListener("change", () => {
      const layer = input.dataset.layer || "";
      const row = currentLayers.find((item) => item.name === layer);
      if (row) row.visible = input.checked;
      viewer.setLayerVisible(layer, input.checked);
    });
  });
  layerSolosNode.querySelectorAll<HTMLButtonElement>("button[data-layer-solo]").forEach((button) => {
    button.addEventListener("click", () => {
      const layer = button.dataset.layerSolo || "";
      currentLayers.forEach((row) => {
        row.visible = row.name === layer;
        viewer.setLayerVisible(row.name, row.visible);
      });
      renderLayerRows();
    });
  });
}

function renderModels(models: ViewerModelRecord[]): void {
  currentModels = models;
  modelCountNode.textContent = formatNumber(models.length);
  if (!models.length) {
    modelsNode.innerHTML = `<div class="empty">Модели не загружены</div>`;
    return;
  }
  modelsNode.innerHTML = models
    .map(
      (model) => `
        <article class="model-row" data-model-id="${escapeHtml(model.id)}">
          <label class="model-head">
            <input type="checkbox" data-model-visible="${escapeHtml(model.id)}" ${model.visible ? "checked" : ""} />
            <span class="swatch" style="--swatch:${model.kind === "ifc" ? "#a78bfa" : layerColor(model.label)}"></span>
            <span class="name">${escapeHtml(model.label)}</span>
            <span class="pill tiny">${escapeHtml(model.kind.toUpperCase())}</span>
          </label>
          <div class="model-meta">
            <span>элементов: ${formatNumber(model.elements)}</span>
            <span>в сцене: ${formatNumber(model.drawable)}</span>
          </div>
          <div class="model-buttons">
            <button type="button" data-model-fit="${escapeHtml(model.id)}">Вписать</button>
            <button type="button" data-model-solo="${escapeHtml(model.id)}">Соло</button>
            <button type="button" data-model-unload="${escapeHtml(model.id)}">Выгрузить</button>
          </div>
        </article>
      `,
    )
    .join("");
  modelsNode.querySelectorAll<HTMLInputElement>("input[data-model-visible]").forEach((input) => {
    input.addEventListener("change", () => {
      viewer.setModelVisible(input.dataset.modelVisible || "", input.checked);
    });
  });
  modelsNode.querySelectorAll<HTMLButtonElement>("button[data-model-fit]").forEach((button) => {
    button.addEventListener("click", () => viewer.fitModel(button.dataset.modelFit || ""));
  });
  modelsNode.querySelectorAll<HTMLButtonElement>("button[data-model-solo]").forEach((button) => {
    button.addEventListener("click", () => viewer.isolateModel(button.dataset.modelSolo || ""));
  });
  modelsNode.querySelectorAll<HTMLButtonElement>("button[data-model-unload]").forEach((button) => {
    button.addEventListener("click", () => {
      const modelId = button.dataset.modelUnload || "";
      viewer.removeModel(modelId);
      structureModels.delete(modelId);
      renderStructure();
      renderFederatedHud();
    });
  });
}

function registerStructureModel(id: string, label: string, elements: CadBimElement[]): void {
  structureModels.set(id, { id, label, elements: elements.filter((element) => element.category !== "Model") });
}

function renderStructure(): void {
  const filter = structureFilterInput.value.trim().toLocaleLowerCase("ru-RU");
  const rows: string[] = [];
  let groupCount = 0;
  for (const model of structureModels.values()) {
    const hierarchy = buildStructure(model.elements);
    const modelMatches = model.label.toLocaleLowerCase("ru-RU").includes(filter);
    const body = [...hierarchy.entries()]
      .map(([level, categories]) => {
        const categoryRows = [...categories.entries()]
          .map(([category, count]) => {
            const text = `${level} ${category}`.toLocaleLowerCase("ru-RU");
            if (filter && !modelMatches && !text.includes(filter)) return "";
            groupCount += 1;
            return `
              <div class="structure-row">
                <span class="level">${escapeHtml(level)}</span>
                <span class="name">${escapeHtml(category)}</span>
                <span class="count">${formatNumber(count)}</span>
              </div>
            `;
          })
          .join("");
        return categoryRows;
      })
      .join("");
    if (!body && filter && !modelMatches) continue;
    rows.push(`
      <details class="structure-model" open>
        <summary>${escapeHtml(model.label)} <span>${formatNumber(model.elements.length)}</span></summary>
        ${body || `<div class="empty">Совпадений нет</div>`}
      </details>
    `);
  }
  structureCountNode.textContent = formatNumber(groupCount);
  structureNode.innerHTML = rows.length ? rows.join("") : `<div class="empty">Структура JSON не загружена</div>`;
}

function renderSelected(element: CadBimElement | null): void {
  selectedElement = element;
  const token = ++selectionContextToken;
  renderToolSelectionInfo(element);
  if (!element) {
    selectedNode.innerHTML = `<div class="empty">Ничего не выбрано</div>`;
    return;
  }
  const sourceId = selectionSourceId(element);
  const props = flattenProperties(element.properties || {});
  const meshStats = flattenProperties(element.geometry?.stats || {}, "mesh").slice(0, 4);
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
  const rows = baseRows.concat(meshStats).concat(props.slice(0, 30)).filter(([, value]) => value !== "");

  selectedNode.innerHTML = `
    <article class="selection-card">
      <div class="selection-head">
        <span class="swatch large" style="--swatch:${layerColor(element.layer || element.category || "")}"></span>
        <div>
          <strong>${escapeHtml(element.name || element.type || "Элемент")}</strong>
          <span>${escapeHtml([element.category, element.family, element.level].filter(Boolean).join(" / "))}</span>
        </div>
      </div>
    </article>
    <div class="list props-list">
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
    ${renderLesContextShell(sourceId)}
  `;
  void hydrateLesContext(sourceId, token);
}

function renderIfcSelected(selection: IfcSelection | null): void {
  selectedElement = null;
  const token = ++selectionContextToken;
  toolSelectionInfoNode.textContent = selection ? `${selection.globalId || selection.modelId}:${selection.localId}` : "IFC-элемент не выбран";
  if (!selection) {
    selectedNode.innerHTML = `<div class="empty">IFC-элемент не выбран</div>`;
    return;
  }
  const baseRows: [string, unknown][] = [
    ["model_id", selection.modelId],
    ["local_id", selection.localId],
    ["global_id", selection.globalId],
  ];
  const semantic = semanticByGlobalId.get(selection.globalId);
  const semanticBaseRows: [string, unknown][] = semantic
    ? ([
        ["les_json.type", semantic.type || semantic.object_type || ""],
        ["les_json.name", semantic.name || ""],
        ["les_json.category", semantic.category || ""],
        ["les_json.family", semantic.family || ""],
        ["les_json.material", semantic.material || ""],
      ] as [string, unknown][])
    : [["les_json", "не найдено по GlobalId"]];
  const semanticRows = semanticBaseRows.concat(
    semantic
      ? flattenProperties((semantic as CadBimElement & { propertySets?: Record<string, unknown> }).propertySets || {}, "les_json.pset").slice(0, 18)
      : [],
  );
  const rows = baseRows
    .concat(semanticRows)
    .concat(selection.rows.filter(([, value]) => value !== "" && value != null).slice(0, 20));
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
    ${renderLesContextShell(selection.globalId)}
  `;
  void hydrateLesContext(selection.globalId, token);
}

function selectionSourceId(element: CadBimElement): string {
  const props = element.properties || {};
  const parameters = props.parameters as Record<string, unknown> | undefined;
  return String(
    element.id ||
      props.global_id ||
      props.GlobalId ||
      props.IfcGUID ||
      parameters?.IfcGUID ||
      parameters?.GlobalId ||
      "",
  );
}

function renderLesContextShell(sourceId: string): string {
  if (!sourceId) {
    return `<article class="rag-card"><strong>LES/RAG</strong><div class="empty">У элемента нет стабильного id для поиска в graph DB.</div></article>`;
  }
  if (isStandaloneViewer) {
    return `
      <article class="rag-card">
        <div class="selection-head">
          <span class="swatch large" style="--swatch:#38bdf8"></span>
          <div>
            <strong>LES/RAG</strong>
            <span>source_id: ${escapeHtml(sourceId)}</span>
          </div>
        </div>
        <div class="empty">Standalone не обращается к LES. Открой viewer из LES, чтобы получить RAG-контекст выбранного элемента.</div>
      </article>
    `;
  }
  return `
    <article class="rag-card" id="les-rag-context" data-source-id="${escapeHtml(sourceId)}">
      <div class="selection-head">
        <span class="swatch large" style="--swatch:#38bdf8"></span>
        <div>
          <strong>LES/RAG</strong>
          <span>source_id: ${escapeHtml(sourceId)}</span>
        </div>
      </div>
      <div class="empty">ищу элемент в graph DB...</div>
    </article>
  `;
}

async function hydrateLesContext(sourceId: string, token: number): Promise<void> {
  if (!sourceId || isStandaloneViewer) return;
  const node = document.getElementById("les-rag-context");
  if (!node) return;
  try {
    const context = await requestElementContext(sourceId);
    if (token !== selectionContextToken) return;
    renderLesContext(node, context);
  } catch (error) {
    if (token !== selectionContextToken) return;
    const message = error instanceof Error ? error.message : String(error);
    node.innerHTML = `
      <div class="selection-head">
        <span class="swatch large" style="--swatch:#ef4444"></span>
        <div>
          <strong>LES/RAG</strong>
          <span>source_id: ${escapeHtml(sourceId)}</span>
        </div>
      </div>
      <div class="empty error">${escapeHtml(message)}</div>
    `;
  }
}

async function requestElementContext(sourceId: string): Promise<CadBimElementContext> {
  const query = new URLSearchParams({ source_id: sourceId });
  const response = await fetch(`/lite-api/cad-bim/element?${query.toString()}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(response.status === 404 ? "элемент не найден в LES graph DB" : `LES/RAG ${response.status}: ${text.slice(0, 180)}`);
  }
  return (await response.json()) as CadBimElementContext;
}

function renderLesContext(node: HTMLElement, context: CadBimElementContext): void {
  const element = context.element;
  const rows: [string, unknown][] = [
    ["import_id", context.summary.import_id],
    ["profile", context.summary.profile],
    ["source", context.summary.source],
    ["projection", context.summary.projection_path],
    ["type", element.object_type || element.speckle_type || ""],
    ["category", element.category || ""],
    ["family", element.family || ""],
    ["level", element.level || ""],
    ["material", element.material || ""],
    ["properties", context.summary.properties],
    ["relations", context.summary.relations],
  ];
  node.innerHTML = `
    <div class="selection-head">
      <span class="swatch large" style="--swatch:#38bdf8"></span>
      <div>
        <strong>LES/RAG найден</strong>
        <span>${escapeHtml(context.summary.title || context.source_id)}</span>
      </div>
    </div>
    <div class="tool-grid rag-actions">
      <button type="button" id="copy-rag-prompt">Копировать вопрос</button>
      <button type="button" id="ask-les-rag">Спросить LES</button>
    </div>
    <div id="les-rag-answer" class="rag-answer empty">Ответ появится здесь.</div>
    <div class="list props-list compact">
      ${rows.map(([key, value]) => propLine(key, value)).join("")}
    </div>
  `;
  document.getElementById("copy-rag-prompt")?.addEventListener("click", () => {
    void copyText(context.rag_prompt);
  });
  document.getElementById("ask-les-rag")?.addEventListener("click", () => {
    void askLesForElement(context);
  });
}

async function askLesForElement(context: CadBimElementContext): Promise<void> {
  const answerNode = document.getElementById("les-rag-answer");
  const button = document.getElementById("ask-les-rag") as HTMLButtonElement | null;
  if (!answerNode) return;
  const previousLabel = button?.textContent || "Спросить LES";
  if (button) {
    button.disabled = true;
    button.textContent = "Спрашиваю...";
  }
  answerNode.classList.remove("error");
  answerNode.classList.add("empty");
  answerNode.textContent = "LES ищет контекст и готовит ответ...";
  try {
    const response = await fetch("/lite-api/chat", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        question: context.rag_prompt,
        dataset_filter: "CAD_BIM",
      }),
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(response.status === 401 ? "нужен LES trusted/key доступ" : `chat ${response.status}: ${text.slice(0, 220)}`);
    }
    const data = JSON.parse(text) as LesChatResponse;
    renderLesAnswer(answerNode, data);
    const highlighted = highlightFromAnswer(data, "LES");
    setStatus(highlighted ? "LES ответил и подсветил элементы" : "LES ответил по выбранному элементу");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    answerNode.classList.add("error");
    answerNode.classList.remove("empty");
    answerNode.innerHTML = `<strong>Ошибка LES</strong><div>${escapeHtml(message)}</div>`;
    setStatus("LES/RAG вопрос не выполнен", true);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = previousLabel;
    }
  }
}

function renderLesAnswer(node: HTMLElement, data: LesChatResponse): void {
  const trace = data.retrieval_trace || {};
  const meta = [
    data.crag_status ? `CRAG: ${data.crag_status}` : "",
    data.effective_dataset_filter ? `filter: ${data.effective_dataset_filter}` : "",
    trace.mode ? `mode: ${trace.mode}` : "",
    typeof trace.merged_count === "number" ? `chunks: ${trace.merged_count}` : "",
  ].filter(Boolean);
  node.classList.remove("empty", "error");
  node.innerHTML = `
    <div class="rag-answer-head">
      <strong>Ответ LES</strong>
      ${meta.length ? `<span>${escapeHtml(meta.join(" / "))}</span>` : ""}
    </div>
    <div class="rag-answer-text">${escapeHtml(data.answer || "LES не вернул текст ответа.")}</div>
    ${renderLesSources(data.sources || [])}
  `;
}

function renderLesSources(sources: unknown[]): string {
  if (!sources.length) return "";
  const items = sources.slice(0, 6).map((source) => {
    if (typeof source === "string") return source;
    if (source && typeof source === "object") {
      const item = source as Record<string, unknown>;
      return String(item.title || item.name || item.source || item.filename || item.doc_name || JSON.stringify(item));
    }
    return String(source);
  });
  return `
    <div class="rag-sources">
      <span>Источники</span>
      ${items.map((item) => `<div>${escapeHtml(item)}</div>`).join("")}
    </div>
  `;
}

// W6.7: применить подсветку из ответа чата к загруженной модели.
function highlightFromAnswer(data: LesChatResponse, who: string): boolean {
  const ids = data.source_ids || data.cad_bim?.source_ids || [];
  if (!ids.length) return false;
  const matched = viewer.applyHighlight(ids);
  if (matched > 0) {
    viewer.focusElement(ids[0]);
    setStatus(`${who} подсветил элементов: ${matched}`);
    return true;
  }
  return false;
}

// W6.7: кросс-вкладка — вьювер поллит последнюю подсветку из proxy. Любой клиент
// (чат Совушки, lite, внешний контур) задаёт source_ids → АТЛАС перекрашивает.
let lastHighlightSeq = -1;
async function pollHighlight(): Promise<void> {
  try {
    const response = await fetch("/lite-api/cad-bim/highlight", { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const data = (await response.json()) as { seq?: number; source_ids?: string[] };
    const seq = Number(data.seq || 0);
    if (lastHighlightSeq < 0) {
      lastHighlightSeq = seq; // базовый уровень при загрузке — не реагируем на старый снимок
      return;
    }
    if (seq <= lastHighlightSeq) return;
    lastHighlightSeq = seq;
    const ids = Array.isArray(data.source_ids) ? data.source_ids : [];
    if (ids.length && viewer.applyHighlight(ids) > 0) {
      viewer.focusElement(ids[0]);
      setStatus(`Чат подсветил элементов: ${ids.length}`);
    }
  } catch {
    /* поллинг подсветки не должен мешать вьюверу */
  }
}
window.setInterval(() => {
  void pollHighlight();
}, 2500);

async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
    setStatus("RAG-вопрос скопирован");
  } catch {
    window.prompt("Скопируй RAG-вопрос", value);
  }
}

function renderHud(data: CadBimSourceResponse, stats: ViewerStats): void {
  const payload = data.payload && !Array.isArray(data.payload) ? data.payload : undefined;
  const chips = [
    payload?.name || "CAD/BIM JSON",
    payload?.source_format || "json",
    `в сцене: ${formatNumber(stats.drawable)}`,
    data.truncated ? "обрезано" : "полностью",
  ];
  hudNode.innerHTML = chips.map((chip) => `<span class="chip">${escapeHtml(chip)}</span>`).join("");
  modePillNode.textContent = String(payload?.source_format || "JSON").toUpperCase();
}

function renderIfcHud(result: IfcRenderResult): void {
  const chips = ["IFC-фрагменты", "модели buildingSMART", `загружено: ${result.loaded}`, "мост GlobalId"];
  if (semanticByGlobalId.size) chips.push(`JSON-элементов: ${formatNumber(semanticByGlobalId.size)}`);
  hudNode.innerHTML = chips.map((chip) => `<span class="chip">${escapeHtml(chip)}</span>`).join("");
}

function renderFederatedHud(): void {
  const jsonCount = currentModels.filter((model) => model.kind === "json").length;
  const ifcCount = currentModels.filter((model) => model.kind === "ifc").length;
  const chips = ["Федеративная сцена", `моделей: ${formatNumber(currentModels.length)}`];
  if (jsonCount) chips.push(`${formatNumber(jsonCount)} JSON`);
  if (ifcCount) chips.push(`${formatNumber(ifcCount)} IFC`);
  hudNode.innerHTML = chips.map((chip) => `<span class="chip">${escapeHtml(chip)}</span>`).join("");
  modePillNode.textContent = currentModels.length > 1 ? "FED" : currentMode.toUpperCase();
}

function renderSource(data: CadBimSourceResponse, stats: ViewerStats): void {
  const payload = data.payload && !Array.isArray(data.payload) ? data.payload : undefined;
  const meshCount = payload?.elements?.filter((element) => element.geometry?.type === "mesh").length || 0;
  sourceMetaNode.innerHTML = `
    <span>${escapeHtml(payload?.name || "CAD/BIM JSON")}</span>
    <span>mesh: ${formatNumber(meshCount)}</span>
  `;
  sourceCardNode.innerHTML = `
    ${propLine("источник", data.source || "последний")}
    ${propLine("модель", payload?.name || "")}
    ${propLine("формат", payload?.source_format || "json")}
    ${propLine("элементы", formatNumber(stats.elements))}
    ${propLine("в сцене", formatNumber(stats.drawable))}
    ${propLine("mesh", formatNumber(meshCount))}
    ${propLine("связи", formatNumber(stats.relations))}
  `;
}

function renderIfcSource(result: IfcRenderResult): void {
  sourceMetaNode.innerHTML = `<span>IFC-фрагменты</span><span>загружено: ${formatNumber(result.loaded)}</span>`;
  sourceCardNode.innerHTML = result.models.map((model) => propLine(model.id, model.url)).join("");
}

function renderStandaloneSource(): void {
  const models = currentModels.length ? currentModels : viewer.sceneModels();
  sourceMetaNode.innerHTML = `<span>Сцена готова к standalone</span><span>моделей: ${formatNumber(models.length)}</span>`;
  sourceCardNode.innerHTML = models
    .map((model) => propLine(`${model.kind}:${model.label}`, model.source || model.id))
    .join("");
}

function renderStandaloneEmpty(): void {
  statsNode.innerHTML = [statCard("Элементы", 0), statCard("В сцене", 0), statCard("Связи", 0)].join("");
  sourceMetaNode.innerHTML = `<span>Standalone</span><span>локальные файлы</span>`;
  sourceCardNode.innerHTML = propLine("режим", "Добавь JSON/IFC файлы локально или укажи прямой JSON URL");
  hudNode.innerHTML = [`<span class="chip">Standalone</span>`, `<span class="chip">JSON / IFC</span>`].join("");
  renderModels(viewer?.sceneModels?.() || []);
  renderStructure();
}

function renderToolSelectionInfo(element: CadBimElement | null): void {
  if (!element) {
    toolSelectionInfoNode.textContent = "Ничего не выбрано";
    return;
  }
  const props = element.properties || {};
  const ifcGuid = String((props.parameters as Record<string, unknown> | undefined)?.IfcGUID || props.IfcGUID || "");
  const chunks = [
    element.type || element.object_type || "Элемент",
    element.category || "",
    element.level || "",
    ifcGuid ? `IfcGUID ${ifcGuid}` : "",
  ].filter(Boolean);
  toolSelectionInfoNode.textContent = chunks.join(" / ");
}

function applyClip(): void {
  const axis = clipAxisInput.value as ClipAxis;
  const direction = Number(clipDirectionInput.value) === -1 ? -1 : 1;
  const offset = Number(clipOffsetInput.value) / 100;
  viewer.setClipPlane(axis, clipEnabledInput.checked, offset, direction as ClipDirection);
  renderClipInfo();
}

function renderClipInfo(): void {
  const state = viewer.clipState();
  const active = (Object.entries(state) as [ClipAxis, { enabled: boolean; offset: number; direction: ClipDirection }][])
    .filter(([, value]) => value.enabled)
    .map(([axis, value]) => `${axis.toUpperCase()}${value.direction > 0 ? "+" : "-"} ${Math.round(value.offset * 100)}%`);
  clipInfoNode.textContent = active.length ? active.join(" / ") : "Сечение выключено";
}

function updateClipDirectionOptions(): void {
  const axis = clipAxisInput.value as ClipAxis;
  const labels: Record<ClipAxis, [string, string]> = {
    x: ["+X вправо", "-X влево"],
    y: ["+Y вверх", "-Y вниз"],
    z: ["+Z вперёд", "-Z назад"],
  };
  const current = clipDirectionInput.value === "-1" ? "-1" : "1";
  clipDirectionInput.innerHTML = `
    <option value="1">${labels[axis][0]}</option>
    <option value="-1">${labels[axis][1]}</option>
  `;
  clipDirectionInput.value = current;
}

function statCard(label: string, value: number): string {
  return `<div class="stat"><span>${label}</span><strong>${formatNumber(value)}</strong></div>`;
}

function propLine(key: string, value: unknown): string {
  return `
    <div class="prop-row">
      <span class="key">${escapeHtml(key)}</span>
      <span class="value">${escapeHtml(formatValue(value))}</span>
    </div>
  `;
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

function shortLabel(value: string): string {
  return value.length > 18 ? `${value.slice(0, 17)}…` : value;
}

function layerColor(layer: string): string {
  const palette = ["#38bdf8", "#22c55e", "#f59e0b", "#ef4444", "#a78bfa", "#14b8a6", "#f97316", "#e879f9", "#84cc16"];
  let hash = 0;
  for (let index = 0; index < layer.length; index++) {
    hash = ((hash << 5) - hash + layer.charCodeAt(index)) | 0;
  }
  return palette[Math.abs(hash) % palette.length];
}

function sourceLabel(payload: CadBimSourceResponse["payload"], fallback: string): string {
  if (payload && !Array.isArray(payload)) {
    return payload.name || payload.id || fallback.split("/").pop() || fallback;
  }
  return fallback.split("/").pop() || "CAD/BIM JSON";
}

function uniqueModelId(label: string): string {
  const base = label
    .replace(/\.[^.]+$/g, "")
    .replace(/[^a-z0-9_-]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
    .toLowerCase() || "model";
  let candidate = base;
  let index = 2;
  const existing = new Set(currentModels.map((model) => model.id));
  while (existing.has(candidate)) {
    candidate = `${base}-${index++}`;
  }
  return candidate;
}

function buildStructure(elements: CadBimElement[]): Map<string, Map<string, number>> {
  const levels = new Map<string, Map<string, number>>();
  for (const element of elements) {
    const level = String(element.level || "Без уровня");
    const category = String(element.category || element.family || element.type || element.object_type || "Элемент");
    const categories = levels.get(level) || new Map<string, number>();
    categories.set(category, (categories.get(category) || 0) + 1);
    levels.set(level, categories);
  }
  return new Map(
    [...levels.entries()]
      .sort(([a], [b]) => a.localeCompare(b, "ru"))
      .map(([level, categories]) => [
        level,
        new Map([...categories.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ru"))),
      ]),
  );
}

function ifcModelsFromSelection(selection: string): IfcModelSource[] {
  const normalized = selection.trim();
  if (!normalized || normalized === "demo" || normalized === "building") return BUILDINGSMART_DEMO_MODELS;
  if (normalized === "hvac") return BUILDINGSMART_DEMO_MODELS.filter((model) => model.id === "Building-Hvac");
  const byId = BUILDINGSMART_DEMO_MODELS.find((model) => model.id === normalized || `${model.id}.ifc` === normalized);
  if (byId) return [byId];
  const label = normalized.split("/").pop() || normalized;
  return [{ id: label.replace(/\.ifc$/i, ""), label, url: directIfcUrl(normalized) }];
}

function directIfcUrl(path: string): string {
  const normalized = path.trim();
  if (
    /^https?:\/\//i.test(normalized) ||
    normalized.startsWith("blob:") ||
    normalized.startsWith("/") ||
    normalized.startsWith("./") ||
    normalized.startsWith("../")
  ) {
    return normalized;
  }
  return viewerAssetUrl(normalized);
}

function viewerAssetUrl(path: string): string {
  const meta = import.meta as unknown as { env?: { BASE_URL?: string } };
  const base = meta.env?.BASE_URL || viewerRuntimeBase();
  return `${base.endsWith("/") ? base : `${base}/`}${path}`;
}

function viewerRuntimeBase(): string {
  const script = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/"], script[type="module"][src*="assets/"]');
  if (!script?.src) return `${window.location.origin}/les/cad-bim-viewer/`;
  const url = new URL(script.src, window.location.href);
  url.pathname = url.pathname.replace(/assets\/[^/]+$/, "");
  url.search = "";
  url.hash = "";
  return url.toString();
}

function isDirectJsonSource(sourcePath: string): boolean {
  const value = sourcePath.trim();
  if (!value) return false;
  return (
    /^https?:\/\//i.test(value) ||
    value.startsWith("./") ||
    value.startsWith("../") ||
    value.startsWith("/") ||
    value.startsWith("models/") ||
    value.endsWith(".json")
  );
}

function setStatus(message: string, error = false): void {
  statusNode.textContent = message;
  statusNode.classList.toggle("error", error);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadGraph(sourceInput.value.trim());
});

document.getElementById("load-default-model")?.addEventListener("click", () => {
  void loadDefaultModel();
});
document.getElementById("fit-btn")?.addEventListener("click", () => viewer.fit());
document.getElementById("reload-btn")?.addEventListener("click", () => {
  if (currentMode === "ifc") {
    void loadIfcModels(BUILDINGSMART_DEMO_MODELS);
  } else {
    void loadGraph(latestSource);
  }
});
document.getElementById("add-file-btn")?.addEventListener("click", () => addFileInput.click());
addFileInput.addEventListener("change", async () => {
  await addLocalFiles(addFileInput.files || []);
  addFileInput.value = "";
});
document.getElementById("tool-fit-selected")?.addEventListener("click", () => {
  if (!viewer.focusSelected() && selectedElement?.id) viewer.focusElement(selectedElement.id);
});
document.getElementById("tool-hide")?.addEventListener("click", () => {
  if (!viewer.hideSelected()) setStatus("сначала выбери элемент", true);
});
document.getElementById("tool-isolate")?.addEventListener("click", () => {
  if (!viewer.isolateSelected()) setStatus("сначала выбери элемент", true);
});
document.getElementById("tool-show-all")?.addEventListener("click", () => {
  viewer.showAll();
  currentLayers.forEach((row) => (row.visible = true));
  renderLayerRows();
});
document.getElementById("measure-distance")?.addEventListener("click", () => {
  measureEnabled = !measureEnabled;
  viewer.setMeasureMode(measureEnabled);
  document.getElementById("measure-distance")?.classList.toggle("active", measureEnabled);
});
document.getElementById("measure-clear")?.addEventListener("click", () => viewer.clearMeasurements());
clipEnabledInput.addEventListener("change", applyClip);
clipAxisInput.addEventListener("change", () => {
  updateClipDirectionOptions();
  applyClip();
});
clipDirectionInput.addEventListener("change", applyClip);
clipOffsetInput.addEventListener("input", applyClip);
document.getElementById("clip-clear")?.addEventListener("click", () => {
  clipEnabledInput.checked = false;
  viewer.clearClipPlanes();
  renderClipInfo();
});
document.getElementById("clip-mid")?.addEventListener("click", () => {
  clipOffsetInput.value = "50";
  applyClip();
});
document.querySelectorAll<HTMLButtonElement>("button[data-source-id]").forEach((button) => {
  button.addEventListener("click", async () => {
    const item = QUICK_SOURCES.find((source) => source.id === button.dataset.sourceId);
    if (!item) return;
    const source = item.source;
    if (source != null) {
      sourceInput.value = source;
      await loadGraph(source);
    } else {
      await loadIfcSelection(item.ifc);
    }
  });
});
document.querySelectorAll<HTMLButtonElement>(".tabs button[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tab = button.dataset.tab || "inspect";
    document.querySelectorAll<HTMLButtonElement>(".tabs button[data-tab]").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelector(".shell")?.setAttribute("data-tab", tab);
  });
});
layerFilterInput.addEventListener("input", renderLayerRows);
document.getElementById("layers-all")?.addEventListener("click", () => {
  currentLayers.forEach((row) => {
    row.visible = true;
    viewer.setLayerVisible(row.name, true);
  });
  renderLayerRows();
});
document.getElementById("layers-none")?.addEventListener("click", () => {
  currentLayers.forEach((row) => {
    row.visible = false;
    viewer.setLayerVisible(row.name, false);
  });
  renderLayerRows();
});
document.getElementById("models-show-all")?.addEventListener("click", () => {
  viewer.showAll();
  currentLayers.forEach((row) => (row.visible = true));
  renderLayerRows();
});
document.getElementById("models-fit-all")?.addEventListener("click", () => viewer.fit());
structureFilterInput.addEventListener("input", renderStructure);

updateClipDirectionOptions();
boot().catch((error) => {
  setStatus(error instanceof Error ? error.message : String(error), true);
});
