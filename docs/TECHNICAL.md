# Magnet

Magnet is a play-replay tool built on 2021 NFL Next Gen Stats tracking (Weeks 1–8, 7,541 throws). It measures how far each receiver pulls the deep safeties toward himself before the throw, and ranks every pass option frame by frame from snap to throw. Outside receivers 8–18 yards downfield drag the safeties up to twice their fair share, and against single-high coverage a teammate's pull gives the targeted receiver +0.25 yards of separation and +4 points of completion rate, with no effect against two-high shells because the second safety is still there. Our pass ranking combines a completion model learned from real throws (held-out AUC 0.72) with yards and first-down value; on held-out weeks, QBs who threw to our #1 option gained 10.0 yards and a first down 51% of the time, versus 6.5 yards and 33% otherwise. Coaches can use it to design decoy routes against single-high looks, scouts to find receivers whose value never shows in their own stats, and broadcasters to show viewers who really opened the play.

![Safety Pull heatmap](output/safety_pull_heatmap.png)

Code: `safety_pull.py`, `pass_options.py`, `app/`. Methods, setup and limitations: [docs/TECHNICAL.md](docs/TECHNICAL.md).
