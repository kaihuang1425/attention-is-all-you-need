import { describe, expect, it } from 'vitest';
import { bootstrapMean, calibration, filteredRows, qbSummary, type AggregateRow } from './stats';

const row = (week: number, pCatch: number, complete: boolean, gap: number, timeToThrow = 2.8): AggregateRow => ({
  gameId: 1, playId: week, week, qb: 'Example QB', coverage: 'Cover-3', coverageType: 'Zone',
  timeToThrow, gap, pCatch, complete, samePick: gap === 0, bestX: 10, bestY: 20,
  targetX: 12, targetY: 22,
});

describe('aggregate validation summaries', () => {
  it('uses only held-out weeks for calibration and computes Brier score', () => {
    const c = calibration([row(1, 0.9, false, 0), row(7, 0.8, true, 0), row(8, 0.2, false, 0)]);
    expect(c.n).toBe(2);
    expect(c.brier).toBeCloseTo(0.04);
    expect(c.bins[2].observed).toBe(0);
    expect(c.bins[8].observed).toBe(1);
  });

  it('applies the selected coverage and time bucket before QB summaries', () => {
    const rows = [row(7, 0.5, true, 0.1, 2), row(8, 0.5, false, 0.5, 3)];
    rows[1].coverageType = 'Man';
    expect(filteredRows(rows, 'Zone', 'quick')).toHaveLength(1);
    expect(qbSummary(rows, 2)[0].mean).toBeCloseTo(0.3);
    expect(qbSummary(rows, 3)).toEqual([]);
  });

  it('keeps bootstrap intervals stable for the same data and seed', () => {
    const values = [0, 0.2, 0.4, 0.8, 1];
    const a = bootstrapMean(values, 42);
    expect(bootstrapMean(values, 42)).toEqual(a);
    expect(a[0]).toBeLessThan(0.48);
    expect(a[1]).toBeGreaterThan(0.48);
  });
});
