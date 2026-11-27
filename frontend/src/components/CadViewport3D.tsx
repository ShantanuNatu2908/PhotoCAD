import React, { useRef, useState, useEffect, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { OrbitControls, Grid, Center, GizmoHelper, GizmoViewport } from '@react-three/drei';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js';
import { Play, Pause, Eye, Grid as GridIcon, Shield, Box, Sparkles, Ruler, RotateCcw, X } from 'lucide-react';
import type { Open3DGeometryReport } from '../types/cad';

interface CadViewportProps {
  stlUrl?: string;
  plyUrl?: string;
  geometryReport?: Open3DGeometryReport | null;
  dimensions?: { x: number; y: number; z: number };
  unit: string;
}

type RenderLayerMode = 'mesh' | 'cloud' | 'overlay';
type Point3D = [number, number, number];

const ModelMesh: React.FC<{
  stlUrl?: string;
  wireframe: boolean;
  xray: boolean;
  rotating: boolean;
  dimensions?: { x: number; y: number; z: number };
  measureMode: boolean;
  onMeasurePick: (pt: Point3D) => void;
}> = ({ stlUrl, wireframe, xray, rotating, dimensions, measureMode, onMeasurePick }) => {
  const meshRef = useRef<THREE.Mesh>(null);
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    if (!stlUrl) {
      const dx = dimensions?.x || 60;
      const dy = dimensions?.y || 40;
      const dz = dimensions?.z || 25;
      setGeometry(new THREE.BoxGeometry(dx, dz, dy));
      return;
    }

    const loader = new STLLoader();
    loader.load(
      stlUrl,
      (geo) => {
        geo.computeVertexNormals();
        geo.center();
        setGeometry(geo);
      },
      undefined,
      (err) => {
        console.warn('Could not load STL, using parametric fallback geometry', err);
        const dx = dimensions?.x || 60;
        const dy = dimensions?.y || 40;
        const dz = dimensions?.z || 25;
        setGeometry(new THREE.BoxGeometry(dx, dz, dy));
      }
    );
  }, [stlUrl, dimensions]);

  useFrame((_, delta) => {
    if (rotating && meshRef.current) {
      if (stlUrl) {
        meshRef.current.rotation.z += delta * 0.5;
      } else {
        meshRef.current.rotation.y += delta * 0.5;
      }
    }
  });

  if (!geometry) return null;

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (!measureMode) return;
    e.stopPropagation();
    onMeasurePick([e.point.x, e.point.y, e.point.z]);
  };

  return (
    <Center top>
      <mesh
        ref={meshRef}
        geometry={geometry}
        rotation={stlUrl ? [-Math.PI / 2, 0, 0] : [0, 0, 0]}
        onClick={handleClick}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          color={xray ? '#00f0ff' : '#00adb5'}
          roughness={0.25}
          metalness={0.65}
          wireframe={wireframe}
          transparent={xray}
          opacity={xray ? 0.45 : 1.0}
        />
        {!wireframe && !xray && (
          <lineSegments>
            <edgesGeometry attach="geometry" args={[geometry]} />
            <lineBasicMaterial attach="material" color="#ffffff" linewidth={1.5} opacity={0.3} transparent />
          </lineSegments>
        )}
      </mesh>
    </Center>
  );
};

const PointCloudMesh: React.FC<{
  plyUrl: string;
  rotating: boolean;
  measureMode: boolean;
  onMeasurePick: (pt: Point3D) => void;
}> = ({ plyUrl, rotating, measureMode, onMeasurePick }) => {
  const pointsRef = useRef<THREE.Points>(null);
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    const loader = new PLYLoader();
    loader.load(
      plyUrl,
      (geo) => {
        geo.center();
        setGeometry(geo);
      },
      undefined,
      (err) => {
        console.warn('Failed to load PLY point cloud:', err);
      }
    );
  }, [plyUrl]);

  useFrame((_, delta) => {
    if (rotating && pointsRef.current) {
      pointsRef.current.rotation.z += delta * 0.5;
    }
  });

  if (!geometry) return null;

  const hasVertexColors = Boolean(geometry.getAttribute('color'));

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (!measureMode) return;
    e.stopPropagation();
    onMeasurePick([e.point.x, e.point.y, e.point.z]);
  };

  return (
    <Center top>
      <points ref={pointsRef} geometry={geometry} rotation={[-Math.PI / 2, 0, 0]} onClick={handleClick}>
        <pointsMaterial
          size={1.65}
          sizeAttenuation
          vertexColors={hasVertexColors}
          color={hasVertexColors ? '#ffffff' : '#00f0ff'}
          transparent
          opacity={0.95}
        />
      </points>
    </Center>
  );
};

