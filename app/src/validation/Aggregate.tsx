import { useMemo, useState } from 'react';
import {
  calibration,
  filteredRows,
  qbSummary,
  type AggregateData,
  type AggregateRow,
  type TimeBucket,
} from './stats';

const fmt = (n: number) => n.toLocaleString('en-US');

export default function Aggregate({ data }: { data: AggregateData }) {
  const [coverage, setCoverage] = useState('All');
  const [time, setTime] = useState<TimeBucket>('all');
  const rows = useMemo(() => filteredRows(data.rows, coverage, time), [data.rows, coverage, time]);
  const qbs = useMemo(() => qbSummary(rows), [rows]);
  const cal = useMemo(() => calibration(rows), [rows]);
  const same = rows.filter((r) => r.samePick).length;

  return (
    <main className="aggregate">
      <section className="aggregate-intro">
        <div>
          <span className="eyebrow">2021 season · weeks 1–8 · release frame</span>
          <h2>Do the estimates hold up?</h2>
          <p>
            {data.scope}. The completion model was trained on weeks 1–6; the calibration chart
            uses weeks 7–8 only. EPA and attention remain model estimates.
          </p>
        </div>
        <div className="aggregate-stats">
          <div><b>{fmt(rows.length)}</b><span>matched throws in view</span></div>
          <div><b>{rows.length ? `${Math.round((100 * same) / rows.length)}%` : '–'}</b><span>model and QB agree</span></div>
          <div><b>{fmt(cal.n)}</b><span>held-out throws</span></div>
        </div>
      </section>

      <div className="aggregate-filters" role="group" aria-label="Aggregate filters">
        <label>Coverage
          <select value={coverage} onChange={(e) => setCoverage(e.target.value)}>
            <option>All</option><option>Man</option><option>Zone</option>
          </select>
        </label>
        <label>Time to throw
          <select value={time} onChange={(e) => setTime(e.target.value as TimeBucket)}>
            <option value="all">All times</option>
            <option value="quick">Under 2.5 s</option>
            <option value="medium">2.5–3.4 s</option>
            <option value="long">3.5 s or more</option>
          </select>
        </label>
        <span>All charts except attention sanity follow these filters.</span>
      </div>

      <div className="aggregate-grid">
        <section className="panel validation-card gap-card">
          <div className="validation-head"><div><span className="eyebrow">01 / Decision quality</span><h3>QB decision gap</h3></div><span className="validation-unit">Expected EPA · lower is better</span></div>
          <p className="validation-caption">Mean of best pass EPA minus targeted pass EPA; 90% bootstrap interval. QBs need at least 50 eligible throws in the current filter. n = {fmt(rows.length)} throws; {qbs.length} QBs shown.</p>
          {qbs.length ? <GapPlot qbs={qbs} /> : <p className="empty">No QB has 50 eligible throws with these filters.</p>}
        </section>

        <section className="panel validation-card calibration-card">
          <div className="validation-head"><div><span className="eyebrow">02 / Held-out check</span><h3>Catch probability calibration</h3></div><span className="validation-unit">Weeks 7–8</span></div>
          <p className="validation-caption">Predicted completion probability versus actual completion rate, grouped into ten bins. n = {fmt(cal.n)} targeted throws. Brier score {cal.brier == null ? '–' : cal.brier.toFixed(3)}; lower is better.</p>
          {cal.n ? <CalibrationPlot bins={cal.bins} /> : <p className="empty">No held-out throws in this filter.</p>}
        </section>

        <section className="panel validation-card attention-card">
          <div className="validation-head"><div><span className="eyebrow">03 / Attention sanity</span><h3>Man versus zone</h3></div><span className="validation-unit">Model weight</span></div>
          <p className="validation-caption">Largest player attention share per coverage defender at release. Man median {data.attention.manMedian.toFixed(2)} (n = {fmt(data.attention.manN)}) versus zone {data.attention.zoneMedian.toFixed(2)} (n = {fmt(data.attention.zoneN)}). First-block assignment agreement: {data.attention.blockTotal ? `${Math.round((100 * data.attention.blockHits) / data.attention.blockTotal)}%` : '–'} of {fmt(data.attention.blockTotal)} rushers.</p>
          <AttentionPlot attention={data.attention} />
        </section>

        <section className="panel validation-card location-card">
          <div className="validation-head"><div><span className="eyebrow">04 / Where choices differ</span><h3>Projected catch locations</h3></div><span className="validation-unit">Relative to line of scrimmage</span></div>
          <p className="validation-caption">Model best pass (cyan) and actual target (magenta) at release. These are projected locations, not observed catch points or alternative outcomes. A deterministic sample of up to 500 of {fmt(rows.length)} plays is drawn.</p>
          <LocationPlot rows={rows} />
        </section>
      </div>
      <p className="aggregate-foot">Scope: {fmt(data.replayablePlays)} replayable of {fmt(data.indexedPlays)} indexed plays; {fmt(data.eligibleThrows)} eligible targeted throws. Decision gaps compare pass targets only. {data.model}.</p>
    </main>
  );
}

