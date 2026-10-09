import { memo, useEffect, useMemo, useRef, useState } from 'react';
import {
  ballAt,
  lastName,
  optionRows,
  playerLabel,
  posAt,
  velAt,
  type PlayView,
  type Vec,
} from '../data/derive';
import type { PlayerInfo } from '../data/types';
import { useUi } from '../state';
import HeatCanvas from './HeatCanvas';
import { computeCrop, FIELD_L, FIELD_W, shadowsAt, sy, yardNumber, type Crop } from './geometry';

const DRAW_EDGE_MIN = 0.15;
const R_OFF = 0.95;
const R_DEF = 1.15;

interface Props {
  view: PlayView;
}

export default function Field({ view }: Props) {
  const { state, dispatch } = useUi();
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 900, h: 520 });

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ w: Math.round(width), h: Math.round(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const crop = useMemo(() => computeCrop(view), [view]);
  const glyphScaleX = (size.h * (crop.x1 - crop.x0)) / (size.w * (crop.y1 - crop.y0));
  const f = state.frame;
  const i = Math.round(f);
  const { layers } = state;
  const m = view.data.model;
  const legal = m.legal[i] ?? false;
  const rows = useMemo(() => optionRows(view, i, 'epa'), [view, i]);
  const pick = rows[0]?.id ?? null;
  const selected = state.selectedId != null ? (view.byId.get(state.selectedId) ?? null) : null;
  const focusId = state.hoveredId ?? state.selectedId;
  const afterThrow = view.throwIdx != null && i >= view.throwIdx;
  const target = view.data.result.targetId;
  const showActual =
    target != null && view.data.result.targetIsRouteRunner && (afterThrow || layers.showActual);

  const vb = `${crop.x0} ${sy(crop.y1)} ${crop.x1 - crop.x0} ${crop.y1 - crop.y0}`;
  const qb = posAt(view, view.qbId, f);

  // Catch points for the top 3 options plus the selected receiver.
  const catchIds = new Set(rows.slice(0, 3).map((r) => r.id));
  if (state.selectedId != null && view.receiverCol.has(state.selectedId))
    catchIds.add(state.selectedId);
  const pickRow = rows.find((r) => r.id === pick);
  const actualIdx = view.throwIdx ?? view.endIdx;
  const actualK = target != null ? view.receiverCol.get(target) : undefined;
  const actualCatch: Vec | null =
    actualK !== undefined && m.catchX[actualIdx]?.[actualK] != null
      ? { x: m.catchX[actualIdx][actualK] as number, y: m.catchY[actualIdx][actualK] as number }
      : null;
  const qbAtThrow = posAt(view, view.qbId, actualIdx);

  return (
    <div className="field-wrap" ref={wrap}>
      <svg
        className="field-svg field-bg"
        viewBox={vb}
        preserveAspectRatio="none"
        width={size.w}
        height={size.h}
        aria-hidden="true"
      >
        <Surface crop={crop} heat={layers.heat !== 'off'} />
      </svg>
      <HeatCanvas
        view={view}
        frame={f}
        crop={crop}
        mode={layers.heat}
        width={size.w}
        height={size.h}
      />
      <svg
        className="field-svg field-fg"
        viewBox={vb}
        preserveAspectRatio="none"
        width={size.w}
        height={size.h}
        role="img"
        aria-label={`Field at ${view.data.frames.t[i]?.toFixed(1)} s after the snap`}
        onClick={() => dispatch({ type: 'select', id: null })}
      >
        <defs>
          <marker
            id="arrow-pick"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="var(--model-pick)" />
          </marker>
          <marker
            id="arrow-actual"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="var(--actual)" />
          </marker>
          <marker
            id="arrow-proj"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="4"
            markerHeight="4"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="var(--projection)" />
          </marker>
          <clipPath id="field-clip">
            <rect x={0} y={0} width={FIELD_L} height={FIELD_W} />
          </clipPath>
        </defs>

        {layers.shadows && <Shadows view={view} frame={f} />}
        <Lines view={view} crop={crop} />
        {layers.protection && <Protection view={view} frame={f} />}
        {layers.edges && <Edges view={view} frame={i} at={f} focusId={focusId} />}
        {layers.trails && (
          <Trails
            view={view}
            frame={f}
            n={state.trailFrames}
            ids={
              state.trailAll
                ? view.data.players.map((p) => p.id)
                : focusIds(state.selectedId, state.hoveredId)
            }
          />
        )}
        {layers.projection && <Projections view={view} frame={i} />}

        {layers.catchPoints && legal && qb && (
          <g className="catch-points">
            {rows
              .filter((r) => catchIds.has(r.id) && r.catchX != null && r.catchY != null)
              .map((r) => (
                <g key={r.id}>
                  <circle
                    cx={r.catchX!}
                    cy={sy(r.catchY!)}
                    r={1.1}
                    className={`catch-circle${r.id === pick ? ' is-pick' : ''}`}
                  />
                  {(r.id === pick || r.id === state.selectedId) && (() => {
                    const label = `#${r.jersey} · ${r.tBall?.toFixed(1)} s flight`;
                    const left = r.catchX! + 1.5 + 0.62 * label.length > crop.x1;
                    return (
                      <text
                        x={left ? r.catchX! - 1.5 : r.catchX! + 1.5}
                        y={sy(r.catchY!) + (sy(r.catchY!) - 1.5 < sy(crop.y1) ? 2.2 : -1.0)}
                        textAnchor={left ? 'end' : 'start'}
                        className="catch-label"
                      >
                        {label}
                      </text>
                    );
                  })()}
                </g>
              ))}
            {pickRow && pickRow.catchX != null && (
              <line
                x1={qb.x}
                y1={sy(qb.y)}
                x2={pickRow.catchX}
                y2={sy(pickRow.catchY!)}
                className="path-pick"
                markerEnd="url(#arrow-pick)"
              />
            )}
          </g>
        )}
        {showActual && actualCatch && qbAtThrow && (
          <line
            x1={qbAtThrow.x}
            y1={sy(qbAtThrow.y)}
            x2={actualCatch.x}
            y2={sy(actualCatch.y)}
            className="path-actual"
            markerEnd="url(#arrow-actual)"
          />
        )}

        <Players
          view={view}
          frame={f}
          selectedId={state.selectedId}
          hoveredId={state.hoveredId}
          pickId={legal ? pick : null}
          actualId={showActual ? target : null}
          glyphScaleX={glyphScaleX}
          onSelect={(id) => dispatch({ type: 'select', id })}
          onHover={(id) => dispatch({ type: 'hover', id })}
        />
        <Ball view={view} frame={f} />
        {selected && <Callout view={view} frame={f} p={selected} glyphScaleX={glyphScaleX} />}
      </svg>
      <Tooltip view={view} frame={i} crop={crop} size={size} />
      <div className="attack-tag" aria-hidden="true">
        Attack <span>→</span>
      </div>
    </div>
  );
}

