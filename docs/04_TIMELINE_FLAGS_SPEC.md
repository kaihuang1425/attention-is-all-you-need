# Timeline, event flags and filters

## Goal

Users can see where key moments happen in the play, choose which kinds of moments are shown (for example "snap only" or "all events"), and click or tap any flag to jump to that exact frame.

## Time axis

- Unit: `frameId` at 10 Hz.
- Display: seconds relative to the snap. `t = (frameId - snapFrame) / 10`. Pre-snap frames are negative (−0.5 s).
- Range: first frame to last frame of the play (typically −0.5 s to throw + 0.5 s). The 0.5 s after the throw is shaded and labelled "ball in air (tracking ends)".
- The readout shows both: `1.8 s · frame 24`.

## Flag sources

| Source | Where it comes from | Marker | Shown on timeline |
|---|---|---|---|
| `tracking` | `event` column on ball rows | solid diamond | yes |
| `model` | `02_MODEL_SPEC.md` section 9 | hollow circle | yes |
| `pbp` | `plays.csv` result | none | **no**, post-play panel only |

Canonical tracking flags after cleanup:

| Group | Events |
|---|---|
| Key | `ball_snap` (merged with `autoevent_ballsnap`), `pass_forward` (merged with `autoevent_passforward`), `qb_sack`, `qb_strip_sack`, `run`. The merged flag sits at the manual event's frame; the auto event is only a fallback (auto snaps can be far off) |
| Pre-snap | `line_set`, `man_in_motion`, `shift`, `huddle_break_offense` |
| Play | `play_action`, `pass_tipped`, `autoevent_passinterrupted`, `handoff`, `lateral`, `first_contact`, `fumble`, `fumble_offense_recovered`, `penalty_flag` |
| Ball in air | `pass_arrived`, `pass_outcome_caught`, `pass_outcome_incomplete`, `dropped_pass`, `out_of_bounds`, `tackle` |

Unknown event strings go to "Play" and are logged by the pipeline so nothing is silently dropped.

Model flag groups:

| Group | Flags |
|---|---|
| Windows | `window_open`, `window_close` (per receiver) |
| Decision | `best_option_change`, `peak_decision_gap` |
| Protection | `pressure_arrives`, `block_beaten` (per blocker), `unblocked_rusher` |

## Filter UI

Chips in a single row above the scrubber, so the active filter is always visible:

`[Key ●] [All tracking] [Pre-snap] [Windows ▾] [Decision] [Protection] [Custom ▾]`

- **Key** is the default. Shows snap and the end event only.
- **All tracking** shows every tracking flag.
- **Windows ▾** opens a list of receivers with checkboxes, so window flags can be shown for one receiver at a time. Default: the selected receiver only.
- **Custom ▾** opens checkboxes per event type.
- Chips are toggles and can combine. "Key" is always included unless explicitly unticked in Custom.
- Remember the last filter in `localStorage` (wrapped in try/catch) and in the URL.

## Interaction

| Input | Action |
|---|---|
| Click or tap a flag | Pause, seek to its `frameId`, select related player if any (e.g. the receiver for `window_open`) |
| Drag the scrubber | Snap to the nearest frame; snap to a visible flag within 4 px |
| `←` / `→` | Step one frame |
| `Shift + ←/→` | Step 5 frames (0.5 s) |
| `[` / `]` | Previous / next **visible** flag (respects filters) |
| `Space` | Play / pause |
| `Home` / `End` | First frame / last frame |
| Hover a flag | Tooltip: label, source, frame, time, and for model flags one line of reason ("#1 margin crosses +0.3 s") |

Playback speeds: 0.25×, 0.5×, 1×, 2×. Playback renders every frame; it never skips frames at 1× and below.

## Shared x-axis

Flags appear as faint vertical guide lines through:

- the option-value chart (expected EPA per option over time, plus scramble, throw away and hold),
- the receiver attention strips.

The playhead is a single vertical line across all three. Clicking anywhere on the chart or strips also seeks.

## Overlapping flags

- If two or more visible flags are within 12 px, draw one cluster marker with a count badge.
- Click a cluster: popover listing its flags; choosing one seeks to it.
- On zoom (`Ctrl + scroll` or pinch) clusters split as space allows.

## Accessibility

- Each flag is a `<button>` with `aria-label`, e.g. "Pass forward, tracking event, frame 38, 3.2 seconds".
- Hit area at least 32 px tall even if the marker is 10 px.
- Shape and fill style encode the source; colour is secondary.
- The scrubber is a `role="slider"` with `aria-valuetext="1.8 seconds, frame 24"`.
- Focus moves to the playhead after a flag is activated.

## Deep links

`?game=2021090900&play=1687&frame=24&flags=key,windows:46277&sel=46277`

Loading this URL opens the play paused on that frame with those filters and that receiver selected.

## Data contract (per play JSON)

```ts
type FlagSource = "tracking" | "model";
interface Flag {
  id: string;              // stable, e.g. "trk-38-pass_forward" or "mdl-21-window_open-46277"
  frameId: number;
  t: number;               // seconds from snap
  type: string;            // event or model flag name
  group: "key" | "presnap" | "play" | "ballInAir" | "windows" | "decision" | "protection";
  source: FlagSource;
  label: string;           // "Throw", "#1 Wilson window opens"
  nflId?: number;          // related player
  reason?: string;         // model flags only
  inferred?: boolean;      // e.g. snap inferred from ball movement
}
```

## Tests (Vitest)

- Filtering by groups returns the expected flags for a fixture play.
- `[` and `]` skip hidden flags.
- Clustering merges flags within 12 px at a given width and splits when wider.
- Seeking to a flag sets `currentFrame === flag.frameId` and pauses playback.
- Duplicate snap/throw events produce exactly one flag each.
