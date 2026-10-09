/**
 * Pass Options ranking: TypeScript port of pass_options.py.
 *
 * Drop into app/src/ (e.g. app/src/data/passOptions.ts). No dependencies.
 * Computes, for any frame of a play JSON exported by pass_options.py:
 *   - per-receiver metrics: separation, attention, lane clearance, depth / reaches sticks
 *   - completion probability (logistic model learned from real targeted throws)
 *   - expected yards (best value, default) and the safest-throw ranking (backup)
 *   - pocket pressure and the "why this window" sentence
 *
 * Typical use:
 *   import { rankPlayFrame } from './passOptions';
 *   const r = rankPlayFrame(play, frameIndex);                    // observed positions
 *   const p = rankPlayFrame(play, frameIndex, { projected: true }); // the +0.5 s projection
 *   r.options      -> sorted by best value (rankValue 1 first)
 *   r.whyValue / r.whySafe, r.pressure
 *
 * Coordinates: the offense attacks toward +x, the field is 0-120 x 0-53.3 yards,
 * +y is the QB's left. Positions come straight from the play JSON.
 */

// ---------------------------------------------------------------- types
export interface Vec {
  x: number;
  y: number;
}

export type Role = 'QB' | 'route' | 'block' | 'coverage' | 'rush' | 'other';
export type RankMode = 'value' | 'safe';

export interface PlayPlayer {
  id: number;
  jersey: number;
  name: string;
  position: string;
  side: 'offense' | 'defense';
  role: Role;
}

export interface FramePlayer {
  id: number;
  x: number;
  y: number;
  px: number;
  py: number;
}

export interface ExportedReceiver {
  id: number;
  safety_pull: number;
}

export interface PlayFrame {
  frame: number;
  t: number;
  phase: 'pre_snap' | 'live' | 'post_throw';
  ball: Vec | null;
  players: FramePlayer[];
  receivers?: ExportedReceiver[];
}

export interface PlayJson {
  meta: { los_x: number; yardsToGo: number; snap_frame: number; throw_frame: number };
  players: PlayPlayer[];
  frames: PlayFrame[];
}

export interface CompletionModel {
  intercept: number;
  /** standardised coefficients, order: sep, lane, attention, depth, depth^2 */
  coef: [number, number, number, number, number];
  mu: [number, number, number, number, number];
  sd: [number, number, number, number, number];
  expectedYac: number;
  firstDownBonus: number;
  attentionSigma: number;
  nobodyRadius: number;
}

export interface ReceiverMetrics {
  id: number;
  sep: number;
  attention: number;
  lane: number;
  depth: number;
  reachesSticks: boolean;
}

export interface RankedOption extends ReceiverMetrics {
  jersey: number;
  completionPct: number;
  expectedYards: number;
  rankValue: number;
  rankSafe: number;
  safetyPull: number;
}

export interface Pressure {
  nearestRusherYds: number;
  closingSpeed: number;
  /** 0 (clean) to 7 (on top of the QB): matches the 7-segment meter in the UI */
  level: number;
  side: 'left' | 'right';
  text: string;
  rusherId: number;
}

export interface FrameRanking {
  options: RankedOption[];
  top: { value: RankedOption; safe: RankedOption };
  pressure: Pressure | null;
  whyValue: string;
  whySafe: string;
}

// ---------------------------------------------------------------- model (from output/model.json)
/** Trained on 2021 Weeks 1-6 targeted throws, held-out AUC 0.72 on Weeks 7-8. */
export const DEFAULT_MODEL: CompletionModel = {
  intercept: 0.7578694391359947,
  coef: [
    0.5705272892715294, -0.09125081626188389, -0.028536078737154056, -0.3327617969832017,
    -0.02829357429351297,
  ],
  mu: [
    3.757487148025027, 3.78167896408568, 0.850562858773423, 6.790964100666172, 86.61537111398964,
  ],
  sd: [
    2.3025147598530564, 3.4489378587838955, 0.47084588300490043, 6.363817856458539,
    134.9895540714804,
  ],
  expectedYac: 3.0,
  firstDownBonus: 5.0,
  attentionSigma: 3.0,
  nobodyRadius: 7.0,
};

/** Build a model from a freshly generated output/model.json (same shape as pass_options.py writes). */
export function modelFromJson(j: {
  coef_standardised: Record<string, number>;
  mu: number[];
  sd: number[];
  assumptions: {
    expected_yac: number;
    first_down_bonus: number;
    attention_sigma: number;
    nobody_radius: number;
  };
}): CompletionModel {
  const c = j.coef_standardised;
  const five = (a: number[]): [number, number, number, number, number] => [
    a[0],
    a[1],
    a[2],
    a[3],
    a[4],
  ];
  return {
    intercept: c.intercept,
    coef: [c.sep, c.lane, c.attention, c.depth, c.depth2],
    mu: five(j.mu),
    sd: five(j.sd),
    expectedYac: j.assumptions.expected_yac,
    firstDownBonus: j.assumptions.first_down_bonus,
    attentionSigma: j.assumptions.attention_sigma,
    nobodyRadius: j.assumptions.nobody_radius,
  };
}