function focusIds(sel: number | null, hov: number | null): number[] {
  const s = new Set<number>();
  if (sel != null) s.add(sel);
  if (hov != null) s.add(hov);
  return [...s];
}

// ------------------------------------------------------------------ surface and lines

const Surface = memo(function Surface({ crop, heat }: { crop: Crop; heat: boolean }) {
  const lines = [];
  for (let x = 10; x <= 110; x += 5) lines.push(x);
  const hashes = [];
  for (let x = 11; x < 110; x++) if (x % 5) hashes.push(x);
  const nums = [20, 30, 40, 50, 60, 70, 80, 90, 100];
  return (
    <g className="surface">
      <rect
        x={crop.x0 - 5}
        y={sy(crop.y1) - 5}
        width={crop.x1 - crop.x0 + 10}
        height={crop.y1 - crop.y0 + 10}
        className="oob"
      />
      <rect
        x={0}
        y={0}
        width={FIELD_L}
        height={FIELD_W}
        className={heat ? 'turf turf-muted' : 'turf'}
      />
      {lines.map((x) =>
        x % 10 === 5 ? null : (
          <rect key={`s${x}`} x={x} y={0} width={5} height={FIELD_W} className="stripe" />
        ),
      )}
      <rect x={0} y={0} width={10} height={FIELD_W} className="endzone" />
      <rect x={110} y={0} width={10} height={FIELD_W} className="endzone" />
      {lines.map((x) => (
        <line
          key={x}
          x1={x}
          x2={x}
          y1={0}
          y2={FIELD_W}
          className={x === 10 || x === 110 ? 'goal-line' : 'yard-line'}
        />
      ))}
      {hashes.map((x) => (
        <g key={`h${x}`} className="hash">
          <line x1={x} x2={x} y1={0.3} y2={1.0} />
          <line x1={x} x2={x} y1={sy(23.58) - 0.35} y2={sy(23.58) + 0.35} />
          <line x1={x} x2={x} y1={sy(29.72) - 0.35} y2={sy(29.72) + 0.35} />
          <line x1={x} x2={x} y1={FIELD_W - 1.0} y2={FIELD_W - 0.3} />
        </g>
      ))}
      {nums.map((x) => (
        <g key={`n${x}`} className="yard-num">
          <text x={x} y={sy(12) + 1.0} textAnchor="middle">
            {yardNumber(x)}
          </text>
          <text x={x} y={sy(FIELD_W - 12) + 1.0} textAnchor="middle">
            {yardNumber(x)}
          </text>
        </g>
      ))}
      <rect x={0} y={0} width={FIELD_L} height={FIELD_W} className="sideline" />
    </g>
  );
});

