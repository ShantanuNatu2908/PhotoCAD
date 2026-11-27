import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Camera, RotateCcw, Sparkles, Ruler, AlertCircle, CheckCircle2 } from 'lucide-react';
import { computeLaplacianVariance, evaluateSharpness } from '../../utils/blurDetector';
import type { SharpnessResult } from '../../utils/blurDetector';
import { ScaleCalibrator } from './ScaleCalibrator';
import type { AxisView, KeyframeCapture, CalibrationSpec } from '../../types/cad';

interface ScannerChamberProps {
  onAllKeyframesCaptured: (captures: Record<AxisView, KeyframeCapture>, calibration?: CalibrationSpec) => void;
  onLoadDemo: () => void;
}

const AXIS_SEQUENCE: Array<{ key: AxisView; label: string; axis: string; desc: string }> = [
  { key: 'front', label: 'FRONT (+Y)', axis: 'Front Elevation', desc: 'Face primary mechanical features directly' },
  { key: 'back', label: 'BACK (-Y)', axis: 'Rear Elevation', desc: 'Opposing rear face' },
  { key: 'left', label: 'LEFT (-X)', axis: 'Left Profile', desc: 'Left cross-section' },
  { key: 'right', label: 'RIGHT (+X)', axis: 'Right Profile', desc: 'Right cross-section' },
  { key: 'top', label: 'TOP (+Z)', axis: 'Plan View', desc: 'Top view with mounting holes/bores' },
  { key: 'bottom', label: 'BOTTOM (-Z)', axis: 'Base Datum', desc: 'Base surface and bottom cutouts' }
];