// ---------------------------------------------------------------- geometry
const dist = (a: Vec, b: Vec): number => Math.hypot(a.x - b.x, a.y - b.y);

/** Distance from p to the middle 25%-85% of the throwing line a->b; Infinity if p is not alongside it. */
function laneDist(p: Vec, a: Vec, b: Vec): number {
  const abx = b.x - a.x;
  const aby = b.y - a.y;
  const L2 = Math.max(abx * abx + aby * aby, 1e-6);
  const u = ((p.x - a.x) * abx + (p.y - a.y) * aby) / L2;
  if (u < 0.25 || u > 0.85) return Infinity;
  return Math.hypot(p.x - (a.x + u * abx), p.y - (a.y + u * aby));
}

/** Per-receiver metrics for one frame. */
export function frameMetrics(
  receivers: (Vec & { id: number })[],
  coverage: Vec[],
  defense: Vec[],
  qb: Vec,
  losX: number,
  yardsToGo: number,
  model: CompletionModel = DEFAULT_MODEL,
): ReceiverMetrics[] {
  const s2 = 2 * model.attentionSigma ** 2;
  const qNone = Math.exp(-(model.nobodyRadius ** 2) / s2);
  const attention = receivers.map(() => 0);
  for (const d of coverage) {
    // each coverage defender's focus is split across receivers plus "nobody"
    const q = receivers.map((r) => Math.exp(-(dist(d, r) ** 2) / s2));
    const total = qNone + q.reduce((s, v) => s + v, 0);
    q.forEach((v, k) => (attention[k] += v / total));
  }
  return receivers.map((r, k) => {
    const sep = defense.length ? Math.min(10, Math.min(...defense.map((d) => dist(d, r)))) : 10;
    const lane = defense.length
      ? Math.min(10, Math.min(...defense.map((d) => laneDist(d, qb, r))))
      : 10;
    const depth = r.x - losX;
    return {
      id: r.id,
      sep,
      attention: attention[k],
      lane,
      depth,
      reachesSticks: depth >= yardsToGo,
    };
  });
}

// ---------------------------------------------------------------- model + ranking
export function completionProb(m: ReceiverMetrics, model: CompletionModel = DEFAULT_MODEL): number {
  const f = [m.sep, m.lane, m.attention, m.depth, m.depth * m.depth];
  let z = model.intercept;
  for (let i = 0; i < 5; i++) z += model.coef[i] * ((f[i] - model.mu[i]) / model.sd[i]);
  return 1 / (1 + Math.exp(-z));
}

/** Best-value score: P(complete) x (depth + expected YAC + first-down bonus if it reaches the sticks). */
export function expectedYards(
  p: number,
  m: ReceiverMetrics,
  model: CompletionModel = DEFAULT_MODEL,
): number {
  return (
    p * Math.max(m.depth + model.expectedYac + (m.reachesSticks ? model.firstDownBonus : 0), 0)
  );
}

/** Rank descending by primary score; ties break by the secondary score, then by player id (same rule as Python). */
function ranks(primary: number[], secondary: number[], ids: number[]): number[] {
  const order = primary
    .map((_, i) => i)
    .sort((a, b) => primary[b] - primary[a] || secondary[b] - secondary[a] || ids[a] - ids[b]);
  const r = primary.map(() => 0);
  order.forEach((i, pos) => (r[i] = pos + 1));
  return r;
}

/** Rank receivers in both modes. Returned list is sorted by best value (rankValue 1 first). */
export function rankOptions(
  metrics: ReceiverMetrics[],
  jerseyById: Map<number, number>,
  model: CompletionModel = DEFAULT_MODEL,
  safetyPullById: Map<number, number> = new Map(),
): RankedOption[] {
  const p = metrics.map((m) => completionProb(m, model));
  const v = metrics.map((m, k) => expectedYards(p[k], m, model));
  const ids = metrics.map((m) => m.id);
  const rv = ranks(v, p, ids);
  const rs = ranks(p, v, ids);
  return metrics
    .map((m, k) => ({
      ...m,
      jersey: jerseyById.get(m.id) ?? 0,
      completionPct: 100 * p[k],
      expectedYards: v[k],
      rankValue: rv[k],
      rankSafe: rs[k],
      safetyPull: safetyPullById.get(m.id) ?? 0,
    }))
    .sort((a, b) => a.rankValue - b.rankValue);
}

export function topOption(options: RankedOption[], mode: RankMode): RankedOption {
  const key = mode === 'value' ? 'rankValue' : 'rankSafe';
  return options.reduce((best, o) => (o[key] < best[key] ? o : best));
}