function Lines({ view, crop }: { view: PlayView; crop: Crop }) {
  const m = view.data.meta;
  const tagY = Math.min(sy(crop.y0) - 1.3, FIELD_W + 1.6);
  const los = `LOS · ${m.losLabel}`;
  const fd = `1st down · ${m.firstDownLabel}`;
  const wOf = (t: string) => 0.68 * t.length + 1.2;
  return (
    <g className="scrimmage">
      <line x1={m.los_x} x2={m.los_x} y1={0} y2={FIELD_W} className="los" />
      <line x1={m.firstDown_x} x2={m.firstDown_x} y1={0} y2={FIELD_W} className="first-down" />
      {/* LOS tag sits left of its line, first-down tag right of its line, so they never overlap. */}
      <g transform={`translate(${m.los_x - 0.4 - wOf(los)}, ${tagY})`}>
        <rect x={0} y={-1.2} width={wOf(los)} height={2.1} rx={0.35} className="tag tag-los" />
        <text x={wOf(los) / 2} textAnchor="middle" y={0.4} className="tag-text">
          {los}
        </text>
      </g>
      <g transform={`translate(${m.firstDown_x + 0.4}, ${tagY})`}>
        <rect x={0} y={-1.2} width={wOf(fd)} height={2.1} rx={0.35} className="tag tag-fd" />
        <text x={wOf(fd) / 2} textAnchor="middle" y={0.4} className="tag-text tag-text-dark">
          {fd}
        </text>
      </g>
    </g>
  );
}

// ------------------------------------------------------------------ layers

function Shadows({ view, frame }: { view: PlayView; frame: number }) {
  const shadows = shadowsAt(view, frame);
  return (
    <g className="shadows" clipPath="url(#field-clip)">
      <defs>
        {shadows.map((s) => (
          <linearGradient
            key={s.id}
            id={`sh-${s.id}`}
            gradientUnits="userSpaceOnUse"
            x1={s.from.x}
            y1={sy(s.from.y)}
            x2={s.to.x}
            y2={sy(s.to.y)}
          >
            <stop offset="0" stopColor="var(--shadow)" stopOpacity={0.62 * s.strength} />
            <stop offset="0.55" stopColor="var(--shadow)" stopOpacity={0.3 * s.strength} />
            <stop offset="1" stopColor="var(--shadow)" stopOpacity={0} />
          </linearGradient>
        ))}
      </defs>
      {shadows.map((s) => (
        <polygon
          key={s.id}
          points={s.points.map((p) => `${p.x},${sy(p.y)}`).join(' ')}
          fill={`url(#sh-${s.id})`}
        />
      ))}
    </g>
  );
}

