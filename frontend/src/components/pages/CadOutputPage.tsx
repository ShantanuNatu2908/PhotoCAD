import React, { useState } from 'react';
import {
  Download,
  Wand2,
  Terminal,
  Code2,
  Sliders,
  Camera,
  CheckCircle2,
  ShieldCheck,
  X,
} from 'lucide-react';
import { CadViewport3D } from '../CadViewport3D';
import { AgentTerminal } from '../AgentTerminal';
import { resolveBackendAssetUrl } from '../../services/scanApi';
import type {
  ActivePipelineEngines,
  AgentLog,
  CadGeneration,
  Open3DGeometryReport,
  ValidationMetrics,
} from '../../types/cad';

interface CadOutputPageProps {
  projectName: string;
  generation: CadGeneration | null;
  geometryReport: Open3DGeometryReport | null;
  plyUrl?: string;
  unit: string;
  activeEngines?: ActivePipelineEngines | null;
  agentLogs: AgentLog[];
  activeNode: string | null;
  validationMetrics: ValidationMetrics | null;
  refinePrompt: string;
  setRefinePrompt: (val: string) => void;
  isRefining: boolean;
  onSubmitRefine: (e: React.FormEvent) => void;
  onQuickRefine: (instruction: string) => void;
  onOpenExport: () => void;
  onRescan: () => void;
  onBackToGenerate: () => void;
}

