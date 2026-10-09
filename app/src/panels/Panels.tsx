import { useMemo } from 'react';
import {
  lastName,
  optionRows,
  panelFrame,
  playerLabel,
  type OptionRow,
  type PlayView,
  type RankMode,
} from '../data/derive';
import { useUi } from '../state';
import { laneWord, pct, RESULT_TEXT, secs, signed } from './format';
import { whyEpa } from './why';

const MODES: { mode: RankMode; label: string; title: string }[] = [
  {
    mode: 'epa',
    label: 'Exp EPA',
    title:
      'Expected points added: catch probability x value of the catch, plus incompletion and interception branches',
  },
  {
    mode: 'value',
    label: 'Exp yards',
    title: 'pass_options.py value: catch probability x (depth + YAC + first-down bonus)',
  },
  { mode: 'safe', label: 'Safest', title: 'Highest catch probability' },
];

// ------------------------------------------------------------------ pass options

export function PassOptionsPanel({ view }: { view: PlayView }) {
  const { state, dispatch } = useUi();
  const i = Math.round(state.frame);
  const { idx, note } = panelFrame(view, i);
  const rows = useMemo(
    () => (idx == null ? [] : optionRows(view, idx, state.rankMode)),
    [view, idx, state.rankMode],
  );
  const illegal = idx != null && !view.data.model.legal[idx];

  const score = (r: OptionRow): string => {
    if (state.rankMode === 'epa') {
      return signed(r.ev);
    }
    if (state.rankMode === 'value') {
      return `${(r.expectedYards ?? 0).toFixed(1)}`;
    }
    return pct(r.catchPct);
  };
  const unit = state.rankMode === 'epa' ? 'EPA' : state.rankMode === 'value' ? 'yd' : 'catch';

  return (
    <section className="panel options-panel" aria-labelledby="po-h">
      <header className="panel-head">
        <div>
          <h2 id="po-h">Decision options</h2>
          <p className="sub">{`Illustrative model estimates ${note}`}</p>
        </div>
        <label className="rank-select">
          Rank by{' '}
          <select
            aria-label="Rank pass options by"
            value={state.rankMode}
            onChange={(e) => dispatch({ type: 'rankMode', mode: e.target.value as RankMode })}
          >
            {MODES.map((m) => (
              <option key={m.mode} value={m.mode} title={m.title}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      </header>
      {idx == null && <p className="empty">Options appear from the snap (0.0 s).</p>}
      {illegal && <p className="empty">Forward pass no longer legal (QB past the LOS).</p>}
      <div className="option-columns" aria-hidden="true">
        <span>Option</span>
        <span>Catch</span>
        <span>
          {state.rankMode === 'epa' ? 'Exp EPA' : state.rankMode === 'value' ? 'Exp yd' : 'Safe'}
        </span>
        <span>INT</span>
        <span>Arrival margin</span>
        <span>1st down</span>
      </div>
      <ol className="option-list option-table">
        {rows.map((r) => {
          const sel = r.id === state.selectedId;
          return (
            <li key={r.id}>
              <button
                className={`option${r.rank === 1 ? ' top' : ''}${sel ? ' selected' : ''}`}
                onClick={() => dispatch({ type: 'select', id: sel ? null : r.id })}
                onMouseEnter={() => dispatch({ type: 'hover', id: r.id })}
                onMouseLeave={() => dispatch({ type: 'hover', id: null })}
                aria-pressed={sel}
              >
                <span className="option-name">
                  <b>{`#${r.jersey} ${lastName(r.name)}`}</b>
                  {r.rank === 1 && <small className="chip chip-pick">Top pass</small>}
                </span>
                <span className="option-num">{pct(r.catchPct)}</span>
                <span className="option-num option-epa">
                  {score(r)}
                  <small>{unit}</small>
                </span>
                <span className="option-num">{pct((r.pInt ?? 0) * 100, 1)}</span>
                <span className="option-arrival">
                  <small>{`Ball ${secs(r.tBall)} / Def ${secs(r.tDef)}`}</small>
                  <b className={(r.margin ?? 0) >= 0 ? 'pos' : 'neg'}>{`${signed(r.margin)} s`}</b>
                </span>
                <span className="option-down">
                  {r.touchdown
                    ? 'TD if caught'
                    : r.firstDown
                      ? `✓ ${view.data.meta.firstDownLabel}`
                      : `${(r.yardsShort ?? 0).toFixed(0)} yd short`}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="nonpass-note">
        <b>
          Non-pass options <small>· unscored</small>
        </b>
        <div>
          <span>Scramble</span>
          <span>Not modelled</span>
        </div>
        <div>
          <span>Throw away</span>
          <span>Not modelled</span>
        </div>
        <div>
          <span>Hold</span>
          <span>See pocket pressure below</span>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ selected player

export function SelectedPanel({ view }: { view: PlayView }) {
  const { state, dispatch } = useUi();
  const i = Math.round(state.frame);
  const { idx, note } = panelFrame(view, i);
  const rows = useMemo(
    () => (idx == null ? [] : optionRows(view, idx, state.rankMode)),
    [view, idx, state.rankMode],
  );
  const fallback = rows[0]?.id ?? null;
  const id = state.selectedId ?? fallback;
  const p = id != null ? view.byId.get(id) : undefined;
  const whyRows =
    id == null ? rows : [...rows.filter((r) => r.id === id), ...rows.filter((r) => r.id !== id)];
  const why = idx == null || !rows.some((r) => r.id === id) ? '' : whyEpa(whyRows);

  if (!p) {
    return (
      <section className="panel selected-panel">
        <p className="empty">Click a player on the field to inspect him.</p>
      </section>
    );
  }
  const m = view.data.model;
  const fi = idx ?? i;
  const row = rows.find((r) => r.id === p.id);
  const j = view.offenseCol.get(p.id);
  const A = j !== undefined ? m.attention.A[fi]?.[j] : null;

  return (
    <section className="panel selected-panel" aria-live="polite">
      <header className="panel-head">
        <div>
          <h2>{`${p.position} #${p.jersey} ${lastName(p.name)}`}</h2>
          <p className="sub">
            {state.selectedId == null
              ? `Showing the top option ${note} · click a player to inspect`
              : `${p.name} · ${p.side} · ${p.role} · ${note}`}
          </p>
        </div>
        {state.selectedId != null && (
          <button
            className="ghost-btn"
            onClick={() => dispatch({ type: 'select', id: null })}
            aria-label="Clear selection"
          >
            ✕
          </button>
        )}
      </header>

      {p.side === 'offense' && p.role !== 'QB' && (
        <div className="metric-grid">
          <Metric
            label="Attention"
            value={A != null ? A.toFixed(1) : '–'}
            unit="def-equiv"
            note={`defender-equivalents · play avg ${(view.avgA.get(p.id) ?? 0).toFixed(1)}`}
          />
          {row ? (
            <>
              <Metric
                label="Lane"
                value={row.lane != null ? row.lane.toFixed(1) : '–'}
                unit="yd"
                note={`min clearance · ${laneWord(row.lane)} · 2D proxy`}
              />
              <Metric
                label="Arrival"
                value={`${signed(row.margin)} s`}
                unit="margin"
                note={`Ball ${secs(row.tBall)} / Def ${secs(row.tDef)}`}
                tone={(row.margin ?? 0) >= 0 ? 'pos' : 'neg'}
              />
              <Metric
                label="Catch · EPA"
                value={pct(row.catchPct)}
                unit="catch"
                note={`${signed(row.ev)} EPA · INT ${pct((row.pInt ?? 0) * 100, 1)}`}
              />
              {(row.safetyPull ?? 0) >= 0.5 && (
                <Metric
                  label="Safety pull"
                  value={(row.safetyPull ?? 0).toFixed(1)}
                  unit="yd"
                  note="deep safeties moved toward him since the snap"
                />
              )}
            </>
          ) : (
            <p className="empty small">
              {p.role === 'block'
                ? 'Pass blocker: not a target on this play.'
                : 'No pass options on this frame.'}
            </p>
          )}
        </div>
      )}
      {p.side === 'defense' && <DefenderAttention view={view} id={p.id} frame={fi} />}
      {p.role === 'QB' && (
        <p className="empty small">{`Time to ${view.data.meta.endType === 'throw' ? 'throw' : view.data.meta.endType}: ${view.data.meta.timeToEnd.toFixed(1)} s`}</p>
      )}

      {why && (
        <div className="why">
          <h3>Why this window? · model</h3>
          <p>{why}</p>
        </div>
      )}
    </section>
  );
}

function Metric({
  label,
  value,
  unit,
  note,
  tone,
}: {
  label: string;
  value: string;
  unit: string;
  note?: string;
  tone?: 'pos' | 'neg';
}) {
  return (
    <div className="metric">
      <span className="m-label">{label}</span>
      <span className={`m-value ${tone ?? ''}`}>
        {value} <small>{unit}</small>
      </span>
      {note && <span className="m-note">{note}</span>}
    </div>
  );
}

function DefenderAttention({ view, id, frame }: { view: PlayView; id: number; frame: number }) {
  const m = view.data.model.attention;
  const d = m.defense.indexOf(id);
  const edges = (m.edges[frame] ?? [])
    .filter(([dd]) => dd === d)
    .sort((a, b) => b[2] - a[2])
    .slice(0, 4);
  const space = m.space[frame]?.[d] ?? 0;
  const p = view.byId.get(id)!;
  return (
    <div className="def-att">
      <span className="m-label">{`Attention split (model, body orientation + distance) · ${p.role} · aligned ${p.aligned ?? '–'}`}</span>
      {edges.map(([, j, w]) => {
        const o = view.byId.get(m.offense[j]);
        return (
          <div key={j} className="split-row">
            <span>{o ? playerLabel(o) : j}</span>
            <span className="split-bar">
              <span style={{ width: `${100 * w}%` }} />
            </span>
            <b>{w.toFixed(2)}</b>
          </div>
        );
      })}
      <div className="split-row muted">
        <span>Space (no one)</span>
        <span className="split-bar">
          <span style={{ width: `${100 * space}%` }} />
        </span>
        <b>{space.toFixed(2)}</b>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ pocket pressure

export function PressurePanel({ view }: { view: PlayView }) {
  const { state, dispatch } = useUi();
  const i = Math.round(state.frame);
  const { idx } = panelFrame(view, i);
  const pr = idx != null ? view.data.model.pressure[idx] : null;
  const rusher = pr ? view.byId.get(pr.rusherId) : undefined;
  const credits = view.data.players.filter((p) => p.pff && Object.keys(p.pff).length);
  return (
    <section className="panel pressure-panel">
      <header className="panel-head">
        <h2>Pocket pressure</h2>
        <button
          className={`ghost-btn${state.layers.protection ? ' on' : ''}`}
          aria-pressed={state.layers.protection}
          onClick={() => dispatch({ type: 'layer', key: 'protection' })}
        >
          {state.layers.protection ? 'Hide protection' : 'Inspect protection'}
        </button>
      </header>
      <div
        className="meter"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={7}
        aria-valuenow={pr?.level ?? 0}
        aria-label="Pocket pressure level"
      >
        {Array.from({ length: 7 }, (_, k) => (
          <span key={k} className={pr && k < pr.level ? 'lit' : ''} />
        ))}
      </div>
      <p className="pressure-text">
        {pr ? (
          <>
            <b>{pr.text}</b>
            {rusher &&
              ` · nearest rusher #${rusher.jersey} ${lastName(rusher.name)} ${pr.nearest.toFixed(1)} yd`}
            {pr.closing > 0.5 && `, closing ${pr.closing.toFixed(1)} yd/s`}
          </>
        ) : (
          'From the snap to the throw.'
        )}
      </p>
      {state.layers.protection && credits.length > 0 && (
        <div className="pff-credits">
          <span className="m-label">PFF credit (data, not model)</span>
          <ul>
            {credits.map((p) => (
              <li key={p.id}>
                {`#${p.jersey} ${lastName(p.name)}: `}
                {Object.entries(p.pff!)
                  .map(([k, v]) =>
                    v === 1 ? k.replace(/([A-Z])/g, ' $1').toLowerCase() : `${k} ${v}`,
                  )
                  .join(', ')}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ post-play

export function PostPlayPanel({ view }: { view: PlayView }) {
  const r = view.data.result;
  const d = r.decision;
  const qb = view.byId.get(view.qbId);
  const pick = d.bestId != null ? view.byId.get(d.bestId) : undefined;
  const yards =
    r.playResult != null ? `${r.playResult >= 0 ? '' : '−'}${Math.abs(r.playResult)} yd` : '';
  let observed: string;
  if (r.passResult === 'S') observed = `${qb ? lastName(qb.name) : 'QB'} sacked · ${yards}`;
  else if (r.passResult === 'R') observed = `${qb ? lastName(qb.name) : 'QB'} scrambles · ${yards}`;
  else if (r.targetId == null)
    observed = `${RESULT_TEXT[r.passResult]}, no intended receiver listed`;
  else
    observed = `${qb ? lastName(qb.name) : 'QB'} → #${r.targetJersey} ${lastName(r.targetName ?? '')} · ${RESULT_TEXT[r.passResult]}${r.passResult === 'C' ? ` · ${yards}` : ''}`;

  const agree = d.chosen != null && d.best === d.chosen;
  return (
    <section className="panel postplay-panel">
      <header className="panel-head">
        <h2>Post-play · play-by-play data</h2>
      </header>
      <div className="pp-row actual">
        <span className="pp-k">Actual</span>
        <span>{observed}</span>
      </div>
      {pick && (
        <div className="pp-row pick">
          <span className="pp-k">Top pass</span>
          <span>{`#${pick.jersey} ${lastName(pick.name)} at release · ${agree ? 'same as the QB' : 'outcome unknown'}`}</span>
        </div>
      )}
      <div className="pp-gap">
        <div>
          <span className="m-label">Chosen</span>
          <b>
            {d.evChosen != null
              ? `${signed(d.evChosen)} EPA`
              : d.chosen === 'hold'
                ? 'held (sack)'
                : d.chosen === 'scramble'
                  ? 'scramble'
                  : '–'}
          </b>
        </div>
        <div>
          <span className="m-label">Top pass</span>
          <b className="pick-txt">{d.evBest != null ? `${signed(d.evBest)} EPA` : '–'}</b>
        </div>
        <div>
          <span className="m-label">Expected gap</span>
          <b>{d.gap != null ? `${signed(d.gap)} EPA` : '–'}</b>
        </div>
      </div>
      <p className="note">
        Alternative outcome is unknown. Gap compares pass targets only; scramble, throw away and
        hold are unscored{view.data.meta.illustrative ? '; model values are illustrative' : ''}.
      </p>
      {r.description && <p className="desc">{r.description}</p>}
    </section>
  );
}
