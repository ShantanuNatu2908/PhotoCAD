import React, { useEffect, useState } from 'react';
import {
  FolderKanban,
  RefreshCw,
  Box,
  ArrowRight,
  Sliders,
  Plus,
  Layers,
  Clock,
} from 'lucide-react';
import { fetchSavedScans, resolveBackendAssetUrl } from '../../services/scanApi';
import type { SavedScanItem } from '../../types/cad';

interface SavedScansPageProps {
  onOpenViewerForScan: (item: SavedScanItem) => void;
  onOpenGenerateForScan: (item: SavedScanItem) => void;
  onStartNewProject: () => void;
}

export const SavedScansPage: React.FC<SavedScansPageProps> = ({
  onOpenViewerForScan,
  onOpenGenerateForScan,
  onStartNewProject,
}) => {
  const [scans, setScans] = useState<SavedScanItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadScans = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSavedScans();
      setScans(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to reach backend scan archive');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    fetchSavedScans()
      .then((data) => {
        if (!cancelled) {
          setScans(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to reach backend scan archive');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="max-w-[1440px] mx-auto p-4 lg:p-6 space-y-5">
      {/* Header */}
      <div className="bg-cad-card border border-cad-border rounded-xl p-4 flex flex-wrap items-center justify-between gap-3 shadow-lg">
        <div>
          <div className="flex items-center gap-2 text-xs font-mono text-cyan-400">
            <FolderKanban className="w-4 h-4" />
            <span>PROJECT ARCHIVE &amp; SAVED 3D SCANS</span>
          </div>
          <h1 className="text-lg font-bold text-white mt-0.5">Previous Projects &amp; CAD Revisions</h1>
          <p className="text-xs text-slate-400">
            Re-open any scanned object directly into the Fullscreen 3D CAD Inspector or adjust calibration &amp; synthesis options.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => void loadScans()}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-cad-dark border border-cad-border hover:border-cyan-500/60 text-xs font-mono text-slate-300 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
            <span>Refresh</span>
          </button>
          <button
            onClick={onStartNewProject}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-xs font-mono font-semibold text-white transition"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New Capture Session</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-amber-950/40 border border-amber-700/60 text-xs font-mono text-amber-200">
          {error} — Ensure FastAPI backend is running on localhost:8000.
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((n) => (
            <div key={n} className="h-56 rounded-xl bg-cad-card/60 border border-cad-border animate-pulse" />
          ))}
        </div>
      ) : scans.length === 0 ? (
        <div className="bg-cad-card border border-cad-border rounded-xl p-10 text-center space-y-3">
          <Box className="w-10 h-10 text-slate-500 mx-auto" />
          <h3 className="text-sm font-semibold text-white">No Saved Scan Sessions Yet</h3>
          <p className="text-xs text-slate-400 max-w-md mx-auto">
            Capture or upload 4 to 6 side views in the Capture Studio to store your first 3D scan and CAD revision here.
          </p>
          <button
            onClick={onStartNewProject}
            className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-xs font-mono font-semibold text-white transition"
          >
            Start First Scan
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {scans.map((item) => {
            const thumb = resolveBackendAssetUrl(item.thumbnail_url);
            const gen = item.latest_generation;
            const dims = gen?.dimensions_mm
              ? `${gen.dimensions_mm.x} × ${gen.dimensions_mm.y} × ${gen.dimensions_mm.z} mm`
              : item.geometry_report?.bounding_box_mm
                ? `${item.geometry_report.bounding_box_mm.join(' × ')} mm`
                : 'Uncalibrated';

            return (
              <div
                key={item.scan_id}
                className="bg-cad-card border border-cad-border hover:border-cyan-500/50 rounded-xl overflow-hidden flex flex-col justify-between shadow-lg transition"
              >
                <div>
                  <div className="h-36 bg-[#070a10] border-b border-cad-border relative flex items-center justify-center overflow-hidden">
                    {thumb ? (
                      <img src={thumb} alt={item.project_name} className="w-full h-full object-contain p-2" />
                    ) : (
                      <Layers className="w-8 h-8 text-slate-600" />
                    )}
                    <div className="absolute top-2 left-2 bg-black/80 px-2 py-0.5 rounded text-[10px] font-mono text-cyan-300 border border-cyan-800/70">
                      {item.views_count}/6 Views
                    </div>
                    <div
                      className={`absolute top-2 right-2 px-2 py-0.5 rounded text-[10px] font-mono uppercase ${
                        gen?.status === 'completed'
                          ? 'bg-emerald-950/90 text-emerald-300 border border-emerald-700'
                          : 'bg-slate-900/90 text-slate-300 border border-slate-700'
                      }`}
                    >
                      {gen ? `Rev v${gen.version} ${gen.status}` : item.status}
                    </div>
                  </div>

                  <div className="p-3.5 space-y-1.5">
                    <h3 className="text-sm font-bold text-white truncate">{item.project_name}</h3>
                    <div className="text-xs font-mono text-cyan-300">{dims}</div>
                    {item.created_at && (
                      <div className="flex items-center gap-1 text-[10px] font-mono text-slate-500">
                        <Clock className="w-3 h-3" />
                        <span>{new Date(item.created_at).toLocaleString()}</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="p-3 pt-0 grid grid-cols-2 gap-2">
                  <button
                    onClick={() => onOpenGenerateForScan(item)}
                    className="flex items-center justify-center gap-1 py-2 rounded-lg bg-cad-dark hover:bg-slate-800 border border-cad-border text-[11px] font-mono text-slate-200 transition"
                  >
                    <Sliders className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Configure</span>
                  </button>
                  <button
                    onClick={() => onOpenViewerForScan(item)}
                    className="flex items-center justify-center gap-1 py-2 rounded-lg bg-cyan-950/80 hover:bg-cyan-900 border border-cyan-700 text-[11px] font-mono font-semibold text-cyan-300 transition"
                  >
                    <span>3D Viewer</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
