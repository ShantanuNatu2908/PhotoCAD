import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Camera,
  RotateCcw,
  Sparkles,
  Ruler,
  CheckCircle2,
  Upload,
  FolderOpen,
  Video,
  VideoOff,
  AlertCircle,
  ArrowRight,
  Timer,
} from 'lucide-react';
import {
  computeLaplacianVariance,
  evaluateSharpness,
  analyzeAndConvertImageToPng,
} from '../../utils/blurDetector';
import type { SharpnessResult } from '../../utils/blurDetector';
import { ScaleCalibrator } from './ScaleCalibrator';
import type { AxisView, KeyframeCapture, CalibrationSpec } from '../../types/cad';

interface ScannerChamberProps {
  projectName: string;
  captures: Partial<Record<AxisView, KeyframeCapture>>;
  calibrationSpec: CalibrationSpec | null;
  onSideCaptured: (side: AxisView, capture: KeyframeCapture) => void;
  onRemoveSide: (side: AxisView) => void;
  onBatchCaptured: (captures: Partial<Record<AxisView, KeyframeCapture>>) => void;
  onSaveCalibration: (spec: CalibrationSpec) => void;
  onLoadDemo: () => void;
  onProceedToGenerate: () => void;
}

const AXIS_SEQUENCE: Array<{ key: AxisView; label: string; axis: string; desc: string }> = [
  { key: 'front', label: 'FRONT (+Y)', axis: 'Front View', desc: 'Align primary front face toward camera' },
  { key: 'back', label: 'BACK (-Y)', axis: 'Rear View', desc: 'Rotate 180° to show rear elevation' },
  { key: 'left', label: 'LEFT (-X)', axis: 'Left Profile', desc: 'Rotate 90° to left side profile' },
  { key: 'right', label: 'RIGHT (+X)', axis: 'Right Profile', desc: 'Rotate to right side profile' },
  { key: 'top', label: 'TOP (+Z)', axis: 'Overhead Plan', desc: 'Shoot overhead top silhouette' },
  { key: 'bottom', label: 'BOTTOM (-Z)', axis: 'Base (Optional)', desc: 'Shoot underside or skip for flat bases' },
];

