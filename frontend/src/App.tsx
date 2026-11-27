import React, { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { SixAxisCapture } from './components/SixAxisCapture';
import { ScannerChamber } from './components/scanner/ScannerChamber';
import { CadViewport3D } from './components/CadViewport3D';
import { AgentTerminal } from './components/AgentTerminal';
import { ExportModal } from './components/ExportModal';
import type {
  AxisView,
  ViewDetail,
  CadGeneration,
  AgentLog,
  KeyframeCapture,
  CalibrationSpec,
  Open3DGeometryReport,
  ScanWsEvent,
} from './types/cad';
import {
  API_BASE,
  uploadAndRunCvFusion,
  resolveBackendAssetUrl,
} from './services/scanApi';
import { Play, Download, Sparkles, RefreshCw, Camera, Grid, Layers, CheckCircle2 } from 'lucide-react';

async function generateDemoPngBatch(): Promise<Record<AxisView, KeyframeCapture>> {
  const specs: Record<AxisView, [number, number]> = {
    front: [320, 200],
    back: [320, 200],
    left: [240, 200],
    right: [240, 200],
    top: [320, 240],
    bottom: [320, 240],
  };

  const out = {} as Record<AxisView, KeyframeCapture>;
  for (const side of Object.keys(specs) as AxisView[]) {
    const [w, h] = specs[side];
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d')!;

    // Dark studio surface background
    ctx.fillStyle = '#141923';
    ctx.fillRect(0, 0, w, h);

    // Metallic bracket silhouette
    ctx.fillStyle = '#9db4c8';
    ctx.fillRect(w * 0.18, h * 0.2, w * 0.64, h * 0.6);

    // Center through-hole
    if (side === 'top' || side === 'bottom' || side === 'front') {
      ctx.fillStyle = '#141923';
      ctx.beginPath();
      ctx.arc(w / 2, h / 2, Math.min(w, h) * 0.14, 0, Math.PI * 2);
      ctx.fill();
    }

    const blob = await new Promise<Blob>((resolve) =>
      canvas.toBlob((b) => resolve(b || new Blob()), 'image/png')
    );
    out[side] = {
      side,
      blob,
      dataUrl: URL.createObjectURL(blob),
      blurScore: 192.4,
      width: w,
      height: h,
      timestamp: new Date().toISOString(),
    };
  }
  return out;
}

export const App: React.FC = () => {
  const [unit, setUnit] = useState('mm');
  const [systemStatus, setSystemStatus] = useState('Ready (SAM2 + Open3D)');
  const [projectId, setProjectId] = useState<string>('demo-proj-001');
  const [scanSessionId, setScanSessionId] = useState<string | null>(null);
  const [hasScaleRef, setHasScaleRef] = useState(true);
  const [scalePxToMm, setScalePxToMm] = useState(1.0);
  const [viewsData, setViewsData] = useState<Partial<Record<AxisView, ViewDetail>>>({});
  const [capturedKeyframes, setCapturedKeyframes] = useState<Record<AxisView, KeyframeCapture> | null>(null);
  const [calibrationSpec, setCalibrationSpec] = useState<CalibrationSpec | null>(null);
  const [geometryReport, setGeometryReport] = useState<Open3DGeometryReport | null>(null);
  const [plyUrl, setPlyUrl] = useState<string | undefined>(undefined);
  const [isFusing, setIsFusing] = useState(false);

  const [activeTab, setActiveTab] = useState<'camera' | 'grid'>('camera');
  const [generation, setGeneration] = useState<CadGeneration | null>(null);
  const [agentLogs, setAgentLogs] = useState<AgentLog[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);

  // Initialize or fetch default project
  useEffect(() => {
    fetch(`${API_BASE}/projects`)
      .then((res) => res.json())
      .then((projects) => {
        if (projects.length > 0) {
          setProjectId(projects[0].id);
        } else {
          fetch(`${API_BASE}/projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: 'Precision Aluminum Mounting Bracket',
              description: '6-Axis Orthographic Photogrammetry to B-Rep CAD',
              unit: 'mm',
            }),
          })
            .then((res) => res.json())
            .then((p) => setProjectId(p.id))
            .catch(() => {});
        }
      })
      .catch((err) => {
        console.warn('Backend server not connected yet, operating in demo mode.', err);
      });
  }, []);

  // Poll generation status and agent logs if generation is active
  useEffect(() => {
    if (!generation || (generation.status !== 'generating' && generation.status !== 'compiling' && generation.status !== 'pending')) {
      return;
    }

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/generate/${generation.id}`);
        if (res.ok) {
          const updated: CadGeneration = await res.json();
          setGeneration(updated);
          if (updated.agent_logs) {
            setAgentLogs(updated.agent_logs);
          }
          if (updated.status === 'completed' || updated.status === 'failed') {
            setIsGenerating(false);
          }
        }
      } catch (e) {
        console.warn('Polling error', e);
      }
    }, 1200);

    return () => clearInterval(interval);
  }, [generation?.id, generation?.status]);

  const appendLog = (agentName: string, logType: AgentLog['log_type'], message: string) => {
    setAgentLogs((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random().toString(16).slice(2, 6)}`,
        agent_name: agentName,
        log_type: logType,
        message,
        created_at: new Date().toISOString(),
      },
    ]);
  };

  // Load High-Fidelity Demo Bracket 6-Axis Scan
  const handleLoadDemo = () => {
    const demoSvgBox = (label: string, w: number, h: number, holes = true) => {
      return `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
        <rect width="100%" height="100%" fill="%231a2333"/>
        <rect x="20" y="20" width="${w - 40}" height="${h - 40}" rx="15" fill="%232c3e50" stroke="%2300f0ff" stroke-width="3"/>
        ${holes ? `<circle cx="${w/2}" cy="${h/2}" r="18" fill="%230b0f17" stroke="%23ffb703" stroke-width="2"/>` : ''}
        <text x="50%" y="35%" dominant-baseline="middle" text-anchor="middle" fill="%23ffffff" font-family="monospace" font-size="14">${label}</text>
        <text x="50%" y="85%" dominant-baseline="middle" text-anchor="middle" fill="%2300f0ff" font-family="monospace" font-size="11">${w}x${h}mm</text>
      </svg>`;
    };

    const demoViews: Record<AxisView, ViewDetail> = {
      front: { view: 'front', image_url: demoSvgBox('FRONT ELEVATION', 300, 180, true), original_resolution: [300, 180], features_detected: 4, primary_dimensions_mm: [80.0, 30.0], features: [] },
      back: { view: 'back', image_url: demoSvgBox('REAR ELEVATION', 300, 180, false), original_resolution: [300, 180], features_detected: 2, primary_dimensions_mm: [80.0, 30.0], features: [] },
      top: { view: 'top', image_url: demoSvgBox('TOP PLAN VIEW', 300, 240, true), original_resolution: [300, 240], features_detected: 6, primary_dimensions_mm: [80.0, 50.0], features: [] },
      bottom: { view: 'bottom', image_url: demoSvgBox('BASE PLAN VIEW', 300, 240, true), original_resolution: [300, 240], features_detected: 5, primary_dimensions_mm: [80.0, 50.0], features: [] },
      left: { view: 'left', image_url: demoSvgBox('LEFT PROFILE', 240, 180, false), original_resolution: [240, 180], features_detected: 2, primary_dimensions_mm: [50.0, 30.0], features: [] },
      right: { view: 'right', image_url: demoSvgBox('RIGHT PROFILE', 240, 180, false), original_resolution: [240, 180], features_detected: 2, primary_dimensions_mm: [50.0, 30.0], features: [] },
    };

    setViewsData(demoViews);
    setScalePxToMm(3.75);
    setScanSessionId('demo-session-882');
    setCalibrationSpec({
      mode: 'known_dimension',
      reference_side: 'front',
      known_length_mm: 80.0,
      point_a_px: [58, 100],
      point_b_px: [262, 100],
      mm_per_unit: 80.0 / 204.0,
    });
    appendLog('ScannerChamber', 'info', 'Loaded 6-axis demo keyframe set with 80.0mm calibration reference.');
  };

  // Upload view photo to backend
  const handleUploadView = async (view: AxisView, file: File) => {
    const formData = new FormData();
    formData.append('project_id', projectId);
    formData.append('has_scale_reference', String(hasScaleRef));
    formData.append(view, file);

    try {
      const res = await fetch(`${API_BASE}/scans/upload-6-axis`, {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        const session = await res.json();
        setScanSessionId(session.id);
        setViewsData((prev) => ({ ...prev, ...session.views_data }));
      }
    } catch (e) {
      console.error('Upload failed', e);
    }
  };

  const handleKeyframesCaptured = (
    captures: Record<AxisView, KeyframeCapture>,
    calibration?: CalibrationSpec
  ) => {
    setCapturedKeyframes(captures);
    const newViewsData: Partial<Record<AxisView, ViewDetail>> = {};
    (Object.keys(captures) as AxisView[]).forEach((side) => {
      const cap = captures[side];
      newViewsData[side] = {
        view: side,
        image_url: cap.dataUrl,
        blur_score: cap.blurScore,
        original_resolution: [cap.width, cap.height],
        features_detected: 4,
        primary_dimensions_mm: [80.0, 50.0],
        features: [],
      };
    });
    setViewsData(newViewsData);

    if (calibration) {
      setCalibrationSpec(calibration);
      if (calibration.mm_per_unit) {
        setScalePxToMm(1.0 / calibration.mm_per_unit);
      }
    }
  };

  // Trigger Phase 3: SAM 2.1 + Depth Anything + Open3D 6-Side 3D Fusion
  const handleRunCvFusion = async () => {
    setIsFusing(true);
    setSystemStatus('GPU Vision Fusion...');
    appendLog('ModalGPUWorker', 'thought', 'Uploading 6 uncompressed PNG keyframes and metric calibration spec...');

    try {
      const batch = capturedKeyframes || (await generateDemoPngBatch());
      const calib: CalibrationSpec = calibrationSpec || {
        mode: 'known_dimension',
        reference_side: 'front',
        known_length_mm: 80.0,
        point_a_px: [58, 100],
        point_b_px: [262, 100],
        mm_per_unit: 80.0 / 204.0,
      };

      const fused = await uploadAndRunCvFusion(projectId, batch, calib, (ev: ScanWsEvent) => {
        if (ev.event === 'cv_segmentation_started') {
          appendLog('SAM2Worker', 'info', 'Running BF16 SAM 2.1 hand & background removal across 6 views...');
        } else if (ev.event === 'cv_fusion_completed') {
          appendLog('Open3DFusion', 'success', `6-side ICP registration finished (${ev.payload.point_count} pts).`);
        }
      });

      setScanSessionId(fused.scan_id);
      setGeometryReport(fused.geometry_report);
      setPlyUrl(resolveBackendAssetUrl(fused.ply_url));
      setSystemStatus('Fused .PLY Ready');

      // Attach SAM masked PNG URLs into viewsData grid
      setViewsData((prev) => {
        const next = { ...prev };
        (Object.keys(fused.masked_urls || {}) as AxisView[]).forEach((side) => {
          const mUrl = resolveBackendAssetUrl(fused.masked_urls[side]);
          if (mUrl && next[side]) {
            next[side] = { ...next[side]!, masked_url: mUrl };
          }
        });
        return next;
      });

      const bb = fused.geometry_report.bounding_box_mm;
      appendLog(
        'Open3DFusion',
        'success',
        `Fused [${fused.execution_mode}]: ${fused.geometry_report.point_count} points | ` +
          `Envelope ${bb[0]}×${bb[1]}×${bb[2]} mm | ICP ${(fused.geometry_report.icp_fitness_score * 100).toFixed(1)}% | ` +
          `${fused.geometry_report.planes.length} planes, ${fused.geometry_report.cylinders.length} cylinders.`
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Vision fusion failed';
      appendLog('Open3DFusion', 'error', msg);
      setSystemStatus('Fusion Error');
    } finally {
      setIsFusing(false);
    }
  };

  // Trigger Multi-Agent CAD Synthesis
  const handleSynthesizeCAD = async () => {
    setIsGenerating(true);

    if (!scanSessionId) {
      handleLoadDemo();
    }

    try {
      const res = await fetch(`${API_BASE}/generate/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scan_session_id: scanSessionId || 'demo-session-882',
          target_engine: 'cadquery',
        }),
      });

      if (res.ok) {
        const gen: CadGeneration = await res.json();
        setGeneration(gen);
      }
    } catch (e) {
      console.warn('Fallback local agent simulation loop active', e);
      simulateAgentLoop();
    }
  };

  const simulateAgentLoop = () => {
    const fakeLogs: AgentLog[] = [
      { id: '1', agent_name: 'VisionAnalyst', log_type: 'thought', message: 'Scanning all 6 orthogonal perspectives... Aligning Front and Top silhouettes.', created_at: new Date().toISOString() },
      { id: '2', agent_name: 'VisionAnalyst', log_type: 'info', message: 'Part Classification: Precision Mounting Bracket. Bounding Envelope: 80.0 x 50.0 x 30.0 mm.', created_at: new Date().toISOString() },
      { id: '3', agent_name: 'CSGArchitect', log_type: 'thought', message: 'Formulating CSG Recipe: Workplane("XY").box(80, 50, 30) -> Fillet Z-edges (r=4.0mm) -> Cut central counterbore hole dia 16mm.', created_at: new Date().toISOString() },
      { id: '4', agent_name: 'CadCoder', log_type: 'code', message: `import cadquery as cq\n\nresult = (\n    cq.Workplane("XY")\n    .box(80.0, 50.0, 30.0)\n    .edges("|Z")\n    .fillet(4.0)\n    .faces(">Z")\n    .workplane()\n    .hole(16.0)\n)`, created_at: new Date().toISOString() },
      { id: '5', agent_name: 'Validator', log_type: 'success', message: 'B-Rep Validation Passed: Closed manifold solid confirmed. STEP and STL exported successfully.', created_at: new Date().toISOString() },
    ];

    let i = 0;
    setAgentLogs([]);
    const timer = setInterval(() => {
      if (i < fakeLogs.length) {
        setAgentLogs((prev) => [...prev, fakeLogs[i]]);
        i++;
      } else {
        clearInterval(timer);
        setIsGenerating(false);
        setGeneration({
          id: 'demo-gen-001',
          scan_session_id: 'demo-session-882',
          version: 1,
          status: 'completed',
          dimensions_mm: { x: 80, y: 50, z: 30 },
          created_at: new Date().toISOString(),
          code: `import cadquery as cq\n\nresult = (\n    cq.Workplane("XY")\n    .box(80.0, 50.0, 30.0)\n    .edges("|Z")\n    .fillet(4.0)\n    .faces(">Z")\n    .workplane()\n    .hole(16.0)\n)`,
        });
      }
    }, 800);
  };

  return (
    <div className="min-h-screen bg-[#090d14] cad-grid-bg text-slate-100 flex flex-col">
      <Navbar unit={unit} setUnit={setUnit} systemStatus={systemStatus} />

      <main className="flex-1 p-4 lg:p-6 max-w-[1600px] w-full mx-auto space-y-5">
        {/* Top Action Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 bg-cad-card border border-cad-border p-3.5 rounded-xl shadow-lg">
          <div>
            <h1 className="text-base font-bold text-white flex items-center space-x-2">
              <span className="text-cyan-400 font-mono">PROJECT //</span>
              <span>Precision Aluminum Mounting Bracket</span>
            </h1>
            <p className="text-xs text-slate-400">
              6-Axis Guided Capture → SAM 2.1 + Depth Anything + Open3D Fusion → Parametric ISO 10303-21 STEP
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {/* Phase 3: Cloud GPU 3D Fusion Trigger */}
            <button
              onClick={handleRunCvFusion}
              disabled={isFusing}
              className={`flex items-center space-x-2 px-4 py-2.5 rounded-lg font-mono text-xs font-semibold tracking-wider transition border shadow-md ${
                isFusing
                  ? 'bg-emerald-900/40 text-emerald-200 border-emerald-700 cursor-not-allowed'
                  : 'bg-emerald-950/90 hover:bg-emerald-900 text-emerald-300 border-emerald-600/70'
              }`}
            >
              {isFusing ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin text-emerald-300" />
                  <span>FUSING 6 VIEWS...</span>
                </>
              ) : (
                <>
                  <Layers className="w-4 h-4 text-emerald-400" />
                  <span>FUSE 3D POINT CLOUD</span>
                </>
              )}
            </button>

            <button
              onClick={handleSynthesizeCAD}
              disabled={isGenerating}
              className={`flex items-center space-x-2 px-5 py-2.5 rounded-lg font-mono text-xs font-semibold tracking-wider transition shadow-lg ${
                isGenerating
                  ? 'bg-cyan-600/50 text-cyan-200 cursor-not-allowed'
                  : 'bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white shadow-cyan-500/20'
              }`}
            >
              {isGenerating ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin text-white" />
                  <span>SYNTHESIZING CAD...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  <span>SYNTHESIZE 3D CAD</span>
                </>
              )}
            </button>

            {generation?.status === 'completed' && (
              <button
                onClick={() => setShowExportModal(true)}
                className="flex items-center space-x-2 px-4 py-2.5 rounded-lg bg-emerald-950 text-emerald-300 border border-emerald-700 hover:bg-emerald-900 transition font-mono text-xs font-semibold shadow-md"
              >
                <Download className="w-4 h-4" />
                <span>EXPORT CAD PACKAGES</span>
              </button>
            )}
          </div>
        </div>

        {/* Workspace Split Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* Left Column: 6-Axis Scanning Chamber (5 cols) */}
          <div className="lg:col-span-5 space-y-4">
            {/* Capture Mode Tabs */}
            <div className="flex bg-cad-card border border-cad-border rounded-lg p-1 text-xs font-mono">
              <button
                onClick={() => setActiveTab('camera')}
                className={`flex-1 py-1.5 rounded transition flex items-center justify-center space-x-1.5 ${
                  activeTab === 'camera'
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Camera className="w-3.5 h-3.5" />
                <span>Live Camera (Blur Filter)</span>
              </button>
              <button
                onClick={() => setActiveTab('grid')}
                className={`flex-1 py-1.5 rounded transition flex items-center justify-center space-x-1.5 ${
                  activeTab === 'grid'
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Grid className="w-3.5 h-3.5" />
                <span>6-View Masked Grid</span>
              </button>
            </div>

            {activeTab === 'camera' ? (
              <ScannerChamber
                onAllKeyframesCaptured={handleKeyframesCaptured}
                onLoadDemo={handleLoadDemo}
              />
            ) : (
              <SixAxisCapture
                viewsData={viewsData}
                onUploadView={handleUploadView}
                onLoadDemo={handleLoadDemo}
                hasScaleRef={hasScaleRef}
                setHasScaleRef={setHasScaleRef}
                scalePxToMm={scalePxToMm}
              />
            )}

            {/* Open3D Primitive & Alignment Report Inspector */}
            {geometryReport ? (
              <div className="p-3.5 bg-cad-card border border-emerald-700/60 rounded-xl text-xs font-mono space-y-2 shadow-lg">
                <div className="flex items-center justify-between text-emerald-300 font-semibold">
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    Open3D Geometry Report (1:1 mm)
                  </span>
                  <span className="text-[11px] bg-emerald-950 px-2 py-0.5 rounded border border-emerald-800">
                    ICP {(geometryReport.icp_fitness_score * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-[11px] text-slate-300 bg-cad-dark/70 p-2 rounded border border-cad-border">
                  <div>
                    <span className="text-slate-500 block">BBox (mm)</span>
                    <span className="font-bold text-white">
                      {geometryReport.bounding_box_mm.join('×')}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Planes / Cyls</span>
                    <span className="font-bold text-cyan-300">
                      {geometryReport.planes.length}P / {geometryReport.cylinders.length}C
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Symmetry</span>
                    <span className="font-bold text-emerald-300">
                      {geometryReport.symmetry_planes.join(', ') || 'None'}
                    </span>
                  </div>
                </div>
                {geometryReport.cylinders.length > 0 && (
                  <div className="text-[11px] text-slate-400">
                    Detected {geometryReport.cylinders[0].kind}: R={geometryReport.cylinders[0].radius_mm}mm, Depth={geometryReport.cylinders[0].depth_mm}mm
                  </div>
                )}
              </div>
            ) : (
              <div className="p-3 bg-cad-card/60 border border-cad-border/70 rounded-xl text-xs space-y-1.5 text-slate-400 font-mono">
                <div className="flex items-center space-x-1.5 text-cyan-400 font-semibold">
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>Phase 3 GPU Vision Protocol</span>
                </div>
                <p className="text-[11px] leading-relaxed">
                  Capture 6 crisp keyframes and click <strong>FUSE 3D POINT CLOUD</strong> to strip hands via SAM 2.1, estimate depth, align views in Open3D, and inspect the 1:1 mm .PLY scan.
                </p>
              </div>
            )}
          </div>

          {/* Right Column: 3D CAD Viewport & Multi-Agent Terminal (7 cols) */}
          <div className="lg:col-span-7 flex flex-col space-y-4">
            <div className="h-[430px] w-full">
              <CadViewport3D
                stlUrl={generation?.stl_file ? `http://localhost:8000${generation.stl_file}` : undefined}
                plyUrl={plyUrl}
                geometryReport={geometryReport}
                dimensions={generation?.dimensions_mm}
                unit={unit}
              />
            </div>

            <div className="h-[280px] w-full">
              <AgentTerminal
                logs={agentLogs}
                status={generation?.status || (isFusing ? 'generating' : isGenerating ? 'generating' : 'idle')}
              />
            </div>
          </div>
        </div>
      </main>

      {showExportModal && generation && (
        <ExportModal generation={generation} onClose={() => setShowExportModal(false)} />
      )}
    </div>
  );
};

export default App;
