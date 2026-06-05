import * as THREE from "three";
import * as OBC from "@thatopen/components";
import * as BUI from "@thatopen/ui";
import {
  buildStats,
  createDrawables,
  elementLayer,
  graphElements,
  graphRelations,
  relationEndpointId,
} from "./cad-bim-adapter";
import { IfcEngine } from "./ifc-engine";
import type {
  CadBimElement,
  CadBimGraph,
  IfcModelSource,
  IfcRenderResult,
  IfcSelection,
  ViewerModelRecord,
  ViewerStats,
} from "./types";

export interface RenderResult {
  elements: CadBimElement[];
  selected: CadBimElement | null;
  stats: ViewerStats;
  modelId: string;
}

export type ClipAxis = "x" | "y" | "z";
export type ClipDirection = 1 | -1;

export interface RenderOptions {
  id?: string;
  label?: string;
  source?: string;
  replace?: boolean;
}

interface JsonSceneModel {
  id: string;
  label: string;
  source?: string;
  root: THREE.Group;
  elements: CadBimElement[];
  relations: ReturnType<typeof graphRelations>;
  stats: ViewerStats;
  visible: boolean;
}

export class CadBimViewer {
  readonly components: OBC.Components;

  readonly world: OBC.World;

  private readonly container: HTMLElement;

  private readonly viewport: BUI.Viewport;

  private readonly root = new THREE.Group();

  private readonly ifcRoot = new THREE.Group();

  private readonly layerGroups = new Map<string, Set<THREE.Group>>();

  private readonly jsonModels = new Map<string, JsonSceneModel>();

  private readonly ifcModels = new Map<string, ViewerModelRecord>();

  private readonly measurementRoot = new THREE.Group();

  private readonly raycaster = new THREE.Raycaster();

  private readonly pointer = new THREE.Vector2();

  private selectedObject: THREE.Object3D | null = null;

  private selectedElement: CadBimElement | null = null;

  private selectedMaterial = new THREE.MeshBasicMaterial({ color: 0xfacc15, depthTest: false });

  private lineHighlightMaterial = new THREE.LineBasicMaterial({ color: 0xfacc15, linewidth: 3, depthTest: false });

  private readonly clipSettings = new Map<ClipAxis, { enabled: boolean; offset: number; direction: ClipDirection }>([
    ["x", { enabled: false, offset: 0.5, direction: 1 }],
    ["y", { enabled: false, offset: 0.5, direction: 1 }],
    ["z", { enabled: false, offset: 0.5, direction: 1 }],
  ]);

  private readonly ifcEngine: IfcEngine;

  private renderMode: "json" | "ifc" = "json";

  private modelCounter = 0;

  private measureMode = false;

  private measurePoints: THREE.Vector3[] = [];

  onSelect: (element: CadBimElement | null) => void = () => {};

  onIfcSelect: (selection: IfcSelection | null) => void = () => {};

  onModelsChange: (models: ViewerModelRecord[]) => void = () => {};

  onMeasure: (message: string) => void = () => {};

  private constructor(container: HTMLElement, viewport: BUI.Viewport, components: OBC.Components, world: OBC.World) {
    this.container = container;
    this.viewport = viewport;
    this.components = components;
    this.world = world;
    this.root.name = "LES CAD/BIM JSON";
    this.ifcRoot.name = "LES IFC fragments";
    this.measurementRoot.name = "LES CAD/BIM measurements";
    this.world.scene.three.add(this.root);
    this.world.scene.three.add(this.ifcRoot);
    this.world.scene.three.add(this.measurementRoot);
    this.ifcEngine = new IfcEngine({
      components,
      world,
      root: this.ifcRoot,
      requestRender: () => this.requestRender(),
      onSelect: (selection) => this.onIfcSelect(selection),
    });
    this.container.addEventListener("pointerdown", this.onPointerDown);
    this.viewport.addEventListener("resize", this.resize);
    window.addEventListener("resize", this.resize);
  }

