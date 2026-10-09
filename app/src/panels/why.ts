// "Why this window?" sentences. Template based: the top option's two strongest reasons plus,
// when it matters, the teammate who is drawing the defense.
import { explain } from '../data/passOptions';
import { ranking, type OptionRow, type PlayView, type RankMode } from '../data/derive';
import { laneWord, signed } from './format';

interface Reason {
  weight: number;
  text: string;
}

export function whyEpa(rows: OptionRow[]): string {
  if (!rows.length) return '';
  const top = rows[0];
  const others = rows.slice(1);
  const lead: string[] = [];
  const drawer = others.reduce<OptionRow | null>(
    (a, b) => ((b.A ?? 0) > (a?.A ?? 0) ? b : a),
    null,
  );
  if (drawer && (drawer.A ?? 0) >= 1.2 && (drawer.A ?? 0) > (top.A ?? 0) + 0.3) {
    lead.push(`#${drawer.jersey} draws ${(drawer.A ?? 0).toFixed(1)} defenders`);
  }
  const puller = others.reduce<OptionRow | null>(
    (a, b) => ((b.safetyPull ?? 0) > (a?.safetyPull ?? 0) ? b : a),
    null,
  );
  if (puller && (puller.safetyPull ?? 0) >= 2) {
    lead.push(
      `the deep safety has moved ${(puller.safetyPull ?? 0).toFixed(1)} yd toward #${puller.jersey}`,
    );
  }

  const reasons: Reason[] = [];
  const m = top.margin;
  if (m != null) {
    if (m >= 0.3)
      reasons.push({
        weight: m,
        text: `gets to the catch point ${m.toFixed(1)} s before any defender`,
      });
    else if (m < 0) reasons.push({ weight: 0.2, text: `is contested (margin ${signed(m)} s)` });
  }
  if (top.touchdown) reasons.push({ weight: 1.5, text: 'scores if caught' });
  else if (top.firstDown) reasons.push({ weight: 0.8, text: 'reaches the line to gain' });
  if (top.sep != null && top.sep >= 4)
    reasons.push({ weight: top.sep / 8, text: `has ${top.sep.toFixed(1)} yd of space` });
  if (top.lane != null) {
    const w = laneWord(top.lane);
    if (w === 'clear') reasons.push({ weight: 0.5, text: 'has a clear lane' });
    if (w === 'crowded') reasons.push({ weight: 0.1, text: 'has a crowded lane' });
  }
  reasons.sort((a, b) => b.weight - a.weight);
  const body = reasons.slice(0, 2).map((r) => r.text);
  const catchTxt =
    top.catchPct != null ? ` (${top.catchPct.toFixed(0)}% catch, ${signed(top.ev)} EPA)` : '';
  let s = lead.length ? lead.join(' and ') + '; ' : '';
  s = s.charAt(0).toUpperCase() + s.slice(1);
  const subject = `#${top.jersey}`;
  const pred = body.length ? body.join(' and ') : 'has the best expected value';
  const sentence = `${s}${subject} ${pred}${catchTxt}.`;
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

export function whyText(view: PlayView, i: number, mode: RankMode, rows: OptionRow[]): string {
  if (mode === 'epa') return whyEpa(rows);
  const r = ranking(view, i);
  if (!r) return '';
  return explain(r.options, mode === 'value' ? 'value' : 'safe');
}
