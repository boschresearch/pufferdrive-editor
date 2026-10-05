# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""Tests for pure functions in demo/demo/viewer.py.

No real environment, no map files, no C++ bindings needed.
"""

import base64
import configparser
import io
import os
import sys
import tempfile

import numpy as np
import pytest

# Make viewer importable without going through the demo package (which pulls in reflex).
_VIEWER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo", "demo")
sys.path.insert(0, _VIEWER_DIR)
import viewer


# ── _parse_map_path ───────────────────────────────────────────────────────────

class TestParseMapPath:
    def test_standard_path(self):
        data_root, split, map_id = viewer._parse_map_path("/data/drive/binaries/training/map_000042.bin")
        assert data_root == "/data/drive/binaries"
        assert split == "training"
        assert map_id == 42

    def test_validation_split(self):
        _, split, _ = viewer._parse_map_path("/foo/bar/validation/map_000001.bin")
        assert split == "validation"

    def test_map_id_zero_padded(self):
        _, _, map_id = viewer._parse_map_path("/root/testing/map_000000.bin")
        assert map_id == 0

    def test_invalid_path_raises(self):
        with pytest.raises(ValueError):
            viewer._parse_map_path("/no/bin/extension/map_001")

    def test_missing_split_dir_raises(self):
        with pytest.raises(ValueError):
            viewer._parse_map_path("map_000042.bin")


# ── Coordinate conversions ─────────────────────────────────────────────────────

@pytest.fixture
def simple_transform():
    """Set up a known world-to-pixel transform and return it."""
    t = {"min_x": 0.0, "max_y": 100.0, "scale": 2.0, "img_w": 200, "img_h": 200}
    viewer.last_render_transform = t
    yield t
    viewer.last_render_transform = None


class TestWorldPixelConversions:
    def test_world_to_pixel_fraction_origin(self, simple_transform):
        fx, fy = viewer.world_to_pixel_fraction(0.0, 100.0)  # top-left in world
        assert abs(fx) < 1e-6
        assert abs(fy) < 1e-6

    def test_world_to_pixel_fraction_center(self, simple_transform):
        # world (50, 50) → pixel (100, 100) → fractions (0.5, 0.5)
        fx, fy = viewer.world_to_pixel_fraction(50.0, 50.0)
        assert abs(fx - 0.5) < 1e-6
        assert abs(fy - 0.5) < 1e-6

    def test_pixels_to_world_roundtrip(self, simple_transform):
        wx, wy = 37.3, 62.7
        fx, fy = viewer.world_to_pixel_fraction(wx, wy)
        img_x = fx * simple_transform["img_w"]
        img_y = fy * simple_transform["img_h"]
        wx2, wy2 = viewer.pixels_to_world(img_x, img_y)
        assert abs(wx2 - wx) < 1e-3
        assert abs(wy2 - wy) < 1e-3

    def test_without_transform_returns_none(self):
        viewer.last_render_transform = None
        assert viewer.world_to_pixel_fraction(10.0, 10.0) is None
        assert viewer.pixels_to_world(10.0, 10.0) is None
        assert viewer.frac_to_world(0.5, 0.5) is None

    def test_frac_to_world_roundtrip(self, simple_transform):
        wx, wy = 25.0, 75.0
        fx, fy = viewer.world_to_pixel_fraction(wx, wy)
        wx2, wy2 = viewer.frac_to_world(fx, fy)
        assert abs(wx2 - wx) < 1e-3
        assert abs(wy2 - wy) < 1e-3


class TestWorldToPx:
    def test_make_to_px_basic(self):
        bounds = {"min_x": 0.0, "max_y": 10.0, "scale": 1.0, "img_w": 10, "img_h": 10}
        to_px = viewer._make_to_px(bounds)
        # world (0, 10) → top-left (0, 0)
        assert to_px(0.0, 10.0) == (0, 0)
        # world (10, 0) → bottom-right (10, 10)
        assert to_px(10.0, 0.0) == (10, 10)

    def test_world_to_px_helper(self):
        bounds = {"min_x": 0.0, "max_y": 10.0, "scale": 2.0, "img_w": 20, "img_h": 20}
        px, py = viewer._world_to_px(5.0, 5.0, bounds)
        assert px == 10
        assert py == 10


# ── find_agent_at_pixel ───────────────────────────────────────────────────────

def _make_agent_states(positions: list[tuple[float, float]]) -> list[dict]:
    """Build a single-frame agent_states list from world positions."""
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    return [{"x": xs, "y": ys, "valid": [True] * len(positions)}]


class TestFindAgentAtPixel:
    def setup_method(self):
        self.bounds = {"min_x": 0.0, "max_y": 100.0, "scale": 1.0, "img_w": 100, "img_h": 100}

    def test_finds_nearest_agent(self):
        # world (10, 90) → pixel (10, 10), world (50, 50) → pixel (50, 50)
        states = _make_agent_states([(10.0, 90.0), (50.0, 50.0)])
        idx = viewer.find_agent_at_pixel(10.0, 10.0, 0, states, self.bounds, hit_radius=30)
        assert idx == 0

    def test_returns_minus_one_when_none_in_radius(self):
        states = _make_agent_states([(50.0, 50.0)])
        idx = viewer.find_agent_at_pixel(0.0, 0.0, 0, states, self.bounds, hit_radius=5)
        assert idx == -1

    def test_empty_states_returns_minus_one(self):
        assert viewer.find_agent_at_pixel(0, 0, 0, [], {}, hit_radius=30) == -1

    def test_frame_out_of_range_returns_minus_one(self):
        states = _make_agent_states([(10.0, 90.0)])
        assert viewer.find_agent_at_pixel(10, 10, 99, states, self.bounds) == -1

    def test_invalid_agents_skipped(self):
        states = [{"x": [10.0, 50.0], "y": [90.0, 50.0], "valid": [False, True]}]
        idx = viewer.find_agent_at_pixel(10.0, 10.0, 0, states, self.bounds, hit_radius=30)
        # agent 0 is invalid even though it's closest
        assert idx != 0


# ── get_agent_all_frame_pixels ─────────────────────────────────────────────────

class TestGetAgentAllFramePixels:
    def setup_method(self):
        self.bounds = {"min_x": 0.0, "max_y": 100.0, "scale": 1.0, "img_w": 100, "img_h": 100}

    def test_returns_one_entry_per_frame(self):
        states = [
            {"x": [10.0, 20.0], "y": [90.0, 80.0], "valid": [True, True]},
            {"x": [15.0, 20.0], "y": [85.0, 80.0], "valid": [True, True]},
        ]
        result = viewer.get_agent_all_frame_pixels(0, states, self.bounds)
        assert len(result) == 2
        assert result[0]["valid"]
        assert result[1]["valid"]

    def test_invalid_frame_gives_valid_false(self):
        states = [{"x": [10.0], "y": [90.0], "valid": [False]}]
        result = viewer.get_agent_all_frame_pixels(0, states, self.bounds)
        assert not result[0]["valid"]

    def test_out_of_range_agent_index(self):
        states = [{"x": [10.0], "y": [90.0], "valid": [True]}]
        result = viewer.get_agent_all_frame_pixels(5, states, self.bounds)
        assert not result[0]["valid"]

    def test_pixel_values_match_expected(self):
        # world (25, 75) → pixel (25, 25) with this bounds
        states = [{"x": [25.0], "y": [75.0], "valid": [True]}]
        result = viewer.get_agent_all_frame_pixels(0, states, self.bounds)
        assert result[0]["px"] == 25
        assert result[0]["py"] == 25


# ── encode_image ──────────────────────────────────────────────────────────────

class TestEncodeImage:
    def test_returns_data_uri_prefix(self):
        from PIL import Image
        img = Image.new("RGB", (10, 10), (255, 0, 0))
        result = viewer.encode_image(img)
        assert result.startswith("data:image/png;base64,")

    def test_base64_is_valid(self):
        from PIL import Image
        img = Image.new("RGB", (4, 4), (0, 128, 255))
        result = viewer.encode_image(img)
        b64_part = result[len("data:image/png;base64,"):]
        decoded = base64.b64decode(b64_part)
        assert decoded[:4] == b"\x89PNG"  # PNG magic bytes

    def test_roundtrip_preserves_image(self):
        from PIL import Image
        img = Image.new("RGB", (8, 8), (123, 45, 67))
        encoded = viewer.encode_image(img)
        b64_part = encoded[len("data:image/png;base64,"):]
        decoded_img = Image.open(io.BytesIO(base64.b64decode(b64_part)))
        assert decoded_img.size == (8, 8)
        assert decoded_img.getpixel((0, 0)) == (123, 45, 67)


# ── scan_ini_files ────────────────────────────────────────────────────────────

class TestScanIniFiles:
    def test_finds_ini_files(self, tmp_path):
        (tmp_path / "a.ini").write_text("[section]\nkey=val\n")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "b.ini").write_text("[section]\nkey=val\n")
        (tmp_path / "ignore.txt").write_text("not ini")

        results = viewer.scan_ini_files(str(tmp_path))
        labels = [r[0] for r in results]
        assert any("a.ini" in l for l in labels)
        assert any("b.ini" in l for l in labels)
        assert all(l.endswith(".ini") for l in labels)

    def test_missing_dir_returns_empty(self):
        result = viewer.scan_ini_files("/nonexistent/path/that/does/not/exist")
        assert result == []

    def test_returns_sorted(self, tmp_path):
        for name in ["z.ini", "a.ini", "m.ini"]:
            (tmp_path / name).write_text("")
        results = viewer.scan_ini_files(str(tmp_path))
        labels = [r[0] for r in results]
        assert labels == sorted(labels)


# ── parse_demo_sections ───────────────────────────────────────────────────────

class TestParseDemoSections:
    def test_parses_maps_and_policies(self, tmp_path):
        ini = tmp_path / "demo.ini"
        ini.write_text(
            "[demo.maps]\nmap_a = /path/to/a.bin\n"
            "[demo.policies]\npolicy_1 = /path/to/p.pt\n"
        )
        result = viewer.parse_demo_sections(str(ini))
        assert result["maps"]["map_a"] == "/path/to/a.bin"
        assert result["policies"]["policy_1"] == "/path/to/p.pt"

    def test_missing_sections_return_empty_dicts(self, tmp_path):
        ini = tmp_path / "empty.ini"
        ini.write_text("[unrelated]\nfoo=bar\n")
        result = viewer.parse_demo_sections(str(ini))
        assert result["maps"] == {}
        assert result["policies"] == {}

    def test_missing_file_returns_empty_dicts(self, tmp_path):
        result = viewer.parse_demo_sections(str(tmp_path / "nonexistent.ini"))
        assert result["maps"] == {}
        assert result["policies"] == {}


# ── load_render_style ─────────────────────────────────────────────────────────

class TestLoadRenderStyle:
    def test_defaults(self):
        style = viewer.load_render_style(ini_path=None)
        assert style.px_per_meter > 0
        assert style.supersample >= 1
        assert len(style.bg_color) == 3

    def test_overrides_from_ini(self, tmp_path, monkeypatch):
        # Patch out the default ini so custom values aren't overridden by it.
        monkeypatch.setattr(viewer, "_DEFAULT_INI_PATH", str(tmp_path / "nonexistent.ini"))
        ini = tmp_path / "custom.ini"
        ini.write_text("[demo.ui]\nresolution = 10.0\nsupersample = 4\n")
        style = viewer.load_render_style(ini_path=str(ini))
        assert style.px_per_meter == 10.0
        assert style.supersample == 4

    def test_color_parsing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(viewer, "_DEFAULT_INI_PATH", str(tmp_path / "nonexistent.ini"))
        ini = tmp_path / "color.ini"
        ini.write_text("[demo.ui]\nbg_color = 1, 2, 3\n")
        style = viewer.load_render_style(ini_path=str(ini))
        assert style.bg_color == (1, 2, 3)


# ── scan_maps ─────────────────────────────────────────────────────────────────

class TestScanMaps:
    def test_finds_map_files(self, tmp_path):
        split_dir = tmp_path / "training"
        split_dir.mkdir()
        (split_dir / "map_000001.bin").write_bytes(b"")
        (split_dir / "map_000042.bin").write_bytes(b"")
        (split_dir / "other.txt").write_text("ignore")

        ids = viewer.scan_maps(str(tmp_path), "training")
        assert ids == [1, 42]

    def test_missing_split_returns_empty(self, tmp_path):
        ids = viewer.scan_maps(str(tmp_path), "nonexistent")
        assert ids == []

    def test_returns_sorted_ids(self, tmp_path):
        split_dir = tmp_path / "testing"
        split_dir.mkdir()
        for n in [100, 5, 42]:
            (split_dir / f"map_{n:06d}.bin").write_bytes(b"")
        ids = viewer.scan_maps(str(tmp_path), "testing")
        assert ids == sorted(ids)
