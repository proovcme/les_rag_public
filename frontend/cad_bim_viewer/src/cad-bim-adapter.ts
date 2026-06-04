import * as THREE from "three";
import type { CadBimElement, CadBimGraph, CadBimRelation, Vec, ViewerStats } from "./types";

export interface DrawableElement {
  element: CadBimElement;
  object: THREE.Object3D;
  layer: string;
  type: string;
}

const PALETTE = [
  0x38bdf8,
  0x22c55e,
  0xf59e0b,
  0xef4444,
  0xa78bfa,
  0x14b8a6,
  0xf97316,
  0xe879f9,
  0xf8fafc,
  0x84cc16,
];

const UNIT_SCALE = 0.001;

export function graphElements(payload: CadBimGraph | CadBimElement[] | undefined): CadBimElement[] {
  if (Array.isArray(payload)) {
    return payload.filter(isObject);
  }
  if (!payload || typeof payload !== "object") {
    return [];
  }

  const root: CadBimElement[] = payload.id
    ? [
        {
          id: payload.id,
          type: payload.type || "Model",
          name: payload.name || payload.id,
          category: "Model",
          properties: payload.properties,
        },
      ]
    : [];
  return root.concat(Array.isArray(payload.elements) ? payload.elements.filter(isObject) : []);
}

export function graphRelations(payload: CadBimGraph | CadBimElement[] | undefined): CadBimRelation[] {
  return !Array.isArray(payload) && payload?.relations ? payload.relations.filter(isObject) : [];
}

export function buildStats(elements: CadBimElement[], drawableCount: number, relations: CadBimRelation[]): ViewerStats {
  const layers = new Map<string, number>();
  const types = new Map<string, number>();
  for (const element of elements) {
    if (isModelRoot(element)) continue;
    increment(layers, elementLayer(element));
    increment(types, elementType(element));
  }
  return {
    elements: elements.filter((element) => !isModelRoot(element)).length,
    drawable: drawableCount,
    relations: relations.length,
    layers,
    types,
  };
}

export function createDrawables(elements: CadBimElement[], highlightIds: Set<string>): DrawableElement[] {
  const drawables: DrawableElement[] = [];
  for (const element of elements) {
    if (isModelRoot(element)) continue;
    const object = createElementObject(element, highlightIds.has(String(element.id || "")));
    if (!object) continue;

    const layer = elementLayer(element);
    const type = elementType(element);
    object.userData.element = element;
    object.userData.elementId = element.id || "";
    object.traverse((child) => {
      child.userData.element = element;
      child.userData.elementId = element.id || "";
      child.userData.layer = layer;
      child.userData.type = type;
    });
    drawables.push({ element, object, layer, type });
  }
  return drawables;
}

export function elementLayer(element: CadBimElement): string {
  return String(element.layer || element.category || element.level || element.family || "default");
}

export function elementType(element: CadBimElement): string {
  return String(element.type || element.object_type || "element");
}

export function elementColor(layer: string, highlighted = false): THREE.Color {
  if (highlighted) return new THREE.Color(0xfacc15);
  let hash = 0;
  for (let index = 0; index < layer.length; index++) {
    hash = ((hash << 5) - hash + layer.charCodeAt(index)) | 0;
  }
  return new THREE.Color(PALETTE[Math.abs(hash) % PALETTE.length]);
}

export function relationEndpointId(relation: CadBimRelation, side: "source" | "target"): string {
  if (side === "source") {
    return String(relation.source_id || relation.sourceId || relation.from || "");
  }
  return String(relation.target_id || relation.targetId || relation.to || "");
}

export function isModelRoot(element: CadBimElement): boolean {
  const type = elementType(element).toLowerCase();
  return type.endsWith("model") || type === "model" || element.category === "Model";
}

function createElementObject(element: CadBimElement, highlighted: boolean): THREE.Object3D | null {
  const props = element.properties || {};
  const layer = elementLayer(element);
  const type = elementType(element).toUpperCase();
  const color = elementColor(layer, highlighted);
  const group = new THREE.Group();

  if (point3(props.start) && point3(props.end)) {
    group.add(createLine(point3(props.start)!, point3(props.end)!, color, highlighted));
  } else if (Array.isArray(props.points_preview) && props.points_preview.length > 1) {
    const points = props.points_preview.map(point3).filter((point): point is Vec => Boolean(point));
    if (points.length > 1) group.add(createPolyline(points, color, highlighted, Boolean(props.closed)));
  } else if (point3(props.center) && Number(props.radius) > 0) {
    const center = point3(props.center)!;
    const radius = Number(props.radius);
    const startAngle = numberOrNull(props.start_angle);
    const endAngle = numberOrNull(props.end_angle);
    group.add(createArcOrCircle(center, radius, color, highlighted, startAngle, endAngle, type === "CIRCLE"));
  } else if (point3(props.bbox_min) && point3(props.bbox_max)) {
    group.add(createBbox(point3(props.bbox_min)!, point3(props.bbox_max)!, color, highlighted));
  } else if (point3(props.insert)) {
    const point = point3(props.insert)!;
    group.add(createPoint(point, color, highlighted));
    group.add(createTextSprite(String(props.text || element.name || element.id || ""), point, color, highlighted));
  } else {
    return null;
  }

  if (type !== "TEXT" && typeof props.text === "string" && point3(props.insert)) {
    group.add(createTextSprite(props.text, point3(props.insert)!, color, highlighted));
  }

  return group.children.length ? group : null;
}