  static async create(container: HTMLElement): Promise<CadBimViewer> {
    BUI.Manager.init();

    const components = new OBC.Components();
    const worlds = components.get(OBC.Worlds);
    const world = worlds.create<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>();
    world.name = "LES CAD/BIM";
    world.scene = new OBC.SimpleScene(components);
    world.scene.setup();
    world.scene.three.background = new THREE.Color(0x07090c);
    world.scene.three.add(new THREE.AmbientLight(0xffffff, 0.62));
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
    keyLight.position.set(4, 7, 5);
    world.scene.three.add(keyLight);

    const viewport = BUI.Component.create<BUI.Viewport>(() => BUI.html`
      <bim-viewport style="width: 100%; height: 100%; display: block;"></bim-viewport>
    `);
    container.append(viewport);

    world.renderer = new OBC.SimpleRenderer(components, viewport);
    (world.renderer.three as THREE.WebGLRenderer).localClippingEnabled = true;
    world.camera = new OBC.OrthoPerspectiveCamera(components);
    world.camera.threePersp.near = 0.01;
    world.camera.threePersp.updateProjectionMatrix();
    world.camera.controls.restThreshold = 0.05;
    world.camera.controls.dollySpeed = 0.65;
    world.camera.controls.truckSpeed = 0.65;
    world.camera.controls.azimuthRotateSpeed = 0.35;
    world.camera.controls.polarRotateSpeed = 0.35;

    const grid = components.get(OBC.Grids).create(world);
    grid.material.uniforms.uColor.value = new THREE.Color(0x263748);
    grid.material.uniforms.uSize1.value = 0.1;
    grid.material.uniforms.uSize2.value = 1.0;

    components.init();
    world.scene.setup();
    if (new URLSearchParams(window.location.search).has("debug_scene")) {
      world.scene.three.add(
        new THREE.Mesh(
          new THREE.BoxGeometry(1, 1, 1),
          new THREE.MeshBasicMaterial({ color: 0xff0000 }),
        ),
      );
    }
    world.camera.controls.setLookAt(0.5, 0.7, 0.5, 0, 0, 0, false);

    const viewer = new CadBimViewer(container, viewport, components, world);
    viewer.resize();
    return viewer;
  }

  render(payload: CadBimGraph | CadBimElement[] | undefined, highlightIds: Set<string>, options: RenderOptions = {}): RenderResult {
    this.renderMode = "json";
    if (options.replace !== false) {
      this.clearIfcModels();
      this.clear();
    }
    return this.addJsonModel(payload, highlightIds, options);
  }

  addJsonModel(payload: CadBimGraph | CadBimElement[] | undefined, highlightIds: Set<string>, options: RenderOptions = {}): RenderResult {
    this.renderMode = "json";
    const graph = payload && !Array.isArray(payload) ? payload : undefined;
    const modelId = options.id || graph?.id || `json-${++this.modelCounter}`;
    if (this.jsonModels.has(modelId)) this.removeModel(modelId);

    const modelRoot = new THREE.Group();
    modelRoot.name = options.label || graph?.name || modelId;
    modelRoot.userData.modelId = modelId;
    this.root.add(modelRoot);

    const elements = graphElements(payload);
    const relations = graphRelations(payload);
    const drawables = createDrawables(elements, highlightIds);
    const localLayerGroups = new Map<string, THREE.Group>();

    for (const drawable of drawables) {
      const layer = drawable.layer;
      let group = localLayerGroups.get(layer);
      if (!group) {
        group = new THREE.Group();
        group.name = layer;
        group.userData.layer = layer;
        group.userData.modelId = modelId;
        localLayerGroups.set(layer, group);
        this.registerLayerGroup(layer, group);
        modelRoot.add(group);
      }
      drawable.object.userData.modelId = modelId;
      group.add(drawable.object);
    }

    if (drawables.length === 0) {
      this.renderRelationGraph(modelRoot, elements, relations, highlightIds, modelId);
    }

    const stats = buildStats(elements, drawables.length, relations);
    this.jsonModels.set(modelId, {
      id: modelId,
      label: modelRoot.name,
      source: options.source || graph?.source_path,
      root: modelRoot,
      elements,
      relations,
      stats,
      visible: true,
    });
    this.emitModelsChange();
    this.fit();
    this.requestRender();
    return { elements, selected: null, stats: this.aggregateStats(), modelId };
  }

  async renderIfcModels(models: IfcModelSource[], onProgress?: (message: string) => void): Promise<IfcRenderResult> {
    this.renderMode = "ifc";
    this.clear();
    this.ifcModels.clear();
    const result = await this.ifcEngine.loadModels(models, onProgress);
    for (const model of result.models) {
      this.ifcModels.set(model.id, {
        id: model.id,
        label: model.label,
        kind: "ifc",
        source: model.url,
        visible: true,
        elements: 0,
        drawable: 1,
        relations: 0,
      });
    }
    this.emitModelsChange();
    this.fit();
    this.requestRender();
    return result;
  }

