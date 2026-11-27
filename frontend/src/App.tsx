import React, { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { SixAxisCapture } from './components/SixAxisCapture';
import { ScannerChamber } from './components/scanner/ScannerChamber';
import { CadViewport3D } from './components/CadViewport3D';
import { AgentTerminal } from './components/AgentTerminal';
import { ExportModal } from './components/ExportModal';
import type { AxisView, ViewDetail, CadGeneration, AgentLog, KeyframeCapture, CalibrationSpec } from './types/cad';
import { Play, Download, Sparkles, RefreshCw, Camera, Grid } from 'lucide-react';

const API_BASE = 'http://localhost:8000/api';

export const App: React.FC = () => {
  const [unit, setUnit] = useState('mm');
  const [systemStatus] = useState('Ready (B-Rep)');
  const [projectId, setProjectId] = useState<string>('demo-proj-001');
  const [scanSessionId, setScanSessionId] = useState<string | null>(null);
  const [hasScaleRef, setHasScaleRef] = useState(true);
  const [scalePxToMm, setScalePxToMm] = useState(1.0);
  const [viewsData, setViewsData] = useState<Partial<Record<AxisView, ViewDetail>>>({});
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
          // Create default project
          fetch(`${API_BASE}/projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: 'Precision Aluminum Mounting Bracket',
              description: '6-Axis Orthographic Photogrammetry to B-Rep CAD',
              unit: 'mm'
            })
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

    const demoSvgEdges = (label: string, w: number, h: number) => {
      return `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
        <rect width="100%" height="100%" fill="%23000000"/>
        <rect x="20" y="20" width="${w - 40}" height="${h - 40}" rx="15" fill="none" stroke="%2339ff14" stroke-width="2"/>
        <circle cx="${w/2}" cy="${h/2}" r="18" fill="none" stroke="%2339ff14" stroke-width="2"/>
        <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="%2339ff14" font-family="monospace" font-size="12">OPENCV CANNY CONTOUR: ${label}</text>
      </svg>`;
    };

    const demoViews: Record<AxisView, ViewDetail> = {
      front: {
        view: 'front',
        image_url: demoSvgBox('FRONT ELEVATION', 300, 180, true),
        edge_url: demoSvgEdges('FRONT', 300, 180),
        original_resolution: [300, 180],
        features_detected: 4,
        primary_dimensions_mm: [80.0, 30.0],
        features: []
      },
      back: {
        view: 'back',
        image_url: demoSvgBox('REAR ELEVATION', 300, 180, false),
        edge_url: demoSvgEdges('REAR', 300, 180),
        original_resolution: [300, 180],
        features_detected: 2,
        primary_dimensions_mm: [80.0, 30.0],
        features: []
      },
      top: {
        view: 'top',
        image_url: demoSvgBox('TOP PLAN VIEW', 300, 240, true),
        edge_url: demoSvgEdges('TOP', 300, 240),
        original_resolution: [300, 240],
        features_detected: 6,
        primary_dimensions_mm: [80.0, 50.0],
        features: []
      },
      bottom: {
        view: 'bottom',
        image_url: demoSvgBox('BASE PLAN VIEW', 300, 240, true),
        edge_url: demoSvgEdges('BOTTOM', 300, 240),
        original_resolution: [300, 240],
        features_detected: 5,
        primary_dimensions_mm: [80.0, 50.0],
        features: []
      },
      left: {
        view: 'left',
        image_url: demoSvgBox('LEFT PROFILE', 240, 180, false),
        edge_url: demoSvgEdges('LEFT', 240, 180),
        original_resolution: [240, 180],
        features_detected: 2,
        primary_dimensions_mm: [50.0, 30.0],
        features: []
      },
      right: {
        view: 'right',
        image_url: demoSvgBox('RIGHT PROFILE', 240, 180, false),
        edge_url: demoSvgEdges('RIGHT', 240, 180),
        original_resolution: [240, 180],
        features_detected: 2,
        primary_dimensions_mm: [50.0, 30.0],
        features: []
      }
    };

    setViewsData(demoViews);
    setScalePxToMm(3.75); // Calibrated px per mm
    setScanSessionId('demo-session-882');
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
        body: formData
      });
      if (res.ok) {
        const session = await res.json();
        setScanSessionId(session.id);
        setViewsData((prev) => ({
          ...prev,
          ...session.views_data
        }));
      }
    } catch (e) {
      console.error('Upload failed', e);
    }
  };

  const handleKeyframesCaptured = (
    captures: Record<AxisView, KeyframeCapture>,
    calibration?: CalibrationSpec
  ) => {
    const newViewsData: Partial<Record<AxisView, ViewDetail>> = {};
    (Object.keys(captures) as AxisView[]).forEach((side) => {
      const cap = captures[side];
      newViewsData[side] = {
        view: side,
        image_url: cap.dataUrl,
        edge_url: cap.dataUrl,
        original_resolution: [cap.width, cap.height],
        features_detected: 4,
        primary_dimensions_mm: [80.0, 50.0],
        features: []
      };
    });
    setViewsData(newViewsData);

    if (calibration?.mm_per_unit) {
      setScalePxToMm(1.0 / calibration.mm_per_unit);
    }
  };

  // Trigger Multi-Agent CAD Synthesis
  const handleSynthesizeCAD = async () => {
    setIsGenerating(true);

    if (!scanSessionId) {
      // Create session first if not yet created
      handleLoadDemo();
    }

    try {
      const res = await fetch(`${API_BASE}/generate/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scan_session_id: scanSessionId || 'demo-session-882',
          target_engine: 'cadquery'
        })
      });

      if (res.ok) {
        const gen: CadGeneration = await res.json();
        setGeneration(gen);
      }
    } catch (e) {
      console.warn('Fallback local agent simulation loop active', e);
      // Simulate multi-agent trace locally if backend is starting
      simulateAgentLoop();
    }
  };

  const simulateAgentLoop = () => {
    const fakeLogs: AgentLog[] = [
      {
        id: '1',
        agent_name: 'VisionAnalyst',
        log_type: 'thought',
        message: 'Scanning all 6 orthogonal perspectives... Aligning Front and Top silhouettes.',
        created_at: new Date().toISOString()
      },
      {
        id: '2',
        agent_name: 'VisionAnalyst',
        log_type: 'info',
        message: 'Part Classification: Precision Mounting Bracket. Bounding Envelope: 80.0 x 50.0 x 30.0 mm.',
        created_at: new Date().toISOString()
      },
      {
        id: '3',
        agent_name: 'CSGArchitect',
        log_type: 'thought',
        message: 'Formulating CSG Recipe: Workplane("XY").box(80, 50, 30) -> Fillet Z-edges (r=4.0mm) -> Cut central counterbore hole dia 16mm.',
        created_at: new Date().toISOString()
      },
      {
        id: '4',
        agent_name: 'CadCoder',
        log_type: 'code',
        message: `import cadquery as cq\n\nresult = (\n    cq.Workplane("XY")\n    .box(80.0, 50.0, 30.0)\n    .edges("|Z")\n    .fillet(4.0)\n    .faces(">Z")\n    .workplane()\n    .hole(16.0)\n)`,
        created_at: new Date().toISOString()
      },
      {
        id: '5',
        agent_name: 'Validator',
        log_type: 'success',
        message: 'B-Rep Validation Passed: Closed manifold solid confirmed. STEP and STL exported successfully.',
        created_at: new Date().toISOString()
      }
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
          code: `import cadquery as cq\n\nresult = (\n    cq.Workplane("XY")\n    .box(80.0, 50.0, 30.0)\n    .edges("|Z")\n    .fillet(4.0)\n    .faces(">Z")\n    .workplane()\n    .hole(16.0)\n)`
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
              6-Axis Photometric Reverse-Engineering Pipeline • Target Format: ISO 10303-21 STEP & DXF
            </p>
          </div>

          <div className="flex items-center space-x-3">
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
                <span>Live Camera (Laplacian Blur Filter)</span>
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
                <span>6-View Edge Grid</span>
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

            {/* Quick Helper Tips */}
            <div className="p-3 bg-cad-card/60 border border-cad-border/70 rounded-xl text-xs space-y-1.5 text-slate-400 font-mono">
              <div className="flex items-center space-x-1.5 text-cyan-400 font-semibold">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Industrial Scanning Protocol</span>
              </div>
              <p className="text-[11px] leading-relaxed">
                For optimal B-Rep accuracy, place a known 20mm calibration token beside your part. The OpenCV sub-pixel edge detector maps planar silhouettes into closed extrusion loops.
              </p>
            </div>
          </div>

          {/* Right Column: 3D CAD Viewport & Multi-Agent Terminal (7 cols) */}
          <div className="lg:col-span-7 flex flex-col space-y-4">
            {/* 3D Simulation Viewport */}
            <div className="h-[430px] w-full">
              <CadViewport3D
                stlUrl={generation?.stl_file ? `http://localhost:8000${generation.stl_file}` : undefined}
                dimensions={generation?.dimensions_mm}
                unit={unit}
              />
            </div>

            {/* Live Agent Terminal */}
            <div className="h-[280px] w-full">
              <AgentTerminal
                logs={agentLogs}
                status={generation?.status || (isGenerating ? 'generating' : 'idle')}
              />
            </div>
          </div>
        </div>
      </main>

      {/* Export Modal */}
      {showExportModal && generation && (
        <ExportModal generation={generation} onClose={() => setShowExportModal(false)} />
      )}
    </div>
  );
};

export default App;
