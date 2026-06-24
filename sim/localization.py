#!/usr/bin/env python3
"""
PhytoSense visitor localization (simulation).

This module is the hub-side maths. It does NOT model the radio; the broker owns
that. It provides:

  * VisitorTag   - a point that walks a looping path at a known true position
  * sense()      - turn a true position into per-anchor RSSI readings, with noise
  * estimate()   - turn per-anchor RSSI readings back into a position guess

The idea in one line: every fixed node has a known position. A visitor carries a
BLE tag that chirps. Nearby nodes hear the chirp and report how loud it was
(RSSI). The closer the tag, the louder. Combine the loud-ness reported by every
node that heard it and you get an estimated point on the map.

Two estimators are provided so you can watch them compete in the viewer:

  weighted_centroid  - robust, always returns something, coarse. Position is the
                       RSSI-weighted average of the anchors that heard the tag.
  trilaterate        - the "triangulation" you asked for. Converts each RSSI to a
                       rough distance and solves for the best-fit point. Needs at
                       least 3 anchors with usable geometry; falls back otherwise.

Run this file directly for a self-test:  python3 localization.py
"""

import math
import random

# ---------------------------------------------------------------------------
# Radio constants (kept in step with broker.py)
# ---------------------------------------------------------------------------
TX_POWER_DBM  = -40.0   # representative indoor BLE tag Tx power
PATH_LOSS_EXP = 2.0     # indoor path-loss exponent

# Localization reception range is deliberately LARGER than the mesh routing
# cutoff (5 m in broker.py). That 5 m number is an artificial device to force
# multi-hop mesh routing; it is not a real radio limit. A real node hears a BLE
# advertisement many metres away, and trilateration needs several anchors to
# hear each tag, so we model reception out to a realistic range here.
LOC_RANGE_M   = 18.0    # an anchor reports a tag chirp within this range
RSSI_NOISE_DB = 4.0     # std-dev of per-chirp Gaussian noise on RSSI

# ---- Fused estimator tuning ----
LOC_TOPK         = 6        # use only the strongest N anchors (drops far/cross-house)
LOC_REG_BETA     = 2.00     # centroid-prior strength: higher = tethered harder to centroid
LOC_SMOOTH_ALPHA = 0.40     # exponential smoothing factor (the broker applies it over time)
LOC_AVG_WINDOW   = 1        # chirps averaged per anchor before estimating (1 = off).
                            # Averaging cuts RSSI noise but lags a moving tag, and at
                            # walking speed the lag cancels the gain, so off by default.
                            # Try 2 if visitors tend to stop and dwell at exhibits.
LOC_BOUNDS       = (-12.0, 15.0, -6.0, 6.0)   # xmin, xmax, ymin, ymax safety clamp

# A small fixed per-anchor bias (antenna, mounting, orientation) drawn once.
# This is what makes the estimate wobble in a way tuning a single constant
# cannot fully remove, which is the honest source of real-world error.
_anchor_bias: dict[int, float] = {}


def _bias(node_id: int) -> float:
    if node_id not in _anchor_bias:
        _anchor_bias[node_id] = random.gauss(0.0, 2.0)
    return _anchor_bias[node_id]


# ---------------------------------------------------------------------------
# RSSI <-> distance
# ---------------------------------------------------------------------------

def rssi_at(dist_m: float) -> float:
    """Noiseless RSSI an anchor would read for a tag at this distance."""
    d = max(dist_m, 0.1)
    return TX_POWER_DBM - 10.0 * PATH_LOSS_EXP * math.log10(d)


def distance_from_rssi(rssi: float) -> float:
    """Invert the path-loss model: rough distance implied by an RSSI reading."""
    return 10.0 ** ((TX_POWER_DBM - rssi) / (10.0 * PATH_LOSS_EXP))


# ---------------------------------------------------------------------------
# Sensing: true position -> per-anchor RSSI readings (with noise)
# ---------------------------------------------------------------------------

def sense(true_xy, node_coords, dead=None, rng=random):
    """
    Given a tag's true (x, y) and a dict {node_id: (x, y)} of anchor positions,
    return the list of anchors that hear the chirp, each as:
        {"id": node_id, "x": x, "y": y, "rssi": int}

    dead: optional set of node_ids that are offline and hear nothing.
    """
    dead = dead or set()
    tx, ty = true_xy
    heard = []
    for nid, (nx, ny) in node_coords.items():
        if nid in dead:
            continue
        d = math.hypot(tx - nx, ty - ny)
        if d > LOC_RANGE_M:
            continue
        rssi = rssi_at(d) + _bias(nid) + rng.gauss(0.0, RSSI_NOISE_DB)
        heard.append({"id": nid, "x": nx, "y": ny, "rssi": int(round(rssi))})
    return heard


