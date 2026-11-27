import React, { useRef, useState, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Grid, Center, GizmoHelper, GizmoViewport } from '@react-three/drei';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js';
import { Play, Pause, Eye, Grid as GridIcon, Shield, Box, Sparkles } from 'lucide-react';
import type { Open3DGeometryReport } from '../types/cad';

interface CadViewportProps {
  stlUrl?: string;
  plyUrl?: string;
  geometryReport?: Open3DGeometryReport | null;
  dimensions?: { x: number; y: number; z: number };
  unit: string;
}

type RenderLayerMode = 'mesh' | 'cloud' | 'overlay';

// 3D Model Mesh Component (.STL / parametric box fallback)
const ModelMesh: React.FC<{
  stlUrl?: string;
  wireframe: boolean;
  xray: boolean;
  rotating: boolean;
  dimensions?: { x: number; y: number; z: number };
}> = ({ stlUrl, wireframe, xray, rotating, dimensions }) => {
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
      meshRef.current.rotation.y += delta * 0.5;
    }
  });

  if (!geometry) return null;

  return (
    <Center top>
      <mesh ref={meshRef} geometry={geometry} castShadow receiveShadow>
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

// 3D Fused Point Cloud Component (.PLY from Phase 3 Open3D)
const PointCloudMesh: React.FC<{
  plyUrl: string;
  rotating: boolean;
}> = ({ plyUrl, rotating }) => {
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

  return (
    <Center top>
      {/* Rotate -90 deg around X to align CAD +Z-up scan coordinates with Three.js +Y-up stage */}
      <points ref={pointsRef} geometry={geometry} rotation={[-Math.PI / 2, 0, 0]}>
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

  // Auto-switch to point cloud view as soon as Phase 3 .PLY arrives before .STL is compiled
  useEffect(() => {
    if (plyUrl && !stlUrl) {
      setLayerMode('cloud');
    } else if (stlUrl && !plyUrl) {
      setLayerMode('mesh');
    } else if (stlUrl && plyUrl) {
      setLayerMode('overlay');
    }
  }, [plyUrl, stlUrl]);

  const dx = geometryReport?.bounding_box_mm[0] ?? dimensions?.x ?? 60;
  const dy = geometryReport?.bounding_box_mm[1] ?? dimensions?.y ?? 40;
  const dz = geometryReport?.bounding_box_mm[2] ?? dimensions?.z ?? 25;

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
            {dx} × {dy} × {dz} {unit}
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
          </div>
        </div>
      </div>

      {/* 3D Canvas */}
      <div className="flex-1 w-full h-full cursor-grab active:cursor-grabbing">
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
              dimensions={{ x: dx, y: dy, z: dz }}
            />
          )}

          {showCloud && plyUrl && (
            <PointCloudMesh plyUrl={plyUrl} rotating={rotating} />
          )}

          <OrbitControls makeDefault minDistance={20} maxDistance={400} enableDamping dampingFactor={0.05} />

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
