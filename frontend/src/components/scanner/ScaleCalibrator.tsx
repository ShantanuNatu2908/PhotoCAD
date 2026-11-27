import React, { useState, useRef, useEffect } from 'react';
import type { MouseEvent } from 'react';
import { Ruler, Check, X, Crosshair, CreditCard, Compass } from 'lucide-react';
import type { CalibrationSpec, AxisView } from '../../types/cad';

interface ScaleCalibratorProps {
  primaryViewUrl: string;
  referenceSide?: AxisView;
  onSaveCalibration: (spec: CalibrationSpec) => void;
  onCancel: () => void;
  initialKnownLengthMm?: number;
}

export const ScaleCalibrator: React.FC<ScaleCalibratorProps> = ({
  primaryViewUrl,
  referenceSide = 'front',
  onSaveCalibration,
  onCancel,
  initialKnownLengthMm = 64.5
}) => {
  const [mode, setMode] = useState<'known_dimension' | 'id1_card' | 'aruco_token'>('known_dimension');
  const [knownLengthMm, setKnownLengthMm] = useState<number>(initialKnownLengthMm);
  const [pointA, setPointA] = useState<[number, number] | null>(null);
  const [pointB, setPointB] = useState<[number, number] | null>(null);
  const [activePoint, setActivePoint] = useState<'A' | 'B'>('A');

  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Switch presets when changing mode
  useEffect(() => {
    if (mode === 'id1_card') {
      setKnownLengthMm(85.6); // ISO/IEC 7810 ID-1 standard width
    } else if (mode === 'aruco_token') {
      setKnownLengthMm(20.0); // Standard 20mm ArUco marker
    }
  }, [mode]);

  // Handle clicking on image to set Point A and Point B
  const handleImageClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();

    // Normalized to original image resolution coordinates
    const scaleX = imgRef.current.naturalWidth / rect.width;
    const scaleY = imgRef.current.naturalHeight / rect.height;

    const clickX = (e.clientX - rect.left) * scaleX;
    const clickY = (e.clientY - rect.top) * scaleY;

    if (activePoint === 'A') {
      setPointA([Math.round(clickX), Math.round(clickY)]);
      setActivePoint('B');
    } else {
      setPointB([Math.round(clickX), Math.round(clickY)]);
      setActivePoint('A');
    }
  };

  // Compute pixel distance between A and B
  const pixelDistance = pointA && pointB
    ? Math.hypot(pointB[0] - pointA[0], pointB[1] - pointA[1])
    : null;

  // Compute scale: mm per pixel
  const mmPerPixel = pixelDistance && pixelDistance > 0 && knownLengthMm > 0
    ? knownLengthMm / pixelDistance
    : null;

  const handleSave = () => {
    if (!knownLengthMm || knownLengthMm <= 0) return;

    const spec: CalibrationSpec = {
      mode,
      reference_side: referenceSide,
      known_length_mm: knownLengthMm,
      point_a_px: pointA || undefined,
      point_b_px: pointB || undefined,
      mm_per_unit: mmPerPixel || (pixelDistance ? knownLengthMm / pixelDistance : undefined)
    };

    onSaveCalibration(spec);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-md p-4">
      <div className="bg-cad-card border border-cad-border rounded-xl w-full max-w-3xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="bg-cad-dark px-5 py-3 border-b border-cad-border flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Ruler className="w-4 h-4 text-cyan-400" />
            <h3 className="font-semibold text-sm text-white">
              Metric Scale Calibration (1:1 mm Grounding)
            </h3>
          </div>
          <button
            onClick={onCancel}
            className="text-slate-400 hover:text-white text-xs font-mono px-2 py-1 rounded hover:bg-slate-800 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Mode Selector Tabs */}
        <div className="flex border-b border-cad-border bg-cad-dark/50 px-5 pt-2 gap-2">
          <button
            onClick={() => setMode('known_dimension')}
            className={`pb-2.5 px-3 text-xs font-mono font-medium border-b-2 transition flex items-center space-x-1.5 ${
              mode === 'known_dimension'
                ? 'border-cyan-400 text-cyan-400'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            <Crosshair className="w-3.5 h-3.5" />
            <span>2-Point Caliper Measurement</span>
          </button>
          <button
            onClick={() => setMode('id1_card')}
            className={`pb-2.5 px-3 text-xs font-mono font-medium border-b-2 transition flex items-center space-x-1.5 ${
              mode === 'id1_card'
                ? 'border-cyan-400 text-cyan-400'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            <CreditCard className="w-3.5 h-3.5" />
            <span>ID-1 Reference Card (85.6mm)</span>
          </button>
          <button
            onClick={() => setMode('aruco_token')}
            className={`pb-2.5 px-3 text-xs font-mono font-medium border-b-2 transition flex items-center space-x-1.5 ${
              mode === 'aruco_token'
                ? 'border-cyan-400 text-cyan-400'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            <Compass className="w-3.5 h-3.5" />
            <span>ArUco Token (20mm)</span>
          </button>
        </div>

        {/* Content Body */}
        <div className="p-5 overflow-y-auto space-y-4 flex-1">
          {/* Instructions banner */}
          <div className="bg-cyan-950/40 border border-cyan-800/60 rounded-lg p-3 text-xs font-mono text-cyan-200 flex items-start justify-between">
            <div>
              <p className="font-semibold mb-1">
                {mode === 'known_dimension'
                  ? 'Click two points across a known physical edge (e.g., overall length or bolt-to-bolt center).'
                  : mode === 'id1_card'
                  ? 'Click opposing corners of the standard credit/ID card placed beside the object.'
                  : 'Click opposing edges of the 20mm ArUco marker.'}
              </p>
              <p className="text-[11px] text-slate-400">
                Active Selection: <span className="text-cyan-400 font-bold">Point {activePoint}</span>. Click on the image below to place.
              </p>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-slate-400 uppercase">Ref View:</span>
              <span className="text-xs font-bold text-white ml-1 uppercase">{referenceSide}</span>
            </div>
          </div>

          {/* Interactive Image Canvas */}
          <div
            ref={containerRef}
            onClick={handleImageClick}
            className="relative bg-black rounded-lg border border-cad-border overflow-hidden cursor-crosshair flex items-center justify-center min-h-[300px]"
          >
            <img
              ref={imgRef}
              src={primaryViewUrl}
              alt="Calibration Reference"
              className="max-h-[380px] w-auto object-contain select-none pointer-events-auto"
            />

            {/* Point A Marker */}
            {pointA && imgRef.current && (
              <div
                className="absolute w-4 h-4 -ml-2 -mt-2 rounded-full border-2 border-emerald-400 bg-emerald-400/40 flex items-center justify-center pointer-events-none text-[9px] font-bold text-black"
                style={{
                  left: `${(pointA[0] / imgRef.current.naturalWidth) * 100}%`,
                  top: `${(pointA[1] / imgRef.current.naturalHeight) * 100}%`
                }}
              >
                A
              </div>
            )}

            {/* Point B Marker */}
            {pointB && imgRef.current && (
              <div
                className="absolute w-4 h-4 -ml-2 -mt-2 rounded-full border-2 border-cyan-400 bg-cyan-400/40 flex items-center justify-center pointer-events-none text-[9px] font-bold text-black"
                style={{
                  left: `${(pointB[0] / imgRef.current.naturalWidth) * 100}%`,
                  top: `${(pointB[1] / imgRef.current.naturalHeight) * 100}%`
                }}
              >
                B
              </div>
            )}
          </div>

          {/* Measurements Form */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 bg-cad-dark/80 p-3 rounded-lg border border-cad-border text-xs font-mono">
            <div>
              <label className="text-slate-400 block mb-1">Caliper Length (mm):</label>
              <input
                type="number"
                step="0.1"
                min="1.0"
                max="2000.0"
                value={knownLengthMm}
                onChange={(e) => setKnownLengthMm(parseFloat(e.target.value) || 0)}
                className="w-full bg-cad-card border border-cad-border rounded px-2.5 py-1.5 text-white font-bold focus:border-cyan-400 focus:outline-none"
              />
            </div>

            <div>
              <span className="text-slate-400 block mb-1">Pixel Distance:</span>
              <div className="text-white font-semibold pt-1.5">
                {pixelDistance ? `${pixelDistance.toFixed(1)} px` : '— Pick Points A & B —'}
              </div>
            </div>

            <div>
              <span className="text-slate-400 block mb-1">Calculated Scale Factor:</span>
              <div className="text-cyan-400 font-bold pt-1.5">
                {mmPerPixel ? `${mmPerPixel.toFixed(4)} mm/px` : '— Pending Points —'}
              </div>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="bg-cad-dark px-5 py-3 border-t border-cad-border flex items-center justify-between">
          <div className="text-[11px] font-mono text-slate-400">
            {mmPerPixel ? (
              <span className="text-emerald-400 flex items-center gap-1">
                <Check className="w-3.5 h-3.5" /> 1:1 mm Scale Calibrated
              </span>
            ) : (
              <span>Pick Point A and Point B on image</span>
            )}
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={onCancel}
              className="px-3.5 py-1.5 rounded-lg border border-cad-border text-slate-300 hover:text-white text-xs font-mono transition"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!knownLengthMm || knownLengthMm <= 0}
              className="px-4 py-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-semibold text-xs font-mono transition shadow-md disabled:opacity-50"
            >
              Lock 1:1 Metric Scale
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