function GapPlot({ qbs }: { qbs: ReturnType<typeof qbSummary> }) {
  const max = Math.max(0.5, ...qbs.map((q) => q.hi)) * 1.08;
  const width = 660;
  const x = (v: number) => 190 + (Math.min(v, max) / max) * 430;
  const height = 48 + 31 * qbs.length;
  return (
    <div className="plot-scroll">
      <svg className="validation-plot gap-plot" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="QB mean decision gap and 90 percent bootstrap intervals">
        {[0, 0.25, 0.5, 0.75, 1].map((p) => <g key={p}><line x1={x(max * p)} x2={x(max * p)} y1={16} y2={height - 23} className="plot-grid"/><text x={x(max * p)} y={height - 7} className="plot-tick" textAnchor="middle">{(max * p).toFixed(1)}</text></g>)}
        {qbs.map((q, i) => {
          const y = 24 + i * 31;
          return <g key={q.qb}><text x={4} y={y + 4} className="plot-label">{q.qb}</text><text x={172} y={y + 4} textAnchor="end" className="plot-n">{q.n}</text><line x1={x(q.lo)} x2={x(q.hi)} y1={y} y2={y} className="gap-interval"/><line x1={x(q.lo)} x2={x(q.lo)} y1={y - 4} y2={y + 4} className="gap-interval"/><line x1={x(q.hi)} x2={x(q.hi)} y1={y - 4} y2={y + 4} className="gap-interval"/><circle cx={x(q.mean)} cy={y} r={5} className="gap-dot"><title>{`${q.qb}: +${q.mean.toFixed(2)} EPA, n=${q.n}, 90% interval ${q.lo.toFixed(2)}–${q.hi.toFixed(2)}`}</title></circle></g>;
        })}
      </svg>
    </div>
  );
}

function CalibrationPlot({ bins }: { bins: ReturnType<typeof calibration>['bins'] }) {
  const x = (v: number) => 48 + v * 490;
  const y = (v: number) => 258 - v * 220;
  const points = bins.filter((b) => b.n > 0 && b.predicted != null && b.observed != null);
  return <svg className="validation-plot" viewBox="0 0 570 292" role="img" aria-label="Catch probability calibration plot">
    {[0, 0.25, 0.5, 0.75, 1].map((v) => <g key={v}><line x1={x(v)} x2={x(v)} y1={38} y2={258} className="plot-grid"/><line x1={48} x2={538} y1={y(v)} y2={y(v)} className="plot-grid"/><text x={x(v)} y={277} textAnchor="middle" className="plot-tick">{Math.round(v * 100)}%</text><text x={38} y={y(v) + 4} textAnchor="end" className="plot-tick">{Math.round(v * 100)}</text></g>)}
    <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} className="perfect-line"/>
    {points.length > 1 && <polyline points={points.map((b) => `${x(b.predicted!)},${y(b.observed!)}`).join(' ')} className="calibration-line"/>}
    {points.map((b) => <circle key={b.lower} cx={x(b.predicted!)} cy={y(b.observed!)} r={Math.min(10, 3 + Math.sqrt(b.n) / 3)} className="calibration-dot"><title>{`${Math.round(b.lower * 100)}–${Math.round(b.upper * 100)}% bin: predicted ${Math.round(b.predicted! * 100)}%, observed ${Math.round(b.observed! * 100)}%, n=${b.n}`}</title></circle>)}
    <text x={293} y={291} textAnchor="middle" className="plot-axis">Predicted completion probability</text><text x={8} y={32} className="plot-axis">Observed %</text>
  </svg>;
}