function Edges({
  view,
  frame,
  at,
  focusId,
}: {
  view: PlayView;
  frame: number;
  at: number;
  focusId: number | null;
}) {
  const att = view.data.model.attention;
  const edges = att.edges[frame] ?? [];
  return (
    <g className="edges">
      {edges
        .filter(([, , w]) => w >= DRAW_EDGE_MIN)
        .map(([d, j, w]) => {
          const did = att.defense[d];
          const oid = att.offense[j];
          const a = posAt(view, did, at);
          const b = posAt(view, oid, at);
          if (!a || !b) return null;
          const focus = focusId == null || focusId === did || focusId === oid;
          return (
            <line
              key={`${d}-${j}`}
              x1={a.x}
              y1={sy(a.y)}
              x2={b.x}
              y2={sy(b.y)}
              className="edge"
              strokeWidth={0.08 + 0.42 * w}
              strokeOpacity={focus ? 0.35 + 0.6 * w : 0.12}
            />
          );
        })}
    </g>
  );
}

function Trails({
  view,
  frame,
  n,
  ids,
}: {
  view: PlayView;
  frame: number;
  n: number;
  ids: number[];
}) {
  const i = Math.round(frame);
  return (
    <g className="trails">
      {ids.map((id) => {
        const p = view.byId.get(id);
        if (!p) return null;
        const past: Vec[] = [];
        for (let k = Math.max(0, i - n); k <= i; k++) {
          const q = posAt(view, id, k);
          if (q) past.push(q);
        }
        const future: Vec[] = [];
        for (let k = i; k <= Math.min(view.nFrames - 1, i + n); k++) {
          const q = posAt(view, id, k);
          if (q) future.push(q);
        }
        const cls = p.side === 'offense' ? 'trail-off' : 'trail-def';
        const last = future[future.length - 1];
        return (
          <g key={id} className={cls}>
            {past.slice(1).map((q, k) => (
              <line
                key={`p${k}`}
                x1={past[k].x}
                y1={sy(past[k].y)}
                x2={q.x}
                y2={sy(q.y)}
                className="trail-past"
                strokeOpacity={0.15 + (0.75 * (k + 1)) / past.length}
              />
            ))}
            {past.slice(0, -1).map((q, k) => (
              <circle
                key={`pd${k}`}
                cx={q.x}
                cy={sy(q.y)}
                r={0.18}
                className="trail-dot"
                opacity={0.2 + (0.6 * (k + 1)) / past.length}
              />
            ))}
            {future.length > 1 && (
              <polyline
                points={future.map((q) => `${q.x},${sy(q.y)}`).join(' ')}
                className="trail-future"
              />
            )}
            {future.slice(1).map((q, k) => (
              <circle key={`fd${k}`} cx={q.x} cy={sy(q.y)} r={0.16} className="trail-dot-future" />
            ))}
            {future.length > 1 &&
              last &&
              (p.side === 'offense' ? (
                <circle cx={last.x} cy={sy(last.y)} r={R_OFF} className="ghost" />
              ) : (
                <rect
                  x={last.x - R_DEF * 0.72}
                  y={sy(last.y) - R_DEF * 0.72}
                  width={R_DEF * 1.44}
                  height={R_DEF * 1.44}
                  transform={`rotate(45 ${last.x} ${sy(last.y)})`}
                  className="ghost"
                />
              ))}
          </g>
        );
      })}
    </g>
  );
}

