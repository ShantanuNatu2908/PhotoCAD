import React, { useState } from 'react';
import {
  Sliders,
  Layers,
  Play,
  Ruler,
  ArrowLeft,
  ArrowRight,
  RefreshCw,
  CheckCircle2,
  Eye,
  Sparkles,
  AlertCircle,
} from 'lucide-react';
import { ScaleCalibrator } from '../scanner/ScaleCalibrator';
import { AgentTerminal } from '../AgentTerminal';
import type {
  ActivePipelineEngines,
  AxisView,
  CalibrationSpec,
  CadGeneration,
  KeyframeCapture,
  Open3DGeometryReport,
  ValidationMetrics,
  ViewDetail,
  AgentLog,
} from '../../types/cad';

export interface GenerationOptions {
  reconstructionMode: 'auto_hull' | 'prismatic';
  edgeFinish: 'clean' | 'fillet' | 'chamfer';
  detailLevel: 'standard' | 'high';
  strictCloud: boolean;
}

interface GeneratePipelinePageProps {
  projectName: string;
  captures: Partial<Record<AxisView, KeyframeCapture>>;
  viewsData: Partial<Record<AxisView, ViewDetail>>;
  calibrationSpec: CalibrationSpec | null;
  onSaveCalibration: (spec: CalibrationSpec) => void;
  options: GenerationOptions;
  onChangeOptions: (opts: GenerationOptions) => void;
  activeEngines: ActivePipelineEngines | null;
  isRunning: boolean;
  progressPct: number;
  progressStage: string;
  errorMsg: string | null;
  geometryReport: Open3DGeometryReport | null;
  generation: CadGeneration | null;
  agentLogs: AgentLog[];
  activeNode: string | null;
  validationMetrics: ValidationMetrics | null;
  onBackToCapture: () => void;
  onRunPipeline: () => void;
  onGoToViewer: () => void;
}

const AXIS_LABELS: Array<{ key: AxisView; label: string }> = [
  { key: 'front', label: 'FRONT (+Y)' },
  { key: 'back', label: 'BACK (-Y)' },
  { key: 'left', label: 'LEFT (-X)' },
  { key: 'right', label: 'RIGHT (+X)' },
  { key: 'top', label: 'TOP (+Z)' },
  { key: 'bottom', label: 'BOTTOM (-Z)' },
];

