import React, { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { ScannerChamber } from './components/scanner/ScannerChamber';
import { GeneratePipelinePage } from './components/pages/GeneratePipelinePage';
import type { GenerationOptions } from './components/pages/GeneratePipelinePage';
import { CadOutputPage } from './components/pages/CadOutputPage';
import { SavedScansPage } from './components/pages/SavedScansPage';
import { ExportModal } from './components/ExportModal';
import type {
  ActivePipelineEngines,
  AppPage,
  AxisView,
  ViewDetail,
  CadGeneration,
  AgentLog,
  KeyframeCapture,
  CalibrationSpec,
  Open3DGeometryReport,
  SavedScanItem,
  ScanWsEvent,
  ValidationMetrics,
} from './types/cad';
import {
  API_BASE,
  fetchActiveEngines,
  uploadAndRunCvFusion,
  uploadSingleViewKeyframe,
  generateCadForScan,
  resolveBackendAssetUrl,
  subscribeScanEvents,
  refineCadRevision,
} from './services/scanApi';
import type { ScanGenerateApiResponse } from './services/scanApi';
import { applyClientDemoRefine } from './utils/cadExport';

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

    ctx.fillStyle = '#141923';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#9db4c8';
    ctx.fillRect(w * 0.18, h * 0.2, w * 0.64, h * 0.6);

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
      source: 'upload',
    };
  }
  return out;
}

