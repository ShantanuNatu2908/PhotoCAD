/**
 * PhotoCAD - Laplacian Variance Blur Detection Engine
 * Document ID: PCAD-PRD-SRS-001 (FR-03) & PCAD-SAD-002
 *
 * Computes edge frequency variance using a 2D discrete Laplacian kernel:
 *   [ 0  1  0 ]
 *   [ 1 -4  1 ]
 *   [ 0  1  0 ]
 *
 * High variance (> 120.0) = Sharp, high-frequency mechanical edges.
 * Low variance (< 120.0)  = Motion blur / out-of-focus handheld capture.
 */

export interface SharpnessResult {
  score: number;
  isSharp: boolean;
  status: 'sharp' | 'blurry' | 'critical';
  label: string;
}

export const SHARPNESS_THRESHOLD = 120.0;
export const CRITICAL_THRESHOLD = 60.0;

/**
 * Computes the variance of the Laplacian from raw Canvas ImageData.
 * Downsamples large frames to 320x240 for 30+ FPS real-time camera evaluation.
 */
export function computeLaplacianVariance(imageData: ImageData): number {
  const { width, height, data } = imageData;
  const pixelCount = width * height;

  if (pixelCount === 0 || width < 3 || height < 3) {
    return 0.0;
  }

  // 1. Convert RGBA to Grayscale Luminance (Rec. 601 standard)
  const gray = new Float32Array(pixelCount);
  for (let i = 0, j = 0; i < data.length; i += 4, j++) {
    gray[j] = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  }

  // 2. Convolve with 3x3 discrete Laplacian operator
  let sum = 0.0;
  let sumSq = 0.0;
  let count = 0;

  // Process inner pixels (ignoring 1px border for kernel boundary)
  for (let y = 1; y < height - 1; y++) {
    const rowOffset = y * width;
    const rowAbove = (y - 1) * width;
    const rowBelow = (y + 1) * width;

    for (let x = 1; x < width - 1; x++) {
      const center = gray[rowOffset + x];
      const top = gray[rowAbove + x];
      const bottom = gray[rowBelow + x];
      const left = gray[rowOffset + x - 1];
      const right = gray[rowOffset + x + 1];

      // Discrete Laplacian: L = (top + bottom + left + right) - 4 * center
      const lap = (top + bottom + left + right) - 4.0 * center;

      sum += lap;
      sumSq += lap * lap;
      count++;
    }
  }

  if (count === 0) return 0.0;

  // 3. Compute variance: Var = E[X^2] - (E[X])^2
  const mean = sum / count;
  const variance = (sumSq / count) - (mean * mean);

  return Math.max(0.0, Math.round(variance * 10) / 10);
}

/**
 * Evaluates whether a frame meets the sharpness criteria for uncompressed keyframe capture.
 */
export function evaluateSharpness(
  variance: number,
  threshold: number = SHARPNESS_THRESHOLD
): SharpnessResult {
  const isSharp = variance >= threshold;

  if (isSharp) {
    return {
      score: variance,
      isSharp: true,
      status: 'sharp',
      label: `Sharp (${variance.toFixed(1)})`
    };
  }

  if (variance < CRITICAL_THRESHOLD) {
    return {
      score: variance,
      isSharp: false,
      status: 'critical',
      label: `Heavy Motion Blur (${variance.toFixed(1)})`
    };
  }

  return {
    score: variance,
    isSharp: false,
    status: 'blurry',
    label: `Slight Blur (${variance.toFixed(1)})`
  };
}

/**
 * Decodes any user-uploaded image (JPEG, PNG, WebP), computes true Laplacian sharpness
 * variance, and normalizes it into an uncompressed PNG Blob per FR-04.
 */
export async function analyzeAndConvertImageToPng(file: File): Promise<{
  blob: Blob;
  dataUrl: string;
  blurScore: number;
  width: number;
  height: number;
}> {
  const objectUrl = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error(`Could not decode image: ${file.name}`));
      el.src = objectUrl;
    });

    const width = img.naturalWidth || 1280;
    const height = img.naturalHeight || 720;

    // 1. Evaluate sharpness at normalized 320x240 scale
    const evalCanvas = document.createElement('canvas');
    evalCanvas.width = 320;
    evalCanvas.height = 240;
    const evalCtx = evalCanvas.getContext('2d');
    let blurScore = 150.0;
    if (evalCtx) {
      evalCtx.drawImage(img, 0, 0, 320, 240);
      const imgData = evalCtx.getImageData(0, 0, 320, 240);
      blurScore = computeLaplacianVariance(imgData);
    }

    // 2. Encode uncompressed PNG keyframe at native resolution
    const fullCanvas = document.createElement('canvas');
    fullCanvas.width = width;
    fullCanvas.height = height;
    const fullCtx = fullCanvas.getContext('2d');
    if (fullCtx) {
      fullCtx.drawImage(img, 0, 0, width, height);
    }

    const pngBlob = await new Promise<Blob>((resolve) => {
      fullCanvas.toBlob((b) => resolve(b || file), 'image/png');
    });
    const pngDataUrl = URL.createObjectURL(pngBlob);

    return { blob: pngBlob, dataUrl: pngDataUrl, blurScore, width, height };
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
