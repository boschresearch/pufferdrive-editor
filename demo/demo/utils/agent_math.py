# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""Pure utility functions for agent position/heading mathematics."""
import math


def _match_positions_to_slots(user_agents: list[dict], state0: dict) -> list[int]:
    """Return the controlled-agent slot index for each user agent by nearest-position match.

    Frame 0 is captured before any env.step(), so agents are still at their injection
    positions — position matching is exact.  Returns -1 for any agent not found.
    """
    import numpy as np
    xs = np.array(state0["x"])
    ys = np.array(state0["y"])
    valid = np.array(state0["valid"], dtype=bool)
    result = []
    for ua in user_agents:
        d2 = (xs - ua["x"]) ** 2 + (ys - ua["y"]) ** 2
        d2[~valid] = float("inf")
        idx = int(np.argmin(d2))
        result.append(idx if np.isfinite(d2[idx]) else -1)
    return result


def _match_static_positions_to_slots(user_statics: list[dict], static_agents: list[dict], bounds: dict) -> list[int]:
    """Return the global slot index for each user-placed static agent by nearest pixel-space match."""
    import numpy as np
    scale = bounds["scale"]
    min_x, max_y = bounds["min_x"], bounds["max_y"]
    cxs = np.array([e["cx"] for e in static_agents])
    cys = np.array([e["cy"] for e in static_agents])
    slots = [e["slot"] for e in static_agents]
    result = []
    for ua in user_statics:
        cx = (ua["x"] - min_x) * scale
        cy = (max_y - ua["y"]) * scale
        d2 = (cxs - cx) ** 2 + (cys - cy) ** 2
        idx = int(np.argmin(d2))
        result.append(slots[idx])
    return result


def _recompute_headings(xs, ys):
    """Recompute headings for a trajectory using central differences."""
    import numpy as np
    n = len(xs)
    hs = np.empty(n, dtype=np.float32)
    for t in range(n):
        if t == 0:
            hs[t] = math.atan2(ys[1] - ys[0], xs[1] - xs[0]) if n > 1 else 0.0
        elif t == n - 1:
            hs[t] = math.atan2(ys[t] - ys[t - 1], xs[t] - xs[t - 1])
        else:
            hs[t] = math.atan2(ys[t + 1] - ys[t - 1], xs[t + 1] - xs[t - 1])
    return hs


def _spline_fit_trajectory(agent: dict, traj_step: int, new_x: float, new_y: float, n: int,
                           sigma: float = 2.0):
    """Smooth Gaussian displacement: move traj_step to (new_x, new_y) and spread the
    displacement to neighbouring timesteps with a Gaussian falloff (width=sigma).

    The Gaussian weight is linearly detrended so the displacement tapers smoothly to
    exactly zero at the pinned endpoints (no snap-back kink), then renormalized so the
    dragged point lands exactly on the target with no peak kink. Both endpoints are
    pinned: the start (t=0) to agent["sx"], agent["sy"] and the goal (t=n-1) to its
    original position, so dragging never moves them (unless the goal is the dragged
    point itself).

    Returns (xs, ys) numpy arrays of length n, or (None, None) on failure.
    """
    import numpy as np

    try:
        xs = np.array(agent["traj_xs"], dtype=float)
        ys = np.array(agent["traj_ys"], dtype=float)

        dx = new_x - xs[traj_step]
        dy = new_y - ys[traj_step]

        t = np.arange(n, dtype=float)
        w = np.exp(-(t - traj_step) ** 2 / (2.0 * sigma ** 2))

        # Detrend so the displacement tapers to exactly 0 at the pinned endpoints.
        # Start (t=0) is always pinned; the goal (t=n-1) is pinned unless it is the
        # dragged point.
        if n > 1:
            s = t / (n - 1)
            if traj_step != n - 1:
                w = w - (w[0] * (1.0 - s) + w[n - 1] * s)
            else:
                w = w - w[0] * (1.0 - s)

        # Renormalize so the dragged point lands exactly on the target (no peak kink).
        peak = w[traj_step]
        if abs(peak) > 1e-9:
            w = w / peak

        xs = xs + w * dx
        ys = ys + w * dy

        # Explicitly pin the start for float safety (its weight is already ~0).
        xs[0] = agent["sx"]
        ys[0] = agent["sy"]

        return xs, ys
    except Exception:
        return None, None


def _snap_world_to_lane(x: float, y: float, lanes) -> tuple[float, float]:
    """Project world point (x,y) onto the nearest road lane polyline."""
    best_d2 = float("inf")
    best_x, best_y = x, y
    for lane in lanes:
        for si in range(len(lane) - 1):
            ax, ay = float(lane[si, 0]), float(lane[si, 1])
            bx, by = float(lane[si + 1, 0]), float(lane[si + 1, 1])
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg2)) if seg2 > 1e-12 else 0.0
            px, py = ax + t * dx, ay + t * dy
            d2 = (x - px) ** 2 + (y - py) ** 2
            if d2 < best_d2:
                best_d2, best_x, best_y = d2, px, py
    return best_x, best_y
