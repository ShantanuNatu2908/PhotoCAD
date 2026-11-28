import { describe, expect, it } from 'vitest';
import {
  DEFAULT_ARUCO_DICTIONARY,
  detectArucoToken,
  detectId1Card,
  detectScaleReference,
} from './scaleDetection';
import type { PixelImage } from './scaleDetection';

function whiteImage(width: number, height: number): { image: PixelImage; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i += 1) {
    data[i * 4] = 255;
    data[i * 4 + 1] = 255;
    data[i * 4 + 2] = 255;
    data[i * 4 + 3] = 255;
  }
  return { image: { width, height, data }, data };
}

function setPixel(data: Uint8ClampedArray, width: number, x: number, y: number): void {
  const index = (y * width + x) * 4;
  data[index] = 0;
  data[index + 1] = 0;
  data[index + 2] = 0;
  data[index + 3] = 255;
}

function drawAxisAlignedFrame(
  target: ReturnType<typeof whiteImage>,
  left: number,
  top: number,
  width: number,
  height: number,
  thickness = 3,
): void {
  for (let y = top; y < top + height; y += 1) {
    for (let x = left; x < left + width; x += 1) {
      const onBorder =
        x - left < thickness || left + width - 1 - x < thickness ||
        y - top < thickness || top + height - 1 - y < thickness;
      if (onBorder) setPixel(target.data, target.image.width, x, y);
    }
  }
}

function drawRotatedFrame(
  target: ReturnType<typeof whiteImage>,
  cx: number,
  cy: number,
  width: number,
  height: number,
  angleRad: number,
  thickness = 3,
): void {
  const cos = Math.cos(angleRad);
  const sin = Math.sin(angleRad);
  for (let y = Math.floor(cy - height); y <= Math.ceil(cy + height); y += 1) {
    for (let x = Math.floor(cx - width); x <= Math.ceil(cx + width); x += 1) {
      if (x < 0 || y < 0 || x >= target.image.width || y >= target.image.height) continue;
      const dx = x - cx;
      const dy = y - cy;
      const u = dx * cos + dy * sin;
      const v = -dx * sin + dy * cos;
      const inside = Math.abs(u) <= width / 2 && Math.abs(v) <= height / 2;
      const nearEdge =
        width / 2 - Math.abs(u) < thickness || height / 2 - Math.abs(v) < thickness;
      if (inside && nearEdge) setPixel(target.data, target.image.width, x, y);
    }
  }
}

function drawFiducial(
  target: ReturnType<typeof whiteImage>,
  bits: number[],
  gridSize: number,
  cellPx: number,
  originX: number,
  originY: number,
): void {
  const side = cellPx * (gridSize + 2);
  for (let y = originY; y < originY + side; y += 1) {
    for (let x = originX; x < originX + side; x += 1) {
      const localX = x - originX;
      const localY = y - originY;
      const onBorder = localX < cellPx || localY < cellPx ||
        localX >= side - cellPx || localY >= side - cellPx;
      let dark = onBorder;
      if (!onBorder) {
        const col = Math.floor((localX - cellPx) / cellPx);
        const row = Math.floor((localY - cellPx) / cellPx);
        dark = bits[row * gridSize + col] === 1;
      }
      if (dark) setPixel(target.data, target.image.width, x, y);
    }
  }
}

describe('ID-1 automatic scale detection', () => {
  it('finds an axis-aligned ID-1 card and computes mm per pixel', () => {
    const target = whiteImage(400, 300);
    drawAxisAlignedFrame(target, 120, 100, 160, 101);
    const found = detectId1Card(target.image);
    expect(found).not.toBeNull();
    expect(found?.mode).toBe('id1_card');
    expect(found?.referenceLengthMm).toBeCloseTo(85.6, 5);
    expect(found?.referencePixels).toBeGreaterThan(150);
    expect(found?.mmPerUnit).toBeCloseTo(85.6 / 160, 2);
    expect(found?.cornersPx).toHaveLength(4);
  });

  it('finds a rotated ID-1 card using its minimum-area rectangle', () => {
    const target = whiteImage(500, 400);
    drawRotatedFrame(target, 250, 200, 170, 107, Math.PI / 9);
    const found = detectId1Card(target.image);
    expect(found).not.toBeNull();
    expect(found?.referenceLengthMm).toBe(85.6);
    expect(found?.mmPerUnit).toBeGreaterThan(0.4);
    expect(found?.mmPerUnit).toBeLessThan(0.6);
  });

  it('rejects a square frame so manual calibration is never overwritten', () => {
    const target = whiteImage(300, 300);
    drawAxisAlignedFrame(target, 100, 100, 100, 100);
    expect(detectId1Card(target.image)).toBeNull();
    expect(detectScaleReference(target.image, 'id1_card')).toBeNull();
  });
});

describe('ArUco fiducial automatic scale detection', () => {
  it('decodes an exact 4x4 dictionary marker and derives 20 mm scale', () => {
    const target = whiteImage(240, 200);
    drawFiducial(target, DEFAULT_ARUCO_DICTIONARY.codes[0], 4, 8, 96, 76);
    const found = detectArucoToken(target.image);
    expect(found).not.toBeNull();
    expect(found?.mode).toBe('aruco_token');
    expect(found?.markerId).toBe(0);
    expect(found?.referenceLengthMm).toBeCloseTo(20, 5);
    expect(found?.mmPerUnit).toBeCloseTo(20 / 48, 3);
    expect(found?.confidence).toBe(1);
  });

  it('rejects an unknown bit pattern with no exact dictionary match', () => {
    const target = whiteImage(240, 200);
    const unknown = DEFAULT_ARUCO_DICTIONARY.codes[0].map((bit) => 1 - bit);
    const isKnown = DEFAULT_ARUCO_DICTIONARY.codes.some(
      (code) => code.every((value, index) => value === unknown[index]),
    );
    expect(isKnown).toBe(false);
    drawFiducial(target, unknown, 4, 8, 96, 76);
    expect(detectArucoToken(target.image)).toBeNull();
  });
});
