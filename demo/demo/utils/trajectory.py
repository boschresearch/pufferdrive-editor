# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""Utility functions for computing expert trajectories and goal positions."""
from .. import globals as _g
from .. import viewer
from .agent_math import _snap_world_to_lane


def _compute_expert_trajectory(agent: dict, num_steps: int):
    """Compute a lane-graph trajectory from start to goal for a user expert agent.

    If the agent has a manually-edited trajectory (traj_manual=True) of the right
    length, returns it directly.  Otherwise snaps (sx, sy) and (ex, ey) to the
    nearest road lane, BFS-searches for a connecting path, and samples num_steps
    evenly-spaced waypoints along it, storing the result in the agent dict.

    Returns (xs, ys, headings) as float32 numpy arrays on success, or None when
    no lane path exists (caller should skip set_demo_expert_trajectory).
    """
    if agent.get("traj_manual") and "traj_xs" in agent:
        xs, ys, hs = agent["traj_xs"], agent["traj_ys"], agent["traj_hs"]
        if len(xs) == num_steps:
            return xs, ys, hs

    sx, sy = agent["sx"], agent["sy"]
    ex, ey = agent["ex"], agent["ey"]

    if _g._env is not None:
        try:
            if _g._lane_graph_cache is None:
                _g._lane_graph_cache = viewer.build_lane_graph(_g._env)
            lanes, successors = _g._lane_graph_cache
            result = viewer.compute_lane_trajectory(
                _g._env, sx, sy, ex, ey, num_steps, lanes=lanes, successors=successors
            )
            if result is not None:
                xs, ys, hs = result
                agent["traj_xs"] = xs.copy()
                agent["traj_ys"] = ys.copy()
                agent["traj_hs"] = hs.copy()
                agent["traj_manual"] = False
                return xs, ys, hs
        except Exception:
            pass

    return None


def _compute_goal_positions() -> list[dict]:
    """Merge initial goal positions with any manual overrides into pixel fractions."""
    positions = {p["slot"]: dict(p) for p in viewer.initial_goal_positions}
    for slot, (wx, wy) in _g._goal_overrides.items():
        frac = viewer.world_to_pixel_fraction(wx, wy)
        if frac is not None:
            label = positions[slot]["label"] if slot in positions and "label" in positions[slot] else str(slot)
            positions[slot] = {"slot": slot, "fx": frac[0], "fy": frac[1], "label": label}
    return list(positions.values())


def _compute_ghost_goal_positions() -> list[dict]:
    """Compute ghost-env goal positions directly from the ghost env, independent of the
    main env's initial_goal_positions (which shrinks when main-env agents are removed)."""
    if _g._ghost_env is None or not _g._ghost_render_bounds:
        return []
    raw = viewer.goal_frame_data(_g._ghost_env, _g._ghost_render_bounds, update_last=False)
    positions = {}
    for p in raw:
        label = str(p["slot"]) if p.get("label") == "SDC" else p.get("label", str(p["slot"]))
        positions[p["slot"]] = {**p, "label": label}
    for slot, (wx, wy) in _g._ghost_goal_overrides.items():
        frac = viewer.world_to_pixel_fraction(wx, wy)
        if frac is not None:
            label = positions[slot]["label"] if slot in positions else str(slot)
            positions[slot] = {"slot": slot, "fx": frac[0], "fy": frac[1], "label": label}
    return list(positions.values())


def _compute_ghost_expert_waypoints() -> list[dict]:
    """Same as _compute_expert_waypoints but for ghost user expert agents."""
    try:
        result = []
        for agent_idx, agent in enumerate(_g._ghost_user_expert_agents):
            points = []
            frac = viewer.world_to_pixel_fraction(agent["sx"], agent["sy"])
            if frac:
                points.append({"wp_idx": 0, "fx": float(frac[0]), "fy": float(frac[1])})
            wps = agent.get("waypoints", [])
            for i, wp in enumerate(wps):
                frac = viewer.world_to_pixel_fraction(wp[0], wp[1])
                if frac:
                    points.append({"wp_idx": i + 1, "fx": float(frac[0]), "fy": float(frac[1])})
            frac = viewer.world_to_pixel_fraction(agent["ex"], agent["ey"])
            if frac:
                points.append({"wp_idx": len(wps) + 1, "fx": float(frac[0]), "fy": float(frac[1])})
            traj_pts = []
            traj = _compute_expert_trajectory(agent, _g._current_sim_steps)
            if traj is None:
                result.append({"agent_idx": agent_idx, "points": points, "traj_pts": []})
                continue
            xs, ys, _ = traj
            for t in range(len(xs)):
                frac = viewer.world_to_pixel_fraction(float(xs[t]), float(ys[t]))
                if frac:
                    traj_pts.append({"t": t, "fx": float(frac[0]), "fy": float(frac[1])})
            result.append({"agent_idx": agent_idx, "points": points, "traj_pts": traj_pts})
        return result
    except Exception:
        return []


def _compute_expert_waypoints() -> list[dict]:
    """Convert user expert agent trajectories to pixel-fraction waypoint data for JS.

    Each agent entry contains:
      - points:   control-point handles (start, intermediates, end) — larger draggable circles
      - traj_pts: every simulation timestep along the interpolated path — small draggable dots

    Never raises — returns [] on any error so the caller's JSON serialization is safe.
    """
    try:
        result = []
        for agent_idx, agent in enumerate(_g._user_expert_agents):
            points = []
            frac = viewer.world_to_pixel_fraction(agent["sx"], agent["sy"])
            if frac:
                points.append({"wp_idx": 0, "fx": float(frac[0]), "fy": float(frac[1])})
            wps = agent.get("waypoints", [])
            for i, wp in enumerate(wps):
                frac = viewer.world_to_pixel_fraction(wp[0], wp[1])
                if frac:
                    points.append({"wp_idx": i + 1, "fx": float(frac[0]), "fy": float(frac[1])})
            frac = viewer.world_to_pixel_fraction(agent["ex"], agent["ey"])
            if frac:
                points.append({"wp_idx": len(wps) + 1, "fx": float(frac[0]), "fy": float(frac[1])})
            traj_pts = []
            traj = _compute_expert_trajectory(agent, _g._current_sim_steps)
            if traj is None:
                result.append({"agent_idx": agent_idx, "points": points, "traj_pts": []})
                continue
            xs, ys, _ = traj
            for t in range(len(xs)):
                frac = viewer.world_to_pixel_fraction(float(xs[t]), float(ys[t]))
                if frac:
                    traj_pts.append({"t": t, "fx": float(frac[0]), "fy": float(frac[1])})
            result.append({"agent_idx": agent_idx, "points": points, "traj_pts": traj_pts})
        return result
    except Exception:
        return []
