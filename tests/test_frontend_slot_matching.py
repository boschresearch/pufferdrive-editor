# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""
Regression tests for the frontend slot-matching bug in demo/state/state.py.

Bug: _match_static_positions_to_slots() was called BEFORE filtering
_removed_static_slots from _g._static_agents.  When the user placed a demo
static at (or near) the same position as a previously-removed native static,
numpy.argmin() returned the NATIVE static's slot (lower index wins on ties)
instead of the DEMO static's slot.  The user label "U0" was therefore
assigned to the native slot — which was then filtered out — making the demo
static appear unlabelled and "unclaimed" in the sidebar.

Fix: filter _removed_static_slots BEFORE calling _match_static_positions_to_slots().
These tests verify that the corrected match function returns the demo slot
even when a removed native static is at the same position.
"""
import numpy as np
import pytest
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from demo.demo.utils.agent_math import _match_static_positions_to_slots


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_bounds(min_x=0.0, max_y=100.0, scale=1.0, img_w=100, img_h=100):
    return {"min_x": min_x, "max_y": max_y, "scale": scale, "img_w": img_w, "img_h": img_h}


def _make_static(slot: int, wx: float, wy: float, bounds: dict) -> dict:
    """Build a static_agents dict entry matching static_agent_data() format."""
    scale = bounds["scale"]
    min_x, max_y = bounds["min_x"], bounds["max_y"]
    cx = round((wx - min_x) * scale, 2)
    cy = round((max_y - wy) * scale, 2)
    return {"slot": slot, "id": str(slot), "cx": cx, "cy": cy,
            "heading": 0.0, "hl": 4.5, "hw": 2.0, "lx": cx + 2, "ly": cy - 10}


# ── tests ─────────────────────────────────────────────────────────────────────

def test_match_finds_demo_slot_when_no_collision():
    """Baseline: demo static is at a unique position, match returns its slot."""
    bounds = _make_bounds()
    native = [_make_static(i, float(i * 10), float(i * 10), bounds) for i in range(5)]
    demo   = _make_static(29, 55.0, 55.0, bounds)  # distinct position
    statics = native + [demo]

    user = [{"x": 55.0, "y": 55.0}]
    slots = _match_static_positions_to_slots(user, statics, bounds)
    assert slots == [29], f"expected [29], got {slots}"


def test_match_finds_demo_slot_not_removed_native_at_same_position():
    """
    Bug scenario: removed native static at same position as demo static.
    Without the fix the match returned the native slot (lower index wins).
    With the fix (filter BEFORE match) only the demo slot is a candidate.
    """
    bounds = _make_bounds()
    SAME_X, SAME_Y = 40.0, 60.0

    # Native statics 0-4; slot 3 is at the same position as the demo static.
    native = [_make_static(i, float(i * 10), float(i * 10), bounds) for i in range(3)]
    native_removed = _make_static(3, SAME_X, SAME_Y, bounds)   # slot 3 — was removed
    native_after  = _make_static(4, 80.0, 80.0, bounds)
    demo = _make_static(29, SAME_X, SAME_Y, bounds)             # slot 29 — user placed here

    removed_slots = {3}  # simulates _g._removed_static_slots

    # PRE-FIX behaviour: passing unfiltered list → argmin returns slot 3 (wrong)
    unfiltered = native + [native_removed, native_after, demo]
    slots_wrong = _match_static_positions_to_slots([{"x": SAME_X, "y": SAME_Y}], unfiltered, bounds)
    assert slots_wrong[0] == 3, (
        "Pre-fix sanity check: argmin should prefer the lower native slot on a tie; "
        f"got {slots_wrong[0]}"
    )

    # POST-FIX behaviour: filtering removed statics first → match returns slot 29 (correct)
    filtered = [e for e in unfiltered if e["slot"] not in removed_slots]
    slots_correct = _match_static_positions_to_slots([{"x": SAME_X, "y": SAME_Y}], filtered, bounds)
    assert slots_correct[0] == 29, (
        f"Post-fix: expected demo slot 29 after removing native slot 3 from candidates; "
        f"got {slots_correct[0]}"
    )


def test_match_finds_demo_slot_near_removed_native():
    """Demo static is within 5 px of a removed native; must match demo slot after filter."""
    bounds = _make_bounds(scale=5.0)  # 5 px/m

    native_at = (20.0, 30.0)
    demo_at   = (20.5, 30.0)  # 0.5 m off (2.5 px)

    native = [_make_static(i, float(i * 100), float(i * 100), bounds) for i in range(5)]
    native_removed = _make_static(5, *native_at, bounds)   # slot 5 — removed
    demo = _make_static(29, *demo_at, bounds)              # slot 29 — user placed

    removed_slots = {5}
    all_statics = native + [native_removed, demo]
    filtered    = [e for e in all_statics if e["slot"] not in removed_slots]

    slots = _match_static_positions_to_slots([{"x": demo_at[0], "y": demo_at[1]}], filtered, bounds)
    assert slots == [29], f"expected [29], got {slots}"


def test_match_multiple_demo_statics_correct_slots():
    """Two demo statics placed at different positions; both get correct slots after filter."""
    bounds = _make_bounds(scale=2.0)

    native = [_make_static(i, float(i * 50), 0.0, bounds) for i in range(5)]
    demo0 = _make_static(29, 11.0, 11.0, bounds)
    demo1 = _make_static(30, 77.0, 77.0, bounds)
    removed_slots = set()

    all_statics = native + [demo0, demo1]
    filtered = [e for e in all_statics if e["slot"] not in removed_slots]

    user = [{"x": 11.0, "y": 11.0}, {"x": 77.0, "y": 77.0}]
    slots = _match_static_positions_to_slots(user, filtered, bounds)
    assert slots == [29, 30], f"expected [29, 30], got {slots}"


def test_match_demo_slot_when_two_natives_removed():
    """Two removed native statics (including one at demo position); demo slot wins."""
    bounds = _make_bounds()
    DEMO_X, DEMO_Y = 50.0, 50.0

    native = [_make_static(i, float(i * 10), 0.0, bounds) for i in range(5)]
    removed_a = _make_static(5, DEMO_X, DEMO_Y, bounds)   # at demo position
    removed_b = _make_static(6, 70.0, 70.0, bounds)
    demo = _make_static(29, DEMO_X, DEMO_Y, bounds)

    removed_slots = {5, 6}
    all_statics = native + [removed_a, removed_b, demo]
    filtered = [e for e in all_statics if e["slot"] not in removed_slots]

    slots = _match_static_positions_to_slots([{"x": DEMO_X, "y": DEMO_Y}], filtered, bounds)
    assert slots == [29], f"expected [29], got {slots}"
