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

export interface ViewerStats {
  elements: number;
  drawable: number;
  relations: number;
  layers: Map<string, number>;
  types: Map<string, number>;
}
