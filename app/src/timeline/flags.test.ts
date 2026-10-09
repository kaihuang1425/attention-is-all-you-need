import { describe, expect, it } from 'vitest';
import type { Flag } from '../data/types';
import { adjacentFlag, CHIPS, clusterFlags, toggleChip, visibleFlags } from './flags';

const f = (frameId: number, group: Flag['group'], extra: Partial<Flag> = {}): Flag => ({
  id: `${group}-${frameId}-${extra.nflId ?? ''}`,
  frameId,
  t: (frameId - 6) / 10,
  type: group,
  group,
  source: ['key', 'presnap', 'play', 'ballInAir'].includes(group) ? 'tracking' : 'model',
  label: group,
  ...extra,
});

const FLAGS: Flag[] = [
  f(6, 'key'),
  f(3, 'presnap'),
  f(20, 'windows', { nflId: 1 }),
  f(22, 'windows', { nflId: 2 }),
  f(25, 'decision'),
  f(30, 'protection'),
  f(38, 'key'),
];

describe('flag filters', () => {
  it('Key shows only snap and the end event', () => {
    expect(visibleFlags(FLAGS, ['key'], null).map((x) => x.frameId)).toEqual([6, 38]);
  });

  it('window flags follow the selected receiver', () => {
    expect(visibleFlags(FLAGS, ['windows'], 2).map((x) => x.nflId)).toEqual([2]);
    expect(visibleFlags(FLAGS, ['windows'], null)).toHaveLength(2);
  });

  it('chips combine and "All tracking" off keeps Key', () => {
    const all = CHIPS.find((c) => c.id === 'tracking')!;
    const on = toggleChip(all, ['key']);
    expect(on.sort()).toEqual(['ballInAir', 'key', 'play', 'presnap']);
    expect(toggleChip(all, on)).toEqual(['key']);
  });

  it('[ and ] skip hidden flags', () => {
    const visible = visibleFlags(FLAGS, ['key'], null);
    expect(adjacentFlag(visible, 6, 1)?.frameId).toBe(38);
    expect(adjacentFlag(visible, 38, -1)?.frameId).toBe(6);
    expect(adjacentFlag(visible, 38, 1)).toBeNull();
  });
});

describe('flag clustering', () => {
  const two = [f(20, 'decision'), f(22, 'decision')];
  it('merges flags within 12 px', () => {
    expect(clusterFlags(two, (fr) => fr * 5, 12)).toHaveLength(1); // 10 px apart
  });
  it('splits them when the track is wider', () => {
    expect(clusterFlags(two, (fr) => fr * 10, 12)).toHaveLength(2); // 20 px apart
  });
});