function createLine(start: Vec, end: Vec, color: THREE.Color, highlighted: boolean): THREE.Mesh {
  return createTube([toWorld(start), toWorld(end)], color, highlighted);
}

function createPolyline(points: Vec[], color: THREE.Color, highlighted: boolean, closed: boolean): THREE.Object3D {
  const worldPoints = points.map(toWorld);
  if (closed && worldPoints.length > 2) {
    worldPoints.push(worldPoints[0].clone());
  }
  return createTube(worldPoints, color, highlighted);
}

function createArcOrCircle(
  center: Vec,
  radius: number,
  color: THREE.Color,
  highlighted: boolean,
  startAngle: number | null,
  endAngle: number | null,
  forceCircle: boolean,
): THREE.Mesh {
  const start = forceCircle || startAngle === null ? 0 : degreesToRadians(startAngle);
  const end = forceCircle || endAngle === null ? Math.PI * 2 : degreesToRadians(endAngle);
  const steps = Math.max(24, Math.min(160, Math.ceil(Math.abs(end - start) / (Math.PI / 36))));
  const points: THREE.Vector3[] = [];
  for (let index = 0; index <= steps; index++) {
    const t = start + ((end - start) * index) / steps;
    points.push(toWorld([center[0] + Math.cos(t) * radius, center[1] + Math.sin(t) * radius, center[2]]));
  }
  return createTube(points, color, highlighted);
}

function createBbox(min: Vec, max: Vec, color: THREE.Color, highlighted: boolean): THREE.LineSegments {
  const minWorld = toWorld(min);
  const maxWorld = toWorld(max);
  const size = new THREE.Vector3(
    Math.max(0.01, Math.abs(maxWorld.x - minWorld.x)),
    Math.max(0.01, Math.abs(maxWorld.y - minWorld.y)),
    Math.max(0.01, Math.abs(maxWorld.z - minWorld.z)),
  );
  const center = new THREE.Vector3().addVectors(minWorld, maxWorld).multiplyScalar(0.5);
  const geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x, size.y, size.z));
  const box = new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({ color, linewidth: highlighted ? 3 : 1, depthTest: false }),
  );
  box.position.copy(center);
  return box;
}

function createPoint(point: Vec, color: THREE.Color, highlighted: boolean): THREE.Mesh {
  const geometry = new THREE.SphereGeometry(highlighted ? 0.035 : 0.02, 16, 12);
  const material = new THREE.MeshBasicMaterial({ color, depthTest: false });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.copy(toWorld(point));
  return mesh;
}

function createTube(points: THREE.Vector3[], color: THREE.Color, highlighted: boolean): THREE.Mesh {
  const clean = points.filter((point, index) => index === 0 || point.distanceTo(points[index - 1]) > 1e-7);
  const material = new THREE.MeshBasicMaterial({ color, depthTest: true });
  if (clean.length < 2) {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(highlighted ? 0.05 : 0.025, 12, 8), material);
    mesh.position.copy(clean[0] || new THREE.Vector3());
    return mesh;
  }
  const curve = new THREE.CatmullRomCurve3(clean, false, "centripetal");
  const geometry = new THREE.TubeGeometry(curve, Math.max(1, clean.length - 1) * 8, highlighted ? 0.05 : 0.025, 8, false);
  return new THREE.Mesh(geometry, material);
}

function createTextSprite(text: string, point: Vec, color: THREE.Color, highlighted: boolean): THREE.Sprite {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d")!;
  const fontSize = highlighted ? 46 : 38;
  context.font = `${fontSize}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
  const metrics = context.measureText(text || " ");
  canvas.width = Math.max(128, Math.ceil(metrics.width + 32));
  canvas.height = 72;
  context.font = `${fontSize}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
  context.fillStyle = highlighted ? "rgba(250, 204, 21, 0.18)" : "rgba(2, 6, 23, 0.72)";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = highlighted ? "#facc15" : "#334155";
  context.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);
  context.fillStyle = `#${color.getHexString()}`;
  context.fillText(text.slice(0, 64), 16, 48);

  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({ map: texture, depthTest: false, transparent: true });
  const sprite = new THREE.Sprite(material);
  sprite.position.copy(toWorld(point));
  sprite.position.y += 0.03;
  sprite.scale.set(canvas.width * 0.0008, canvas.height * 0.0008, 1);
  return sprite;
}

function toWorld(point: Vec): THREE.Vector3 {
  return new THREE.Vector3(point[0] * UNIT_SCALE, (point[2] || 0) * UNIT_SCALE, -point[1] * UNIT_SCALE);
}

function point3(value: unknown): Vec | null {
  if (!Array.isArray(value) || value.length < 2) return null;
  const x = Number(value[0]);
  const y = Number(value[1]);
  const z = Number(value[2] || 0);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
  return [x, y, z];
}

function numberOrNull(value: unknown): number | null {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function degreesToRadians(value: number): number {
  return (value * Math.PI) / 180;
}

function increment(map: Map<string, number>, key: string): void {
  map.set(key, (map.get(key) || 0) + 1);
}

function isObject<T extends object>(item: unknown): item is T {
  return Boolean(item && typeof item === "object");
}