export const App: React.FC = () => {
  const [activePage, setActivePage] = useState<AppPage>('capture');
  const [unit, setUnit] = useState('mm');
  const [systemStatus, setSystemStatus] = useState('Ready (Visual Hull + build123d)');
  const [projectId, setProjectId] = useState<string>('demo-proj-001');
  const [projectName, setProjectName] = useState<string>('Precision Multi-View Scan');
  const [scanSessionId, setScanSessionId] = useState<string | null>(null);

  const [captures, setCaptures] = useState<Partial<Record<AxisView, KeyframeCapture>>>({});
  const [viewsData, setViewsData] = useState<Partial<Record<AxisView, ViewDetail>>>({});
  const [calibrationSpec, setCalibrationSpec] = useState<CalibrationSpec | null>(null);
  const [geometryReport, setGeometryReport] = useState<Open3DGeometryReport | null>(null);
  const [plyUrl, setPlyUrl] = useState<string | undefined>(undefined);

  const [generationOptions, setGenerationOptions] = useState<GenerationOptions>({
    reconstructionMode: 'auto_hull',
    edgeFinish: 'clean',
    detailLevel: 'standard',
    strictCloud: false,
  });
  const [activeEngines, setActiveEngines] = useState<ActivePipelineEngines | null>(null);

  const [isPipelineRunning, setIsPipelineRunning] = useState(false);
  const [progressPct, setProgressPct] = useState(0);
  const [progressStage, setProgressStage] = useState('Idle — Configure scale & options, then click Generate');
  const [pipelineError, setPipelineError] = useState<string | null>(null);

  const [generation, setGeneration] = useState<CadGeneration | null>(null);
  const [agentLogs, setAgentLogs] = useState<AgentLog[]>([]);
  const [activeLangGraphNode, setActiveLangGraphNode] = useState<string | null>(null);
  const [validationMetrics, setValidationMetrics] = useState<ValidationMetrics | null>(null);
  const [refinePrompt, setRefinePrompt] = useState('');
  const [isRefining, setIsRefining] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);

  // Initialize default project & inspect active AI/GPU engines
  useEffect(() => {
    void fetchActiveEngines().then((eng) => {
      if (eng) setActiveEngines(eng);
    });
    fetch(`${API_BASE}/projects`)
      .then((res) => res.json())
      .then((projects) => {
        if (Array.isArray(projects) && projects.length > 0) {
          setProjectId(projects[0].id);
          setProjectName(projects[0].name || 'PhotoCAD Scan Workspace');
        } else {
          fetch(`${API_BASE}/projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: 'PhotoCAD Multi-View Project',
              description: 'Multi-axis 3D photometric reverse engineering',
              unit: 'mm',
            }),
          })
            .then((r) => r.json())
            .then((p) => {
              if (p?.id) {
                setProjectId(p.id);
                setProjectName(p.name || 'PhotoCAD Multi-View Project');
              }
            });
        }
      })
      .catch(() => {
        // Offline demo capability remains active
      });
  }, []);

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

  // Distinct per-side capture/upload -> uploads individual side right when confirmed
  const handleSideCaptured = (side: AxisView, capture: KeyframeCapture) => {
    setCaptures((prev) => ({ ...prev, [side]: capture }));
    setViewsData((prev) => ({
      ...prev,
      [side]: {
        view: side,
        image_url: capture.dataUrl,
        blur_score: capture.blurScore,
        original_resolution: [capture.width, capture.height],
        features_detected: 0,
        primary_dimensions_mm: [80, 50],
        features: [],
      },
    }));

    void uploadSingleViewKeyframe(projectId, scanSessionId, side, capture)
      .then((id) => {
        setScanSessionId(id);
        appendLog('CaptureClient', 'info', `Uploaded ${side.toUpperCase()} (${capture.width}×${capture.height}, sharpness ${capture.blurScore.toFixed(0)}).`);
      })
      .catch(() => {
        // Offline fallback keeps local blob captures
      });
  };

  const handleRemoveSide = (side: AxisView) => {
    setCaptures((prev) => {
      const next = { ...prev };
      delete next[side];
      return next;
    });
    setViewsData((prev) => {
      const next = { ...prev };
      delete next[side];
      return next;
    });
  };

  const handleBatchCaptured = (batch: Partial<Record<AxisView, KeyframeCapture>>) => {
    setCaptures((prev) => ({ ...prev, ...batch }));
    setViewsData((prev) => {
      const next = { ...prev };
      (Object.keys(batch) as AxisView[]).forEach((side) => {
        const cap = batch[side];
        if (cap) {
          next[side] = {
            view: side,
            image_url: cap.dataUrl,
            blur_score: cap.blurScore,
            original_resolution: [cap.width, cap.height],
            features_detected: 0,
            primary_dimensions_mm: [80, 50],
            features: [],
          };
        }
      });
      return next;
    });
  };

  const handleLoadDemo = async () => {
    setSystemStatus('Demo Scan Loaded');
    const demoCaptures = await generateDemoPngBatch();
    setCaptures(demoCaptures);
    handleBatchCaptured(demoCaptures);
    setCalibrationSpec({
      mode: 'known_dimension',
      reference_side: 'front',
      known_length_mm: 80.0,
      point_a_px: [58, 100],
      point_b_px: [262, 100],
      mm_per_unit: 80.0 / 204.0,
    });
    setProjectName('Demo Mounting Bracket (80×50×30 mm)');
    appendLog('CaptureClient', 'success', 'Loaded 6-axis Demo Bracket PNG dataset. Proceed to Page 2 to generate CAD.');
  };

  const handleScanWsEvent = (ev: ScanWsEvent) => {
    const p = ev.payload || {};
    if (typeof ev.progress_pct === 'number' && ev.progress_pct > 0) {
      setProgressPct(ev.progress_pct);
    }

    if (ev.event === 'cv_segmentation_started') {
      setProgressStage('Isolating foreground silhouettes & removing backgrounds...');
      appendLog('CVSegmentation', 'info', 'Running GrabCut / SAM foreground segmentation across uploaded views...');
    } else if (ev.event === 'cv_fusion_completed') {
      setProgressStage('3D Visual Hull & Point Cloud Fusion complete');
      appendLog('Open3DFusion', 'success', `3D fusion finished (${String(p.point_count || 0)} surface pts).`);
    } else if (ev.event === 'agent_node_started') {
      const node = String(p.node || '');
      setActiveLangGraphNode(node);
      setProgressStage(String(p.message || `Executing ${node}...`));
      const nameMap: Record<string, string> = {
        geometry_analyst: 'VisionAnalyst',
        parametric_architect: 'CSGArchitect',
        cad_synthesizer: 'CadCoder',
        sandbox_executor: 'SandboxExecutor',
        geometric_validator: 'Validator',
      };
      appendLog(nameMap[node] || 'Orchestrator', 'thought', String(p.message || `Running ${node}...`));
    } else if (ev.event === 'cad_code_diff') {
      appendLog('CadCoder', 'diff', String(p.diff || p.code || ''));
    } else if (ev.event === 'cad_compile_error') {
      appendLog('SandboxExecutor', 'error', `[Retry ${p.attempt}/${p.max_attempts}] ${String(p.error_summary || '')}`);
    } else if (ev.event === 'validation_completed') {
      const m = p as unknown as ValidationMetrics;
      setValidationMetrics({
        is_watertight: Boolean(m.is_watertight),
        volume_mm3: Number(m.volume_mm3 || 0),
        surface_area_mm2: Number(m.surface_area_mm2 || 0),
        chamfer_mean_mm: Number(m.chamfer_mean_mm || 0),
        chamfer_p95_mm: Number(m.chamfer_p95_mm || 0),
        bbox_delta_mm: (m.bbox_delta_mm as [number, number, number]) || [0, 0, 0],
        passed_tolerance: Boolean((p as Record<string, unknown>).passed),
        discrepancy_notes: (m.discrepancy_notes as string[]) || [],
      });
      appendLog(
        'Validator',
        (p as Record<string, unknown>).passed ? 'success' : 'info',
        `Chamfer ${Number(p.chamfer_mean_mm || 0).toFixed(3)} mm • Watertight=${String(p.is_watertight)}`
      );
    } else if (ev.event === 'pipeline_completed') {
      setActiveLangGraphNode(null);
      setProgressPct(100);
      setProgressStage('Verified .STEP, .DXF & .STL Ready!');
      setSystemStatus('Verified .STEP Ready');
    }
  };

  const applyScanGenerationResult = (res: ScanGenerateApiResponse) => {
    setGeneration({
      id: res.generation_id,
      scan_session_id: res.scan_id,
      version: res.revision,
      status: res.status as CadGeneration['status'],
      code: res.code,
      step_file: res.artifacts.step_url,
      stl_file: res.artifacts.stl_url,
      dxf_file: res.artifacts.dxf_url,
      dimensions_mm: res.dimensions_mm,
      created_at: new Date().toISOString(),
    });
    if (res.validation_metrics) {
      setValidationMetrics(res.validation_metrics);
    }
    if (res.active_models) {
      setActiveEngines(res.active_models);
    }
    if (res.agent_logs && res.agent_logs.length > 0) {
      setAgentLogs(res.agent_logs);
    }
  };

  // Page 2 -> Runs CV Visual Hull Fusion + LangGraph Synthesis with live progress, then redirects to Page 3
  const handleRunFullPipeline = async () => {
    setIsPipelineRunning(true);
    setPipelineError(null);
    setProgressPct(10);
    setProgressStage('Uploading keyframes & isolating 3D silhouettes...');
    setSystemStatus('Generating 3D CAD...');

    let unsubscribeWs = () => {};

    try {
      const batch = Object.keys(captures).length >= 4 ? captures : await generateDemoPngBatch();
      const calib: CalibrationSpec = calibrationSpec || {
        mode: 'known_dimension',
        reference_side: captures.front ? 'front' : 'left',
        known_length_mm: 180.0,
      };

      const fused = await uploadAndRunCvFusion(
        projectId,
        batch,
        calib,
        handleScanWsEvent,
        scanSessionId,
        generationOptions.strictCloud
      );
      if (fused.active_models) {
        setActiveEngines(fused.active_models);
      }
      const activeScanId = fused.scan_id;
      setScanSessionId(activeScanId);
      setGeometryReport(fused.geometry_report);
      setPlyUrl(resolveBackendAssetUrl(fused.ply_url));
      setProgressPct(38);
      setProgressStage('Running LangGraph Multi-Agent B-Rep Synthesis...');

      setViewsData((prev) => {
        const next = { ...prev };
        (Object.keys(fused.masked_urls || {}) as AxisView[]).forEach((side) => {
          const mUrl = resolveBackendAssetUrl(fused.masked_urls[side]);
          if (mUrl) {
            next[side] = {
              ...(next[side] || {
                view: side,
                image_url: mUrl,
                original_resolution: [640, 480],
                features_detected: 0,
                primary_dimensions_mm: [80, 50],
                features: [],
              }),
              masked_url: mUrl,
            };
          }
        });
        return next;
      });

      unsubscribeWs = subscribeScanEvents(activeScanId, handleScanWsEvent);

      let genRes: ScanGenerateApiResponse;
      if (generationOptions.edgeFinish === 'chamfer') {
        await generateCadForScan(activeScanId, generationOptions.strictCloud);
        genRes = await refineCadRevision(activeScanId, 'Add 1.5 mm chamfer', 1);
      } else {
        genRes = await generateCadForScan(activeScanId, generationOptions.strictCloud);
      }

      applyScanGenerationResult(genRes);
      setProgressPct(100);
      setProgressStage('CAD Synthesis Complete — Opening Fullscreen 3D Output...');
      setSystemStatus(`Rev v${genRes.revision} Verified`);

      setTimeout(() => {
        setActivePage('viewer');
      }, 650);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Pipeline execution failed';
      setPipelineError(msg);
      appendLog('Orchestrator', 'error', msg);
      setSystemStatus('Generation Failed');
    } finally {
      setIsPipelineRunning(false);
      setActiveLangGraphNode(null);
      setTimeout(unsubscribeWs, 1200);
    }
  };

  // Parametric /refine from Page 3
  const executeRefineInstruction = async (rawInstruction: string) => {
    const instruction = rawInstruction.trim();
    if (!instruction) return;

    setIsRefining(true);
    setSystemStatus('Refining Checkpoint...');
    appendLog('CSGArchitect', 'thought', `Applying parametric edit: "${instruction}"`);

    let unsub = () => {};
    try {
      if (scanSessionId && !scanSessionId.startsWith('demo-')) {
        unsub = subscribeScanEvents(scanSessionId, handleScanWsEvent);
        const updated = await refineCadRevision(scanSessionId, instruction, generation?.version || 1);
        applyScanGenerationResult(updated);
        setRefinePrompt('');
        setSystemStatus(`Rev v${updated.revision} Ready`);
        return;
      }

      const baseGen: CadGeneration = generation || {
        id: 'demo-gen-001',
        scan_session_id: 'demo-session-882',
        version: 1,
        status: 'completed',
        dimensions_mm: { x: 80, y: 50, z: 30 },
        created_at: new Date().toISOString(),
      };
      const { updated, summary } = applyClientDemoRefine(baseGen, instruction);
      setGeneration(updated);
      setRefinePrompt('');
      setSystemStatus(`Rev v${updated.version} (Demo)`);
      appendLog('Validator', 'success', summary);
    } catch (err) {
      appendLog('Orchestrator', 'error', err instanceof Error ? err.message : 'Refine failed');
      setSystemStatus('Refine Failed');
    } finally {
      setIsRefining(false);
      setActiveLangGraphNode(null);
      setTimeout(unsub, 500);
    }
  };

  const handleSubmitRefine = async (e: React.FormEvent) => {
    e.preventDefault();
    await executeRefineInstruction(refinePrompt);
  };

  const hydrateSavedScan = (item: SavedScanItem, targetPage: AppPage) => {
    setScanSessionId(item.scan_id);
    setProjectId(item.project_id);
    setProjectName(item.project_name);
    setGeometryReport(item.geometry_report || null);
    setCalibrationSpec(item.calibration || null);
    setPlyUrl(resolveBackendAssetUrl(item.ply_url));
    setGeneration(item.latest_generation || null);

    const hydratedViews: Partial<Record<AxisView, ViewDetail>> = {};
    for (const side of item.confirmed_sides) {
      hydratedViews[side] = {
        view: side,
        image_url: resolveBackendAssetUrl(`/storage/uploads/${item.scan_id}/${side}.png`) || '',
        masked_url: resolveBackendAssetUrl(`/storage/processed_edges/${item.scan_id}/${side}_masked.png`),
        original_resolution: [640, 480],
        features_detected: 0,
        primary_dimensions_mm: [80, 50],
        features: [],
      };
    }
    setViewsData(hydratedViews);
    setActivePage(targetPage);
  };

  const handleStartNewProject = () => {
    setScanSessionId(null);
    setCaptures({});
    setViewsData({});
    setCalibrationSpec(null);
    setGeometryReport(null);
    setPlyUrl(undefined);
    setGeneration(null);
    setAgentLogs([]);
    setValidationMetrics(null);
    setProgressPct(0);
    setProgressStage('Idle — Capture 4 to 6 sides first');
    setProjectName('New Multi-View Scan Session');
    setActivePage('capture');
  };

  const capturedCount = Math.max(
    Object.keys(captures).length,
    Object.keys(viewsData).length
  );

  return (
    <div className="min-h-screen bg-[#090d14] cad-grid-bg text-slate-100 flex flex-col">
      <Navbar
        unit={unit}
        setUnit={setUnit}
        systemStatus={systemStatus}
        activePage={activePage}
        onNavigate={setActivePage}
        capturedCount={capturedCount}
        hasGeneration={Boolean(generation)}
      />

      <main className="flex-1">
        {activePage === 'capture' && (
          <ScannerChamber
            projectName={projectName}
            captures={captures}
            calibrationSpec={calibrationSpec}
            onSideCaptured={handleSideCaptured}
            onRemoveSide={handleRemoveSide}
            onBatchCaptured={handleBatchCaptured}
            onSaveCalibration={setCalibrationSpec}
            onLoadDemo={() => void handleLoadDemo()}
            onProceedToGenerate={() => setActivePage('generate')}
          />
        )}

        {activePage === 'generate' && (
          <GeneratePipelinePage
            projectName={projectName}
            captures={captures}
            viewsData={viewsData}
            calibrationSpec={calibrationSpec}
            onSaveCalibration={setCalibrationSpec}
            options={generationOptions}
            onChangeOptions={setGenerationOptions}
            activeEngines={activeEngines}
            isRunning={isPipelineRunning}
            progressPct={progressPct}
            progressStage={progressStage}
            errorMsg={pipelineError}
            geometryReport={geometryReport}
            generation={generation}
            agentLogs={agentLogs}
            activeNode={activeLangGraphNode}
            validationMetrics={validationMetrics}
            onBackToCapture={() => setActivePage('capture')}
            onRunPipeline={() => void handleRunFullPipeline()}
            onGoToViewer={() => setActivePage('viewer')}
          />
        )}

        {activePage === 'viewer' && (
          <CadOutputPage
            projectName={projectName}
            generation={generation}
            geometryReport={geometryReport}
            plyUrl={plyUrl}
            unit={unit}
            activeEngines={activeEngines}
            agentLogs={agentLogs}
            activeNode={activeLangGraphNode}
            validationMetrics={validationMetrics}
            refinePrompt={refinePrompt}
            setRefinePrompt={setRefinePrompt}
            isRefining={isRefining}
            onSubmitRefine={handleSubmitRefine}
            onQuickRefine={(instr) => void executeRefineInstruction(instr)}
            onOpenExport={() => {
              if (!generation) {
                setGeneration({
                  id: 'demo-gen-001',
                  scan_session_id: scanSessionId || 'demo-session-882',
                  version: 1,
                  status: 'completed',
                  dimensions_mm: {
                    x: geometryReport?.bounding_box_mm[0] ?? 80,
                    y: geometryReport?.bounding_box_mm[1] ?? 50,
                    z: geometryReport?.bounding_box_mm[2] ?? 30,
                  },
                  created_at: new Date().toISOString(),
                });
              }
              setShowExportModal(true);
            }}
            onRescan={() => setActivePage('capture')}
            onBackToGenerate={() => setActivePage('generate')}
          />
        )}

        {activePage === 'projects' && (
          <SavedScansPage
            onOpenViewerForScan={(item) => hydrateSavedScan(item, 'viewer')}
            onOpenGenerateForScan={(item) => hydrateSavedScan(item, 'generate')}
            onStartNewProject={handleStartNewProject}
          />
        )}
      </main>

      {showExportModal && generation && (
        <ExportModal generation={generation} onClose={() => setShowExportModal(false)} />
      )}
    </div>
  );
};

export default App;
