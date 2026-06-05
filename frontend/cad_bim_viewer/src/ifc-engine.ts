import * as THREE from "three";
import * as OBC from "@thatopen/components";
import * as OBF from "@thatopen/components-front";
import type { IfcModelSource, IfcRenderResult, IfcSelection } from "./types";

export interface IfcEngineOptions {
  components: OBC.Components;
  world: OBC.World;
  root: THREE.Group;
  requestRender: () => void;
  onSelect: (selection: IfcSelection | null) => void;
}

export class IfcEngine {
  readonly components: OBC.Components;

  readonly world: OBC.World;

  readonly root: THREE.Group;

  fragments: any = null;

  private ifcLoader: any = null;

  private highlighter: any = null;

  private ready = false;

  private readonly requestRender: () => void;

  private readonly emitSelect: (selection: IfcSelection | null) => void;

  constructor(options: IfcEngineOptions) {
    this.components = options.components;
    this.world = options.world;
    this.root = options.root;
    this.requestRender = options.requestRender;
    this.emitSelect = options.onSelect;
  }

  async loadModels(models: IfcModelSource[], onProgress?: (message: string) => void, replace = true): Promise<IfcRenderResult> {
    if (replace) this.clear();
    await this.ensureReady();
    let loaded = 0;
    for (const model of models) {
      onProgress?.(`загрузка ${model.label}...`);
      const bytes = await this.fetchBytes(model.url);
      await this.loadIfcBytes(bytes, model.id);
      loaded += 1;
      onProgress?.(`загружено ${loaded}/${models.length}: ${model.label}`);
    }
    await this.fragments?.core?.update?.(true);
    this.requestRender();
    return { models, loaded };
  }

  async highlightByGuids(globalIds: string[]): Promise<number> {
    await this.ensureReady();
    const map: Record<string, Set<number>> = {};
    let count = 0;
    for (const [modelId, model] of this.fragments.list) {
      const localIds = await model.getLocalIdsByGuids(globalIds);
      const hits = localIds.filter((id: number | null): id is number => id !== null);
      if (!hits.length) continue;
      map[modelId] = new Set(hits);
      count += hits.length;
    }
    if (!count) return 0;
    await this.highlighter.highlightByID("select", map, false, false);
    return count;
  }

  clear(): void {
    this.highlighter?.clear?.("select");
    this.emitSelect(null);
    for (const child of [...this.root.children]) {
      this.root.remove(child);
    }
  }

  modelObject(modelId: string): THREE.Object3D | null {
    const model = this.fragments?.list?.get?.(modelId);
    return model?.object || null;
  }

  setModelVisible(modelId: string, visible: boolean): boolean {
    const object = this.modelObject(modelId);
    if (!object) return false;
    object.visible = visible;
    this.requestRender();
    return true;
  }

  removeModel(modelId: string): boolean {
    const object = this.modelObject(modelId);
    if (!object) return false;
    this.root.remove(object);
    this.fragments?.list?.delete?.(modelId);
    this.highlighter?.clear?.("select");
    this.emitSelect(null);
    this.requestRender();
    return true;
  }

  async handleSelection(modelIdMap: Record<string, Set<number>>): Promise<void> {
    for (const [modelId, localIdSet] of Object.entries(modelIdMap)) {
      const localIds = [...localIdSet];
      if (!localIds.length) continue;
      const model = this.fragments?.list?.get(modelId);
      if (!model) continue;
      const localId = localIds[0];
      const guids = await model.getGuidsByLocalIds?.([localId]);
      const globalId = String(guids?.[0] || "");
      const rows = await this.itemRows(model, localId);
      this.emitSelect({ modelId, localId, globalId, rows });
      return;
    }
    this.emitSelect(null);
  }

  async ensureReady(): Promise<void> {
    if (this.ready) return;
    this.fragments = this.components.get((OBC as any).FragmentsManager);
    this.fragments.init(`${viewerBase()}fragments/worker.mjs`);
    (this.world.camera as any).controls.addEventListener("rest", () => this.fragments?.core?.update?.(true));
    (this.world.camera as any).projection.onChanged.add(() => {
      for (const [, model] of this.fragments.list) model.useCamera(this.world.camera.three);
    });
    this.fragments.list.onItemSet.add(async ({ value: model }: { key: string; value: any }) => {
      model.useCamera(this.world.camera.three);
      model.getClippingPlanesEvent = () => Array.from(this.world.renderer?.three.clippingPlanes || []);
      this.root.add(model.object);
      await this.fragments.core.update(true);
      this.requestRender();
    });

    this.ifcLoader = this.components.get((OBC as any).IfcLoader);
    await this.ifcLoader.setup({
      autoSetWasm: false,
      wasm: { absolute: true, path: `${window.location.origin}${viewerBase()}web-ifc/` },
    });

    this.highlighter = this.components.get(OBF.Highlighter);
    this.highlighter.setup({
      world: this.world,
      selectMaterialDefinition: {
        color: new THREE.Color("#facc15"),
        renderedFaces: 1,
        opacity: 1,
        transparent: false,
      },
    });
    this.highlighter.events.select.onHighlight.add((modelIdMap: Record<string, Set<number>>) => {
      void this.handleSelection(modelIdMap);
    });
    this.highlighter.events.select.onClear.add(() => this.emitSelect(null));
    this.ready = true;
  }

  private async fetchBytes(url: string): Promise<Uint8Array> {
    const response = await fetch(url, { headers: { Accept: "application/octet-stream" } });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`IFC ${response.status}: ${text.slice(0, 180)}`);
    }
    return new Uint8Array(await response.arrayBuffer());
  }

  private async loadIfcBytes(bytes: Uint8Array, modelId: string): Promise<void> {
    const load = this.ifcLoader.load(bytes, true, modelId);
    const timeout = new Promise((_, reject) =>
      window.setTimeout(() => reject(new Error(`IFC parse timeout: ${modelId}`)), 30000),
    );
    await Promise.race([load, timeout]);
  }

  private async itemRows(model: any, localId: number): Promise<[string, unknown][]> {
    try {
      const data = await model.getItemsData([localId], {
        attributesDefault: true,
        relations: { IsDefinedBy: { attributes: true, relations: true } },
        relationsDefault: { attributes: false, relations: false },
      });
      return flattenIfcData(data?.[0]).slice(0, 36);
    } catch (error) {
      return [["properties_error", error instanceof Error ? error.message : String(error)]];
    }
  }
}

function viewerBase(): string {
  const meta = import.meta as unknown as { env?: { BASE_URL?: string } };
  const base = meta.env?.BASE_URL || viewerRuntimeBase();
  return base.endsWith("/") ? base : `${base}/`;
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

function flattenIfcData(value: unknown, prefix = ""): [string, unknown][] {
  if (!value || typeof value !== "object") return [];
  const out: [string, unknown][] = [];
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    const name = prefix ? `${prefix}.${key}` : key;
    if (Array.isArray(item)) {
      for (let index = 0; index < Math.min(item.length, 6); index++) {
        out.push(...flattenIfcData(item[index], `${name}.${index}`));
      }
      continue;
    }
    if (item && typeof item === "object" && "value" in item) {
      out.push([name, (item as { value: unknown }).value]);
      continue;
    }
    if (item && typeof item === "object") {
      out.push(...flattenIfcData(item, name));
    }
  }
  return out;
}
