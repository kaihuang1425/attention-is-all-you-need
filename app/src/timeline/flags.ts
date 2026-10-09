import type { Flag, FlagGroup } from '../data/types';

export const TRACKING_GROUPS: FlagGroup[] = ['key', 'presnap', 'play', 'ballInAir'];

export interface Chip {
  id: string;
  label: string;
  groups: FlagGroup[];
}

export const CHIPS: Chip[] = [
  { id: 'key', label: 'Key', groups: ['key'] },
  { id: 'tracking', label: 'All tracking', groups: TRACKING_GROUPS },
  { id: 'presnap', label: 'Pre-snap', groups: ['presnap'] },
  { id: 'windows', label: 'Windows', groups: ['windows'] },
  { id: 'decision', label: 'Decision', groups: ['decision'] },
  { id: 'protection', label: 'Protection', groups: ['protection'] },
];

export function chipActive(chip: Chip, groups: FlagGroup[]): boolean {
  return chip.groups.every((g) => groups.includes(g));
}

export function toggleChip(chip: Chip, groups: FlagGroup[]): FlagGroup[] {
  const on = chipActive(chip, groups);
  const set = new Set(groups);
  for (const g of chip.groups) {
    if (!on) set.add(g);
    else if (g !== 'key' || chip.id === 'key') set.delete(g); // "All tracking" off keeps Key on
  }
  return [...set];
}

/**
 * Flags shown on the timeline. Window flags follow the selected receiver only (all receivers when
 * nobody is selected), so the row doesn't fill up with every receiver's windows.
 */
export function visibleFlags(
  flags: Flag[],
  groups: FlagGroup[],
  selectedId: number | null,
): Flag[] {
  return flags.filter((f) => {
    if (!groups.includes(f.group)) return false;
    if (f.group === 'windows' && selectedId != null) return f.nflId === selectedId;
    return true;
  });
}

export interface Cluster {
  x: number;
  flags: Flag[];
}

/** Merge flags whose markers sit within `px` pixels of each other (left to right). */
export function clusterFlags(flags: Flag[], xOf: (frameId: number) => number, px = 12): Cluster[] {
  const sorted = [...flags].sort((a, b) => a.frameId - b.frameId);
  const out: Cluster[] = [];
  for (const f of sorted) {
    const x = xOf(f.frameId);
    const last = out[out.length - 1];
    if (last && x - last.x < px) {
      last.flags.push(f);
      last.x = (last.x * (last.flags.length - 1) + x) / last.flags.length;
    } else {
      out.push({ x, flags: [f] });
    }
  }
  return out;
}

/** Next or previous visible flag frame relative to the current frame. */
export function adjacentFlag(flags: Flag[], frameId: number, dir: 1 | -1): Flag | null {
  const sorted = [...flags].sort((a, b) => a.frameId - b.frameId);
  if (dir > 0) return sorted.find((f) => f.frameId > frameId) ?? null;
  for (let k = sorted.length - 1; k >= 0; k--) if (sorted[k].frameId < frameId) return sorted[k];
  return null;
}
