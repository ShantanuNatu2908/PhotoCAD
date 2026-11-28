/**
 * PhotoCAD metric scale auto-detection (scale-calibration.skill.md).
 *
 * Pure TypeScript, deterministic detectors for ISO/IEC 7810 ID-1 reference cards
 * and ArUco-style 4x4 square fiducials. Everything is measured in natural image
 * pixels and converted to millimetres via `mm_per_unit` (mm per source pixel).
 *
 * No OpenCV WASM, no model download, no network access. Dark-pixel connected
 * components are used only to locate the reference object — never to reconstruct
 * CAD geometry (AGENTS.md non-negotiable rule 2).
 */

export type PointPx = [number, number];

export type DetectionMode = 'id1_card' | 'aruco_token';

/** Structural subset of ImageData so unit tests can supply plain pixel buffers. */
export interface PixelImage {
  width: number;
  height: number;
  data: Uint8ClampedArray | Uint8Array;
}

export interface DetectedReference {
  mode: DetectionMode;
  /** Four image-space corners; the first two span the measured reference length. */
  cornersPx: [PointPx, PointPx, PointPx, PointPx];
  /** Physical length between cornersPx[0] and cornersPx[1], always millimetres. */
  referenceLengthMm: number;
  /** Distance in natural pixels between the same two corners. */
  referencePixels: number;
  /** Millimetres per natural image pixel (1:1 metric grounding). */
  mmPerUnit: number;
  /** 0..1 detection confidence; exact fiducial matches score 1. */
  confidence: number;
  /** Resolved fiducial identifier, when a dictionary match succeeded. */
  markerId?: number;
}

interface Component {
  pixels: number[];
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  count: number;
}

interface MinAreaRect {
  corners: [PointPx, PointPx, PointPx, PointPx];
  width: number;
  height: number;
  area: number;
}

export interface ArucoDictionary {
  gridSize: number;
  codes: number[][];
}

const ID1_LONG_MM = 85.6;
const ID1_SHORT_MM = 53.98;
const ID1_ASPECT = ID1_LONG_MM / ID1_SHORT_MM;
const ID1_ASPECT_TOLERANCE = 0.08;
const DEFAULT_DARK_THRESHOLD = 110;
const DEFAULT_ARUCO_MM = 20.0;
const MIN_CARD_SHORT_PX = 12;
const MIN_MARKER_SIDE_PX = 12;

function luminance(image: PixelImage, x: number, y: number): number {
  const index = (y * image.width + x) * 4;
  return 0.299 * image.data[index] + 0.587 * image.data[index + 1] + 0.114 * image.data[index + 2];
}

function buildDarkMask(image: PixelImage, threshold: number): Uint8Array {
  const mask = new Uint8Array(image.width * image.height);
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      if (luminance(image, x, y) < threshold) mask[y * image.width + x] = 1;
    }
  }
  return mask;
}

/** 8-connected component scan; returns components ordered by pixel count. */
function connectedComponents(mask: Uint8Array, width: number, height: number): Component[] {
  const visited = new Uint8Array(mask.length);
  const result: Component[] = [];
  const stack: number[] = [];

  for (let start = 0; start < mask.length; start += 1) {
    if (!mask[start] || visited[start]) continue;
    stack.length = 0;
    stack.push(start);
    visited[start] = 1;
    const pixels: number[] = [];
    let minX = width;
    let maxX = 0;
    let minY = height;
    let maxY = 0;

    while (stack.length > 0) {
      const index = stack.pop() as number;
      const x = index % width;
      const y = Math.floor(index / width);
      pixels.push(index);
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;

      for (let dy = -1; dy <= 1; dy += 1) {
        const ny = y + dy;
        if (ny < 0 || ny >= height) continue;
        for (let dx = -1; dx <= 1; dx += 1) {
          const nx = x + dx;
          if (nx < 0 || nx >= width) continue;
          const nIndex = ny * width + nx;
          if (mask[nIndex] && !visited[nIndex]) {
            visited[nIndex] = 1;
            stack.push(nIndex);
          }
        }
      }
    }

    result.push({ pixels, minX, maxX, minY, maxY, count: pixels.length });
  }

  result.sort((a, b) => b.count - a.count);
  return result;
}

function cross(o: PointPx, a: PointPx, b: PointPx): number {
  return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
}

/** Andrew's monotone chain convex hull. */
export function convexHull(points: PointPx[]): PointPx[] {
  if (points.length < 3) return points.slice();
  const sorted = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const lower: PointPx[] = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], point) <= 0) {
      lower.pop();
    }
    lower.push(point);
  }
  const upper: PointPx[] = [];
  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    const point = sorted[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], point) <= 0) {
      upper.pop();
    }
    upper.push(point);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