const MeasurementOverlay3D: React.FC<{ points: Point3D[] }> = ({ points }) => {
  const lineGeometry = useMemo(() => {
    if (points.length !== 2) return null;
    const geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...points[0]),
      new THREE.Vector3(...points[1]),
    ]);
    return geo;
  }, [points]);

  return (
    <group>
      {points.map((pt, idx) => (
        <mesh key={idx} position={pt}>
          <sphereGeometry args={[1.4, 16, 16]} />
          <meshBasicMaterial color={idx === 0 ? '#34d399' : '#22d3ee'} />
        </mesh>
      ))}
      {lineGeometry && (
        <lineSegments geometry={lineGeometry}>
          <lineBasicMaterial color="#fde047" linewidth={2} />
        </lineSegments>
      )}
    </group>
  );
};

export const CadViewport3D: React.FC<CadViewportProps> = ({
  stlUrl,
  plyUrl,
  geometryReport,
  dimensions,
  unit,
}) => {
  const [wireframe, setWireframe] = useState(false);
  const [xray, setXray] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [layerMode, setLayerMode] = useState<RenderLayerMode>('mesh');
  const [measureMode, setMeasureMode] = useState(false);
  const [measurePoints, setMeasurePoints] = useState<Point3D[]>([]);

  const controlsRef = useRef<{ reset: () => void } | null>(null);

  useEffect(() => {
    if (plyUrl && !stlUrl) {
      setLayerMode('cloud');
    } else if (stlUrl && !plyUrl) {
      setLayerMode('mesh');
    } else if (stlUrl && plyUrl) {
      setLayerMode('overlay');
    }
  }, [plyUrl, stlUrl]);

  const rawDx = geometryReport?.bounding_box_mm[0] ?? dimensions?.x ?? 60;
  const rawDy = geometryReport?.bounding_box_mm[1] ?? dimensions?.y ?? 40;
  const rawDz = geometryReport?.bounding_box_mm[2] ?? dimensions?.z ?? 25;

  const scaleFactor = unit === 'inch' ? 1.0 / 25.4 : 1.0;
  const decimals = unit === 'inch' ? 3 : 1;
  const fmtDim = (mm: number) => (mm * scaleFactor).toFixed(decimals);

  const handleMeasurePick = (pt: Point3D) => {
    setMeasurePoints((prev) => (prev.length >= 2 ? [pt] : [...prev, pt]));
  };

  const measuredMm = useMemo(() => {
    if (measurePoints.length !== 2) return null;
    const [a, b] = measurePoints;
    return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  }, [measurePoints]);

  const showMesh = layerMode === 'mesh' || layerMode === 'overlay';
  const showCloud = Boolean(plyUrl) && (layerMode === 'cloud' || layerMode === 'overlay');

  return (
    <div className="relative w-full h-full min-h-[420px] bg-[#0c1017] rounded-xl border border-cad-border overflow-hidden shadow-2xl flex flex-col">
      {/* Top Controls Overlay */}
      <div className="absolute top-3 left-3 right-3 z-10 flex flex-wrap items-center justify-between gap-2 pointer-events-none">
        {/* Physical Dimension & Open3D Telemetry Badge */}
        <div className="pointer-events-auto bg-cad-card/90 backdrop-blur border border-cad-border rounded-lg px-3 py-1.5 flex items-center space-x-3 text-xs font-mono shadow-lg">
          <div className="flex items-center space-x-1.5">
            <span className={`w-2 h-2 rounded-full ${plyUrl ? 'bg-emerald-400' : 'bg-cyan-400'}`} />
            <span className="text-slate-400">Envelope:</span>
          </div>
          <span className="text-white font-semibold">
            {fmtDim(rawDx)} × {fmtDim(rawDy)} × {fmtDim(rawDz)} {unit}
          </span>
          {geometryReport && (
            <span className="hidden sm:inline-block pl-2 border-l border-cad-border text-[11px] text-emerald-300">
              {geometryReport.point_count.toLocaleString()} pts • ICP {(geometryReport.icp_fitness_score * 100).toFixed(0)}%
            </span>
          )}
        </div>

        {/* Layer Switcher + Viewport Action Buttons */}
        <div className="pointer-events-auto flex items-center space-x-1.5">
          {plyUrl && (
            <div className="flex items-center bg-cad-card/90 backdrop-blur border border-cad-border rounded-lg p-1 text-[11px] font-mono shadow-lg">
              <button
                onClick={() => setLayerMode('cloud')}
                className={`px-2 py-1 rounded flex items-center gap-1 transition ${
                  layerMode === 'cloud' ? 'bg-cyan-500/25 text-cyan-300 font-semibold' : 'text-slate-400 hover:text-white'
                }`}
              >
                <Sparkles className="w-3 h-3" />
                <span>.PLY Cloud</span>
              </button>
              <button
                onClick={() => setLayerMode('mesh')}
                className={`px-2 py-1 rounded flex items-center gap-1 transition ${
                  layerMode === 'mesh' ? 'bg-cyan-500/25 text-cyan-300 font-semibold' : 'text-slate-400 hover:text-white'
                }`}
              >
                <Box className="w-3 h-3" />
                <span>Solid</span>
              </button>
              {stlUrl && (
                <button
                  onClick={() => setLayerMode('overlay')}
                  className={`px-2 py-1 rounded transition ${
                    layerMode === 'overlay' ? 'bg-emerald-500/25 text-emerald-300 font-semibold' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Overlay
                </button>
              )}
            </div>
          )}

          <div className="flex items-center space-x-1 bg-cad-card/90 backdrop-blur border border-cad-border rounded-lg p-1 shadow-lg">
            <button
              onClick={() => {
                setMeasureMode(!measureMode);
                if (measureMode) setMeasurePoints([]);
              }}
              title="3D Point-to-Point Tape Measure (Click A & B on model)"
              className={`p-1.5 rounded transition ${measureMode ? 'bg-amber-500/25 text-amber-300 ring-1 ring-amber-400' : 'text-slate-400 hover:text-white'}`}
            >
              <Ruler className="w-4 h-4" />
            </button>
            <button
              onClick={() => setRotating(!rotating)}
              title={rotating ? 'Pause Turntable' : 'Simulate Turntable Rotation'}
              className={`p-1.5 rounded transition ${rotating ? 'bg-cyan-500/20 text-cyan-400' : 'text-slate-400 hover:text-white'}`}
            >
              {rotating ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
            </button>
            <button
              onClick={() => setWireframe(!wireframe)}
              title="Toggle Wireframe Cage"
              className={`p-1.5 rounded transition ${wireframe ? 'bg-cyan-500/20 text-cyan-400' : 'text-slate-400 hover:text-white'}`}
            >
              <GridIcon className="w-4 h-4" />
            </button>
            <button
              onClick={() => setXray(!xray)}
              title="Toggle X-Ray / Transparent Mode"
              className={`p-1.5 rounded transition ${xray ? 'bg-cyan-500/20 text-cyan-400' : 'text-slate-400 hover:text-white'}`}
            >
              <Eye className="w-4 h-4" />
            </button>
            <button
              onClick={() => setShowGrid(!showGrid)}
              title="Toggle Datum Ground Grid"
              className={`p-1.5 rounded transition ${showGrid ? 'bg-cyan-500/20 text-cyan-400' : 'text-slate-400 hover:text-white'}`}
            >
              <Shield className="w-4 h-4" />
            </button>
            <button
              onClick={() => controlsRef.current?.reset()}
              title="Reset 3D Camera View"
              className="p-1.5 rounded text-slate-400 hover:text-white transition"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Floating 3D Measurement HUD */}
      {measureMode && (
        <div className="absolute top-14 left-3 z-10 pointer-events-auto bg-amber-950/90 backdrop-blur border border-amber-500/60 rounded-lg px-3 py-1.5 flex items-center space-x-3 text-xs font-mono text-amber-200 shadow-lg">
          <Ruler className="w-3.5 h-3.5 text-amber-400" />
          {measuredMm !== null ? (
            <span>
              Distance: <strong className="text-white">{(measuredMm * scaleFactor).toFixed(2)} {unit}</strong>
              {unit === 'mm' ? ` (${(measuredMm / 25.4).toFixed(3)} in)` : ` (${measuredMm.toFixed(2)} mm)`}
            </span>
          ) : (
            <span>
              {measurePoints.length === 0 ? 'Click Point A on 3D surface' : 'Click Point B to measure'}
            </span>
          )}
          {measurePoints.length > 0 && (
            <button
              onClick={() => setMeasurePoints([])}
              title="Clear pins"
              className="text-amber-300 hover:text-white"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* 3D Canvas */}
      <div className={`flex-1 w-full h-full ${measureMode ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing'}`}>
        <Canvas shadows camera={{ position: [90, 80, 110], fov: 45 }}>
          <color attach="background" args={['#080b11']} />

          <ambientLight intensity={0.7} />
          <directionalLight position={[100, 150, 100]} intensity={1.2} castShadow shadow-mapSize={1024} />
          <directionalLight position={[-100, -50, -100]} intensity={0.4} color="#00f0ff" />

          {showGrid && (
            <Grid
              renderOrder={-1}
              position={[0, -0.01, 0]}
              infiniteGrid
              cellSize={10}
              cellThickness={0.8}
              cellColor="#1a2333"
              sectionSize={50}
              sectionThickness={1.2}
              sectionColor="#2a3b54"
              fadeDistance={400}
            />
          )}

          {showMesh && (
            <ModelMesh
              stlUrl={stlUrl}
              wireframe={wireframe}
              xray={layerMode === 'overlay' ? true : xray}
              rotating={rotating}
              dimensions={{ x: rawDx, y: rawDy, z: rawDz }}
              measureMode={measureMode}
              onMeasurePick={handleMeasurePick}
            />
          )}

          {showCloud && plyUrl && (
            <PointCloudMesh
              plyUrl={plyUrl}
              rotating={rotating}
              measureMode={measureMode}
              onMeasurePick={handleMeasurePick}
            />
          )}

          {measurePoints.length > 0 && <MeasurementOverlay3D points={measurePoints} />}

          <OrbitControls
            ref={(ctrl) => {
              controlsRef.current = ctrl;
            }}
            makeDefault
            minDistance={20}
            maxDistance={400}
            enableDamping
            dampingFactor={0.05}
          />

          <GizmoHelper alignment="bottom-right" margin={[70, 70]}>
            <GizmoViewport axisColors={['#ff3366', '#33cc66', '#3399ff']} labelColor="#ffffff" />
          </GizmoHelper>
        </Canvas>
      </div>

      {/* Bottom Status Bar */}
      <div className="bg-cad-dark px-4 py-2 border-t border-cad-border flex items-center justify-between text-[11px] font-mono text-slate-400">
        <div className="flex items-center space-x-4">
          <span>Camera: Orbit & Pan (RMB / MMB)</span>
          <span>Zoom: Scroll Wheel</span>
        </div>
        <div className="flex items-center space-x-2">
          <span className={`w-1.5 h-1.5 rounded-full ${plyUrl || stlUrl ? 'bg-emerald-400' : 'bg-cyan-400'}`} />
          <span>
            {layerMode === 'cloud' && plyUrl
              ? 'Open3D 6-View Fused .PLY Point Cloud (1:1 mm)'
              : layerMode === 'overlay'
              ? 'Overlay: B-Rep Solid + Fused Point Cloud'
              : 'B-Rep Tessellation: Valid Solid'}
          </span>
        </div>
      </div>
    </div>
  );
};
