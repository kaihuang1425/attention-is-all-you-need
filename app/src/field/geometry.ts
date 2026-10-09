// Field geometry: crop, coordinate mapping, pass-lane shadows and influence surfaces.
import type { PlayView, Vec } from '../data/derive';
import { posAt, velAt } from '../data/derive';

export const FIELD_W = 53.3;
export const FIELD_L = 120;

export interface Crop {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

/** SVG y for a field y (+y is the offense's left, drawn at the top). */
export const sy = (y: number): number => FIELD_W - y;

/**
 * Crop that fits every player over the whole play, at least LOS-12 .. LOS+35 along the field.
 * The field is a schematic: x and y fill the available panel independently so the action
 * remains readable beside the decision table.
 */
export function computeCrop(view: PlayView): Crop {
  const { x, y } = view.data.tracks;
  let xmin = view.data.meta.los_x - 12;
  let xmax = view.data.meta.los_x + 35;
  let ymin = Infinity;
  let ymax = -Infinity;
  for (let i = 0; i < x.length; i++) {
    for (let c = 0; c < x[i].length; c++) {
      const xv = x[i][c];
      const yv = y[i][c];
      if (xv == null || yv == null) continue;
      xmin = Math.min(xmin, xv - 4);
      xmax = Math.max(xmax, xv + 4);
      ymin = Math.min(ymin, yv - 4);
      ymax = Math.max(ymax, yv + 4);
    }
  }
  // Projected catch points (every legal frame) must be visible too.
  const m = view.data.model;
  for (let i = 0; i < m.catchX.length; i++) {
    for (let k = 0; k < m.catchX[i].length; k++) {
      const cx = m.catchX[i][k];
      const cy = m.catchY[i][k];
      if (cx == null || cy == null) continue;
      xmax = Math.max(xmax, cx + 3);
      ymin = Math.min(ymin, cy - 3);
      ymax = Math.max(ymax, cy + 3);
    }
  }
  // Snap to a sideline when the action gets within 4 yd of it, so the boundary is on screen.
  ymin = ymin < 4 ? -2 : Math.min(ymin, 8);
  ymax = ymax > FIELD_W - 4 ? FIELD_W + 2 : Math.max(ymax, FIELD_W - 8);
  const w = xmax - xmin;
  // Keep the box on the field where possible: slide it back inside -2 .. 122.
  if (xmin + w > FIELD_L + 2) xmin = Math.max(-2, FIELD_L + 2 - w);
  if (xmin < -2) xmin = -2;
  return { x0: xmin, x1: xmin + w, y0: ymin, y1: ymax };
}

/** Real-field yard number for a normalised x line (multiples of 10 between the goal lines). */
export function yardNumber(xn: number): number {
  return xn <= 60 ? Math.round(xn - 10) : Math.round(110 - xn);
}

// ------------------------------------------------------------------ pass-lane shadows

export interface Shadow {
  id: number; // defender nflId
  points: Vec[]; // polygon in field coordinates
  from: Vec; // defender position (gradient start)
  to: Vec; // far end along the axis (gradient end)
  strength: number; // 0-1: rushers in the QB's face are drawn lighter (passes usually go over them)
}

/**
 * The region a straight 2D pass from the QB cannot reach because a defender stands in the way:
 * a cone that starts at the defender (rounded cap of radius `reach` facing the QB) and widens
 * away from the QB for `length` yards. Ball height is ignored (2D proxy).
 */
export function shadowPolygon(
  qb: Vec,
  d: Vec,
  reach = 1.2,
  length = 30,
  maxHalfAngleDeg = 30,
): Omit<Shadow, 'id'> | null {
  const dx = d.x - qb.x;
  const dy = d.y - qb.y;
  const r = Math.hypot(dx, dy);
  if (r < 2.5) return null;
  const ux = dx / r;
  const uy = dy / r;
  const nx = -uy;
  const ny = ux;
  const alpha = Math.min(Math.asin(Math.min(0.95, reach / r)), (maxHalfAngleDeg * Math.PI) / 180);
  const far = r + length;
  const rot = (a: number): Vec => ({
    x: ux * Math.cos(a) - uy * Math.sin(a),
    y: ux * Math.sin(a) + uy * Math.cos(a),
  });
  const ePlus = rot(alpha);
  const eMinus = rot(-alpha);
  // Tangent points on the cap circle.
  const tPlus = { x: d.x + nx * reach * Math.cos(alpha), y: d.y + ny * reach * Math.cos(alpha) };
  const tMinus = { x: d.x - nx * reach * Math.cos(alpha), y: d.y - ny * reach * Math.cos(alpha) };
  const pts: Vec[] = [
    tPlus,
    { x: qb.x + ePlus.x * far, y: qb.y + ePlus.y * far },
    { x: qb.x + eMinus.x * far, y: qb.y + eMinus.y * far },
    tMinus,
  ];
  // Rounded cap toward the QB: half circle from tMinus back to tPlus through d - u*reach.
  const a0 = Math.atan2(-ny, -nx);
  for (let k = 1; k < 10; k++) {
    const a = a0 - (Math.PI * k) / 10;
    pts.push({ x: d.x + reach * Math.cos(a), y: d.y + reach * Math.sin(a) });
  }
  const strength = Math.max(0.35, Math.min(1, (r - 2) / 8));
  return { points: pts, from: d, to: { x: qb.x + ux * far, y: qb.y + uy * far }, strength };
}

export function shadowsAt(view: PlayView, f: number, reach = 1.2): Shadow[] {
  const qb = posAt(view, view.qbId, f);
  if (!qb) return [];
  const out: Shadow[] = [];
  for (const p of view.data.players) {
    if (p.side !== 'defense') continue;
    const d = posAt(view, p.id, f);
    if (!d || d.x < qb.x - 1) continue; // defenders behind the QB cast no useful shadow
    const s = shadowPolygon(qb, d, reach);
    if (s) out.push({ id: p.id, ...s });
  }
  return out;
}

/** Fraction of a receiver's catch point that lies inside any shadow (0 or 1), for labels and tests. */
export function inShadow(p: Vec, shadows: Shadow[]): boolean {
  return shadows.some((s) => pointInPolygon(p, s.points));
}

export function pointInPolygon(p: Vec, poly: Vec[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i];
    const b = poly[j];
    if (a.y > p.y !== b.y > p.y && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y + 1e-12) + a.x)
      inside = !inside;
  }
  return inside;
}