# ---------------------------------------------------------------------------
# Estimator 1: weighted centroid
# ---------------------------------------------------------------------------

def weighted_centroid(anchors):
    """
    Position = weighted average of anchor positions. Weight rises sharply as the
    implied distance shrinks (1/d^2), so the nearest anchors dominate. Always
    returns a point as long as at least one anchor heard the tag.
    """
    if not anchors:
        return None
    sx = sy = sw = 0.0
    for a in anchors:
        d = max(distance_from_rssi(a["rssi"]), 0.3)
        w = 1.0 / (d * d)
        sx += a["x"] * w
        sy += a["y"] * w
        sw += w
    if sw == 0.0:
        return None
    return (sx / sw, sy / sw)


# ---------------------------------------------------------------------------
# Estimator 2: RSSI trilateration (linear least squares, pure Python)
# ---------------------------------------------------------------------------

def trilaterate(anchors):
    """
    Convert each RSSI to a distance, then solve for the point whose distances to
    the anchors best match. Linearised by subtracting a reference equation, then
    solved as a 2x2 normal-equations system. Needs >= 3 anchors; returns None if
    geometry is degenerate (e.g. all anchors collinear).
    """
    if len(anchors) < 3:
        return None

    # Reference = strongest anchor (smallest implied distance), most reliable.
    ref = max(anchors, key=lambda a: a["rssi"])
    x0, y0 = ref["x"], ref["y"]
    r0 = distance_from_rssi(ref["rssi"])

    Sxx = Sxy = Syy = Sxb = Syb = 0.0
    used = 0
    for a in anchors:
        if a is ref:
            continue
        xi, yi = a["x"], a["y"]
        ri = distance_from_rssi(a["rssi"])
        ax = 2.0 * (x0 - xi)
        ay = 2.0 * (y0 - yi)
        b  = (ri * ri - r0 * r0
              - (xi * xi - x0 * x0)
              - (yi * yi - y0 * y0))
        Sxx += ax * ax
        Sxy += ax * ay
        Syy += ay * ay
        Sxb += ax * b
        Syb += ay * b
        used += 1

    if used < 2:
        return None
    det = Sxx * Syy - Sxy * Sxy
    if abs(det) < 1e-9:
        return None   # degenerate geometry, fall back to centroid upstream

    x = (Syy * Sxb - Sxy * Syb) / det
    y = (Sxx * Syb - Sxy * Sxb) / det
    return (x, y)


def estimate(anchors):
    """
    Run all three estimators. The fused one is the headline; centroid and raw
    trilateration are kept so the viewer can show how much the fusion helps.
    Returns a dict the broker can ship to the viewer verbatim.
    """
    cen = weighted_centroid(anchors)
    tri = trilaterate(anchors)
    fus = fused(anchors)
    return {
        "centroid": _pt(cen),
        "trilat":   _pt(tri),
        "fused":    _pt(fus),
        "n_anchors": len(anchors),
    }


# ---------------------------------------------------------------------------
# Estimator 3: fused (the recommended one)
#
# This is "fix trilateration AND combine with centroid" in a single solver:
#
#   1. Listen to only the strongest LOC_TOPK anchors. Far and cross-house
#      anchors are the weakest, so this drops exactly the unreliable ones.
#   2. Weight each anchor by signal strength (1/d^2), so close anchors dominate.
#   3. Tether the least-squares solve to the weighted centroid with a prior term
#      (damped least squares). When the geometry is strong the data wins and the
#      estimate refines past the centroid; when the geometry is weak the prior
#      keeps it from flying off. This is the part that stops the divergence you
#      saw, and it is what "combining A and B" actually means.
#   4. Clamp to the greenhouse footprint as a final guard.
#
# Temporal smoothing (stop the estimate teleporting) is applied by the broker,
# which holds the per-tag history; see LOC_SMOOTH_ALPHA.
# ---------------------------------------------------------------------------

def _pt(p):
    return None if p is None else {"x": round(p[0], 2), "y": round(p[1], 2)}


def _clamp(x, y):
    xmin, xmax, ymin, ymax = LOC_BOUNDS
    return (min(max(x, xmin), xmax), min(max(y, ymin), ymax))


