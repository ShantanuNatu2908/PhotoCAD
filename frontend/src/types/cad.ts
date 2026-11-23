export type AxisView = 'front' | 'back' | 'left' | 'right' | 'top' | 'bottom';

export interface ViewDetail {
  view: AxisView;
  image_url: string;
  edge_url?: string;
  original_resolution: [number, number];
  features_detected: number;
  primary_dimensions_mm: [number, number];
  features: Array<{
    type: string;
    area_px: number;
    bbox_mm: [number, number];
    geometric_primitive?: string;
    radius_mm?: number;
    center_mm?: [number, number];
  }>;
}

export interface ScanSession {
  id: string;
  project_id: string;
  has_scale_reference: number;
  scale_px_to_mm: number;
  views_data: Record<AxisView, ViewDetail>;
  created_at: string;
}

export interface AgentLog {
  id: string;
  agent_name: string;
  log_type: 'info' | 'thought' | 'code' | 'error' | 'success';
  message: string;
  created_at: string;
}

export interface CadGeneration {
  id: string;
  scan_session_id: string;
  version: number;
  status: 'pending' | 'generating' | 'compiling' | 'completed' | 'failed';
  code?: string;
  step_file?: string;
  dxf_file?: string;
  stl_file?: string;
  dimensions_mm?: {
    x: number;
    y: number;
    z: number;
  };
  error_log?: string;
  created_at: string;
  agent_logs?: AgentLog[];
}
