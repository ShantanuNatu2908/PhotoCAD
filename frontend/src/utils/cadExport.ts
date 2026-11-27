import { API_BASE } from '../services/scanApi';
import type { CadGeneration } from '../types/cad';

export type CadExportFormat = 'step' | 'dxf' | 'stl' | 'py';

function buildParametricDxf(lx: number, wy: number, holeDia: number): string {
  const hx = lx / 2;
  const hy = wy / 2;
  const entities: string[] = [
    '0', 'LWPOLYLINE', '8', 'OUTLINE', '90', '4', '70', '1',
    '10', (-hx).toFixed(4), '20', (-hy).toFixed(4),
    '10', hx.toFixed(4), '20', (-hy).toFixed(4),
    '10', hx.toFixed(4), '20', hy.toFixed(4),
    '10', (-hx).toFixed(4), '20', hy.toFixed(4),
  ];
  if (holeDia > 0.5) {
    entities.push(
      '0', 'CIRCLE', '8', 'FEATURES',
      '10', '0.0', '20', '0.0', '30', '0.0',
      '40', (holeDia / 2).toFixed(4)
    );
  }
  return [
    '0', 'SECTION', '2', 'HEADER',
    '9', '$ACADVER', '1', 'AC1027',
    '9', '$INSUNITS', '70', '4',
    '0', 'ENDSEC',
    '0', 'SECTION', '2', 'ENTITIES',
    ...entities,
    '0', 'ENDSEC',
    '0', 'EOF',
  ].join('\n');
}

function buildFallbackAsciiStl(lx: number, wy: number, hz: number): string {
  const hx = lx / 2;
  const hy = wy / 2;
  const tri = (
    nx: number, ny: number, nz: number,
    a: [number, number, number],
    b: [number, number, number],
    c: [number, number, number]
  ) =>
    `  facet normal ${nx} ${ny} ${nz}\n    outer loop\n` +
    `      vertex ${a[0].toFixed(4)} ${a[1].toFixed(4)} ${a[2].toFixed(4)}\n` +
    `      vertex ${b[0].toFixed(4)} ${b[1].toFixed(4)} ${b[2].toFixed(4)}\n` +
    `      vertex ${c[0].toFixed(4)} ${c[1].toFixed(4)} ${c[2].toFixed(4)}\n` +
    `    endloop\n  endfacet\n`;

  const p000: [number, number, number] = [-hx, -hy, 0];
  const p100: [number, number, number] = [hx, -hy, 0];
  const p110: [number, number, number] = [hx, hy, 0];
  const p010: [number, number, number] = [-hx, hy, 0];
  const p001: [number, number, number] = [-hx, -hy, hz];
  const p101: [number, number, number] = [hx, -hy, hz];
  const p111: [number, number, number] = [hx, hy, hz];
  const p011: [number, number, number] = [-hx, hy, hz];

  return (
    'solid PhotoCAD_Part\n' +
    tri(0, 0, -1, p000, p110, p100) + tri(0, 0, -1, p000, p010, p110) +
    tri(0, 0, 1, p001, p101, p111) + tri(0, 0, 1, p001, p111, p011) +
    tri(0, -1, 0, p000, p100, p101) + tri(0, -1, 0, p000, p101, p001) +
    tri(0, 1, 0, p010, p111, p110) + tri(0, 1, 0, p010, p011, p111) +
    tri(-1, 0, 0, p000, p001, p011) + tri(-1, 0, 0, p000, p011, p010) +
    tri(1, 0, 0, p100, p110, p111) + tri(1, 0, 0, p100, p111, p101) +
    'endsolid PhotoCAD_Part\n'
  );
}

function buildFallbackStep(lx: number, wy: number, hz: number): string {
  const ts = new Date().toISOString();
  return [
    'ISO-10303-21;',
    'HEADER;',
    "FILE_DESCRIPTION(('PhotoCAD 1:1 mm Parametric B-Rep'), '2;1');",
    `FILE_NAME('PhotoCAD_Part.step', '${ts}', ('PhotoCAD'), ('PhotoCAD'), 'PhotoCAD Web', 'PhotoCAD Studio', '');`,
    "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));",
    'ENDSEC;',
    'DATA;',
    `#10 = PRODUCT('PhotoCAD_Part', 'PhotoCAD_Part', 'Envelope ${lx.toFixed(2)}x${wy.toFixed(2)}x${hz.toFixed(2)} mm', (#11));`,
    "#11 = PRODUCT_CONTEXT('',#12,'mechanical');",
    "#12 = APPLICATION_CONTEXT('automotive design');",
    'ENDSEC;',
    'END-ISO-10303-21;',
  ].join('\n');
}

