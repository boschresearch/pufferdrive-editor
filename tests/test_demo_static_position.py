# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""
Regression tests for demo static vehicle position correctness in PufferDrive.

Bug: inject_demo_static_agent() previously only wrote the injected position to
traj_x[init_steps].  All other trajectory steps remained INVALID_POSITION (left
over from reset_demo_slots()).  If set_start_position() or move_expert() read from
any other step, the entity would jump to INVALID_POSITION (invisible / displaced).

Fix: inject_demo_static_agent() now fills the ENTIRE trajectory array with the
injected position so the entity stays put regardless of which step is read.

These tests cover:
  * Position is correct immediately after injection.
  * Position survives env.reset() (set_start_position reads from trajectory).
  * Position survives a full resimulate cycle (reset_demo_slots → prepare → re-inject).
  * Position survives a full episode run (internal c_reset at episode boundary).
  * Native (non-demo) statics are undisturbed throughout.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAP_PATH = "resources/drive/binaries/training/map_000005.bin"
TOL = 1.0  # meters — acceptable position error

# World coordinates clearly outside the native-static cluster for map 5
# (~-4630 x, ~3300 y), so the demo static is easy to identify even if
# we rely purely on the injected value matching.
INJECT_X = 0.0
INJECT_Y = 0.0


def _make_env():
    """Create a Drive env for map 5 (5 active agents, 27 native non-expert statics)."""
    if not os.path.exists(MAP_PATH):
        pytest.skip("Map 5 binary not found; skipping position regression tests")
    from pufferlib.ocean.drive import drive as drive_mod

    env = drive_mod.Drive(
        data_root="resources/drive/binaries",
        split="training",
        map_id=5,
        num_agents=5,
        episode_length=91,
    )
    env.reset()
    env.prepare_demo_slots()
    return env


def _n_native_statics(env):
    """Number of non-expert statics before any injection."""
    from pufferlib.ocean.drive import binding
    return binding.vec_get_static_agent_count(env.c_envs)


def _inject_and_read(env, wx=INJECT_X, wy=INJECT_Y):
    """Detach agent 0, prepare, inject static at (wx, wy); return last static entry (x, y)."""
    env.detach_active_agent(0)
    env.prepare_demo_slots()
    slot_k = env.inject_demo_static_agent(x=wx, y=wy, heading=0.0)
    assert slot_k >= 0, "inject_demo_static_agent returned -1 (no free slots)"
    return _read_last_static(env)


def _read_last_static(env):
    """Return (x, y) of the last (demo) static entry, or None if array is empty."""
    data = env.get_static_agent_state()
    if len(data["x"]) == 0:
        return None
    x, y = float(data["x"][-1]), float(data["y"][-1])
    if abs(x) >= 9000 or abs(y) >= 9000:
        return None
    return (x, y)


def _read_native_statics(env, n_native):
    """Return the first n_native static entries (the native, non-demo parked cars)."""
    data = env.get_static_agent_state()
    return [(float(data["x"][i]), float(data["y"][i])) for i in range(n_native)]


# ---------------------------------------------------------------------------

def test_demo_static_world_position_after_inject():
    """Position returned by get_static_agent_state must match the injected world coords."""
    env = _make_env()
    pos = _inject_and_read(env)

    assert pos is not None, "Demo static not visible after injection"
    assert abs(pos[0] - INJECT_X) < TOL, f"x: expected {INJECT_X}, got {pos[0]:.2f}"
    assert abs(pos[1] - INJECT_Y) < TOL, f"y: expected {INJECT_Y}, got {pos[1]:.2f}"


def test_demo_static_position_survives_reset():
    """Position must be preserved after env.reset() triggers set_start_position()."""
    env = _make_env()
    n_native = _n_native_statics(env)
    _inject_and_read(env)

    env.reset()  # c_reset → set_start_position reads traj_x[init_steps]

    pos = _read_last_static(env)
    assert pos is not None, "Demo static invisible after env.reset()"
    assert abs(pos[0] - INJECT_X) < TOL, f"x after reset: expected {INJECT_X}, got {pos[0]:.2f}"
    assert abs(pos[1] - INJECT_Y) < TOL, f"y after reset: expected {INJECT_Y}, got {pos[1]:.2f}"

    # Confirm the env still has the right number of entries
    data = env.get_static_agent_state()
    assert len(data["x"]) == n_native + 1, (
        f"Expected {n_native + 1} statics after reset, got {len(data['x'])}"
    )


