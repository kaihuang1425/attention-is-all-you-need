"""Soft attention: how each defender's attention is shared across offensive players (model spec §2).

    score(d, j) = -dist(d, j) / sigma + k * cos(theta(d, j))
    a(d -> j)   = softmax_j(score(d, j) / T)      over the 10 non-QB offensive players + "unattached"
    A(j)        = sum_d a(d -> j)                 "defender-equivalents" on player j

theta is the angle between the defender's body orientation (sin o, cos o) and the vector from
the defender to player j. `o` is body orientation (shoulder-pad sensor), not eye direction, and
is smoothed over 3 frames (circular mean) before use.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import load_config
from .playdata import PlayArrays


@dataclass(frozen=True)
class AttentionParams:
    sigma: float = 4.0
    k: float = 1.0
    temperature: float = 1.0
    unattached_score: float = -3.0
    smoothing_frames: int = 3

    @classmethod
    def from_config(cls) -> AttentionParams:
        c = load_config()["attention"]
        return cls(
            sigma=float(c["sigma"]),
            k=float(c["k"]),
            temperature=float(c["temperature"]),
            unattached_score=float(c["unattached_score"]),
            smoothing_frames=int(c["orientation_smoothing_frames"]),
        )


@dataclass
class PlayAttention:
    frames: np.ndarray  # (F,)
    def_ids: np.ndarray  # (11,)
    off_ids: np.ndarray  # (10,)
    weights: np.ndarray  # (F, 11, 11): defenders x (10 offense + unattached); rows sum to 1

    @property
    def edges(self) -> np.ndarray:
        """(F, 11, 10) a(d -> j) without the unattached column."""
        return self.weights[:, :, :-1]

    @property
    def unattached(self) -> np.ndarray:
        """(F, 11) share of each defender's attention spent on space."""
        return self.weights[:, :, -1]

    @property
    def A(self) -> np.ndarray:
        """(F, 10) defender-equivalents on each offensive player."""
        return self.edges.sum(axis=1)


def smooth_orientation(o_deg: np.ndarray, window: int = 3) -> np.ndarray:
    """Centred circular mean of orientation over `window` frames along axis 0 (NaN-aware)."""
    if window <= 1:
        return o_deg.copy()
    rad = np.deg2rad(o_deg)
    s, c = np.sin(rad), np.cos(rad)
    valid = np.isfinite(rad)
    s, c = np.where(valid, s, 0.0), np.where(valid, c, 0.0)
    half = window // 2
    pad = [(half, half)] + [(0, 0)] * (o_deg.ndim - 1)
    sp, cp, vp = np.pad(s, pad), np.pad(c, pad), np.pad(valid.astype(float), pad)
    ss = sum(sp[i : i + len(o_deg)] for i in range(window))
    cs = sum(cp[i : i + len(o_deg)] for i in range(window))
    n = sum(vp[i : i + len(o_deg)] for i in range(window))
    out = np.rad2deg(np.arctan2(ss, cs)) % 360.0
    return np.where(n > 0, out, np.nan)


def geometry(def_xy: np.ndarray, def_o: np.ndarray, off_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distances and cos(theta) for every (frame, defender, offensive player).

    def_xy (F, D, 2), def_o (F, D) degrees (already smoothed), off_xy (F, J, 2).
    Returns dist (F, D, J) and cos (F, D, J); cos is 0 where undefined.
    """
    vec = off_xy[:, None, :, :] - def_xy[:, :, None, :]  # (F, D, J, 2)
    dist = np.hypot(vec[..., 0], vec[..., 1])
    rad = np.deg2rad(def_o)
    u = np.stack([np.sin(rad), np.cos(rad)], axis=-1)  # (F, D, 2) unit body vector
    with np.errstate(invalid="ignore", divide="ignore"):
        cos = (vec[..., 0] * u[:, :, None, 0] + vec[..., 1] * u[:, :, None, 1]) / dist
    cos = np.where(np.isfinite(cos), cos, 0.0)
    return dist, cos


def attention_from_geometry(dist: np.ndarray, cos: np.ndarray, p: AttentionParams) -> np.ndarray:
    """(…, D, J) geometry -> (…, D, J + 1) weights; last column is "unattached"."""
    score = -dist / p.sigma + p.k * cos
    score = np.where(np.isfinite(score), score, -np.inf)
    un = np.full(score.shape[:-1] + (1,), p.unattached_score)
    z = np.concatenate([score, un], axis=-1) / p.temperature
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def attention_for_play(pa: PlayArrays, params: AttentionParams | None = None) -> PlayAttention:
    """Attention for every frame of a play."""
    p = params or AttentionParams.from_config()
    o = smooth_orientation(pa.def_o, p.smoothing_frames)
    dist, cos = geometry(pa.def_xy, o, pa.off_xy)
    w = attention_from_geometry(dist, cos, p)
    return PlayAttention(frames=pa.frames, def_ids=pa.def_ids, off_ids=pa.off_ids, weights=w)


def format_matrix(pa: PlayArrays, att: PlayAttention, frame_id: int, min_show: float = 0.005) -> str:
    """Text table of a(d -> j) at one frame with jersey numbers as labels."""
    i = pa.idx(frame_id)
    cols = [f"#{j}" for j in pa.off_jersey] + ["space"]
    head = "def\\off " + " ".join(f"{c:>5}" for c in cols)
    lines = [head]
    for r, (jersey, role) in enumerate(zip(pa.def_jersey, pa.def_roles)):
        vals = " ".join(f"{v:5.2f}" if v >= min_show else "    ." for v in att.weights[i, r])
        lines.append(f"#{jersey:<3}{'R' if role == 'Pass Rush' else 'C'}   {vals}")
    lines.append("A(j)    " + " ".join(f"{v:5.2f}" for v in att.A[i]))
    return "\n".join(lines)
