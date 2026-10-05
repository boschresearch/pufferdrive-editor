# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""Tests for viewer.py functions that need an environment.

Uses a lightweight MockEnv — no real map files, no C++ bindings, no GPU.
"""

import os
import sys

import numpy as np
import pytest

_VIEWER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo", "demo")
sys.path.insert(0, _VIEWER_DIR)
import viewer


# ── Mock environment ──────────────────────────────────────────────────────────

N = 4  # number of agents in the mock


class _MockActionSpace:
    def sample(self):
        return np.zeros((N, 1), dtype=np.int64)


class MockEnv:
    """Minimal environment stub that satisfies viewer.py's call sites."""

    def __init__(self, n: int = N):
        self._n = n
        # Two obs columns are enough: viewer._goal_positions reads obs[:,0] and obs[:,1]
        self.observations = np.zeros((n, 4), dtype=np.float32)
        self.action_space = _MockActionSpace()

        xs = np.linspace(10.0, 40.0, n, dtype=np.float32)
        ys = np.linspace(10.0, 40.0, n, dtype=np.float32)
        self._agent_state = {
            "x": xs,
            "y": ys,
            "heading": np.zeros(n, dtype=np.float32),
            "length": np.full(n, 4.5, dtype=np.float32),
            "width": np.full(n, 2.0, dtype=np.float32),
            "id": np.arange(n, dtype=np.int64),
        }

    def get_global_agent_state(self) -> dict:
        return {k: v.copy() for k, v in self._agent_state.items()}

    def get_expert_agent_state(self) -> dict:
        empty = np.array([], dtype=np.float32)
        return {"x": empty, "y": empty, "heading": empty,
                "length": empty, "width": empty, "id": np.array([], dtype=np.int64)}

    def get_road_edge_polylines(self) -> dict:
        return {
            "x": np.array([0.0, 50.0, 50.0], dtype=np.float32),
            "y": np.array([0.0, 0.0, 50.0], dtype=np.float32),
            "lengths": np.array([3], dtype=np.int32),
        }

    def get_lane_polylines(self) -> dict:
        return {
            "x": np.array([0.0, 50.0], dtype=np.float32),
            "y": np.array([5.0, 5.0], dtype=np.float32),
            "lengths": np.array([2], dtype=np.int32),
        }

    @property
    def num_agents(self) -> int:
        return self._n

    def step(self, actions) -> None:
        pass  # stateless — each step returns the same scene


class MockPolicy:
    """Deterministic policy that always outputs action 0."""
    is_continuous = False

    def __call__(self, obs):
        import torch
        logits = torch.zeros(obs.shape[0], 91)
        return logits, {}


@pytest.fixture
def env():
    return MockEnv()


@pytest.fixture
def bounds(env):
    b = viewer.compute_render_bounds(env)
    assert b is not None, "compute_render_bounds returned None for MockEnv"
    return b


# ── compute_render_bounds ─────────────────────────────────────────────────────

class TestComputeRenderBounds:
    def test_returns_dict_with_required_keys(self, env):
        b = viewer.compute_render_bounds(env)
        assert b is not None
        for key in ("min_x", "max_x", "min_y", "max_y", "scale", "img_w", "img_h"):
            assert key in b, f"missing key: {key}"

    def test_positive_dimensions(self, env):
        b = viewer.compute_render_bounds(env)
        assert b["img_w"] > 0
        assert b["img_h"] > 0
        assert b["scale"] > 0

    def test_bounds_contain_agents(self, env):
        b = viewer.compute_render_bounds(env)
        state = env.get_global_agent_state()
        for x in state["x"]:
            assert b["min_x"] <= x <= b["max_x"]
        for y in state["y"]:
            assert b["min_y"] <= y <= b["max_y"]

    def test_custom_px_per_meter(self, env):
        b1 = viewer.compute_render_bounds(env, px_per_meter=2.0)
        b2 = viewer.compute_render_bounds(env, px_per_meter=4.0)
        # Higher px_per_meter → larger image (or equal if clamped by 8192 limit)
        assert b2["img_w"] >= b1["img_w"]


