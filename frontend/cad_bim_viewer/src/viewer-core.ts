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
import type { CadBimElement, CadBimGraph, ViewerStats } from "./types";

export interface RenderResult {
  elements: CadBimElement[];
  selected: CadBimElement | null;
  stats: ViewerStats;
}

export class CadBimViewer {
  readonly components: OBC.Components;

  readonly world: OBC.World;

  private readonly container: HTMLElement;

  private readonly viewport: BUI.Viewport;

  private readonly root = new THREE.Group();

  private readonly layerGroups = new Map<string, THREE.Group>();

  private readonly raycaster = new THREE.Raycaster();

  private readonly pointer = new THREE.Vector2();

  private selectedObject: THREE.Object3D | null = null;

  private selectedMaterial = new THREE.MeshBasicMaterial({ color: 0xfacc15, depthTest: false });

  private lineHighlightMaterial = new THREE.LineBasicMaterial({ color: 0xfacc15, linewidth: 3, depthTest: false });

  onSelect: (element: CadBimElement | null) => void = () => {};

  private constructor(container: HTMLElement, viewport: BUI.Viewport, components: OBC.Components, world: OBC.World) {
    this.container = container;
    this.viewport = viewport;
    this.components = components;
    this.world = world;
    this.root.name = "LES CAD/BIM JSON";
    this.world.scene.three.add(this.root);
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

    const viewport = BUI.Component.create<BUI.Viewport>(() => BUI.html`
      <bim-viewport style="width: 100%; height: 100%; display: block;"></bim-viewport>
    `);
    container.append(viewport);

    world.renderer = new OBC.SimpleRenderer(components, viewport);
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

  render(payload: CadBimGraph | CadBimElement[] | undefined, highlightIds: Set<string>): RenderResult {
    this.clear();
    const elements = graphElements(payload);
    const relations = graphRelations(payload);
    const drawables = createDrawables(elements, highlightIds);

    for (const drawable of drawables) {
      const layer = drawable.layer;
      let group = this.layerGroups.get(layer);
      if (!group) {
        group = new THREE.Group();
        group.name = layer;
        this.layerGroups.set(layer, group);
        this.root.add(group);
      }
      group.add(drawable.object);
    }

    if (drawables.length === 0) {
      this.renderRelationGraph(elements, relations, highlightIds);
    }

    const stats = buildStats(elements, drawables.length, relations);
    this.fit();
    this.requestRender();
    return { elements, selected: null, stats };
  }

  setLayerVisible(layer: string, visible: boolean): void {
    const group = this.layerGroups.get(layer);
    if (group) group.visible = visible;
  }

  focusElement(id: string): void {
    const object = this.findObjectByElementId(id);
    if (!object) return;
    this.selectObject(object);
    const sphere = new THREE.Sphere();
    new THREE.Box3().setFromObject(object).getBoundingSphere(sphere);
    if (Number.isFinite(sphere.radius) && sphere.radius > 0) {
      (this.world.camera as any)?.controls?.fitToSphere(sphere, true);
    }
  }

  fit(): void {
    const box = new THREE.Box3().setFromObject(this.root);
    if (box.isEmpty()) {
      (this.world.camera as any)?.controls?.setLookAt(0.5, 0.7, 0.5, 0, 0, 0, false);
      return;
    }
    const sphere = new THREE.Sphere();
    box.getBoundingSphere(sphere);
    if (!Number.isFinite(sphere.radius) || sphere.radius <= 0) return;
    const radius = Math.max(0.4, sphere.radius * 1.7);
    const center = sphere.center;
    (this.world.camera as any)?.controls?.setLookAt(
      center.x + radius * 0.35,
      center.y + radius * 1.15,
      center.z + radius * 0.75,
      center.x,
      center.y,
      center.z,
      false,
    );
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
    const box = new THREE.Box3().setFromObject(this.root);
    return {
      rootChildren: this.root.children.length,
      rootVisible: this.root.visible,
      layerGroups: [...this.layerGroups.keys()],
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
    for (const child of [...this.root.children]) {
      this.disposeObject(child);
      this.root.remove(child);
    }
    this.layerGroups.clear();
  }

  private renderRelationGraph(elements: CadBimElement[], relations: ReturnType<typeof graphRelations>, highlightIds: Set<string>): void {
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
      this.root.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(relationPoints), relationMaterial));
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
      this.root.add(mesh);
    }
  }

  private onPointerDown = (event: PointerEvent): void => {
    const rect = this.container.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    this.raycaster.setFromCamera(this.pointer, this.world.camera.three);
    const hits = this.raycaster.intersectObjects(this.root.children, true);
    const hit = hits.find((item) => item.object.userData.element);
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
