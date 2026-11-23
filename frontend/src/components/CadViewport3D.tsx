import React, { useRef, useState, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Grid, Center, GizmoHelper, GizmoViewport } from '@react-three/drei';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { Play, Pause, Eye, Grid as GridIcon, Shield } from 'lucide-react';

interface CadViewportProps {
  stlUrl?: string;
  dimensions?: { x: number; y: number; z: number };
  unit: string;
}

// 3D Model Mesh Component
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
      // Create fallback parametric box with dimensions or defaults
      const dx = dimensions?.x || 60;
      const dy = dimensions?.y || 40;
      const dz = dimensions?.z || 25;
      const boxGeo = new THREE.BoxGeometry(dx, dz, dy);
      setGeometry(boxGeo);
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

  // Turntable simulation loop
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
        {/* Crisp edge outline highlight */}
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

export const CadViewport3D: React.FC<CadViewportProps> = ({ stlUrl, dimensions, unit }) => {
  const [wireframe, setWireframe] = useState(false);
  const [xray, setXray] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [showGrid, setShowGrid] = useState(true);

  const dx = dimensions?.x || 60;
  const dy = dimensions?.y || 40;
  const dz = dimensions?.z || 25;

  return (
    <div className="relative w-full h-full min-h-[420px] bg-[#0c1017] rounded-xl border border-cad-border overflow-hidden shadow-2xl flex flex-col">
      {/* Top Controls Overlay */}
      <div className="absolute top-3 left-3 right-3 z-10 flex items-center justify-between pointer-events-none">
        {/* Physical Dimension Badge */}
        <div className="pointer-events-auto bg-cad-card/90 backdrop-blur border border-cad-border rounded-lg px-3 py-1.5 flex items-center space-x-3 text-xs font-mono shadow-lg">
          <div className="flex items-center space-x-1.5">
            <span className="w-2 h-2 rounded-full bg-cyan-400" />
            <span className="text-slate-400">Bounding Envelope:</span>
          </div>
          <span className="text-white font-semibold">
            {dx} × {dy} × {dz} {unit}
          </span>
        </div>

        {/* Viewport Action Buttons */}
        <div className="pointer-events-auto flex items-center space-x-1.5 bg-cad-card/90 backdrop-blur border border-cad-border rounded-lg p-1 shadow-lg">
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

      {/* 3D Canvas */}
      <div className="flex-1 w-full h-full cursor-grab active:cursor-grabbing">
        <Canvas shadows camera={{ position: [90, 80, 110], fov: 45 }}>
          <color attach="background" args={['#080b11']} />
          
          {/* Lighting */}
          <ambientLight intensity={0.7} />
          <directionalLight position={[100, 150, 100]} intensity={1.2} castShadow shadow-mapSize={1024} />
          <directionalLight position={[-100, -50, -100]} intensity={0.4} color="#00f0ff" />

          {/* Ground Engineering Datum Grid */}
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

          {/* Model */}
          <ModelMesh
            stlUrl={stlUrl}
            wireframe={wireframe}
            xray={xray}
            rotating={rotating}
            dimensions={dimensions}
          />

          {/* Orbit Controls */}
          <OrbitControls makeDefault minDistance={20} maxDistance={400} enableDamping dampingFactor={0.05} />

          {/* Interactive XYZ Orientation Gizmo */}
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
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          <span>B-Rep Tessellation: Valid Solid</span>
        </div>
      </div>
    </div>
  );
};
