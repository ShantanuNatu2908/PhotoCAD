import React, { useState, useEffect } from 'react';
import { Download, Check, Copy, Box, Layers, Scissors, ShieldCheck, Loader2, AlertCircle } from 'lucide-react';
import type { CadGeneration } from '../types/cad';
import { downloadCadArtifact } from '../utils/cadExport';
import type { CadExportFormat } from '../utils/cadExport';

interface ExportModalProps {
  generation: CadGeneration;
  onClose: () => void;
}

interface InteropReportData {
  autocad_compatible: boolean;
  fusion360_compatible: boolean;
  solidworks_compatible: boolean;
  step: {
    valid: boolean;
    schema_protocol: string;
    units_millimeters: boolean;
    entity_count: number;
    dangling_references: number[];
    bounding_box_mm: [number, number, number];
  };
  dxf: {
    valid: boolean;
    insunits_mm: boolean;
    line_count: number;
    circle_count: number;
  };
  stl: {
    valid: boolean;
    is_watertight: boolean;
    volume_mm3: number;
  };
}

export const ExportModal: React.FC<ExportModalProps> = ({ generation, onClose }) => {
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<'download' | 'code'>('download');
  const [interop, setInterop] = useState<InteropReportData | null>(null);
  const [downloadingFormat, setDownloadingFormat] = useState<CadExportFormat | null>(null);
  const [downloadedFormat, setDownloadedFormat] = useState<CadExportFormat | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    if (!generation.id || generation.id.startsWith('demo-')) return;
    fetch(`http://localhost:8000/api/export/${generation.id}/interop-report`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) setInterop(data as InteropReportData);
      })
      .catch(() => {});
  }, [generation.id]);

  const handleCopyCode = () => {
    if (generation.code) {
      navigator.clipboard.writeText(generation.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleDownload = async (format: CadExportFormat) => {
    setExportError(null);
    setDownloadingFormat(format);
    try {
      await downloadCadArtifact(generation, format);
      setDownloadedFormat(format);
      setTimeout(() => setDownloadedFormat((prev) => (prev === format ? null : prev)), 2500);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : `Failed to export .${format}`);
    } finally {
      setDownloadingFormat(null);
    }
  };

  const EXPORT_CARDS: Array<{
    format: CadExportFormat;
    badge: string;
    title: string;
    subtitle: string;
    borderClass: string;
    textClass: string;
    icon: React.ReactNode;
  }> = [
    {
      format: 'step',
      badge: '.STEP / .STP',
      title: 'ISO 10303-21 AP214 B-Rep Solid.',
      subtitle: 'AutoCAD, SolidWorks, Fusion 360, FreeCAD',
      borderClass: 'border-cyan-500/30 bg-cyan-950/20 hover:bg-cyan-900/30',
      textClass: 'text-cyan-400',
      icon: <Box className="w-4 h-4 text-cyan-400" />,
    },
    {
      format: 'dxf',
      badge: '.DXF',
      title: 'AutoCAD 2D CAD Blueprint.',
      subtitle: 'AutoCAD ($INSUNITS=4 mm) & CNC',
      borderClass: 'border-purple-500/30 bg-purple-950/20 hover:bg-purple-900/30',
      textClass: 'text-purple-400',
      icon: <Layers className="w-4 h-4 text-purple-400" />,
    },
    {
      format: 'stl',
      badge: '.STL',
      title: 'Watertight 2-Manifold Mesh.',
      subtitle: 'Cura, PrusaSlicer, Bambu Studio',
      borderClass: 'border-amber-500/30 bg-amber-950/20 hover:bg-amber-900/30',
      textClass: 'text-amber-400',
      icon: <Scissors className="w-4 h-4 text-amber-400" />,
    },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-cad-card border border-cad-border rounded-xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col max-h-[85vh]">
        {/* Modal Header */}
        <div className="bg-cad-dark px-6 py-4 border-b border-cad-border flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Box className="w-5 h-5 text-cyan-400" />
            <h3 className="font-semibold text-white">CAD Engineering Export Center</h3>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-sm font-mono px-2 py-1 rounded hover:bg-slate-800 transition"
          >
            ✕
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="flex border-b border-cad-border bg-cad-dark/50 px-6 pt-2">
          <button
            onClick={() => setActiveTab('download')}
            className={`pb-2.5 px-4 text-xs font-mono font-medium border-b-2 transition ${
              activeTab === 'download'
                ? 'border-cyan-400 text-cyan-400'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            Standard CAD Packages
          </button>
          <button
            onClick={() => setActiveTab('code')}
            className={`pb-2.5 px-4 text-xs font-mono font-medium border-b-2 transition ${
              activeTab === 'code'
                ? 'border-cyan-400 text-cyan-400'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            Parametric build123d Script (.py)
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto flex-1">
          {activeTab === 'download' ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-slate-400 leading-relaxed">
                  Export Rev v{generation.version} (
                  {generation.dimensions_mm
                    ? `${generation.dimensions_mm.x}×${generation.dimensions_mm.y}×${generation.dimensions_mm.z} mm`
                    : '1:1 mm'}
                  ) directly for AutoCAD, Fusion 360, or slicing:
                </p>
                {generation.id.startsWith('demo-') && (
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/70">
                    Parametric Quick-Export Ready
                  </span>
                )}
              </div>

              {exportError && (
                <div className="p-2.5 rounded-lg bg-red-950/50 border border-red-700/60 text-xs font-mono text-red-300 flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{exportError}</span>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
                {EXPORT_CARDS.map((card) => {
                  const isBusy = downloadingFormat === card.format;
                  const isDone = downloadedFormat === card.format;
                  return (
                    <button
                      key={card.format}
                      type="button"
                      disabled={Boolean(downloadingFormat)}
                      onClick={() => handleDownload(card.format)}
                      className={`text-left p-4 rounded-xl border ${card.borderClass} transition flex flex-col justify-between group disabled:opacity-60`}
                    >
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className={`text-xs font-mono font-bold ${card.textClass}`}>{card.badge}</span>
                          {card.icon}
                        </div>
                        <p className="text-[11px] text-slate-300">{card.title}</p>
                        <p className="text-[10px] text-slate-500 mt-1">{card.subtitle}</p>
                      </div>
                      <div className={`mt-4 flex items-center space-x-1.5 text-xs ${card.textClass} font-mono font-medium`}>
                        {isBusy ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : isDone ? (
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                        ) : (
                          <Download className="w-3.5 h-3.5" />
                        )}
                        <span>{isBusy ? 'Preparing...' : isDone ? 'Downloaded!' : `Download .${card.format}`}</span>
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Interoperability Checklist */}
              {interop && (
                <div className="mt-4 p-3.5 rounded-xl bg-emerald-950/25 border border-emerald-700/60 text-xs font-mono space-y-2">
                  <div className="flex items-center justify-between text-emerald-300 font-semibold">
                    <span className="flex items-center gap-1.5">
                      <ShieldCheck className="w-4 h-4 text-emerald-400" />
                      Ecosystem Interoperability Verified (1:1 mm)
                    </span>
                    <span className="text-[10px] text-emerald-400">
                      {interop.step.entity_count} STEP entities • {interop.stl.volume_mm3.toLocaleString()} mm³
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[11px]">
                    <div className="px-2 py-1 rounded bg-black/40 border border-emerald-800/60 text-emerald-300">
                      {interop.autocad_compatible ? '✓ AutoCAD Ready' : '✗ AutoCAD Issue'}
                    </div>
                    <div className="px-2 py-1 rounded bg-black/40 border border-emerald-800/60 text-emerald-300">
                      {interop.fusion360_compatible ? '✓ Fusion 360 Ready' : '✗ Fusion Issue'}
                    </div>
                    <div className="px-2 py-1 rounded bg-black/40 border border-emerald-800/60 text-emerald-300">
                      {interop.solidworks_compatible ? '✓ SolidWorks Ready' : '✗ SW Issue'}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono text-slate-400">build123d B-Rep Python Source (1:1 mm)</span>
                <div className="flex items-center space-x-2">
                  <button
                    type="button"
                    onClick={() => handleDownload('py')}
                    className="flex items-center space-x-1 px-2.5 py-1 rounded bg-cyan-950 hover:bg-cyan-900 border border-cyan-700 text-xs text-cyan-300 transition"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>{downloadedFormat === 'py' ? 'Saved .py' : 'Download .py'}</span>
                  </button>
                  <button
                    onClick={handleCopyCode}
                    className="flex items-center space-x-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 transition"
                  >
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copied ? 'Copied!' : 'Copy Code'}</span>
                  </button>
                </div>
              </div>
              <pre className="p-4 rounded-lg bg-black border border-cad-border text-xs text-emerald-300 font-mono overflow-x-auto max-h-80 whitespace-pre">
                {generation.code || '# No code generated yet'}
              </pre>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="bg-cad-dark px-6 py-3 border-t border-cad-border flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-mono text-white transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
