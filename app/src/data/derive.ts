// Helpers over a loaded PlayData: lookups, interpolation and per-frame option rows.
import type { PlayData, PlayerInfo } from './types';
import {
  rankPlayFrame,
  type FrameRanking,
  type PlayJson,
  type Role as PoRole,
} from './passOptions';

export interface Vec {
  x: number;
  y: number;
}

export interface PlayView {
  data: PlayData;
  nFrames: number;
  byId: Map<number, PlayerInfo>;
  col: Map<number, number>; // nflId -> column in tracks
  receiverCol: Map<number, number>; // nflId -> column in model grids
  offenseCol: Map<number, number>; // nflId -> column in attention.A
  snapIdx: number;
  endIdx: number;
  throwIdx: number | null;
  qbId: number;
  poPlay: PlayJson; // passOptions.ts view of the same play
  rankCache: Map<string, FrameRanking | null>;
  avgA: Map<number, number>; // play-average A(j) from snap to end
}

export const lastName = (name: string): string => {
  const parts = name.trim().split(/\s+/);
  const suffix = /^(jr\.?|sr\.?|ii|iii|iv|v)$/i;
  while (parts.length > 1 && suffix.test(parts[parts.length - 1])) parts.pop();
  return parts[parts.length - 1] ?? name;
};

export function frameIndexOf(data: PlayData, frameId: number): number {
  return frameId - data.frames.frameId[0];
}

export function toPassOptionsPlay(data: PlayData): PlayJson {
  const m = data.meta;
  const roleOf = (r: PlayerInfo['role']): PoRole => r;
  const players = data.players.map((p) => ({
    id: p.id,
    jersey: p.jersey,
    name: p.name,
    position: p.position,
    side: p.side,
    role: roleOf(p.role),
  }));
  const rcol = new Map(data.model.receivers.map((id, k) => [id, k]));
  const frames = data.frames.frameId.map((frameId, i) => {
    const phase: 'pre_snap' | 'live' | 'post_throw' =
      frameId < m.snapFrame ? 'pre_snap' : frameId > m.endFrame ? 'post_throw' : 'live';
    const fp = data.players.map((p, c) => {
      const x = data.tracks.x[i][c] ?? 0;
      const y = data.tracks.y[i][c] ?? 0;
      const s = data.tracks.s[i][c] ?? 0;
      const dir = ((data.tracks.dir[i][c] ?? 0) * Math.PI) / 180;
      return { id: p.id, x, y, px: x + 0.5 * s * Math.sin(dir), py: y + 0.5 * s * Math.cos(dir) };
    });
    const b = data.ball[i];
    const receivers = data.model.receivers.map((id) => ({
      id,
      safety_pull: data.model.safetyPull[i]?.[rcol.get(id) ?? 0] ?? 0,
    }));
    return {
      frame: frameId,
      t: data.frames.t[i],
      phase,
      ball: b ? { x: b[0], y: b[1] } : null,
      players: fp,
      receivers,
    };
  });
  return {
    meta: {
      los_x: m.los_x,
      yardsToGo: m.yardsToGo,
      snap_frame: m.snapFrame,
      throw_frame: m.endFrame,
    },
    players,
    frames,
  };
}

export function makeView(data: PlayData): PlayView {
  const byId = new Map(data.players.map((p) => [p.id, p]));
  const col = new Map(data.players.map((p, c) => [p.id, c]));
  const receiverCol = new Map(data.model.receivers.map((id, k) => [id, k]));
  const offenseCol = new Map(data.model.attention.offense.map((id, k) => [id, k]));
  const snapIdx = frameIndexOf(data, data.meta.snapFrame);
  const endIdx = frameIndexOf(data, data.meta.endFrame);
  const qb = data.players.find((p) => p.role === 'QB');
  const avgA = new Map<number, number>();
  data.model.attention.offense.forEach((id, j) => {
    let s = 0;
    let n = 0;
    for (let i = snapIdx; i <= endIdx; i++) {
      const v = data.model.attention.A[i]?.[j];
      if (v != null) {
        s += v;
        n++;
      }
    }
    avgA.set(id, n ? s / n : 0);
  });
  return {
    data,
    nFrames: data.frames.frameId.length,
    byId,
    col,
    receiverCol,
    offenseCol,
    snapIdx,
    endIdx,
    throwIdx: data.meta.throwFrame != null ? frameIndexOf(data, data.meta.throwFrame) : null,
    qbId: qb ? qb.id : data.players[0].id,
    poPlay: toPassOptionsPlay(data),
    rankCache: new Map(),
    avgA,
  };
}

export function ranking(view: PlayView, idx: number, projected = false): FrameRanking | null {
  const key = `${idx}:${projected ? 1 : 0}`;
  if (!view.rankCache.has(key))
    view.rankCache.set(key, rankPlayFrame(view.poPlay, idx, { projected }));
  return view.rankCache.get(key) ?? null;
}

