// Number formatting shared by panels. Signed values always carry + or − (colour is never the only cue).
export const signed = (v: number | null | undefined, digits = 2): string => {
  if (v == null || !Number.isFinite(v)) return '–';
  const s = Math.abs(v).toFixed(digits);
  if (Number(s) === 0) return s;
  return `${v > 0 ? '+' : '−'}${s}`;
};

export const pct = (v: number | null | undefined, digits = 0): string =>
  v == null || !Number.isFinite(v) ? '–' : `${v.toFixed(digits)}%`;

export const yd = (v: number | null | undefined, digits = 1): string =>
  v == null || !Number.isFinite(v) ? '–' : `${v.toFixed(digits)} yd`;

export const secs = (v: number | null | undefined, digits = 1): string =>
  v == null || !Number.isFinite(v) ? '–' : `${v.toFixed(digits)} s`;

export const RESULT_TEXT: Record<string, string> = {
  C: 'Complete',
  I: 'Incomplete',
  IN: 'Intercepted',
  S: 'Sack',
  R: 'Scramble',
};

export const laneWord = (l: number | null): string =>
  l == null ? '' : l >= 5 ? 'clear' : l >= 2 ? 'tight' : 'crowded';
