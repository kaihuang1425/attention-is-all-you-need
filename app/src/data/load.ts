import type { PlayData, PlayIndex } from './types';
import type { AggregateData } from '../validation/stats';

const BASE = `${import.meta.env.BASE_URL}data/`;

export async function fetchIndex(): Promise<PlayIndex> {
  const r = await fetch(`${BASE}index.json`);
  if (!r.ok)
    throw new Error(`index.json: HTTP ${r.status}. Run \`python -m pipeline.export\` first.`);
  return r.json();
}

export async function fetchAggregate(): Promise<AggregateData> {
  const r = await fetch(`${BASE}aggregate.json`);
  if (!r.ok) throw new Error(`aggregate.json: HTTP ${r.status}. Run \`python -m pipeline.aggregate\` first.`);
  const data = (await r.json()) as AggregateData;
  if (data.version !== 1) throw new Error(`aggregate.json: unsupported schema version ${data.version}`);
  return data;
}

const cache = new Map<string, Promise<PlayData>>();

export function fetchPlay(file: string): Promise<PlayData> {
  if (!cache.has(file)) {
    const p = fetch(`${BASE}${file}`).then(async (r) => {
      if (!r.ok) throw new Error(`${file}: HTTP ${r.status}`);
      const d = (await r.json()) as PlayData;
      if (d.version !== 1) throw new Error(`${file}: unsupported schema version ${d.version}`);
      return d;
    });
    p.catch(() => cache.delete(file));
    cache.set(file, p);
  }
  return cache.get(file)!;
}
