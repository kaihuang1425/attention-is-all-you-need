import { createContext, useContext } from 'react';
import type { FlagGroup } from './data/types';
import type { RankMode } from './data/derive';

export type HeatMode = 'off' | 'defense' | 'control';

export interface Layers {
  heat: HeatMode;
  shadows: boolean;
  edges: boolean;
  projection: boolean;
  trails: boolean;
  catchPoints: boolean;
  showActual: boolean;
  protection: boolean;
}

export interface UiState {
  frame: number; // playhead as a fractional frame index (0 = first frame)
  playing: boolean;
  speed: number;
  selectedId: number | null;
  hoveredId: number | null;
  rankMode: RankMode;
  layers: Layers;
  trailFrames: number;
  trailAll: boolean;
  flagGroups: FlagGroup[];
  revealCoverage: boolean;
}

export const DEFAULT_LAYERS: Layers = {
  heat: 'defense',
  shadows: false,
  edges: true,
  projection: false,
  trails: true,
  catchPoints: true,
  showActual: false,
  protection: false,
};

export const initialState: UiState = {
  frame: 0,
  playing: false,
  speed: 1,
  selectedId: null,
  hoveredId: null,
  rankMode: 'epa',
  layers: DEFAULT_LAYERS,
  trailFrames: 10,
  trailAll: false,
  flagGroups: ['key'],
  revealCoverage: false,
};

export type Action =
  | { type: 'reset'; frame: number; selectedId: number | null }
  | { type: 'seek'; frame: number; pause?: boolean }
  | { type: 'tick'; frame: number }
  | { type: 'play' }
  | { type: 'pause' }
  | { type: 'speed'; speed: number }
  | { type: 'select'; id: number | null }
  | { type: 'hover'; id: number | null }
  | { type: 'rankMode'; mode: RankMode }
  | { type: 'layer'; key: Exclude<keyof Layers, 'heat'>; value?: boolean }
  | { type: 'heat'; mode: HeatMode }
  | { type: 'trailFrames'; n: number }
  | { type: 'trailAll'; value: boolean }
  | { type: 'flagGroups'; groups: FlagGroup[] }
  | { type: 'revealCoverage' }
  | { type: 'restoreLayers'; layers: Partial<Layers>; trailFrames?: number };

export function makeReducer(nFrames: () => number) {
  const clamp = (f: number) => Math.max(0, Math.min(nFrames() - 1, f));
  return function reducer(s: UiState, a: Action): UiState {
    switch (a.type) {
      case 'reset':
        return {
          ...s,
          frame: clamp(a.frame),
          playing: false,
          selectedId: a.selectedId,
          hoveredId: null,
        };
      case 'seek':
        return {
          ...s,
          frame: clamp(Math.round(a.frame)),
          playing: a.pause === false ? s.playing : false,
        };
      case 'tick': {
        const f = clamp(a.frame);
        return { ...s, frame: f, playing: f < nFrames() - 1 ? s.playing : false };
      }
      case 'play':
        return { ...s, playing: true, frame: s.frame >= nFrames() - 1 ? 0 : Math.round(s.frame) };
      case 'pause':
        return { ...s, playing: false, frame: Math.round(s.frame) };
      case 'speed':
        return { ...s, speed: a.speed };
      case 'select':
        return { ...s, selectedId: a.id };
      case 'hover':
        return s.hoveredId === a.id ? s : { ...s, hoveredId: a.id };
      case 'rankMode':
        return { ...s, rankMode: a.mode };
      case 'layer':
        return { ...s, layers: { ...s.layers, [a.key]: a.value ?? !s.layers[a.key] } };
      case 'heat':
        return { ...s, layers: { ...s.layers, heat: a.mode } };
      case 'trailFrames':
        return { ...s, trailFrames: a.n };
      case 'trailAll':
        return { ...s, trailAll: a.value };
      case 'flagGroups':
        return { ...s, flagGroups: a.groups };
      case 'revealCoverage':
        return { ...s, revealCoverage: !s.revealCoverage };
      case 'restoreLayers':
        return {
          ...s,
          layers: { ...s.layers, ...a.layers },
          trailFrames: a.trailFrames ?? s.trailFrames,
        };
      default:
        return s;
    }
  };
}

export const UiContext = createContext<{ state: UiState; dispatch: (a: Action) => void } | null>(
  null,
);

export function useUi() {
  const ctx = useContext(UiContext);
  if (!ctx) throw new Error('UiContext missing');
  return ctx;
}

const STORE_KEY = 'defensive-attention:layers:v1';

export function loadSavedLayers(): { layers: Partial<Layers>; trailFrames?: number } | null {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveLayers(layers: Layers, trailFrames: number): void {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify({ layers, trailFrames }));
  } catch {
    // storage unavailable (private window, blocked): ignore
  }
}
