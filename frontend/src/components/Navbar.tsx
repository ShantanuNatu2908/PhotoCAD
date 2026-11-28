import React, { useState, useEffect } from 'react';
import { Box, Cpu, Cloud, CheckCircle2, AlertCircle, Camera, Sliders, Maximize2, FolderKanban } from 'lucide-react';
import type { AppPage } from '../types/cad';

interface NavbarProps {
  unit: string;
  setUnit: (u: string) => void;
  systemStatus: string;
  activePage: AppPage;
  onNavigate: (page: AppPage) => void;
  capturedCount: number;
  hasGeneration: boolean;
}

interface CloudTierInfo {
  tier: string;
  status: string;
  engine?: string;
  provider?: string;
  target_gpu?: string;
  note?: string;
  message?: string;
}

interface CloudHealthData {
  status: string;
  architecture: string;
  cloud_tiers: Record<string, CloudTierInfo>;
}

export const Navbar: React.FC<NavbarProps> = ({
  unit,
  setUnit,
  systemStatus,
  activePage,
  onNavigate,
  capturedCount,
  hasGeneration,
}) => {
  const [cloudHealth, setCloudHealth] = useState<CloudHealthData | null>(null);
  const [showCloudMenu, setShowCloudMenu] = useState(false);

  const fetchCloudDiagnostics = () => {
    fetch('http://localhost:8000/api/health/cloud')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) setCloudHealth(data as CloudHealthData);
      })
      .catch(() => {});
  };

  useEffect(() => {
    fetchCloudDiagnostics();
  }, []);

  const navItems: Array<{ id: AppPage; label: string; icon: React.ReactNode; badge?: string }> = [
    {
      id: 'capture',
      label: '1. Capture Studio',
      icon: <Camera className="w-3.5 h-3.5" />,
      badge: capturedCount > 0 ? `${capturedCount}/6` : undefined,
    },
    {
      id: 'generate',
      label: '2. Calibrate & Generate',
      icon: <Sliders className="w-3.5 h-3.5" />,
    },
    {
      id: 'viewer',
      label: '3. 3D CAD Output',
      icon: <Maximize2 className="w-3.5 h-3.5" />,
      badge: hasGeneration ? 'Ready' : undefined,
    },
    {
      id: 'projects',
      label: 'Saved Projects',
      icon: <FolderKanban className="w-3.5 h-3.5" />,
    },
  ];

  return (
    <header className="border-b border-cad-border bg-cad-card/90 backdrop-blur px-4 lg:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3 sticky top-0 z-50">
      <div className="flex items-center space-x-3">
        <button
          onClick={() => onNavigate('capture')}
          className="h-9 w-9 rounded-lg bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20"
        >
          <Box className="w-5 h-5 text-white" />
        </button>
        <div>
          <div className="flex items-center space-x-2">
            <span className="font-bold text-base tracking-wider text-white">PhotoCAD</span>
            <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800">
              B-Rep v1.0
            </span>
          </div>
          <p className="text-[11px] text-slate-400 hidden xl:block">
            6-Axis Photometric Reverse-Engineering Studio
          </p>
        </div>
      </div>

      {/* Multi-Page Workflow Stepper */}
      <nav className="flex flex-wrap items-center gap-1 bg-cad-dark/80 border border-cad-border p-1 rounded-xl">
        {navItems.map((item) => {
          const active = activePage === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-mono text-xs transition ${
                active
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 font-semibold shadow-sm'
                  : 'text-slate-400 hover:text-white border border-transparent hover:bg-slate-800/70'
              }`}
            >
              {item.icon}
              <span>{item.label}</span>
              {item.badge && (
                <span className="text-[10px] px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/80">
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="flex items-center space-x-3">
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

        {/* Cloud Tiers Diagnostics Button */}
        <div className="relative">
          <button
            onClick={() => {
              if (!showCloudMenu) fetchCloudDiagnostics();
              setShowCloudMenu(!showCloudMenu);
            }}
            className="hidden md:flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-cad-dark border border-cad-border hover:border-cyan-500/50 text-xs font-mono transition"
          >
            <Cloud className={`w-3.5 h-3.5 ${cloudHealth?.status === 'healthy' ? 'text-emerald-400' : cloudHealth?.status === 'partial' ? 'text-amber-300' : 'text-slate-400'}`} />
            <span className="text-slate-300">Cloud:</span>
            <span className={cloudHealth?.status === 'healthy' ? 'text-emerald-400 font-semibold' : 'text-amber-300'}>
              {cloudHealth?.status === 'healthy'
                ? '4 Tiers OK'
                : cloudHealth?.status === 'partial'
                ? 'Deploy Modal GPU'
                : 'Offline/Dev'}
            </span>
          </button>

          {showCloudMenu && (
            <div className="absolute right-0 mt-2 w-80 bg-cad-card border border-cad-border rounded-xl shadow-2xl p-3 z-50 text-xs font-mono space-y-2">
              <div className="flex items-center justify-between border-b border-cad-border pb-2">
                <span className="font-semibold text-cyan-300">Zero-Heat Cloud Tiers</span>
                <button
                  onClick={() => setShowCloudMenu(false)}
                  className="text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              </div>
              {cloudHealth ? (
                <div className="space-y-1.5">
                  {Object.entries(cloudHealth.cloud_tiers).map(([key, info]) => {
                    const ok = ['connected', 'dev_mock_connected', 'simulated_ready'].includes(info.status);
                    const pendingDeploy = info.status === 'not_deployed';
                    const badgeLabel = info.status === 'connected' ? 'LIVE' : pendingDeploy ? 'DEPLOY REQ' : 'DEV';
                    return (
                      <div key={key} className="p-2 rounded bg-cad-dark/70 border border-slate-800 space-y-1">
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <div className="text-slate-200 font-semibold">{info.engine || info.provider || key}</div>
                            <div className="text-[10px] text-slate-400">{info.tier}</div>
                          </div>
                          <span
                            className={`flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded shrink-0 ${
                              info.status === 'connected'
                                ? 'bg-emerald-950 text-emerald-300'
                                : ok
                                ? 'bg-slate-800 text-slate-300'
                                : pendingDeploy
                                ? 'bg-amber-950 text-amber-300'
                                : 'bg-rose-950 text-rose-300'
                            }`}
                          >
                            {ok ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                            {badgeLabel}
                          </span>
                        </div>
                        {pendingDeploy && (info.note || info.message) && (
                          <div className="text-[10px] text-amber-300/90 leading-snug">
                            {info.note || info.message}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="text-[11px] text-slate-400">
                  Start backend (`localhost:8000`) to inspect live Supabase, Redis, R2 & Modal GPU telemetry.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Engine Kernel Status */}
        <div className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-cad-dark border border-cad-border text-xs font-mono">
          <Cpu className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
          <span className="text-slate-300 hidden sm:inline">Kernel:</span>
          <span className="text-emerald-400 font-semibold">{systemStatus}</span>
        </div>
      </div>
    </header>
  );
};