// ---------------------------------------------------------------- pressure + explanation
/** Nearest pass rusher to the QB. Pass the previous frame's distance to get closing speed (yds/s at 10 Hz). */
export function pocketPressure(
  qb: Vec,
  rushers: (Vec & { id: number })[],
  prevNearest?: number,
): Pressure | null {
  if (!rushers.length) return null;
  let k = 0;
  rushers.forEach((r, i) => {
    if (dist(r, qb) < dist(rushers[k], qb)) k = i;
  });
  const d = dist(rushers[k], qb);
  const closing = prevNearest === undefined ? 0 : (prevNearest - d) * 10;
  const level = Math.min(7, Math.max(0, Math.round(7 * (1 - (d - 1) / 6))));
  const side: 'left' | 'right' = rushers[k].y > qb.y ? 'left' : 'right'; // +y is the QB's left
  const base =
    level <= 2
      ? 'Pocket clean'
      : Math.abs(rushers[k].y - qb.y) < 2
        ? 'Interior pressure'
        : `${side === 'left' ? 'Left' : 'Right'} edge`;
  const text = level <= 2 ? base : base + (closing > 1 ? ' closing' : '');
  return { nearestRusherYds: d, closingSpeed: closing, level, side, text, rusherId: rushers[k].id };
}

const laneWord = (l: number): string => (l >= 5 ? 'clear' : l >= 2 ? 'tight' : 'crowded');

/** One-line "why this window" text for the #1 option in the given mode. */
export function explain(options: RankedOption[], mode: RankMode): string {
  const top = topOption(options, mode);
  const others = options.filter((o) => o.id !== top.id);
  const bits: string[] = [];
  if (others.length) {
    const drawer = others.reduce((a, b) => (b.attention > a.attention ? b : a));
    const puller = others.reduce((a, b) => (b.safetyPull > a.safetyPull ? b : a));
    if (drawer.attention >= 1.0)
      bits.push(`#${drawer.jersey} draws ${drawer.attention.toFixed(1)} defenders`);
    if (puller.safetyPull >= 2.0)
      bits.push(
        `the deep safety has moved ${puller.safetyPull.toFixed(1)} yds toward #${puller.jersey}`,
      );
  }
  let lead = bits.length ? bits.join(' and ') + '. ' : '';
  lead = lead.charAt(0).toUpperCase() + lead.slice(1);
  const sticks = top.reachesSticks ? ', past the sticks' : '';
  return (
    `${lead}#${top.jersey} has ${top.sep.toFixed(1)} yds of space and a ${laneWord(top.lane)} lane` +
    `${sticks} (${top.completionPct.toFixed(0)}% completion).`
  );
}

// ---------------------------------------------------------------- one call for the UI
/**
 * Rank the options at frames[frameIndex] of an exported play.
 * Returns null outside the snap->throw window (no decision to make).
 * projected: use the +0.5 s projected positions (px, py) instead of the observed ones.
 * Safety pull is read from the exported frame (it needs the play's history and PFF alignments).
 */
export function rankPlayFrame(
  play: PlayJson,
  frameIndex: number,
  opts: { projected?: boolean; model?: CompletionModel } = {},
): FrameRanking | null {
  const fr = play.frames[frameIndex];
  if (!fr || fr.phase !== 'live') return null;
  const model = opts.model ?? DEFAULT_MODEL;
  const info = new Map(play.players.map((p) => [p.id, p]));
  const at = (p: FramePlayer): Vec & { id: number } =>
    opts.projected ? { id: p.id, x: p.px, y: p.py } : { id: p.id, x: p.x, y: p.y };
  const withRole = (pred: (p: PlayPlayer) => boolean) =>
    fr.players.filter((p) => {
      const i = info.get(p.id);
      return i !== undefined && pred(i);
    });

  const receivers = withRole((p) => p.role === 'route').map(at);
  const qbRow = withRole((p) => p.role === 'QB')[0];
  if (!receivers.length || !qbRow) return null;
  const qb = at(qbRow);
  const coverage = withRole((p) => p.role === 'coverage').map(at);
  const defense = withRole((p) => p.side === 'defense').map(at);
  const rushers = withRole((p) => p.role === 'rush').map(at);

  const metrics = frameMetrics(
    receivers,
    coverage,
    defense,
    qb,
    play.meta.los_x,
    play.meta.yardsToGo,
    model,
  );
  const jersey = new Map(play.players.map((p) => [p.id, p.jersey]));
  const pull = new Map((fr.receivers ?? []).map((r) => [r.id, r.safety_pull]));
  const options = rankOptions(metrics, jersey, model, pull);

  // closing speed needs the previous frame's nearest-rusher distance
  let prevNearest: number | undefined;
  const prev = play.frames[frameIndex - 1];
  if (prev && prev.phase === 'live') {
    const pq = prev.players.find((p) => info.get(p.id)?.role === 'QB');
    const pr = prev.players.filter((p) => info.get(p.id)?.role === 'rush');
    if (pq && pr.length) prevNearest = Math.min(...pr.map((r) => dist(at(r), at(pq))));
  }

  return {
    options,
    top: { value: topOption(options, 'value'), safe: topOption(options, 'safe') },
    pressure: pocketPressure(qb, rushers, prevNearest),
    whyValue: explain(options, 'value'),
    whySafe: explain(options, 'safe'),
  };
}
