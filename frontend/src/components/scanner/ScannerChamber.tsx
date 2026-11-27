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
  onAllKeyframesCaptured: (captures: Record<AxisView, KeyframeCapture>, calibration?: CalibrationSpec) => void;
  onLoadDemo: () => void;
}

const AXIS_SEQUENCE: Array<{ key: AxisView; label: string; axis: string; desc: string }> = [
  { key: 'front', label: 'FRONT (+Y)', axis: 'Front Elevation', desc: 'Face primary mechanical features directly' },
  { key: 'back', label: 'BACK (-Y)', axis: 'Rear Elevation', desc: 'Opposing rear face' },
  { key: 'left', label: 'LEFT (-X)', axis: 'Left Profile', desc: 'Left cross-section' },
  { key: 'right', label: 'RIGHT (+X)', axis: 'Right Profile', desc: 'Right cross-section' },
  { key: 'top', label: 'TOP (+Z)', axis: 'Plan View', desc: 'Top view with mounting holes/bores' },
  { key: 'bottom', label: 'BOTTOM (-Z)', axis: 'Base Datum', desc: 'Base surface and bottom cutouts' },
];

export const ScannerChamber: React.FC<ScannerChamberProps> = ({
  onAllKeyframesCaptured,
  onLoadDemo,
}) => {
  const [currentSideIndex, setCurrentSideIndex] = useState<number>(0);
  const [captures, setCaptures] = useState<Partial<Record<AxisView, KeyframeCapture>>>({});
  const [cameraActive, setCameraActive] = useState<boolean>(false);
  const [cameraStatusText, setCameraStatusText] = useState<string>('Ready — Enable Camera or Upload Photos');
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
  const [autoCaptureEnabled, setAutoCaptureEnabled] = useState<boolean>(true);
  const [sharpHoldCounter, setSharpHoldCounter] = useState<number>(0);
  const [showCalibrator, setShowCalibrator] = useState<boolean>(false);
  const [calibrationSpec, setCalibrationSpec] = useState<CalibrationSpec | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const hiddenCanvasRef = useRef<HTMLCanvasElement>(null);
  const singleFileInputRef = useRef<HTMLInputElement>(null);
  const batchFileInputRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafIdRef = useRef<number | null>(null);

  const currentAxis = AXIS_SEQUENCE[currentSideIndex];
  const capturedCount = Object.keys(captures).length;
  const isComplete = capturedCount === 6;

  // Enumerate connected cameras cleanly
  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const list = await navigator.mediaDevices.enumerateDevices();
      setDevices(list.filter((d) => d.kind === 'videoinput'));
    } catch {
      // Ignore permission restriction before grant
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
    setVideoResLabel('');
    setSharpHoldCounter(0);
    setCameraStatusText('Camera Paused');
  }, []);

  // Initialize camera ONLY when explicitly requested or when permission is already granted
  const startCamera = useCallback(
    async (deviceIdOverride?: string) => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setCameraError('Browser MediaDevices API is unavailable in this window (use Upload Photos instead).');
        return;
      }

      stopCamera();
      setCameraError(null);
      setCameraStatusText('Connecting webcam...');

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
          // Graceful fallback if ideal 1080p or facingMode is unsupported on laptop webcam
          stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        }

        streamRef.current = stream;
        const videoEl = videoRef.current;
        if (videoEl) {
          videoEl.srcObject = stream;
          await videoEl.play();
          const track = stream.getVideoTracks()[0];
          const settings = track?.getSettings();
          if (settings?.width && settings?.height) {
            setVideoResLabel(`${settings.width}×${settings.height}`);
          }
          setCameraActive(true);
          setCameraStatusText('LIVE');
          await refreshDevices();
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Camera permission denied or device in use';
        setCameraError(msg);
        setCameraActive(false);
        setCameraStatusText('Camera Offline');
      }
    },
    [selectedDeviceId, stopCamera, refreshDevices]
  );

  // Check camera permission passively on mount: only auto-start if already granted,
  // avoiding unexpected browser permission popups before user clicks Start Live Camera.
  useEffect(() => {
    let cancelled = false;
    const initPassive = async () => {
      await refreshDevices();
      if (navigator.permissions?.query) {
        try {
          const status = await navigator.permissions.query({ name: 'camera' as PermissionName });
          if (!cancelled && status.state === 'granted') {
            await startCamera();
          }
        } catch {
          // Permissions API unsupported in some browsers -> wait for explicit button click
        }
      }
    };
    void initPassive();

    return () => {
      cancelled = true;
      stopCamera();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Uncompressed PNG Keyframe Capture (FR-04)
  const snapKeyframe = useCallback(
    (side: AxisView, blurScore: number) => {
      const video = videoRef.current;
      if (!video || video.readyState < 2) return;

      const snapCanvas = document.createElement('canvas');
      snapCanvas.width = video.videoWidth || 1280;
      snapCanvas.height = video.videoHeight || 720;
      const snapCtx = snapCanvas.getContext('2d');
      if (!snapCtx) return;

      snapCtx.drawImage(video, 0, 0, snapCanvas.width, snapCanvas.height);

      snapCanvas.toBlob((blob) => {
        if (!blob) return;
        const dataUrl = URL.createObjectURL(blob);
        const newCapture: KeyframeCapture = {
          side,
          blob,
          dataUrl,
          blurScore,
          width: snapCanvas.width,
          height: snapCanvas.height,
          timestamp: new Date().toISOString(),
        };

        setCaptures((prev) => {
          const updated = { ...prev, [side]: newCapture };
          if (Object.keys(updated).length === 6) {
            onAllKeyframesCaptured(updated as Record<AxisView, KeyframeCapture>, calibrationSpec || undefined);
          }
          return updated;
        });

        setCurrentSideIndex((prev) => (prev < AXIS_SEQUENCE.length - 1 ? prev + 1 : prev));
      }, 'image/png');
    },
    [onAllKeyframesCaptured, calibrationSpec]
  );

  // Real-Time Sharpness / Blur Evaluation Loop (FR-03)
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
          const result = evaluateSharpness(variance);
          setSharpness(result);

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
        } catch {
          // Ignore frame read errors while stream negotiates resolution
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
  }, [cameraActive, autoCaptureEnabled, currentAxis.key, captures, snapKeyframe]);

  const handleManualSnap = () => {
    snapKeyframe(currentAxis.key, sharpness.score);
  };

  const handleRetake = (index: number) => {
    const targetKey = AXIS_SEQUENCE[index].key;
    setCaptures((prev) => {
      const copy = { ...prev };
      delete copy[targetKey];
      return copy;
    });
    setCurrentSideIndex(index);
  };

  // Explicit single-side photo/file upload with real blur measurement
  const handleSingleFileChange = async (e: React.ChangeEvent<HTMLInputElement>, explicitSide?: AxisView) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;

    const targetSide = explicitSide || currentAxis.key;
    const processed = await analyzeAndConvertImageToPng(file);
    const newCapture: KeyframeCapture = {
      side: targetSide,
      blob: processed.blob,
      dataUrl: processed.dataUrl,
      blurScore: processed.blurScore,
      width: processed.width,
      height: processed.height,
      timestamp: new Date().toISOString(),
    };

    setCaptures((prev) => {
      const updated = { ...prev, [targetSide]: newCapture };
      if (Object.keys(updated).length === 6) {
        onAllKeyframesCaptured(updated as Record<AxisView, KeyframeCapture>, calibrationSpec || undefined);
      }
      return updated;
    });

    if (!explicitSide && currentSideIndex < AXIS_SEQUENCE.length - 1) {
      setCurrentSideIndex((prev) => prev + 1);
    }
  };

  // Batch upload up to 6 photos from computer / phone gallery
  const handleBatchFilesChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []).slice(0, 6);
    e.target.value = '';
    if (files.length === 0) return;

    const processedList = await Promise.all(files.map((f) => analyzeAndConvertImageToPng(f)));
    setCaptures((prev) => {
      const updated = { ...prev };
      const emptySides = AXIS_SEQUENCE.map((a) => a.key).filter((k) => !updated[k]);
      const targets = emptySides.length >= processedList.length ? emptySides : AXIS_SEQUENCE.map((a) => a.key);

      processedList.forEach((proc, idx) => {
        const side = targets[idx];
        if (side) {
          updated[side] = {
            side,
            blob: proc.blob,
            dataUrl: proc.dataUrl,
            blurScore: proc.blurScore,
            width: proc.width,
            height: proc.height,
            timestamp: new Date().toISOString(),
          };
        }
      });

      if (Object.keys(updated).length === 6) {
        onAllKeyframesCaptured(updated as Record<AxisView, KeyframeCapture>, calibrationSpec || undefined);
      }
      return updated;
    });
  };

  return (
    <div className="bg-cad-card border border-cad-border rounded-xl p-4 shadow-xl space-y-4">
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

      {/* Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-cad-border pb-3">
        <div>
          <div className="flex items-center space-x-2">
            <Camera className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold text-white">6-Axis Capture &amp; Upload Studio</h2>
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                cameraActive
                  ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500/60'
                  : 'bg-slate-900 text-slate-400 border-slate-700'
              }`}
            >
              {cameraActive ? `● LIVE ${videoResLabel}` : cameraStatusText}
            </span>
          </div>
          <p className="text-xs text-slate-400">
            Capture live via webcam or upload PNG/JPG photos from your device
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={onLoadDemo}
            className="flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg bg-cyan-950/70 text-cyan-300 border border-cyan-800 hover:bg-cyan-900 transition text-xs font-mono font-medium"
          >
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            <span>Demo Bracket</span>
          </button>

          <button
            onClick={() => setShowCalibrator(true)}
            disabled={!captures.front}
            className={`flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-mono transition ${
              calibrationSpec
                ? 'bg-emerald-950 text-emerald-300 border-emerald-700'
                : 'bg-cad-dark text-slate-300 border-cad-border hover:border-cyan-500 disabled:opacity-40'
            }`}
          >
            <Ruler className="w-3.5 h-3.5" />
            <span>{calibrationSpec ? 'Scale Locked' : 'Calibrate mm'}</span>
          </button>
        </div>
      </div>

      {/* Mode & Upload Action Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 bg-cad-dark/80 p-2 rounded-lg border border-cad-border text-xs font-mono">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => (cameraActive ? stopCamera() : void startCamera())}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md border font-semibold transition ${
              cameraActive
                ? 'bg-rose-950/70 text-rose-300 border-rose-700 hover:bg-rose-900'
                : 'bg-cyan-600 hover:bg-cyan-500 text-white border-cyan-400'
            }`}
          >
            {cameraActive ? <VideoOff className="w-3.5 h-3.5" /> : <Video className="w-3.5 h-3.5" />}
            <span>{cameraActive ? 'Stop Camera' : 'Start Live Camera'}</span>
          </button>

          <button
            onClick={() => singleFileInputRef.current?.click()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-cad-card hover:bg-slate-800 text-slate-200 border border-cad-border transition"
          >
            <Upload className="w-3.5 h-3.5 text-cyan-400" />
            <span>Upload {currentAxis.key.toUpperCase()}</span>
          </button>

          <button
            onClick={() => batchFileInputRef.current?.click()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-cad-card hover:bg-slate-800 text-slate-200 border border-cad-border transition"
          >
            <FolderOpen className="w-3.5 h-3.5 text-amber-400" />
            <span>Batch 6 Photos</span>
          </button>
        </div>

        {devices.length > 1 && (
          <select
            value={selectedDeviceId}
            onChange={(e) => {
              setSelectedDeviceId(e.target.value);
              if (cameraActive) void startCamera(e.target.value);
            }}
            className="bg-cad-card border border-cad-border rounded px-2 py-1 text-[11px] text-slate-300 max-w-[160px]"
          >
            {devices.map((d, i) => (
              <option key={d.deviceId || i} value={d.deviceId}>
                {d.label || `Camera ${i + 1}`}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Camera Viewport: ALWAYS Keep <video> mounted in DOM so videoRef.current is valid! */}
      <div className="relative aspect-video max-h-[340px] w-full bg-black rounded-lg border border-cad-border overflow-hidden flex items-center justify-center">
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          className={cameraActive ? 'w-full h-full object-cover' : 'hidden'}
        />

        {!cameraActive && (
          <div className="text-center p-6 space-y-3">
            {cameraError ? (
              <>
                <AlertCircle className="w-8 h-8 text-amber-400 mx-auto" />
                <p className="text-xs font-mono text-amber-200 max-w-sm mx-auto">{cameraError}</p>
              </>
            ) : (
              <>
                <Camera className="w-8 h-8 text-cyan-400/80 mx-auto" />
                <p className="text-xs font-mono text-slate-300">
                  Target: <strong className="text-cyan-300">{currentAxis.label}</strong> — Start Live Camera or upload photos
                </p>
              </>
            )}
            <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
              <button
                onClick={() => void startCamera()}
                className="px-3.5 py-1.5 rounded bg-cyan-600 hover:bg-cyan-500 text-xs font-mono text-white font-semibold transition"
              >
                Enable Live Camera
              </button>
              <button
                onClick={() => singleFileInputRef.current?.click()}
                className="px-3.5 py-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-600 text-xs font-mono text-slate-200 transition"
              >
                Upload Photo File
              </button>
            </div>
          </div>
        )}

        {/* 6-Axis Orientation Guide Overlay when camera is active */}
        {cameraActive && (
          <div className="absolute inset-0 pointer-events-none flex flex-col justify-between p-3.5">
            <div className="flex items-center justify-between">
              <div className="bg-black/80 backdrop-blur px-3 py-1.5 rounded-lg border border-cyan-500/50 text-xs font-mono">
                <span className="text-slate-400 uppercase">TARGET: </span>
                <span className="text-cyan-300 font-bold">{currentAxis.label}</span>
                <span className="text-[10px] text-slate-400 ml-2">({currentAxis.axis})</span>
              </div>

              <div
                className={`px-3 py-1.5 rounded-lg border text-xs font-mono font-semibold flex items-center space-x-1.5 backdrop-blur ${
                  sharpness.status === 'sharp'
                    ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500'
                    : sharpness.status === 'critical'
                    ? 'bg-rose-950/80 text-rose-300 border-rose-500'
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

            <div className="self-center w-52 h-36 border-2 border-dashed border-cyan-400/40 rounded-xl flex items-center justify-center">
              <span className="text-[10px] font-mono uppercase text-cyan-400/70 bg-black/60 px-2 py-0.5 rounded">
                Align {currentAxis.label}
              </span>
            </div>

            <div className="flex items-center justify-between pointer-events-auto">
              <div className="flex items-center space-x-2">
                <label className="flex items-center space-x-2 text-xs font-mono text-slate-300 bg-black/75 px-2.5 py-1 rounded border border-cad-border cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoCaptureEnabled}
                    onChange={(e) => setAutoCaptureEnabled(e.target.checked)}
                    className="rounded border-slate-700 text-cyan-500 focus:ring-0"
                  />
                  <span>Auto-Snap Sharp</span>
                </label>
                {autoCaptureEnabled && sharpHoldCounter > 0 && (
                  <span className="text-[10px] font-mono text-cyan-400 bg-black/80 px-2 py-1 rounded border border-cyan-800">
                    Locking: {Math.round((sharpHoldCounter / 30) * 100)}%
                  </span>
                )}
                {isComplete && (
                  <span className="text-[10px] font-mono text-emerald-300 bg-emerald-950/80 px-2 py-1 rounded border border-emerald-700 flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> All 6 Ready
                  </span>
                )}
              </div>

              <button
                onClick={handleManualSnap}
                className="px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-mono text-xs font-bold shadow-lg transition"
              >
                SNAP {currentAxis.key.toUpperCase()} (PNG)
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 6-Axis Thumbnail Progress Strip: Clicking tile selects target view ONLY (never hijacks with file popup) */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        {AXIS_SEQUENCE.map(({ key, label }, index) => {
          const capture = captures[key];
          const isSelected = index === currentSideIndex;

          return (
            <div
              key={key}
              onClick={() => setCurrentSideIndex(index)}
              className={`relative rounded-lg border p-1.5 cursor-pointer transition flex flex-col justify-between ${
                capture
                  ? isSelected
                    ? 'border-emerald-400 bg-emerald-950/30 ring-1 ring-emerald-400'
                    : 'border-emerald-500/50 bg-emerald-950/20'
                  : isSelected
                  ? 'border-cyan-400 bg-cyan-950/30 ring-1 ring-cyan-400'
                  : 'border-cad-border bg-cad-dark/50 hover:border-slate-600'
              }`}
            >
              <div className="h-16 w-full rounded bg-black/60 overflow-hidden flex items-center justify-center relative">
                {capture ? (
                  <>
                    <img src={capture.dataUrl} alt={label} className="w-full h-full object-cover" />
                    <div className="absolute top-1 right-1 bg-black/80 px-1 py-0.5 rounded text-[8px] font-mono text-emerald-400">
                      ✓ {capture.blurScore.toFixed(0)}
                    </div>
                  </>
                ) : (
                  <div className="flex flex-col items-center justify-center text-[10px] text-slate-400 font-mono">
                    <span className={isSelected ? 'text-cyan-300 font-bold' : ''}>{label.split(' ')[0]}</span>
                    <span className="text-[8px] text-slate-500">{isSelected ? 'Selected' : 'Tap to aim'}</span>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between pt-1 text-[10px] font-mono">
                <span className={capture ? 'text-emerald-300 font-bold' : isSelected ? 'text-cyan-300' : 'text-slate-400'}>
                  {label.split(' ')[0]}
                </span>
                {capture ? (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRetake(index);
                    }}
                    title="Clear & Retake perspective"
                    className="text-slate-400 hover:text-rose-400"
                  >
                    <RotateCcw className="w-3 h-3" />
                  </button>
                ) : (
                  <label
                    onClick={(e) => e.stopPropagation()}
                    title={`Upload image for ${label}`}
                    className="text-slate-400 hover:text-cyan-400 cursor-pointer"
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
