import { describe, expect, it } from 'vitest';
import { loadPlay } from '../test/fixture';
import { makeView, optionRows, ranking } from './derive';

describe('exported play', () => {
  const data = loadPlay();
  const view = makeView(data);

  it('has 11 players per side and the demo play facts', () => {
    expect(data.players.filter((p) => p.side === 'offense')).toHaveLength(11);
    expect(data.players.filter((p) => p.side === 'defense')).toHaveLength(11);
    expect(data.meta.snapFrame).toBe(6);
    expect(data.meta.endFrame).toBe(38);
    expect(data.meta.losLabel).toBe('TB 25');
    expect(data.meta.formation).toBe('2x2');
    expect(data.result.targetJersey).toBe(88);
  });

  it('has exactly one snap flag and one throw flag', () => {
    expect(data.flags.filter((f) => f.type === 'ball_snap')).toHaveLength(1);
    expect(data.flags.filter((f) => f.type === 'pass_forward').map((f) => f.frameId)).toEqual([38]);
  });

  it('passOptions.ts reproduces the pipeline completion model', () => {
    for (const fr of [10, 24, 38]) {
      const i = fr - data.frames.frameId[0];
      const r = ranking(view, i)!;
      for (const o of r.options) {
        const k = data.model.receivers.indexOf(o.id);
        expect(o.completionPct / 100).toBeCloseTo(data.model.pCatch[i][k] as number, 2);
        expect(o.sep).toBeCloseTo(data.model.sep[i][k] as number, 1);
      }
    }
  });

  it('ranks options by expected EPA with the model pick first', () => {
    const i = 38 - data.frames.frameId[0];
    const rows = optionRows(view, i, 'epa');
    expect(rows.map((r) => r.rank)).toEqual([1, 2, 3, 4, 5]);
    for (let k = 1; k < rows.length; k++)
      expect(rows[k - 1].ev!).toBeGreaterThanOrEqual(rows[k].ev!);
    expect(rows[0].id).toBe(data.result.decision.bestId);
  });

  it('has no forward-pass options before the snap', () => {
    expect(optionRows(view, 0, 'epa')).toEqual([]);
  });
});
