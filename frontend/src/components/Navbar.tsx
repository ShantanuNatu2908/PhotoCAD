import React from 'react';
import { Box, Cpu } from 'lucide-react';

interface NavbarProps {
  unit: string;
  setUnit: (u: string) => void;
  systemStatus: string;
}

export const Navbar: React.FC<NavbarProps> = ({ unit, setUnit, systemStatus }) => {
  return (
    <header className="border-b border-cad-border bg-cad-card/80 backdrop-blur px-6 py-3.5 flex items-center justify-between sticky top-0 z-50">
      <div className="flex items-center space-x-3">
        <div className="h-10 w-10 rounded-lg bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
          <Box className="w-6 h-6 text-white" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <span className="font-bold text-lg tracking-wider text-white">PhotoCAD</span>
            <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800">
              B-Rep v1.0
            </span>
          </div>
          <p className="text-xs text-slate-400 hidden sm:block">
            6-Axis Photometric Reverse-Engineering to Parametric CAD
          </p>
        </div>
      </div>

      <div className="flex items-center space-x-4">
        {/* Metric / Imperial Unit Selector */}
        <div className="flex items-center bg-cad-dark border border-cad-border rounded-lg p-0.5 text-xs font-mono">
          <button
            onClick={() => setUnit('mm')}
            className={`px-3 py-1 rounded transition ${
              unit === 'mm' ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40' : 'text-slate-400 hover:text-white'
            }`}
          >
            MM
          </button>
          <button
            onClick={() => setUnit('inch')}
            className={`px-3 py-1 rounded transition ${
              unit === 'inch' ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40' : 'text-slate-400 hover:text-white'
            }`}
          >
            INCH
          </button>
        </div>

        {/* Engine Kernel Status */}
        <div className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-cad-dark border border-cad-border text-xs font-mono">
          <Cpu className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
          <span className="text-slate-300">OpenCascade Kernel:</span>
          <span className="text-emerald-400 font-semibold">{systemStatus}</span>
        </div>
      </div>
    </header>
  );
};
