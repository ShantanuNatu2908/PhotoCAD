export type AxisView = 'front' | 'back' | 'left' | 'right' | 'top' | 'bottom';

export interface CalibrationSpec {
  mode: 'aruco_token' | 'id1_card' | 'known_dimension';
  reference_side: AxisView;
  known_length_mm: number;
  point_a_px?: [number, number];
  point_b_px?: [number, number];
  mm_per_unit?: number;
}

export interface KeyframeCapture {
  side: AxisView;
  blob: Blob;
  dataUrl: string;
  blurScore: number;
  width: number;
  height: number;
  timestamp: string;
}

export interface DetectedPlane {
  plane_id: string;
  normal: [number, number, number];
  centroid_mm: [number, number, number];
  area_mm2: number;
  inlier_ratio: number;
}

export interface DetectedCylinder {
  cylinder_id: string;
  kind: 'boss' | 'through_hole' | 'blind_hole';
  axis_origin_mm: [number, number, number];
  axis_direction: [number, number, number];
  radius_mm: number;
  depth_mm: number;
  confidence: number;
}

export interface Open3DGeometryReport {
  scan_id: string;
  units: 'mm';
  point_count: number;
  icp_fitness_score: number;
  icp_inlier_rmse_mm: number;
  bounding_box_mm: [number, number, number];
  principal_axes: Array<[number, number, number]>;
  symmetry_planes: Array<'XY' | 'YZ' | 'XZ'>;
  planes: DetectedPlane[];
  cylinders: DetectedCylinder[];
  ply_object_key: string;
}

export interface ScanFusionResponse {
  scan_id: string;
  status: 'fused' | 'failed';
  execution_mode: string;
  ply_url: string;
  masked_urls: Partial<Record<AxisView, string>>;
  geometry_report: Open3DGeometryReport;
  telemetry: Record<string, unknown>;
}

export interface ScanWsEvent {
  event: string;
  scan_id: string;
  timestamp: string;
  progress_pct: number;
  payload: Record<string, unknown>;
}

export interface ViewDetail {
  view: AxisView;
  image_url: string;
  edge_url?: string;
  masked_url?: string;
  blur_score?: number;
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
  status?: string;
  has_scale_reference: number;
  scale_px_to_mm: number;
  calibration_json?: CalibrationSpec;
  geometry_report_json?: Open3DGeometryReport;
  ply_file?: string;
  views_data: Record<AxisView, ViewDetail>;
  created_at: string;
}

export interface ValidationMetrics {
  is_watertight: boolean;
  volume_mm3: number;
  surface_area_mm2: number;
  chamfer_mean_mm: number;
  chamfer_p95_mm: number;
  bbox_delta_mm: [number, number, number];
  passed_tolerance: boolean;
  discrepancy_notes: string[];
}

export interface AgentLog {
  id: string;
  agent_name: string;
  log_type: 'info' | 'thought' | 'code' | 'diff' | 'error' | 'success';
  message: string;
  created_at: string;
}

export interface CadGeneration {
  id: string;
  scan_session_id: string;
  version: number;
  status: 'pending' | 'generating' | 'compiling' | 'completed' | 'completed_with_warning' | 'failed';
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
