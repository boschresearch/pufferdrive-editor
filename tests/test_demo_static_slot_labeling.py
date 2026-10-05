# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""
Regression tests for demo static slot labeling in PufferDrive.

Bug: In a full environment (active_agent_count == num_agents), all non-active
entities become expert_static (mark_as_expert=1).  After detaching one active
agent and injecting a demo static, c_get_static_agent_state returns the demo
static at C output index 0.  In state.py, expert labels are computed as
str(i + _native_static_count); in a full env _native_static_count=0, so
expert 0 is labelled "0" — same as the demo static's slot 0.  Both the new
demo static and the original expert 0 display with label "0".

Fix: state.py remaps demo-static slots to start above the expert label range
(_native_static_count + _native_expert_count).

These tests cover:
  * C-level: native statics keep their array positions after demo injection.
  * C-level: demo statics are always appended after native statics.
  * Unit:    the remap logic places demo slots above the expert range without
             disturbing native-static or expert labels.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAP_PATH = "resources/drive/binaries/training/map_000005.bin"


def _make_env():
    """Create a fresh Drive env for map 5 training split."""
    if not os.path.exists(MAP_PATH):
        pytest.skip("Map 5 binary not found; skipping slot-labeling regression")
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


def _static_valid_slots(env):
    """Return C output indices for valid non-expert statics."""
    data = env.get_static_agent_state()
    return [i for i, x in enumerate(data["x"]) if abs(float(x)) < 9000]


def _expert_count(env):
    """Return number of currently visible expert agents."""
    data = env.get_expert_agent_state()
    return int(np.sum(np.abs(data["x"]) < 9000))


# ---------------------------------------------------------------------------
# C-level structural tests: verify array invariants hold at the C layer.
# ---------------------------------------------------------------------------

def test_native_static_slots_unchanged_after_demo_inject():
    """Injecting a demo static must not shift the slot indices of native statics.

    Demo statics are appended at the end of static_agent_indices in C, so the
    native entries must always appear at the same out_idx positions.
    """
    env = _make_env()

    slots_before = _static_valid_slots(env)

    # Free one slot and inject a demo static.
    env.detach_active_agent(0)
    env.prepare_demo_slots()
    slot_k = env.inject_demo_static_agent(x=0.0, y=0.0, heading=0.0)
    assert slot_k >= 0, "inject_demo_static_agent failed — no free demo slots"

    slots_after = _static_valid_slots(env)
    prefix = slots_after[: len(slots_before)]

    assert prefix == slots_before, (
        f"Native static slot indices shifted after demo inject. "
        f"Before: {slots_before}, after (prefix): {prefix}"
    )


def test_demo_static_appended_after_native_statics():
    """The demo static's C output index must be strictly greater than all native slots."""
    env = _make_env()

    n_native = len(_static_valid_slots(env))

    env.detach_active_agent(0)
    env.prepare_demo_slots()
    slot_k = env.inject_demo_static_agent(x=0.0, y=0.0, heading=0.0)
    assert slot_k >= 0

    slots_after = _static_valid_slots(env)
    demo_raw_slot = slots_after[-1]  # demo is always last

    assert demo_raw_slot == n_native, (
        f"Expected demo static at C output index {n_native} (after {n_native} native statics), "
        f"got {demo_raw_slot}. slots_after={slots_after}"
    )


def test_two_demo_statics_appended_consecutively():
    """Two injected demo statics should appear at consecutive slots after native statics."""
    env = _make_env()

    n_native = len(_static_valid_slots(env))

    # Free two active slots.
    env.detach_active_agent(0)
    env.detach_active_agent(0)   # slot 0 again after left-shift
    env.prepare_demo_slots()

    s0 = env.inject_demo_static_agent(x=1.0, y=0.0, heading=0.0)
    s1 = env.inject_demo_static_agent(x=2.0, y=0.0, heading=0.0)
    assert s0 >= 0 and s1 >= 0, f"Demo static injection failed: s0={s0}, s1={s1}"

    slots_after = _static_valid_slots(env)
    demo_slots = slots_after[n_native:]

    assert demo_slots == [n_native, n_native + 1], (
        f"Expected two demo statics at consecutive C slots [{n_native}, {n_native+1}], "
        f"got {demo_slots}"
    )


# ---------------------------------------------------------------------------
# Unit tests: verify the state.py slot-remap logic in isolation.
# ---------------------------------------------------------------------------

def _apply_remap(static_agents, native_static_count, native_expert_count):
    """Mirror the remap block from state.py resimulate()."""
    expert_base = native_static_count + native_expert_count
    for e in static_agents:
        raw = e.get("slot", -1)
        if native_static_count <= raw < expert_base:
            demo_pos = raw - native_static_count
            new_slot = expert_base + demo_pos
            e["slot"] = new_slot
            e["id"] = str(new_slot)
    return static_agents


def test_remap_full_env_no_native_statics():
    """Full env: 0 native statics, 27 experts.  Demo static slot 0 → remapped to 27."""
    S, E = 0, 27
    agents = [{"slot": 0, "id": "0"}]
    _apply_remap(agents, S, E)

    assert agents[0]["slot"] == 27
    assert agents[0]["id"] == "27"
    assert agents[0]["slot"] not in range(S, S + E)


def test_remap_partial_env_with_native_statics():
    """Partial env: 3 native statics, 10 experts.  Demo static slot 3 → remapped to 13."""
    S, E = 3, 10
    native = [{"slot": i, "id": str(i)} for i in range(S)]
    demo = [{"slot": S, "id": str(S)}]
    all_agents = native + demo

    _apply_remap(all_agents, S, E)

    # Native statics must be unchanged.
    for i, a in enumerate(native):
        assert a["slot"] == i, f"Native static {i} slot changed to {a['slot']}"

    # Demo static must land above the expert range.
    assert demo[0]["slot"] == S + E  # 3 + 10 = 13
    assert demo[0]["slot"] not in range(S, S + E)


def test_remap_multiple_demo_statics():
    """Two demo statics should be placed consecutively above expert range."""
    S, E = 2, 5
    native = [{"slot": i, "id": str(i)} for i in range(S)]
    demos = [{"slot": S, "id": str(S)}, {"slot": S + 1, "id": str(S + 1)}]
    all_agents = native + demos

    _apply_remap(all_agents, S, E)

    expert_range = set(range(S, S + E))
    for d in demos:
        assert d["slot"] not in expert_range, (
            f"Demo static slot {d['slot']} still in expert range {expert_range}"
        )

    # Slots should be consecutive starting at S+E.
    demo_slots = [d["slot"] for d in demos]
    assert demo_slots == [S + E, S + E + 1]


def test_remap_no_experts_no_collision_needed():
    """If there are no experts, demo statics follow native statics with no gap required."""
    S, E = 3, 0
    native = [{"slot": i, "id": str(i)} for i in range(S)]
    demo = [{"slot": S, "id": str(S)}]
    all_agents = native + demo

    _apply_remap(all_agents, S, E)

    # With E=0, expert_base == S; demo slot S stays S — no overlap since there are no experts.
    assert demo[0]["slot"] == S
    assert native == [{"slot": i, "id": str(i)} for i in range(S)]


def test_remap_is_idempotent():
    """Applying remap twice must not further shift an already-remapped slot."""
    S, E = 0, 27
    agents = [{"slot": 0, "id": "0"}]
    _apply_remap(agents, S, E)
    first_slot = agents[0]["slot"]

    _apply_remap(agents, S, E)
    assert agents[0]["slot"] == first_slot, (
        "Second application of remap changed slot from "
        f"{first_slot} to {agents[0]['slot']}"
    )