export const GeneratePipelinePage: React.FC<GeneratePipelinePageProps> = ({
  projectName,
  captures,
  viewsData,
  calibrationSpec,
  onSaveCalibration,
  options,
  onChangeOptions,
  activeEngines,
  isRunning,
  progressPct,
  progressStage,
  errorMsg,
  geometryReport,
  generation,
  agentLogs,
  activeNode,
  validationMetrics,
  onBackToCapture,
  onRunPipeline,
  onGoToViewer,
}) => {
  const [showMasked, setShowMasked] = useState(true);
  const [showCalibrator, setShowCalibrator] = useState(false);
  const [knownLengthInput, setKnownLengthInput] = useState<string>(
    String(calibrationSpec?.known_length_mm ?? 180)
  );
  const [refSide, setRefSide] = useState<AxisView>(
    calibrationSpec?.reference_side ?? (captures.front ? 'front' : captures.left ? 'left' : 'top')
  );

  const capturedCount = AXIS_LABELS.filter((a) => captures[a.key] || viewsData[a.key]?.image_url).length;
  const primaryCalibImage =
    captures[refSide]?.dataUrl ||
    viewsData[refSide]?.image_url ||
    captures.front?.dataUrl ||
    viewsData.front?.image_url ||
    Object.values(captures)[0]?.dataUrl ||
    '';

  const handleQuickCalibSave = () => {
    const val = parseFloat(knownLengthInput);
    if (!Number.isFinite(val) || val <= 1) return;
    onSaveCalibration({
      mode: 'known_dimension',
      reference_side: refSide,
      known_length_mm: val,
    });
  };

  return (
    <div className="max-w-[1440px] mx-auto p-4 lg:p-6 space-y-5">
      {/* Header Bar */}
      <div className="bg-cad-card border border-cad-border rounded-xl p-4 flex flex-wrap items-center justify-between gap-3 shadow-lg">
        <div>
          <div className="flex items-center gap-2 text-xs font-mono text-cyan-400">
            <Sliders className="w-4 h-4" />
            <span>STEP 2 OF 3 — CALIBRATION, RECONSTRUCTION OPTIONS &amp; LANGGRAPH PIPELINE</span>
          </div>
          <h1 className="text-lg font-bold text-white mt-0.5">{projectName}</h1>
          <p className="text-xs text-slate-400">
            Verify foreground isolation across {capturedCount}/6 captured perspectives, set 1:1 mm scale, and launch 3D B-Rep synthesis.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={onBackToCapture}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-cad-dark border border-cad-border hover:border-slate-500 text-xs font-mono text-slate-200 transition"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Back to Capture Studio</span>
          </button>

          {generation && (
            <button
              onClick={onGoToViewer}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-950 border border-emerald-600/80 hover:bg-emerald-900 text-xs font-mono font-semibold text-emerald-300 transition"
            >
              <span>Open Fullscreen 3D Output</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Left: Captured Views + Masked Silhouettes + Calibration (7 cols) */}
        <div className="lg:col-span-7 space-y-5">
          {/* 6-View Verification Grid */}
          <div className="bg-cad-card border border-cad-border rounded-xl p-4 space-y-3 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-cad-border pb-2.5">
              <span className="text-sm font-semibold text-white flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-400" />
                <span>Captured Perspectives ({capturedCount}/6 Ready)</span>
              </span>
              <button
                onClick={() => setShowMasked(!showMasked)}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded border text-[11px] font-mono transition ${
                  showMasked
                    ? 'bg-emerald-950/70 text-emerald-300 border-emerald-700'
                    : 'bg-cad-dark text-slate-300 border-cad-border'
                }`}
              >
                <Eye className="w-3.5 h-3.5" />
                <span>{showMasked ? 'Showing Masked Silhouettes (if fused)' : 'Showing Raw Photos'}</span>
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {AXIS_LABELS.map(({ key, label }) => {
                const cap = captures[key];
                const vd = viewsData[key];
                const rawUrl = cap?.dataUrl || vd?.image_url;
                const maskUrl = vd?.masked_url;
                const displayUrl = showMasked && maskUrl ? maskUrl : rawUrl;
                const blur = cap?.blurScore ?? vd?.blur_score;

                return (
                  <div
                    key={key}
                    className={`rounded-lg border overflow-hidden ${
                      displayUrl ? 'border-cyan-500/40 bg-cad-dark' : 'border-dashed border-cad-border bg-cad-dark/40'
                    }`}
                  >
                    <div className="px-2 py-1 bg-[#121822] border-b border-cad-border flex items-center justify-between text-[10px] font-mono">
                      <span className="font-semibold text-slate-200">{label}</span>
                      {maskUrl ? (
                        <span className="text-emerald-400">MASKED</span>
                      ) : rawUrl ? (
                        <span className="text-cyan-400">PNG OK</span>
                      ) : (
                        <span className="text-slate-500">SKIPPED</span>
                      )}
                    </div>
                    <div className="h-28 bg-[#070a10] flex items-center justify-center relative">
                      {displayUrl ? (
                        <>
                          <img src={displayUrl} alt={label} className="w-full h-full object-contain p-1" />
                          {blur !== undefined && (
                            <span className="absolute bottom-1 right-1 bg-black/80 px-1.5 py-0.5 rounded text-[9px] font-mono text-emerald-300">
                              Score {blur.toFixed(0)}
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="text-[10px] font-mono text-slate-500 px-2 text-center">
                          Auto-inferred from opposite/plan views
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 1-Step Metric Calibration Panel */}
          <div className="bg-cad-card border border-cad-border rounded-xl p-4 space-y-3 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                  <Ruler className="w-4 h-4 text-cyan-400" />
                  <span>1-Step Metric Calibration (1:1 mm)</span>
                </h2>
                <p className="text-xs text-slate-400">
                  Anchor real-world dimensions using a known span in millimeters or open the 2-point caliper overlay.
                </p>
              </div>
              <button
                onClick={() => setShowCalibrator(true)}
                disabled={!primaryCalibImage}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-950/70 hover:bg-cyan-900 border border-cyan-700 text-xs font-mono text-cyan-300 disabled:opacity-40 transition"
              >
                <Ruler className="w-3.5 h-3.5" />
                <span>2-Point Caliper Tool</span>
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end bg-cad-dark/70 p-3 rounded-lg border border-cad-border">
              <div>
                <label className="text-[10px] font-mono text-slate-400 block mb-1">Reference View</label>
                <select
                  value={refSide}
                  onChange={(e) => setRefSide(e.target.value as AxisView)}
                  className="w-full bg-cad-card border border-cad-border rounded px-2.5 py-1.5 text-xs font-mono text-white"
                >
                  {AXIS_LABELS.filter((a) => captures[a.key] || viewsData[a.key]?.image_url).map((a) => (
                    <option key={a.key} value={a.key}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-[10px] font-mono text-slate-400 block mb-1">Known Object Span (mm)</label>
                <input
                  type="number"
                  step="0.5"
                  min="5"
                  max="5000"
                  value={knownLengthInput}
                  onChange={(e) => setKnownLengthInput(e.target.value)}
                  className="w-full bg-cad-card border border-cad-border rounded px-2.5 py-1.5 text-xs font-mono text-white"
                />
              </div>

              <button
                onClick={handleQuickCalibSave}
                className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-cyan-600/60 text-xs font-mono text-cyan-300 font-semibold transition"
              >
                {calibrationSpec ? '✓ Scale Locked (Update)' : 'Lock Metric Scale'}
              </button>
            </div>
          </div>
        </div>

        {/* Right: CAD Generation Options + Progress Loop + Live Log Stream (5 cols) */}
        <div className="lg:col-span-5 space-y-5">
          {/* Generation Options */}
          <div className="bg-cad-card border border-cad-border rounded-xl p-4 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-cad-border pb-2.5">
              <span className="text-sm font-semibold text-white flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-cyan-400" />
                <span>CAD Synthesis Options</span>
              </span>
              <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950/70 px-2 py-0.5 rounded border border-cyan-800">
                ISO 10303-21 / DXF / STL
              </span>
            </div>

            <div className="space-y-3 text-xs font-mono">
              <div>
                <label className="text-[10px] text-slate-400 block mb-1">Geometry Reconstruction Kernel</label>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: 'auto_hull', label: '3D Visual Hull', sub: 'Curved / organic / complex' },
                    { id: 'prismatic', label: 'Prismatic B-Rep', sub: 'Boxes, plates & bores' },
                  ].map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      onClick={() =>
                        onChangeOptions({ ...options, reconstructionMode: mode.id as GenerationOptions['reconstructionMode'] })
                      }
                      className={`text-left p-2.5 rounded-lg border transition ${
                        options.reconstructionMode === mode.id
                          ? 'bg-cyan-950/60 border-cyan-500 text-cyan-200'
                          : 'bg-cad-dark border-cad-border text-slate-400 hover:border-slate-600'
                      }`}
                    >
                      <div className="font-semibold text-[11px]">{mode.label}</div>
                      <div className="text-[10px] opacity-75">{mode.sub}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-[10px] text-slate-400 block mb-1">Edge Finishing &amp; Detail</label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { id: 'clean', label: 'Natural Profile' },
                    { id: 'chamfer', label: 'Chamfer Bevel' },
                    { id: 'fillet', label: 'Corner Fillet' },
                  ].map((edge) => (
                    <button
                      key={edge.id}
                      type="button"
                      onClick={() =>
                        onChangeOptions({ ...options, edgeFinish: edge.id as GenerationOptions['edgeFinish'] })
                      }
                      className={`py-2 px-2 rounded-lg border text-[11px] transition ${
                        options.edgeFinish === edge.id
                          ? 'bg-cyan-950/60 border-cyan-500 text-cyan-200 font-semibold'
                          : 'bg-cad-dark border-cad-border text-slate-400 hover:border-slate-600'
                      }`}
                    >
                      {edge.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Active AI & CAD Engine Diagnostics + Strict Cloud Toggle */}
              <div className="p-2.5 rounded-lg bg-cad-dark/90 border border-cad-border space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] text-slate-400 uppercase font-semibold">Active Model Cycle</span>
                  <label className="flex items-center gap-1.5 cursor-pointer text-[10px]">
                    <input
                      type="checkbox"
                      checked={options.strictCloud}
                      onChange={(e) => onChangeOptions({ ...options, strictCloud: e.target.checked })}
                      className="rounded border-slate-700 text-cyan-500"
                    />
                    <span className={options.strictCloud ? 'text-cyan-300 font-semibold' : 'text-slate-400'}>
                      Strict Cloud Mode (No Fallback)
                    </span>
                  </label>
                </div>
                {activeEngines && (
                  <div className="grid grid-cols-2 gap-1.5 text-[10px]">
                    <div className={`px-2 py-1 rounded border ${activeEngines.cloud_gpu_ready === 'true' ? 'bg-emerald-950/40 border-emerald-700/60 text-emerald-300' : 'bg-amber-950/30 border-amber-700/50 text-amber-200'}`}>
                      Seg: {activeEngines.segmentation}
                    </div>
                    <div className={`px-2 py-1 rounded border ${activeEngines.cloud_gpu_ready === 'true' ? 'bg-emerald-950/40 border-emerald-700/60 text-emerald-300' : 'bg-amber-950/30 border-amber-700/50 text-amber-200'}`}>
                      3D: {activeEngines.depth_fusion}
                    </div>
                    <div className={`px-2 py-1 rounded border ${activeEngines.multimodal_llm_ready === 'true' ? 'bg-emerald-950/40 border-emerald-700/60 text-emerald-300' : 'bg-amber-950/30 border-amber-700/50 text-amber-200'}`}>
                      VLM: {activeEngines.llm_vlm}
                    </div>
                    <div className={`px-2 py-1 rounded border ${activeEngines.cloud_gpu_ready === 'true' ? 'bg-emerald-950/40 border-emerald-700/60 text-emerald-300' : 'bg-amber-950/30 border-amber-700/50 text-amber-200'}`}>
                      CAD: {activeEngines.cad_kernel}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {errorMsg && (
              <div className="p-2.5 rounded-lg bg-rose-950/60 border border-rose-700/70 text-xs font-mono text-rose-200 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{errorMsg}</span>
              </div>
            )}

            <button
              onClick={onRunPipeline}
              disabled={isRunning || capturedCount < 4}
              className="w-full py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 disabled:opacity-45 text-white font-mono text-xs font-bold tracking-wider flex items-center justify-center gap-2 shadow-lg shadow-cyan-500/20 transition"
            >
              {isRunning ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>RUNNING 3D FUSION &amp; SYNTHESIS ({progressPct}%)...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  <span>{generation ? 'RE-RUN FUSION & GENERATE CAD' : 'FUSE 3D & GENERATE PARAMETRIC CAD'}</span>
                </>
              )}
            </button>

            {/* Progress Bar Loop Indicator */}
            <div className="space-y-1.5 pt-1">
              <div className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-slate-300">{progressStage}</span>
                <span className="text-cyan-400 font-bold">{progressPct}%</span>
              </div>
              <div className="w-full h-2.5 bg-cad-dark rounded-full overflow-hidden border border-cad-border">
                <div
                  className={`h-full transition-all duration-300 ${
                    progressPct >= 100
                      ? 'bg-emerald-500'
                      : 'bg-gradient-to-r from-cyan-500 via-blue-500 to-emerald-400'
                  }`}
                  style={{ width: `${Math.min(100, Math.max(0, progressPct))}%` }}
                />
              </div>
              {geometryReport && (
                <div className="flex items-center gap-2 text-[10px] font-mono text-emerald-300 pt-1">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>
                    Envelope: {geometryReport.bounding_box_mm.join(' × ')} mm • {geometryReport.point_count.toLocaleString()} pts
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Live LangGraph Stream */}
          <div className="h-[310px] w-full">
            <AgentTerminal
              logs={agentLogs}
              status={generation?.status || (isRunning ? 'generating' : 'idle')}
              activeNode={activeNode}
              validationMetrics={validationMetrics}
            />
          </div>
        </div>
      </div>

      {showCalibrator && primaryCalibImage && (
        <ScaleCalibrator
          primaryViewUrl={primaryCalibImage}
          referenceSide={refSide}
          initialKnownLengthMm={parseFloat(knownLengthInput) || 180}
          onSaveCalibration={(spec) => {
            setKnownLengthInput(String(spec.known_length_mm));
            onSaveCalibration(spec);
            setShowCalibrator(false);
          }}
          onCancel={() => setShowCalibrator(false)}
        />
      )}
    </div>
  );
};
