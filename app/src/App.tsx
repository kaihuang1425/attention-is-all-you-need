import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { fetchAggregate, fetchIndex, fetchPlay } from './data/load';
import { frameIndexOf, makeView, type PlayView } from './data/derive';
import type { PlayIndexEntry } from './data/types';
import Field from './field/Field';
import { PassOptionsPanel, PostPlayPanel, PressurePanel, SelectedPanel } from './panels/Panels';
import Timeline from './timeline/Timeline';
import Aggregate from './validation/Aggregate';
import type { AggregateData } from './validation/stats';
import { adjacentFlag, visibleFlags } from './timeline/flags';
import {
  initialState,
  loadSavedLayers,
  makeReducer,
  saveLayers,
  UiContext,
  useUi,
  type HeatMode,
} from './state';

function readUrl() {
  const q = new URLSearchParams(window.location.search);
  const num = (k: string) => (q.get(k) != null && q.get(k) !== '' ? Number(q.get(k)) : null);
  return { game: num('game'), play: num('play'), frame: num('frame'), sel: num('sel') };
}

export default function App() {
  const [tab, setTab] = useState<'play' | 'aggregate'>(() =>
    new URLSearchParams(window.location.search).get('view') === 'aggregate' ? 'aggregate' : 'play',
  );
  const [aggregate, setAggregate] = useState<AggregateData | null>(null);
  const [aggregateError, setAggregateError] = useState<string | null>(null);
  const [index, setIndex] = useState<PlayIndexEntry[] | null>(null);
  const [entry, setEntry] = useState<PlayIndexEntry | null>(null);
  const [view, setView] = useState<PlayView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const viewRef = useRef<PlayView | null>(null);
  viewRef.current = view;
  const reducer = useMemo(() => makeReducer(() => viewRef.current?.nFrames ?? 1), []);
  const [state, dispatch] = useReducer(reducer, initialState);
  const pendingUrl = useRef(readUrl());

  // Load the play list once, then the play named in the URL (or the first one).
  useEffect(() => {
    const saved = loadSavedLayers();
    if (saved)
      dispatch({ type: 'restoreLayers', layers: saved.layers, trailFrames: saved.trailFrames });
    fetchIndex()
      .then((ix) => {
        setIndex(ix.plays);
        const u = pendingUrl.current;
        const fromUrl = ix.plays.find((p) => p.gameId === u.game && p.playId === u.play);
        setEntry(fromUrl ?? ix.plays[0] ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!entry) return;
    let live = true;
    setView(null);
    fetchPlay(entry.file)
      .then((d) => {
        if (!live) return;
        const v = makeView(d);
        viewRef.current = v;
        setView(v);
        const u = pendingUrl.current;
        const same = u.game === d.meta.gameId && u.play === d.meta.playId;
        const frame =
          same && u.frame != null
            ? frameIndexOf(d, u.frame)
            : d.meta.gameId === 2021090900 && d.meta.playId === 1687
              ? Math.min(v.endIdx, v.snapIdx + 18)
              : v.snapIdx;
        dispatch({ type: 'reset', frame, selectedId: same ? u.sel : null });
        pendingUrl.current = { game: null, play: null, frame: null, sel: null };
      })
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [entry]);

  useEffect(() => saveLayers(state.layers, state.trailFrames), [state.layers, state.trailFrames]);

  useEffect(() => {
    if (tab !== 'aggregate' || aggregate) return;
    let live = true;
    fetchAggregate()
      .then((data) => live && setAggregate(data))
      .catch((e: Error) => live && setAggregateError(e.message));
    return () => {
      live = false;
    };
  }, [tab, aggregate]);

  // Keep the URL in sync (deep links: game, play, frame, sel).
  useEffect(() => {
    if (!view || tab !== 'play') return;
    const q = new URLSearchParams();
    q.set('game', String(view.data.meta.gameId));
    q.set('play', String(view.data.meta.playId));
    q.set('frame', String(view.data.frames.frameId[Math.round(state.frame)]));
    if (state.selectedId != null) q.set('sel', String(state.selectedId));
    const url = `${window.location.pathname}?${q.toString()}`;
    if (!state.playing) window.history.replaceState(null, '', url);
  }, [view, state.frame, state.selectedId, state.playing, tab]);

  // Playback: advance the fractional playhead at 10 frames per second times the speed.
  useEffect(() => {
    if (!state.playing || !view || tab !== 'play') return;
    let raf = 0;
    let last = performance.now();
    let f = state.frame;
    const step = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      f = Math.min(view.nFrames - 1, f + dt * 10 * state.speed);
      dispatch({ type: 'tick', frame: f });
      if (f < view.nFrames - 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
    // state.frame is read once when playback starts; ticks own it afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.playing, state.speed, view, tab]);

  // Keyboard shortcuts (not while typing in a form control).
  const onKey = useCallback(
    (e: KeyboardEvent) => {
      const v = viewRef.current;
      if (!v || tab !== 'play') return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      const i = Math.round(state.frame);
      const flags = visibleFlags(v.data.flags, state.flagGroups, state.selectedId);
      switch (e.key) {
        case ' ':
          e.preventDefault();
          dispatch({ type: state.playing ? 'pause' : 'play' });
          break;
        case 'ArrowRight':
          e.preventDefault();
          dispatch({ type: 'seek', frame: i + (e.shiftKey ? 5 : 1) });
          break;
        case 'ArrowLeft':
          e.preventDefault();
          dispatch({ type: 'seek', frame: i - (e.shiftKey ? 5 : 1) });
          break;
        case 'Home':
          dispatch({ type: 'seek', frame: 0 });
          break;
        case 'End':
          dispatch({ type: 'seek', frame: v.nFrames - 1 });
          break;
        case ']':
        case '[': {
          const f = adjacentFlag(flags, v.data.frames.frameId[i], e.key === ']' ? 1 : -1);
          if (f) dispatch({ type: 'seek', frame: frameIndexOf(v.data, f.frameId) });
          break;
        }
        case 'Escape':
          dispatch({ type: 'select', id: null });
          break;
      }
    },
    [state.frame, state.flagGroups, state.selectedId, state.playing, tab],
  );
  useEffect(() => {
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onKey]);

  const ctx = useMemo(() => ({ state, dispatch }), [state]);

  return (
    <UiContext.Provider value={ctx}>
      <div className="app">
        <header className="topbar">
          <div className="brand">
            <h1>Defensive Attention</h1>
          </div>
          <nav className="main-tabs" aria-label="Main views">
            <button
              className={tab === 'play' ? 'active' : ''}
              aria-current={tab === 'play' ? 'page' : undefined}
              onClick={() => setTab('play')}
            >
              Play analysis
            </button>
            <button
              className={tab === 'aggregate' ? 'active' : ''}
              aria-current={tab === 'aggregate' ? 'page' : undefined}
              onClick={() => {
                dispatch({ type: 'pause' });
                setTab('aggregate');
              }}
            >
              Aggregate validation
            </button>
          </nav>
          <span
            className="badge-honest"
            title="Model numbers are estimates; calibration is in progress"
          >
            Model values illustrative
          </span>
        </header>

        {tab === 'play' && error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}

        {tab === 'play' && index && (
          <PlayBar
            index={index}
            entry={entry}
            view={view}
            onPick={(e) => setEntry(e)}
            onReplay={() => {
              if (!view) return;
              dispatch({ type: 'seek', frame: 0 });
              dispatch({ type: 'play' });
            }}
          />
        )}

        {tab === 'aggregate' ? (
          aggregate ? (
            <Aggregate data={aggregate} />
          ) : (
            <div
              className={aggregateError ? 'error' : 'loading'}
              role={aggregateError ? 'alert' : undefined}
            >
              {aggregateError ?? 'Loading validation data…'}
            </div>
          )
        ) : view ? (
          <main className="grid">
            <div className="col-left">
              <div className="field-card">
                <LayerBar />
                <Field view={view} />
                <Legend />
              </div>
              <Timeline view={view} />
            </div>
            <aside className="col-right">
              <PassOptionsPanel view={view} />
              <SelectedPanel view={view} />
              <PressurePanel view={view} />
              <PostPlayPanel view={view} />
              <section className="panel aggregate-shortcut">
                <h2>Aggregate validation</h2>
                <button
                  onClick={() => {
                    dispatch({ type: 'pause' });
                    setTab('aggregate');
                  }}
                >
                  QB decision gaps · Calibration →
                </button>
              </section>
            </aside>
          </main>
        ) : (
          !error && <div className="loading">Loading play…</div>
        )}

        <footer className="foot">
          Recorded 2021 NGS tracking · 1× playback = game speed, not a live feed · Roles: PFF ·
          Results: play-by-play · Estimates: model
        </footer>
      </div>
    </UiContext.Provider>
  );
}

// ------------------------------------------------------------------ play bar

function PlayBar({
  index,
  entry,
  view,
  onPick,
  onReplay,
}: {
  index: PlayIndexEntry[];
  entry: PlayIndexEntry | null;
  view: PlayView | null;
  onPick: (e: PlayIndexEntry) => void;
  onReplay: () => void;
}) {
  const { state, dispatch } = useUi();
  const m = view?.data.meta;
  const ord = (d: number) => ['1st', '2nd', '3rd', '4th'][d - 1] ?? `${d}th`;
  return (
    <div className="playbar">
      <label className="picker">
        <span className="sr-only">Play</span>
        <select
          value={entry ? `${entry.gameId}_${entry.playId}` : ''}
          onChange={(e) => {
            const next = index.find((p) => `${p.gameId}_${p.playId}` === e.target.value);
            if (next) onPick(next);
          }}
        >
          {index.map((p) => (
            <option key={`${p.gameId}_${p.playId}`} value={`${p.gameId}_${p.playId}`}>
              {`${p.star ? '★ ' : ''}${p.label || `${p.title} · ${p.qb} · Q${p.quarter} ${p.gameClock}`}`}
            </option>
          ))}
        </select>
      </label>
      {m && (
        <>
          <span className="pb-strong">{`${m.title} · ${m.qbName} · Q${m.quarter} ${m.gameClock} · ${ord(m.down)} & ${m.yardsToGo}`}</span>
          <span className="pb-item">{`${m.possessionTeam} ${m.offenseScore} · ${m.defensiveTeam} ${m.defenseScore}`}</span>
          <span
            className="pb-chip"
            title={m.personnelO ?? ''}
          >{`${titleCase(m.offenseFormation ?? '')} · ${m.formation}`}</span>
          <button
            className={`pb-chip reveal${state.revealCoverage ? ' on' : ''}`}
            onClick={() => dispatch({ type: 'revealCoverage' })}
            aria-pressed={state.revealCoverage}
          >
            {state.revealCoverage
              ? `${m.pff_passCoverage} (${m.pff_passCoverageType})`
              : 'Reveal coverage'}
          </button>
          <span className="pb-item muted small">{`gameId ${m.gameId} · playId ${m.playId}`}</span>
          <button className="replay" onClick={onReplay}>
            ▶ Replay
          </button>
        </>
      )}
    </div>
  );
}

const titleCase = (s: string) => s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, ' ');

// ------------------------------------------------------------------ layer bar and legend

function LayerBar() {
  const { state, dispatch } = useUi();
  const L = state.layers;
  const toggle = (
    key: 'shadows' | 'edges' | 'projection' | 'trails' | 'catchPoints' | 'showActual',
    label: string,
    title: string,
  ) => (
    <button
      className={`layer-btn${L[key] ? ' on' : ''}`}
      aria-pressed={L[key]}
      onClick={() => dispatch({ type: 'layer', key })}
      title={title}
    >
      {label}
    </button>
  );
  return (
    <details className="layer-menu">
      <summary>Field layers</summary>
      <div className="layerbar" role="toolbar" aria-label="Field layers">
        <label className="layer-select" title="Coverage influence surface (canvas)">
          Heatmap
          <select
            value={L.heat}
            onChange={(e) => dispatch({ type: 'heat', mode: e.target.value as HeatMode })}
          >
            <option value="off">Off</option>
            <option value="defense">Defense influence</option>
            <option value="control">Offense vs defense</option>
          </select>
        </label>
        {toggle(
          'shadows',
          'Shadows',
          'Cone behind each defender as seen from the QB: a straight 2D pass cannot get through (ball height ignored)',
        )}
        {toggle(
          'edges',
          'Attention',
          'Defender → player lines where the attention weight is at least 0.15',
        )}
        {toggle(
          'trails',
          'Trails',
          'Selected player: past frames solid, next frames dashed (tracking)',
        )}
        <label className="layer-select" title="Trail length: frames before and after the playhead">
          Trail ±
          <select
            value={state.trailFrames}
            onChange={(e) => dispatch({ type: 'trailFrames', n: Number(e.target.value) })}
          >
            {[5, 10, 15, 20, 30].map((n) => (
              <option key={n} value={n}>{`${(n / 10).toFixed(1)} s`}</option>
            ))}
          </select>
        </label>
        <button
          className={`layer-btn${state.trailAll ? ' on' : ''}`}
          aria-pressed={state.trailAll}
          onClick={() => dispatch({ type: 'trailAll', value: !state.trailAll })}
          title="Trails for all 22 players"
        >
          All players
        </button>
        {toggle(
          'projection',
          '+0.5 s projection',
          'Where each route runner and coverage defender is heading in 0.5 s at current velocity',
        )}
        {toggle(
          'catchPoints',
          'Catch points',
          'Projected catch point with per-receiver ball flight time, top 3 options + selected',
        )}
        {toggle('showActual', 'Show actual', 'Draw the actual target path before the throw')}
      </div>
    </details>
  );
}

function Legend() {
  const { state } = useUi();
  const L = state.layers;
  return (
    <div className="legend" aria-label="Legend">
      <span>
        <i className="lg-off" /> Offense
      </span>
      <span>
        <i className="lg-def" /> Defense
      </span>
      {L.heat !== 'off' && (
        <span>
          <i className="lg-heat" />{' '}
          {L.heat === 'defense' ? 'Defensive influence' : 'Offense (cyan) vs defense (amber)'}
        </span>
      )}
      {L.shadows && (
        <span>
          <i className="lg-shadow" /> Pass-lane shadow (from QB, 2D)
        </span>
      )}
      {L.edges && (
        <span>
          <i className="lg-edge" /> Attention weight
        </span>
      )}
      {L.trails && (
        <span>
          <i className="lg-trail" /> Path past / <i className="lg-trail-f" /> next (tracking)
        </span>
      )}
      {L.projection && (
        <span>
          <i className="lg-proj" /> Projection +0.5 s
        </span>
      )}
      {L.catchPoints && (
        <span>
          <i className="lg-catch" /> Projected catch point
        </span>
      )}
      <span>
        <i className="lg-pick" /> Model pick (pass)
      </span>
      <span>
        <i className="lg-actual" /> Actual target (after throw)
      </span>
      {L.protection && (
        <span>
          <i className="lg-block" /> First block (PFF)
        </span>
      )}
    </div>
  );
}
