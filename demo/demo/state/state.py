# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""State class for the PufferDrive interactive demo."""
import asyncio
import datetime
import json
import math
import os
import re
import subprocess

import reflex as rx
from reflex_base.event import BACKGROUND_TASK_MARKER

from .. import globals as _g
from .. import viewer
from ..utils.agent_math import _match_positions_to_slots, _match_static_positions_to_slots, _recompute_headings, _snap_world_to_lane, _spline_fit_trajectory
from ..utils.trajectory import _compute_expert_trajectory, _compute_goal_positions, _compute_expert_waypoints
from ..utils.js_gen import _agent_frames_js, _ghost_frames_js, _ghost_frames_clear_js, _goal_js, _ghost_goal_js, _deep_reset_js, _restart_wait_js


def _background(fn):
    """Mark an async state method as a non-blocking background task."""
    setattr(fn, BACKGROUND_TASK_MARKER, True)
    return fn


VEHICLE_SIZES = {
    "S":  {"length": 3.8, "width": 1.8},
    "M":  {"length": 4.5, "width": 2.0},
    "L":  {"length": 5.5, "width": 2.2},
    "XL": {"length": 8.0, "width": 2.5},
}


# JS that clears every selection global + renderer highlight (primary and ghost).
# Prepended to each select_* call_script so selection is fully exclusive.
_CLEAR_ALL_SELECT_JS = (
    "window._pdSelectedNativeExpertIdx = -1;"
    "window._pdSelectedExpertIdx = -1; window._pdSelectedExpertSlot = -1;"
    "if(window._pdAgentRenderer){"
    "window._pdAgentRenderer.setSelected(-1);"
    "window._pdAgentRenderer.setSelectedStatic(-1);"
    "window._pdAgentRenderer.setSelectedExpert(-1);}"
    "window._pdGhostSelectedNativeExpertIdx = -1;"
    "window._pdGhostSelectedExpertIdx = -1; window._pdGhostSelectedExpertSlot = -1;"
    "if(window._pdGhostRenderer){"
    "window._pdGhostRenderer.setSelectedExpert(-1);"
    "window._pdGhostRenderer.setSelected(-1);"
    "window._pdGhostRenderer.setSelectedStatic(-1);}"
)


def _apply_wp_edit(agent: dict, wp_idx: int, pos) -> None:
    """Move one waypoint of a user-expert agent dict in place.

    wp_idx 0 = start, len(waypoints)+1 = end (heading recomputed from this agent's own
    start), 1..len = an intermediate waypoint. Shared by the primary and ghost waypoint
    drop handlers so both env copies edit identically."""
    wps = list(agent["waypoints"])
    if wp_idx == 0:
        agent["sx"], agent["sy"] = pos
    elif wp_idx == len(wps) + 1:
        agent["ex"], agent["ey"] = pos
        agent["eh"] = math.atan2(pos[1] - agent["sy"], pos[0] - agent["sx"])
    elif 0 < wp_idx <= len(wps):
        wps[wp_idx - 1] = (pos[0], pos[1])
        agent["waypoints"] = wps


def _apply_traj_edit(agent: dict, traj_step: int, pos) -> bool:
    """Move one trajectory timestep of a user-expert agent dict in place (spline-fit +
    heading recompute). Returns False if the agent has no trajectory or the step is out
    of range. Shared by the primary and ghost trajectory drop handlers."""
    if "traj_xs" not in agent:
        return False
    xs = agent["traj_xs"].copy()
    ys = agent["traj_ys"].copy()
    n = len(xs)
    if traj_step < 0 or traj_step >= n:
        return False
    new_xs, new_ys = _spline_fit_trajectory(agent, traj_step, pos[0], pos[1], n)
    if new_xs is not None:
        xs, ys = new_xs, new_ys
    else:
        xs[traj_step] = pos[0]
        ys[traj_step] = pos[1]
    hs = _recompute_headings(xs, ys)
    agent["traj_xs"] = list(xs)
    agent["traj_ys"] = list(ys)
    agent["traj_hs"] = list(hs)
    agent["traj_manual"] = True
    return True