  async addIfcModels(models: IfcModelSource[], onProgress?: (message: string) => void): Promise<IfcRenderResult> {
    this.renderMode = "ifc";
    const result = await this.ifcEngine.loadModels(models, onProgress, false);
    for (const model of result.models) {
      this.ifcModels.set(model.id, {
        id: model.id,
        label: model.label,
        kind: "ifc",
        source: model.url,
        visible: true,
        elements: 0,
        drawable: 1,
        relations: 0,
      });
    }
    this.emitModelsChange();
    this.fit();
    this.requestRender();
    return result;
  }

  async highlightIfcGlobalIds(globalIds: string[]): Promise<number> {
    return this.ifcEngine.highlightByGuids(globalIds);
  }

  setLayerVisible(layer: string, visible: boolean): void {
    const groups = this.layerGroups.get(layer);
    groups?.forEach((group) => {
      group.visible = visible;
    });
    this.requestRender();
  }

  sceneModels(): ViewerModelRecord[] {
    const jsonRecords: ViewerModelRecord[] = [...this.jsonModels.values()].map((model) => ({
        id: model.id,
        label: model.label,
        kind: "json",
        source: model.source,
        visible: model.visible,
        elements: model.stats.elements,
        drawable: model.stats.drawable,
        relations: model.stats.relations,
      }));
    return jsonRecords.concat([...this.ifcModels.values()]);
  }

  setModelVisible(modelId: string, visible: boolean): boolean {
    const json = this.jsonModels.get(modelId);
    if (json) {
      json.visible = visible;
      json.root.visible = visible;
      this.emitModelsChange();
      this.requestRender();
      return true;
    }
    const ifc = this.ifcModels.get(modelId);
    if (ifc) {
      ifc.visible = visible;
      this.ifcEngine.setModelVisible(modelId, visible);
      this.emitModelsChange();
      this.requestRender();
      return true;
    }
    return false;
  }

  isolateModel(modelId: string): boolean {
    if (!this.jsonModels.has(modelId) && !this.ifcModels.has(modelId)) return false;
    for (const model of this.sceneModels()) {
      this.setModelVisible(model.id, model.id === modelId);
    }
    return true;
  }

  removeModel(modelId: string): boolean {
    const json = this.jsonModels.get(modelId);
    if (json) {
      this.unregisterModelLayers(json.root);
      this.disposeObject(json.root);
      this.root.remove(json.root);
      this.jsonModels.delete(modelId);
      this.selectObject(null);
      this.emitModelsChange();
      this.requestRender();
      return true;
    }
    if (this.ifcModels.has(modelId)) {
      this.ifcEngine.removeModel(modelId);
      this.ifcModels.delete(modelId);
      this.emitModelsChange();
      this.requestRender();
      return true;
    }
    return false;
  }

  fitModel(modelId: string): boolean {
    const object = this.modelObject(modelId);
    if (!object) return false;
    this.fitObject(object);
    return true;
  }

  focusElement(id: string): void {
    const object = this.findObjectByElementId(id);
    if (!object) return;
    this.selectObject(object);
    this.fitObject(object);
  }

  focusSelected(): boolean {
    const target = this.selectedDrawableRoot();
    if (!target) return false;
    this.fitObject(target);
    return true;
  }

  hideSelected(): boolean {
    const target = this.selectedDrawableRoot();
    if (!target) return false;
    target.visible = false;
    this.selectObject(null);
    this.requestRender();
    return true;
  }

  isolateSelected(): boolean {
    const target = this.selectedDrawableRoot();
    if (!target) return false;
    for (const layerGroups of this.layerGroups.values()) {
      for (const layerGroup of layerGroups) {
        for (const child of layerGroup.children) {
          child.visible = child === target;
        }
        layerGroup.visible = true;
      }
    }
    target.visible = true;
    this.requestRender();
    return true;
  }

  showAll(): void {
    this.root.traverse((child) => {
      child.visible = true;
    });
    this.ifcRoot.traverse((child) => {
      child.visible = true;
    });
    for (const model of this.jsonModels.values()) model.visible = true;
    for (const model of this.ifcModels.values()) model.visible = true;
    this.emitModelsChange();
    this.requestRender();
  }

  setMeasureMode(enabled: boolean): void {
    this.measureMode = enabled;
    this.measurePoints = [];
    this.onMeasure(enabled ? "Укажи первую точку на геометрии" : "Замер выключен");
  }

