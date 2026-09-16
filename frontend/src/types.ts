export type ProjectStatus =
  | 'draft'
  | 'analyzing'
  | 'graph_ready'
  | 'entities_confirming'
  | 'images_generating'
  | 'frames_ready'
  | 'export_ready'
  | 'failed';

export interface Project {
  id: string;
  title: string;
  script: string;
  content_type?: string;
  status: ProjectStatus;
  progress: number;
  entity_count: number;
  completed_entity_image_count: number;
  frame_count: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
  graph?: KnowledgeGraph;
  entities?: Entity[];
  frames?: VideoFrame[];
  exports?: ExportRecord[];
}

export interface KnowledgeGraphNode {
  id: string;
  type: string;
  name: string;
  description: string;
  source_text?: string;
  entity_id?: string;
  x: number;
  y: number;
}

export interface KnowledgeGraphEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relation: string;
  description?: string;
}

export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
}

export interface EntityImage {
  id: string;
  entity_id: string;
  project_id: string;
  image_url: string;
  prompt: string;
  is_main: number;
  created_at: string;
}

export interface Entity {
  id: string;
  project_id: string;
  name: string;
  type: string;
  description: string;
  visual_description?: string;
  prompt?: string;
  status: string;
  main_image_id?: string;
  occurrence_count: number;
  images: EntityImage[];
}

export interface VideoFrame {
  id: string;
  project_id: string;
  frame_index: number;
  source_text: string;
  description: string;
  camera?: string;
  mood?: string;
  entity_ids: string[];
  reference_image_ids: string[];
  prompt: string;
  entities: Entity[];
}

export interface ExportRecord {
  id: string;
  project_id?: string;
  file_url: string;
  created_at: string;
}
