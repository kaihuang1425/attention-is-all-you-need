# Demo video script (2 minutes max)

Seven beats, about 260 words of narration. At a steady pace that runs 1:50 and leaves a few seconds of slack. Every number below is what the app shows on screen.

## Before you record

1. Start the app: double-click `run-demo.cmd` (Windows) or run `./run-demo.sh`. It opens http://localhost:5173.
2. Use a private browser window. The app remembers layer choices, and a private window starts from the defaults: Heatmap on (Defense influence), Attention on, Trails on at ±1.0 s, Shadows off.
3. Record at 1920×1080, browser zoom 100%, full screen (F11).
4. Load the opening frame: http://localhost:5173/?game=2021090900&play=1687&frame=24 (★ Main demo: DAL @ TB, paused at 1.8 s).
5. Set the speed menu next to the playback buttons to 0.5×.
6. Rehearse once. The clicks in beats 2, 3 and 5 are where time slips.

## Script

### 1. Open (0:00–0:10)

Screen: the opening frame. Point at the play bar (DAL @ TB · Q2 05:43 · 2nd & 8), then click **Reveal coverage** so it shows Cover-3 (Zone).

> This is Defensive Attention. It replays 2021 NFL passing plays from snap to throw, built on player tracking data. Dallas at Tampa Bay, second and 8, Tampa in Cover-3.

### 2. Attention and shadows (0:10–0:28)

Screen: point at the amber line from #35 Dean to #88 Lamb. Open **Field layers** (top right of the field) and turn on Shadows.

> The amber lines are our attention model: who each defender is watching. Dean, number 35, is almost fully on CeeDee Lamb. Turn on shadows and you see the throwing lanes each defender takes away from Prescott.

### 3. Play it (0:28–0:55)

Screen: click #88 Lamb so his trail shows. Click **▶ Replay**. At 0.5× the play runs about 8 seconds and stops after the throw. Point at the flags on the timeline as you name them.

> Click a receiver: the solid trail is the last second of his route, the dashed trail is the next one. Now play it. The timeline flags what the model sees. Collins is beaten by Barrett at 1.9 seconds, which matches PFF's charting. The best option moves from Lamb to Wilson, then to Jarwin at 2.9. Prescott throws at 3.2.

### 4. The decision (0:55–1:13)

Screen: press `[` to jump back to the Throw flag. Point at the top row of **Decision options** (#89 Jarwin), then the **Post-play** panel.

> At release, the model's top pass is Jarwin, at an estimated plus 1.74 EPA. Prescott went deep to Lamb, plus 0.82, and it fell incomplete. We can't know what the Jarwin throw would have done, and the app says so on screen.

### 5. A sack (1:13–1:30)

Screen: pick **★ Sack: Burns comes free** from the play menu. Click **Inspect protection** in the Pocket pressure panel, then **▶ Replay**.

> Same view on a sack: Jets at Carolina. Brian Burns is unblocked two tenths of a second after the snap. Pressure arrives at 1.9, and Zach Wilson goes down at 2.8 for a loss of 9.

### 6. Does it hold up? (1:30–1:47)

Screen: click the **Aggregate validation** tab. Point at the calibration chart, then scroll to Man versus zone.

> Does it hold up? Across 7,282 targeted throws, catch probability is checked against held-out weeks 7 and 8. And defenders lock on harder in man coverage than in zone, 0.86 against 0.70, which is what you'd expect.

### 7. Close (1:47–1:58)

Screen: the Safety Pull heatmap (`output/safety_pull_heatmap.png`) full screen, or go back to the Lamb frame from beat 2.

> Across the season, outside receivers 8 to 18 yards deep pull the safeties up to twice their fair share. Coaches can use that to design decoys, and broadcasters to show who opened the play.

## If you run long

- Drop the shadows sentence in beat 2 (saves about 6 seconds).
- In beat 3, cut "which matches PFF's charting" and the trail sentence (about 8 seconds).
- Still long: cut beat 5. The sack is the least important story.

## What not to say

- Don't say the model "knew" Jarwin would catch it. His value is an estimate, and the outcome of a throw that never happened is unknown.
- Don't call 1× playback live. It is recorded 10 Hz tracking played at game speed.
- The +0.25 yards of separation is an association from a regression, not a proven cause. If you mention it, say "comes with", not "causes".
