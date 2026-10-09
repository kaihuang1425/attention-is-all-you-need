export interface AggregateRow {
  gameId: number;
  playId: number;
  week: number;
  qb: string;
  coverage: string;
  coverageType: string;
  timeToThrow: number;
  gap: number;
  pCatch: number;
  complete: boolean;
  samePick: boolean;
  bestX: number;
  bestY: number;
  targetX: number;
  targetY: number;
}

export interface AggregateData {
  version: number;
  scope: string;
  model: string;
  indexedPlays: number;
  replayablePlays: number;
  processedPlays: number;
  eligibleThrows: number;
  rows: AggregateRow[];
  attention: {
    bins: number[];
    Man: number[];
    Zone: number[];
    manN: number;
    zoneN: number;
    manMedian: number;
    zoneMedian: number;
    blockHits: number;
    blockTotal: number;
  };
}

export type TimeBucket = 'all' | 'quick' | 'medium' | 'long';

export function filteredRows(rows: AggregateRow[], coverage: string, time: TimeBucket) {
  return rows.filter(
    (r) =>
      (coverage === 'All' || r.coverageType === coverage) &&
      (time === 'all' ||
        (time === 'quick' && r.timeToThrow < 2.5) ||
        (time === 'medium' && r.timeToThrow >= 2.5 && r.timeToThrow < 3.5) ||
        (time === 'long' && r.timeToThrow >= 3.5)),
  );
}

const mean = (a: number[]) => a.reduce((sum, x) => sum + x, 0) / a.length;

/** Deterministic 90% bootstrap interval so filters produce stable plots. */
export function bootstrapMean(values: number[], seed: number, draws = 300): [number, number] {
  if (!values.length) return [0, 0];
  let s = seed >>> 0;
  const next = () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
  const sample = Array.from({ length: draws }, () => {
    let sum = 0;
    for (let i = 0; i < values.length; i++) sum += values[Math.floor(next() * values.length)];
    return sum / values.length;
  }).sort((a, b) => a - b);
  return [sample[Math.floor(draws * 0.05)], sample[Math.floor(draws * 0.95)]];
}

export function qbSummary(rows: AggregateRow[], minThrows = 50) {
  const by = new Map<string, number[]>();
  for (const r of rows) {
    const a = by.get(r.qb) ?? [];
    a.push(r.gap);
    by.set(r.qb, a);
  }
  return [...by]
    .filter(([, values]) => values.length >= minThrows)
    .map(([qb, values]) => {
      const seed = [...qb].reduce((n, c) => Math.imul(n, 31) + c.charCodeAt(0), 17);
      const [lo, hi] = bootstrapMean(values, seed);
      return { qb, n: values.length, mean: mean(values), lo, hi };
    })
    .sort((a, b) => a.mean - b.mean);
}

export function calibration(rows: AggregateRow[]) {
  const heldOut = rows.filter((r) => r.week >= 7 && r.week <= 8);
  const bins = Array.from({ length: 10 }, (_, k) => {
    const sample = heldOut.filter((r) => Math.min(9, Math.floor(r.pCatch * 10)) === k);
    return {
      lower: k / 10,
      upper: (k + 1) / 10,
      n: sample.length,
      predicted: sample.length ? mean(sample.map((r) => r.pCatch)) : null,
      observed: sample.length ? mean(sample.map((r) => Number(r.complete))) : null,
    };
  });
  const brier = heldOut.length
    ? mean(heldOut.map((r) => (r.pCatch - Number(r.complete)) ** 2))
    : null;
  return { bins, n: heldOut.length, brier };
}