/** Position of a player at a fractional frame index (linear interpolation). */
export function posAt(view: PlayView, id: number, f: number): Vec | null {
  const c = view.col.get(id);
  if (c === undefined) return null;
  const { x, y } = view.data.tracks;
  const i0 = Math.max(0, Math.min(view.nFrames - 1, Math.floor(f)));
  const i1 = Math.min(view.nFrames - 1, i0 + 1);
  const a = f - i0;
  const x0 = x[i0][c];
  const y0 = y[i0][c];
  if (x0 == null || y0 == null) return null;
  const x1 = x[i1][c] ?? x0;
  const y1 = y[i1][c] ?? y0;
  return { x: x0 + (x1 - x0) * a, y: y0 + (y1 - y0) * a };
}

export function velAt(view: PlayView, id: number, i: number): Vec {
  const c = view.col.get(id);
  if (c === undefined) return { x: 0, y: 0 };
  const s = view.data.tracks.s[i][c] ?? 0;
  const d = ((view.data.tracks.dir[i][c] ?? 0) * Math.PI) / 180;
  return { x: s * Math.sin(d), y: s * Math.cos(d) };
}

export function ballAt(view: PlayView, f: number): Vec | null {
  const i0 = Math.max(0, Math.min(view.nFrames - 1, Math.floor(f)));
  const i1 = Math.min(view.nFrames - 1, i0 + 1);
  const b0 = view.data.ball[i0];
  if (!b0) return null;
  const b1 = view.data.ball[i1] ?? b0;
  const a = f - i0;
  return { x: b0[0] + (b1[0] - b0[0]) * a, y: b0[1] + (b1[1] - b0[1]) * a };
}

export const tAt = (view: PlayView, i: number): number => view.data.frames.t[i] ?? 0;

export const inDecisionWindow = (view: PlayView, i: number): boolean =>
  i >= view.snapIdx && i <= view.endIdx;

export type RankMode = 'epa' | 'value' | 'safe';

export interface OptionRow {
  id: number;
  jersey: number;
  name: string;
  position: string;
  catchPct: number | null;
  ev: number | null;
  pInt: number | null;
  margin: number | null;
  tBall: number | null;
  tDef: number | null;
  sep: number | null;
  lane: number | null;
  expectedYards: number | null;
  firstDown: boolean;
  touchdown: boolean;
  yardsShort: number | null;
  catchX: number | null;
  catchY: number | null;
  A: number | null;
  safetyPull: number | null;
  rank: number;
}

const rowCache = new WeakMap<PlayView, Map<string, OptionRow[]>>();

/** Rows for the pass options panel at frame index i, sorted by the chosen mode (cached). */
export function optionRows(view: PlayView, i: number, mode: RankMode): OptionRow[] {
  let c = rowCache.get(view);
  if (!c) {
    c = new Map();
    rowCache.set(view, c);
  }
  const key = `${i}:${mode}`;
  if (!c.has(key)) c.set(key, computeOptionRows(view, i, mode));
  return c.get(key)!;
}

function computeOptionRows(view: PlayView, i: number, mode: RankMode): OptionRow[] {
  const m = view.data.model;
  if (!m.legal[i]) return [];
  const r = ranking(view, i);
  const po = new Map((r?.options ?? []).map((o) => [o.id, o]));
  const rows: OptionRow[] = m.receivers.map((id, k) => {
    const p = view.byId.get(id)!;
    const o = po.get(id);
    const j = view.offenseCol.get(id);
    return {
      id,
      jersey: p.jersey,
      name: p.name,
      position: p.position,
      catchPct: m.pCatch[i][k] != null ? 100 * (m.pCatch[i][k] as number) : null,
      ev: m.ev[i][k],
      pInt: m.pInt[i][k],
      margin: m.margin[i][k],
      tBall: m.tBall[i][k],
      tDef: m.tDef[i][k],
      sep: m.sep[i][k],
      lane: m.lane[i][k],
      expectedYards: o ? o.expectedYards : null,
      firstDown: m.firstDown[i][k],
      touchdown: m.touchdown[i][k],
      yardsShort: m.yardsShort[i][k],
      catchX: m.catchX[i][k],
      catchY: m.catchY[i][k],
      A: j !== undefined ? m.attention.A[i][j] : null,
      safetyPull: m.safetyPull[i][k],
      rank: 0,
    };
  });
  const key = (row: OptionRow): number =>
    mode === 'epa'
      ? (row.ev ?? -99)
      : mode === 'value'
        ? (row.expectedYards ?? -99)
        : (row.catchPct ?? -99);
  rows.sort((a, b) => key(b) - key(a) || (b.catchPct ?? 0) - (a.catchPct ?? 0) || a.id - b.id);
  rows.forEach((row, n) => (row.rank = n + 1));
  return rows;
}

export function playerLabel(p: PlayerInfo): string {
  return `#${p.jersey} ${lastName(p.name)}`;
}

/** Best pass option by expected EPA at frame i (the "model pick"), or null. */
export function modelPick(view: PlayView, i: number): number | null {
  const rows = optionRows(view, i, 'epa');
  return rows.length ? rows[0].id : null;
}

/** Frame the decision panels describe: the playhead, or the release frame once the ball is out. */
export function panelFrame(view: PlayView, i: number): { idx: number | null; note: string } {
  if (i < view.snapIdx) return { idx: null, note: 'before the snap' };
  if (i > view.endIdx)
    return {
      idx: view.endIdx,
      note: `at release, ${view.data.frames.t[view.endIdx].toFixed(1)} s`,
    };
  return { idx: i, note: `at ${view.data.frames.t[i].toFixed(1)} s` };
}
