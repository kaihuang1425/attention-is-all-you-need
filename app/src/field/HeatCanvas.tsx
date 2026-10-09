import { useEffect, useRef } from 'react';
import type { PlayView } from '../data/derive';
import type { HeatMode } from '../state';
import { influenceGrid, type Crop } from './geometry';

interface Props {
  view: PlayView;
  frame: number;
  crop: Crop;
  mode: HeatMode;
  width: number;
  height: number;
}

// Attention amber for defensive influence; model cyan for offensive control (diverging mode).
const AMBER: [number, number, number] = [245, 158, 11];
const CYAN: [number, number, number] = [34, 211, 238];
const MAX_ALPHA = 0.45;

/** Canvas under the SVG field. Redraws only when the frame, crop, mode or size changes. */
export default function HeatCanvas({ view, frame, crop, mode, width, height }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const cell = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || width <= 0 || height <= 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (mode === 'off') return;

    const g = influenceGrid(view, frame, crop, mode);
    if (!cell.current) cell.current = document.createElement('canvas');
    const small = cell.current;
    small.width = g.nx;
    small.height = g.ny;
    const sctx = small.getContext('2d');
    if (!sctx) return;
    const img = sctx.createImageData(g.nx, g.ny);
    for (let iy = 0; iy < g.ny; iy++) {
      // canvas rows go top -> bottom = field y descending
      const row = g.ny - 1 - iy;
      for (let ix = 0; ix < g.nx; ix++) {
        const v = g.values[iy * g.nx + ix];
        const k = (row * g.nx + ix) * 4;
        let rgb = AMBER;
        let a: number;
        if (mode === 'defense') {
          a = Math.min(1, v / 1.4);
        } else {
          rgb = v < 0 ? CYAN : AMBER;
          a = Math.min(1, Math.abs(v) / 1.2);
        }
        img.data[k] = rgb[0];
        img.data[k + 1] = rgb[1];
        img.data[k + 2] = rgb[2];
        img.data[k + 3] = Math.round(255 * MAX_ALPHA * Math.pow(a, 0.9));
      }
    }
    sctx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    // The grid starts at (crop.x0, crop.y0) and spans nx * step by ny * step yards, which can
    // overshoot the crop's top edge by part of a cell; shift it up by that amount.
    const pxPerX = canvas.width / (crop.x1 - crop.x0);
    const pxPerY = canvas.height / (crop.y1 - crop.y0);
    const overshoot = crop.y0 + g.ny * g.step - crop.y1;
    ctx.drawImage(small, 0, -overshoot * pxPerY, g.nx * g.step * pxPerX, g.ny * g.step * pxPerY);
  }, [view, frame, crop, mode, width, height]);

  return <canvas ref={ref} className="heat-canvas" style={{ width, height }} aria-hidden="true" />;
}
