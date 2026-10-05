# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""Module-level simulation cache shared across all submodules.

All mutable simulation state lives here. Submodules that need to read or write
these values should import the module itself and access attributes:

    from demo.demo import globals as _g
    _g._env = new_env          # mutation
    if _g._env is not None:    # read
        ...
"""
from . import viewer

# ── Server-side simulation cache ──────────────────────────────────────────────
_agent_render_frames: list[list[dict]] = []
_expert_render_frames: list[list[dict]] = []
_static_agents: list[dict] = []
_map_data: dict = {}
_env = None
_policy = None
_goal_overrides: dict[int, tuple[float, float]] = {}  # slot → (world_x, world_y)

MAX_AGENTS = 32  # hard cap from C; matches drive.h MAX_AGENTS
INVALID_POS = -10000.0  # out-of-range sentinel for unused reserved slots

_user_agents: list[dict] = []
_user_agent_name_counter: int = 0
_user_static_agents: list[dict] = []
_user_expert_agents: list[dict] = []
_user_static_expert_name_counter: int = 0
_user_agent_slots: list[int] = []
_user_static_agent_slots: list[int] = []
_user_expert_agent_slots: list[int] = []
_native_agent_labels: list[str] = []
_native_static_labels: list[str] = []
_native_expert_orig_indices: list[int] = []  # original index per current expert position, for ghost replay
_native_expert_labels: list[str] = []  # stable label per current expert position (mirrors _native_static_labels)
_removed_slots: set[int] = set()
_removed_static_slots: set[int] = set()
_removed_native_expert_idxs: set[int] = set()
# Pending C-level detaches applied once per resimulate, then cleared.
# Unlike the display-filter sets above these map to CURRENT array indices
# so they must be consumed before the array shifts.
_pending_static_detach_slots: set[int] = set()
_pending_expert_detach_idxs: set[int] = set()
# True once any native agent (active/static/expert) has been permanently detached
# at the C level. c_detach_* zeroes the entity trajectory, so the only way to bring
# the agent back on Reset is to recreate the env from the map file.
_env_has_detaches: bool = False
# Move tool: native active agents repositioned in place via teleport_agent, replayed
# each resimulate so the agent keeps its original slot/ID. {slot: (x, y, heading, goal_x, goal_y)}
_native_active_moves: dict = {}
_ghost_native_active_moves: dict = {}  # ghost-specific native active teleports; merged with _native_active_moves
# Move tool for native statics/experts: repositioned in place (teleport), keyed by STABLE
# LABEL so the current C index can be re-derived each resimulate. Statics map label→(x,y,heading);
# experts map label→ea-dict (recomputed to a lane-snapped trajectory each resimulate).
_native_static_moves: dict = {}
_native_expert_moves: dict = {}
_ghost_native_static_moves: dict = {}
_ghost_native_expert_moves: dict = {}
_sdc_slots: set[int] = set()
_current_sim_steps: int = 91
_native_expert_count: int = 0
_native_static_count: int = 0
_agent_states: list[dict] = []
_agent_status_frames: list[list[str]] = []
_render_bounds: dict = {}
_original_frames_cache: dict = {}
_lane_graph_cache: tuple | None = None

# ── Ghost ("secondary") environment ──────────────────────────────────────────
_ghost_env = None
_ghost_policy = None
_ghost_agent_render_frames: list[list[dict]] = []
_ghost_expert_render_frames: list[list[dict]] = []
_ghost_static_agents: list[dict] = []
_ghost_map_data: dict = {}
_ghost_agent_states: list[dict] = []
_ghost_agent_status_frames: list[list[str]] = []
_ghost_render_bounds: dict = {}
_ghost_user_agents: list[dict] = []
_ghost_user_static_agents: list[dict] = []
_ghost_user_expert_agents: list[dict] = []
_ghost_user_agent_slots: list[int] = []
_ghost_user_static_agent_slots: list[int] = []
_ghost_user_expert_agent_slots: list[int] = []
_ghost_removed_slots: set[int] = set()
_ghost_removed_static_slots: set[int] = set()
_ghost_removed_native_expert_idxs: set[int] = set()
_ghost_goal_overrides: dict[int, tuple[float, float]] = {}
_ghost_agent_ids: list[int] = []
_ghost_agent_labels: list[str] = []
_ghost_native_agent_labels: list[str] = []
# Ghost-owned snapshot of the native static/expert baseline, captured at activation.
# The ghost env replays the main env's permanent detaches once at activation, then stays
# independent — so it must NOT read the shared _native_static_*/_native_expert_* globals,
# which the main env keeps popping/decrementing on every later detach. Reading those would
# make a main-env removal also disappear from the (otherwise independent) ghost env.
_ghost_native_static_count: int = 0
_ghost_native_static_labels: list[str] = []
_ghost_native_expert_count: int = 0
_ghost_native_expert_labels: list[str] = []
_primary_actions: list = []
_metrics: dict = {}
_ghost_metrics: dict = {}

# ── Render / timing constants ─────────────────────────────────────────────────
DT = 0.1
SAVE_EVERY = viewer.load_render_every()
NUM_STEPS = 91
_render_style = viewer.load_render_style()
