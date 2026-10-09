import { describe, expect, it } from 'vitest';
import { initialState, makeReducer } from './state';

describe('playback state', () => {
  const reduce = makeReducer(() => 43);

  it('seeking pauses playback and snaps to a whole frame', () => {
    const s = reduce({ ...initialState, playing: true, frame: 3.4 }, { type: 'seek', frame: 32.4 });
    expect(s.playing).toBe(false);
    expect(s.frame).toBe(32);
  });

  it('clamps to the play', () => {
    expect(reduce(initialState, { type: 'seek', frame: 99 }).frame).toBe(42);
    expect(reduce(initialState, { type: 'seek', frame: -5 }).frame).toBe(0);
  });

  it('stops at the last frame', () => {
    const s = reduce({ ...initialState, playing: true }, { type: 'tick', frame: 50 });
    expect(s.frame).toBe(42);
    expect(s.playing).toBe(false);
  });

  it('play from the end restarts', () => {
    expect(reduce({ ...initialState, frame: 42 }, { type: 'play' }).frame).toBe(0);
  });
});