def fused(anchors, topk=LOC_TOPK, beta=LOC_REG_BETA):
    if not anchors:
        return None

    # 1. strongest anchors only
    sel = sorted(anchors, key=lambda a: a["rssi"], reverse=True)[:topk]

    # centroid of the selected set is both an estimate and the prior
    cen = weighted_centroid(sel)
    if cen is None:
        return None
    if len(sel) < 3:
        return cen           # too few to refine; centroid is the answer
    cx, cy = cen

    ref = sel[0]             # strongest = reference equation
    x0, y0 = ref["x"], ref["y"]
    r0 = distance_from_rssi(ref["rssi"])

    # 2. signal-strength weights, normalised so the mean weight is 1 (keeps the
    #    regularisation scale stable across different anchor counts)
    raw_w = [1.0 / (max(distance_from_rssi(a["rssi"]), 0.5) ** 2) for a in sel]
    wm = sum(raw_w) / len(raw_w)
    weights = [w / wm for w in raw_w]

    Sxx = Sxy = Syy = Sxb = Syb = 0.0
    for a, w in zip(sel, weights):
        if a is ref:
            continue
        xi, yi = a["x"], a["y"]
        ri = distance_from_rssi(a["rssi"])
        ax = 2.0 * (x0 - xi)
        ay = 2.0 * (y0 - yi)
        b  = (ri * ri - r0 * r0
              - (xi * xi - x0 * x0)
              - (yi * yi - y0 * y0))
        Sxx += w * ax * ax
        Sxy += w * ax * ay
        Syy += w * ay * ay
        Sxb += w * ax * b
        Syb += w * ay * b

    # 3. centroid prior: add beta-scaled identity and pull rhs toward (cx, cy).
    #    lam is scaled by the data magnitude so beta stays geometry-independent.
    lam = beta * (Sxx + Syy) / 2.0
    Sxx += lam
    Syy += lam
    Sxb += lam * cx
    Syb += lam * cy

    det = Sxx * Syy - Sxy * Sxy
    if abs(det) < 1e-9:      # cannot happen once lam > 0, but stay safe
        return cen
    x = (Syy * Sxb - Sxy * Syb) / det
    y = (Sxx * Syb - Sxy * Sxb) / det

    # 4. footprint clamp
    return _clamp(x, y)


def smooth(prev, new, alpha=LOC_SMOOTH_ALPHA):
    """Exponential moving average between the previous and new estimate."""
    if prev is None:
        return new
    if new is None:
        return prev
    return (alpha * new[0] + (1 - alpha) * prev[0],
            alpha * new[1] + (1 - alpha) * prev[1])


def average_anchors(window):
    """
    Average each anchor's RSSI across a window of recent chirp snapshots.

    window: list of snapshots, each a list of {id, x, y, rssi} from one chirp.
    Random per-chirp noise is zero-mean, so averaging W chirps shrinks it by
    about sqrt(W). The fixed per-anchor bias is constant and survives averaging,
    which is why this helps the random spikes but not the systematic offset.

    An anchor must appear in at least half the snapshots to get a vote, so a far
    anchor heard once by luck does not enter the solve.
    """
    if not window:
        return []
    acc = {}   # id -> [rssi_sum, count, x, y]
    for snap in window:
        for a in snap:
            e = acc.get(a["id"])
            if e is None:
                acc[a["id"]] = [float(a["rssi"]), 1, a["x"], a["y"]]
            else:
                e[0] += a["rssi"]
                e[1] += 1
    need = (len(window) + 1) // 2
    out = []
    for nid, (rsum, count, x, y) in acc.items():
        if count >= need:
            out.append({"id": nid, "x": x, "y": y, "rssi": rsum / count})
    return out


# ---------------------------------------------------------------------------
# Visitor tags: points that walk looping paths at a known true position
# ---------------------------------------------------------------------------

class VisitorTag:
    """A tag walking a closed polyline at constant speed (metres/second)."""

    def __init__(self, tag_id, name, color, waypoints, speed=1.0):
        self.id = tag_id
        self.name = name
        self.color = color
        self.waypoints = waypoints          # list of (x, y), looped
        self.speed = speed
        self._seg = 0
        self._t = 0.0                        # 0..1 along current segment
        self.x, self.y = waypoints[0]

    def advance(self, dt):
        """Move forward by speed*dt along the path, wrapping at the end."""
        remaining = self.speed * dt
        n = len(self.waypoints)
        while remaining > 1e-9:
            a = self.waypoints[self._seg]
            b = self.waypoints[(self._seg + 1) % n]
            seg_len = math.hypot(b[0] - a[0], b[1] - a[1])
            if seg_len < 1e-9:
                self._seg = (self._seg + 1) % n
                self._t = 0.0
                continue
            step_t = remaining / seg_len
            if self._t + step_t < 1.0:
                self._t += step_t
                remaining = 0.0
            else:
                remaining -= (1.0 - self._t) * seg_len
                self._seg = (self._seg + 1) % n
                self._t = 0.0
            a = self.waypoints[self._seg]
            b = self.waypoints[(self._seg + 1) % n]
            self.x = a[0] + (b[0] - a[0]) * self._t
            self.y = a[1] + (b[1] - a[1]) * self._t
        return (self.x, self.y)