function Projections({ view, frame }: { view: PlayView; frame: number }) {
  return (
    <g className="projections">
      {view.data.players
        .filter((p) => p.role === 'route' || p.role === 'coverage')
        .map((p) => {
          const a = posAt(view, p.id, frame);
          if (!a) return null;
          const v = velAt(view, p.id, frame);
          if (Math.hypot(v.x, v.y) < 1) return null;
          const b = { x: a.x + 0.5 * v.x, y: a.y + 0.5 * v.y };
          return (
            <g key={p.id}>
              <line
                x1={a.x}
                y1={sy(a.y)}
                x2={b.x}
                y2={sy(b.y)}
                className="proj-line"
                markerEnd="url(#arrow-proj)"
              />
              <circle cx={b.x} cy={sy(b.y)} r={0.75} className="proj-ghost" />
            </g>
          );
        })}
    </g>
  );
}

function Protection({ view, frame }: { view: PlayView; frame: number }) {
  const assigned = new Set<number>();
  view.data.players.forEach((p) => p.blockedId != null && assigned.add(p.blockedId));
  return (
    <g className="protection">
      {view.data.players
        .filter((p) => p.blockedId != null)
        .map((p) => {
          const a = posAt(view, p.id, frame);
          const b = posAt(view, p.blockedId!, frame);
          if (!a || !b) return null;
          return (
            <g key={p.id}>
              <line x1={a.x} y1={sy(a.y)} x2={b.x} y2={sy(b.y)} className="block-link">
                <title>{`#${p.jersey} → #${view.byId.get(p.blockedId!)?.jersey} · ${p.blockType ?? ''} ${p.blockTypeName ? `(${p.blockTypeName})` : ''}`}</title>
              </line>
            </g>
          );
        })}
      {view.data.players
        .filter((p) => p.role === 'rush' && !assigned.has(p.id))
        .map((p) => {
          const a = posAt(view, p.id, frame);
          if (!a) return null;
          return (
            <g key={`u${p.id}`}>
              <circle cx={a.x} cy={sy(a.y)} r={2.0} className="unassigned-ring" />
              <text x={a.x} y={sy(a.y) + 3.2} textAnchor="middle" className="unassigned-text">
                no first assignment
              </text>
            </g>
          );
        })}
    </g>
  );
}

// ------------------------------------------------------------------ players

interface PlayersProps {
  view: PlayView;
  frame: number;
  selectedId: number | null;
  hoveredId: number | null;
  pickId: number | null;
  actualId: number | null;
  glyphScaleX: number;
  onSelect: (id: number) => void;
  onHover: (id: number | null) => void;
}

function Players({
  view,
  frame,
  selectedId,
  hoveredId,
  pickId,
  actualId,
  glyphScaleX,
  onSelect,
  onHover,
}: PlayersProps) {
  // Defense first so offense discs sit on top where they overlap.
  const order = [...view.data.players].sort((a, b) =>
    a.side === b.side ? 0 : a.side === 'defense' ? -1 : 1,
  );
  return (
    <g className="players">
      {order.map((p) => {
        const q = posAt(view, p.id, frame);
        if (!q) return null;
        const cls = [
          'player',
          p.side,
          p.role === 'QB' ? 'qb' : '',
          p.id === selectedId ? 'selected' : '',
          p.id === hoveredId ? 'hovered' : '',
          p.id === pickId ? 'pick' : '',
          p.id === actualId ? 'actual' : '',
        ]
          .filter(Boolean)
          .join(' ');
        const cx = q.x;
        const cy = sy(q.y);
        return (
          <g
            key={p.id}
            className={cls}
            transform={`translate(${cx} ${cy}) scale(${glyphScaleX} 1)`}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(p.id);
            }}
            onMouseEnter={() => onHover(p.id)}
            onMouseLeave={() => onHover(null)}
            role="button"
            aria-label={`${playerLabel(p)}, ${p.position}, ${p.side}`}
          >
            <circle r={2.0} className="hit" />
            {(p.id === selectedId || p.id === pickId || p.id === actualId) && (
              <circle r={p.side === 'defense' ? 1.75 : 1.55} className="halo" />
            )}
            {p.side === 'offense' ? (
              <circle r={R_OFF} className="body" />
            ) : (
              <rect
                x={-R_DEF * 0.72}
                y={-R_DEF * 0.72}
                width={R_DEF * 1.44}
                height={R_DEF * 1.44}
                transform="rotate(45)"
                className="body"
              />
            )}
            {p.role === 'QB' && <circle r={R_OFF + 0.38} className="qb-ring" />}
            <text y={0.36} textAnchor="middle" className="num">
              {p.jersey}
            </text>
          </g>
        );
      })}
    </g>
  );
}