# ── render_static_bg ──────────────────────────────────────────────────────────

class TestRenderStaticBg:
    def test_returns_pil_image(self, env, bounds):
        from PIL import Image
        img = viewer.render_static_bg(env, bounds, viewer.RenderStyle())
        assert isinstance(img, Image.Image)

    def test_image_dimensions_match_bounds(self, env, bounds):
        img = viewer.render_static_bg(env, bounds, viewer.RenderStyle())
        assert img.width == bounds["img_w"]
        assert img.height == bounds["img_h"]

    def test_non_empty_image(self, env, bounds):
        img = viewer.render_static_bg(env, bounds, viewer.RenderStyle())
        pixels = list(img.getdata())
        # Not a uniform blank (roads/lanes should change some pixels)
        assert len(set(pixels)) > 1

    def test_custom_bg_color(self, env, bounds):
        style = viewer.RenderStyle(bg_color=(255, 0, 0))
        img = viewer.render_static_bg(env, bounds, style)
        # Background color should appear somewhere
        pixels = list(img.getdata())
        assert (255, 0, 0) in pixels


# ── agent_frame_data ──────────────────────────────────────────────────────────

class TestAgentFrameData:
    def test_returns_list_of_dicts(self, env, bounds):
        result = viewer.agent_frame_data(env, bounds)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_each_entry_has_required_keys(self, env, bounds):
        result = viewer.agent_frame_data(env, bounds)
        for entry in result:
            for key in ("id", "cx", "cy", "heading", "hl", "hw", "lx", "ly"):
                assert key in entry

    def test_dims_are_positive(self, env, bounds):
        result = viewer.agent_frame_data(env, bounds)
        for entry in result:
            assert entry["hl"] > 0
            assert entry["hw"] > 0

    def test_invalid_agents_excluded(self, bounds):
        env = MockEnv(n=3)
        # Place one agent far outside the valid range
        env._agent_state["x"][1] = 99999.0
        result = viewer.agent_frame_data(env, bounds)
        ids = [e["id"] for e in result]
        # Agent 0 and 2 should be present; agent 1 (x=99999) should be absent
        assert len(result) == 2
        assert "1" not in ids

    def test_labels_match_agent_ids(self, env, bounds):
        result = viewer.agent_frame_data(env, bounds)
        for i, entry in enumerate(result):
            assert isinstance(entry["id"], str)


# ── goal_frame_data ───────────────────────────────────────────────────────────

class TestGoalFrameData:
    def test_returns_list_of_dicts(self, env, bounds):
        result = viewer.goal_frame_data(env, bounds)
        assert isinstance(result, list)

    def test_each_entry_has_required_keys(self, env, bounds):
        result = viewer.goal_frame_data(env, bounds)
        for entry in result:
            assert "slot" in entry
            assert "fx" in entry
            assert "fy" in entry
            assert "label" in entry

    def test_fractions_in_unit_range(self, env, bounds):
        # With zero observations goals are at agent positions, which are within bounds
        result = viewer.goal_frame_data(env, bounds)
        for entry in result:
            assert 0.0 <= entry["fx"] <= 1.0, f"fx={entry['fx']} out of range"
            assert 0.0 <= entry["fy"] <= 1.0, f"fy={entry['fy']} out of range"

    def test_goal_override_changes_position(self, env, bounds):
        result_before = viewer.goal_frame_data(env, bounds)
        # Override slot 0 goal to a different world position
        override = {0: (1.0, 1.0)}
        result_after = viewer.goal_frame_data(env, bounds, goal_overrides=override)
        # The overridden slot should have a different position
        slot0_before = next(r for r in result_before if r["slot"] == 0)
        slot0_after = next(r for r in result_after if r["slot"] == 0)
        assert slot0_before["fx"] != slot0_after["fx"] or slot0_before["fy"] != slot0_after["fy"]

    def test_updates_module_last_goal_positions(self, env, bounds):
        viewer.last_goal_positions = []
        viewer.goal_frame_data(env, bounds)
        assert len(viewer.last_goal_positions) > 0