def default_tags():
    """Three featured visitors: a Romeo loop, a Julia loop, and one crossing."""
    return [
        VisitorTag("V1", "Visitor 1", "#e84393",
                   [(1.0, 0.0), (4.0, 2.0), (8.0, 3.0), (12.0, 1.0),
                    (12.0, -1.0), (8.0, -3.0), (4.0, -2.0), (1.0, 0.0)],
                   speed=1.1),
        VisitorTag("V2", "Visitor 2", "#00cec9",
                   [(-1.0, 0.0), (-4.0, 2.0), (-8.0, 2.0), (-8.0, -2.0),
                    (-4.0, -2.0), (-1.0, 0.0)],
                   speed=0.9),
        VisitorTag("V3", "Visitor 3", "#fdcb6e",
                   [(10.0, 0.0), (0.0, 0.5), (-8.0, 0.0), (0.0, -0.5), (10.0, 0.0)],
                   speed=1.3),
    ]


# Greenhouse footprints used to scatter the crowd (x_min, x_max, y_min, y_max)
ROMEO_BOX = (1.0, 14.0, -3.5, 3.5)
JULIA_BOX = (-10.0, -1.5, -3.0, 3.0)


def crowd_tags(n, seed=11):
    """
    Generate n anonymous wandering bands for the occupancy heatmap. Each band
    loops a short random path inside one greenhouse at a casual walking pace.
    They are not drawn individually; they only feed the per-node crowd count.
    """
    rng = random.Random(seed)
    tags = []
    for i in range(n):
        box = ROMEO_BOX if rng.random() < 0.6 else JULIA_BOX   # Romeo is bigger
        xlo, xhi, ylo, yhi = box
        pts = [(rng.uniform(xlo, xhi), rng.uniform(ylo, yhi))
               for _ in range(rng.randint(3, 5))]
        tags.append(VisitorTag(f"C{i}", f"crowd {i}", "#888888", pts,
                               speed=rng.uniform(0.5, 1.2)))
    return tags


def nearest_node(xy, node_coords, dead=None, max_range=LOC_RANGE_M):
    """
    The single closest live node within range. This is the node a band would
    ack, so the node can count it for the crowd heatmap. Returns a node id, or
    None if the band is out of range of every node (a dead zone).
    """
    dead = dead or set()
    bx, by = xy
    best_id, best_d = None, max_range
    for nid, (nx, ny) in node_coords.items():
        if nid in dead:
            continue
        d = math.hypot(bx - nx, by - ny)
        if d <= best_d:
            best_d = d
            best_id = nid
    return best_id


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # A small known grid of anchors around a target.
    nodes = {
        0: (0.0, 0.0), 1: (5.0, 0.0), 2: (0.0, 5.0),
        3: (5.0, 5.0), 4: (2.5, 2.5),
    }
    rng = random.Random(42)
    truth = (3.0, 2.0)

    cen_err = []
    tri_err = []
    fus_err = []
    for _ in range(2000):
        anchors = sense(truth, nodes, rng=rng)
        est = estimate(anchors)
        if est["centroid"]:
            cen_err.append(math.hypot(est["centroid"]["x"] - truth[0],
                                      est["centroid"]["y"] - truth[1]))
        if est["trilat"]:
            tri_err.append(math.hypot(est["trilat"]["x"] - truth[0],
                                      est["trilat"]["y"] - truth[1]))
        if est["fused"]:
            fus_err.append(math.hypot(est["fused"]["x"] - truth[0],
                                      est["fused"]["y"] - truth[1]))

    def mean(v): return sum(v) / len(v) if v else float("nan")
    print(f"anchors heard      : {len(sense(truth, nodes, rng=rng))}")
    print(f"weighted_centroid  : mean error {mean(cen_err):.2f} m  (n={len(cen_err)})")
    print(f"trilaterate (raw)  : mean error {mean(tri_err):.2f} m  (n={len(tri_err)})")
    print(f"fused              : mean error {mean(fus_err):.2f} m  (n={len(fus_err)})")

    # Tag motion sanity: distance walked over 10 s at 1.1 m/s should be ~11 m.
    tag = default_tags()[0]
    start = (tag.x, tag.y)
    walked = 0.0
    px, py = start
    for _ in range(100):
        tag.advance(0.1)
        walked += math.hypot(tag.x - px, tag.y - py)
        px, py = tag.x, tag.y
    print(f"tag walked in 10 s : {walked:.1f} m  (expected ~11.0)")