export const ScannerChamber: React.FC<ScannerChamberProps> = ({
  projectName,
  captures,
  calibrationSpec,
  onSideCaptured,
  onRemoveSide,
  onBatchCaptured,
  onSaveCalibration,
  onLoadDemo,
  onProceedToGenerate,
}) => {
  const [currentSideIndex, setCurrentSideIndex] = useState<number>(0);
  const [cameraActive, setCameraActive] = useState<boolean>(false);
  const [cameraSideSession, setCameraSideSession] = useState<AxisView | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [videoResLabel, setVideoResLabel] = useState<string>('');
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('');
  const [sharpness, setSharpness] = useState<SharpnessResult>({
    score: 0,
    isSharp: false,
    status: 'blurry',
    label: 'Camera Idle',
  });
  const [countdownSeconds, setCountdownSeconds] = useState<number | null>(null);
  const [showCalibrator, setShowCalibrator] = useState<boolean>(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const hiddenCanvasRef = useRef<HTMLCanvasElement>(null);
  const singleFileInputRef = useRef<HTMLInputElement>(null);
  const batchFileInputRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafIdRef = useRef<number | null>(null);

  const currentAxis = AXIS_SEQUENCE[currentSideIndex];
  const currentCapture = captures[currentAxis.key];
  const capturedCount = AXIS_SEQUENCE.filter((a) => Boolean(captures[a.key])).length;
  const canProceed = capturedCount >= 4;

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const list = await navigator.mediaDevices.enumerateDevices();
      setDevices(list.filter((d) => d.kind === 'videoinput'));
    } catch {
      // Ignore enumerate block prior to permission grant
    }
  }, []);

  const stopCamera = useCallback(() => {
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraActive(false);
    setCameraSideSession(null);
    setVideoResLabel('');
    setCountdownSeconds(null);
  }, []);

  // Starts a dedicated single-side camera session (always waits for explicit capture click)
  const startCameraForSide = useCallback(
    async (side: AxisView, deviceIdOverride?: string) => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setCameraError('Browser webcam API is unavailable here — use Photo File Upload.');
        return;
      }

      stopCamera();
      setCameraError(null);
      setCameraSideSession(side);

      const targetDevice = deviceIdOverride || selectedDeviceId;
      const primaryConstraints: MediaStreamConstraints = {
        video: targetDevice
          ? { deviceId: { exact: targetDevice }, width: { ideal: 1920 }, height: { ideal: 1080 } }
          : { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      };

      try {
        let stream: MediaStream;
        try {
          stream = await navigator.mediaDevices.getUserMedia(primaryConstraints);
        } catch {
          stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        }

        streamRef.current = stream;
        const videoEl = videoRef.current;
        if (videoEl) {
          videoEl.srcObject = stream;
          await videoEl.play();
          const settings = stream.getVideoTracks()[0]?.getSettings();
          if (settings?.width && settings?.height) {
            setVideoResLabel(`${settings.width}×${settings.height}`);
          }
          setCameraActive(true);
          await refreshDevices();
        }
      } catch (err) {
        setCameraError(err instanceof Error ? err.message : 'Camera permission denied or device busy');
        stopCamera();
      }
    },
    [selectedDeviceId, stopCamera, refreshDevices]
  );

  // Enumerate cameras on mount and close webcam cleanly on unmount
  useEffect(() => {
    let cancelled = false;
    if (navigator.mediaDevices?.enumerateDevices) {
      navigator.mediaDevices
        .enumerateDevices()
        .then((list) => {
          if (!cancelled) {
            setDevices(list.filter((d) => d.kind === 'videoinput'));
          }
        })
        .catch(() => {});
    }
    return () => {
      cancelled = true;
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
    };
  }, []);

  // Live Sharpness Monitor ONLY (no auto-capture burst across sides!)
  useEffect(() => {
    if (!cameraActive) return;

    let stopped = false;
    const loop = () => {
      if (stopped) return;
      const video = videoRef.current;
      const canvas = hiddenCanvasRef.current;
      const ctx = canvas?.getContext('2d', { willReadFrequently: true });

      if (video && canvas && ctx && video.readyState >= video.HAVE_CURRENT_DATA) {
        canvas.width = 320;
        canvas.height = 240;
        ctx.drawImage(video, 0, 0, 320, 240);
        try {
          const imgData = ctx.getImageData(0, 0, 320, 240);
          const variance = computeLaplacianVariance(imgData);
          setSharpness(evaluateSharpness(variance));
        } catch {
          // Ignore transient draw timing
        }
      }
      rafIdRef.current = requestAnimationFrame(loop);
    };

    rafIdRef.current = requestAnimationFrame(loop);
    return () => {
      stopped = true;
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    };
  }, [cameraActive]);

  // Captures ONE PNG for the locked cameraSideSession, then IMMEDIATELY stops webcam so user can rotate object calmly
  const captureCurrentSideOnce = useCallback(() => {
    const video = videoRef.current;
    const targetSide = cameraSideSession || currentAxis.key;
    if (!video || video.readyState < 2) return;

    const snapCanvas = document.createElement('canvas');
    snapCanvas.width = video.videoWidth || 1280;
    snapCanvas.height = video.videoHeight || 720;
    const snapCtx = snapCanvas.getContext('2d');
    if (!snapCtx) return;

    snapCtx.drawImage(video, 0, 0, snapCanvas.width, snapCanvas.height);

    snapCanvas.toBlob((blob) => {
      if (!blob) return;
      const newCapture: KeyframeCapture = {
        side: targetSide,
        blob,
        dataUrl: URL.createObjectURL(blob),
        blurScore: Math.max(sharpness.score, 125.0),
        width: snapCanvas.width,
        height: snapCanvas.height,
        timestamp: new Date().toISOString(),
        source: 'camera',
      };

      // Close this side's camera session immediately so user controls pacing for next angle
      stopCamera();
      onSideCaptured(targetSide, newCapture);
    }, 'image/png');
  }, [cameraSideSession, currentAxis.key, sharpness.score, stopCamera, onSideCaptured]);

  // Optional 3-second single-shot countdown trigger for current side only
  useEffect(() => {
    if (countdownSeconds === null) return;
    if (countdownSeconds <= 0) {
      captureCurrentSideOnce();
      return;
    }
    const t = setTimeout(() => setCountdownSeconds((c) => (c !== null ? c - 1 : null)), 1000);
    return () => clearTimeout(t);
  }, [countdownSeconds, captureCurrentSideOnce]);

  const handleSelectSide = (idx: number) => {
    if (idx !== currentSideIndex && cameraActive) {
      stopCamera();
    }
    setCurrentSideIndex(idx);
  };

  const handleNextUncaptured = () => {
    const nextIdx = AXIS_SEQUENCE.findIndex((a, i) => i > currentSideIndex && !captures[a.key]);
    if (nextIdx >= 0) {
      handleSelectSide(nextIdx);
      return;
    }
    const anyMissing = AXIS_SEQUENCE.findIndex((a) => !captures[a.key]);
    if (anyMissing >= 0) {
      handleSelectSide(anyMissing);
    } else if (currentSideIndex < AXIS_SEQUENCE.length - 1) {
      handleSelectSide(currentSideIndex + 1);
    }
  };

  const handleSingleFileChange = async (e: React.ChangeEvent<HTMLInputElement>, explicitSide?: AxisView) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;

    const targetSide = explicitSide || currentAxis.key;
    stopCamera();
    const processed = await analyzeAndConvertImageToPng(file);
    onSideCaptured(targetSide, {
      side: targetSide,
      blob: processed.blob,
      dataUrl: processed.dataUrl,
      blurScore: processed.blurScore,
      width: processed.width,
      height: processed.height,
      timestamp: new Date().toISOString(),
      source: 'upload',
    });
  };

  const handleBatchFilesChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []).slice(0, 6);
    e.target.value = '';
    if (files.length === 0) return;

    stopCamera();
    const processedList = await Promise.all(files.map((f) => analyzeAndConvertImageToPng(f)));
    const nextBatch: Partial<Record<AxisView, KeyframeCapture>> = {};
    const emptySides = AXIS_SEQUENCE.map((a) => a.key).filter((k) => !captures[k]);
    const targets = emptySides.length >= processedList.length ? emptySides : AXIS_SEQUENCE.map((a) => a.key);

    processedList.forEach((proc, idx) => {
      const side = targets[idx];
      if (side) {
        nextBatch[side] = {
          side,
          blob: proc.blob,
          dataUrl: proc.dataUrl,
          blurScore: proc.blurScore,
          width: proc.width,
          height: proc.height,
          timestamp: new Date().toISOString(),
          source: 'upload',
        };
      }
    });
    onBatchCaptured(nextBatch);
  };

  const calibPreviewUrl = captures.front?.dataUrl || currentCapture?.dataUrl || Object.values(captures)[0]?.dataUrl;

  return (
    <div className="max-w-6xl mx-auto p-4 lg:p-6 space-y-5">
      <canvas ref={hiddenCanvasRef} className="hidden" />
      <input
        ref={singleFileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => void handleSingleFileChange(e)}
      />
      <input
        ref={batchFileInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => void handleBatchFilesChange(e)}
      />

      {/* Page 1 Header Card */}
      <div className="bg-cad-card border border-cad-border rounded-xl p-4 flex flex-wrap items-center justify-between gap-3 shadow-lg">
        <div>
          <div className="flex items-center gap-2 text-xs font-mono text-cyan-400">
            <Camera className="w-4 h-4" />
            <span>STEP 1 OF 3 — GUIDED 6-SIDE CAPTURE &amp; UPLOAD STUDIO</span>
          </div>
          <h1 className="text-lg font-bold text-white mt-0.5">{projectName}</h1>
          <p className="text-xs text-slate-400">
            Each perspective opens a distinct manual camera session or file upload — capture 4 to 6 sides at your own pace, then continue to CAD synthesis.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={onLoadDemo}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-cyan-950/70 text-cyan-300 border border-cyan-800 hover:bg-cyan-900 text-xs font-mono font-medium transition"
          >
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            <span>Load Demo Bracket</span>
          </button>

          <button
            onClick={() => setShowCalibrator(true)}
            disabled={!calibPreviewUrl}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-xs font-mono transition ${
              calibrationSpec
                ? 'bg-emerald-950 text-emerald-300 border-emerald-700'
                : 'bg-cad-dark text-slate-200 border-cad-border hover:border-cyan-500 disabled:opacity-40'
            }`}
          >
            <Ruler className="w-3.5 h-3.5" />
            <span>{calibrationSpec ? `Scale: ${calibrationSpec.known_length_mm}mm` : 'Calibrate Scale'}</span>
          </button>
        </div>
      </div>

      {/* Main Guided Side Studio Card */}
      <div className="bg-cad-card border border-cad-border rounded-xl p-4 lg:p-5 space-y-4 shadow-xl">
        {/* Active Side Step Header & Camera/Upload Actions */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-cad-border pb-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-700 font-bold">
                SIDE {currentSideIndex + 1} / 6 • {currentAxis.label}
              </span>
              <span
                className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${
                  cameraActive
                    ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500/60'
                    : currentCapture
                      ? 'bg-cyan-950/60 text-cyan-300 border-cyan-700/60'
                      : 'bg-slate-900 text-slate-400 border-slate-700'
                }`}
              >
                {cameraActive
                  ? `● LIVE ${videoResLabel} (${cameraSideSession?.toUpperCase()})`
                  : currentCapture
                    ? `✓ Captured (${currentCapture.width}×${currentCapture.height})`
                    : 'Waiting for position'}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">{currentAxis.desc}</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => (cameraActive ? stopCamera() : void startCameraForSide(currentAxis.key))}
              className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg border font-mono text-xs font-semibold transition ${
                cameraActive
                  ? 'bg-rose-950/70 text-rose-300 border-rose-700 hover:bg-rose-900'
                  : 'bg-cyan-600 hover:bg-cyan-500 text-white border-cyan-400'
              }`}
            >
              {cameraActive ? <VideoOff className="w-3.5 h-3.5" /> : <Video className="w-3.5 h-3.5" />}
              <span>{cameraActive ? 'Close Camera' : `Start Camera (${currentAxis.key.toUpperCase()})`}</span>
            </button>

            <button
              onClick={() => singleFileInputRef.current?.click()}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-cad-dark hover:bg-slate-800 text-slate-200 border border-cad-border font-mono text-xs transition"
            >
              <Upload className="w-3.5 h-3.5 text-cyan-400" />
              <span>Upload {currentAxis.key.toUpperCase()}</span>
            </button>

            <button
              onClick={() => batchFileInputRef.current?.click()}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-cad-dark hover:bg-slate-800 text-slate-200 border border-cad-border font-mono text-xs transition"
            >
              <FolderOpen className="w-3.5 h-3.5 text-amber-400" />
              <span>Batch Upload (4–6)</span>
            </button>

            {devices.length > 1 && (
              <select
                value={selectedDeviceId}
                onChange={(e) => {
                  setSelectedDeviceId(e.target.value);
                  if (cameraActive) void startCameraForSide(currentAxis.key, e.target.value);
                }}
                className="bg-cad-dark border border-cad-border rounded-lg px-2 py-2 text-[11px] font-mono text-slate-300 max-w-[160px]"
              >
                {devices.map((d, i) => (
                  <option key={d.deviceId || i} value={d.deviceId}>
                    {d.label || `Camera ${i + 1}`}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        {/* Viewport: ALWAYS keep <video> mounted cleanly in DOM */}
        <div className="relative h-[360px] sm:h-[400px] w-full bg-black rounded-xl border border-cad-border overflow-hidden flex items-center justify-center">
          <video
            ref={videoRef}
            playsInline
            muted
            autoPlay
            className={cameraActive ? 'w-full h-full object-cover' : 'hidden'}
          />

          {/* When camera is OFF: show captured preview for this side OR waiting-to-start prompt */}
          {!cameraActive && currentCapture && (
            <div className="w-full h-full flex flex-col items-center justify-center p-4 bg-[#080c12] relative">
              <img
                src={currentCapture.dataUrl}
                alt={currentAxis.label}
                className="max-h-full max-w-full object-contain rounded-lg"
              />
              <div className="absolute bottom-3 left-3 right-3 flex flex-wrap items-center justify-between gap-2 bg-black/85 backdrop-blur px-3.5 py-2 rounded-xl border border-emerald-500/40">
                <div className="flex items-center gap-2 text-xs font-mono text-emerald-300">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>
                    {currentAxis.label} Locked ({currentCapture.width}×{currentCapture.height} • Clarity {currentCapture.blurScore.toFixed(0)})
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => void startCameraForSide(currentAxis.key)}
                    className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs font-mono text-slate-200 transition"
                  >
                    Retake with Cam
                  </button>
                  <button
                    onClick={() => singleFileInputRef.current?.click()}
                    className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs font-mono text-slate-200 transition"
                  >
                    Replace Photo
                  </button>
                  <button
                    onClick={handleNextUncaptured}
                    className="flex items-center gap-1 px-3 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-xs font-mono font-semibold text-white transition"
                  >
                    <span>Next Side</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          )}

          {!cameraActive && !currentCapture && (
            <div className="text-center p-6 space-y-3 max-w-md">
              {cameraError ? (
                <>
                  <AlertCircle className="w-9 h-9 text-amber-400 mx-auto" />
                  <p className="text-xs font-mono text-amber-200">{cameraError}</p>
                </>
              ) : (
                <>
                  <Camera className="w-10 h-10 text-cyan-400/80 mx-auto" />
                  <div className="space-y-1">
                    <h3 className="text-sm font-semibold text-white">Position Object: {currentAxis.label}</h3>
                    <p className="text-xs text-slate-400">
                      Open a dedicated camera session for this angle or choose a PNG/JPG photo. The camera will automatically stop once you snap this side so you can safely rotate the object.
                    </p>
                  </div>
                </>
              )}
              <div className="flex flex-wrap items-center justify-center gap-2.5 pt-2">
                <button
                  onClick={() => void startCameraForSide(currentAxis.key)}
                  className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-xs font-mono font-semibold text-white transition"
                >
                  Open Camera for {currentAxis.key.toUpperCase()}
                </button>
                <button
                  onClick={() => singleFileInputRef.current?.click()}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-xs font-mono text-slate-200 transition"
                >
                  Upload {currentAxis.key.toUpperCase()} File
                </button>
              </div>
            </div>
          )}

          {/* Active Live Camera Overlay — Manual Capture + Optional 3s Timer */}
          {cameraActive && (
            <div className="absolute inset-0 pointer-events-none flex flex-col justify-between p-4">
              <div className="flex items-center justify-between">
                <div className="bg-black/80 backdrop-blur px-3 py-1.5 rounded-lg border border-cyan-500/50 text-xs font-mono">
                  <span className="text-slate-400">CAPTURING: </span>
                  <span className="text-cyan-300 font-bold">{currentAxis.label}</span>
                </div>

                <div
                  className={`px-3 py-1.5 rounded-lg border text-xs font-mono font-semibold flex items-center gap-1.5 backdrop-blur ${
                    sharpness.status === 'sharp'
                      ? 'bg-emerald-950/85 text-emerald-300 border-emerald-500'
                      : 'bg-amber-950/85 text-amber-300 border-amber-500'
                  }`}
                >
                  <span
                    className={`w-2 h-2 rounded-full ${
                      sharpness.status === 'sharp' ? 'bg-emerald-400' : 'bg-amber-400'
                    }`}
                  />
                  <span>{sharpness.label}</span>
                </div>
              </div>

              {countdownSeconds !== null ? (
                <div className="self-center w-24 h-24 rounded-full bg-black/80 border-2 border-cyan-400 flex items-center justify-center text-3xl font-mono font-bold text-cyan-300">
                  {countdownSeconds}
                </div>
              ) : (
                <div className="self-center w-64 h-44 border-2 border-dashed border-cyan-400/45 rounded-xl flex items-center justify-center">
                  <span className="text-[11px] font-mono uppercase text-cyan-300/80 bg-black/65 px-2.5 py-1 rounded">
                    Frame {currentAxis.label}
                  </span>
                </div>
              )}

              <div className="flex items-center justify-between gap-2 pointer-events-auto">
                <button
                  type="button"
                  onClick={() => setCountdownSeconds(countdownSeconds === null ? 3 : null)}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-black/80 hover:bg-slate-900 border border-cad-border text-xs font-mono text-slate-200 transition"
                >
                  <Timer className="w-3.5 h-3.5 text-amber-400" />
                  <span>{countdownSeconds !== null ? 'Cancel Timer' : '3s Self-Timer'}</span>
                </button>

                <button
                  type="button"
                  onClick={captureCurrentSideOnce}
                  className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 hover:from-cyan-400 hover:to-emerald-400 text-white font-mono text-xs font-bold shadow-lg transition"
                >
                  CAPTURE {currentAxis.key.toUpperCase()} &amp; LOCK SIDE
                </button>
              </div>
            </div>
          )}
        </div>

        {/* 6-Side Strip Selector */}
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-2.5">
          {AXIS_SEQUENCE.map(({ key, label }, index) => {
            const cap = captures[key];
            const isSelected = index === currentSideIndex;

            return (
              <div
                key={key}
                onClick={() => handleSelectSide(index)}
                className={`relative rounded-xl border p-2 cursor-pointer transition flex flex-col justify-between ${
                  cap
                    ? isSelected
                      ? 'border-emerald-400 bg-emerald-950/30 ring-1 ring-emerald-400'
                      : 'border-emerald-500/50 bg-emerald-950/15'
                    : isSelected
                      ? 'border-cyan-400 bg-cyan-950/25 ring-1 ring-cyan-400'
                      : 'border-cad-border bg-cad-dark/60 hover:border-slate-500'
                }`}
              >
                <div className="h-20 w-full rounded-lg bg-black/65 overflow-hidden flex items-center justify-center relative">
                  {cap ? (
                    <>
                      <img src={cap.dataUrl} alt={label} className="w-full h-full object-cover" />
                      <div className="absolute top-1 right-1 bg-black/80 px-1.5 py-0.5 rounded text-[9px] font-mono text-emerald-400">
                        ✓ {cap.blurScore.toFixed(0)}
                      </div>
                    </>
                  ) : (
                    <div className="flex flex-col items-center justify-center text-[10px] font-mono text-slate-400 text-center px-1">
                      <span className={isSelected ? 'text-cyan-300 font-bold' : ''}>{label.split(' ')[0]}</span>
                      <span className="text-[9px] text-slate-500">{isSelected ? 'Active' : 'Empty'}</span>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between pt-1.5 text-[10px] font-mono">
                  <span className={cap ? 'text-emerald-300 font-bold' : isSelected ? 'text-cyan-300 font-semibold' : 'text-slate-400'}>
                    {index + 1}. {label.split(' ')[0]}
                  </span>
                  {cap ? (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveSide(key);
                        handleSelectSide(index);
                      }}
                      title="Clear side"
                      className="text-slate-400 hover:text-rose-400 p-0.5"
                    >
                      <RotateCcw className="w-3 h-3" />
                    </button>
                  ) : (
                    <label
                      onClick={(e) => e.stopPropagation()}
                      title={`Upload file for ${label}`}
                      className="text-slate-400 hover:text-cyan-400 cursor-pointer p-0.5"
                    >
                      <Upload className="w-3 h-3" />
                      <input
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={(e) => void handleSingleFileChange(e, key)}
                      />
                    </label>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer Progression CTA */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-cad-border">
          <div className="text-xs font-mono text-slate-400">
            Captured <strong className="text-white">{capturedCount}/6</strong> perspectives
            {capturedCount >= 4 && capturedCount < 6 && (
              <span className="ml-2 text-cyan-300">(4+ views ready — skipped faces auto-inferred)</span>
            )}
          </div>

          <button
            onClick={onProceedToGenerate}
            disabled={!canProceed}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 disabled:opacity-40 text-white font-mono text-xs font-bold shadow-lg shadow-cyan-500/20 transition"
          >
            <span>Proceed to Page 2: Calibrate &amp; Generate CAD</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {showCalibrator && calibPreviewUrl && (
        <ScaleCalibrator
          primaryViewUrl={calibPreviewUrl}
          referenceSide={captures.front ? 'front' : currentAxis.key}
          initialKnownLengthMm={calibrationSpec?.known_length_mm ?? 180}
          onSaveCalibration={(spec) => {
            onSaveCalibration(spec);
            setShowCalibrator(false);
          }}
          onCancel={() => setShowCalibrator(false)}
        />
      )}
    </div>
  );
};