  clearMeasurements(): void {
    this.measurePoints = [];
    for (const child of [...this.measurementRoot.children]) {
      this.disposeObject(child);
      this.measurementRoot.remove(child);
    }
    this.onMeasure(this.measureMode ? "Укажи первую точку на геометрии" : "Замеры очищены");
    this.requestRender();
  }

  setClipPlane(axis: ClipAxis, enabled: boolean, offset: number, direction: ClipDirection): void {
    this.clipSettings.set(axis, {
      enabled,
      offset: Math.max(0, Math.min(1, offset)),
      direction,
    });
    this.updateClippingPlanes();
    this.requestRender();
  }

  clearClipPlanes(): void {
    for (const [axis, setting] of this.clipSettings) {
      this.clipSettings.set(axis, { ...setting, enabled: false });
    }
    this.updateClippingPlanes();
    this.requestRender();
  }

  clipState(): Record<ClipAxis, { enabled: boolean; offset: number; direction: ClipDirection }> {
    return {
      x: { ...(this.clipSettings.get("x") || { enabled: false, offset: 0.5, direction: 1 as ClipDirection }) },
      y: { ...(this.clipSettings.get("y") || { enabled: false, offset: 0.5, direction: 1 as ClipDirection }) },
      z: { ...(this.clipSettings.get("z") || { enabled: false, offset: 0.5, direction: 1 as ClipDirection }) },
    };
  }

  fit(): void {
    const box = this.sceneBox();
    if (box.isEmpty()) {
      (this.world.camera as any)?.controls?.setLookAt(0.5, 0.7, 0.5, 0, 0, 0, false);
      return;
    }
    const sphere = new THREE.Sphere();
    box.getBoundingSphere(sphere);
    if (!Number.isFinite(sphere.radius) || sphere.radius <= 0) return;
    sphere.radius = Math.max(0.25, sphere.radius * 1.15);
    void (this.world.camera as any)?.controls?.fitToSphere?.(sphere, true);
    this.requestRender();
  }

  dispose(): void {
    this.clear();
    this.container.removeEventListener("pointerdown", this.onPointerDown);
    this.viewport.removeEventListener("resize", this.resize);
    window.removeEventListener("resize", this.resize);
    this.components.dispose();
  }

  debugState(): unknown {
    const target = this.ifcRoot.children.length ? this.ifcRoot : this.root;
    const box = new THREE.Box3().setFromObject(target);
    return {
      rootChildren: this.root.children.length,
      ifcChildren: this.ifcRoot.children.length,
      rootVisible: this.root.visible,
      layerGroups: [...this.layerGroups.keys()],
      models: this.sceneModels(),
      boxMin: box.min.toArray(),
      boxMax: box.max.toArray(),
      cameraPosition: this.world.camera?.three.position.toArray(),
      cameraQuaternion: this.world.camera?.three.quaternion.toArray(),
      sceneChildren: this.world.scene.three.children.map((child) => ({
        name: child.name,
        type: child.type,
        visible: child.visible,
        children: child.children.length,
      })),
    };
  }

  private clear(): void {
    this.selectedObject = null;
    this.selectedElement = null;
    this.clearMeasurements();
    for (const child of [...this.root.children]) {
      this.disposeObject(child);
      this.root.remove(child);
    }
    this.layerGroups.clear();
    this.jsonModels.clear();
    this.emitModelsChange();
  }

  private clearIfcModels(): void {
    this.ifcEngine.clear();
    this.ifcModels.clear();
    this.emitModelsChange();
  }

