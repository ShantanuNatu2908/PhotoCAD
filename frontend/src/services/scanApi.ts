import type {
  AgentLog,
  AxisView,
  CalibrationSpec,
  KeyframeCapture,
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
    }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, `Failed to confirm ${side} view`));
  }
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

export async function triggerCvFusion(scanId: string): Promise<ScanFusionResponse> {
  const res = await fetch(`${API_BASE}/scans/${scanId}/fuse`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res, 'CV 3D Fusion failed'));
  }
  return res.json();
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
  captures: Record<AxisView, KeyframeCapture>,
  calibration: CalibrationSpec,
  onWsEvent?: (ev: ScanWsEvent) => void
): Promise<ScanFusionResponse> {
  const session = await createScanSession(projectId);
  const scanId = session.scan_id;

  const unsubscribe = onWsEvent ? subscribeScanEvents(scanId, onWsEvent) : () => {};

  try {
    const sides = Object.keys(captures) as AxisView[];
    await Promise.all(
      sides.map(async (side) => {
        const cap = captures[side];
        const uploadUrl = session.upload_urls[side];
        await uploadKeyframeBinary(uploadUrl, cap.blob);
        await confirmKeyframeView(scanId, side, cap);
      })
    );

    await submitCalibration(scanId, calibration);
    return await triggerCvFusion(scanId);
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

export async function generateCadForScan(scanId: string): Promise<ScanGenerateApiResponse> {
  const res = await fetch(`${API_BASE}/scans/${scanId}/generate`, {
    method: 'POST',
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