function extractHoleDiameter(code?: string): number {
  if (!code) return 14.0;
  const m = code.match(/HOLE_DIA_MM\s*=\s*(\d+(?:\.\d+)?)|\.hole\(\s*(\d+(?:\.\d+)?)/i);
  if (!m) return 14.0;
  return Number(m[1] || m[2] || 14.0);
}

export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

export async function downloadCadArtifact(
  generation: CadGeneration,
  format: CadExportFormat
): Promise<{ filename: string; source: 'backend' | 'client_fallback' }> {
  const filename = `PhotoCAD_Rev${generation.version}_${generation.id.slice(0, 8)}.${format}`;
  const isRemoteSession = !generation.id.startsWith('demo-');

  if (isRemoteSession) {
    const res = await fetch(`${API_BASE}/export/${generation.id}/${format}`);
    if (res.ok) {
      const blob = await res.blob();
      triggerBlobDownload(blob, filename);
      return { filename, source: 'backend' };
    }
    if (res.status !== 404) {
      throw new Error(`Export failed with HTTP ${res.status}`);
    }
  }

  const lx = generation.dimensions_mm?.x ?? 80.0;
  const wy = generation.dimensions_mm?.y ?? 50.0;
  const hz = generation.dimensions_mm?.z ?? 30.0;
  const holeDia = extractHoleDiameter(generation.code);

  let content = '';
  let mimeType = 'text/plain;charset=utf-8';
  if (format === 'dxf') {
    content = buildParametricDxf(lx, wy, holeDia);
    mimeType = 'application/dxf';
  } else if (format === 'stl') {
    content = buildFallbackAsciiStl(lx, wy, hz);
    mimeType = 'model/stl';
  } else if (format === 'step') {
    content = buildFallbackStep(lx, wy, hz);
    mimeType = 'application/step';
  } else {
    content =
      generation.code ||
      `from build123d import *\n\nLENGTH_MM = ${lx.toFixed(2)}\nWIDTH_MM = ${wy.toFixed(2)}\nTHICKNESS_MM = ${hz.toFixed(2)}\n`;
    mimeType = 'text/x-python';
  }

  triggerBlobDownload(new Blob([content], { type: mimeType }), filename);
  return { filename, source: 'client_fallback' };
}

export function applyClientDemoRefine(
  generation: CadGeneration,
  instruction: string
): { updated: CadGeneration; summary: string } {
  const lower = instruction.toLowerCase();
  const dims = {
    x: generation.dimensions_mm?.x ?? 80,
    y: generation.dimensions_mm?.y ?? 50,
    z: generation.dimensions_mm?.z ?? 30,
  };

  let holeDia = extractHoleDiameter(generation.code);
  let fillet = 2.0;
  let chamfer = 0.0;

  const triple = lower.match(/\b(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)(?:\s*mm\b)?/);
  if (triple) {
    dims.x = Number(triple[1]);
    dims.y = Number(triple[2]);
    dims.z = Number(triple[3]);
  }

  const clauses = lower.split(/(?:[,;]|\.(?!\d)|\band\b)/);
  for (const clause of clauses) {
    const pickNum = () => {
      const toM = clause.match(/\bto\s+(\d+(?:\.\d+)?)(?:\s*mm\b)?/);
      if (toM) return Number(toM[1]);
      const all = [...clause.matchAll(/(\d+(?:\.\d+)?)(?:\s*mm\b)?/g)];
      return all.length ? Number(all[all.length - 1][1]) : null;
    };
    const isRemove = /\b(?:remove|delete|drop|clear|without|no)\b/.test(clause);

    if (/\b(?:hole|holes|bore|diameter|dia)\b/.test(clause)) {
      holeDia = isRemove ? 0 : (pickNum() ?? holeDia);
    }
    if (/\b(?:length|x\s*axis)\b/.test(clause)) {
      dims.x = pickNum() ?? dims.x;
    }
    if (/\b(?:width|y\s*axis)\b/.test(clause)) {
      dims.y = pickNum() ?? dims.y;
    }
    if (/\b(?:thickness|height|depth|z\s*axis)\b/.test(clause)) {
      dims.z = pickNum() ?? dims.z;
    }
    if (/\b(?:fillet|radius)\b/.test(clause)) {
      fillet = isRemove ? 0 : (pickNum() ?? fillet);
    }
    if (/\bchamfer\b/.test(clause)) {
      chamfer = isRemove ? 0 : (pickNum() ?? chamfer);
    }
  }

  const lines = [
    'from build123d import *',
    '',
    `LENGTH_MM = ${dims.x.toFixed(2)}`,
    `WIDTH_MM = ${dims.y.toFixed(2)}`,
    `THICKNESS_MM = ${dims.z.toFixed(2)}`,
    `HOLE_DIA_MM = ${holeDia.toFixed(2)}`,
    ...(chamfer > 0 ? [`CHAMFER_MM = ${chamfer.toFixed(2)}`] : [`FILLET_RADIUS_MM = ${fillet.toFixed(2)}`]),
    '',
    'with BuildPart() as part:',
    '    Box(LENGTH_MM, WIDTH_MM, THICKNESS_MM)',
    ...(holeDia > 0.5 ? ['    Cylinder(radius=HOLE_DIA_MM / 2.0, height=THICKNESS_MM + 2.0, mode=Mode.SUBTRACT)'] : []),
    ...(chamfer > 0.1
      ? ['    chamfer(part.edges().filter_by(Axis.Z), length=CHAMFER_MM)']
      : fillet > 0.1
        ? ['    fillet(part.edges().filter_by(Axis.Z), radius=FILLET_RADIUS_MM)']
        : []),
    'RESULT_PART = part.part',
  ];

  const nextVersion = generation.version + 1;
  return {
    updated: {
      ...generation,
      version: nextVersion,
      dimensions_mm: dims,
      code: lines.join('\n'),
      created_at: new Date().toISOString(),
    },
    summary: `Rev v${nextVersion}: ${dims.x}×${dims.y}×${dims.z} mm • Hole ${holeDia} mm` +
      (chamfer > 0 ? ` • Chamfer ${chamfer} mm` : fillet > 0 ? ` • Fillet ${fillet} mm` : ''),
  };
}