// ------------------------------------------------------------------ influence

export interface InfluenceGrid {
  x0: number;
  y0: number;
  step: number;
  nx: number;
  ny: number;
  values: Float32Array; // row-major, ny rows (y ascending) x nx columns
}

/**
 * Coverage influence: sum over players of a Gaussian centred on position + 0.5 s x velocity,
 * width 2 yd plus 0.25 yd per yd/s of speed. side = 'defense' sums defenders; 'control' returns
 * offense minus defense (non-QB offense).
 */
export function influenceGrid(
  view: PlayView,
  f: number,
  crop: Crop,
  mode: 'defense' | 'control',
  step = 0.5,
): InfluenceGrid {
  const nx = Math.ceil((crop.x1 - crop.x0) / step);
  const ny = Math.ceil((crop.y1 - crop.y0) / step);
  const values = new Float32Array(nx * ny);
  const i = Math.max(0, Math.min(view.nFrames - 1, Math.round(f)));
  for (const p of view.data.players) {
    if (p.role === 'QB') continue;
    const sign = p.side === 'defense' ? 1 : mode === 'control' ? -1 : 0;
    if (!sign) continue;
    const pos = posAt(view, p.id, f);
    if (!pos) continue;
    const v = velAt(view, p.id, i);
    const cx = pos.x + 0.5 * v.x;
    const cy = pos.y + 0.5 * v.y;
    const sigma = 2 + 0.25 * Math.hypot(v.x, v.y);
    const s2 = 2 * sigma * sigma;
    const rad = 3 * sigma;
    const ix0 = Math.max(0, Math.floor((cx - rad - crop.x0) / step));
    const ix1 = Math.min(nx - 1, Math.ceil((cx + rad - crop.x0) / step));
    const iy0 = Math.max(0, Math.floor((cy - rad - crop.y0) / step));
    const iy1 = Math.min(ny - 1, Math.ceil((cy + rad - crop.y0) / step));
    for (let iy = iy0; iy <= iy1; iy++) {
      const gy = crop.y0 + (iy + 0.5) * step - cy;
      for (let ix = ix0; ix <= ix1; ix++) {
        const gx = crop.x0 + (ix + 0.5) * step - cx;
        values[iy * nx + ix] += sign * Math.exp(-(gx * gx + gy * gy) / s2);
      }
    }
  }
  return { x0: crop.x0, y0: crop.y0, step, nx, ny, values };
}
