import { describe, expect, it } from 'vitest';
import { makeView } from '../data/derive';
import { loadPlay } from '../test/fixture';
import { computeCrop, pointInPolygon, shadowPolygon } from './geometry';

describe('pass-lane shadow', () => {
  const qb = { x: 20, y: 26.65 };
  const d = { x: 30, y: 26.65 };
  const s = shadowPolygon(qb, d, 1.2, 30)!;

  it('covers the space straight behind the defender', () => {
    expect(pointInPolygon({ x: 40, y: 26.65 }, s.points)).toBe(true);
  });
  it('widens with distance from the QB', () => {
    expect(pointInPolygon({ x: 50, y: 26.65 + 3 }, s.points)).toBe(true);
    expect(pointInPolygon({ x: 32, y: 26.65 + 3 }, s.points)).toBe(false);
  });
  it('does not cover the lane in front of the defender', () => {
    expect(pointInPolygon({ x: 25, y: 26.65 }, s.points)).toBe(false);
  });
  it('is skipped for players on top of the QB', () => {
    expect(shadowPolygon(qb, { x: 21, y: 27 })).toBeNull();
  });
});

describe('crop', () => {
  it('keeps the full play in a readable LOS-centered crop', () => {
    const view = makeView(loadPlay());
    const c = computeCrop(view);
    for (const row of view.data.tracks.x)
      for (const x of row) if (x != null) expect(x).toBeGreaterThanOrEqual(c.x0);
    expect(c.x0).toBeLessThanOrEqual(view.data.meta.los_x - 12);
    expect(c.x1).toBeGreaterThanOrEqual(view.data.meta.los_x + 35);
  });
});