export const CadOutputPage: React.FC<CadOutputPageProps> = ({
  projectName,
  generation,
  geometryReport,
  plyUrl,
  unit,
  activeEngines,
  agentLogs,
  activeNode,
  validationMetrics,
  refinePrompt,
  setRefinePrompt,
  isRefining,
  onSubmitRefine,
  onQuickRefine,
  onOpenExport,
  onRescan,
  onBackToGenerate,
}) => {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTab, setDrawerTab] = useState<'stream' | 'code'>('stream');

  const stlResolved = resolveBackendAssetUrl(generation?.stl_file);

  return (
    <div className="flex flex-col h-[calc(100vh-66px)] min-h-[620px] bg-[#070a10] relative">
      {/* Top Floating Output & Precision Summary Ribbon */}
      <div className="border-b border-cad-border bg-cad-card/95 px-4 lg:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3 z-20">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-700">
                STEP 3 — FULLSCREEN B-REP OUTPUT
              </span>
              <span className="text-sm font-bold text-white">{projectName}</span>
              {generation && (
                <span className="text-xs font-mono text-cyan-400">Rev v{generation.version}</span>
              )}
            </div>
          </div>

          {/* Precision Output Status Chips */}
          {validationMetrics && (
            <div className="hidden md:flex items-center gap-2 text-[11px] font-mono">
              <span className="px-2 py-0.5 rounded bg-cad-dark border border-cad-border text-emerald-300 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" />
                {validationMetrics.is_watertight ? 'Watertight 2-Manifold' : 'Open Mesh'}
              </span>
              <span className="px-2 py-0.5 rounded bg-cad-dark border border-cad-border text-cyan-300 flex items-center gap-1">
                <ShieldCheck className="w-3 h-3" />
                Chamfer {validationMetrics.chamfer_mean_mm.toFixed(2)} mm
              </span>
              <span className="px-2 py-0.5 rounded bg-cad-dark border border-cad-border text-slate-300">
                Vol {(validationMetrics.volume_mm3 / 1000).toFixed(1)} cm³
              </span>
            </div>
          )}
          {activeEngines && (
            <span className={`hidden xl:inline-block px-2 py-0.5 rounded border text-[10px] font-mono ${activeEngines.cloud_gpu_ready === 'true' ? 'bg-emerald-950/60 border-emerald-700 text-emerald-300' : 'bg-amber-950/50 border-amber-700/70 text-amber-200'}`}>
              {activeEngines.segmentation} • {activeEngines.cad_kernel}
            </span>
          )}
        </div>

        {/* Navigation, Stream Drawer & Export Actions */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={onRescan}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cad-dark border border-cad-border hover:border-slate-500 text-xs font-mono text-slate-300 transition"
          >
            <Camera className="w-3.5 h-3.5" />
            <span>Rescan Sides</span>
          </button>
          <button
            onClick={onBackToGenerate}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cad-dark border border-cad-border hover:border-cyan-500/60 text-xs font-mono text-slate-200 transition"
          >
            <Sliders className="w-3.5 h-3.5 text-cyan-400" />
            <span>Options &amp; Calibrate</span>
          </button>
          <button
            onClick={() => setDrawerOpen(!drawerOpen)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-mono transition ${
              drawerOpen
                ? 'bg-cyan-950 text-cyan-300 border-cyan-600'
                : 'bg-cad-dark text-slate-200 border-cad-border hover:border-cyan-500'
            }`}
          >
            <Terminal className="w-3.5 h-3.5 text-cyan-400" />
            <span>Execution Summary &amp; Code</span>
          </button>
          <button
            onClick={onOpenExport}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white font-mono text-xs font-bold shadow-lg transition"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export AutoCAD / STEP / DXF</span>
          </button>
        </div>
      </div>

      {/* Main Fullscreen 3D Viewport Area + Slide-Over Stream Drawer */}
      <div className="flex-1 relative overflow-hidden p-3">
        <div className="w-full h-full">
          <CadViewport3D
            stlUrl={stlResolved}
            plyUrl={plyUrl}
            geometryReport={geometryReport}
            dimensions={generation?.dimensions_mm}
            unit={unit}
            onExportClick={onOpenExport}
          />
        </div>

        {/* Toggleable Side Drawer: Live Execution Summary / Generated build123d Script */}
        {drawerOpen && (
          <div className="absolute top-5 right-5 bottom-5 w-full max-w-[460px] bg-cad-card/95 backdrop-blur-md border border-cad-border rounded-xl shadow-2xl z-30 flex flex-col overflow-hidden">
            <div className="px-4 py-2.5 bg-cad-dark border-b border-cad-border flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-mono">
                <button
                  onClick={() => setDrawerTab('stream')}
                  className={`px-2.5 py-1 rounded transition ${
                    drawerTab === 'stream' ? 'bg-cyan-500/20 text-cyan-300 font-semibold' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  LangGraph Stream ({agentLogs.length})
                </button>
                <button
                  onClick={() => setDrawerTab('code')}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded transition ${
                    drawerTab === 'code' ? 'bg-cyan-500/20 text-cyan-300 font-semibold' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <Code2 className="w-3.5 h-3.5" />
                  <span>build123d .py</span>
                </button>
              </div>
              <button
                onClick={() => setDrawerOpen(false)}
                className="text-slate-400 hover:text-white p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-hidden p-3">
              {drawerTab === 'stream' ? (
                <AgentTerminal
                  logs={agentLogs}
                  status={generation?.status || 'idle'}
                  activeNode={activeNode}
                  validationMetrics={validationMetrics}
                />
              ) : (
                <pre className="h-full overflow-auto p-3 rounded-lg bg-black border border-cad-border text-[11px] font-mono text-emerald-300 whitespace-pre">
                  {generation?.code || '# Run synthesis on Page 2 to inspect build123d code'}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Bottom Docked Parametric /refine Bar */}
      <form
        onSubmit={onSubmitRefine}
        className="border-t border-cad-border bg-cad-card/95 px-4 lg:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3 z-20"
      >
        <div className="flex items-center gap-2 flex-1 min-w-[260px] bg-cad-dark border border-cyan-800/70 rounded-lg px-3 py-1.5">
          <Wand2 className="w-4 h-4 text-cyan-400 shrink-0" />
          <input
            type="text"
            value={refinePrompt}
            onChange={(e) => setRefinePrompt(e.target.value)}
            placeholder='Parametric /refine edit (e.g. "120x60x35", "Change hole to 14 mm", "Add 2 mm chamfer")'
            className="flex-1 bg-transparent text-xs font-mono text-white placeholder-slate-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={isRefining || !refinePrompt.trim()}
            className="px-3 py-1 rounded bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 text-white font-mono text-xs font-semibold transition"
          >
            {isRefining ? 'Refining...' : 'Apply /refine'}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-mono text-slate-400">Quick edits:</span>
          {[
            { label: 'Hole 14mm', instr: 'Change hole diameter to 14 mm' },
            { label: '100×60×25 mm', instr: '100x60x25' },
            { label: 'Chamfer 2mm', instr: 'Add 2 mm chamfer' },
            { label: 'Remove Hole', instr: 'Remove center hole' },
          ].map((preset) => (
            <button
              key={preset.label}
              type="button"
              disabled={isRefining}
              onClick={() => onQuickRefine(preset.instr)}
              className="px-2.5 py-1 rounded bg-cad-dark hover:bg-cyan-950 border border-cad-border hover:border-cyan-700 text-[11px] font-mono text-slate-300 hover:text-cyan-300 transition disabled:opacity-40"
            >
              {preset.label}
            </button>
          ))}
        </div>
      </form>
    </div>
  );
};