export const ScannerChamber: React.FC<ScannerChamberProps> = ({
  onAllKeyframesCaptured,
  onLoadDemo
}) => {
  const [currentSideIndex, setCurrentSideIndex] = useState<number>(0);
  const [captures, setCaptures] = useState<Partial<Record<AxisView, KeyframeCapture>>>({});
  const [cameraActive, setCameraActive] = useState<boolean>(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [sharpness, setSharpness] = useState<SharpnessResult>({
    score: 0,
    isSharp: false,
    status: 'blurry',
    label: 'Initializing...'
  });
  const [autoCaptureEnabled, setAutoCaptureEnabled] = useState<boolean>(true);
  const [sharpHoldCounter, setSharpHoldCounter] = useState<number>(0);
  const [showCalibrator, setShowCalibrator] = useState<boolean>(false);
  const [calibrationSpec, setCalibrationSpec] = useState<CalibrationSpec | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const hiddenCanvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafIdRef = useRef<number | null>(null);

  const currentAxis = AXIS_SEQUENCE[currentSideIndex];
  const capturedCount = Object.keys(captures).length;
  const isComplete = capturedCount === 6;

  // 1. Initialize Browser Camera Feed (getUserMedia - FR-01)
  const startCamera = async () => {
    try {
      setCameraError(null);
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: 'environment',
          width: { ideal: 1920 },
          height: { ideal: 1080 }
        },
        audio: false
      });

      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
        setCameraActive(true);
      }
    } catch (err: any) {
      console.warn('Camera initialization failed, falling back to upload mode', err);
      setCameraError(err.message || 'Camera permission denied or camera not found');
      setCameraActive(false);
    }
  };

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    setCameraActive(false);
  };

  useEffect(() => {
    startCamera();
    return () => {
      stopCamera();
    };
  }, []);

  // 2. Real-Time Sharpness / Blur Evaluation Loop (FR-03)
  const evaluateCurrentFrame = useCallback(() => {
    if (!videoRef.current || !hiddenCanvasRef.current || !cameraActive) {
      rafIdRef.current = requestAnimationFrame(evaluateCurrentFrame);
      return;
    }

    const video = videoRef.current;
    const canvas = hiddenCanvasRef.current;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });

    if (ctx && video.readyState === video.HAVE_ENOUGH_DATA) {
      // Downsample to 320x240 for 30 FPS analysis
      canvas.width = 320;
      canvas.height = 240;
      ctx.drawImage(video, 0, 0, 320, 240);

      try {
        const imgData = ctx.getImageData(0, 0, 320, 240);
        const variance = computeLaplacianVariance(imgData);
        const result = evaluateSharpness(variance);
        setSharpness(result);

        // Auto-capture logic: if sharp for > 1.2s (~36 continuous frames at 30fps)
        if (autoCaptureEnabled && result.isSharp && !captures[currentAxis.key]) {
          setSharpHoldCounter((prev) => {
            if (prev >= 30) {
              snapKeyframe(currentAxis.key, variance);
              return 0;
            }
            return prev + 1;
          });
        } else {
          setSharpHoldCounter(0);
        }
      } catch (e) {
        // Ignore canvas read error during transitions
      }
    }

    rafIdRef.current = requestAnimationFrame(evaluateCurrentFrame);
  }, [cameraActive, autoCaptureEnabled, currentAxis.key, captures]);

  useEffect(() => {
    if (cameraActive) {
      rafIdRef.current = requestAnimationFrame(evaluateCurrentFrame);
    }
    return () => {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    };
  }, [cameraActive, evaluateCurrentFrame]);

  // 3. Uncompressed PNG Keyframe Capture (FR-04)
  const snapKeyframe = (side: AxisView, blurScore: number) => {
    if (!videoRef.current) return;
    const video = videoRef.current;

    // Full resolution snapshot canvas
    const snapCanvas = document.createElement('canvas');
    snapCanvas.width = video.videoWidth || 1920;
    snapCanvas.height = video.videoHeight || 1080;
    const snapCtx = snapCanvas.getContext('2d');

    if (!snapCtx) return;
    snapCtx.drawImage(video, 0, 0, snapCanvas.width, snapCanvas.height);

    snapCanvas.toBlob(
      (blob) => {
        if (!blob) return;
        const dataUrl = URL.createObjectURL(blob);
        const newCapture: KeyframeCapture = {
          side,
          blob,
          dataUrl,
          blurScore,
          width: snapCanvas.width,
          height: snapCanvas.height,
          timestamp: new Date().toISOString()
        };

        setCaptures((prev) => {
          const updated = { ...prev, [side]: newCapture };
          // If all 6 sides are captured, automatically notify parent
          if (Object.keys(updated).length === 6) {
            onAllKeyframesCaptured(updated as Record<AxisView, KeyframeCapture>, calibrationSpec || undefined);
          }
          return updated;
        });

        // Advance to next view in sequence if available
        if (currentSideIndex < AXIS_SEQUENCE.length - 1) {
          setCurrentSideIndex((prev) => prev + 1);
        }
      },
      'image/png' // Uncompressed PNG per PCAD-PRD-SRS-001 FR-04
    );
  };

  // Manual snap trigger
  const handleManualSnap = () => {
    snapKeyframe(currentAxis.key, sharpness.score);
  };

  // Retake individual side (FR-05)
  const handleRetake = (index: number) => {
    const targetKey = AXIS_SEQUENCE[index].key;
    setCaptures((prev) => {
      const copy = { ...prev };
      delete copy[targetKey];
      return copy;
    });
    setCurrentSideIndex(index);
  };

  // Handle file upload fallback
  const handleFileUpload = (side: AxisView, e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const dataUrl = URL.createObjectURL(file);
      const newCapture: KeyframeCapture = {
        side,
        blob: file,
        dataUrl,
        blurScore: 180.0,
        width: 1920,
        height: 1080,
        timestamp: new Date().toISOString()
      };
      setCaptures((prev) => {
        const updated = { ...prev, [side]: newCapture };
        if (Object.keys(updated).length === 6) {
          onAllKeyframesCaptured(updated as Record<AxisView, KeyframeCapture>, calibrationSpec || undefined);
        }
        return updated;
      });
      if (currentSideIndex < AXIS_SEQUENCE.length - 1) {
        setCurrentSideIndex((prev) => prev + 1);
      }
    }
  };

  return (
    <div className="bg-cad-card border border-cad-border rounded-xl p-4 shadow-xl space-y-4">
      {/* Hidden processing canvas for Laplacian variance */}
      <canvas ref={hiddenCanvasRef} className="hidden" />

      {/* Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-cad-border pb-3">
        <div>
          <div className="flex items-center space-x-2">
            <Camera className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold text-white">
              6-Axis Real-Time Guided Capture
            </h2>
          </div>
          <p className="text-xs text-slate-400">
            Uncompressed PNG keyframes with local Laplacian motion-blur filter
          </p>
        </div>

        <div className="flex items-center space-x-2">
          {/* Quick Demo Loader */}
          <button
            onClick={onLoadDemo}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-cyan-950/70 text-cyan-300 border border-cyan-800 hover:bg-cyan-900 transition text-xs font-mono font-medium shadow-sm"
          >
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            <span>Load Demo Scan</span>
          </button>

          {/* Metric Calibrator Modal Trigger */}
          <button
            onClick={() => setShowCalibrator(true)}
            disabled={!captures.front}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border text-xs font-mono transition ${
              calibrationSpec
                ? 'bg-emerald-950 text-emerald-300 border-emerald-700'
                : 'bg-cad-dark text-slate-300 border-cad-border hover:border-cyan-500 disabled:opacity-40'
            }`}
          >
            <Ruler className="w-3.5 h-3.5" />
            <span>{calibrationSpec ? 'Scale Locked' : 'Calibrate Scale'}</span>
          </button>
        </div>
      </div>

      {/* Camera Viewport & Overlay Chamber */}
      <div className="relative aspect-video max-h-[380px] w-full bg-black rounded-lg border border-cad-border overflow-hidden flex items-center justify-center">
        {cameraActive ? (
          <video
            ref={videoRef}
            playsInline
            muted
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="text-center p-6 space-y-3">
            <AlertCircle className="w-8 h-8 text-amber-400 mx-auto" />
            <p className="text-xs font-mono text-slate-300">{cameraError || 'Camera offline'}</p>
            <button
              onClick={startCamera}
              className="px-3.5 py-1.5 rounded bg-cyan-600 hover:bg-cyan-500 text-xs font-mono text-white transition"
            >
              Retry Camera Connection
            </button>
          </div>
        )}

        {/* 6-Axis Orientation Guide Overlay (FR-02) */}
        {cameraActive && (
          <div className="absolute inset-0 pointer-events-none flex flex-col justify-between p-4">
            {/* Top Bar: Target Perspective & Sharpness Badge */}
            <div className="flex items-center justify-between">
              <div className="bg-black/80 backdrop-blur px-3 py-1.5 rounded-lg border border-cyan-500/50 text-xs font-mono">
                <span className="text-slate-400 uppercase">TARGET: </span>
                <span className="text-cyan-300 font-bold">{currentAxis.label}</span>
                <span className="text-[10px] text-slate-400 ml-2">({currentAxis.axis})</span>
              </div>

              {/* Real-Time Sharpness Badge (FR-03) */}
              <div
                className={`px-3 py-1.5 rounded-lg border text-xs font-mono font-semibold flex items-center space-x-1.5 backdrop-blur ${
                  sharpness.status === 'sharp'
                    ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500'
                    : sharpness.status === 'critical'
                    ? 'bg-rose-950/80 text-rose-300 border-rose-500 animate-pulse'
                    : 'bg-amber-950/80 text-amber-300 border-amber-500'
                }`}
              >
                <span
                  className={`w-2 h-2 rounded-full ${
                    sharpness.status === 'sharp' ? 'bg-emerald-400' : 'bg-rose-400'
                  }`}
                />
                <span>{sharpness.label}</span>
              </div>
            </div>

            {/* Center: Silhouette Reticle */}
            <div className="self-center w-52 h-36 border-2 border-dashed border-cyan-400/40 rounded-xl flex items-center justify-center">
              <span className="text-[10px] font-mono uppercase text-cyan-400/60 bg-black/60 px-2 py-0.5 rounded">
                Align {currentAxis.label} in Box
              </span>
            </div>

            {/* Bottom Bar: Auto-Capture Progress & Manual Snap Button */}
            <div className="flex items-center justify-between pointer-events-auto">
              <div className="flex items-center space-x-2">
                <label className="flex items-center space-x-2 text-xs font-mono text-slate-300 bg-black/70 px-2.5 py-1 rounded border border-cad-border cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoCaptureEnabled}
                    onChange={(e) => setAutoCaptureEnabled(e.target.checked)}
                    className="rounded border-slate-700 text-cyan-500 focus:ring-0"
                  />
                  <span>Auto-Snap on Steady</span>
                </label>
                {autoCaptureEnabled && sharpHoldCounter > 0 && (
                  <span className="text-[10px] font-mono text-cyan-400 bg-black/80 px-2 py-1 rounded border border-cyan-800">
                    Locking: {Math.round((sharpHoldCounter / 30) * 100)}%
                  </span>
                )}
                {isComplete && (
                  <span className="text-[10px] font-mono text-emerald-300 bg-emerald-950/80 px-2 py-1 rounded border border-emerald-700 flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> All 6 Captured
                  </span>
                )}
              </div>

              <button
                onClick={handleManualSnap}
                disabled={captures[currentAxis.key] !== undefined}
                className="px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-mono text-xs font-bold shadow-lg transition disabled:opacity-50"
              >
                SNAP KEYFRAME (PNG)
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 6-Axis Thumbnail Progress Strip (FR-05) */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-2">
        {AXIS_SEQUENCE.map(({ key, label }, index) => {
          const capture = captures[key];
          const isSelected = index === currentSideIndex;

          return (
            <div
              key={key}
              onClick={() => setCurrentSideIndex(index)}
              className={`relative rounded-lg border p-1.5 cursor-pointer transition flex flex-col justify-between ${
                capture
                  ? 'border-emerald-500/50 bg-emerald-950/20'
                  : isSelected
                  ? 'border-cyan-400 bg-cyan-950/30 ring-1 ring-cyan-400'
                  : 'border-cad-border bg-cad-dark/50 hover:border-slate-600'
              }`}
            >
              {/* Thumbnail image or placeholder */}
              <div className="h-16 w-full rounded bg-black/60 overflow-hidden flex items-center justify-center relative">
                {capture ? (
                  <>
                    <img
                      src={capture.dataUrl}
                      alt={label}
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute top-1 right-1 bg-black/80 px-1 py-0.5 rounded text-[8px] font-mono text-emerald-400">
                      ✓ {capture.blurScore.toFixed(0)}
                    </div>
                  </>
                ) : (
                  <label className="flex flex-col items-center justify-center text-[10px] text-slate-500 font-mono cursor-pointer w-full h-full">
                    <span>{label.split(' ')[0]}</span>
                    <input
                      type="file"
                      accept="image/png,image/jpeg"
                      className="hidden"
                      onChange={(e) => handleFileUpload(key, e)}
                    />
                  </label>
                )}
              </div>

              {/* Card Footer: Label & Retake button */}
              <div className="flex items-center justify-between pt-1 text-[10px] font-mono">
                <span className={capture ? 'text-emerald-300 font-bold' : 'text-slate-400'}>
                  {label.split(' ')[0]}
                </span>
                {capture && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRetake(index);
                    }}
                    title="Retake this perspective"
                    className="text-slate-400 hover:text-rose-400"
                  >
                    <RotateCcw className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Metric Calibration Modal */}
      {showCalibrator && captures.front && (
        <ScaleCalibrator
          primaryViewUrl={captures.front.dataUrl}
          referenceSide="front"
          onSaveCalibration={(spec) => {
            setCalibrationSpec(spec);
            setShowCalibrator(false);
            if (Object.keys(captures).length === 6) {
              onAllKeyframesCaptured(captures as Record<AxisView, KeyframeCapture>, spec);
            }
          }}
          onCancel={() => setShowCalibrator(false)}
        />
      )}
    </div>
  );
};