class State(rx.State):
    available_ini_files: list[list[str]] = []
    selected_ini_path: str = ""
    demo_maps: list[list[str]] = []
    demo_policies: list[list[str]] = []  # [[name, model_path, config_path], ...]
    # Exported scenes surfaced in the Map dropdown as selectable "maps" — session-only (this
    # list is in-memory state and resets on restart). Each entry is [label, "scenario://<file>"];
    # selecting one stores its sentinel in selected_map_choice and Load re-applies the whole scene.
    session_maps: list[list[str]] = []
    # The value shown selected in the Map dropdown — a real map path OR a "scenario://<file>"
    # sentinel. Kept SEPARATE from selected_map_path (the real path the env is built from) so
    # that applying a saved scene, which points selected_map_path at the scene's underlying map,
    # doesn't change the ★ name shown selected up top.
    selected_map_choice: str = ""
    selected_map_path: str = ""
    selected_policy_path: str = str(viewer.DEFAULT_POLICY_PATH)
    selected_policy_config: str = ""
    ghost_policy_path: str = str(viewer.DEFAULT_POLICY_PATH)
    ghost_policy_config: str = ""
    policy_load_error: str = ""
    ghost_policy_load_error: str = ""
    selected_policy_name: str = ""
    ghost_policy_name: str = ""
    show_ghost_replay_slider: bool = False
    policy_is_random: bool = False
    ghost_policy_is_random: bool = False
    has_demo_maps: bool = False
    has_demo_policies: bool = False

    map_count: int = 0
    map_id_input: str = "0"
    selected_map: int = 0
    selected_split: str = "training"

    frame_image: str = ""
    num_frames: int = 0
    current_frame: int = 0
    is_playing: bool = False
    loop_enabled: bool = False  # default off: playback stops at the last frame, no auto-repeat
    play_speed: float = 1.0
    progress_pct: str = "0%"

    selected_agent_idx: int = -1
    selected_agent_str: str = "-1"   # string mirror used for sidebar highlight comparisons
    selected_agent_label: str = ""
    selected_static_slot_str: str = "-1"
    selected_expert_idx: int = -1
    selected_expert_idx_str: str = "-1"
    selected_native_expert_idx: int = -1
    selected_native_expert_idx_str: str = "-1"
    agent_ids: list[int] = []
    agent_labels: list[str] = []              # track ID label per agent slot (matches canvas)
    agent_sidebar_items: list[list[str]] = []  # [[id_str, label, status_str], …] one per agent
    static_sidebar_items: list[list[str]] = []  # [[label, heading_str], …] sim static vehicles
    _click_signal: str = ""
    _ghost_click_signal: str = ""
    _import_signal: str = ""  # JSON text of an uploaded scenario file (set via hidden input)
    _just_removed: bool = False  # suppresses the bubbled select event after any × removal

    status: str = "Enter a map ID and press Load."
    is_loaded: bool = False
    is_busy: bool = False
    resim_progress: int = 0  # 0–100 during active collect_frames; 0 when idle

    @rx.var
    def resim_progress_pct(self) -> str:
        return f"{self.resim_progress}%"

    # Goal editing
    goal_edit_mode: bool = False
    selected_goal_slot: int = -1  # slot of currently selected goal (-1 = none)
    # Goal editor form inputs (world coords)
    goal_edit_x: str = ""
    goal_edit_y: str = ""

    # Agent placement tool
    agent_place_mode: bool = False
    user_agent_count: int = 0   # number of placed dynamic agents
    user_agent_items: list[list[str]] = []  # [[label, heading_str, status_str], ...] updated per frame

    # Static agent placement tool
    static_agent_place_mode: bool = False
    user_static_agent_count: int = 0  # number of placed static agents
    user_static_items: list[list[str]] = []  # [[idx_str, label, heading_str], ...] for placed static agents

    # Expert trajectory placement tool
    expert_place_mode: bool = False
    user_expert_count: int = 0
    user_expert_items: list[list[str]] = []  # [[idx_str, label], ...]

    # Vehicle size selection per tool (S / M / L / XL)
    agent_size: str = "M"
    static_size: str = "M"
    expert_size: str = "M"

    # Simulation step count
    sim_steps: int = 91
    sim_steps_input: str = "91"
    sim_steps_editing: bool = False

    # Base tool selection (pan vs select — other modes have their own bools)
    select_mode: bool = False

    # Move tool — drag an existing car to a new pose (reposition + reorient)
    move_mode: bool = False

    show_goals: bool = True
    show_goal_radius: bool = True
    show_labels: bool = True
    show_trajectories: bool = True
    expert_sidebar_items: list[list[str]] = []  # [[idx_str, type_str], ...]

    # Ghost (secondary) environment
    ghost_env_active: bool = False
    env_focus: str = "primary"  # "primary" | "ghost"
    ghost_side_by_side: bool = False  # render ghost env in its own pane next to the primary
    ghost_diverge_frame: int = 0   # frame index where ghost stops replaying primary actions
    ghost_diverge_pct: str = "0%"  # CSS % for ghost diverge slider track fill
    ghost_agent_sidebar_items: list[list[str]] = []
    ghost_static_sidebar_items: list[list[str]] = []
    ghost_expert_sidebar_items: list[list[str]] = []  # [[idx_str, type_str], ...]
    ghost_native_expert_sidebar_items: list[list[str]] = []  # [[label, 'default', frame_idx_str], ...]
    ghost_user_agent_count: int = 0
    ghost_user_static_agent_count: int = 0
    ghost_user_expert_count: int = 0
    ghost_user_expert_items: list[list[str]] = []
    ghost_user_agent_items: list[list[str]] = []
    ghost_user_static_items: list[list[str]] = []

    # Mirror placement: add agents to both primary and ghost env simultaneously
    mirror_placement: bool = False
    agent_place_target: str = "primary"  # "primary" | "ghost"
    static_place_target: str = "primary"
    selected_ghost_native_expert_idx: int = -1
    selected_ghost_native_expert_idx_str: str = "-1"
    selected_ghost_expert_idx: int = -1
    selected_ghost_expert_idx_str: str = "-1"
    selected_ghost_agent_idx: int = -1
    selected_ghost_agent_str: str = "-1"
    selected_ghost_static_slot_str: str = "-1"

    @rx.var
    def selected_policy_key(self) -> str:
        return f"{self.selected_policy_path}||{self.selected_policy_config}"

    @rx.var
    def ghost_policy_key(self) -> str:
        return f"{self.ghost_policy_path}||{self.ghost_policy_config}"

    # Unified demo slot counter (updated after prepare_demo_slots and each injection)
    demo_slots_used: int = 0
    demo_slots_total: int = 0   # set to _g.MAX_AGENTS - orig_num_actors after prepare

    @rx.var
    def demo_slots_remaining(self) -> int:
        return self.demo_slots_total - self.demo_slots_used

    @rx.var
    def demo_slots_full(self) -> bool:
        return self.demo_slots_total > 0 and self.demo_slots_used >= self.demo_slots_total

    @rx.var
    def demo_slots_label(self) -> str:
        return f"{self.demo_slots_total - self.demo_slots_used}/{_g.MAX_AGENTS} slots free"

    @rx.var
    def demo_slots_full_label(self) -> str:
        return f"All agent slots full ({self.demo_slots_used}/{_g.MAX_AGENTS})"

    # Ghost env slot counter (independent of primary)
    ghost_demo_slots_used: int = 0
    ghost_demo_slots_total: int = 0

    @rx.var
    def ghost_demo_slots_remaining(self) -> int:
        return self.ghost_demo_slots_total - self.ghost_demo_slots_used

    # Keep the three individual checks as aliases for demo_slots_full
    @rx.var
    def active_slots_full(self) -> bool:
        return self.demo_slots_full

    @rx.var
    def static_slots_full(self) -> bool:
        return self.demo_slots_full

    @rx.var
    def expert_slots_full(self) -> bool:
        return self.demo_slots_full


    @rx.var
    def pan_active(self) -> bool:
        return (not self.select_mode and not self.goal_edit_mode
                and not self.agent_place_mode and not self.static_agent_place_mode
                and not self.expert_place_mode and not self.move_mode)

    @rx.var
    def goal_edit_hint(self) -> str:
        return "Drag a goal marker to reposition it"

    def toggle_goal_edit(self):
        self._reset_to_first_frame()
        self.goal_edit_mode = not self.goal_edit_mode
        self.agent_place_mode = False
        self.static_agent_place_mode = False
        self.expert_place_mode = False
        self.move_mode = False
        self.select_mode = False
        self.selected_goal_slot = -1
        if self.goal_edit_mode:
            self.is_playing = False
            yield rx.call_script(
                "if(window._pdStopRaf)window._pdStopRaf();"
                "if(window._pdSetTool)window._pdSetTool('goal');"
            )
            if _g._env is not None:
                yield rx.call_script(_goal_js(_compute_goal_positions()))
        else:
            yield rx.call_script("if (window._pdSetTool) window._pdSetTool('pan');")

    def toggle_move(self):
        self._reset_to_first_frame()
        self.move_mode = not self.move_mode
        self.goal_edit_mode = False
        self.agent_place_mode = False
        self.static_agent_place_mode = False
        self.expert_place_mode = False
        self.select_mode = False
        self.selected_goal_slot = -1
        if self.move_mode:
            yield rx.call_script("if (window._pdSetTool) window._pdSetTool('move');")
        else:
            yield rx.call_script("if (window._pdSetTool) window._pdSetTool('pan');")

    def _vehicle_sizes_js(self) -> str:
        """Build JS snippet that updates window._pdVehicleSizes with current size selections."""
        def _hw(size_key):
            sz = VEHICLE_SIZES.get(size_key, VEHICLE_SIZES["M"])
            return sz["length"] / 2.0, sz["width"] / 2.0
        ahl, ahw = _hw(self.agent_size)
        shl, shw = _hw(self.static_size)
        ehl, ehw = _hw(self.expert_size)
        return (
            f"window._pdVehicleSizes={{"
            f"add_agent:{{hl:{ahl},hw:{ahw}}},"
            f"add_static:{{hl:{shl},hw:{shw}}},"
            f"add_expert:{{hl:{ehl},hw:{ehw}}}"
            f"}};"
            f"if(window._pdRedraw)window._pdRedraw();"
        )

    def set_agent_size(self, size: str):
        self.agent_size = size
        yield rx.call_script(self._vehicle_sizes_js())

    def set_static_size(self, size: str):
        self.static_size = size
        yield rx.call_script(self._vehicle_sizes_js())

    def set_expert_size(self, size: str):
        self.expert_size = size
        yield rx.call_script(self._vehicle_sizes_js())

    def toggle_agent_place(self):
        self._reset_to_first_frame()
        self.agent_place_mode = not self.agent_place_mode
        self.goal_edit_mode = False
        self.static_agent_place_mode = False
        self.expert_place_mode = False
        self.move_mode = False
        self.select_mode = False
        self.selected_goal_slot = -1
        if self.agent_place_mode:
            self._reset_to_first_frame()
            yield rx.call_script(
                "if(window._pdStopRaf)window._pdStopRaf();"
                "if(window._pdSetTool)window._pdSetTool('add_agent');"
            )
        else:
            yield rx.call_script("if (window._pdSetTool) window._pdSetTool('pan');")

    async def handle_agent_place(self, data):
        """Receive 3-click placement data and resimulate with the new agent."""
        if not isinstance(data, dict):
            return
        mirror = self.mirror_placement and self.ghost_env_active
        is_ghost = not mirror and self.env_focus == "ghost" and self.ghost_env_active
        target_env = _g._ghost_env if is_ghost else _g._env
        if target_env is None:
            return
        if self.demo_slots_full:
            self.status = f"No demo slots left ({self.demo_slots_used}/{self.demo_slots_total} used)"
            return
        pos = viewer.frac_to_world(float(data["pfx"]), float(data["pfy"]))
        hdg = viewer.frac_to_world(float(data["hfx"]), float(data["hfy"]))
        goal = viewer.frac_to_world(float(data["gfx"]), float(data["gfy"]))
        if pos is None or hdg is None or goal is None:
            return
        heading = math.atan2(hdg[1] - pos[1], hdg[0] - pos[0])
        label = f"{_g._user_agent_name_counter}"
        _g._user_agent_name_counter += 1
        _asz = VEHICLE_SIZES.get(self.agent_size, VEHICLE_SIZES["M"])
        agent_data = {
            "x": pos[0], "y": pos[1],
            "heading": heading,
            "goal_x": goal[0], "goal_y": goal[1],
            "label": label,
            "length": _asz["length"],
            "width": _asz["width"],
        }
        if mirror:
            _g._user_agents.append(agent_data)
            _g._ghost_user_agents.append(dict(agent_data))
            self.user_agent_count = len(_g._user_agents)
            self.ghost_user_agent_count = len(_g._ghost_user_agents)
            self.status = "Agent placed in both envs — resimulating…"
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            for _ev in self.ghost_resimulate(): yield _ev
        elif is_ghost:
            _g._ghost_user_agents.append(agent_data)
            self.ghost_user_agent_count = len(_g._ghost_user_agents)
            self.status = "Ghost agent placed — resimulating ghost…"
            for _ev in self.ghost_resimulate(): yield _ev
        else:
            _g._user_agents.append(agent_data)
            self.user_agent_count = len(_g._user_agents)
            self.status = "Agent placed — resimulating…"
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev

    # ── Move tool ──────────────────────────────────────────────────────────────

    def _native_goal_world(self, slot: int):
        """World goal (x, y) of a native active agent at env ``slot``, or None."""
        if slot in _g._goal_overrides:
            return _g._goal_overrides[slot]
        for p in viewer.initial_goal_positions:
            if p.get("slot") == slot:
                return viewer.frac_to_world(p["fx"], p["fy"])
        return None

    def _native_expert_end_world(self, frame_idx: int):
        """World end-position of a native expert (last render frame), or None."""
        bounds = _g._render_bounds
        if not bounds or not _g._expert_render_frames:
            return None
        scale = bounds.get("scale", 1.0) or 1.0
        min_x, max_y = bounds.get("min_x", 0.0), bounds.get("max_y", 0.0)
        for fr in reversed(_g._expert_render_frames):
            if frame_idx < len(fr):
                e = fr[frame_idx]
                return (min_x + e["cx"] / scale, max_y - e["cy"] / scale)
        return None

    async def handle_agent_move(self, data):
        """Move tool: reposition + reorient the dragged car (primary env).

        ``data`` carries image fractions: start (sfx,sfy) identifies the grabbed car,
        drop (dfx,dfy) is the new centre, heading point (hfx,hfy) sets orientation.
        Active/static cars get the new pose (active keeps its goal); experts only move
        if a valid road-lane trajectory exists from the new start, else they snap back.
        """
        if not isinstance(data, dict) or _g._env is None or not _g._render_bounds:
            return
        try:
            sfx, sfy = float(data["sfx"]), float(data["sfy"])
            drop = viewer.frac_to_world(float(data["dfx"]), float(data["dfy"]))
            head = viewer.frac_to_world(float(data["hfx"]), float(data["hfy"]))
        except (KeyError, ValueError, TypeError):
            return
        if drop is None:
            return
        heading = (math.atan2(head[1] - drop[1], head[0] - drop[0])
                   if head is not None and head != drop else 0.0)

        bounds = _g._render_bounds
        start_px = sfx * bounds.get("img_w", 1)
        start_py = sfy * bounds.get("img_h", 1)
        # Both/mirror mode: apply the same move to the ghost car at the corresponding
        # slot/index (envs are index-aligned in mirror mode; drop/heading are world coords).
        mirror = self._mirror_active()

        # Identify the grabbed car using the same hit-test ladder as on_click_signal.
        agent_idx = viewer.find_agent_at_pixel(
            start_px, start_py, self.current_frame, _g._agent_states, bounds
        ) if _g._agent_states else -1
        if agent_idx >= 0:
            async for _ev in self._move_active(agent_idx, drop, heading): yield _ev
            if mirror:
                for _ev in self._move_active_ghost(agent_idx, drop, heading): yield _ev
            return

        static_slot = viewer.find_static_agent_at_pixel(
            start_px, start_py, _g._static_agents
        ) if _g._static_agents else -1
        if static_slot >= 0:
            async for _ev in self._move_static(static_slot, drop, heading): yield _ev
            if mirror:
                for _ev in self._move_static_ghost(static_slot, drop, heading): yield _ev
            return

        if _g._expert_render_frames and self.current_frame < len(_g._expert_render_frames):
            expert_frame = _g._expert_render_frames[self.current_frame]
            frame_idx = viewer.find_expert_at_pixel(start_px, start_py, expert_frame)
            if frame_idx >= 0:
                # JS sends the lane-snapped goal (gfx,gfy) so placement matches the preview.
                goal_override = None
                try:
                    if data.get("gfx") is not None and data.get("gfy") is not None:
                        goal_override = viewer.frac_to_world(float(data["gfx"]), float(data["gfy"]))
                except (ValueError, TypeError):
                    goal_override = None
                n_user = len(_g._user_expert_agents)
                user_idx = frame_idx - (len(expert_frame) - n_user)
                async for _ev in self._move_expert(frame_idx, user_idx, n_user, drop, heading, goal_override): yield _ev
                if mirror:
                    # Pass goal_override=None so the ghost expert keeps its ORIGINAL goal,
                    # matching _move_expert's rule — otherwise the two envs get different
                    # goals (lane-snapped vs original) and diverge.
                    for _ev in self._move_expert_ghost(frame_idx, user_idx, n_user, drop, heading, None): yield _ev
                return
        self.status = "Move: no car under the cursor."

    async def _move_active(self, slot, drop, heading):
        if slot in _g._user_agent_slots:
            ui = _g._user_agent_slots.index(slot)
            if 0 <= ui < len(_g._user_agents):
                _g._user_agents[ui]["x"], _g._user_agents[ui]["y"] = drop[0], drop[1]
                _g._user_agents[ui]["heading"] = heading
                self.status = "Agent moved — resimulating…"
                async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
                return
        # Native: reposition in place via teleport so it keeps its slot/ID and goal.
        goal = self._native_goal_world(slot)
        if goal is None:
            goal = (drop[0] + math.cos(heading) * 20.0, drop[1] + math.sin(heading) * 20.0)
        _g._native_active_moves[slot] = (drop[0], drop[1], heading, goal[0], goal[1])
        self.status = "Agent moved — resimulating…"
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev

    async def _move_static(self, slot, drop, heading):
        if slot in _g._user_static_agent_slots:
            ui = _g._user_static_agent_slots.index(slot)
            if 0 <= ui < len(_g._user_static_agents):
                _g._user_static_agents[ui]["x"], _g._user_static_agents[ui]["y"] = drop[0], drop[1]
                _g._user_static_agents[ui]["heading"] = heading
                self.status = "Static moved — resimulating…"
                async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
                return
        # Native static: reposition in place (teleport keeps slot/ID). The render slot of a
        # native static equals its stable label, so key the move by that label and re-derive
        # the live C index each resimulate.
        _g._native_static_moves[str(slot)] = (drop[0], drop[1], heading)
        self.status = "Static moved — resimulating…"
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev

    async def _move_expert(self, frame_idx, user_idx, n_user, drop, heading, goal_override=None):
        sim = self.sim_steps
        if 0 <= user_idx < n_user:
            # Keep the expert's ORIGINAL goal — moving the start must still reach it, else revert.
            # (goal_override is the JS lane-snapped goal, which can snap onto a different,
            # reachable lane and mask the fact that the true goal is no longer reachable.)
            ea = dict(_g._user_expert_agents[user_idx])
            ea["sx"], ea["sy"], ea["sh"] = drop[0], drop[1], heading
            ea["waypoints"] = []
            for k in ("traj_manual", "traj_xs", "traj_ys", "traj_hs"):
                ea.pop(k, None)
            if _compute_expert_trajectory(ea, sim) is None:
                self.status = "Fixed Trajectory move reverted — can't reach its goal from there."
                return
            _g._user_expert_agents[user_idx] = ea
            self.status = "Fixed Trajectory moved — resimulating…"
            saved = self.selected_expert_idx
            self.selected_expert_idx = -1
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            if saved >= 0:
                for _ev in self.select_expert(str(saved)): yield _ev
            return
        # Native expert: reposition in place (teleport replaces its trajectory, keeps slot/ID).
        # Target the TRUE original goal (the expert's last logged position) — the move is only
        # allowed if a road-lane path from the new start still reaches it, else revert. Falling
        # back to the JS-snapped goal would let it move to a different, reachable lane instead.
        end = self._native_expert_end_world(frame_idx)
        if end is None:
            end = goal_override
        if end is None:
            self.status = "Fixed Trajectory move reverted — original goal unknown."
            return
        label = (_g._native_expert_labels[frame_idx]
                 if 0 <= frame_idx < len(_g._native_expert_labels) else str(frame_idx))
        ea = {"sx": drop[0], "sy": drop[1], "sh": heading,
              "ex": end[0], "ey": end[1], "eh": heading, "waypoints": [], "label": str(label)}
        if _compute_expert_trajectory(ea, sim) is None:
            self.status = "Fixed Trajectory move reverted — can't reach its goal from there."
            return
        _g._native_expert_moves[str(label)] = ea
        self.status = "Fixed Trajectory moved — resimulating…"
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev

    # ── Ghost move tool ────────────────────────────────────────────────────────

    def _ghost_native_goal_world(self, slot: int):
        if slot in _g._ghost_goal_overrides:
            return _g._ghost_goal_overrides[slot]
        for p in viewer.initial_goal_positions:
            if p.get("slot") == slot:
                return viewer.frac_to_world(p["fx"], p["fy"])
        return None

    def _ghost_native_expert_end_world(self, frame_idx: int):
        bounds = _g._ghost_render_bounds
        if not bounds or not _g._ghost_expert_render_frames:
            return None
        scale = bounds.get("scale", 1.0) or 1.0
        min_x, max_y = bounds.get("min_x", 0.0), bounds.get("max_y", 0.0)
        for fr in reversed(_g._ghost_expert_render_frames):
            if frame_idx < len(fr):
                e = fr[frame_idx]
                return (min_x + e["cx"] / scale, max_y - e["cy"] / scale)
        return None

    async def handle_ghost_agent_move(self, data):
        if not isinstance(data, dict):
            return
        async for _ev in self._do_ghost_move(data): yield _ev

    async def _do_ghost_move(self, data):
        if not isinstance(data, dict) or _g._ghost_env is None or not _g._ghost_render_bounds:
            return
        try:
            sfx, sfy = float(data["sfx"]), float(data["sfy"])
            drop = viewer.frac_to_world(float(data["dfx"]), float(data["dfy"]))
            head = viewer.frac_to_world(float(data["hfx"]), float(data["hfy"]))
        except (KeyError, ValueError, TypeError):
            return
        if drop is None:
            return
        heading = (math.atan2(head[1] - drop[1], head[0] - drop[0])
                   if head is not None and head != drop else 0.0)
        bounds = _g._ghost_render_bounds
        start_px = sfx * bounds.get("img_w", 1)
        start_py = sfy * bounds.get("img_h", 1)
        # Both/mirror mode: apply the same move to the primary car at the corresponding slot.
        mirror = self._mirror_active()
        agent_idx = viewer.find_agent_at_pixel(
            start_px, start_py, self.current_frame, _g._ghost_agent_states, bounds
        ) if _g._ghost_agent_states else -1
        if agent_idx >= 0:
            for _ev in self._move_active_ghost(agent_idx, drop, heading): yield _ev
            if mirror:
                async for _ev in self._move_active(agent_idx, drop, heading): yield _ev
            return
        static_slot = viewer.find_static_agent_at_pixel(
            start_px, start_py, _g._ghost_static_agents
        ) if _g._ghost_static_agents else -1
        if static_slot >= 0:
            for _ev in self._move_static_ghost(static_slot, drop, heading): yield _ev
            if mirror:
                async for _ev in self._move_static(static_slot, drop, heading): yield _ev
            return
        if _g._ghost_expert_render_frames and self.current_frame < len(_g._ghost_expert_render_frames):
            expert_frame = _g._ghost_expert_render_frames[self.current_frame]
            frame_idx = viewer.find_expert_at_pixel(start_px, start_py, expert_frame)
            if frame_idx >= 0:
                goal_override = None
                try:
                    if data.get("gfx") is not None and data.get("gfy") is not None:
                        goal_override = viewer.frac_to_world(float(data["gfx"]), float(data["gfy"]))
                except (ValueError, TypeError):
                    goal_override = None
                n_user = len(_g._ghost_user_expert_agents)
                user_idx = frame_idx - (len(expert_frame) - n_user)
                # In mirror mode drop the lane-snapped goal_override so the ghost expert
                # keeps its ORIGINAL goal — matching primary _move_expert — so both envs
                # move identically instead of diverging on goal.
                _ov = None if mirror else goal_override
                for _ev in self._move_expert_ghost(frame_idx, user_idx, n_user, drop, heading, _ov): yield _ev
                if mirror:
                    async for _ev in self._move_expert(frame_idx, user_idx, n_user, drop, heading, None): yield _ev
                return
        self.status = "Move: no car under the cursor (ghost)."

    def _move_active_ghost(self, slot, drop, heading):
        if slot in _g._ghost_user_agent_slots:
            ui = _g._ghost_user_agent_slots.index(slot)
            if 0 <= ui < len(_g._ghost_user_agents):
                _g._ghost_user_agents[ui]["x"], _g._ghost_user_agents[ui]["y"] = drop[0], drop[1]
                _g._ghost_user_agents[ui]["heading"] = heading
                self.status = "Agent moved — resimulating ghost…"
                yield from self.ghost_resimulate()
                return
        goal = self._ghost_native_goal_world(slot)
        if goal is None:
            goal = (drop[0] + math.cos(heading) * 20.0, drop[1] + math.sin(heading) * 20.0)
        _g._ghost_native_active_moves[slot] = (drop[0], drop[1], heading, goal[0], goal[1])
        self.status = "Agent moved — resimulating ghost…"
        yield from self.ghost_resimulate()

    def _move_static_ghost(self, slot, drop, heading):
        if slot in _g._ghost_user_static_agent_slots:
            ui = _g._ghost_user_static_agent_slots.index(slot)
            if 0 <= ui < len(_g._ghost_user_static_agents):
                _g._ghost_user_static_agents[ui]["x"], _g._ghost_user_static_agents[ui]["y"] = drop[0], drop[1]
                _g._ghost_user_static_agents[ui]["heading"] = heading
                self.status = "Static moved — resimulating ghost…"
                yield from self.ghost_resimulate()
                return
        _g._ghost_native_static_moves[str(slot)] = (drop[0], drop[1], heading)
        self.status = "Static moved — resimulating ghost…"
        yield from self.ghost_resimulate()

    def _move_expert_ghost(self, frame_idx, user_idx, n_user, drop, heading, goal_override=None):
        sim = self.sim_steps
        if 0 <= user_idx < n_user:
            ea = dict(_g._ghost_user_expert_agents[user_idx])
            ea["sx"], ea["sy"], ea["sh"] = drop[0], drop[1], heading
            if goal_override is not None:
                ea["ex"], ea["ey"] = goal_override
            ea["waypoints"] = []
            for k in ("traj_manual", "traj_xs", "traj_ys", "traj_hs"):
                ea.pop(k, None)
            if _compute_expert_trajectory(ea, sim) is None:
                self.status = "Fixed Trajectory move reverted — no valid road-lane trajectory there."
                return
            _g._ghost_user_expert_agents[user_idx] = ea
            self.status = "Fixed Trajectory moved — resimulating ghost…"
            yield from self.ghost_resimulate()
            return
        end = goal_override if goal_override is not None else self._ghost_native_expert_end_world(frame_idx)
        if end is None:
            end = (drop[0] + math.cos(heading) * 20.0, drop[1] + math.sin(heading) * 20.0)
        label = (_g._ghost_native_expert_labels[frame_idx]
                 if 0 <= frame_idx < len(_g._ghost_native_expert_labels) else str(frame_idx))
        ea = {"sx": drop[0], "sy": drop[1], "sh": heading,
              "ex": end[0], "ey": end[1], "eh": heading, "waypoints": [], "label": str(label)}
        if _compute_expert_trajectory(ea, sim) is None:
            self.status = "Fixed Trajectory move reverted — no valid road-lane trajectory there."
            return
        _g._ghost_native_expert_moves[str(label)] = ea
        self.status = "Fixed Trajectory moved — resimulating ghost…"
        yield from self.ghost_resimulate()

    async def remove_user_agent(self, idx: str):
        i = int(idx)
        if 0 <= i < len(_g._user_agents):
            _g._user_agents.pop(i)
            self.user_agent_count = len(_g._user_agents)
            if not _g._user_agents:
                self.user_agent_items = []
            # Both/mirror mode: remove the same-index ghost counterpart too.
            mirror = self._mirror_active() and 0 <= i < len(_g._ghost_user_agents)
            if mirror:
                _g._ghost_user_agents.pop(i)
                self.ghost_user_agent_count = len(_g._ghost_user_agents)
                if not _g._ghost_user_agents:
                    self.ghost_user_agent_items = []
            self.status = "Agent removed — resimulating…"
            for _ev in self.clear_selection(): yield _ev
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            if mirror:
                for _ev in self.ghost_resimulate(): yield _ev
            self._just_removed = True

    async def remove_vehicle(self, slot_str: str):
        _g._removed_slots.add(int(slot_str))
        _g._env_has_detaches = True
        mirror = self._mirror_active()
        if mirror:
            _g._ghost_removed_slots.add(int(slot_str))
        self.status = f"Vehicle {slot_str} removed — resimulating…"
        for _ev in self.clear_selection(): yield _ev
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        if mirror:
            for _ev in self.ghost_resimulate(): yield _ev
        self._just_removed = True

    async def remove_static_vehicle(self, slot_str: str):
        slot = int(slot_str)
        _g._removed_static_slots.add(slot)
        _g._pending_static_detach_slots.add(slot)
        _g._env_has_detaches = True
        mirror = self._mirror_active()
        if mirror:
            _g._ghost_removed_static_slots.add(slot)
        self.status = f"Static vehicle {slot_str} removed — resimulating…"
        for _ev in self.clear_selection(): yield _ev
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        if mirror:
            for _ev in self.ghost_resimulate(): yield _ev
        self._just_removed = True

    def clear_user_agents(self):
        _g._user_agents = []
        self.user_agent_count = 0
        self.user_agent_items = []
        self.status = "Cleared all placed agents — press Resimulate"

    # ── Ghost env agent management ─────────────────────────────────────────────

    async def remove_ghost_user_agent(self, idx: str):
        i = int(idx)
        if 0 <= i < len(_g._ghost_user_agents):
            _g._ghost_user_agents.pop(i)
            self.ghost_user_agent_count = len(_g._ghost_user_agents)
            if not _g._ghost_user_agents:
                self.ghost_user_agent_items = []
            # Both/mirror mode: remove the same-index primary counterpart too.
            mirror = self._mirror_active() and 0 <= i < len(_g._user_agents)
            if mirror:
                _g._user_agents.pop(i)
                self.user_agent_count = len(_g._user_agents)
                if not _g._user_agents:
                    self.user_agent_items = []
                for _ev in self.clear_selection(): yield _ev
            self.status = "Ghost agent removed — resimulating ghost…"
            for _ev in self.ghost_resimulate(): yield _ev
            if mirror:
                async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            self._just_removed = True

    async def remove_ghost_vehicle(self, slot_str: str):
        _g._ghost_removed_slots.add(int(slot_str))
        mirror = self._mirror_active()
        if mirror:
            _g._removed_slots.add(int(slot_str))
            _g._env_has_detaches = True
        self.status = f"Ghost vehicle {slot_str} removed — resimulating ghost…"
        for _ev in self.ghost_resimulate(): yield _ev
        if mirror:
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        self._just_removed = True

    async def remove_ghost_static_vehicle(self, slot_str: str):
        slot = int(slot_str)
        _g._ghost_removed_static_slots.add(slot)
        mirror = self._mirror_active()
        if mirror:
            _g._removed_static_slots.add(slot)
            _g._pending_static_detach_slots.add(slot)
            _g._env_has_detaches = True
        self.status = f"Ghost static vehicle {slot_str} removed — resimulating ghost…"
        for _ev in self.ghost_resimulate(): yield _ev
        if mirror:
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        self._just_removed = True

    async def remove_ghost_user_static_agent(self, idx: str):
        i = int(idx)
        if 0 <= i < len(_g._ghost_user_static_agents):
            _g._ghost_user_static_agents.pop(i)
            self.ghost_user_static_agent_count = len(_g._ghost_user_static_agents)
            if not _g._ghost_user_static_agents:
                self.ghost_user_static_items = []
            mirror = self._mirror_active() and 0 <= i < len(_g._user_static_agents)
            if mirror:
                _g._user_static_agents.pop(i)
                self.user_static_agent_count = len(_g._user_static_agents)
                if not _g._user_static_agents:
                    self.user_static_items = []
                for _ev in self.clear_selection(): yield _ev
            self.status = "Ghost static agent removed — resimulating ghost…"
            for _ev in self.ghost_resimulate(): yield _ev
            if mirror:
                async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            self._just_removed = True

    async def remove_ghost_native_expert(self, frame_idx_str: str):
        i = int(frame_idx_str)
        _g._ghost_removed_native_expert_idxs.add(i)
        self.selected_ghost_native_expert_idx = -1
        self.selected_ghost_native_expert_idx_str = "-1"
        mirror = self._mirror_active()
        if mirror:
            _g._removed_native_expert_idxs.add(i)
            _g._pending_expert_detach_idxs.add(i)
            _g._env_has_detaches = True
        self.status = "Ghost native fixed trajectory removed — resimulating ghost…"
        for _ev in self.ghost_resimulate(): yield _ev
        if mirror:
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        self._just_removed = True

    async def remove_ghost_user_expert_agent(self, idx_str: str):
        i = int(idx_str)
        if 0 <= i < len(_g._ghost_user_expert_agents):
            _g._ghost_user_expert_agents.pop(i)
            self.ghost_user_expert_count = len(_g._ghost_user_expert_agents)
            if not _g._ghost_user_expert_agents:
                self.ghost_user_expert_items = []
            self.selected_ghost_expert_idx = -1
            self.selected_ghost_expert_idx_str = "-1"
            mirror = self._mirror_active() and 0 <= i < len(_g._user_expert_agents)
            if mirror:
                _g._user_expert_agents.pop(i)
                self.user_expert_count = len(_g._user_expert_agents)
                if not _g._user_expert_agents:
                    self.user_expert_items = []
                for _ev in self.clear_selection(): yield _ev
            self.status = "Ghost fixed trajectory agent removed — resimulating ghost…"
            for _ev in self.ghost_resimulate(): yield _ev
            if mirror:
                async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            self._just_removed = True

    def select_ghost_native_expert(self, idx_str: str):
        if self._just_removed:
            self._just_removed = False
            return
        self._reset_to_first_frame()
        i = int(idx_str)
        if self.selected_ghost_native_expert_idx == i:
            self.selected_ghost_native_expert_idx = -1
            self.selected_ghost_native_expert_idx_str = "-1"
            return rx.call_script(
                "window._pdGhostSelectedNativeExpertIdx = -1;"
                "if(window._pdRedraw)window._pdRedraw();"
            )
        self._reset_selection_vars()
        self.selected_ghost_native_expert_idx = i
        self.selected_ghost_native_expert_idx_str = idx_str
        return rx.call_script(
            _CLEAR_ALL_SELECT_JS
            + self._focus_env_js("ghost")
            + f"window._pdGhostSelectedNativeExpertIdx = {i};"
            + self._primary_link_js("native_expert", i)
            + f"if(window._pdRedraw)window._pdRedraw();"
            f"var el=document.getElementById('pd-ghost-native-expert-row-{i}');"
            f"if(el)el.scrollIntoView({{block:'nearest'}});"
        )

    def select_ghost_expert(self, idx_str: str):
        if self._just_removed:
            self._just_removed = False
            return
        self._reset_to_first_frame()
        i = int(idx_str)
        if self.selected_ghost_expert_idx == i:
            self.selected_ghost_expert_idx = -1
            self.selected_ghost_expert_idx_str = "-1"
            return rx.call_script(
                "window._pdGhostSelectedExpertIdx = -1; window._pdGhostSelectedExpertSlot = -1;"
                "if(window._pdGhostRenderer) window._pdGhostRenderer.setSelectedExpert(-1);"
                "if(window._pdRedraw)window._pdRedraw();"
            )
        self._reset_selection_vars()
        self.selected_ghost_expert_idx = i
        self.selected_ghost_expert_idx_str = idx_str
        self.select_mode = True
        slot = _g._ghost_user_expert_agent_slots[i] if 0 <= i < len(_g._ghost_user_expert_agent_slots) else -1
        return rx.call_script(
            f"if(window._pdSetTool)window._pdSetTool('select');"
            + _CLEAR_ALL_SELECT_JS
            + self._focus_env_js("ghost")
            + self._primary_link_js("expert", i)
            + f"window._pdGhostSelectedExpertIdx = {i}; window._pdGhostSelectedExpertSlot = {slot};"
            f"if(window._pdGhostRenderer){{"
            f"window._pdGhostRenderer.setSelectedExpert({slot});}}"
            f"if(window._pdRedraw)window._pdRedraw();"
            f"var el=document.getElementById('pd-ghost-user-expert-row-{i}');"
            f"if(el)el.scrollIntoView({{block:'nearest'}});"
        )

    def select_ghost_agent(self, idx):
        if self._just_removed:
            self._just_removed = False
            return
        self._reset_to_first_frame()
        i = int(idx) if not isinstance(idx, int) else idx
        if self.selected_ghost_agent_idx == i:
            self.selected_ghost_agent_idx = -1
            self.selected_ghost_agent_str = "-1"
            return rx.call_script(
                "if(window._pdGhostRenderer) window._pdGhostRenderer.setSelected(-1);"
                "if(window._pdRedraw)window._pdRedraw();"
            )
        # Mutually exclusive: clear every other selection, then set this one.
        self._reset_selection_vars()
        self.selected_ghost_agent_idx = i
        self.selected_ghost_agent_str = str(i)
        return rx.call_script(
            f"(function(){{"
            + _CLEAR_ALL_SELECT_JS
            + self._focus_env_js("ghost")
            + self._primary_link_js("agent", i)
            + f"if(window._pdGhostRenderer){{"
            f"window._pdGhostRenderer.setSelected({i});}}"
            f"if(window._pdRedraw)window._pdRedraw();"
            f"var el=document.getElementById('pd-ghost-agent-row-{i}');"
            f"if(el)el.scrollIntoView({{block:'nearest'}});"
            f"}})();"
        )

    def select_ghost_static_agent(self, slot_str):
        if self._just_removed:
            self._just_removed = False
            return
        self._reset_to_first_frame()
        if self.selected_ghost_static_slot_str == slot_str:
            self.selected_ghost_static_slot_str = "-1"
            return rx.call_script(
                "if(window._pdGhostRenderer) window._pdGhostRenderer.setSelectedStatic(-1);"
                "if(window._pdRedraw)window._pdRedraw();"
            )
        # Mutually exclusive: clear every other selection, then set this one.
        self._reset_selection_vars()
        self.selected_ghost_static_slot_str = slot_str
        slot = int(slot_str)
        return rx.call_script(
            f"(function(){{"
            + _CLEAR_ALL_SELECT_JS
            + self._focus_env_js("ghost")
            + self._primary_link_js("static", slot)
            + f"if(window._pdGhostRenderer){{"
            f"window._pdGhostRenderer.setSelectedStatic({slot});}}"
            f"if(window._pdRedraw)window._pdRedraw();"
            f"var el=document.getElementById('pd-ghost-static-row-{slot}');"
            f"if(el)el.scrollIntoView({{block:'nearest'}});"
            f"}})();"
        )

    # ── Ghost env focus / toggle ───────────────────────────────────────────────

    def _focus_env_js(self, focus: str) -> str:
        """Give `focus` env primary focus without disturbing the active tool.

        Sets the reactive Python state and returns the JS snippet to prepend to a
        selection handler's call_script. Unlike set_env_focus(), it leaves the
        tool/placement state alone so select mode is preserved.
        """
        self.env_focus = focus
        return f"window._pdEnvFocus='{focus}';"

    def _mirror_active(self) -> bool:
        """True when Both/mirror mode is on and a ghost env exists to mirror into."""
        return self.mirror_placement and self.ghost_env_active and _g._ghost_env is not None

    def _ghost_link_js(self, kind: str, i: int) -> str:
        """In mirror mode, also select the ghost counterpart of a primary selection.

        Sets the reactive ghost-selection var (so the ghost sidebar row highlights) and
        returns JS driving the ghost renderer/`window._pd*` state. Returns "" when not
        mirroring. Called while building a primary setter's call_script, after that
        setter has already emitted _CLEAR_ALL_SELECT_JS (which clears both envs)."""
        if not self._mirror_active():
            return ""
        if kind == "expert":
            slot = _g._ghost_user_expert_agent_slots[i] if 0 <= i < len(_g._ghost_user_expert_agent_slots) else -1
            self.selected_ghost_expert_idx = i
            self.selected_ghost_expert_idx_str = str(i)
            return (f"window._pdGhostSelectedExpertIdx={i};window._pdGhostSelectedExpertSlot={slot};"
                    f"if(window._pdGhostRenderer)window._pdGhostRenderer.setSelectedExpert({slot});")
        if kind == "native_expert":
            self.selected_ghost_native_expert_idx = i
            self.selected_ghost_native_expert_idx_str = str(i)
            return f"window._pdGhostSelectedNativeExpertIdx={i};"
        if kind == "agent":
            self.selected_ghost_agent_idx = i
            self.selected_ghost_agent_str = str(i)
            return f"if(window._pdGhostRenderer)window._pdGhostRenderer.setSelected({i});"
        if kind == "static":
            self.selected_ghost_static_slot_str = str(i)
            return f"if(window._pdGhostRenderer)window._pdGhostRenderer.setSelectedStatic({i});"
        return ""

    def _primary_link_js(self, kind: str, i: int) -> str:
        """In mirror mode, also select the primary counterpart of a ghost selection.

        Mirror image of _ghost_link_js — used inside the ghost setters' call_script."""
        if not self._mirror_active():
            return ""
        if kind == "expert":
            slot = _g._user_expert_agent_slots[i] if 0 <= i < len(_g._user_expert_agent_slots) else -1
            self.selected_expert_idx = i
            self.selected_expert_idx_str = str(i)
            return (f"window._pdSelectedExpertIdx={i};window._pdSelectedExpertSlot={slot};"
                    f"if(window._pdAgentRenderer)window._pdAgentRenderer.setSelectedExpert({slot});")
        if kind == "native_expert":
            self.selected_native_expert_idx = i
            self.selected_native_expert_idx_str = str(i)
            return f"window._pdSelectedNativeExpertIdx={i};"
        if kind == "agent":
            self.selected_agent_idx = i
            self.selected_agent_str = str(i)
            self.selected_agent_label = f"#{i}"
            return f"if(window._pdAgentRenderer)window._pdAgentRenderer.setSelected({i});"
        if kind == "static":
            self.selected_static_slot_str = str(i)
            return f"if(window._pdAgentRenderer)window._pdAgentRenderer.setSelectedStatic({i});"
        return ""

    def set_env_focus(self, focus: str):
        self.env_focus = focus
        # Switching envs resets the JS tool to pan; clear every server tool mode
        # to match, so the goal/select buttons don't need a double-click after.
        self._clear_tool_modes()
        return rx.call_script(
            f"window._pdEnvFocus = '{focus}';"
            "window._pdAgentPlacement = {step:0};"
            "window._pdStaticPlacement = {step:0};"
            "if (window._pdSetTool) window._pdSetTool('pan');"
            "if (window._pdRedraw) window._pdRedraw();"
        )

    def toggle_env_focus(self):
        new_focus = "primary" if self.env_focus == "ghost" else "ghost"
        self.env_focus = new_focus
        # Switching envs resets the JS tool to pan; clear every server tool mode
        # to match, so the goal/select buttons don't need a double-click after.
        self._clear_tool_modes()
        yield rx.call_script(
            f"window._pdEnvFocus = '{new_focus}';"
            "window._pdAgentPlacement = {step:0};"
            "window._pdStaticPlacement = {step:0};"
            "if (window._pdSetTool) window._pdSetTool('pan');"
            "if (window._pdRedraw) window._pdRedraw();"
        )

    def toggle_ghost_side_by_side(self):
        # The JS renderer detects split mode from the ghost pane's presence in the
        # DOM; the pan-wrapper ResizeObserver redraws once the pane mounts/unmounts.
        self.ghost_side_by_side = not self.ghost_side_by_side
        return rx.call_script("if (window._pdRedraw) window._pdRedraw();")

    def toggle_mirror_placement(self):
        """Toggle mirror mode: when on, placements go into both primary and ghost env."""
        self._reset_to_first_frame()
        self.mirror_placement = not self.mirror_placement

    def _deactivate_ghost(self):
        """Tear down the ghost env and clear all ghost state (Python + client JS)."""
        self.ghost_env_active = False
        self.env_focus = "primary"
        _g._ghost_env = None
        _g._ghost_policy = None
        _g._ghost_agent_render_frames = []
        _g._ghost_expert_render_frames = []
        _g._ghost_static_agents = []
        _g._ghost_map_data = {}
        _g._ghost_agent_states = []
        _g._ghost_agent_status_frames = []
        _g._ghost_render_bounds = {}
        _g._ghost_user_agents = []
        _g._ghost_user_static_agents = []
        _g._ghost_user_expert_agents = []
        _g._ghost_user_agent_slots = []
        _g._ghost_user_static_agent_slots = []
        _g._ghost_user_expert_agent_slots = []
        _g._ghost_removed_slots = set()
        _g._ghost_removed_static_slots = set()
        _g._ghost_removed_native_expert_idxs = set()
        _g._ghost_goal_overrides.clear()
        _g._ghost_agent_ids = []
        _g._ghost_agent_labels = []
        _g._ghost_native_agent_labels = []
        _g._ghost_native_static_count = 0
        _g._ghost_native_static_labels = []
        _g._ghost_native_expert_count = 0
        _g._ghost_native_expert_labels = []
        self.ghost_agent_sidebar_items = []
        self.ghost_static_sidebar_items = []
        self.ghost_expert_sidebar_items = []
        self.ghost_native_expert_sidebar_items = []
        self.ghost_user_agent_count = 0
        self.ghost_user_static_agent_count = 0
        self.ghost_user_expert_count = 0
        self.ghost_user_expert_items = []
        self.ghost_demo_slots_used = 0
        self.ghost_demo_slots_total = 0
        self.ghost_diverge_frame = 0
        self.ghost_diverge_pct = "0%"
        self.ghost_policy_load_error = ""
        self.ghost_policy_is_random = False
        self.selected_ghost_native_expert_idx = -1
        self.selected_ghost_native_expert_idx_str = "-1"
        self.selected_ghost_expert_idx = -1
        self.selected_ghost_expert_idx_str = "-1"
        yield rx.call_script(
            "window._pdEnvFocus = 'primary';"
            "window._pdGhostSelectedNativeExpertIdx = -1;"
            "window._pdGhostSelectedExpertIdx = -1;"
            "window._pdGhostGoalPositions = [];"
            + _ghost_frames_clear_js()
        )

    def toggle_ghost_env(self):

        if not self.is_loaded:
            return

        if self.ghost_env_active:
            # Deactivate: clear all ghost state
            yield from self._deactivate_ghost()
            return

        # Activate: create env from same map using ghost policy's config, then copy primary's modifications
        self.is_busy = True
        self.status = "Activating ghost environment…"
        yield
        try:
            ghost_ini = self.ghost_policy_config or None
            use_demo_map = self.has_demo_maps
            if use_demo_map:
                env = viewer.create_env_from_path(self.selected_map_path, episode_length=self.sim_steps, ini_path=ghost_ini)
            else:
                data_root = viewer.get_data_root()
                env = viewer.create_env(
                    self.selected_map, self.selected_split, data_root, episode_length=self.sim_steps, ini_path=ghost_ini
                )
            env.reset()
            env.reset_demo_slots()
            # Replay permanent C-level detaches from main env so ghost env has the same
            # orig_num_actors baseline — without this, a full env stays full in the ghost.
            if _g._original_frames_cache:
                _orig_static_labels = _g._original_frames_cache.get("native_static_labels", [])
                _curr_static_label_set = set(_g._native_static_labels)
                _removed_static_orig = sorted(
                    int(lbl) for lbl in _orig_static_labels if lbl not in _curr_static_label_set
                )
                for _j, _orig_slot in enumerate(_removed_static_orig):
                    env.detach_static_agent(_orig_slot - _j)
                _orig_expert_count = _g._original_frames_cache.get("native_expert_count", _g._native_expert_count)
                _curr_expert_orig_set = set(_g._native_expert_orig_indices)
                _removed_expert_orig = sorted(
                    i for i in range(_orig_expert_count) if i not in _curr_expert_orig_set
                )
                for _j, _orig_idx in enumerate(_removed_expert_orig):
                    env.detach_expert_agent(_orig_idx - _j)
            env.prepare_demo_slots()
            _g._ghost_env = env
            # Freeze the native static/expert baseline the ghost env was built with. The ghost
            # replayed the main env's detaches above, so these match the main counts *right now* —
            # but they must stay frozen here so later main-env removals (which pop the shared
            # _native_static_*/_native_expert_* globals) don't also vanish from the ghost.
            _g._ghost_native_static_count = _g._native_static_count
            _g._ghost_native_static_labels = list(_g._native_static_labels)
            _g._ghost_native_expert_count = _g._native_expert_count
            _g._ghost_native_expert_labels = list(_g._native_expert_labels)
            _g._ghost_policy = None
            if self.ghost_policy_path:
                try:
                    _g._ghost_policy = viewer.load_policy_from_path(self.ghost_policy_path, env, ghost_ini)
                    self.ghost_policy_load_error = ""
                    self.ghost_policy_is_random = False
                except Exception as exc:
                    self.ghost_policy_load_error = str(exc)
                    self.ghost_policy_is_random = True
            else:
                self.ghost_policy_load_error = ""
                self.ghost_policy_is_random = True

            # Mirror primary env's modifications into ghost so it starts as an exact copy.
            # Include permanently removed active agents (detached in main env, so _removed_slots
            # is already cleared — derive from label diff against the original cache snapshot).
            _perm_removed_active: set[int] = set()
            if _g._original_frames_cache:
                _orig_agent_labels = _g._original_frames_cache.get("native_agent_labels", [])
                _curr_label_set = set(_g._native_agent_labels)
                _perm_removed_active = {
                    _s for _s, _lbl in enumerate(_orig_agent_labels)
                    if _lbl not in _curr_label_set
                }
            _g._ghost_removed_slots = _perm_removed_active | set(_g._removed_slots)
            _g._ghost_removed_static_slots = set(_g._removed_static_slots)
            _g._ghost_goal_overrides.clear()
            _g._ghost_goal_overrides.update(_g._goal_overrides)
            _g._ghost_user_agents = [dict(ua) for ua in _g._user_agents]
            _g._ghost_user_static_agents = [dict(sa) for sa in _g._user_static_agents]
            _g._ghost_user_expert_agents = [dict(ea) for ea in _g._user_expert_agents]

            # Apply mirrored modifications to the ghost env
            for slot in _g._ghost_removed_slots:
                _g._ghost_env.teleport_agent(slot, _g.INVALID_POS, _g.INVALID_POS, 0.0, _g.INVALID_POS, _g.INVALID_POS)
            if _g._ghost_goal_overrides:
                _g._ghost_env.set_goals(_g._ghost_goal_overrides)
            for ua in _g._ghost_user_agents:
                _g._ghost_env.inject_demo_active_agent(ua["x"], ua["y"], ua["heading"], ua["goal_x"], ua["goal_y"],
                                                        length=ua.get("length", 0.0), width=ua.get("width", 0.0))
            _g._ghost_user_static_agent_slots = []
            for sa in _g._ghost_user_static_agents:
                slot = _g._ghost_env.inject_demo_static_agent(sa["x"], sa["y"], sa["heading"],
                                                               length=sa.get("length", 0.0), width=sa.get("width", 0.0))
                _g._ghost_user_static_agent_slots.append(slot)
            _g._ghost_user_expert_agent_slots = []
            for ea in _g._ghost_user_expert_agents:
                traj = _compute_expert_trajectory(ea, self.sim_steps)
                if traj is None:
                    _g._ghost_user_expert_agent_slots.append(-1)
                    continue
                slot_k = _g._ghost_env.inject_demo_expert_agent(ea["sx"], ea["sy"], ea["sh"],
                                                                  length=ea.get("length", 0.0), width=ea.get("width", 0.0))
                if slot_k >= 0:
                    xs, ys, hs = traj
                    _g._ghost_env.set_demo_expert_trajectory(slot_k, xs, ys, hs)
                _g._ghost_user_expert_agent_slots.append(slot_k)
            # Inherit native-active moves from the primary env so moved natives appear at
            # their repositioned spot here too (teleport keeps the slot/ID). Seed the ghost
            # move dicts so later ghost resimulates keep them.
            _g._ghost_native_active_moves = dict(_g._native_active_moves)
            for _mslot, _mv in _g._ghost_native_active_moves.items():
                try:
                    _g._ghost_env.teleport_agent(_mslot, _mv[0], _mv[1], _mv[2], _mv[3], _mv[4])
                except Exception:
                    pass
            _g._ghost_native_static_moves = dict(_g._native_static_moves)
            for _lbl, _mv in _g._ghost_native_static_moves.items():
                _idx = next((p for p, l in enumerate(_g._ghost_native_static_labels) if str(l) == str(_lbl)), -1)
                if _idx >= 0:
                    try:
                        _g._ghost_env.teleport_static_agent(_idx, _mv[0], _mv[1], _mv[2])
                    except Exception:
                        pass
            _g._ghost_native_expert_moves = dict(_g._native_expert_moves)
            for _lbl, _ea in _g._ghost_native_expert_moves.items():
                _idx = next((p for p, l in enumerate(_g._ghost_native_expert_labels) if str(l) == str(_lbl)), -1)
                if _idx < 0:
                    continue
                _traj = _compute_expert_trajectory(_ea, self.sim_steps)
                if _traj is None:
                    continue
                _xs, _ys, _hs = _traj
                try:
                    _g._ghost_env.teleport_expert_agent(_idx, _xs, _ys, _hs)
                except Exception:
                    pass
            _g._ghost_env.recompute_observations()

            (
                _g._ghost_agent_render_frames, _g._ghost_static_agents, _g._ghost_map_data,
                _g._ghost_agent_states, _g._ghost_agent_status_frames, _g._ghost_render_bounds,
                _g._ghost_expert_render_frames, _g._ghost_metrics,
            ) = viewer.collect_frames(
                _g._ghost_env, num_steps=self.sim_steps, save_every=_g.SAVE_EVERY,
                policy=_g._ghost_policy, fixed_bounds=_g._render_bounds,
                replay_actions=_g._primary_actions if _g._primary_actions else None,
                diverge_step=self.ghost_diverge_frame * _g.SAVE_EVERY,
            )
            _g._ghost_user_agent_slots = (
                _match_positions_to_slots(_g._ghost_user_agents, _g._ghost_agent_states[0])
                if _g._ghost_user_agents and _g._ghost_agent_states else []
            )
            # Stable-label identity for ghost statics (same model as the primary resimulate).
            # The ghost already replayed the primary's native detaches above, so removed natives
            # are absent from the C render output — no removed-slot filter is needed.
            _ghost_present_user_statics = [
                i for i, k in enumerate(_g._ghost_user_static_agent_slots) if k is not None and k >= 0
            ] if _g._ghost_user_static_agent_slots else list(range(len(_g._ghost_user_static_agents)))
            _ghost_demo_slot_to_useridx = {}
            for _gse in _g._ghost_static_agents:
                _graw = _gse.get("slot", -1)
                if 0 <= _graw < _g._ghost_native_static_count and _graw < len(_g._ghost_native_static_labels):
                    _glbl = _g._ghost_native_static_labels[_graw]
                elif _graw >= _g._ghost_native_static_count:
                    _gp = _graw - _g._ghost_native_static_count
                    if _gp < len(_ghost_present_user_statics):
                        _guidx = _ghost_present_user_statics[_gp]
                        _glbl = _g._ghost_user_static_agents[_guidx].get("label", str(_guidx))
                        _ghost_demo_slot_to_useridx[str(_glbl)] = _guidx
                    else:
                        _glbl = str(_graw)
                else:
                    _glbl = str(_graw)
                _gse["id"] = str(_glbl)
                try:
                    _gse["slot"] = int(_glbl)
                except (TypeError, ValueError):
                    _gse["slot"] = _graw
            # Hide ghost-removed native statics from the render output (and sidebar). The ghost
            # keeps native removals as a reversible render-only filter — mirroring native experts —
            # rather than a permanent C detach, so the slot indices stay stable across resimulates.
            ghost_static_filtered = [
                e for e in _g._ghost_static_agents
                if e.get("slot") not in _g._ghost_removed_static_slots
            ]
            ghost_user_slot_to_idx = {int(_glbl): _guidx for _glbl, _guidx in _ghost_demo_slot_to_useridx.items()}
            _guidx_to_gslot = {_guidx: _gslot for _gslot, _guidx in ghost_user_slot_to_idx.items()}
            _g._ghost_user_static_agent_slots = [
                _guidx_to_gslot.get(i, -1) for i in range(len(_g._ghost_user_static_agents))
            ]
            self.ghost_static_sidebar_items = [
                [str(e["slot"]),
                 "added" if e.get("slot") in ghost_user_slot_to_idx else "default",
                 str(ghost_user_slot_to_idx[e.get("slot")]) if e.get("slot") in ghost_user_slot_to_idx else "-1",
                 e["id"]]
                for e in ghost_static_filtered
            ]
            _g._ghost_agent_ids = [i for i, v in enumerate(_g._ghost_agent_states[0]["valid"]) if v] \
                if _g._ghost_agent_states else []
            # Build slot→label using original-slot indices from the cache snapshot.
            # Ghost never shifts active_agent_indices (uses teleport), so ghost slot == original slot.
            # This correctly handles gaps where permanently-removed agents leave holes.
            _g._ghost_native_agent_labels = list(_g._native_agent_labels)
            _ghost_user_slot_to_label = {
                slot: _g._ghost_user_agents[i].get("label", f"U{i}")
                for i, slot in enumerate(_g._ghost_user_agent_slots) if slot >= 0
            }
            if _g._original_frames_cache:
                _orig_al = _g._original_frames_cache.get("native_agent_labels", [])
                _ghost_slot_to_label = {
                    _s: _lbl for _s, _lbl in enumerate(_orig_al)
                    if _s not in _g._ghost_removed_slots
                }
            else:
                _ghost_slot_to_label = {i: _g._ghost_native_agent_labels[i] for i in range(len(_g._ghost_native_agent_labels))}
            _ghost_slot_to_label.update(_ghost_user_slot_to_label)
            if _g._ghost_agent_render_frames:
                if _ghost_slot_to_label:
                    for frame in _g._ghost_agent_render_frames:
                        for entry in frame:
                            if entry.get("slot") in _ghost_slot_to_label:
                                entry["id"] = _ghost_slot_to_label[entry["slot"]]
                f0 = _g._ghost_agent_render_frames[0]
                _g._ghost_agent_labels = [
                    _ghost_slot_to_label.get(aid, f0[k]["id"] if k < len(f0) else str(aid))
                    for k, aid in enumerate(_g._ghost_agent_ids)
                ]
            else:
                _g._ghost_agent_labels = []
            # Label ghost expert frames with stable IDs (mirrors resimulate logic for main env).
            # Only injected user experts appear in the frames, so match that subset.
            _ghost_injected_user_expert_labels = [
                a.get("label", f"Fixed Trajectory {i+1}")
                for i, a in enumerate(_g._ghost_user_expert_agents)
                if i < len(_g._ghost_user_expert_agent_slots)
                and _g._ghost_user_expert_agent_slots[i] is not None
                and _g._ghost_user_expert_agent_slots[i] >= 0
            ]
            _ghost_expert_labels = list(_g._ghost_native_expert_labels) + _ghost_injected_user_expert_labels
            if _ghost_expert_labels and _g._ghost_expert_render_frames:
                _g._ghost_expert_render_frames = [
                    [{**e, "id": lbl, "lx": round(e["cx"] + 2, 2), "ly": round(e["cy"] - 10, 2)}
                     for e, lbl in zip(frame, _ghost_expert_labels)]
                    for frame in _g._ghost_expert_render_frames
                ]
            self.ghost_user_agent_count = len(_g._ghost_user_agents)
            self.ghost_user_static_agent_count = len(_g._ghost_user_static_agents)
            _ghost_used, _ghost_total = _g._ghost_env.get_demo_slots_info()
            _ghost_n_removed_non_active = len(_g._ghost_removed_static_slots) + len(_g._ghost_removed_native_expert_idxs)
            # inject_demo_active_agent is not tracked by get_demo_slots_info (unlike static/expert),
            # so user active agents must be added manually. Removed default active agents free a slot
            # (mirroring detach_active_agent + prepare_demo_slots in the primary env).
            self.ghost_demo_slots_used = _ghost_used - _ghost_n_removed_non_active + len(_g._ghost_user_agents)
            self.ghost_demo_slots_total = _ghost_total + len(_g._ghost_removed_slots)
            self.ghost_env_active = True
            self.status = "Ghost environment active."
            self._set_frame(self.current_frame)
            _ghost_n_injected_user_experts = sum(
                1 for s in _g._ghost_user_expert_agent_slots if s is not None and s >= 0
            )
            yield rx.call_script(_ghost_frames_js(
                _g._ghost_agent_render_frames, ghost_static_filtered, _g._ghost_expert_render_frames,
                n_user_experts=_ghost_n_injected_user_experts,
            ))
            yield rx.call_script(_ghost_goal_js())
        except Exception as exc:
            self.status = f"Ghost env error: {exc}"
            _g._ghost_env = None
        self.is_busy = False

    def ghost_resimulate(self):
        """Re-run the ghost env with current ghost modifications."""

        if _g._ghost_env is None:
            return
        self.is_busy = True
        self.status = "Re-simulating ghost…"
        yield
        try:
            _g._ghost_env.reset()
            _g._ghost_env.reset_demo_slots()

            # Permanently detach ghost-removed native statics/experts from the ghost env's C
            # state, mirroring the main env's resimulate. Without this they were only hidden
            # from the display (via the *_removed_* sets below) while staying alive in the
            # simulation, so they kept causing collisions — the main/ghost asymmetry. Labels
            # and counts are popped/decremented in lockstep with the C detach (which compacts
            # the index arrays), and prepare_demo_slots() re-snapshots the baseline so the
            # detaches persist across subsequent reset_demo_slots() calls.
            _ghost_did_detach = False
            for _lbl in list(_g._ghost_removed_static_slots):
                _pos = next((p for p, l in enumerate(_g._ghost_native_static_labels)
                             if str(l) == str(_lbl)), -1)
                if _pos < 0:
                    continue
                _g._ghost_env.detach_static_agent(_pos)
                _g._ghost_native_static_labels.pop(_pos)
                _g._ghost_native_static_count -= 1
                _ghost_did_detach = True
            _g._ghost_removed_static_slots.clear()
            for _idx in sorted(_g._ghost_removed_native_expert_idxs, reverse=True):
                _g._ghost_env.detach_expert_agent(_idx)
                if 0 <= _idx < len(_g._ghost_native_expert_labels):
                    _g._ghost_native_expert_labels.pop(_idx)
                _g._ghost_native_expert_count -= 1
                _ghost_did_detach = True
            _g._ghost_removed_native_expert_idxs.clear()
            if _ghost_did_detach:
                _g._ghost_env.prepare_demo_slots()
            for slot in _g._ghost_removed_slots:
                _g._ghost_env.teleport_agent(slot, _g.INVALID_POS, _g.INVALID_POS, 0.0, _g.INVALID_POS, _g.INVALID_POS)
            # Native static/expert removals stay a reversible render-only filter (applied when
            # building the render output below) — the entities remain in the C env so the
            # non-expert index space stays stable for in-place teleport moves.
            _g._ghost_env.prepare_demo_slots()
            if _g._ghost_goal_overrides:
                _g._ghost_env.set_goals(_g._ghost_goal_overrides)
            for ua in _g._ghost_user_agents:
                _g._ghost_env.inject_demo_active_agent(ua["x"], ua["y"], ua["heading"], ua["goal_x"], ua["goal_y"],
                                                        length=ua.get("length", 0.0), width=ua.get("width", 0.0))
            _g._ghost_user_static_agent_slots = []
            for sa in _g._ghost_user_static_agents:
                slot = _g._ghost_env.inject_demo_static_agent(sa["x"], sa["y"], sa["heading"],
                                                               length=sa.get("length", 0.0), width=sa.get("width", 0.0))
                _g._ghost_user_static_agent_slots.append(slot)
            _g._ghost_user_expert_agent_slots = []
            for ea in _g._ghost_user_expert_agents:
                traj = _compute_expert_trajectory(ea, self.sim_steps)
                if traj is None:
                    _g._ghost_user_expert_agent_slots.append(-1)
                    continue
                slot_k = _g._ghost_env.inject_demo_expert_agent(ea["sx"], ea["sy"], ea["sh"],
                                                                  length=ea.get("length", 0.0), width=ea.get("width", 0.0))
                if slot_k >= 0:
                    xs, ys, hs = traj
                    _g._ghost_env.set_demo_expert_trajectory(slot_k, xs, ys, hs)
                _g._ghost_user_expert_agent_slots.append(slot_k)
            # Re-apply the ghost's OWN native moves only. The ghost is seeded with the primary's
            # moves once at activation (a snapshot); after that each env is independent — mirror
            # mode keeps them in sync by writing to both move dicts, not by merging here.
            for _mslot, _mv in _g._ghost_native_active_moves.items():
                try:
                    _g._ghost_env.teleport_agent(_mslot, _mv[0], _mv[1], _mv[2], _mv[3], _mv[4])
                except Exception:
                    pass
            # Re-apply native static/expert moves in place (teleport keeps slot/ID).
            # Map stable label → current C index.
            for _lbl, _mv in _g._ghost_native_static_moves.items():
                _idx = next((p for p, l in enumerate(_g._ghost_native_static_labels) if str(l) == str(_lbl)), -1)
                if _idx < 0:
                    continue
                try:
                    _g._ghost_env.teleport_static_agent(_idx, _mv[0], _mv[1], _mv[2])
                except Exception:
                    pass
            for _lbl, _ea in _g._ghost_native_expert_moves.items():
                _idx = next((p for p, l in enumerate(_g._ghost_native_expert_labels) if str(l) == str(_lbl)), -1)
                if _idx < 0:
                    continue
                _traj = _compute_expert_trajectory(_ea, self.sim_steps)
                if _traj is None:
                    continue
                _xs, _ys, _hs = _traj
                try:
                    _g._ghost_env.teleport_expert_agent(_idx, _xs, _ys, _hs)
                except Exception:
                    pass
            _g._ghost_env.recompute_observations()
            (
                _g._ghost_agent_render_frames, _g._ghost_static_agents, _g._ghost_map_data,
                _g._ghost_agent_states, _g._ghost_agent_status_frames, _g._ghost_render_bounds,
                _g._ghost_expert_render_frames, _g._ghost_metrics,
            ) = viewer.collect_frames(
                _g._ghost_env, num_steps=self.sim_steps, save_every=_g.SAVE_EVERY,
                policy=_g._ghost_policy, fixed_bounds=_g._render_bounds,
                replay_actions=_g._primary_actions if _g._primary_actions else None,
                diverge_step=self.ghost_diverge_frame * _g.SAVE_EVERY,
            )
            _g._ghost_user_agent_slots = (
                _match_positions_to_slots(_g._ghost_user_agents, _g._ghost_agent_states[0])
                if _g._ghost_user_agents and _g._ghost_agent_states else []
            )
            # Apply stable labels: ghost slot == original slot (teleport, no shift), so map
            # original-slot indices from the cache to their labels to handle removal gaps.
            _ghost_user_slot_to_label = {
                slot: _g._ghost_user_agents[i].get("label", f"U{i}")
                for i, slot in enumerate(_g._ghost_user_agent_slots) if slot >= 0
            }
            if _g._original_frames_cache:
                _orig_al2 = _g._original_frames_cache.get("native_agent_labels", [])
                _ghost_slot_to_label = {
                    _s: _lbl for _s, _lbl in enumerate(_orig_al2)
                    if _s not in _g._ghost_removed_slots
                }
            else:
                _ghost_slot_to_label = {i: _g._ghost_native_agent_labels[i] for i in range(len(_g._ghost_native_agent_labels))}
            _ghost_slot_to_label.update(_ghost_user_slot_to_label)
            if _ghost_slot_to_label:
                for frame in _g._ghost_agent_render_frames:
                    for entry in frame:
                        if entry.get("slot") in _ghost_slot_to_label:
                            entry["id"] = _ghost_slot_to_label[entry["slot"]]
            # Stable-label identity for ghost statics (same model as the primary resimulate).
            _ghost_present_user_statics2 = [
                i for i, k in enumerate(_g._ghost_user_static_agent_slots) if k is not None and k >= 0
            ] if _g._ghost_user_static_agent_slots else list(range(len(_g._ghost_user_static_agents)))
            _ghost_demo_slot_to_useridx2 = {}
            for _gse2 in _g._ghost_static_agents:
                _graw2 = _gse2.get("slot", -1)
                if 0 <= _graw2 < _g._ghost_native_static_count and _graw2 < len(_g._ghost_native_static_labels):
                    _glbl2 = _g._ghost_native_static_labels[_graw2]
                elif _graw2 >= _g._ghost_native_static_count:
                    _gp2 = _graw2 - _g._ghost_native_static_count
                    if _gp2 < len(_ghost_present_user_statics2):
                        _guidx2 = _ghost_present_user_statics2[_gp2]
                        _glbl2 = _g._ghost_user_static_agents[_guidx2].get("label", str(_guidx2))
                        _ghost_demo_slot_to_useridx2[str(_glbl2)] = _guidx2
                    else:
                        _glbl2 = str(_graw2)
                else:
                    _glbl2 = str(_graw2)
                _gse2["id"] = str(_glbl2)
                try:
                    _gse2["slot"] = int(_glbl2)
                except (TypeError, ValueError):
                    _gse2["slot"] = _graw2
            # Hide ghost-removed native statics from the render output (and sidebar) — reversible
            # render-only filter, mirroring native experts (see toggle_ghost_env for rationale).
            ghost_static_filtered = [
                e for e in _g._ghost_static_agents
                if e.get("slot") not in _g._ghost_removed_static_slots
            ]
            ghost_user_slot_to_idx = {int(_glbl2): _guidx2 for _glbl2, _guidx2 in _ghost_demo_slot_to_useridx2.items()}
            _guidx_to_gslot2 = {_guidx2: _gslot2 for _gslot2, _guidx2 in ghost_user_slot_to_idx.items()}
            _g._ghost_user_static_agent_slots = [
                _guidx_to_gslot2.get(i, -1) for i in range(len(_g._ghost_user_static_agents))
            ]
            self.ghost_static_sidebar_items = [
                [str(e["slot"]),
                 "added" if e.get("slot") in ghost_user_slot_to_idx else "default",
                 str(ghost_user_slot_to_idx[e.get("slot")]) if e.get("slot") in ghost_user_slot_to_idx else "-1",
                 e["id"]]
                for e in ghost_static_filtered
            ]
            _g._ghost_agent_ids = [i for i, v in enumerate(_g._ghost_agent_states[0]["valid"]) if v] \
                if _g._ghost_agent_states else []
            if _g._ghost_agent_render_frames:
                f0 = _g._ghost_agent_render_frames[0]
                _g._ghost_agent_labels = [f0[k]["id"] if k < len(f0) else str(aid)
                                       for k, aid in enumerate(_g._ghost_agent_ids)]
            if _g._ghost_removed_native_expert_idxs:
                _g._ghost_expert_render_frames = [
                    [e for i, e in enumerate(frame)
                     if i >= _g._ghost_native_expert_count or i not in _g._ghost_removed_native_expert_idxs]
                    for frame in _g._ghost_expert_render_frames
                ]
            self.ghost_native_expert_sidebar_items = [
                [_g._ghost_native_expert_labels[i], "default", str(i)]
                for i in range(_g._ghost_native_expert_count)
                if i < len(_g._ghost_native_expert_labels) and i not in _g._ghost_removed_native_expert_idxs
            ]
            # Label ghost expert frames with stable IDs (mirrors main env resimulate).
            # Only injected user experts appear in the frames, so match that subset.
            _ghost_injected_user_expert_labels = [
                a.get("label", f"Fixed Trajectory {i+1}")
                for i, a in enumerate(_g._ghost_user_expert_agents)
                if i < len(_g._ghost_user_expert_agent_slots)
                and _g._ghost_user_expert_agent_slots[i] is not None
                and _g._ghost_user_expert_agent_slots[i] >= 0
            ]
            _ghost_expert_labels = (
                [_g._ghost_native_expert_labels[i]
                 for i in range(_g._ghost_native_expert_count)
                 if i < len(_g._ghost_native_expert_labels) and i not in _g._ghost_removed_native_expert_idxs]
                + _ghost_injected_user_expert_labels
            )
            if _ghost_expert_labels and _g._ghost_expert_render_frames:
                _g._ghost_expert_render_frames = [
                    [{**e, "id": lbl, "lx": round(e["cx"] + 2, 2), "ly": round(e["cy"] - 10, 2)}
                     for e, lbl in zip(frame, _ghost_expert_labels)]
                    for frame in _g._ghost_expert_render_frames
                ]
            _ghost_used, _ghost_total = _g._ghost_env.get_demo_slots_info()
            _ghost_n_removed_non_active = len(_g._ghost_removed_static_slots) + len(_g._ghost_removed_native_expert_idxs)
            self.ghost_demo_slots_used = _ghost_used - _ghost_n_removed_non_active + len(_g._ghost_user_agents)
            self.ghost_demo_slots_total = _ghost_total + len(_g._ghost_removed_slots)
            self._set_frame(self.current_frame)
            self.status = "Ghost re-simulation complete."
            _ghost_n_injected_user_experts = sum(
                1 for s in _g._ghost_user_expert_agent_slots if s is not None and s >= 0
            )
            yield rx.call_script(_ghost_frames_js(
                _g._ghost_agent_render_frames, ghost_static_filtered, _g._ghost_expert_render_frames,
                n_user_experts=_ghost_n_injected_user_experts,
            ))
            yield rx.call_script(_ghost_goal_js())
        except Exception as exc:
            self.status = f"Ghost sim error: {exc}"
        self.is_busy = False

    def toggle_static_agent_place(self):
        self._reset_to_first_frame()
        self.static_agent_place_mode = not self.static_agent_place_mode
        self.goal_edit_mode = False
        self.agent_place_mode = False
        self.expert_place_mode = False
        self.move_mode = False
        self.select_mode = False
        self.selected_goal_slot = -1
        if self.static_agent_place_mode:
            self._reset_to_first_frame()
            yield rx.call_script(
                "if(window._pdStopRaf)window._pdStopRaf();"
                "if(window._pdSetTool)window._pdSetTool('add_static');"
            )
        else:
            yield rx.call_script("if (window._pdSetTool) window._pdSetTool('pan');")

    async def handle_static_agent_place(self, data):
        """Receive 2-click placement data and resimulate with a new static agent."""
        if not isinstance(data, dict):
            return
        mirror = self.mirror_placement and self.ghost_env_active
        is_ghost = not mirror and self.env_focus == "ghost" and self.ghost_env_active
        target_env = _g._ghost_env if is_ghost else _g._env
        if target_env is None:
            return
        if self.demo_slots_full:
            self.status = f"No demo slots left ({self.demo_slots_used}/{self.demo_slots_total} used)"
            return
        pos = viewer.frac_to_world(float(data["pfx"]), float(data["pfy"]))
        hdg = viewer.frac_to_world(float(data["hfx"]), float(data["hfy"]))
        if pos is None or hdg is None:
            return
        heading = math.atan2(hdg[1] - pos[1], hdg[0] - pos[0])
        label = str(_g._user_static_expert_name_counter)
        _g._user_static_expert_name_counter += 1
        _ssz = VEHICLE_SIZES.get(self.static_size, VEHICLE_SIZES["M"])
        agent_data = {"x": pos[0], "y": pos[1], "heading": heading, "label": label,
                      "length": _ssz["length"], "width": _ssz["width"]}
        if mirror:
            _g._user_static_agents.append(agent_data)
            _g._ghost_user_static_agents.append(dict(agent_data))
            self.user_static_agent_count = len(_g._user_static_agents)
            self.ghost_user_static_agent_count = len(_g._ghost_user_static_agents)
            self.status = "Static agent placed in both envs — resimulating…"
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            for _ev in self.ghost_resimulate(): yield _ev
        elif is_ghost:
            _g._ghost_user_static_agents.append(agent_data)
            self.ghost_user_static_agent_count = len(_g._ghost_user_static_agents)
            self.status = "Ghost static agent placed — resimulating ghost…"
            for _ev in self.ghost_resimulate(): yield _ev
        else:
            _g._user_static_agents.append(agent_data)
            self.user_static_agent_count = len(_g._user_static_agents)
            self.status = "Static agent placed — resimulating…"
            # user_static_items rebuilt by resimulate once slot numbers are known
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev

    async def remove_user_static_agent(self, idx: str):
        i = int(idx)
        if 0 <= i < len(_g._user_static_agents):
            _g._user_static_agents.pop(i)
            self.user_static_agent_count = len(_g._user_static_agents)
            if not _g._user_static_agents:
                self.user_static_items = []
            # Both/mirror mode: remove the same-index ghost counterpart too.
            mirror = self._mirror_active() and 0 <= i < len(_g._ghost_user_static_agents)
            if mirror:
                _g._ghost_user_static_agents.pop(i)
                self.ghost_user_static_agent_count = len(_g._ghost_user_static_agents)
                if not _g._ghost_user_static_agents:
                    self.ghost_user_static_items = []
            self.status = "Static agent removed — resimulating…"
            for _ev in self.clear_selection(): yield _ev
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            if mirror:
                for _ev in self.ghost_resimulate(): yield _ev
            self._just_removed = True

    def clear_user_static_agents(self):
        _g._user_static_agents = []
        self.user_static_agent_count = 0
        self.user_static_items = []
        self.status = "Cleared all placed static agents — press Resimulate"

    # ── Expert trajectory placement ───────────────────────────────────────────

    def toggle_expert_place(self):
        self._reset_to_first_frame()
        self.expert_place_mode = not self.expert_place_mode
        self.goal_edit_mode = False
        self.agent_place_mode = False
        self.static_agent_place_mode = False
        self.move_mode = False
        self.select_mode = False
        self.selected_goal_slot = -1
        if self.expert_place_mode:
            yield rx.call_script("if (window._pdSetTool) window._pdSetTool('add_expert');")
        else:
            yield rx.call_script("if (window._pdSetTool) window._pdSetTool('pan');")

    async def handle_expert_place(self, data):
        """Receive 2-click placement (start + heading) and add an expert trajectory agent."""
        if not isinstance(data, dict):
            return
        mirror = self.mirror_placement and self.ghost_env_active
        is_ghost = not mirror and self.env_focus == "ghost" and self.ghost_env_active
        target_env = _g._ghost_env if is_ghost else _g._env
        if target_env is None:
            return
        if self.demo_slots_full:
            self.status = f"No demo slots left ({self.demo_slots_used}/{self.demo_slots_total} used)"
            return
        pos = viewer.frac_to_world(float(data["pfx"]), float(data["pfy"]))
        end_pos = viewer.frac_to_world(float(data.get("efx", data["pfx"])), float(data.get("efy", data["pfy"])))
        if pos is None:
            return
        if end_pos is None:
            end_pos = pos
        # Snap both click positions to the nearest road lane.
        if _g._lane_graph_cache is None:
            _g._lane_graph_cache = viewer.build_lane_graph(target_env)
        if _g._lane_graph_cache is not None:
            lanes, _ = _g._lane_graph_cache
            pos = _snap_world_to_lane(pos[0], pos[1], lanes)
            end_pos = _snap_world_to_lane(end_pos[0], end_pos[1], lanes)
        # Heading = direction from snapped start to snapped end; fall back to east (0).
        heading = math.atan2(end_pos[1] - pos[1], end_pos[0] - pos[0]) if end_pos != pos else 0.0
        label = str(_g._user_static_expert_name_counter)
        _g._user_static_expert_name_counter += 1
        _esz = VEHICLE_SIZES.get(self.expert_size, VEHICLE_SIZES["M"])
        agent_data = {
            "sx": pos[0], "sy": pos[1], "sh": heading,
            "ex": end_pos[0], "ey": end_pos[1], "eh": heading,
            "waypoints": [],
            "length": _esz["length"], "width": _esz["width"],
            "label": label,
        }
        if mirror:
            _g._user_expert_agents.append(agent_data)
            _g._ghost_user_expert_agents.append(dict(agent_data))
            self.user_expert_count = len(_g._user_expert_agents)
            self.ghost_user_expert_count = len(_g._ghost_user_expert_agents)
            self.status = "Fixed Trajectory agent placed in both envs — resimulating…"
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            for _ev in self.ghost_resimulate(): yield _ev
        elif is_ghost:
            _g._ghost_user_expert_agents.append(agent_data)
            self.ghost_user_expert_count = len(_g._ghost_user_expert_agents)
            self.status = "Ghost fixed trajectory agent placed — resimulating ghost…"
            for _ev in self.ghost_resimulate(): yield _ev
        else:
            _g._user_expert_agents.append(agent_data)
            self.user_expert_count = len(_g._user_expert_agents)
            self.status = "Fixed Trajectory agent placed — resimulating…"
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev

    async def remove_user_expert_agent(self, idx_str: str):
        i = int(idx_str)
        if 0 <= i < len(_g._user_expert_agents):
            _g._user_expert_agents.pop(i)
            self.user_expert_count = len(_g._user_expert_agents)
            if not _g._user_expert_agents:
                self.user_expert_items = []
            # Both/mirror mode: remove the same-index ghost counterpart too.
            mirror = self._mirror_active() and 0 <= i < len(_g._ghost_user_expert_agents)
            if mirror:
                _g._ghost_user_expert_agents.pop(i)
                self.ghost_user_expert_count = len(_g._ghost_user_expert_agents)
                if not _g._ghost_user_expert_agents:
                    self.ghost_user_expert_items = []
            self.status = "Fixed Trajectory agent removed — resimulating…"
            for _ev in self.clear_selection(): yield _ev
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            if mirror:
                for _ev in self.ghost_resimulate(): yield _ev
            self._just_removed = True

    async def remove_native_expert(self, frame_idx_str: str):
        i = int(frame_idx_str)
        _g._removed_native_expert_idxs.add(i)
        _g._pending_expert_detach_idxs.add(i)
        _g._env_has_detaches = True
        mirror = self._mirror_active()
        if mirror:
            _g._ghost_removed_native_expert_idxs.add(i)
        self.status = "Native fixed trajectory removed — resimulating…"
        for _ev in self.clear_selection(): yield _ev
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        if mirror:
            for _ev in self.ghost_resimulate(): yield _ev
        self._just_removed = True

    async def handle_expert_wp_drop(self, data):
        """Receive a waypoint drag-drop event to update an expert agent trajectory."""
        if not isinstance(data, dict):
            return
        agent_idx = int(data.get("agent_idx", -1))
        wp_idx = int(data.get("wp_idx", -1))
        if agent_idx < 0 or agent_idx >= len(_g._user_expert_agents):
            return
        pos = viewer.frac_to_world(float(data["pfx"]), float(data["pfy"]))
        if pos is None:
            return
        _apply_wp_edit(_g._user_expert_agents[agent_idx], wp_idx, pos)
        # Both/mirror mode: apply the identical edit to the ghost expert at the same index.
        mirror = self._mirror_active() and 0 <= agent_idx < len(_g._ghost_user_expert_agents)
        if mirror:
            _apply_wp_edit(_g._ghost_user_expert_agents[agent_idx], wp_idx, pos)
            self.status = "Waypoint moved in both envs — resimulating…"
        else:
            self.status = "Waypoint moved — resimulating…"
        saved_expert_idx = self.selected_expert_idx
        self.selected_expert_idx = -1
        if mirror:
            self.selected_ghost_expert_idx = -1
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        if mirror:
            for _ev in self.ghost_resimulate(): yield _ev
        if saved_expert_idx >= 0:
            for _ev in self.select_expert(str(saved_expert_idx)): yield _ev

    async def handle_expert_traj_point_drop(self, data):
        """Move a dragged trajectory timestep to a new world position, updating heading."""
        if not isinstance(data, dict):
            return
        agent_idx = int(data.get("agent_idx", -1))
        traj_step = int(data.get("traj_step", -1))
        if agent_idx < 0 or agent_idx >= len(_g._user_expert_agents):
            return
        pos = viewer.frac_to_world(float(data["pfx"]), float(data["pfy"]))
        if pos is None:
            return
        if not _apply_traj_edit(_g._user_expert_agents[agent_idx], traj_step, pos):
            return  # no trajectory computed yet, or step out of range
        # Both/mirror mode: apply the identical edit to the ghost expert at the same index.
        mirror = self._mirror_active() and 0 <= agent_idx < len(_g._ghost_user_expert_agents)
        if mirror:
            _apply_traj_edit(_g._ghost_user_expert_agents[agent_idx], traj_step, pos)
            self.status = "Trajectory point moved in both envs — resimulating…"
        else:
            self.status = "Trajectory point moved — resimulating…"
        saved_expert_idx = self.selected_expert_idx
        self.selected_expert_idx = -1
        if mirror:
            self.selected_ghost_expert_idx = -1
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        if mirror:
            for _ev in self.ghost_resimulate(): yield _ev
        if saved_expert_idx >= 0:
            for _ev in self.select_expert(str(saved_expert_idx)): yield _ev

    async def handle_ghost_expert_wp_drop(self, data):
        """Ghost-env counterpart of handle_expert_wp_drop (focus-ghost overlay editing)."""
        # Driven by a selected ghost expert (see JS mousedown), independent of env_focus.
        if not self.ghost_env_active:
            return
        if not isinstance(data, dict):
            return
        agent_idx = int(data.get("agent_idx", -1))
        wp_idx = int(data.get("wp_idx", -1))
        if agent_idx < 0 or agent_idx >= len(_g._ghost_user_expert_agents):
            return
        pos = viewer.frac_to_world(float(data["pfx"]), float(data["pfy"]))
        if pos is None:
            return
        _apply_wp_edit(_g._ghost_user_expert_agents[agent_idx], wp_idx, pos)
        # Both/mirror mode: apply the identical edit to the primary expert at the same index.
        mirror = self._mirror_active() and 0 <= agent_idx < len(_g._user_expert_agents)
        if mirror:
            _apply_wp_edit(_g._user_expert_agents[agent_idx], wp_idx, pos)
            self.status = "Waypoint moved in both envs — resimulating…"
        else:
            self.status = "Ghost waypoint moved — resimulating ghost…"
        saved_expert_idx = self.selected_ghost_expert_idx
        self.selected_ghost_expert_idx = -1
        if mirror:
            self.selected_expert_idx = -1
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        for _ev in self.ghost_resimulate(): yield _ev
        if saved_expert_idx >= 0:
            yield self.select_ghost_expert(str(saved_expert_idx))

    async def handle_ghost_expert_traj_point_drop(self, data):
        """Ghost-env counterpart of handle_expert_traj_point_drop (focus-ghost overlay editing)."""
        # Driven by a selected ghost expert (see JS mousedown), independent of env_focus.
        if not self.ghost_env_active:
            return
        if not isinstance(data, dict):
            return
        agent_idx = int(data.get("agent_idx", -1))
        traj_step = int(data.get("traj_step", -1))
        if agent_idx < 0 or agent_idx >= len(_g._ghost_user_expert_agents):
            return
        pos = viewer.frac_to_world(float(data["pfx"]), float(data["pfy"]))
        if pos is None:
            return
        if not _apply_traj_edit(_g._ghost_user_expert_agents[agent_idx], traj_step, pos):
            return  # no trajectory computed yet, or step out of range
        # Both/mirror mode: apply the identical edit to the primary expert at the same index.
        mirror = self._mirror_active() and 0 <= agent_idx < len(_g._user_expert_agents)
        if mirror:
            _apply_traj_edit(_g._user_expert_agents[agent_idx], traj_step, pos)
            self.status = "Trajectory point moved in both envs — resimulating…"
        else:
            self.status = "Ghost trajectory point moved — resimulating ghost…"
        saved_expert_idx = self.selected_ghost_expert_idx
        self.selected_ghost_expert_idx = -1
        if mirror:
            self.selected_expert_idx = -1
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
        for _ev in self.ghost_resimulate(): yield _ev
        if saved_expert_idx >= 0:
            yield self.select_ghost_expert(str(saved_expert_idx))

    def toggle_show_goals(self):
        self.show_goals = not self.show_goals
        new_val = str(self.show_goals).lower()
        return rx.call_script(f"window._pdShowGoals = {new_val}; if (window._pdRedraw) window._pdRedraw();")

    def toggle_show_goal_radius(self):
        self.show_goal_radius = not self.show_goal_radius
        new_val = str(self.show_goal_radius).lower()
        return rx.call_script(f"window._pdShowGoalRadius = {new_val}; if (window._pdRedraw) window._pdRedraw();")

    def toggle_show_labels(self):
        self.show_labels = not self.show_labels
        new_val = str(self.show_labels).lower()
        return rx.call_script(f"window._pdShowLabels = {new_val}; if (window._pdRedraw) window._pdRedraw();")

    def toggle_show_trajectories(self):
        self.show_trajectories = not self.show_trajectories
        new_val = str(self.show_trajectories).lower()
        return rx.call_script(f"window._pdShowTrajectories = {new_val}; if (window._pdRedraw) window._pdRedraw();")

    def toggle_sim_steps_edit(self):
        self.sim_steps_editing = not self.sim_steps_editing
        if self.sim_steps_editing:
            self.sim_steps_input = str(self.sim_steps)

    def set_sim_steps_input(self, value: str):
        self.sim_steps_input = value

    def apply_sim_steps(self):
        try:
            v = int(self.sim_steps_input)
            if v > 0:
                self.sim_steps = v
        except ValueError:
            pass
        self.sim_steps_editing = False

    def _recreate_primary_env(self):
        """(Re)create _g._env from the currently-selected map and re-bind the policy.

        Detaching a native agent permanently zeroes its C-level trajectory
        (c_detach_active/static/expert_agent), so env.reset() alone can never bring
        it back. Rebuilding the env from the map file is the only way to restore
        removed agents on Reset.
        """
        policy_ini = self.selected_policy_config or None
        if self.has_demo_maps:
            _g._env = viewer.create_env_from_path(
                self.selected_map_path, episode_length=self.sim_steps, ini_path=policy_ini)
        else:
            _g._env = viewer.create_env(
                self.selected_map, self.selected_split, viewer.get_data_root(),
                episode_length=self.sim_steps, ini_path=policy_ini)
        _g._env.reset()
        _g._env.prepare_demo_slots()
        _g._lane_graph_cache = None  # env rebuilt — rebuild on first expert trajectory
        _used, _total = _g._env.get_demo_slots_info()
        self.demo_slots_used, self.demo_slots_total = _used, _total
        # Re-bind the policy to the new env, mirroring load_map's guarded load: a reload
        # failure degrades to random actions (with a surfaced reason) instead of throwing
        # out of the rebuild, and we re-attempt unconditionally so a session that was
        # previously stuck random can recover once the checkpoint/config is fixed.
        if self.selected_policy_path:
            try:
                _g._policy = viewer.load_policy_from_path(
                    self.selected_policy_path, _g._env, policy_ini)
                self.policy_load_error = ""
                self.policy_is_random = False
            except Exception as exc:
                self.policy_load_error = str(exc)
                self.policy_is_random = True
                _g._policy = None
        else:
            self.policy_load_error = ""
            self.policy_is_random = True
            _g._policy = None
        _g._env_has_detaches = False

    # ── Scenario export / import ────────────────────────────────────────────────
    scenario_files: list[str] = []       # existing *.json in the scenarios/ folder
    scenario_name: str = ""              # optional custom export name (blank → timestamp)
    selected_scenario_file: str = ""     # import dropdown selection

    def set_scenario_name(self, v: str):
        self.scenario_name = v

    @staticmethod
    def _scenarios_dir() -> str:
        """scenarios/ next to config/ (cwd is the app dir). Created if missing."""
        d = os.environ.get("DRIVE_SCENARIOS_DIR", "scenarios")
        os.makedirs(d, exist_ok=True)
        return d

    def refresh_scenario_files(self):
        try:
            d = self._scenarios_dir()
            self.scenario_files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
        except OSError:
            self.scenario_files = []

    def _scenario_dict(self) -> dict:
        """The full scenario as a JSON-serializable dict (map, policy, sim, every primary +
        ghost edit, and all view/config widget flags). Slot lists are omitted — resimulate
        regenerates them on import."""
        def _sl(s):  # set -> sorted list (JSON has no set type)
            return sorted(s)

        # resimulate() clears _removed_slots / _removed_native_expert_idxs after applying them
        # (the detach persists in the live env), so by export time those sets are usually empty
        # even though native agents/experts were removed. Recover the full removal set the same
        # way the ghost-mirror does: diff the current labels against the original load-time
        # snapshot in _original_frames_cache. Positions in the original array are exactly the
        # indices a fresh env needs on import (resimulate detaches them in descending order).
        def _removed_native(curr_labels, cache_key):
            recovered = set()
            cache = _g._original_frames_cache
            if cache:
                orig = cache.get(cache_key, [])
                live = set(curr_labels)
                recovered = {i for i, lbl in enumerate(orig) if lbl not in live}
            return recovered

        removed_slots = set(_g._removed_slots) | _removed_native(
            _g._native_agent_labels, "native_agent_labels")
        removed_expert_idxs = set(_g._removed_native_expert_idxs) | _removed_native(
            _g._native_expert_labels, "native_expert_labels")
        data = {
            "version": 1,
            "meta": {
                "selected_split": self.selected_split,
                "selected_map": self.selected_map,
                "selected_map_path": self.selected_map_path,
                "map_id_input": self.map_id_input,
                "sim_steps": self.sim_steps,
                # Stored relative to the repo root when they live inside it, so an exported
                # scenario can be replayed on any checkout (see viewer.resolve_policy_path).
                "selected_policy_path": viewer.portable_policy_path(self.selected_policy_path),
                "selected_policy_config": viewer.portable_policy_path(self.selected_policy_config),
                "ghost_policy_path": viewer.portable_policy_path(self.ghost_policy_path),
                "ghost_policy_config": viewer.portable_policy_path(self.ghost_policy_config),
            },
            "flags": {
                "ghost_env_active": self.ghost_env_active,
                "ghost_side_by_side": self.ghost_side_by_side,
                "mirror_placement": self.mirror_placement,
                "env_focus": self.env_focus,
                "ghost_diverge_frame": self.ghost_diverge_frame,
                "agent_size": self.agent_size,
                "static_size": self.static_size,
                "expert_size": self.expert_size,
                "show_goals": self.show_goals,
                "show_goal_radius": self.show_goal_radius,
                "show_labels": self.show_labels,
                "show_trajectories": self.show_trajectories,
            },
            "primary": {
                "user_agents": _g._user_agents,
                "user_static_agents": _g._user_static_agents,
                "user_expert_agents": _g._user_expert_agents,
                "goal_overrides": _g._goal_overrides,
                "removed_slots": _sl(removed_slots),
                "removed_static_slots": _sl(_g._removed_static_slots),
                "removed_native_expert_idxs": _sl(removed_expert_idxs),
                "pending_static_detach_slots": _sl(_g._pending_static_detach_slots),
                "pending_expert_detach_idxs": _sl(_g._pending_expert_detach_idxs),
                "env_has_detaches": _g._env_has_detaches,
                "native_active_moves": _g._native_active_moves,
                "native_static_moves": _g._native_static_moves,
                "native_expert_moves": _g._native_expert_moves,
            },
            "ghost": {
                "user_agents": _g._ghost_user_agents,
                "user_static_agents": _g._ghost_user_static_agents,
                "user_expert_agents": _g._ghost_user_expert_agents,
                "goal_overrides": _g._ghost_goal_overrides,
                "removed_slots": _sl(_g._ghost_removed_slots),
                "removed_static_slots": _sl(_g._ghost_removed_static_slots),
                "removed_native_expert_idxs": _sl(_g._ghost_removed_native_expert_idxs),
                "native_active_moves": _g._ghost_native_active_moves,
                "native_static_moves": _g._ghost_native_static_moves,
                "native_expert_moves": _g._ghost_native_expert_moves,
            },
        }
        return data

    def export_scenario(self):
        """Write the current scenario to scenarios/<name>.json — the name field, or a
        timestamp when blank; an existing file of the same name is overwritten."""
        if not self.is_loaded:
            self.status = "Load a map before exporting."
            return
        name = (self.scenario_name or "").strip()
        if not name:
            name = "scenario_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        if not name.endswith(".json"):
            name += ".json"
        path = os.path.join(self._scenarios_dir(), name)
        try:
            with open(path, "w") as f:
                json.dump(self._scenario_dict(), f, indent=2, default=lambda o: o.tolist())
        except OSError as e:
            self.status = f"Export failed: {e}"
            return
        self.refresh_scenario_files()
        self.selected_scenario_file = name
        # Surface the export in the header's Map dropdown (session-only). Selecting
        # one there + Load re-applies the whole scene losslessly via the scenario-import path.
        sentinel = "scenario://" + name
        label = name[:-5] if name.endswith(".json") else name
        if not any(m[1] == sentinel for m in self.session_maps):
            self.session_maps = self.session_maps + [[label, sentinel]]
        # Show the fresh export as the selected Map entry (selected_map_path stays the real map).
        self.selected_map_choice = sentinel
        self.status = f"Exported → scenarios/{name}"

    async def on_import_signal(self, signal: str):
        """Upload path: JSON text of a file the user picked (hidden input) → apply it."""
        self._import_signal = ""
        if not signal:
            return
        try:
            data = json.loads(signal)
        except (json.JSONDecodeError, TypeError, ValueError):
            self.status = "Import failed: not a valid scenario file."
            return
        async for _ev in self._apply_scenario(data): yield _ev

    async def import_scenario_file(self, filename: str):
        """Folder path: load and apply an existing scenarios/<filename>."""
        self.selected_scenario_file = filename
        if not filename:
            return
        try:
            with open(os.path.join(self._scenarios_dir(), filename)) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            self.status = f"Import failed: {e}"
            return
        async for _ev in self._apply_scenario(data): yield _ev

    async def _apply_scenario(self, data):
        """Restore a scenario dict: reload the map fresh, replay every primary edit, rebuild
        the ghost env + its edits (so a side-by-side policy compare mirrors the imported
        scene), then restore all view/config flags."""
        try:
            meta = data.get("meta", {}); flags = data.get("flags", {})
            prim = data.get("primary", {}); ghost = data.get("ghost", {})
        except AttributeError:
            self.status = "Import failed: unrecognized scenario format."
            return

        def _ikeys(d):  # JSON stringifies int dict keys — restore them
            return {int(k): v for k, v in (d or {}).items()}
        def _tup(v):
            return tuple(v) if isinstance(v, list) else v
        def _wp(agents):  # waypoints list-of-list -> list-of-tuple
            for a in (agents or []):
                if isinstance(a.get("waypoints"), list):
                    a["waypoints"] = [tuple(w) for w in a["waypoints"]]
            return agents or []

        # Phase 1 — map/policy/sim selection, then load a fresh env (clears all globals).
        self.selected_split = meta.get("selected_split", self.selected_split)
        self.selected_map = meta.get("selected_map", self.selected_map)
        self.selected_map_path = meta.get("selected_map_path", self.selected_map_path)
        # A scenario always resolves to its real underlying map — never a sentinel.
        if self.selected_map_path.startswith("scenario://"):
            self.selected_map_path = ""
        self.map_id_input = str(meta.get("map_id_input", self.map_id_input))
        self.sim_steps = int(meta.get("sim_steps", self.sim_steps))
        # Scenarios may carry repo-relative paths (current exports) or an absolute path from
        # whichever machine wrote them (older exports) — resolve both against this checkout.
        self.selected_policy_path = viewer.resolve_policy_path(
            meta.get("selected_policy_path", self.selected_policy_path))
        self.selected_policy_config = viewer.resolve_policy_path(
            meta.get("selected_policy_config", self.selected_policy_config))
        self.ghost_policy_path = viewer.resolve_policy_path(
            meta.get("ghost_policy_path", self.ghost_policy_path))
        self.ghost_policy_config = viewer.resolve_policy_path(
            meta.get("ghost_policy_config", self.ghost_policy_config))
        self.agent_size = flags.get("agent_size", self.agent_size)
        self.static_size = flags.get("static_size", self.static_size)
        self.expert_size = flags.get("expert_size", self.expert_size)
        self.ghost_diverge_frame = int(flags.get("ghost_diverge_frame", self.ghost_diverge_frame))
        self.status = "Importing scenario — loading map…"
        # Load the real underlying map directly (bypass the scenario dispatcher so we neither
        # recurse nor disturb the ★ shown selected in the Map dropdown).
        async for _ev in self._load_map_impl(): yield _ev
        if not self.is_loaded:
            self.status = "Import failed: map could not be loaded (not available here?)."
            return

        # Phase 2 — primary edits into globals, then resimulate to rebuild the scene.
        _g._user_agents = _wp(prim.get("user_agents", []))
        _g._user_static_agents = prim.get("user_static_agents", []) or []
        _g._user_expert_agents = _wp(prim.get("user_expert_agents", []))
        _g._goal_overrides = {k: _tup(v) for k, v in _ikeys(prim.get("goal_overrides", {})).items()}
        _rm_static = set(prim.get("removed_static_slots", []) or [])
        _rm_expert = set(prim.get("removed_native_expert_idxs", []) or [])
        _g._removed_slots = set(prim.get("removed_slots", []) or [])
        _g._removed_static_slots = _rm_static
        _g._removed_native_expert_idxs = _rm_expert
        # _pending_* drive the actual C-level detach in resimulate and are consumed (emptied)
        # after each removal — so they are empty at export time. Reconstruct them from the
        # persistent _removed_* sets (both received identical values at removal time) so the
        # fresh env actually detaches the removed statics/experts instead of showing them.
        _g._pending_static_detach_slots = set(_rm_static)
        _g._pending_expert_detach_idxs = set(_rm_expert)
        _g._env_has_detaches = bool(prim.get("env_has_detaches", False))
        _g._native_active_moves = {k: _tup(v) for k, v in _ikeys(prim.get("native_active_moves", {})).items()}
        _g._native_static_moves = {str(k): _tup(v) for k, v in (prim.get("native_static_moves", {}) or {}).items()}
        _g._native_expert_moves = {str(k): _wp([v])[0] for k, v in (prim.get("native_expert_moves", {}) or {}).items()}
        self.user_agent_count = len(_g._user_agents)
        self.user_static_agent_count = len(_g._user_static_agents)
        self.user_expert_count = len(_g._user_expert_agents)
        async for _ev in self.resimulate(): yield _ev

        # Phase 3 — ghost env. toggle_ghost_env creates it and mirrors primary as baseline
        # (incl. replaying primary's permanent removals); we then overwrite the non-destructive
        # ghost edits (placements/goals/moves) and resimulate. Ghost-only native removals that
        # diverge from primary are not restored (documented limitation).
        if bool(flags.get("ghost_env_active", False)):
            for _ev in self.toggle_ghost_env(): yield _ev
            if self.ghost_env_active:
                _g._ghost_user_agents = _wp(ghost.get("user_agents", []))
                _g._ghost_user_static_agents = ghost.get("user_static_agents", []) or []
                _g._ghost_user_expert_agents = _wp(ghost.get("user_expert_agents", []))
                _g._ghost_goal_overrides = {k: _tup(v) for k, v in _ikeys(ghost.get("goal_overrides", {})).items()}
                _g._ghost_native_active_moves = {k: _tup(v) for k, v in _ikeys(ghost.get("native_active_moves", {})).items()}
                _g._ghost_native_static_moves = {str(k): _tup(v) for k, v in (ghost.get("native_static_moves", {}) or {}).items()}
                _g._ghost_native_expert_moves = {str(k): _wp([v])[0] for k, v in (ghost.get("native_expert_moves", {}) or {}).items()}
                self.ghost_user_agent_count = len(_g._ghost_user_agents)
                self.ghost_user_static_agent_count = len(_g._ghost_user_static_agents)
                self.ghost_user_expert_count = len(_g._ghost_user_expert_agents)
                for _ev in self.ghost_resimulate(): yield _ev

        # Phase 4 — restore view flags + clear selection/tools, sync JS.
        self.ghost_side_by_side = bool(flags.get("ghost_side_by_side", self.ghost_side_by_side))
        self.mirror_placement = bool(flags.get("mirror_placement", self.mirror_placement))
        self.env_focus = flags.get("env_focus", self.env_focus)
        self.show_goals = bool(flags.get("show_goals", self.show_goals))
        self.show_goal_radius = bool(flags.get("show_goal_radius", self.show_goal_radius))
        self.show_labels = bool(flags.get("show_labels", self.show_labels))
        self.show_trajectories = bool(flags.get("show_trajectories", self.show_trajectories))
        self.selected_agent_idx = -1; self.selected_agent_str = "-1"; self.selected_agent_label = ""
        self.selected_expert_idx = -1; self.selected_expert_idx_str = "-1"
        self.selected_native_expert_idx = -1; self.selected_native_expert_idx_str = "-1"
        self.select_mode = False; self.goal_edit_mode = False; self.move_mode = False
        self.agent_place_mode = False; self.static_agent_place_mode = False; self.expert_place_mode = False
        _b = lambda v: str(bool(v)).lower()
        yield rx.call_script(
            f"window._pdEnvFocus='{self.env_focus}';"
            f"window._pdShowGoals={_b(self.show_goals)};window._pdShowGoalRadius={_b(self.show_goal_radius)};"
            f"window._pdShowLabels={_b(self.show_labels)};window._pdShowTrajectories={_b(self.show_trajectories)};"
            "if(window._pdSetTool)window._pdSetTool('pan');"
            "if(window._pdRedraw)window._pdRedraw();"
        )
        self.status = "Scenario imported."

    async def reset_to_default(self):
        """Restore the original loaded scene: clear added agents, restore removed ones, reset goals."""
        # When the loaded scene is an exported ★ entry, its "default" is the saved scene itself,
        # not the raw underlying map. Re-apply the scenario JSON so Reset returns to the export's
        # base (clearing any edits made on top of it) instead of the map it was created from.
        if self.selected_map_choice.startswith("scenario://"):
            fname = self.selected_map_choice[len("scenario://"):]
            async for _ev in self.import_scenario_file(fname): yield _ev
            return
        _g._user_agents = []
        _g._user_static_agents = []
        _g._user_expert_agents = []
        _g._goal_overrides.clear()
        _g._removed_slots = set()
        _g._removed_static_slots = set()
        _g._removed_native_expert_idxs = set()
        _g._pending_static_detach_slots = set()
        _g._pending_expert_detach_idxs = set()
        _g._native_active_moves = {}
        _g._ghost_native_active_moves = {}
        _g._native_static_moves = {}
        _g._native_expert_moves = {}
        _g._ghost_native_static_moves = {}
        _g._ghost_native_expert_moves = {}
        self.user_agent_count = 0
        self.user_static_agent_count = 0
        self.user_expert_count = 0
        self.demo_slots_used = 0
        self.user_agent_items = []
        self.user_static_items = []
        self.user_expert_items = []
        self.agent_place_mode = False
        self.static_agent_place_mode = False
        self.expert_place_mode = False
        self.move_mode = False
        self.goal_edit_mode = False
        self.select_mode = False
        self.selected_goal_slot = -1
        self.selected_agent_idx = -1
        self.selected_agent_str = "-1"
        self.selected_agent_label = ""
        self.selected_expert_idx = -1
        self.selected_expert_idx_str = "-1"
        self.selected_native_expert_idx = -1
        self.selected_native_expert_idx_str = "-1"
        # Restore the user-placed-agent name counters to their load-time values so the
        # next placed agent reuses the same number instead of continuing to climb.
        _g._user_agent_name_counter = _g._original_frames_cache.get(
            "user_agent_name_counter", _g._user_agent_name_counter)
        _g._user_static_expert_name_counter = _g._original_frames_cache.get(
            "user_static_expert_name_counter", _g._user_static_expert_name_counter)
        yield rx.call_script("if (window._pdSetTool) window._pdSetTool('pan');")

        # Reset tears the scene back to the freshly-loaded map, so drop the ghost env too.
        if self.ghost_env_active:
            for _ev in self._deactivate_ghost(): yield _ev

        # Permanently-detached native agents can only be restored by rebuilding the
        # env from the map file (c_detach_* zeroes their trajectory). Skip the rebuild
        # when nothing was detached — the cache/resimulate paths below already restore
        # the original scene correctly in that case.
        _env_rebuilt = False
        if _g._env_has_detaches and _g._env is not None:
            self.status = "Restoring removed agents…"
            yield
            self._recreate_primary_env()
            _env_rebuilt = True

        # After a rebuild the env matches the originally-cached scene, so the cache is
        # authoritative — restore from it even though the (still-decremented) native
        # counts make the staleness check fire. The cache restore below resets those
        # counts. Only fall back to resimulate when there is no cache to restore from.
        _cache_stale = (
            _g._original_frames_cache.get("native_static_count", _g._native_static_count) != _g._native_static_count
            or _g._original_frames_cache.get("native_expert_count", _g._native_expert_count) != _g._native_expert_count
        )
        if not _g._original_frames_cache or (_cache_stale and not _env_rebuilt):
            self.status = "Resetting to default…"
            async for _ev in self.resimulate(): yield _ev
            return

        _g._agent_render_frames = _g._original_frames_cache["agent_render_frames"]
        _g._static_agents = _g._original_frames_cache["static_agents"]
        _g._map_data = _g._original_frames_cache["map_data"]
        _g._agent_states = _g._original_frames_cache["agent_states"]
        _g._agent_status_frames = _g._original_frames_cache["agent_status_frames"]
        _g._render_bounds = _g._original_frames_cache["render_bounds"]
        self.agent_ids = _g._original_frames_cache["agent_ids"]
        self.agent_labels = _g._original_frames_cache["agent_labels"]
        self.static_sidebar_items = _g._original_frames_cache["static_sidebar_items"]
        viewer.initial_goal_positions = list(_g._original_frames_cache["initial_goal_positions"])
        _g._primary_actions = list(_g._original_frames_cache.get("primary_actions", []))
        _g._native_agent_labels = list(_g._original_frames_cache.get("native_agent_labels", []))
        _g._expert_render_frames = _g._original_frames_cache.get("expert_render_frames", [])
        self.expert_sidebar_items = list(_g._original_frames_cache.get("expert_sidebar_items", []))
        _g._native_static_count = _g._original_frames_cache.get("native_static_count", _g._native_static_count)
        _g._native_expert_count = _g._original_frames_cache.get("native_expert_count", _g._native_expert_count)
        _g._native_static_labels = list(_g._original_frames_cache.get("native_static_labels", _g._native_static_labels))
        _g._native_expert_orig_indices = list(_g._original_frames_cache.get("native_expert_orig_indices", _g._native_expert_orig_indices))
        _g._native_expert_labels = list(_g._original_frames_cache.get("native_expert_labels", _g._native_expert_labels))
        self.num_frames = len(_g._agent_render_frames)
        self._set_frame(0)
        self.status = f"Reset to default — {self.num_frames} frames"
        yield rx.call_script("if (window._pdZoomReset) window._pdZoomReset();")
        yield rx.call_script(_goal_js(_compute_goal_positions()))
        yield rx.call_script(_agent_frames_js(_g._agent_render_frames, _g._static_agents, _g._map_data, _g._expert_render_frames, n_user_experts=0))

    async def handle_goal_drop(self, data):
        """Commit a dragged goal to a new position (triggered by hidden button after mouseup)."""
        if not self.goal_edit_mode or not isinstance(data, dict):
            return
        mirror = self.mirror_placement and self.ghost_env_active and _g._ghost_env is not None
        is_ghost = (not mirror) and self.env_focus == "ghost" and self.ghost_env_active
        env = _g._ghost_env if is_ghost else _g._env
        if env is None:
            return
        user_agents = _g._ghost_user_agents if is_ghost else _g._user_agents
        agent_slots = _g._ghost_user_agent_slots if is_ghost else _g._user_agent_slots
        overrides = _g._ghost_goal_overrides if is_ghost else _g._goal_overrides
        slot = int(data.get("slot", -1))
        if slot < 0:
            return
        t = viewer.last_render_transform
        if t is None:
            return
        fx = float(data.get("x", 0.5))
        fy = float(data.get("y", 0.5))
        world_x, world_y = viewer.pixels_to_world(fx * t["img_w"], fy * t["img_h"])
        slot = max(0, min(slot, env.num_agents - 1))
        # User-placed agents are re-injected (with their stored goal) on every resimulate,
        # which would clobber a goal_overrides entry. So for a user agent, update its stored
        # goal directly; only native agents use the goal_overrides mechanism.
        ua_idx = next((i for i, s in enumerate(agent_slots) if s == slot), -1)
        if ua_idx >= 0:
            user_agents[ua_idx]["goal_x"] = world_x
            user_agents[ua_idx]["goal_y"] = world_y
            overrides.pop(slot, None)
        else:
            overrides[slot] = (world_x, world_y)
        env.set_goals({slot: (world_x, world_y)})
        self.selected_goal_slot = -1
        if mirror:
            # Apply same goal change to ghost env (mirrors primary user-agent list).
            ghost_ua_idx = next((i for i, s in enumerate(_g._ghost_user_agent_slots) if s == slot), -1)
            if ghost_ua_idx >= 0:
                _g._ghost_user_agents[ghost_ua_idx]["goal_x"] = world_x
                _g._ghost_user_agents[ghost_ua_idx]["goal_y"] = world_y
                _g._ghost_goal_overrides.pop(slot, None)
            else:
                _g._ghost_goal_overrides[slot] = (world_x, world_y)
            _g._ghost_env.set_goals({slot: (world_x, world_y)})
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev
            for _ev in self.ghost_resimulate(): yield _ev
        elif is_ghost:
            for _ev in self.ghost_resimulate(): yield _ev
        else:
            async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev

    # ── Goal form editor ─────────────────────────────────────────────────────

    def set_goal_edit_x(self, val: str):
        self.goal_edit_x = val

    def set_goal_edit_y(self, val: str):
        self.goal_edit_y = val

    async def apply_goal_from_form(self):
        """Apply typed X/Y world coords as goal override for selected agent."""
        slot = self.selected_agent_idx
        if slot < 0 or _g._env is None:
            self.status = "Select an agent first"
            return
        try:
            wx = float(self.goal_edit_x)
            wy = float(self.goal_edit_y)
        except (ValueError, TypeError):
            self.status = "Invalid goal coordinates"
            return
        slot = max(0, min(slot, _g._env.num_agents - 1))
        _g._goal_overrides[slot] = (wx, wy)
        _g._env.set_goals({slot: (wx, wy)})
        self.selected_goal_slot = -1
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev

    async def resimulate(self, skip_zoom_reset=False):
        """Reset the env, re-apply goal overrides, and regenerate all frames."""
        import asyncio
        if _g._env is None:
            return
        _g._current_sim_steps = self.sim_steps
        self.is_busy = True
        self.is_playing = False
        self.resim_progress = 0
        self.status = "Re-simulating…"
        yield
        try:
            _g._env.reset()
            _g._env.reset_demo_slots()
            # Apply pending slot removals in descending order (avoids index-shift errors).
            # c_detach_active_agent left-shifts active_agent_indices, so we mirror that
            # shift in _g._native_agent_labels by popping at the same position.
            for slot in sorted(_g._removed_slots, reverse=True):
                _g._env.detach_active_agent(slot)
                if 0 <= slot < len(_g._native_agent_labels):
                    _g._native_agent_labels.pop(slot)
            _g._removed_slots.clear()
            # Apply pending C-level static detaches. _pending_static_detach_slots holds STABLE
            # LABELS (not live indices). The live C index for a label shifts as other statics
            # detach, so we re-derive it from _native_static_labels each iteration — order
            # independent, and always removes exactly the clicked car.
            for label in list(_g._pending_static_detach_slots):
                pos = next((p for p, l in enumerate(_g._native_static_labels)
                            if str(l) == str(label)), -1)
                if pos < 0:
                    continue
                _g._env.detach_static_agent(pos)
                _g._native_static_labels.pop(pos)
                _g._native_static_count -= 1
            _g._pending_static_detach_slots.clear()
            # Apply pending C-level expert detaches. Detach in DESCENDING index order so the
            # C left-shift of expert_static_agent_indices doesn't invalidate not-yet-processed
            # indices, and pop the parallel label/orig-index lists at the same position. The
            # detached experts are then permanently absent from the C render output, so the
            # display-filter set is cleared rather than maintained in a shifting index space.
            for idx in sorted(_g._pending_expert_detach_idxs, reverse=True):
                _g._env.detach_expert_agent(idx)
                if 0 <= idx < len(_g._native_expert_orig_indices):
                    _g._native_expert_orig_indices.pop(idx)
                if 0 <= idx < len(_g._native_expert_labels):
                    _g._native_expert_labels.pop(idx)
                _g._native_expert_count -= 1
            _g._pending_expert_detach_idxs.clear()
            _g._removed_native_expert_idxs.clear()
            # Always re-run prepare so newly freed slots get allocated and the counter updates.
            _g._env.prepare_demo_slots()
            if _g._goal_overrides:
                _g._env.set_goals(_g._goal_overrides)
            for ua in _g._user_agents:
                _g._env.inject_demo_active_agent(ua["x"], ua["y"], ua["heading"], ua["goal_x"], ua["goal_y"],
                                                  length=ua.get("length", 0.0), width=ua.get("width", 0.0))
            _g._user_static_agent_slots = []
            for sa in _g._user_static_agents:
                slot = _g._env.inject_demo_static_agent(sa["x"], sa["y"], sa["heading"],
                                                         length=sa.get("length", 0.0), width=sa.get("width", 0.0))
                _g._user_static_agent_slots.append(slot)
            _g._user_expert_agent_slots = []
            _expert_unreachable: list[int] = []
            for ea_idx, ea in enumerate(_g._user_expert_agents):
                traj = _compute_expert_trajectory(ea, self.sim_steps)
                if traj is None:
                    _expert_unreachable.append(ea_idx + 1)
                    _g._user_expert_agent_slots.append(-1)
                    continue
                xs, ys, hs = traj
                slot_k = _g._env.inject_demo_expert_agent(ea["sx"], ea["sy"], float(hs[0]),
                                                           length=ea.get("length", 0.0), width=ea.get("width", 0.0))
                if slot_k >= 0:
                    _g._env.set_demo_expert_trajectory(slot_k, xs, ys, hs)
                _g._user_expert_agent_slots.append(slot_k)
            # Re-apply in-place native-agent moves (teleport keeps the original slot/ID).
            for _mslot, _mv in _g._native_active_moves.items():
                try:
                    _g._env.teleport_agent(_mslot, _mv[0], _mv[1], _mv[2], _mv[3], _mv[4])
                except Exception:
                    pass
            # Re-apply native static/expert moves in place. Key is the stable label; re-derive
            # the live C index from the current native-label lists (popped on detach).
            for _lbl, _mv in _g._native_static_moves.items():
                _idx = next((p for p, l in enumerate(_g._native_static_labels) if str(l) == str(_lbl)), -1)
                if _idx < 0:
                    continue
                try:
                    _g._env.teleport_static_agent(_idx, _mv[0], _mv[1], _mv[2])
                except Exception:
                    pass
            for _lbl, _ea in _g._native_expert_moves.items():
                _idx = next((p for p, l in enumerate(_g._native_expert_labels) if str(l) == str(_lbl)), -1)
                if _idx < 0:
                    continue
                _traj = _compute_expert_trajectory(_ea, self.sim_steps)
                if _traj is None:
                    continue
                _xs, _ys, _hs = _traj
                try:
                    _g._env.teleport_expert_agent(_idx, _xs, _ys, _hs)
                except Exception:
                    pass
            _g._env.recompute_observations()
            # Run collect_frames in a thread and poll progress so Reflex can push updates.
            _env_ref = _g._env
            _policy_ref = _g._policy
            _steps = self.sim_steps
            _loop = asyncio.get_running_loop()
            _task = _loop.run_in_executor(
                None,
                lambda: viewer.collect_frames(
                    _env_ref, num_steps=_steps, save_every=_g.SAVE_EVERY, policy=_policy_ref
                )
            )
            while not _task.done():
                _pct = min(int(viewer._resim_step / max(viewer._resim_total, 1) * 100), 99)
                _off = f"{69.115 * (1 - _pct / 100):.2f}"
                yield rx.call_script(
                    f"(function(){{var e=document.getElementById('pd-resim-ring');"
                    f"if(e)e.style.strokeDashoffset='{_off}';}})();"
                )
                await asyncio.sleep(0.08)
            (
                _g._agent_render_frames, _g._static_agents, _g._map_data,
                _g._agent_states, _g._agent_status_frames, _g._render_bounds,
                _g._expert_render_frames, _g._metrics,
            ) = _task.result()
            yield rx.call_script(
                "var e=document.getElementById('pd-resim-ring');"
                "if(e)e.style.strokeDashoffset='0';"
            )
            _g._primary_actions = list(viewer._last_recorded_actions)
            # Assign each static a STABLE identity that is used uniformly as its display id,
            # its canvas selection handle (slot) and the key for the removed-set. The live C
            # detach index (the raw position _raw) is NOT used as identity — it shifts when
            # other statics detach. Native statics 0.._native_static_count-1 carry their frozen
            # _native_static_labels entry; demo statics (appended after natives, in injection
            # order) carry their user agent's frozen friendly label.
            _present_user_statics = [i for i, k in enumerate(_g._user_static_agent_slots) if k is not None and k >= 0] \
                if _g._user_static_agent_slots else list(range(len(_g._user_static_agents)))
            _demo_slot_to_useridx = {}
            for _se in _g._static_agents:
                _raw = _se.get("slot", -1)
                if 0 <= _raw < _g._native_static_count and _raw < len(_g._native_static_labels):
                    _lbl = _g._native_static_labels[_raw]
                elif _raw >= _g._native_static_count:
                    _p = _raw - _g._native_static_count
                    if _p < len(_present_user_statics):
                        _uidx = _present_user_statics[_p]
                        _lbl = _g._user_static_agents[_uidx].get("label", str(_uidx))
                        _demo_slot_to_useridx[str(_lbl)] = _uidx
                    else:
                        _lbl = str(_raw)
                else:
                    _lbl = str(_raw)
                _se["id"] = str(_lbl)
                try:
                    _se["slot"] = int(_lbl)
                except (TypeError, ValueError):
                    _se["slot"] = _raw
            # Match user-placed active agents to their actual slot indices by position.
            # inject_demo_active_agent returns a demo-slot-relative index (0,1,2…), not
            # the global controlled-agent index, so we must find it via position matching.
            _g._user_agent_slots = (
                _match_positions_to_slots(_g._user_agents, _g._agent_states[0])
                if _g._user_agents and _g._agent_states else []
            )
            # Build a stable slot→label map for all agents.
            # Native agents: _g._native_agent_labels[i] mirrors active_agent_indices after
            # left-shifts from detach, so slot i always maps to the original label.
            # User agents: labels assigned at placement time (e.g. "U0", "U1") so they
            # survive removal and re-injection into different demo slots.
            _user_slot_to_label = {
                slot: _g._user_agents[i].get("label", f"U{i}")
                for i, slot in enumerate(_g._user_agent_slots) if slot >= 0
            }
            _slot_to_label = {i: _g._native_agent_labels[i] for i in range(len(_g._native_agent_labels))}
            _slot_to_label.update(_user_slot_to_label)
            if _slot_to_label:
                for frame in _g._agent_render_frames:
                    for entry in frame:
                        if entry.get("slot") in _slot_to_label:
                            entry["id"] = _slot_to_label[entry["slot"]]
                viewer.initial_goal_positions = [
                    {**p, "label": _slot_to_label[p["slot"]]}
                    if p["slot"] in _slot_to_label else p
                    for p in viewer.initial_goal_positions
                ]
            # Demo statics already carry their friendly label as both id and slot (assigned in
            # the relabel block by injection order). No nearest-position matching and no
            # removed-slot filtering are needed: detached natives are already absent from the C
            # render output, and identity is the stable label, not the shifting raw index.
            user_slot_to_idx = {int(_lbl): _uidx for _lbl, _uidx in _demo_slot_to_useridx.items()}
            _uidx_to_slot = {_uidx: _slot for _slot, _uidx in user_slot_to_idx.items()}
            _g._user_static_agent_slots = [
                _uidx_to_slot.get(i, -1) for i in range(len(_g._user_static_agents))
            ]
            self.static_sidebar_items = [
                [str(e["slot"]),
                 "added" if e.get("slot") in user_slot_to_idx else "default",
                 str(user_slot_to_idx[e.get("slot")]) if e.get("slot") in user_slot_to_idx else "-1",
                 e["id"]]
                for e in _g._static_agents
            ]
            self.num_frames = len(_g._agent_render_frames)
            if _g._agent_states:
                self.agent_ids = [i for i, v in enumerate(_g._agent_states[0]["valid"]) if v]
            if _g._agent_render_frames:
                f0 = _g._agent_render_frames[0]
                self.agent_labels = [f0[k]["id"] if k < len(f0) else str(aid)
                                     for k, aid in enumerate(self.agent_ids)]
            if _g._removed_native_expert_idxs:
                _g._expert_render_frames = [
                    [e for i, e in enumerate(frame)
                     if i >= _g._native_expert_count or i not in _g._removed_native_expert_idxs]
                    for frame in _g._expert_render_frames
                ]
            # Stable labels: _native_expert_labels is popped in lockstep with detaches, so
            # surviving experts keep their original number (no positional renumbering). The
            # third sidebar field stays the current compacted position (the detach slot index).
            self.expert_sidebar_items = [
                [_g._native_expert_labels[i], "default", str(i)]
                for i in range(len(_g._native_expert_labels))
            ]
            self.user_expert_items = [
                [str(i), a.get("label", f"Fixed Trajectory {i+1}")] for i, a in enumerate(_g._user_expert_agents)
            ]
            # Only successfully-injected user experts appear in the render frames (unreachable
            # ones have slot -1 and are skipped), so the label list must match that subset or
            # the zip below misaligns and the native-region indexing (experts.length -
            # userExpertCount) breaks.
            _injected_user_expert_labels = [
                a.get("label", f"Fixed Trajectory {i+1}")
                for i, a in enumerate(_g._user_expert_agents)
                if i < len(_g._user_expert_agent_slots)
                and _g._user_expert_agent_slots[i] is not None
                and _g._user_expert_agent_slots[i] >= 0
            ]
            expert_labels = list(_g._native_expert_labels) + _injected_user_expert_labels
            if expert_labels and _g._expert_render_frames:
                _g._expert_render_frames = [
                    [
                        {**e, "id": lbl, "lx": round(e["cx"] + 2, 2), "ly": round(e["cy"] - 10, 2)}
                        for e, lbl in zip(frame, expert_labels)
                    ]
                    for frame in _g._expert_render_frames
                ]
            self.user_expert_count = len(_g._user_expert_agents)
            _used, _total = _g._env.get_demo_slots_info()
            # Use C-level counts directly. Removing native statics/experts only hides
            # them in the UI; it does NOT free a C entity slot. Subtracting removed
            # counts from _used would falsely show free slots that don't exist, causing
            # inject_demo_static_agent() to return -1 and the position match to label
            # the wrong native static.
            self.demo_slots_used  = _used
            self.demo_slots_total = _total
            self._set_frame(0)
            if _expert_unreachable:
                names = ", ".join(f"Fixed Trajectory {n}" for n in _expert_unreachable)
                self.status = f"No lane path found for {names} — agent not placed"
            else:
                self.status = f"Re-simulation complete — {self.num_frames} frames"
        except Exception as exc:
            self.status = f"Error re-simulating: {exc}"
        self.is_busy = False
        self.resim_progress = 0
        if not skip_zoom_reset:
            yield rx.call_script("if (window._pdZoomReset) window._pdZoomReset();")
        # _pdUserExpertCount must count only injected user experts (those present in the
        # render frames); unreachable ones (slot -1) are not drawn.
        _n_injected_user_experts = sum(
            1 for s in _g._user_expert_agent_slots if s is not None and s >= 0
        )
        yield rx.call_script(_agent_frames_js(_g._agent_render_frames, _g._static_agents, _g._map_data, _g._expert_render_frames, n_user_experts=_n_injected_user_experts))
        yield rx.call_script(_goal_js(_compute_goal_positions()))
        if self.ghost_env_active and _g._ghost_env is not None:
            for _ev in self.ghost_resimulate():
                yield _ev

    def zoom_in(self):
        return rx.call_script("if (window._pdZoomStep) window._pdZoomStep(1);")

    def zoom_out(self):
        return rx.call_script("if (window._pdZoomStep) window._pdZoomStep(-1);")

    def reset_zoom(self):
        return rx.call_script("if (window._pdZoomReset) window._pdZoomReset();")

    @rx.var
    def frames_max(self) -> int:
        return self.num_frames - 1 if self.num_frames > 0 else 0

    @rx.var
    def cur_time_str(self) -> str:
        return f"{self.current_frame * _g.DT * _g.SAVE_EVERY:.2f}" if self.is_loaded else "–"

    @rx.var
    def tot_time_str(self) -> str:
        return f"{(self.num_frames - 1) * _g.DT * _g.SAVE_EVERY:.2f}" if self.is_loaded else "–"

    @rx.var
    def ghost_diverge_time_str(self) -> str:
        return f"{self.ghost_diverge_frame * _g.DT * _g.SAVE_EVERY:.2f}" if self.is_loaded else "–"

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set_frame(self, idx: int):
        idx = max(0, min(idx, len(_g._agent_render_frames) - 1))
        self.current_frame = idx
        total = max(self.num_frames - 1, 1)
        self.progress_pct = f"{idx / total * 100:.1f}%"
        if self.is_playing:
            # Skip sidebar list rebuilds during playback — rebuilding 80-agent lists
            # every tick causes React reconcile jank that drops rAF frames (flicker).
            return
        if _g._agent_status_frames and idx < len(_g._agent_status_frames):
            statuses = _g._agent_status_frames[idx]
            labels = self.agent_labels
            user_slot_to_idx = {slot: i for i, slot in enumerate(_g._user_agent_slots)}
            self.agent_sidebar_items = [
                [str(aid), labels[k] if k < len(labels) else str(aid),
                 statuses[aid] if aid < len(statuses) else "Running",
                 "added" if aid in user_slot_to_idx else "default",
                 str(user_slot_to_idx[aid]) if aid in user_slot_to_idx else "-1",
                 "sdc" if aid in _g._sdc_slots else ""]
                for k, aid in enumerate(self.agent_ids)
            ]
        if _g._expert_render_frames and idx < len(_g._expert_render_frames):
            self.expert_sidebar_items = [
                [_g._native_expert_labels[i], "default", str(i)]
                for i in range(len(_g._native_expert_labels))
            ]
        # Ghost env sidebar
        if self.ghost_env_active:
            if _g._ghost_agent_status_frames and idx < len(_g._ghost_agent_status_frames):
                g_statuses = _g._ghost_agent_status_frames[idx]
                g_labels = _g._ghost_agent_labels
                ghost_slot_to_idx = {slot: i for i, slot in enumerate(_g._ghost_user_agent_slots)}
                self.ghost_agent_sidebar_items = [
                    [str(aid), g_labels[k] if k < len(g_labels) else str(aid),
                     g_statuses[aid] if aid < len(g_statuses) else "Running",
                     "added" if aid in ghost_slot_to_idx else "default",
                     str(ghost_slot_to_idx[aid]) if aid in ghost_slot_to_idx else "-1",
                     "sdc" if aid in _g._sdc_slots else ""]
                    for k, aid in enumerate(_g._ghost_agent_ids)
                ]
            if _g._ghost_expert_render_frames and idx < len(_g._ghost_expert_render_frames):
                self.ghost_native_expert_sidebar_items = [
                    [_g._ghost_native_expert_labels[i], "default", str(i)]
                    for i in range(_g._ghost_native_expert_count)
                    if i < len(_g._ghost_native_expert_labels) and i not in _g._ghost_removed_native_expert_idxs
                ]
            self.ghost_user_expert_count = len(_g._ghost_user_expert_agents)
            self.ghost_user_expert_items = [
                [str(i), a.get("label", f"Fixed Trajectory {i+1}")] for i, a in enumerate(_g._ghost_user_expert_agents)
            ]

    @staticmethod
    def _fmt_time(frame_idx: int) -> str:
        t = frame_idx * _g.DT * _g.SAVE_EVERY
        minutes = int(t) // 60
        secs = t - minutes * 60
        return f"{minutes}:{secs:04.1f}"

    # ── startup ───────────────────────────────────────────────────────────────

    def on_load(self):
        config_dir = viewer.get_config_dir()
        ini_files = viewer.scan_ini_files(config_dir)
        self.available_ini_files = [[label, path] for label, path in ini_files]
        self.refresh_scenario_files()
        self._refresh_split()
        # A reconnecting tab reset the per-session random flags to False, but the shared
        # policy globals survive — reconcile so the banner/badges match what actually runs.
        self._sync_policy_flags()

    def _refresh_split(self):
        data_root = viewer.get_data_root()
        maps = viewer.scan_maps(data_root, self.selected_split)
        self.map_count = len(maps)
        if maps:
            self.selected_map = maps[0]
            self.map_id_input = str(maps[0])
            self.status = (
                f"Found {len(maps)} maps in '{self.selected_split}'. "
                f"Enter a map ID (0–{maps[-1]}) and press Load."
            )
        else:
            self.map_count = 0
            self.status = f"No maps found in {data_root}/{self.selected_split}"

    # ── controls ──────────────────────────────────────────────────────────────

    def set_ini(self, path: str):
        self.selected_ini_path = path
        _g._render_style = viewer.load_render_style(path or None)
        # Changing the config rebuilds maps/policies, so tear down the whole env +
        # frontend first — a stale env or leftover client state causes glitches.
        # Soft (in-process) teardown only: a config switch must not restart the app.
        yield from self._soft_reset()
        if path:
            demo = viewer.parse_demo_sections(path)
            maps = [[k, v] for k, v in demo["maps"].items()]
            policies = [[name, model, config] for name, model, config in demo["policy_list"]]
            features = demo.get("features", {})
            self.demo_maps = maps
            self.demo_policies = policies
            self.has_demo_maps = bool(maps)
            self.has_demo_policies = bool(policies)
            self.show_ghost_replay_slider = features.get("show_ghost_replay_slider", "false").lower() == "true"
            if maps:
                self.selected_map_path = maps[0][1]
                self.selected_map_choice = maps[0][1]
            if policies:
                self.selected_policy_path = policies[0][1]
                self.selected_policy_config = policies[0][2]
                self.selected_policy_name = policies[0][0]
                self.ghost_policy_path = policies[0][1]
                self.ghost_policy_config = policies[0][2]
                self.ghost_policy_name = policies[0][0]
        else:
            self.demo_maps = []
            self.demo_policies = []
            self.has_demo_maps = False
            self.has_demo_policies = False
            self.show_ghost_replay_slider = False
            self.selected_map_choice = ""
        if not self.has_demo_maps:
            self._refresh_split()
        else:
            self.status = "Select a map and press Load."

    def set_demo_map(self, path: str):
        # `path` is either a real map binary path or a "scenario://<file>" sentinel for an
        # exported scene. Always record the dropdown's displayed choice; only real maps set
        # selected_map_path (a saved scene sets it later, to its underlying map, in _apply_scenario).
        self.selected_map_choice = path
        if not path.startswith("scenario://"):
            self.selected_map_path = path

    async def set_demo_policy(self, value: str):
        parts = value.split("||", 1)
        self.selected_policy_path = parts[0]
        self.selected_policy_config = parts[1] if len(parts) > 1 else ""
        self.selected_policy_name = ""
        for policy in self.demo_policies:
            if policy[1] == self.selected_policy_path and policy[2] == self.selected_policy_config:
                self.selected_policy_name = policy[0]
                break
        # Clear the stale error from the previously selected policy regardless of whether
        # an env is loaded yet, so the badge/banner never show a mismatched reason.
        self.policy_load_error = ""
        if _g._env is None:
            # No env yet: this selection will be loaded on the next map load. Nothing to
            # reconcile now, so leave policy_is_random alone (the load path owns it).
            return
        policy_ini = self.selected_policy_config or None
        _g._policy = None
        self.policy_is_random = False
        if self.selected_policy_path:
            try:
                _g._policy = viewer.load_policy_from_path(
                    self.selected_policy_path, _g._env, policy_ini
                )
            except Exception as exc:
                self.policy_load_error = str(exc)
                self.policy_is_random = True
        else:
            self.policy_is_random = True
        async for _ev in self.resimulate(skip_zoom_reset=True): yield _ev

    def set_ghost_policy(self, value: str):
        parts = value.split("||", 1)
        self.ghost_policy_path = parts[0]
        self.ghost_policy_config = parts[1] if len(parts) > 1 else ""
        for policy in self.demo_policies:
            if policy[1] == self.ghost_policy_path and policy[2] == self.ghost_policy_config:
                self.ghost_policy_name = policy[0]
                break
        if not (self.ghost_env_active and _g._ghost_env is not None):
            return
        ghost_ini = self.ghost_policy_config or None
        _g._ghost_policy = None
        self.ghost_policy_is_random = False
        self.ghost_policy_load_error = ""
        if self.ghost_policy_path:
            try:
                _g._ghost_policy = viewer.load_policy_from_path(
                    self.ghost_policy_path, _g._ghost_env, ghost_ini
                )
            except Exception as exc:
                self.ghost_policy_load_error = str(exc)
                self.ghost_policy_is_random = True
        else:
            self.ghost_policy_is_random = True
        yield State.ghost_resimulate

    def set_split(self, split: str):
        self.selected_split = split
        # Choosing a split/map-id supersedes any exported-scene selection.
        if self.selected_map_choice.startswith("scenario://"):
            self.selected_map_choice = ""
        self._refresh_split()
        self._reset_playback()

    def set_map_id_input(self, value: str):
        self.map_id_input = value
        if self.selected_map_choice.startswith("scenario://"):
            self.selected_map_choice = ""

    def set_play_speed(self, value: str):
        try:
            self.play_speed = float(value)
        except ValueError:
            pass
        return rx.call_script(f"window._pdPlaySpeed = {self.play_speed};")

    def _reset_playback(self):
        _g._original_frames_cache.clear()
        _g._lane_graph_cache = None
        _g._agent_render_frames = []
        _g._expert_render_frames = []
        _g._static_agents = []
        _g._map_data = {}
        _g._env = None
        _g._goal_overrides.clear()
        _g._user_agents = []
        _g._user_static_agents = []
        _g._user_expert_agents = []
        _g._user_agent_slots = []
        _g._user_static_agent_slots = []
        _g._user_expert_agent_slots = []
        _g._removed_slots = set()
        _g._removed_static_slots = set()
        _g._removed_native_expert_idxs = set()
        _g._pending_static_detach_slots = set()
        _g._pending_expert_detach_idxs = set()
        _g._native_active_moves = {}
        _g._ghost_native_active_moves = {}
        _g._native_static_moves = {}
        _g._native_expert_moves = {}
        _g._ghost_native_static_moves = {}
        _g._ghost_native_expert_moves = {}
        _g._env_has_detaches = False
        _g._sdc_slots.clear()
        _g._native_agent_labels = []
        _g._native_static_labels = []
        _g._native_expert_orig_indices = []
        _g._native_expert_labels = []
        _g._native_static_count = 0
        _g._native_expert_count = 0
        _g._user_static_expert_name_counter = 0
        _g._user_agent_name_counter = 0
        _g._primary_actions = []
        _g._agent_states = []
        _g._agent_status_frames = []
        _g._render_bounds = {}
        # Clear ghost state too
        _g._ghost_env = None
        _g._ghost_policy = None
        _g._ghost_agent_render_frames = []
        _g._ghost_expert_render_frames = []
        _g._ghost_static_agents = []
        _g._ghost_map_data = {}
        _g._ghost_agent_states = []
        _g._ghost_agent_status_frames = []
        _g._ghost_render_bounds = {}
        _g._ghost_user_agents = []
        _g._ghost_user_static_agents = []
        _g._ghost_user_expert_agents = []
        _g._ghost_user_agent_slots = []
        _g._ghost_user_static_agent_slots = []
        _g._ghost_user_expert_agent_slots = []
        _g._ghost_removed_slots = set()
        _g._ghost_removed_static_slots = set()
        _g._ghost_removed_native_expert_idxs = set()
        _g._ghost_goal_overrides.clear()
        _g._ghost_agent_ids = []
        _g._ghost_agent_labels = []
        _g._ghost_native_agent_labels = []
        _g._ghost_native_static_count = 0
        _g._ghost_native_static_labels = []
        _g._ghost_native_expert_count = 0
        _g._ghost_native_expert_labels = []
        self.user_agent_count = 0
        self.user_static_agent_count = 0
        self.user_expert_count = 0
        self.demo_slots_used = 0
        self.demo_slots_total = 0
        self.agent_place_mode = False
        self.static_agent_place_mode = False
        self.expert_place_mode = False
        self.move_mode = False
        self.goal_edit_mode = False
        self.select_mode = False
        self.mirror_placement = False
        self.selected_goal_slot = -1
        self.frame_image = ""
        self.is_loaded = False
        self.is_playing = False
        self.is_busy = False
        self.current_frame = 0
        self.num_frames = 0
        self.progress_pct = "0%"
        self.policy_load_error = ""
        self.policy_is_random = False
        self._reset_selection_vars()
        self.agent_ids = []
        self.agent_sidebar_items = []
        self.static_sidebar_items = []
        self.expert_sidebar_items = []
        self.user_agent_items = []
        self.user_static_items = []
        self.ghost_env_active = False
        self.env_focus = "primary"
        self.ghost_agent_sidebar_items = []
        self.ghost_static_sidebar_items = []
        self.ghost_expert_sidebar_items = []
        self.ghost_native_expert_sidebar_items = []
        self.ghost_user_agent_count = 0
        self.ghost_user_static_agent_count = 0
        self.ghost_user_expert_count = 0
        self.ghost_user_agent_items = []
        self.ghost_user_static_items = []
        self.ghost_user_expert_items = []
        self.ghost_demo_slots_used = 0
        self.ghost_demo_slots_total = 0
        self.ghost_diverge_frame = 0
        self.ghost_diverge_pct = "0%"
        self.ghost_policy_load_error = ""
        self.ghost_policy_is_random = False

    def _soft_reset(self):
        """In-process teardown of backend + frontend state, back to a blank slate.

        Drops the primary and ghost envs and every cached frame/global, resets all
        UI state vars, and wipes all client-side canvas state. Used on every config
        change (where a stale env/frontend would otherwise cause glitches) and as the
        fallback for deep_reset when no supervising run.sh loop is present."""
        self._reset_playback()
        self.status = "Environment reset — select a map and press Load."
        yield rx.call_script(_deep_reset_js())

    def deep_reset(self):
        """Header Reset button: relaunch the whole app from scratch.

        Asks the supervising run.sh loop to restart the Python/reflex process — a
        genuinely fresh start (new interpreter, cleared globals) — WITHOUT rebuilding
        the C extension, which run.sh compiles once before the loop. The overlay JS
        polls the origin and reloads the page as soon as the new server answers.

        Falls back to an in-process teardown (_soft_reset) when PD_RESTART_SENTINEL is
        unset, e.g. when `reflex run` was started directly with no supervising loop."""
        yield from self._soft_reset()
        sentinel = os.environ.get("PD_RESTART_SENTINEL")
        if not sentinel:
            return
        self.status = "Restarting the app… the page will reload automatically."
        yield rx.call_script(_restart_wait_js())
        self._request_restart(sentinel)

    def _request_restart(self, sentinel: str):
        """Signal the supervising run.sh loop to relaunch, without rebuilding C.

        Touches the sentinel file the loop watches for, then — after a short delay so
        the 'restarting' event reaches the browser first — kills the `reflex run`
        process this backend runs inside. run.sh's foreground `reflex run` then
        returns, the loop sees the sentinel and re-launches (skipping the C build).

        We must terminate the *right* target: `reflex run` shares run.sh's process
        group (run.sh is the group leader), so a group kill would take run.sh down
        too. We therefore signal only the reflex process — unless it happens to be
        its own group leader (some setups detach it), in which case killing its group
        is safe and also reaps the bun frontend + any workers. SIGTERM first for a
        clean shutdown, then SIGKILL as a fallback since granian traps SIGINT as a
        worker *reload* rather than an exit."""
        try:
            with open(sentinel, "w") as fh:
                fh.write("restart\n")
        except OSError:
            return
        target = self._reflex_kill_target()
        if target is None:
            return
        # Detached in its own session so the kill below can't take it down, and it
        # outlives us long enough to escalate to SIGKILL if SIGTERM is ignored.
        subprocess.Popen(
            ["bash", "-c",
             f"sleep 1.5; kill -TERM {target} 2>/dev/null; "
             f"sleep 3; kill -KILL {target} 2>/dev/null"],
            start_new_session=True,
        )

    @staticmethod
    def _reflex_kill_target() -> str | None:
        """Return the kill target for the `reflex run` process this code runs in.

        Walks the ancestor chain for the top-most process whose cmdline contains
        'reflex run'. Returns '-<pid>' (a process group) when that process is its own
        group leader — safe to group-kill and it reaps children too — otherwise the
        bare '<pid>' so we never kill the shared run.sh group. None if not found."""
        def _read_cmd(pid: int) -> str:
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    return f.read().replace(b"\x00", b" ").decode(errors="replace")
            except OSError:
                return ""
        def _ppid(pid: int) -> int:
            try:
                with open(f"/proc/{pid}/stat", "rb") as f:
                    data = f.read()
                return int(data[data.rindex(b")") + 2:].split()[1])
            except (OSError, ValueError, IndexError):
                return 0
        master = None
        pid = os.getpid()
        for _ in range(32):
            if not pid or pid == 1:
                break
            if "reflex run" in _read_cmd(pid):
                master = pid
            pid = _ppid(pid)
        if master is None:
            return None
        try:
            if os.getpgid(master) == master:
                return f"-{master}"
        except OSError:
            pass
        return str(master)

    # ── tool switching ────────────────────────────────────────────────────────

    def set_tool_pan(self):
        self._reset_to_first_frame()
        self.goal_edit_mode = False
        self.agent_place_mode = False
        self.static_agent_place_mode = False
        self.expert_place_mode = False
        self.move_mode = False
        self.select_mode = False
        self.selected_agent_idx = -1
        self.selected_agent_str = "-1"
        self.selected_agent_label = ""
        return rx.call_script("if (window._pdSetTool) window._pdSetTool('pan');")

    def set_tool_select(self):
        self._reset_to_first_frame()
        self.goal_edit_mode = False
        self.agent_place_mode = False
        self.static_agent_place_mode = False
        self.expert_place_mode = False
        self.move_mode = False
        self.select_mode = True
        return rx.call_script("if (window._pdSetTool) window._pdSetTool('select');")

    # ── vehicle selection ─────────────────────────────────────────────────────

    def select_agent(self, idx):
        if self._just_removed:
            self._just_removed = False
            return
        self._reset_to_first_frame()
        i = int(idx) if not isinstance(idx, int) else idx
        if self.selected_agent_idx == i:
            # toggle off
            self.selected_agent_idx = -1
            self.selected_agent_str = "-1"
            self.selected_agent_label = ""
            return rx.call_script(
                "if(window._pdAgentRenderer){"
                "window._pdAgentRenderer.setSelected(-1);"
                "window._pdAgentRenderer.setSelectedStatic(-1);}"
                "if(window._pdRedraw)window._pdRedraw();"
            )
        # Mutually exclusive: clear every other selection, then set this one.
        self._reset_selection_vars()
        self.selected_agent_idx = i
        self.selected_agent_str = str(i)
        self.selected_agent_label = f"#{i}"
        self._enter_select_mode()
        # Pre-fill goal editor from current override if present
        _goal = _g._goal_overrides.get(i)
        if _goal is not None:
            self.goal_edit_x = f"{_goal[0]:.2f}"
            self.goal_edit_y = f"{_goal[1]:.2f}"
        else:
            self.goal_edit_x = ""
            self.goal_edit_y = ""
        return rx.call_script(
            f"(function(){{"
            f"if(window._pdSetTool)window._pdSetTool('select');"
            + _CLEAR_ALL_SELECT_JS
            + self._focus_env_js("primary")
            + self._ghost_link_js("agent", i)
            + f"if(window._pdAgentRenderer){{"
            f"window._pdAgentRenderer.setSelected({i});}}"
            f"if(window._pdRedraw)window._pdRedraw();"
            f"var el=document.getElementById('pd-agent-row-{i}');"
            f"if(el)el.scrollIntoView({{block:'nearest'}});"
            f"}})();"
        )

    def select_static_agent(self, slot_str):
        if self._just_removed:
            self._just_removed = False
            return
        self._reset_to_first_frame()
        if self.selected_static_slot_str == slot_str:
            # toggle off
            self.selected_static_slot_str = "-1"
            return rx.call_script(
                "if(window._pdAgentRenderer){"
                "window._pdAgentRenderer.setSelected(-1);"
                "window._pdAgentRenderer.setSelectedStatic(-1);}"
                "if(window._pdRedraw)window._pdRedraw();"
            )
        # Mutually exclusive: clear every other selection, then set this one.
        self._reset_selection_vars()
        self.selected_static_slot_str = slot_str
        self._enter_select_mode()
        slot = int(slot_str)
        return rx.call_script(
            f"(function(){{"
            f"if(window._pdSetTool)window._pdSetTool('select');"
            + _CLEAR_ALL_SELECT_JS
            + self._focus_env_js("primary")
            + self._ghost_link_js("static", slot)
            + f"if(window._pdAgentRenderer){{"
            f"window._pdAgentRenderer.setSelectedStatic({slot});}}"
            f"if(window._pdRedraw)window._pdRedraw();"
            f"var el=document.getElementById('pd-static-row-{slot}');"
            f"if(el)el.scrollIntoView({{block:'nearest'}});"
            f"}})();"
        )

    def _reset_selection_vars(self):
        """Reset every selection state var (primary + ghost) to its default.

        Used by all select_* setters so selection is fully mutually exclusive.
        """
        self.selected_agent_idx = -1
        self.selected_agent_str = "-1"
        self.selected_agent_label = ""
        self.selected_static_slot_str = "-1"
        self.selected_expert_idx = -1
        self.selected_expert_idx_str = "-1"
        self.selected_native_expert_idx = -1
        self.selected_native_expert_idx_str = "-1"
        self.selected_ghost_agent_idx = -1
        self.selected_ghost_agent_str = "-1"
        self.selected_ghost_static_slot_str = "-1"
        self.selected_ghost_expert_idx = -1
        self.selected_ghost_expert_idx_str = "-1"
        self.selected_ghost_native_expert_idx = -1
        self.selected_ghost_native_expert_idx_str = "-1"

    def _clear_tool_modes(self):
        """Clear every tool-mode boolean (back to the implicit pan tool).

        Keeps the server tool-mode booleans consistent with the JS tool so the
        toolbar buttons (e.g. Goal) don't require a double-click to re-activate."""
        self.goal_edit_mode = False
        self.select_mode = False
        self.agent_place_mode = False
        self.static_agent_place_mode = False
        self.expert_place_mode = False
        self.move_mode = False

    def _enter_select_mode(self):
        """Switch to select mode, clearing the other mutually-exclusive tool modes.

        Keeps the server tool-mode booleans consistent with the JS tool so the
        toolbar buttons (e.g. Goal) don't require a double-click to re-activate."""
        self._clear_tool_modes()
        self.select_mode = True

    def clear_selection(self):
        self._reset_selection_vars()
        yield rx.call_script(_CLEAR_ALL_SELECT_JS)

    def on_click_signal(self, signal: str):
        self._click_signal = ""
        if not signal or not _g._render_bounds:
            return
        parts = signal.split(",")
        if len(parts) != 2:
            return
        try:
            rel_x, rel_y = float(parts[0]), float(parts[1])
        except ValueError:
            return

        img_w = _g._render_bounds.get("img_w", 1)
        img_h = _g._render_bounds.get("img_h", 1)
        click_px = rel_x * img_w
        click_py = rel_y * img_h

        # In focus-ghost OVERLAY mode (single canvas), click-select targets the ghost env
        # instead of the primary env. Both envs share the same scenario/transform, so
        # click_px/click_py (derived from _render_bounds) hit-test directly against the
        # ghost data. In SIDE-BY-SIDE mode this signal only ever fires for the primary
        # (focus) canvas — ghost-canvas clicks route to on_ghost_click_signal — so it must
        # always hit-test the primary env regardless of the current env_focus.
        is_ghost = (
            self.env_focus == "ghost"
            and self.ghost_env_active
            and not self.ghost_side_by_side
        )
        agent_states = _g._ghost_agent_states if is_ghost else _g._agent_states
        agent_bounds = (_g._ghost_render_bounds or _g._render_bounds) if is_ghost else _g._render_bounds
        static_agents = _g._ghost_static_agents if is_ghost else _g._static_agents
        expert_frames = _g._ghost_expert_render_frames if is_ghost else _g._expert_render_frames
        user_expert_agents = _g._ghost_user_expert_agents if is_ghost else _g._user_expert_agents

        # Check active agents first.
        agent_idx = viewer.find_agent_at_pixel(
            click_px, click_py,
            self.current_frame, agent_states, agent_bounds,
        ) if agent_states else -1

        if agent_idx >= 0:
            if is_ghost:
                # Ghost select fully clears other selections and drives _pdGhostRenderer.
                yield self.select_ghost_agent(agent_idx)
                return
            # Active agent hit — clear every other selection, then set this one.
            self._reset_selection_vars()
            self.selected_agent_idx = agent_idx
            self.selected_agent_str = str(agent_idx)
            self.selected_agent_label = f"#{agent_idx}"
            yield rx.call_script(
                f"(function(){{"
                + _CLEAR_ALL_SELECT_JS
                + self._focus_env_js("primary")
                + self._ghost_link_js("agent", agent_idx)
                + f"if(window._pdAgentRenderer){{"
                f"window._pdAgentRenderer.setSelected({agent_idx});}}"
                f"if(window._pdRedraw)window._pdRedraw();"
                f"var el=document.getElementById('pd-agent-row-{agent_idx}');"
                f"if(el)el.scrollIntoView({{block:'nearest'}});"
                f"}})();"
            )
            return

        # Check static agents.
        static_slot = viewer.find_static_agent_at_pixel(
            click_px, click_py, static_agents,
        ) if static_agents else -1

        if static_slot >= 0:
            if is_ghost:
                yield self.select_ghost_static_agent(str(static_slot))
                return
            # Static agent hit — clear every other selection, then set this one.
            self._reset_selection_vars()
            self.selected_static_slot_str = str(static_slot)
            yield rx.call_script(
                f"(function(){{"
                + _CLEAR_ALL_SELECT_JS
                + self._focus_env_js("primary")
                + self._ghost_link_js("static", static_slot)
                + f"if(window._pdAgentRenderer){{"
                f"window._pdAgentRenderer.setSelectedStatic({static_slot});}}"
                f"if(window._pdRedraw)window._pdRedraw();"
                f"var el=document.getElementById('pd-static-row-{static_slot}');"
                f"if(el)el.scrollIntoView({{block:'nearest'}});"
                f"}})();"
            )
            return

        # Check expert agents (native first, then user-placed). Ghost user-experts are
        # routed by JS to pd-ghost-expert-click-signal; this path covers native experts.
        if expert_frames and self.current_frame < len(expert_frames):
            expert_frame = expert_frames[self.current_frame]
            frame_idx = viewer.find_expert_at_pixel(click_px, click_py, expert_frame)
            if frame_idx >= 0:
                n_total = len(expert_frame)
                n_user = len(user_expert_agents)
                user_idx = frame_idx - (n_total - n_user)
                # Both branches delegate to select_*, which fully clear other selections.
                if 0 <= user_idx < n_user:
                    if is_ghost:
                        yield self.select_ghost_expert(str(user_idx))
                    else:
                        yield from self.select_expert(str(user_idx))
                    return
                elif 0 <= frame_idx < n_total - n_user:
                    if is_ghost:
                        yield self.select_ghost_native_expert(str(frame_idx))
                    else:
                        yield self.select_native_expert(str(frame_idx))
                    return

        # Nothing hit — clear all selections.
        self._reset_selection_vars()
        yield rx.call_script(_CLEAR_ALL_SELECT_JS + "if(window._pdRedraw)window._pdRedraw();")

    def on_ghost_click_signal(self, signal: str):
        """Handle select-tool clicks originating on pd-ghost-canvas (side-by-side mode).
        Always targets the ghost environment regardless of env_focus."""
        self._ghost_click_signal = ""
        if not signal or not _g._render_bounds:
            return
        parts = signal.split(",")
        if len(parts) != 2:
            return
        try:
            rel_x, rel_y = float(parts[0]), float(parts[1])
        except ValueError:
            return
        if not self.ghost_env_active:
            return

        img_w = _g._render_bounds.get("img_w", 1)
        img_h = _g._render_bounds.get("img_h", 1)
        click_px = rel_x * img_w
        click_py = rel_y * img_h

        agent_states = _g._ghost_agent_states
        agent_bounds = _g._ghost_render_bounds or _g._render_bounds
        static_agents = _g._ghost_static_agents
        expert_frames = _g._ghost_expert_render_frames
        user_expert_agents = _g._ghost_user_expert_agents

        agent_idx = viewer.find_agent_at_pixel(
            click_px, click_py,
            self.current_frame, agent_states, agent_bounds,
        ) if agent_states else -1

        if agent_idx >= 0:
            yield self.select_ghost_agent(agent_idx)
            return

        static_slot = viewer.find_static_agent_at_pixel(
            click_px, click_py, static_agents,
        ) if static_agents else -1

        if static_slot >= 0:
            yield self.select_ghost_static_agent(str(static_slot))
            return

        if expert_frames and self.current_frame < len(expert_frames):
            expert_frame = expert_frames[self.current_frame]
            frame_idx = viewer.find_expert_at_pixel(click_px, click_py, expert_frame)
            if frame_idx >= 0:
                n_total = len(expert_frame)
                n_user = len(user_expert_agents)
                user_idx = frame_idx - (n_total - n_user)
                if 0 <= user_idx < n_user:
                    yield self.select_ghost_expert(str(user_idx))
                    return
                elif 0 <= frame_idx < n_total - n_user:
                    yield self.select_ghost_native_expert(str(frame_idx))
                    return

        self._reset_selection_vars()
        yield rx.call_script(_CLEAR_ALL_SELECT_JS + "if(window._pdRedraw)window._pdRedraw();")

    def select_expert(self, idx_str: str):
        if self._just_removed:
            self._just_removed = False
            return
        self._reset_to_first_frame()
        i = int(idx_str)
        if self.selected_expert_idx == i:
            self.selected_expert_idx = -1
            self.selected_expert_idx_str = "-1"
            yield rx.call_script(
                "window._pdSelectedExpertIdx = -1; window._pdSelectedExpertSlot = -1;"
                "if(window._pdAgentRenderer) window._pdAgentRenderer.setSelectedExpert(-1);"
                "if(window._pdRedraw) window._pdRedraw();"
            )
            return
        # Mutually exclusive: clear every other selection, then set this one.
        self._reset_selection_vars()
        self.selected_expert_idx = i
        self.selected_expert_idx_str = idx_str
        self._enter_select_mode()
        slot = _g._user_expert_agent_slots[i] if 0 <= i < len(_g._user_expert_agent_slots) else -1
        yield rx.call_script(
            f"if(window._pdSetTool)window._pdSetTool('select');"
            + _CLEAR_ALL_SELECT_JS
            + self._focus_env_js("primary")
            + self._ghost_link_js("expert", i)
            + f"window._pdSelectedExpertIdx = {i}; window._pdSelectedExpertSlot = {slot};"
            f"if(window._pdAgentRenderer){{"
            f"window._pdAgentRenderer.setSelectedExpert({slot});}}"
            f"if(window._pdRedraw) window._pdRedraw();"
            f"var el=document.getElementById('pd-user-expert-row-{i}');"
            f"if(el)el.scrollIntoView({{block:'nearest'}});"
        )

    def select_native_expert(self, idx_str: str):
        """Select a native (ground-truth) expert agent by its original index.

        idx_str is always the original (pre-filter) index stored in expert_sidebar_items.
        The JS render index is computed as the sequential position in the filtered array
        so that _pdSelectedNativeExpertIdx correctly indexes _pdExpertFrames.
        """
        if self._just_removed:
            self._just_removed = False
            return
        self._reset_to_first_frame()
        i = int(idx_str)
        # The sidebar index i is already the compacted position of this expert, which equals
        # its position in the native region of _pdExpertFrames — use it directly.
        render_idx = i if 0 <= i < _g._native_expert_count else -1
        if self.selected_native_expert_idx == i:
            self.selected_native_expert_idx = -1
            self.selected_native_expert_idx_str = "-1"
            return rx.call_script(
                "window._pdSelectedNativeExpertIdx = -1;"
                "if(window._pdRedraw)window._pdRedraw();"
            )
        # Mutually exclusive: clear every other selection, then set this one.
        self._reset_selection_vars()
        self.selected_native_expert_idx = i
        self.selected_native_expert_idx_str = idx_str
        self._enter_select_mode()
        return rx.call_script(
            f"if(window._pdSetTool)window._pdSetTool('select');"
            + _CLEAR_ALL_SELECT_JS
            + self._focus_env_js("primary")
            + f"window._pdSelectedNativeExpertIdx = {render_idx};"
            + self._ghost_link_js("native_expert", i)
            + f"if(window._pdRedraw)window._pdRedraw();"
            f"var el=document.getElementById('pd-native-expert-row-{i}');"
            f"if(el)el.scrollIntoView({{block:'nearest'}});"
        )

    # ── loading ───────────────────────────────────────────────────────────────

    async def load_map(self):
        # Dispatcher for the Load button. A saved-scene choice (★ entries in the Map dropdown)
        # re-applies a full scenario via the Import path — reloading its underlying map and
        # replaying every edit; any other choice is a real map binary loaded directly. Dispatch
        # on selected_map_choice (the displayed selection), which stays the ★ across the load,
        # rather than selected_map_path, which _apply_scenario repoints at the real map.
        if self.selected_map_choice.startswith("scenario://"):
            fname = self.selected_map_choice[len("scenario://"):]
            async for _ev in self.import_scenario_file(fname): yield _ev
            return
        async for _ev in self._load_map_impl(): yield _ev

    async def _load_map_impl(self):
        import asyncio
        _g._current_sim_steps = self.sim_steps

        # Deactivate ghost env when switching maps.
        if self.ghost_env_active:
            self.ghost_env_active = False
            self.env_focus = "primary"
            _g._ghost_env = None
            _g._ghost_policy = None
            _g._ghost_agent_render_frames = []
            _g._ghost_expert_render_frames = []
            _g._ghost_static_agents = []
            _g._ghost_map_data = {}
            _g._ghost_agent_states = []
            _g._ghost_agent_status_frames = []
            _g._ghost_render_bounds = {}
            _g._ghost_user_agents = []
            _g._ghost_user_static_agents = []
            _g._ghost_user_expert_agents = []
            _g._ghost_user_agent_slots = []
            _g._ghost_user_static_agent_slots = []
            _g._ghost_user_expert_agent_slots = []
            _g._ghost_removed_slots = set()
            _g._ghost_removed_static_slots = set()
            _g._ghost_goal_overrides.clear()
            _g._ghost_agent_ids = []
            _g._ghost_agent_labels = []
            self.ghost_agent_sidebar_items = []
            self.ghost_static_sidebar_items = []
            self.ghost_expert_sidebar_items = []
            self.ghost_user_agent_count = 0
            self.ghost_user_static_agent_count = 0
            self.ghost_user_expert_count = 0
            self.ghost_user_expert_items = []
            self.ghost_diverge_frame = 0
            self.ghost_diverge_pct = "0%"
            self.ghost_policy_load_error = ""
            self.ghost_policy_is_random = False
            yield rx.call_script(
                "window._pdEnvFocus = 'primary';"
                + _ghost_frames_clear_js()
            )

        use_demo_map = self.has_demo_maps
        map_path = self.selected_map_path

        if use_demo_map:
            if not map_path:
                self.status = "No map selected."
                return
            map_display = map_path
            for item in self.demo_maps:
                if item[1] == map_path:
                    map_display = item[0]
                    break
            map_id = None
        else:
            try:
                map_id = int(self.map_id_input)
            except ValueError:
                self.status = f"Invalid map ID: '{self.map_id_input}'"
                return
            self.selected_map = map_id
            map_display = str(map_id)

        # Reset all session data from the previous map before loading the new one.
        _g._user_agents = []
        _g._user_static_agents = []
        _g._user_expert_agents = []
        _g._user_agent_slots = []
        _g._user_static_agent_slots = []
        _g._user_expert_agent_slots = []
        _g._goal_overrides.clear()
        _g._removed_slots = set()
        _g._removed_static_slots = set()
        _g._removed_native_expert_idxs = set()
        _g._pending_static_detach_slots = set()
        _g._pending_expert_detach_idxs = set()
        _g._native_active_moves = {}
        _g._ghost_native_active_moves = {}
        _g._native_static_moves = {}
        _g._native_expert_moves = {}
        _g._ghost_native_static_moves = {}
        _g._ghost_native_expert_moves = {}
        _g._env_has_detaches = False
        self.user_agent_count = 0
        self.user_static_agent_count = 0
        self.user_expert_count = 0
        self.user_agent_items = []
        self.user_static_items = []
        self.user_expert_items = []
        self.agent_place_mode = False
        self.static_agent_place_mode = False
        self.expert_place_mode = False
        self.move_mode = False
        self.goal_edit_mode = False
        self.select_mode = False
        self.selected_goal_slot = -1
        self.selected_agent_str = "-1"
        self.selected_agent_label = ""
        self.selected_static_slot_str = "-1"
        self.selected_expert_idx = -1
        self.selected_expert_idx_str = "-1"
        self.selected_native_expert_idx = -1
        self.selected_native_expert_idx_str = "-1"
        yield rx.call_script("if (window._pdSetTool) window._pdSetTool('pan');")

        self.is_busy = True
        self.is_playing = False
        self.selected_agent_idx = -1
        self.status = f"Loading '{map_display}' and pre-rendering {self.sim_steps // _g.SAVE_EVERY + 1} frames…"
        yield

        try:
            policy_ini = self.selected_policy_config or None
            if use_demo_map:
                _g._env = viewer.create_env_from_path(map_path, episode_length=self.sim_steps, ini_path=policy_ini)
            else:
                data_root = viewer.get_data_root()
                _g._env = viewer.create_env(map_id, self.selected_split, data_root, episode_length=self.sim_steps, ini_path=policy_ini)
            _g._env.reset()
            _g._env.prepare_demo_slots()
            _g._lane_graph_cache = None  # new map — rebuild on first expert trajectory
            _used, _total = _g._env.get_demo_slots_info()
            self.demo_slots_used  = _used
            self.demo_slots_total = _total

            policy_path = self.selected_policy_path
            if policy_path:
                try:
                    _g._policy = viewer.load_policy_from_path(policy_path, _g._env, policy_ini)
                    self.policy_load_error = ""
                    self.policy_is_random = False
                except Exception as exc:
                    self.policy_load_error = str(exc)
                    self.policy_is_random = True
                    _g._policy = None
            else:
                self.policy_load_error = ""
                self.policy_is_random = True
                _g._policy = None

            _lm_env = _g._env
            _lm_policy = _g._policy
            _lm_steps = self.sim_steps
            _lm_loop = asyncio.get_running_loop()
            _lm_task = _lm_loop.run_in_executor(
                None,
                lambda: viewer.collect_frames(
                    _lm_env, num_steps=_lm_steps, save_every=_g.SAVE_EVERY, policy=_lm_policy
                )
            )
            while not _lm_task.done():
                _pct = min(int(viewer._resim_step / max(viewer._resim_total, 1) * 100), 99)
                _off = f"{69.115 * (1 - _pct / 100):.2f}"
                yield rx.call_script(
                    f"(function(){{var e=document.getElementById('pd-resim-ring');"
                    f"if(e)e.style.strokeDashoffset='{_off}';}})();"
                )
                await asyncio.sleep(0.08)
            (
                _g._agent_render_frames, _g._static_agents, _g._map_data,
                _g._agent_states, _g._agent_status_frames, _g._render_bounds,
                _g._expert_render_frames, _g._metrics,
            ) = _lm_task.result()
            yield rx.call_script(
                "var e=document.getElementById('pd-resim-ring');"
                "if(e)e.style.strokeDashoffset='0';"
            )
            _g._primary_actions = list(viewer._last_recorded_actions)
            _g._native_expert_count = len(_g._expert_render_frames[0]) if _g._expert_render_frames else 0
            _g._native_static_count = len(_g._static_agents)
            _g._user_static_expert_name_counter = _g._native_static_count + _g._native_expert_count
            self.num_frames = len(_g._agent_render_frames)
            if _g._agent_states:
                self.agent_ids = [i for i, v in enumerate(_g._agent_states[0]["valid"]) if v]
            if _g._agent_render_frames:
                # Record which slots the environment labeled "SDC" before replacing.
                _g._sdc_slots.clear()
                for entry in _g._agent_render_frames[0]:
                    if entry.get("id") == "SDC":
                        _g._sdc_slots.add(entry.get("slot", -1))
                # Replace "SDC" canvas IDs with the numeric slot so the canvas shows a number.
                for frame in _g._agent_render_frames:
                    for entry in frame:
                        if entry.get("id") == "SDC":
                            entry["id"] = str(entry.get("slot", entry["id"]))
                f0 = _g._agent_render_frames[0]
                self.agent_labels = [f0[k]["id"] if k < len(f0) else str(aid)
                                     for k, aid in enumerate(self.agent_ids)]
            # Snapshot stable labels for native agents at load time.  _g._native_agent_labels
            # mirrors active_agent_indices and is updated (pop) when slots are detached.
            _g._native_agent_labels = list(self.agent_labels)
            # Same for native statics: original slot number per array position, updated on detach.
            _g._native_static_labels = [e["id"] for e in _g._static_agents]
            # Track original expert index per current position so ghost env can replay detaches.
            _g._native_expert_orig_indices = list(range(_g._native_expert_count))
            # Snapshot stable expert labels (mirrors _native_static_labels). Popped on detach so
            # surviving experts keep their original number instead of being renumbered positionally.
            _g._native_expert_labels = [str(i + _g._native_static_count) for i in range(_g._native_expert_count)]
            # Initialize user-agent counter to continue after the highest numeric native label.
            numeric_labels = [int(lbl) for lbl in _g._native_agent_labels if lbl.lstrip("-").isdigit() and int(lbl) >= 0]
            _g._user_agent_name_counter = max(numeric_labels) + 1 if numeric_labels else 0
            # Patch goal position labels for SDC slots so the canvas goal marker shows a number.
            if _g._sdc_slots:
                viewer.initial_goal_positions = [
                    {**p, "label": str(p["slot"])} if p.get("slot") in _g._sdc_slots else p
                    for p in viewer.initial_goal_positions
                ]
            self.static_sidebar_items = [
                [str(e["slot"]), "default", "-1", e["id"]]
                for e in _g._static_agents
            ]
            self.expert_sidebar_items = [
                [_g._native_expert_labels[i], "default", str(i)] for i in range(len(_g._native_expert_labels))
            ]
            expert_labels = list(_g._native_expert_labels)
            if expert_labels and _g._expert_render_frames:
                _g._expert_render_frames = [
                    [
                        {**e, "id": lbl, "lx": round(e["cx"] + 2, 2), "ly": round(e["cy"] - 10, 2)}
                        for e, lbl in zip(frame, expert_labels)
                    ]
                    for frame in _g._expert_render_frames
                ]
            _g._original_frames_cache.update({
                "agent_render_frames": _g._agent_render_frames,
                "static_agents": _g._static_agents,
                "map_data": _g._map_data,
                "agent_states": _g._agent_states,
                "agent_status_frames": _g._agent_status_frames,
                "render_bounds": _g._render_bounds,
                "agent_ids": list(self.agent_ids),
                "agent_labels": list(self.agent_labels),
                "native_agent_labels": list(_g._native_agent_labels),
                "native_static_labels": list(_g._native_static_labels),
                "native_expert_orig_indices": list(_g._native_expert_orig_indices),
                "native_expert_labels": list(_g._native_expert_labels),
                "static_sidebar_items": list(self.static_sidebar_items),
                "initial_goal_positions": list(viewer.initial_goal_positions),
                "primary_actions": list(_g._primary_actions),
                "expert_render_frames": _g._expert_render_frames,
                "expert_sidebar_items": list(self.expert_sidebar_items),
                "native_static_count": _g._native_static_count,
                "native_expert_count": _g._native_expert_count,
                "user_agent_name_counter": _g._user_agent_name_counter,
                "user_static_expert_name_counter": _g._user_static_expert_name_counter,
            })
            self._set_frame(0)
            self.is_loaded = True
            self._sync_policy_flags()
            total_t = self._fmt_time(self.num_frames - 1)
            self.status = f"'{map_display}'  |  {self.num_frames} frames  |  {total_t}s total"
            yield rx.call_script("if (window._pdZoomReset) window._pdZoomReset();")
            yield rx.call_script(_goal_js(_compute_goal_positions()))
            yield rx.call_script(_agent_frames_js(_g._agent_render_frames, _g._static_agents, _g._map_data, _g._expert_render_frames, n_user_experts=len(_g._user_expert_agents)))
        except Exception as exc:
            self.status = f"Error: {exc}"
            _g._agent_render_frames = []
            _g._expert_render_frames = []
            _g._static_agents = []
            _g._map_data = {}
            _g._agent_states = []
            _g._agent_status_frames = []
            _g._render_bounds = {}
            _g._env = None
            self.is_loaded = False
        self.is_busy = False
        self.resim_progress = 0

    # ── scrubbing ─────────────────────────────────────────────────────────────

    def scrub(self, idx: int):
        self.is_playing = False
        self._set_frame(idx)
        yield rx.call_script("if(window._pdStopRaf)window._pdStopRaf();")
        # Dragging the timeline while placing an Agent, Static or Expert agent
        # exits the placement tool back to pan and clears any selection.
        if self.agent_place_mode or self.static_agent_place_mode or self.expert_place_mode:
            yield self.set_tool_pan()
            yield from self.clear_selection()

    def _reset_to_first_frame(self):
        """Stop playback and jump back to timestep 0 (canvas redraws via observer)."""
        if not self.is_loaded or self.num_frames == 0:
            return
        self.is_playing = False
        self._set_frame(0)

    def set_ghost_diverge(self, idx: int):
        self.ghost_diverge_frame = int(idx)
        total = max(self.num_frames - 1, 1)
        self.ghost_diverge_pct = f"{int(idx) / total * 100:.1f}%"
        yield from self.ghost_resimulate()

    # ── playback ──────────────────────────────────────────────────────────────

    def toggle_play(self):
        if not self.is_loaded:
            return
        if self.is_playing:
            self.is_playing = False
        else:
            if self.current_frame >= self.num_frames - 1:
                self._set_frame(0)
            self.selected_agent_idx = -1
            self.selected_agent_str = "-1"
            self.selected_agent_label = ""
            self.selected_static_slot_str = "-1"
            self.selected_expert_idx = -1
            self.selected_expert_idx_str = "-1"
            self.selected_native_expert_idx = -1
            self.selected_native_expert_idx_str = "-1"
            self.is_playing = True
            self.goal_edit_mode = False
            self.agent_place_mode = False
            self.static_agent_place_mode = False
            self.expert_place_mode = False
            self.select_mode = False
            yield rx.call_script(
                "if(window._pdSetTool)window._pdSetTool('pan');"
                "if(window._pdAgentRenderer){"
                "window._pdAgentRenderer.setSelected(-1);"
                "window._pdAgentRenderer.setSelectedStatic(-1);"
                "window._pdAgentRenderer.setSelectedExpert(-1);}"
                "window._pdSelectedExpertIdx=-1;"
                "window._pdSelectedNativeExpertIdx=-1;"
                "if(window._pdRedraw)window._pdRedraw();"
            )
            yield State.play_loop

    def toggle_loop(self):
        self.loop_enabled = not self.loop_enabled

    def step_back(self):
        if self.is_loaded and self.num_frames > 0:
            self.is_playing = False
            self._set_frame(max(0, self.current_frame - 1))
            return rx.call_script("if(window._pdStopRaf)window._pdStopRaf();")

    def step_forward(self):
        if self.is_loaded and self.num_frames > 0:
            self.is_playing = False
            self._set_frame(min(self.num_frames - 1, self.current_frame + 1))
            return rx.call_script("if(window._pdStopRaf)window._pdStopRaf();")

    def go_first_frame(self):
        if self.is_loaded and self.num_frames > 0:
            self.is_playing = False
            self._set_frame(0)
            return rx.call_script("if(window._pdStopRaf)window._pdStopRaf();")

    def go_last_frame(self):
        if self.is_loaded and self.num_frames > 0:
            self.is_playing = False
            self._set_frame(self.num_frames - 1)
            return rx.call_script("if(window._pdStopRaf)window._pdStopRaf();")

    # --- Policy status (badge / banner) ---

    def _sync_policy_flags(self):
        """Reconcile the per-session random-action flags with the live shared globals.

        The policy object actually driving the sim lives in module-level globals
        (_g._policy / _g._ghost_policy), shared across every Reflex session, while
        policy_is_random is per-session State. A page reload / second tab / reconnect
        resets the State bools but leaves _g._policy intact, so the banner and per-agent
        badges would otherwise disagree with what collect_frames really runs. Re-derive
        the flags from the globals so the UI always tells the truth. Only touches a flag
        when the corresponding env exists — before a map is loaded there is nothing to
        reconcile and the load paths own the flag."""
        if _g._env is not None:
            self.policy_is_random = _g._policy is None
        if self.ghost_env_active and _g._ghost_env is not None:
            self.ghost_policy_is_random = _g._ghost_policy is None

    @rx.var
    def selected_policy_display_name(self) -> str:
        """Label for the primary policy badge: the configured name, else the checkpoint
        filename stem, else 'default' — so a policy that loaded fine never shows the
        alarming grey 'fallback' pill just because it has no configured name."""
        if self.selected_policy_name:
            return self.selected_policy_name
        if self.selected_policy_path:
            return os.path.splitext(os.path.basename(self.selected_policy_path))[0]
        return "default"

    @rx.var
    def ghost_policy_display_name(self) -> str:
        """Label for the ghost policy badge (see selected_policy_display_name)."""
        if self.ghost_policy_name:
            return self.ghost_policy_name
        if self.ghost_policy_path:
            return os.path.splitext(os.path.basename(self.ghost_policy_path))[0]
        return "default"

    @staticmethod
    def _classify_policy_error(err: str) -> str:
        """Turn a raw load-error string into a compact, human reason for the banner, so
        an intermittent 'random actions' state is diagnosable at a glance rather than
        looking like mysterious nondeterminism."""
        if not err:
            return "no policy configured"
        low = err.lower()
        if any(s in low for s in ("no such file", "does not exist", "not found", "cannot find")):
            return "checkpoint not found"
        if any(s in low for s in ("size mismatch", "missing key", "unexpected key", "shape")):
            return "architecture mismatch"
        if any(s in low for s in ("weights_only", "weights only", "unpickl", "unsupported")):
            return "unreadable checkpoint"
        return "load error"

    @rx.var
    def policy_random_reason(self) -> str:
        return self._classify_policy_error(self.policy_load_error)

    @rx.var
    def ghost_policy_random_reason(self) -> str:
        return self._classify_policy_error(self.ghost_policy_load_error)

    # --- Debug computed vars ---

    @rx.var
    def dbg_env_loaded(self) -> bool:
        return _g._env is not None

    @rx.var
    def dbg_ghost_env_loaded(self) -> bool:
        return _g._ghost_env is not None

    @rx.var
    def dbg_policy_loaded(self) -> bool:
        return _g._policy is not None

    @rx.var
    def dbg_ghost_policy_loaded(self) -> bool:
        return _g._ghost_policy is not None

    @rx.var
    def dbg_frame_cache_size(self) -> int:
        if _g._agent_render_frames is None:
            return 0
        return len(_g._agent_render_frames)

    @rx.var
    def dbg_sim_steps(self) -> int:
        return _g._current_sim_steps or 0

    @_background
    async def play_loop(self):
        _ended = False
        while True:
            sleep_dur = 0.2
            async with self:
                if not self.is_playing or self.num_frames == 0:
                    break
                next_idx = self.current_frame + 1
                if next_idx >= self.num_frames:
                    if self.loop_enabled:
                        next_idx = 0
                    else:
                        # Natural end, no loop: stop at the last frame and halt the
                        # client rAF so the animation does NOT auto-repeat from 0.
                        self.is_playing = False
                        self._set_frame(self.num_frames - 1)
                        _ended = True
                        break
                self._set_frame(next_idx)
                sleep_dur = (_g.DT * _g.SAVE_EVERY) / max(self.play_speed, 0.1)
            await asyncio.sleep(sleep_dur)
        if _ended:
            yield rx.call_script("if(window._pdStopRaf)window._pdStopRaf();")


