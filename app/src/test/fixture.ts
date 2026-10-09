import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { PlayData } from '../data/types';

/** Load an exported play from public/data (written by `python -m pipeline.export`). */
export function loadPlay(name = '2021090900_1687'): PlayData {
  const p = resolve(__dirname, `../../public/data/plays/${name}.json`);
  return JSON.parse(readFileSync(p, 'utf8')) as PlayData;
}