# ── collect_frames ─────────────────────────────────────────────────────────────

class TestCollectFrames:
    """collect_frames returns (agent_render_frames, static_agents, map_data, agent_states, agent_status_frames, bounds)."""

    def test_returns_six_items(self, env):
        result = viewer.collect_frames(env, num_steps=4, save_every=2)
        assert len(result) == 6

    def test_agent_render_frames_is_list(self, env):
        agent_render_frames, _, _, _, _, _ = viewer.collect_frames(env, num_steps=4, save_every=2)
        assert isinstance(agent_render_frames, list)
        assert len(agent_render_frames) > 0

    def test_correct_frame_count(self, env):
        agent_render_frames, _, _, _, _, _ = viewer.collect_frames(env, num_steps=6, save_every=2)
        assert len(agent_render_frames) == 3  # steps 0, 2, 4

    def test_agent_states_length_matches_render_frames(self, env):
        agent_render_frames, _, _, agent_states, _, _ = viewer.collect_frames(env, num_steps=6, save_every=2)
        assert len(agent_states) == len(agent_render_frames)

    def test_map_data_has_required_keys(self, env):
        _, _, map_data, _, _, _ = viewer.collect_frames(env, num_steps=4, save_every=2)
        assert isinstance(map_data, dict)
        for key in ("bg", "lane_color", "road_color", "lane_w", "road_w", "lanes", "roads", "img_w", "img_h"):
            assert key in map_data, f"missing key: {key}"

    def test_map_data_has_polylines(self, env):
        _, _, map_data, _, _, _ = viewer.collect_frames(env, num_steps=4, save_every=2)
        assert isinstance(map_data["lanes"], list)
        assert isinstance(map_data["roads"], list)
        assert len(map_data["lanes"]) > 0
        assert len(map_data["roads"]) > 0

    def test_bounds_returned(self, env):
        _, _, _, _, _, bounds = viewer.collect_frames(env, num_steps=4, save_every=2)
        assert "scale" in bounds
        assert "img_w" in bounds

    def test_agent_states_have_xyz(self, env):
        _, _, _, agent_states, _, _ = viewer.collect_frames(env, num_steps=4, save_every=2)
        for state in agent_states:
            assert "x" in state
            assert "y" in state
            assert "valid" in state

    def test_render_frames_have_required_keys(self, env):
        agent_render_frames, _, _, _, _, _ = viewer.collect_frames(env, num_steps=4, save_every=2)
        for frame in agent_render_frames:
            for agent in frame:
                for key in ("cx", "cy", "heading", "hl", "hw", "id"):
                    assert key in agent

    def test_static_agents_is_list(self, env):
        _, static_agents, _, _, _, _ = viewer.collect_frames(env, num_steps=4, save_every=2)
        assert isinstance(static_agents, list)

    def test_with_mock_policy(self, env):
        policy = MockPolicy()
        agent_render_frames, _, _, agent_states, _, _ = viewer.collect_frames(
            env, num_steps=4, save_every=2, policy=policy
        )
        assert len(agent_render_frames) > 0
        assert len(agent_states) > 0

    def test_sets_initial_goal_positions(self, env):
        viewer.initial_goal_positions = []
        viewer.collect_frames(env, num_steps=4, save_every=2)
        assert len(viewer.initial_goal_positions) > 0

    def test_sets_last_render_transform(self, env):
        viewer.last_render_transform = None
        viewer.collect_frames(env, num_steps=4, save_every=2)
        assert viewer.last_render_transform is not None
