import type {
  ActivePipelineEngines,
  AgentLog,
  AxisView,
  CalibrationSpec,
  KeyframeCapture,
  SavedScanItem,
  ScanFusionResponse,
  ScanWsEvent,
  ValidationMetrics,
} from '../types/cad';

export const BACKEND_ORIGIN = 'http://localhost:8000';
export const API_BASE = `${BACKEND_ORIGIN}/api`;

interface CreateScanResponse {
  scan_id: string;
  status: string;
  upload_urls: Record<AxisView, string>;
  expires_in_seconds: number;
}

interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
  detail?: string;
}

async function parseErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const data: ApiErrorBody = await res.json();
    if (data.error?.message) {
      return `${data.error.code || 'ERROR'}: ${data.error.message}`;
    }
    if (data.detail) {
      return data.detail;
    }
  } catch {
    // Fallback to HTTP status text
  }
  return `${fallback} (HTTP ${res.status})`;
}

export async function createScanSession(
  projectId: string,
  title = '6-Axis Handheld Scan'
): Promise<CreateScanResponse> {
  const res = await fetch(`${API_BASE}/scans`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, title }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, 'Failed to create scan session'));
  }
  return res.json();
}

export async function uploadKeyframeBinary(uploadUrl: string, blob: Blob): Promise<void> {
  const res = await fetch(uploadUrl, {
    method: 'PUT',
    headers: { 'Content-Type': 'image/png' },
    body: blob,
  });
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, 'Failed to upload keyframe PNG'));
  }
}

export async function confirmKeyframeView(
  scanId: string,
  side: AxisView,
  capture: KeyframeCapture
): Promise<void> {
  const res = await fetch(`${API_BASE}/scans/${scanId}/views/${side}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      blur_score: capture.blurScore,
      width_px: capture.width,
      height_px: capture.height,
      manual_override: true,
    }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, `Failed to confirm ${side} view`));
  }
}

export async function fetchSavedScans(): Promise<SavedScanItem[]> {
  const res = await fetch(`${API_BASE}/scans`);
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, 'Failed to load saved scans'));
  }
  return res.json();
}

export async function submitCalibration(
  scanId: string,
  spec: CalibrationSpec
): Promise<void> {
  const res = await fetch(`${API_BASE}/scans/${scanId}/calibrate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(spec),
  });
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, 'Calibration failed'));
  }
}

export async function triggerCvFusion(scanId: string, strictCloud = false): Promise<ScanFusionResponse> {
  const res = await fetch(`${API_BASE}/scans/${scanId}/fuse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ strict_cloud: strictCloud }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, 'CV 3D Fusion failed'));
  }
  return res.json();
}

export async function fetchActiveEngines(): Promise<ActivePipelineEngines | null> {
  try {
    const res = await fetch(`${API_BASE}/health/cloud`);
    if (!res.ok) return null;
    const data = (await res.json()) as { active_engines?: ActivePipelineEngines };
    return data.active_engines || null;
  } catch {
    return null;
  }
}

export function subscribeScanEvents(
  scanId: string,
  onEvent: (ev: ScanWsEvent) => void
): () => void {
  const wsUrl = BACKEND_ORIGIN.replace(/^http/, 'ws') + `/ws/v1/scans/${scanId}`;
  let socket: WebSocket | null = null;
  try {
    socket = new WebSocket(wsUrl);
    socket.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data) as ScanWsEvent;
        onEvent(parsed);
      } catch {
        // Ignore malformed event
      }
    };
  } catch {
    // Graceful no-op if WebSocket unavailable
  }

  return () => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.close();
    }
  };
}

/**
 * Full Phase 3 client pipeline:
 * 1. Create scan session + obtain 6 pre-signed PUT URLs
 * 2. Upload all 6 uncompressed PNG keyframes & confirm Laplacian sharpness scores
 * 3. Submit 1:1 mm calibration specification
 * 4. Stream WebSocket progress & run Cloud GPU CV fusion (SAM 2.1 + Depth Anything + Open3D)
 */
export async function uploadAndRunCvFusion(
  projectId: string,
  captures: Partial<Record<AxisView, KeyframeCapture>>,
  calibration: CalibrationSpec,
  onWsEvent?: (ev: ScanWsEvent) => void,
  existingScanId?: string | null,
  strictCloud = false
): Promise<ScanFusionResponse> {
  let scanId = existingScanId && !existingScanId.startsWith('demo-') ? existingScanId : null;
  if (!scanId) {
    const session = await createScanSession(projectId);
    scanId = session.scan_id;
  }

  const unsubscribe = onWsEvent ? subscribeScanEvents(scanId, onWsEvent) : () => {};

  try {
    const sides = (Object.keys(captures) as AxisView[]).filter((s) => Boolean(captures[s]));
    await Promise.all(
      sides.map(async (side) => {
        const cap = captures[side]!;
        const uploadUrl = `${API_BASE}/scans/${scanId}/views/${side}/upload`;
        await uploadKeyframeBinary(uploadUrl, cap.blob);
        await confirmKeyframeView(scanId!, side, cap);
      })
    );

    await submitCalibration(scanId, calibration);
    return await triggerCvFusion(scanId, strictCloud);
  } finally {
    // Allow final WS event flush before teardown
    setTimeout(unsubscribe, 400);
  }
}

export function resolveBackendAssetUrl(pathOrUrl?: string): string | undefined {
  if (!pathOrUrl) return undefined;
  if (pathOrUrl.startsWith('http://') || pathOrUrl.startsWith('https://') || pathOrUrl.startsWith('blob:') || pathOrUrl.startsWith('data:')) {
    return pathOrUrl;
  }
  return `${BACKEND_ORIGIN}${pathOrUrl.startsWith('/') ? '' : '/'}${pathOrUrl}`;
}

export interface ScanGenerateApiResponse {
  scan_id: string;
  generation_id: string;
  revision: number;
  status: string;
  dimensions_mm?: { x: number; y: number; z: number };
  code: string;
  artifacts: {
    step_url?: string;
    stl_url?: string;
    dxf_url?: string;
    py_url?: string;
  };
  validation_metrics?: ValidationMetrics | null;
  agent_logs?: AgentLog[];
  active_models?: ActivePipelineEngines;
}

export async function uploadSingleViewKeyframe(
  projectId: string,
  existingScanId: string | null,
  side: AxisView,
  capture: KeyframeCapture
): Promise<string> {
  let scanId = existingScanId;
  if (!scanId || scanId.startsWith('demo-')) {
    const session = await createScanSession(projectId);
    scanId = session.scan_id;
  }
  await uploadKeyframeBinary(`${API_BASE}/scans/${scanId}/views/${side}/upload`, capture.blob);
  await confirmKeyframeView(scanId, side, capture);
  return scanId;
}

export async function generateCadForScan(scanId: string, strictCloud = false): Promise<ScanGenerateApiResponse> {
  const res = await fetch(`${API_BASE}/scans/${scanId}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ strict_cloud: strictCloud }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, 'LangGraph CAD generation failed'));
  }
  return res.json();
}

export async function refineCadRevision(
  scanId: string,
  instruction: string,
  baseRevision = 1
): Promise<ScanGenerateApiResponse> {
  const res = await fetch(`${API_BASE}/scans/${scanId}/refine`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ base_revision: baseRevision, instruction }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, 'Parametric refinement failed'));
  }
  return res.json();
}