function AttentionPlot({ attention }: { attention: AggregateData['attention'] }) {
  const ymax = Math.max(1, ...attention.Man, ...attention.Zone);
  const x = (i: number) => 44 + (i / 20) * 500;
  const y = (n: number) => 220 - (n / ymax) * 175;
  return <svg className="validation-plot" viewBox="0 0 570 265" role="img" aria-label="Distribution of maximum attention weight for man and zone coverage">
    {[0, 0.25, 0.5, 0.75, 1].map((v) => <g key={v}><line x1={x(v * 20)} x2={x(v * 20)} y1={40} y2={220} className="plot-grid"/><text x={x(v * 20)} y={240} textAnchor="middle" className="plot-tick">{v.toFixed(2)}</text></g>)}
    {attention.Man.map((n, i) => <rect key={`m${i}`} x={x(i) + 1} y={y(n)} width={11} height={220 - y(n)} className="hist-man"><title>{`Man ${attention.bins[i].toFixed(2)}–${attention.bins[i + 1].toFixed(2)}: ${n}`}</title></rect>)}
    {attention.Zone.map((n, i) => <rect key={`z${i}`} x={x(i) + 12} y={y(n)} width={11} height={220 - y(n)} className="hist-zone"><title>{`Zone ${attention.bins[i].toFixed(2)}–${attention.bins[i + 1].toFixed(2)}: ${n}`}</title></rect>)}
    <text x={44} y={24} className="plot-legend man-key">■ Man</text><text x={112} y={24} className="plot-legend zone-key">■ Zone</text><text x={294} y={260} textAnchor="middle" className="plot-axis">Largest attention share</text>
  </svg>;
}

function LocationPlot({ rows }: { rows: AggregateRow[] }) {
  const sample = rows.filter((_, i) => i % Math.max(1, Math.ceil(rows.length / 500)) === 0).slice(0, 500);
  const x = (v: number) => 44 + ((Math.max(-12, Math.min(35, v)) + 12) / 47) * 500;
  const y = (v: number) => 240 - (v / 53.3) * 210;
  return <svg className="validation-plot" viewBox="0 0 570 275" role="img" aria-label="Model pick and actual target projected catch locations">
    <rect x={44} y={30} width={500} height={210} className="location-field"/>
    {[-10, 0, 10, 20, 30].map((v) => <g key={v}><line x1={x(v)} x2={x(v)} y1={30} y2={240} className={v === 0 ? 'location-los' : 'plot-grid'}/><text x={x(v)} y={258} textAnchor="middle" className="plot-tick">{v > 0 ? '+' : ''}{v}</text></g>)}
    {sample.map((r) => <g key={`${r.gameId}_${r.playId}`}><circle cx={x(r.targetX)} cy={y(r.targetY)} r={2.5} className="location-target"/><circle cx={x(r.bestX)} cy={y(r.bestY)} r={2.5} className="location-best"/></g>)}
    <text x={44} y={18} className="plot-legend target-key">● Actual target</text><text x={161} y={18} className="plot-legend best-key">● Model best</text><text x={294} y={273} textAnchor="middle" className="plot-axis">Yards from line of scrimmage</text>
  </svg>;
}
