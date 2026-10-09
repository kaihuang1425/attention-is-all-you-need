import { useEffect, useMemo, useRef, useState } from 'react';
import { frameIndexOf, lastName, type PlayView } from '../data/derive';
import type { Flag } from '../data/types';
import { useUi } from '../state';
import { CHIPS, chipActive, clusterFlags, toggleChip, visibleFlags, type Cluster } from './flags';
import { rampColor, windowSpans } from './strips';

const PAD = 10; // px inside the track at both ends
const SPEEDS = [0.25, 0.5, 1, 2];

export default function Timeline({ view }: { view: PlayView }) {
  const { state, dispatch } = useUi();
  const track = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  const [open, setOpen] = useState<Cluster | null>(null);
  const [stripsOpen, setStripsOpen] = useState(false);

  useEffect(() => {
    const el = track.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(100, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const n = view.nFrames;
  const xOfIdx = (i: number) => PAD + (i / Math.max(1, n - 1)) * (w - 2 * PAD);
  const xOfFrame = (frameId: number) => xOfIdx(frameIndexOf(view.data, frameId));
  const idxOfX = (x: number) => Math.round(((x - PAD) / (w - 2 * PAD)) * (n - 1));
  const i = Math.round(state.frame);
  const t = view.data.frames.t[i] ?? 0;
  const frameId = view.data.frames.frameId[i];

  const flags = useMemo(
    () => visibleFlags(view.data.flags, state.flagGroups, state.selectedId),
    [view, state.flagGroups, state.selectedId],
  );
  const clusters = clusterFlags(flags, xOfFrame, 12);
  const labelled = labelPlacement(clusters, w);

  const seekToFlag = (f: Flag) => {
    dispatch({ type: 'seek', frame: frameIndexOf(view.data, f.frameId) });
    if (f.nflId != null) dispatch({ type: 'select', id: f.nflId });
    setOpen(null);
    document.getElementById('playhead-slider')?.focus();
  };

  const seekFromEvent = (e: React.MouseEvent<HTMLElement | SVGElement>) => {
    const rect = track.current!.getBoundingClientRect();
    dispatch({ type: 'seek', frame: idxOfX(e.clientX - rect.left) });
  };

  // Ticks every 0.5 s from the first to the last frame.
  const ticks: { x: number; label: string; major: boolean }[] = [];
  const t0 = view.data.frames.t[0];
  const t1 = view.data.frames.t[n - 1];
  for (let s = Math.ceil(t0 * 2) / 2; s <= t1 + 1e-9; s += 0.5) {
    const idx = view.snapIdx + Math.round(s * 10);
    ticks.push({
      x: xOfIdx(idx),
      label: `${s.toFixed(1)}s`,
      major: Math.abs(s - Math.round(s)) < 1e-9,
    });
  }
  const endX = xOfIdx(view.endIdx);
  const receivers = view.data.model.receivers;

  return (
    <section className="panel timeline" aria-label="Playback and timeline">
      <header className="tl-head">
        <h2>Playback &amp; timeline</h2>
        <div className="controls">
          <button
            className="ctl"
            onClick={() => dispatch({ type: 'seek', frame: 0 })}
            aria-label="Restart (Home)"
            title="Restart (Home)"
          >
            ⏮
          </button>
          <button
            className="ctl ctl-wide primary"
            onClick={() => dispatch({ type: state.playing ? 'pause' : 'play' })}
            aria-label={state.playing ? 'Pause (Space)' : 'Play (Space)'}
          >
            {state.playing ? '❚❚ Pause' : '▶ Play'}
          </button>
          <button
            className="ctl"
            onClick={() => dispatch({ type: 'seek', frame: i - 1 })}
            aria-label="Step back 0.1 s (←)"
            title="Step back 0.1 s (←)"
          >
            −0.1s
          </button>
          <button
            className="ctl"
            onClick={() => dispatch({ type: 'seek', frame: i + 1 })}
            aria-label="Step 0.1 s (→)"
            title="Step 0.1 s (→)"
          >
            +0.1s
          </button>
          <label className="speed">
            <span className="sr-only">Speed</span>
            <select
              value={state.speed}
              onChange={(e) => dispatch({ type: 'speed', speed: Number(e.target.value) })}
            >
              {SPEEDS.map((s) => (
                <option key={s} value={s}>{`${s}×`}</option>
              ))}
            </select>
          </label>
          <span className="readout" aria-live="off">
            <b>{`${t >= 0 ? '' : '−'}${Math.abs(t).toFixed(1)} s`}</b>
            {` · frame ${frameId}`}
          </span>
        </div>
      </header>

      <div className="chips" role="group" aria-label="Flag filters">
        {CHIPS.map((c) => (
          <button
            key={c.id}
            className={`chip-btn${chipActive(c, state.flagGroups) ? ' on' : ''}`}
            aria-pressed={chipActive(c, state.flagGroups)}
            onClick={() =>
              dispatch({ type: 'flagGroups', groups: toggleChip(c, state.flagGroups) })
            }
          >
            {c.label}
            {c.id === 'windows' &&
            state.selectedId != null &&
            view.receiverCol.has(state.selectedId)
              ? ` · #${view.byId.get(state.selectedId)?.jersey}`
              : ''}
          </button>
        ))}
        <span className="chip-legend">
          <span className="mk mk-trk" /> tracking event <span className="mk mk-mdl" /> model flag
        </span>
      </div>

      <div className="tl-grid">
        <div className="tl-label" />
        <div className="tl-track" ref={track}>
          {/* flags */}
          <svg className="flag-row" width={w} height={34}>
            {clusters.map((c) => {
              const f = c.flags[0];
              const multi = c.flags.length > 1;
              const model = c.flags.every((x) => x.source === 'model');
              const label = multi
                ? `${c.flags.length} flags: ${c.flags.map((x) => x.label).join(', ')}`
                : flagAria(f);
              return (
                <g
                  key={`${c.x}-${f.id}`}
                  transform={`translate(${c.x} 20)`}
                  className="flag"
                  role="button"
                  tabIndex={0}
                  aria-label={label}
                  onClick={() => (multi ? setOpen(c) : seekToFlag(f))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      if (multi) setOpen(c);
                      else seekToFlag(f);
                    }
                  }}
                >
                  <title>
                    {multi
                      ? label
                      : `${f.label} · ${f.source} · frame ${f.frameId} · ${f.t.toFixed(1)} s${f.reason ? `\n${f.reason}` : ''}`}
                  </title>
                  <rect x={-8} y={-18} width={16} height={32} className="flag-hit" />
                  {model ? (
                    <circle r={5} className="flag-mdl" />
                  ) : (
                    <rect
                      x={-4.5}
                      y={-4.5}
                      width={9}
                      height={9}
                      transform="rotate(45)"
                      className="flag-trk"
                    />
                  )}
                  {labelled.has(c) && (
                    <text y={-9} textAnchor="middle" className="flag-label">
                      {shortLabel(c)}
                    </text>
                  )}
                  {multi && (
                    <g transform="translate(7 -7)">
                      <circle r={6} className="badge" />
                      <text y={3} textAnchor="middle" className="badge-text">
                        {c.flags.length}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
          </svg>
          {open && (
            <div
              className="flag-pop"
              style={{ left: Math.min(Math.max(0, open.x - 110), w - 240) }}
              role="dialog"
              aria-label="Flags at this point"
            >
              {open.flags.map((f) => (
                <button key={f.id} onClick={() => seekToFlag(f)}>
                  <span className={f.source === 'model' ? 'mk mk-mdl' : 'mk mk-trk'} />
                  {`${f.t.toFixed(1)} s · ${f.label}`}
                  {f.reason && <small>{f.reason}</small>}
                </button>
              ))}
              <button className="close" onClick={() => setOpen(null)}>
                Close
              </button>
            </div>
          )}

          {/* scrubber */}
          <div
            id="playhead-slider"
            className="scrubber"
            role="slider"
            tabIndex={0}
            aria-label="Playhead"
            aria-valuemin={0}
            aria-valuemax={n - 1}
            aria-valuenow={i}
            aria-valuetext={`${t.toFixed(1)} seconds, frame ${frameId}`}
            onMouseDown={(e) => {
              seekFromEvent(e);
              const move = (ev: MouseEvent) => {
                const rect = track.current!.getBoundingClientRect();
                dispatch({ type: 'seek', frame: idxOfX(ev.clientX - rect.left) });
              };
              const up = () => {
                window.removeEventListener('mousemove', move);
                window.removeEventListener('mouseup', up);
              };
              window.addEventListener('mousemove', move);
              window.addEventListener('mouseup', up);
            }}
          >
            <svg width={w} height={30}>
              <rect
                x={endX}
                y={6}
                width={Math.max(0, xOfIdx(n - 1) - endX)}
                height={14}
                className="air"
              >
                <title>Ball in air: tracking ends 0.5 s after the throw, sack or scramble</title>
              </rect>
              <text x={xOfIdx(n - 1)} y={3} textAnchor="end" className="air-text">
                {view.data.meta.endType === 'throw'
                  ? 'ball in air · tracking ends'
                  : 'tracking ends'}
              </text>
              <line x1={PAD} x2={w - PAD} y1={13} y2={13} className="rail" />
              <line
                x1={xOfIdx(view.snapIdx)}
                x2={xOfIdx(Math.min(i, view.endIdx))}
                y1={13}
                y2={13}
                className="rail-fill"
              />
              {ticks.map((tk) => (
                <g key={tk.label} transform={`translate(${tk.x} 0)`}>
                  <line y1={18} y2={tk.major ? 23 : 21} className="tick" />
                  {tk.major && (
                    <text y={30} textAnchor="middle" className="tick-text">
                      {tk.label}
                    </text>
                  )}
                </g>
              ))}
              <line
                x1={xOfIdx(state.frame)}
                x2={xOfIdx(state.frame)}
                y1={0}
                y2={26}
                className="strip-head"
              />
              <circle cx={xOfIdx(state.frame)} cy={13} r={6} className="handle" />
            </svg>
          </div>
        </div>
      </div>

      <OptionValueChart view={view} width={w} xOfIdx={xOfIdx} />

      <div className="strips-head">
        <button
          className="link-btn"
          onClick={() => setStripsOpen((v) => !v)}
          aria-expanded={stripsOpen}
        >
          {stripsOpen ? '▾' : '▸'} Receiver attention{' '}
          <span className="muted">(defender-equivalents, model)</span>
        </button>
        <span className="ramp-legend">
          Lower <span className="ramp" /> Higher · <span className="win-key" /> open window (margin
          ≥ +0.3 s)
        </span>
      </div>
      {stripsOpen && (
        <div className="tl-grid strips">
          {receivers.map((id) => {
            const p = view.byId.get(id)!;
            const j = view.offenseCol.get(id)!;
            const k = view.receiverCol.get(id)!;
            const sel = id === state.selectedId;
            const spans = windowSpans(view, k);
            return (
              <div key={id} className={`strip-row${sel ? ' selected' : ''}`}>
                <button
                  className="tl-label strip-label"
                  onClick={() => dispatch({ type: 'select', id: sel ? null : id })}
                  onMouseEnter={() => dispatch({ type: 'hover', id })}
                  onMouseLeave={() => dispatch({ type: 'hover', id: null })}
                  title={p.name}
                >
                  <b>{`#${p.jersey}`}</b> {p.position} {lastName(p.name)}
                </button>
                <svg className="strip" width={w} height={18} onClick={seekFromEvent}>
                  {view.data.model.attention.A.map((row, fi) => {
                    const a = row[j];
                    if (a == null) return null;
                    const x0 = fi === 0 ? 0 : (xOfIdx(fi - 1) + xOfIdx(fi)) / 2;
                    const x1 = fi === n - 1 ? w : (xOfIdx(fi) + xOfIdx(fi + 1)) / 2;
                    return (
                      <rect
                        key={fi}
                        x={x0}
                        y={2}
                        width={x1 - x0 + 0.5}
                        height={14}
                        fill={rampColor(a)}
                      />
                    );
                  })}
                  <line
                    x1={xOfIdx(state.frame)}
                    x2={xOfIdx(state.frame)}
                    y1={0}
                    y2={18}
                    className="strip-head"
                  />
                  {spans.map(([a, b]) => (
                    <g key={`${a}-${b}`}>
                      <rect
                        x={xOfIdx(a) - 2}
                        y={1}
                        width={xOfIdx(b) - xOfIdx(a) + 4}
                        height={16}
                        rx={3}
                        className="win-span"
                      />
                      {xOfIdx(b) - xOfIdx(a) > 74 && (
                        <text x={xOfIdx(a) + 5} y={13} className="win-text">
                          Open window
                        </text>
                      )}
                    </g>
                  ))}
                </svg>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function OptionValueChart({ view, width, xOfIdx }: { view: PlayView; width: number; xOfIdx: (i: number) => number }) {
  const { state } = useUi();
  const [open, setOpen] = useState(true);
  const end = view.endIdx;
  const start = view.snapIdx;
  const values = view.data.model.ev.slice(start, end + 1).flat().filter((v): v is number => v != null && Number.isFinite(v));
  const lo = Math.min(-0.5, ...values);
  const hi = Math.max(0.5, ...values);
  const height = 150;
  const top = 10;
  const bottom = 120;
  const yOf = (v: number) => bottom - ((v - lo) / Math.max(0.1, hi - lo)) * (bottom - top);
  const target = view.data.result.targetId;
  const i = Math.max(start, Math.min(end, Math.round(state.frame)));
  const current = view.data.model.ev[i];
  const bestK = current?.reduce<number>((best, v, k) => v != null && (current[best] == null || v > current[best]!) ? k : best, 0) ?? 0;
  const best = view.data.model.receivers[bestK];
  const pathFor = (k: number) => {
    const points: string[] = [];
    for (let f = start; f <= end; f++) {
      const v = view.data.model.ev[f]?.[k];
      if (v != null && Number.isFinite(v)) points.push(`${xOfIdx(f)},${yOf(v)}`);
    }
    return points.join(' ');
  };
  return <div className="value-chart-wrap">
    <div className="value-chart-head">
      <button className="link-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>{open ? '▾' : '▸'} Expected pass EPA over time</button>
      <span>Model estimate · <i className="value-key value-key-best"/> best now · <i className="value-key value-key-actual"/> actual target · grey other options</span>
    </div>
    {open && <div className="tl-grid value-chart-grid"><div className="tl-label value-axis-label">Expected<br/>EPA</div><svg className="value-chart" width={width} height={height} role="img" aria-label="Expected pass EPA for each receiver from snap to end event">
      {[lo, 0, hi].map((v) => <g key={v}><line x1={xOfIdx(start)} x2={xOfIdx(end)} y1={yOf(v)} y2={yOf(v)} className="value-grid"/><text x={xOfIdx(start) - 3} y={yOf(v) + 3} textAnchor="end" className="value-tick">{v.toFixed(1)}</text></g>)}
      {view.data.model.receivers.map((id, k) => <polyline key={id} points={pathFor(k)} className={`value-line${id === target ? ' value-actual' : ''}${id === best ? ' value-best' : ''}`}><title>{`#${view.byId.get(id)?.jersey} ${lastName(view.byId.get(id)?.name ?? '')}`}</title></polyline>)}
      {view.throwIdx != null && <line x1={xOfIdx(view.throwIdx)} x2={xOfIdx(view.throwIdx)} y1={top} y2={bottom} className="value-throw"/>}
      <line x1={xOfIdx(state.frame)} x2={xOfIdx(state.frame)} y1={top} y2={bottom} className="value-head"/>
      {view.data.model.receivers.map((id, k) => {
        const v = current?.[k];
        return v == null ? null : <circle key={id} cx={xOfIdx(i)} cy={yOf(v)} r={id === best || id === target ? 4 : 2.5} className={`value-point${id === target ? ' value-actual' : ''}${id === best ? ' value-best' : ''}`}><title>{`#${view.byId.get(id)?.jersey}: ${v >= 0 ? '+' : ''}${v.toFixed(2)} EPA at ${view.data.frames.t[i].toFixed(1)} s`}</title></circle>;
      })}
      <text x={xOfIdx(end)} y={height - 5} textAnchor="end" className="value-tick">{view.data.meta.endType === 'throw' ? 'Release' : 'End event'}</text>
    </svg></div>}
  </div>;
}

const shortLabel = (c: Cluster): string => {
  const l = c.flags.length > 1 ? `${c.flags[0].label} +${c.flags.length - 1}` : c.flags[0].label;
  return l.length > 22 ? l.slice(0, 21) + '…' : l;
};

/** Greedy label placement: key (tracking) flags first, then the rest, skipping any label that would overlap. */
function labelPlacement(clusters: Cluster[], width: number): Set<Cluster> {
  const charPx = 6.1;
  const placed: [number, number][] = [];
  const out = new Set<Cluster>();
  const order = [...clusters].sort(
    (a, b) =>
      Number(b.flags.some((f) => f.group === 'key')) -
        Number(a.flags.some((f) => f.group === 'key')) || a.x - b.x,
  );
  for (const c of order) {
    const half = (shortLabel(c).length * charPx) / 2;
    const lo = Math.max(0, c.x - half);
    const hi = Math.min(width, c.x + half);
    if (placed.every(([a, b]) => hi + 6 < a || lo - 6 > b)) {
      placed.push([lo, hi]);
      out.add(c);
    }
  }
  return out;
}

function flagAria(f: Flag): string {
  return `${f.label}, ${f.source === 'tracking' ? 'tracking event' : 'model flag'}, frame ${f.frameId}, ${f.t.toFixed(1)} seconds`;
}