  private renderRelationGraph(
    parent: THREE.Group,
    elements: CadBimElement[],
    relations: ReturnType<typeof graphRelations>,
    highlightIds: Set<string>,
    modelId: string,
  ): void {
    const visible = elements.slice(0, 220);
    const ids = new Map<string, number>();
    visible.forEach((element, index) => ids.set(String(element.id || index), index));
    const radius = Math.max(160, visible.length * 4);
    const positions = visible.map((element, index) => {
      if (index === 0) return new THREE.Vector3(0, 0, 0);
      const angle = ((index - 1) / Math.max(1, visible.length - 1)) * Math.PI * 2;
      return new THREE.Vector3(Math.cos(angle) * radius, 0, Math.sin(angle) * radius);
    });

    const relationMaterial = new THREE.LineBasicMaterial({ color: 0x64748b, transparent: true, opacity: 0.36 });
    const relationPoints: THREE.Vector3[] = [];
    for (const relation of relations.slice(0, 600)) {
      const source = ids.get(relationEndpointId(relation, "source"));
      const target = ids.get(relationEndpointId(relation, "target"));
      if (source == null || target == null) continue;
      relationPoints.push(positions[source], positions[target]);
    }
    if (relationPoints.length) {
      parent.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(relationPoints), relationMaterial));
    }

    for (let index = 0; index < visible.length; index++) {
      const element = visible[index];
      const highlighted = highlightIds.has(String(element.id || ""));
      const color = highlighted ? 0xfacc15 : 0x38bdf8;
      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(index === 0 ? 8 : 5, 18, 12),
        new THREE.MeshBasicMaterial({ color, depthTest: false }),
      );
      mesh.position.copy(positions[index]);
      mesh.userData.element = element;
      mesh.userData.elementId = element.id || "";
      mesh.userData.layer = elementLayer(element);
      mesh.userData.modelId = modelId;
      parent.add(mesh);
    }
  }

  private onPointerDown = (event: PointerEvent): void => {
    const rect = this.container.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    this.raycaster.setFromCamera(this.pointer, this.world.camera.three);
    const hits = this.raycaster.intersectObjects(this.root.children, true);
    const hit = hits.find((item) => item.object.userData.element);
    if (this.measureMode) {
      if (hit) {
        this.addMeasurePoint(hit.point);
      } else {
        this.onMeasure("Кликни по видимой геометрии");
      }
      return;
    }
    if (!hit) {
      this.selectObject(null);
      return;
    }
    this.selectObject(hit.object);
  };

  private selectObject(object: THREE.Object3D | null): void {
    this.restoreSelection();
    this.selectedObject = object;
    const element = object?.userData.element || null;
    this.selectedElement = element;
    if (object) {
      object.traverse((child) => {
        const mesh = child as THREE.Mesh;
        const line = child as THREE.Line;
        if ("material" in child) {
          child.userData.originalMaterial = mesh.material;
          if (line.isLine || (child as THREE.LineSegments).isLineSegments) {
            line.material = this.lineHighlightMaterial;
          } else {
            mesh.material = this.selectedMaterial;
          }
        }
      });
    }
    this.onSelect(element);
  }

  private restoreSelection(): void {
    if (!this.selectedObject) return;
    this.selectedObject.traverse((child) => {
      if ("material" in child && child.userData.originalMaterial) {
        (child as THREE.Mesh).material = child.userData.originalMaterial;
        delete child.userData.originalMaterial;
      }
    });
  }

  private findObjectByElementId(id: string): THREE.Object3D | null {
    let found: THREE.Object3D | null = null;
    this.root.traverse((child) => {
      if (!found && String(child.userData.elementId || "") === id) {
        found = child;
      }
    });
    return found;
  }

  private selectedDrawableRoot(): THREE.Object3D | null {
    if (!this.selectedObject) return null;
    let node: THREE.Object3D | null = this.selectedObject;
    while (node.parent && node.parent !== this.root && !this.isLayerGroup(node.parent)) {
      node = node.parent;
    }
    return node;
  }

  private isLayerGroup(object: THREE.Object3D): boolean {
    return [...this.layerGroups.values()].some((groups) => groups.has(object as THREE.Group));
  }

  private registerLayerGroup(layer: string, group: THREE.Group): void {
    const groups = this.layerGroups.get(layer) || new Set<THREE.Group>();
    groups.add(group);
    this.layerGroups.set(layer, groups);
  }

  private unregisterModelLayers(root: THREE.Group): void {
    root.traverse((child) => {
      const layer = String(child.userData.layer || "");
      if (!layer) return;
      const groups = this.layerGroups.get(layer);
      groups?.delete(child as THREE.Group);
      if (groups && groups.size === 0) this.layerGroups.delete(layer);
    });
  }

  private modelObject(modelId: string): THREE.Object3D | null {
    return this.jsonModels.get(modelId)?.root || this.ifcEngine.modelObject(modelId);
  }

  private aggregateStats(): ViewerStats {
    const layers = new Map<string, number>();
    const types = new Map<string, number>();
    let elements = 0;
    let drawable = 0;
    let relations = 0;
    for (const model of this.jsonModels.values()) {
      elements += model.stats.elements;
      drawable += model.stats.drawable;
      relations += model.stats.relations;
      mergeCounts(layers, model.stats.layers);
      mergeCounts(types, model.stats.types);
    }
    return { elements, drawable, relations, layers, types };
  }

  private emitModelsChange(): void {
    this.onModelsChange(this.sceneModels());
  }

  private addMeasurePoint(point: THREE.Vector3): void {
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.035, 18, 12),
      new THREE.MeshBasicMaterial({ color: 0xfacc15, depthTest: false }),
    );
    marker.position.copy(point);
    this.measurementRoot.add(marker);
    this.measurePoints.push(point.clone());
    if (this.measurePoints.length === 1) {
      this.onMeasure("Укажи вторую точку");
      this.requestRender();
      return;
    }
    const [start, end] = this.measurePoints.slice(-2);
    const distance = start.distanceTo(end);
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([start, end]),
      new THREE.LineBasicMaterial({ color: 0xfacc15, depthTest: false }),
    );
    this.measurementRoot.add(line);
    this.measurementRoot.add(this.createMeasureLabel(`${distance.toFixed(2)} m`, start.clone().lerp(end, 0.5)));
    this.measurePoints = [end.clone()];
    this.onMeasure(`Расстояние ${distance.toFixed(2)} м`);
    this.requestRender();
  }

  private createMeasureLabel(text: string, position: THREE.Vector3): THREE.Sprite {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d")!;
    context.font = "34px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
    const width = Math.ceil(context.measureText(text).width + 34);
    canvas.width = Math.max(128, width);
    canvas.height = 58;
    context.font = "34px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
    context.fillStyle = "rgba(7, 10, 14, 0.86)";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "#facc15";
    context.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);
    context.fillStyle = "#facc15";
    context.fillText(text, 16, 40);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false }));
    sprite.position.copy(position);
    sprite.position.y += 0.12;
    sprite.scale.set(canvas.width * 0.002, canvas.height * 0.002, 1);
    return sprite;
  }

  private fitObject(object: THREE.Object3D): void {
    const sphere = new THREE.Sphere();
    new THREE.Box3().setFromObject(object).getBoundingSphere(sphere);
    if (Number.isFinite(sphere.radius) && sphere.radius > 0) {
      (this.world.camera as any)?.controls?.fitToSphere(sphere, true);
      this.requestRender();
    }
  }

  private updateClippingPlanes(): void {
    const box = this.sceneBox();
    if (box.isEmpty() || !this.world.renderer?.three) return;

    const axes: Record<ClipAxis, { normal: THREE.Vector3; min: number; max: number }> = {
      x: { normal: new THREE.Vector3(1, 0, 0), min: box.min.x, max: box.max.x },
      y: { normal: new THREE.Vector3(0, 1, 0), min: box.min.y, max: box.max.y },
      z: { normal: new THREE.Vector3(0, 0, 1), min: box.min.z, max: box.max.z },
    };
    const planes: THREE.Plane[] = [];
    for (const [axis, setting] of this.clipSettings) {
      if (!setting.enabled) continue;
      const range = axes[axis];
      const value = range.min + (range.max - range.min) * setting.offset;
      const normal = range.normal.clone().multiplyScalar(setting.direction);
      planes.push(new THREE.Plane(normal, -value * setting.direction));
    }
    this.world.renderer.three.clippingPlanes = planes;
    (this.world.renderer.three as THREE.WebGLRenderer).localClippingEnabled = true;
  }

  private resize = (): void => {
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.world.renderer?.resize(new THREE.Vector2(width, height));
    (this.world.camera as any)?.updateAspect?.();
    this.requestRender();
  };

  private requestRender(): void {
    if (!this.world.renderer) return;
    (this.world.renderer as any).needsUpdate = true;
    this.world.renderer.update();
  }

  private sceneBox(): THREE.Box3 {
    const box = new THREE.Box3();
    if (this.root.children.length) box.union(new THREE.Box3().setFromObject(this.root));
    if (this.ifcRoot.children.length) box.union(new THREE.Box3().setFromObject(this.ifcRoot));
    return box;
  }

  private disposeObject(object: THREE.Object3D): void {
    object.traverse((child) => {
      const maybeMesh = child as THREE.Mesh;
      maybeMesh.geometry?.dispose();
      const material = maybeMesh.material;
      if (Array.isArray(material)) {
        material.forEach((item) => item.dispose());
      } else {
        material?.dispose();
      }
    });
  }
}

function mergeCounts(target: Map<string, number>, source: Map<string, number>): void {
  for (const [key, value] of source) {
    target.set(key, (target.get(key) || 0) + value);
  }
}
