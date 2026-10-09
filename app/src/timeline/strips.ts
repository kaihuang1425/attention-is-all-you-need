import type { PlayView } from '../data/derive';

/** Frame-index spans where the arrival margin is at least +0.3 s. */
export function windowSpans(view: PlayView, k: number, thr = 0.3): [number, number][] {
  const out: [number, number][] = [];
  let start = -1;
  const margin = view.data.model.margin;
  for (let i = view.snapIdx; i <= view.endIdx; i++) {
    const m = margin[i]?.[k];
    const open = m != null && m >= thr;
    if (open && start < 0) start = i;
    if (!open && start >= 0) {
      if (i - 1 > start) out.push([start, i - 1]);
      start = -1;
    }
  }
  if (start >= 0 && view.endIdx > start) out.push([start, view.endIdx]);
  return out;
}

// Attention amber ramp (dark -> bright) for A(j) from 0 to 2.5 defender-equivalents.
export function rampColor(a: number): string {
  const v = Math.max(0, Math.min(1, a / 2.5));
  const c0 = [40, 31, 20];
  const c1 = [253, 196, 52];
  const k = Math.pow(v, 1.25);
  const mix = c0.map((c, j) => Math.round(c + (c1[j] - c) * k));
  return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
}