/** Minimum-area enclosing rectangle via rotating calipers over hull edges. */
export function minAreaRect(hull: PointPx[]): MinAreaRect | null {
  if (hull.length < 3) return null;
  let best: MinAreaRect | null = null;

  for (let i = 0; i < hull.length; i += 1) {
    const p = hull[i];
    const q = hull[(i + 1) % hull.length];
    const dx = q[0] - p[0];
    const dy = q[1] - p[1];
    const length = Math.hypot(dx, dy);
    if (length < 1e-6) continue;
    const ux = dx / length;
    const uy = dy / length;
    const vx = -uy;
    const vy = ux;

    let minU = Infinity;
    let maxU = -Infinity;
    let minV = Infinity;
    let maxV = -Infinity;
    for (const point of hull) {
      const u = point[0] * ux + point[1] * uy;
      const v = point[0] * vx + point[1] * vy;
      if (u < minU) minU = u;
      if (u > maxU) maxU = u;
      if (v < minV) minV = v;
      if (v > maxV) maxV = v;
    }

    const width = maxU - minU;
    const height = maxV - minV;
    const area = width * height;
    if (area <= 0) continue;
    if (best === null || area < best.area) {
      const toPoint = (u: number, v: number): PointPx => [u * ux + v * vx, u * uy + v * vy];
      best = {
        corners: [toPoint(minU, minV), toPoint(maxU, minV), toPoint(maxU, maxV), toPoint(minU, maxV)],
        width,
        height,
        area,
      };
    }
  }
  return best;
}

function orderByLongSide(rect: MinAreaRect): [PointPx, PointPx, PointPx, PointPx] {
  const [a, b, c, d] = rect.corners;
  if (rect.width >= rect.height) return [a, b, c, d];
  return [b, c, d, a];
}

function hamming(a: number[], b: number[]): number {
  let distance = 0;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) distance += 1;
  }
  return distance;
}

/**
 * Deterministic ArUco-compatible 4x4 dictionary with corner-orientation bits
 * fixed (top-left = 1, other corners = 0) and pairwise Hamming distance >= 3.
 * Standard dictionaries can be injected via `detectArucoToken(image, dictionary)`.
 */
export function generateArucoDictionary(count = 12, gridSize = 4): ArucoDictionary {
  const codes: number[][] = [];
  const total = gridSize * gridSize;
  const corners = new Set([0, gridSize - 1, total - 1, total - gridSize]);
  let state = 0x9e3779b9;

  const nextBit = (): number => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return (state >>> 16) & 1;
  };

  while (codes.length < count) {
    const code = new Array<number>(total).fill(0);
    code[0] = 1;
    for (const index of corners) code[index] = index === 0 ? 1 : 0;
    for (let i = 0; i < total; i += 1) {
      if (!corners.has(i)) code[i] = nextBit();
    }
    if (codes.every((existing) => hamming(existing, code) >= 3)) codes.push(code);
  }
  return { gridSize, codes };
}

export const DEFAULT_ARUCO_DICTIONARY: ArucoDictionary = generateArucoDictionary();

function rotateBits(bits: number[], gridSize: number, quarterTurns: number): number[] {
  let result = bits.slice();
  for (let turn = 0; turn < quarterTurns; turn += 1) {
    const next = new Array<number>(bits.length);
    for (let row = 0; row < gridSize; row += 1) {
      for (let col = 0; col < gridSize; col += 1) {
        next[row * gridSize + col] = result[(gridSize - 1 - col) * gridSize + row];
      }
    }
    result = next;
  }
  return result;
}

function sampleMarkerGrid(
  image: PixelImage,
  component: Component,
  gridSize: number,
  threshold: number,
): number[] | null {
  const side = Math.min(component.maxX - component.minX + 1, component.maxY - component.minY + 1);
  if (side < MIN_MARKER_SIDE_PX) return null;
  const border = Math.max(2, Math.round(side / (gridSize + 2)));
  const innerMinX = component.minX + border;
  const innerMaxX = component.maxX - border;
  const innerMinY = component.minY + border;
  const innerMaxY = component.maxY - border;
  if (innerMaxX <= innerMinX || innerMaxY <= innerMinY) return null;

  const cellWidth = (innerMaxX - innerMinX + 1) / gridSize;
  const cellHeight = (innerMaxY - innerMinY + 1) / gridSize;
  const bits: number[] = [];
  for (let row = 0; row < gridSize; row += 1) {
    for (let col = 0; col < gridSize; col += 1) {
      const x = Math.min(image.width - 1, Math.floor(innerMinX + (col + 0.5) * cellWidth));
      const y = Math.min(image.height - 1, Math.floor(innerMinY + (row + 0.5) * cellHeight));
      bits.push(luminance(image, x, y) < threshold ? 1 : 0);
    }
  }
  return bits;
}

