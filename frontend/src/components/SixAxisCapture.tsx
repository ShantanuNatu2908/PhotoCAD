import React, { useState } from 'react';
import { Camera, Upload, Sparkles, SlidersHorizontal } from 'lucide-react';
import type { AxisView, ViewDetail } from '../types/cad';

interface SixAxisCaptureProps {
  viewsData: Partial<Record<AxisView, ViewDetail>>;
  onUploadView: (view: AxisView, file: File) => void;
  onLoadDemo: () => void;
  hasScaleRef: boolean;
  setHasScaleRef: (val: boolean) => void;
  scalePxToMm: number;
}

const AXIS_CONFIG: Array<{ key: AxisView; label: string; axis: string; desc: string }> = [
  { key: 'front', label: 'Front (+Y)', axis: 'Elevation', desc: 'Primary front silhouette' },
  { key: 'back', label: 'Back (-Y)', axis: 'Rear', desc: 'Opposite rear elevation' },
  { key: 'top', label: 'Top (+Z)', axis: 'Plan View', desc: 'Plan view with hole patterns' },
  { key: 'bottom', label: 'Bottom (-Z)', axis: 'Base', desc: 'Base datum and mounting holes' },
  { key: 'left', label: 'Left (-X)', axis: 'Profile', desc: 'Left cross-section' },
  { key: 'right', label: 'Right (+X)', axis: 'Profile', desc: 'Right cross-section' }
];

export const SixAxisCapture: React.FC<SixAxisCaptureProps> = ({
  viewsData,
  onUploadView,
  onLoadDemo,
  hasScaleRef,
  setHasScaleRef,
  scalePxToMm
}) => {
  const [showEdges, setShowEdges] = useState(false);

  const handleFileChange = (view: AxisView, e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      onUploadView(view, e.target.files[0]);
    }
  };

  return (
    <div className="bg-cad-card border border-cad-border rounded-xl p-4 shadow-xl space-y-4">
      {/* Header and Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-cad-border pb-3">
        <div>
          <h2 className="text-sm font-semibold text-white flex items-center space-x-2">
            <Camera className="w-4 h-4 text-cyan-400" />
            <span>6-Axis Orthographic Scanning Chamber</span>
          </h2>
          <p className="text-xs text-slate-400">
            Orthogonal photos with real-time OpenCV contour & edge segmentation
          </p>
        </div>

        <div className="flex items-center space-x-2">
          {/* Quick Demo Loader */}
          <button
            onClick={onLoadDemo}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-cyan-950/70 text-cyan-300 border border-cyan-800 hover:bg-cyan-900 transition text-xs font-mono font-medium shadow-sm"
          >
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            <span>Load Demo Bracket Scan</span>
          </button>

          {/* Masked / Edge view toggle */}
          <button
            onClick={() => setShowEdges(!showEdges)}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border text-xs font-mono transition ${
              showEdges
                ? 'bg-emerald-950/80 text-emerald-300 border-emerald-700'
                : 'bg-cad-dark text-slate-300 border-cad-border hover:border-slate-600'
            }`}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span>{showEdges ? 'Showing SAM Masks' : 'Show SAM Masks'}</span>
          </button>
        </div>
      </div>

      {/* 6-Axis Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {AXIS_CONFIG.map(({ key, label, axis }) => {
          const viewInfo = viewsData[key];
          const hasImage = !!viewInfo?.image_url;
          const displayUrl = showEdges
            ? (viewInfo?.masked_url || viewInfo?.edge_url || viewInfo?.image_url)
            : viewInfo?.image_url;

          return (
            <div
              key={key}
              className={`relative group rounded-lg border transition overflow-hidden flex flex-col ${
                hasImage ? 'border-cyan-500/40 bg-cad-dark' : 'border-dashed border-cad-border bg-cad-dark/50 hover:border-cyan-500/40'
              }`}
            >
              {/* Card Header */}
              <div className="px-2.5 py-1.5 bg-[#121822] border-b border-cad-border flex items-center justify-between text-[11px] font-mono">
                <span className="font-semibold text-slate-200">{label}</span>
                <span className="text-[10px] text-slate-400">{axis}</span>
              </div>

              {/* Viewport Preview Area */}
              <div className="relative h-28 bg-[#080b11] flex items-center justify-center overflow-hidden">
                {hasImage ? (
                  <>
                    <img
                      src={displayUrl}
                      alt={label}
                      className="w-full h-full object-contain p-1.5 transition duration-200 group-hover:scale-105"
                    />
                    <div className="absolute bottom-1 right-1 bg-black/80 px-1.5 py-0.5 rounded text-[10px] font-mono text-cyan-400">
                      {viewInfo.primary_dimensions_mm ? `${viewInfo.primary_dimensions_mm[0]} × ${viewInfo.primary_dimensions_mm[1]} mm` : 'Mapped'}
                    </div>
                  </>
                ) : (
                  <label className="cursor-pointer flex flex-col items-center justify-center p-3 text-center space-y-1 w-full h-full">
                    <Upload className="w-5 h-5 text-slate-500 group-hover:text-cyan-400 transition" />
                    <span className="text-[10px] font-mono text-slate-400 group-hover:text-cyan-300">
                      Upload {label}
                    </span>
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => handleFileChange(key, e)}
                    />
                  </label>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Metric Calibration Toolbar */}
      <div className="bg-cad-dark/80 rounded-lg p-2.5 border border-cad-border flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
        <label className="flex items-center space-x-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={hasScaleRef}
            onChange={(e) => setHasScaleRef(e.target.checked)}
            className="rounded border-slate-700 text-cyan-500 focus:ring-0 w-3.5 h-3.5 bg-cad-card"
          />
          <span className="text-slate-300">ArUco / Reference Scale Calibration (20mm Token)</span>
        </label>
        <span className="text-slate-400">
          Scale Factor: <span className="text-cyan-400 font-semibold">{scalePxToMm.toFixed(2)} px/mm</span>
        </span>
      </div>
    </div>
  );
};
