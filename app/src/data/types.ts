// Contract for app/public/data, written by pipeline/export.py (schema version 1).
// Coordinates are normalised: the offense attacks +x, x 0-120 (end zones included),
// y 0-53.3 with +y on the offense's left. Time unit is the frame (10 Hz).

export type Role = 'QB' | 'route' | 'block' | 'rush' | 'coverage';
export type Side = 'offense' | 'defense';

export interface PlayerInfo {
  id: number;
  jersey: number;
  name: string;
  position: string;
  side: Side;
  role: Role;
  aligned: string | null;
  blockedId?: number;
  blockType?: string | null;
  blockTypeName?: string | null;
  pff?: Partial<
    Record<
      'hit' | 'hurry' | 'sack' | 'hitAllowed' | 'hurryAllowed' | 'sackAllowed' | 'beatenByDefender',
      number
    >
  >;
}

export type FlagGroup =
  | 'key'
  | 'presnap'
  | 'play'
  | 'ballInAir'
  | 'windows'
  | 'decision'
  | 'protection';

export interface Flag {
  id: string;
  frameId: number;
  t: number;
  type: string;
  group: FlagGroup;
  source: 'tracking' | 'model';
  label: string;
  nflId?: number;
  reason?: string;
  inferred?: boolean;
}

export interface Pressure {
  nearest: number;
  closing: number;
  level: number; // 0-7
  side: 'left' | 'right';
  text: string;
  rusherId: number;
}

type Grid = (number | null)[][]; // frames x receivers (or players)

export interface PlayModel {
  legal: boolean[];
  receivers: number[]; // route runners, column order of every Grid below
  catchX: Grid;
  catchY: Grid;
  tBall: Grid;
  tDef: Grid;
  margin: Grid;
  pCatch: Grid;
  pInt: Grid;
  ev: Grid;
  gain: Grid;
  firstDown: boolean[][];
  touchdown: boolean[][];
  yardsShort: Grid;
  sep: Grid;
  lane: Grid;
  kernelAttention: Grid;
  safetyPull: Grid;
  epNow: number;
  valueIncomplete: number;
  attention: {
    offense: number[]; // 10 non-QB offensive players
    defense: number[]; // 11 defenders
    A: Grid; // frames x offense
    space: Grid; // frames x defense
    edges: [number, number, number][][]; // per frame: [defenseIndex, offenseIndex, weight]
  };
  pressure: (Pressure | null)[];
}

export interface PlayMeta {
  gameId: number;
  playId: number;
  week: number;
  gameDate: string;
  homeTeamAbbr: string;
  visitorTeamAbbr: string;
  possessionTeam: string;
  defensiveTeam: string;
  qbNflId: number;
  qbName: string;
  quarter: number;
  gameClock: string;
  down: number;
  yardsToGo: number;
  preSnapHomeScore: number;
  preSnapVisitorScore: number;
  offenseScore: number;
  defenseScore: number;
  los_x: number;
  firstDown_x: number;
  losLabel: string;
  firstDownLabel: string;
  formation: string;
  offenseFormation: string | null;
  personnelO: string | null;
  personnelD: string | null;
  defendersInBox: number | null;
  dropBackType: string | null;
  pff_passCoverage: string | null;
  pff_passCoverageType: string | null;
  snapFrame: number;
  snapSource: string;
  snapInferred: boolean;
  throwFrame: number | null;
  endFrame: number;
  endType: 'throw' | 'sack' | 'scramble';
  timeToThrow: number | null;
  timeToEnd: number;
  foulName1: string | null;
  title: string;
  label: string;
  star: boolean;
  firstFrame: number;
  lastFrame: number;
  hz: number;
  illustrative: boolean;
  models: {
    epVersion: string;
    pCatch: string;
    attention: { sigma: number; k: number; T: number; unattached: number };
    arrival: { vBall: number; tRelease: number; tauReact: number };
  };
}

export interface PlayResult {
  passResult: 'C' | 'I' | 'IN' | 'S' | 'R';
  playResult: number | null;
  description: string | null;
  targetId: number | null;
  targetJersey: number | null;
  targetName: string | null;
  targetIsRouteRunner: boolean;
  decision: {
    frameId: number;
    chosen: string | null;
    best: string;
    bestId: number | null;
    evChosen: number | null;
    evBest: number | null;
    gap: number | null;
    scope: string;
  };
}

export interface PlayData {
  version: number;
  meta: PlayMeta;
  players: PlayerInfo[]; // order of every tracks column
  frames: { frameId: number[]; t: number[] };
  tracks: { x: Grid; y: Grid; s: Grid; dir: Grid; o: Grid };
  ball: ([number, number] | null)[];
  model: PlayModel;
  flags: Flag[];
  result: PlayResult;
}

export interface PlayIndexEntry {
  gameId: number;
  playId: number;
  file: string;
  label: string;
  star: boolean;
  title: string;
  offense: string;
  defense: string;
  qb: string;
  week: number;
  quarter: number;
  gameClock: string;
  down: number;
  yardsToGo: number;
  passResult: string;
  playResult: number | null;
  coverage: string | null;
  description: string | null;
}

export interface PlayIndex {
  version: number;
  plays: PlayIndexEntry[];
}
