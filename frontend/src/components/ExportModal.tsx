import React, { useState } from 'react';
import { Download, Check, Copy, Box, Layers, Scissors } from 'lucide-react';
import type { CadGeneration } from '../types/cad';

interface ExportModalProps {
  generation: CadGeneration;
  onClose: () => void;
}

export const ExportModal: React.FC<ExportModalProps> = ({ generation, onClose }) => {
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<'download' | 'code'>('download');

  const handleCopyCode = () => {
    if (generation.code) {
      navigator.clipboard.writeText(generation.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const getDownloadUrl = (format: string) => {
    return `http://localhost:8000/api/export/${generation.id}/${format}`;
  };

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
              <p className="text-xs text-slate-400 leading-relaxed">
                Your 3D model has been processed into native solid geometry with valid B-Rep boundary curves. Select your target engineering ecosystem:
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
                {/* STEP Export */}
                <a
                  href={getDownloadUrl('step')}
                  target="_blank"
                  rel="noreferrer"
                  className="p-4 rounded-xl border border-cyan-500/30 bg-cyan-950/20 hover:bg-cyan-900/30 transition flex flex-col justify-between group"
                >
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-mono font-bold text-cyan-400">.STEP / .STP</span>
                      <Box className="w-4 h-4 text-cyan-400" />
                    </div>
                    <p className="text-[11px] text-slate-300">
                      Standard Parametric B-Rep Solid.
                    </p>
                    <p className="text-[10px] text-slate-500 mt-1">
                      AutoCAD, SolidWorks, Fusion 360, FreeCAD
                    </p>
                  </div>
                  <div className="mt-4 flex items-center space-x-1.5 text-xs text-cyan-300 font-mono font-medium">
                    <Download className="w-3.5 h-3.5" />
                    <span>Download</span>
                  </div>
                </a>

                {/* DXF Export */}
                <a
                  href={getDownloadUrl('dxf')}
                  target="_blank"
                  rel="noreferrer"
                  className="p-4 rounded-xl border border-purple-500/30 bg-purple-950/20 hover:bg-purple-900/30 transition flex flex-col justify-between group"
                >
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-mono font-bold text-purple-400">.DXF</span>
                      <Layers className="w-4 h-4 text-purple-400" />
                    </div>
                    <p className="text-[11px] text-slate-300">
                      2D Engineering Blueprint Vector.
                    </p>
                    <p className="text-[10px] text-slate-500 mt-1">
                      AutoCAD Technical Shop Drawings & CNC
                    </p>
                  </div>
                  <div className="mt-4 flex items-center space-x-1.5 text-xs text-purple-300 font-mono font-medium">
                    <Download className="w-3.5 h-3.5" />
                    <span>Download</span>
                  </div>
                </a>

                {/* STL Export */}
                <a
                  href={getDownloadUrl('stl')}
                  target="_blank"
                  rel="noreferrer"
                  className="p-4 rounded-xl border border-amber-500/30 bg-amber-950/20 hover:bg-amber-900/30 transition flex flex-col justify-between group"
                >
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-mono font-bold text-amber-400">.STL</span>
                      <Scissors className="w-4 h-4 text-amber-400" />
                    </div>
                    <p className="text-[11px] text-slate-300">
                      3D Printing Slicer Mesh.
                    </p>
                    <p className="text-[10px] text-slate-500 mt-1">
                      Cura, PrusaSlicer, Bambu Studio
                    </p>
                  </div>
                  <div className="mt-4 flex items-center space-x-1.5 text-xs text-amber-300 font-mono font-medium">
                    <Download className="w-3.5 h-3.5" />
                    <span>Download</span>
                  </div>
                </a>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono text-slate-400">build123d B-Rep Python Source (1:1 mm)</span>
                <div className="flex items-center space-x-2">
                  <a
                    href={getDownloadUrl('py')}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center space-x-1 px-2.5 py-1 rounded bg-cyan-950 hover:bg-cyan-900 border border-cyan-700 text-xs text-cyan-300 transition"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download .py</span>
                  </a>
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
