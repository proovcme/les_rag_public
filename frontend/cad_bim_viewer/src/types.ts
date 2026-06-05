export type Vec = [number, number, number];

export interface CadBimRelation {
  source_id?: string;
  sourceId?: string;
  from?: string;
  target_id?: string;
  targetId?: string;
  to?: string;
  relation_type?: string;
  relationType?: string;
}

export interface CadBimElement {
  id?: string;
  type?: string;
  object_type?: string;
  name?: string;
  category?: string;
  family?: string;
  level?: string;
  layer?: string;
  material?: string;
  properties?: Record<string, unknown>;
  geometry?: CadBimGeometry;
}

export interface CadBimGeometry {
  type?: string;
  units?: string;
  vertices?: number[];
  faces?: number[];
  material?: {
    color?: string;
    opacity?: number;
    name?: string;
  };
  stats?: Record<string, unknown>;
  truncated?: boolean;
}

export interface CadBimGraph {
  id?: string;
  type?: string;
  name?: string;
  source_format?: string;
  source_path?: string;
  extracted_at?: string;
  properties?: Record<string, unknown>;
  elements?: CadBimElement[];
  relations?: CadBimRelation[];
}

export interface CadBimSourceResponse {
  source?: string;
  payload?: CadBimGraph | CadBimElement[];
  element_count?: number;
  truncated?: boolean;
}

export interface CadBimElementContext {
  found: boolean;
  source_id: string;
  element: {
    id: string;
    import_id: string;
    source_id: string;
    speckle_type?: string;
    object_type?: string;
    name?: string;
    layer?: string;
    category?: string;
    family?: string;
    level?: string;
    material?: string;
    source?: string;
    source_kind?: string;
    profile?: string;
    projection_path?: string;
    attributes?: Record<string, unknown>;
  };
  properties: {
    name: string;
    value: string;
    value_type?: string;
    unit?: string;
    property_set?: string;
  }[];
  relations: {
    source_id: string;
    target_id: string;
    relation_type: string;
  }[];
  rag_prompt: string;
  summary: {
    title: string;
    import_id: string;
    profile: string;
    source: string;
    projection_path: string;
    properties: number;
    relations: number;
  };
}

export interface ViewerStats {
  elements: number;
  drawable: number;
  relations: number;
  layers: Map<string, number>;
  types: Map<string, number>;
}

export type ViewerModelKind = "json" | "ifc";

export interface ViewerModelRecord {
  id: string;
  label: string;
  kind: ViewerModelKind;
  source?: string;
  visible: boolean;
  elements: number;
  drawable: number;
  relations: number;
}

export interface IfcModelSource {
  id: string;
  label: string;
  url: string;
  jsonSourcePath?: string;
}

export interface IfcSelection {
  modelId: string;
  localId: number;
  globalId: string;
  rows: [string, unknown][];
}

export interface IfcRenderResult {
  models: IfcModelSource[];
  loaded: number;
}