function Ball({ view, frame }: { view: PlayView; frame: number }) {
  const b = ballAt(view, frame);
  if (!b) return null;
  return <ellipse cx={b.x + 0.55} cy={sy(b.y) - 0.55} rx={0.42} ry={0.27} className="ball" />;
}

function Callout({ view, frame, p, glyphScaleX }: { view: PlayView; frame: number; p: PlayerInfo; glyphScaleX: number }) {
  const q = posAt(view, p.id, frame);
  if (!q) return null;
  const text = `${p.position} #${p.jersey} ${lastName(p.name)}`;
  const w = 0.62 * text.length + 1.2;
  return (
    <g
      className="callout"
      transform={`translate(${q.x + 1.4} ${sy(q.y) - 2.6}) scale(${glyphScaleX} 1)`}
      pointerEvents="none"
    >
      <rect x={0} y={-1.15} width={w} height={1.9} rx={0.3} />
      <text x={0.6} y={0.32}>
        {text}
      </text>
    </g>
  );
}

// ------------------------------------------------------------------ tooltip

function Tooltip({
  view,
  frame,
  crop,
  size,
}: {
  view: PlayView;
  frame: number;
  crop: Crop;
  size: { w: number; h: number };
}) {
  const { state } = useUi();
  const id = state.hoveredId;
  if (id == null) return null;
  const p = view.byId.get(id);
  const q = posAt(view, id, frame);
  if (!p || !q) return null;
  const px = ((q.x - crop.x0) / (crop.x1 - crop.x0)) * size.w;
  const py = ((crop.y1 - q.y) / (crop.y1 - crop.y0)) * size.h;
  const m = view.data.model;
  const lines: string[] = [];
  if (p.side === 'offense' && p.role !== 'QB') {
    const j = view.offenseCol.get(id);
    const A = j !== undefined ? m.attention.A[frame]?.[j] : null;
    if (A != null) lines.push(`Attention ${A.toFixed(2)} defender-equivalents (model)`);
    const k = view.receiverCol.get(id);
    if (k !== undefined && m.legal[frame]) {
      const mg = m.margin[frame][k];
      const pc = m.pCatch[frame][k];
      if (mg != null)
        lines.push(`Arrival margin ${mg >= 0 ? '+' : '−'}${Math.abs(mg).toFixed(2)} s (model)`);
      if (pc != null) lines.push(`Catch ${(100 * pc).toFixed(0)}% (model)`);
    }
  } else if (p.side === 'defense') {
    const d = m.attention.defense.indexOf(id);
    const row = (m.attention.edges[frame] ?? [])
      .filter(([dd]) => dd === d)
      .sort((a, b) => b[2] - a[2])
      .slice(0, 3);
    if (row.length) {
      lines.push(
        'Attention: ' +
          row
            .map(([, j, w]) => `#${view.byId.get(m.attention.offense[j])?.jersey} ${w.toFixed(2)}`)
            .join(' · '),
      );
    }
    const space = m.attention.space[frame]?.[d];
    if (space != null && space > 0.1) lines.push(`On space ${space.toFixed(2)}`);
  }
  return (
    <div
      className="tooltip"
      style={{ left: Math.min(px + 14, size.w - 240), top: Math.max(4, py - 12) }}
      role="status"
    >
      <strong>{`${p.position} #${p.jersey} ${p.name}`}</strong>
      <span className="tt-role">{`${p.side} · ${p.role}${p.aligned ? ` · aligned ${p.aligned}` : ''}`}</span>
      {lines.map((l) => (
        <span key={l}>{l}</span>
      ))}
    </div>
  );
}