/** Requires a light quiet zone around the black fiducial border. */
function hasQuietZone(image: PixelImage, component: Component, threshold: number): boolean {
  const ring = Math.max(1, Math.round(Math.min(
    component.maxX - component.minX + 1,
    component.maxY - component.minY + 1,
  ) / 8));
  let dark = 0;
  let sampled = 0;
  for (let y = component.minY - ring; y <= component.maxY + ring; y += 1) {
    if (y < 0 || y >= image.height) continue;
    for (let x = component.minX - ring; x <= component.maxX + ring; x += 1) {
      if (x < 0 || x >= image.width) continue;
      if (x >= component.minX && x <= component.maxX && y >= component.minY && y <= component.maxY) continue;
      sampled += 1;
      if (luminance(image, x, y) < threshold) dark += 1;
    }
  }
  return sampled > 0 && dark / sampled < 0.25;
}

function squareCorners(component: Component): [PointPx, PointPx, PointPx, PointPx] {
  return [
    [component.minX, component.minY],
    [component.maxX, component.minY],
    [component.maxX, component.maxY],
    [component.minX, component.maxY],
  ];
}

/** Detects a single ISO/IEC 7810 ID-1 card and returns its long edge as scale reference. */
export function detectId1Card(
  image: PixelImage,
  threshold = DEFAULT_DARK_THRESHOLD,
): DetectedReference | null {
  const mask = buildDarkMask(image, threshold);
  const totalPixels = image.width * image.height;
  for (const component of connectedComponents(mask, image.width, image.height)) {
    const bboxArea = (component.maxX - component.minX + 1) * (component.maxY - component.minY + 1);
    if (bboxArea < totalPixels * 0.005) continue;
    // A rotated thin card border fills only ~3% of its axis-aligned bounding box.
    if (component.count / bboxArea < 0.025) continue;

    const hull = convexHull(component.pixels.map((index) => [
      index % image.width,
      Math.floor(index / image.width),
    ] as PointPx));
    const rect = minAreaRect(hull);
    if (!rect) continue;
    const longSide = Math.max(rect.width, rect.height);
    const shortSide = Math.min(rect.width, rect.height);
    if (shortSide < MIN_CARD_SHORT_PX || longSide < MIN_CARD_SHORT_PX * 1.5) continue;

    const aspect = longSide / shortSide;
    const aspectError = Math.abs(aspect / ID1_ASPECT - 1);
    if (aspectError > ID1_ASPECT_TOLERANCE) continue;

    return {
      mode: 'id1_card',
      cornersPx: orderByLongSide(rect),
      referenceLengthMm: ID1_LONG_MM,
      referencePixels: longSide,
      mmPerUnit: ID1_LONG_MM / longSide,
      confidence: Math.max(0, 1 - aspectError / ID1_ASPECT_TOLERANCE),
    };
  }
  return null;
}

/**
 * Detects one ArUco-style square fiducial by exact Hamming match against a
 * dictionary (4 rotations accepted). `markerLengthMm` defaults to 20 mm.
 */
export function detectArucoToken(
  image: PixelImage,
  dictionary: ArucoDictionary = DEFAULT_ARUCO_DICTIONARY,
  threshold = DEFAULT_DARK_THRESHOLD,
  markerLengthMm = DEFAULT_ARUCO_MM,
): DetectedReference | null {
  const mask = buildDarkMask(image, threshold);
  for (const component of connectedComponents(mask, image.width, image.height)) {
    const width = component.maxX - component.minX + 1;
    const height = component.maxY - component.minY + 1;
    const side = Math.min(width, height);
    if (side < MIN_MARKER_SIDE_PX || width / height < 0.75 || width / height > 1.3) continue;
    if (!hasQuietZone(image, component, threshold)) continue;

    const bits = sampleMarkerGrid(image, component, dictionary.gridSize, threshold);
    if (!bits) continue;

    let matchedId: number | undefined;
    for (let id = 0; id < dictionary.codes.length && matchedId === undefined; id += 1) {
      for (let rotation = 0; rotation < 4; rotation += 1) {
        if (hamming(bits, rotateBits(dictionary.codes[id], dictionary.gridSize, rotation)) === 0) {
          matchedId = id;
          break;
        }
      }
    }
    if (matchedId === undefined) continue;

    const referencePixels = (width + height) / 2;
    return {
      mode: 'aruco_token',
      cornersPx: squareCorners(component),
      referenceLengthMm: markerLengthMm,
      referencePixels,
      mmPerUnit: markerLengthMm / referencePixels,
      confidence: 1,
      markerId: matchedId,
    };
  }
  return null;
}

/** Convenience entry point used by the calibration modal. */
export function detectScaleReference(
  image: PixelImage,
  mode: DetectionMode,
  dictionary: ArucoDictionary = DEFAULT_ARUCO_DICTIONARY,
): DetectedReference | null {
  return mode === 'id1_card' ? detectId1Card(image) : detectArucoToken(image, dictionary);
}