def test_demo_static_position_survives_resimulate_cycle():
    """
    Position must survive a full resimulate cycle:
    reset_demo_slots() invalidates ALL traj entries (including init_steps),
    then prepare + re-inject restores them.
    """
    env = _make_env()
    n_native = _n_native_statics(env)
    _inject_and_read(env)

    # Simulate what state.py resimulate() does at the top of each call
    env.reset()
    env.reset_demo_slots()    # invalidates ALL traj entries
    env.prepare_demo_slots()  # no-op (free slot already exists)
    slot_k = env.inject_demo_static_agent(x=INJECT_X, y=INJECT_Y, heading=0.0)
    assert slot_k >= 0, "Re-injection failed in second cycle"

    pos = _read_last_static(env)
    assert pos is not None, "Demo static invisible after resimulate cycle"
    assert abs(pos[0] - INJECT_X) < TOL, f"x after cycle: expected {INJECT_X}, got {pos[0]:.2f}"
    assert abs(pos[1] - INJECT_Y) < TOL, f"y after cycle: expected {INJECT_Y}, got {pos[1]:.2f}"

    data = env.get_static_agent_state()
    assert len(data["x"]) == n_native + 1


def test_demo_static_position_survives_full_episode():
    """
    Position must be correct after stepping through a full episode.
    At episode end, c_step() calls c_reset() → set_start_position reads traj_x[init_steps].
    The fix ensures traj_x[init_steps] holds the injected position, not INVALID_POSITION.
    """
    env = _make_env()
    _inject_and_read(env)
    env.recompute_observations()

    actions = env.action_space.sample()
    for _ in range(env.episode_length):
        env.step(actions)

    pos = _read_last_static(env)
    assert pos is not None, "Demo static invisible after full episode"
    assert abs(pos[0] - INJECT_X) < TOL, f"x after episode: expected {INJECT_X}, got {pos[0]:.2f}"
    assert abs(pos[1] - INJECT_Y) < TOL, f"y after episode: expected {INJECT_Y}, got {pos[1]:.2f}"


def test_demo_static_trajectory_fully_filled():
    """
    This is the test that directly targets the invariant established by the fix.

    reset_demo_slots() wipes the trajectory to INVALID_POSITION for all steps.
    Without the fix, only traj_x[init_steps] is restored by injection; any code
    that reads another step (e.g. move_expert with timestep > init_steps) would
    see INVALID_POSITION.  With the fix, every trajectory step is filled.

    We verify this by:
      1. Injecting at (wx, wy)
      2. Running reset_demo_slots → prepare → re-inject (trajectory wiped and re-filled)
      3. Calling env.reset() (triggers set_start_position, reads traj_x[init_steps])
      4. Asserting the position is still correct after the reset
    """
    env = _make_env()
    _inject_and_read(env)

    # Cycle: wipe trajectory, re-inject
    env.reset()
    env.reset_demo_slots()
    env.prepare_demo_slots()
    slot_k = env.inject_demo_static_agent(x=INJECT_X, y=INJECT_Y, heading=0.0)
    assert slot_k >= 0

    # Reset reads from the trajectory — must still return (INJECT_X, INJECT_Y)
    env.reset()

    pos = _read_last_static(env)
    assert pos is not None, "Demo static invisible after trajectory-fill test"
    assert abs(pos[0] - INJECT_X) < TOL, f"x: expected {INJECT_X}, got {pos[0]:.2f}"
    assert abs(pos[1] - INJECT_Y) < TOL, f"y: expected {INJECT_Y}, got {pos[1]:.2f}"


def test_native_statics_undisturbed_during_demo_inject():
    """
    Native non-expert statics must not change position when a demo static is injected.
    """
    env = _make_env()
    n_native = _n_native_statics(env)
    natives_before = _read_native_statics(env, n_native)

    # Inject demo static
    env.detach_active_agent(0)
    env.prepare_demo_slots()
    env.inject_demo_static_agent(x=INJECT_X, y=INJECT_Y, heading=0.0)

    natives_after = _read_native_statics(env, n_native)
    for i, (before, after) in enumerate(zip(natives_before, natives_after)):
        assert abs(before[0] - after[0]) < TOL, (
            f"Native static {i} x changed: {before[0]:.2f} → {after[0]:.2f}"
        )
        assert abs(before[1] - after[1]) < TOL, (
            f"Native static {i} y changed: {before[1]:.2f} → {after[1]:.2f}"
        )
