# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""Backend rendering and env management for the PufferDrive Reflex demo."""

import base64
import configparser
from dataclasses import dataclass
import io
import os
import re

import numpy as np

SPLITS = ["training", "validation", "testing"]

_VIEWER_DIR = os.path.dirname(os.path.abspath(__file__))
# <repo>/demo/demo/viewer.py → <repo>
REPO_ROOT = os.path.dirname(os.path.dirname(_VIEWER_DIR))
DEFAULT_POLICY_DIR = os.path.join(REPO_ROOT, "pufferlib", "resources", "drive")
DEFAULT_POLICY_PATH = os.path.join(DEFAULT_POLICY_DIR, "model_puffer_drive_003815.pt")


def portable_policy_path(p: str) -> str:
    """Absolute path → path relative to the repo root, so exported scenarios stay
    machine-independent. Paths outside the repo are returned unchanged."""
    if not p or not os.path.isabs(p):
        return p
    real = os.path.normpath(p)
    root = os.path.normpath(REPO_ROOT)
    if real == root or real.startswith(root + os.sep):
        return os.path.relpath(real, root)
    return real


def resolve_policy_path(p: str) -> str:
    """Inverse of portable_policy_path, tolerant of scenarios written on another machine.

    Tries, in order: the path as given, the path relative to the repo root, and finally
    the bare filename inside the bundled checkpoint directory — so a scenario exported
    with someone else's absolute checkpoint path still finds the shipped model instead
    of silently falling back to a random policy.
    """
    if not p:
        return p
    if os.path.exists(p):
        return p
    candidate = os.path.join(REPO_ROOT, p)
    if os.path.exists(candidate):
        return candidate
    candidate = os.path.join(DEFAULT_POLICY_DIR, os.path.basename(p))
    if os.path.exists(candidate):
        return candidate
    return p

# Color palette (RGB tuples)
_BG = (15, 23, 42)
_ROAD_COLOR = (60, 80, 110)
_LANE_COLOR = (35, 55, 80)
_AGENT_FILL = (1, 83, 214)
_AGENT_OUTLINE = (100, 160, 255)
_EXPERT_FILL = (200, 100, 10)
_EXPERT_OUTLINE = (255, 160, 60)
_LABEL_COLOR = (255, 255, 255)
_GOAL_SELECTED_FILL = (234, 179, 8)     # amber fill when goal is selected for editing
_GOAL_SELECTED_OUTLINE = (253, 224, 71) # lighter amber outline
_CHEVRON_COLOR = (180, 220, 255)   # slightly lighter than outline for contrast
_LABEL_SHADOW = (0, 0, 0)
_LABEL_FG = (255, 255, 255)

# Off-screen sentinel positions written by the C env (drive.h). Agents parked at
# these exact coords are hidden. We test equality rather than a magnitude cutoff so
# maps whose real world coordinates exceed a few thousand metres (e.g. training map 1
# at x~10900) still render — a blanket |pos| < 9000 filter wrongly discards them.
_INVALID_POSITION = -10000.0   # drive.h INVALID_POSITION
_PARKED_POSITION = -90000.0    # drive.h PARKED_X / PARKED_Y


def _render_valid_mask(x, y, lengths):
    """Agents with a real footprint that aren't parked at an off-screen sentinel."""
    return (
        (x != _INVALID_POSITION) & (y != _INVALID_POSITION)
        & (x != _PARKED_POSITION) & (y != _PARKED_POSITION)
        & (lengths > 0)
    )


def get_data_root() -> str:
    return os.environ.get("DRIVE_BINARIES_DATA_ROOT", "resources/drive/binaries")


def get_config_dir() -> str:
    return os.environ.get("DRIVE_CONFIG_DIR", "config")


def scan_ini_files(config_dir: str) -> list[tuple[str, str]]:
    """Find .ini files directly in config_dir (non-recursive). Returns [(label, path), ...]."""
    result = []
    try:
        for fname in sorted(os.listdir(config_dir)):
            if fname.endswith(".ini"):
                path = os.path.join(config_dir, fname)
                if os.path.isfile(path):
                    result.append((fname[:-4], path))
    except (FileNotFoundError, NotADirectoryError):
        pass
    return result


def parse_demo_sections(ini_path: str) -> dict:
    """Return maps, policy list, and features from a demo ini file.

    Reads demo.ini from the same directory first as a base layer, then overlays
    the specified ini. Returns:
      {"maps": {label: path}, "policy_list": [(name, model_path, config_path), ...],
       "features": {key: value}}.
    Falls back to legacy [demo.policies] if no [policies.*] sections exist.
    """
    ini_dir = os.path.dirname(os.path.abspath(ini_path))
    base_ini = os.path.join(ini_dir, "demo.ini")

    parser = configparser.RawConfigParser(inline_comment_prefixes=("#", ";"))
    # Read base first so the specific ini can override any value.
    parser.read([base_ini, ini_path])

    def _resolve(p: str) -> str:
        if not p or os.path.isabs(p):
            return p
        # 1. Try relative to ini_dir and each ancestor.
        candidate = ini_dir
        for _ in range(5):
            full = os.path.join(candidate, p)
            if os.path.exists(full):
                return full
            parent = os.path.dirname(candidate)
            if parent == candidate:
                break
            candidate = parent
        # 2. Strip known binary resource prefixes and resolve via data root.
        data_root = get_data_root()
        for prefix in ('resources/drive/binaries/', 'resources/maps/'):
            if p.startswith(prefix):
                full = os.path.join(data_root, p[len(prefix):])
                if os.path.exists(full):
                    return full
        # 3. Try as a path directly relative to data_root.
        full = os.path.join(data_root, p)
        if os.path.exists(full):
            return full
        return p

    maps = {k: _resolve(v) for k, v in parser.items("demo.maps")} if parser.has_section("demo.maps") else {}

    policy_list = []
    for section in parser.sections():
        if section.startswith("policies."):
            name = parser.get(section, "name", fallback=section[len("policies."):])
            model = _resolve(parser.get(section, "model", fallback=""))
            config = _resolve(parser.get(section, "config", fallback=""))
            policy_list.append((name, model, config))

    if not policy_list and parser.has_section("demo.policies"):
        for k, v in parser.items("demo.policies"):
            policy_list.append((k, _resolve(v), ""))

    features = dict(parser.items("demo.features")) if parser.has_section("demo.features") else {}

    return {"maps": maps, "policy_list": policy_list, "features": features}


_DEFAULT_INI_PATH = os.path.join(os.path.dirname(_VIEWER_DIR), "config", "default.ini")


def _parse_color(s: str) -> tuple[int, int, int]:
    parts = [p.strip() for p in s.split(",")]
    return int(parts[0]), int(parts[1]), int(parts[2])


@dataclass
class RenderStyle:
    supersample: int = 4
    bg_color: tuple = (15, 23, 42)
    road_color: tuple = (60, 80, 110)
    road_width: float = 0.4
    lane_color: tuple = (35, 55, 80)
    lane_width: float = 0.3
    agent_fill: tuple = (234, 88, 12)
    agent_outline: tuple = (251, 146, 60)
    expert_fill: tuple = (1, 83, 214)
    expert_outline: tuple = (100, 160, 255)
    static_fill: tuple = (1, 83, 214)      # = expert_fill; parked cars share the expert color
    static_outline: tuple = (100, 160, 255)  # = expert_outline
    ghost_opacity: float = 0.75
    ghost_fill: tuple = (120, 40, 8)
    ghost_outline: tuple = (180, 83, 9)
    ghost_expert_fill: tuple = (76, 29, 149)
    ghost_expert_outline: tuple = (124, 58, 237)
    ghost_static_fill: tuple = (76, 29, 149)     # = ghost_expert_fill; parked cars share the expert color
    ghost_static_outline: tuple = (124, 58, 237)  # = ghost_expert_outline


def load_render_style(ini_path: str | None = None) -> RenderStyle:
    """Load [demo.ui] visual settings from ini, falling back to default.ini."""
    parser = configparser.RawConfigParser(inline_comment_prefixes=(";",))
    paths = [p for p in [ini_path, _DEFAULT_INI_PATH] if p]
    parser.read(paths)

    def _f(key, default):
        return float(parser.get("demo.ui", key)) if parser.has_option("demo.ui", key) else default

    def _c(key, default):
        return _parse_color(parser.get("demo.ui", key)) if parser.has_option("demo.ui", key) else default

    def _i(key, default):
        return int(parser.get("demo.ui", key)) if parser.has_option("demo.ui", key) else default

    return RenderStyle(
        supersample=_i("supersample", 2),
        bg_color=_c("bg_color", (15, 23, 42)),
        road_color=_c("road_color", (60, 80, 110)),
        road_width=_f("road_width", 0.3),
        lane_color=_c("lane_color", (35, 55, 80)),
        lane_width=_f("lane_width", 0.15),
        agent_fill=_c("agent_fill", (234, 88, 12)),
        agent_outline=_c("agent_outline", (251, 146, 60)),
        expert_fill=_c("expert_fill", (1, 83, 214)),
        expert_outline=_c("expert_outline", (100, 160, 255)),
        static_fill=_c("static_fill", (1, 83, 214)),        # = expert_fill; parked cars share the expert color
        static_outline=_c("static_outline", (100, 160, 255)),  # = expert_outline
        ghost_opacity=_f("ghost_opacity", 0.55),
        ghost_fill=_c("ghost_fill", (76, 29, 149)),
        ghost_outline=_c("ghost_outline", (124, 58, 237)),
        ghost_expert_fill=_c("ghost_expert_fill", (109, 40, 217)),
        ghost_expert_outline=_c("ghost_expert_outline", (167, 139, 250)),
        ghost_static_fill=_c("ghost_static_fill", (76, 29, 149)),        # = ghost_expert_fill; parked cars share the expert color
        ghost_static_outline=_c("ghost_static_outline", (124, 58, 237)),  # = ghost_expert_outline
    )


def load_render_every(ini_path: str | None = None) -> int:
    """Load render_every from [demo.ui] in ini, falling back to default.ini."""
    parser = configparser.RawConfigParser(inline_comment_prefixes=(";",))
    paths = [p for p in [ini_path, _DEFAULT_INI_PATH] if p]
    parser.read(paths)
    if parser.has_option("demo.ui", "render_every"):
        return max(1, int(parser.get("demo.ui", "render_every")))
    return 1


def load_policy_from_path(path: str, env, ini_path: str | None = None):
    """Load a Drive policy from a .pt checkpoint file.

    Reads policy/rnn hyperparameters from the ini, falling back to _DRIVE_INI_PATH
    when ini_path is not provided. Returns the policy in eval mode on CPU.
    """
    import ast
    import torch
    from pufferlib.ocean import torch as ocean_torch

    p = configparser.RawConfigParser(inline_comment_prefixes=("#", ";"))
    # Base first, per-policy ini last so the specific config overrides the fallback
    # (configparser: last read wins) — matches parse_demo_sections' layering and the
    # docstring intent. The reverse order silently let _DRIVE_INI_PATH clobber a
    # policy's own architecture (e.g. a DriveCond checkpoint), breaking load_state_dict.
    p.read([path for path in [_DRIVE_INI_PATH, ini_path] if path])

    def _int(section, key, default):
        try:
            return int(ast.literal_eval(p[section][key]))
        except Exception:
            return default

    policy_kwargs = {
        "input_size":  _int("policy", "input_size",  64),
        "hidden_size": _int("policy", "hidden_size", 256),
    }
    rnn_kwargs = {
        "input_size":  _int("rnn", "input_size",  256),
        "hidden_size": _int("rnn", "hidden_size", 256),
    }

    policy_name = p.get("base", "policy_name", fallback="Drive")
    rnn_name    = p.get("base", "rnn_name",    fallback="Recurrent")
    policy_cls  = getattr(ocean_torch, policy_name, ocean_torch.Drive)
    rnn_cls     = getattr(ocean_torch, rnn_name, ocean_torch.Recurrent) \
                  if rnn_name not in ("None", "none", "") else None

    policy = policy_cls(env, **policy_kwargs)
    if rnn_cls is not None:
        policy = rnn_cls(env, policy, **rnn_kwargs)

    state_dict = torch.load(path, map_location="cpu", weights_only=True)
    state_dict = {k.replace("module.", ""): v for k, v in state_dict.items()}
    policy.load_state_dict(state_dict)
    policy.eval()
    return policy


def _parse_map_path(map_path: str) -> tuple[str, str, int]:
    """Extract (data_root, split, map_id) from <data_root>/<split>/map_NNNNNN.bin."""
    m = re.match(r"^(.+)/([^/]+)/map_(\d+)\.bin$", map_path)
    if not m:
        raise ValueError(f"Cannot parse map path: {map_path!r}")
    return m.group(1), m.group(2), int(m.group(3))


def create_env_from_path(map_path: str, num_agents: int = 100, episode_length: int = 91,
                         ini_path: str | None = None):
    """Create a Drive env from a direct map binary path."""
    data_root, split, map_id = _parse_map_path(map_path)
    return create_env(map_id, split, data_root, num_agents=num_agents,
                      episode_length=episode_length, ini_path=ini_path)


def scan_maps(data_root: str, split: str) -> list[int]:
    split_dir = os.path.join(data_root, split)
    map_ids = []
    try:
        for f in sorted(os.listdir(split_dir)):
            m = re.match(r"map_(\d+)\.bin", f)
            if m:
                map_ids.append(int(m.group(1)))
    except (FileNotFoundError, NotADirectoryError):
        pass
    return map_ids


_DRIVE_INI_PATH = os.path.join(
    os.path.dirname(os.path.dirname(_VIEWER_DIR)), "pufferlib", "config", "ocean", "drive.ini"
)

def _read_env_ini(ini_path: str | None) -> dict:
    """Read [env] section from a drive.ini and return float/int/str values."""
    import ast
    parser = configparser.RawConfigParser(inline_comment_prefixes=("#", ";"))
    parser.read([p for p in [ini_path, _DRIVE_INI_PATH] if p])
    if not parser.has_section("env"):
        return {}
    result = {}
    for key, raw in parser.items("env"):
        val = raw.strip().strip('"')
        try:
            result[key] = ast.literal_eval(val)
        except Exception:
            result[key] = val
    return result


def create_env(map_id: int, split: str, data_root: str, num_agents: int = 80,
               episode_length: int = 91, ini_path: str | None = None):
    from pufferlib.ocean.drive.drive import Drive

    cfg = _read_env_ini(ini_path)

    def _f(key, default):
        return float(cfg[key]) if key in cfg else default

    def _i(key, default):
        return int(cfg[key]) if key in cfg else default

    def _s(key, default):
        return str(cfg[key]) if key in cfg else default

    return Drive(
        data_root=data_root,
        split=split,
        map_id=map_id,
        num_agents=num_agents,
        num_maps=1,
        episode_length=episode_length,
        termination_mode=_i("termination_mode", 0),
        resample_frequency=0,           # always 0 in viewer — no mid-demo map resampling
        dt=_f("dt", 0.1),
        reward_vehicle_collision=_f("reward_vehicle_collision", -0.5),
        reward_offroad_collision=_f("reward_offroad_collision", -0.5),
        reward_goal=_f("reward_goal", 1.0),
        reward_goal_post_respawn=_f("reward_goal_post_respawn", 0.25),
        goal_radius=_f("goal_radius", 2.0),
        goal_speed=_f("goal_speed", 100.0),
        goal_behavior=_i("goal_behavior", 3),
        goal_target_distance=_f("goal_target_distance", 30.0),
        collision_behavior=_i("collision_behavior", 2),
        offroad_behavior=_i("offroad_behavior", 2),
        init_steps=_i("init_steps", 0),
        init_mode=_s("init_mode", "create_all_valid"),
        control_mode=_s("control_mode", "control_vehicles"),
        action_type=_s("action_type", "discrete"),
        dynamics_model=_s("dynamics_model", "classic"),
    )





# ── Module-level state ────────────────────────────────────────────────────────
# These are read by demo.py for coordinate conversion (click→world, goal editing).

last_render_transform: dict | None = None  # {min_x, max_y, scale, img_w, img_h}
last_goal_positions: list[dict] = []       # [{slot, fx, fy, label}] — most recent frame
initial_goal_positions: list[dict] = []    # goal positions at frame 0 (all agents valid)

# Thread-safe progress counters written by collect_frames, polled by async resimulate.
_resim_step: int = 0
_resim_total: int = 0


# ── Coordinate helpers ────────────────────────────────────────────────────────

def _make_to_px(bounds: dict):
    """Return a closure that converts world (x, y) → output image (px, py)."""
    min_x = bounds["min_x"]
    max_y = bounds["max_y"]
    scale = bounds["scale"]
    def to_px(x: float, y: float) -> tuple[int, int]:
        return int((x - min_x) * scale), int((max_y - y) * scale)
    return to_px

def frac_to_world(fx: float, fy: float) -> tuple[float, float] | None:
    """Convert image-fraction (fx, fy) in [0,1] to world (x, y) coordinates."""
    t = last_render_transform
    if t is None:
        return None
    return pixels_to_world(fx * t["img_w"], fy * t["img_h"])


def _goal_positions(env, agents: dict) -> tuple[np.ndarray, np.ndarray]:
    """Decode world-space goal (x, y) for every agent from the observation vector."""
    obs = env.observations  # shape (num_agents, num_obs)
    ax, ay, headings = agents["x"], agents["y"], agents["heading"]
    n = len(ax)
    goal_x = np.zeros(n, dtype=np.float32)
    goal_y = np.zeros(n, dtype=np.float32)
    for i in range(n):
        rel_gx = float(obs[i, 0]) * 200.0  # undo 0.005 scale
        rel_gy = float(obs[i, 1]) * 200.0
        c, s = np.cos(headings[i]), np.sin(headings[i])
        goal_x[i] = ax[i] + rel_gx * c - rel_gy * s
        goal_y[i] = ay[i] + rel_gx * s + rel_gy * c
    return goal_x, goal_y


def world_to_pixel_fraction(world_x: float, world_y: float) -> tuple[float, float] | None:
    """Convert world coords to (fx, fy) fractions in [0, 1] of the rendered image."""
    t = last_render_transform
    if t is None:
        return None
    return (
        (world_x - t["min_x"]) * t["scale"] / t["img_w"],
        (t["max_y"] - world_y) * t["scale"] / t["img_h"],
    )


def pixels_to_world(img_x: float, img_y: float) -> tuple[float, float] | None:
    """Convert output-image pixel coords back to world coords."""
    t = last_render_transform
    if t is None:
        return None
    return img_x / t["scale"] + t["min_x"], t["max_y"] - img_y / t["scale"]


# ── Bounds computation ────────────────────────────────────────────────────────

def compute_render_bounds(env, px_per_meter: float = 5.0, margin: float = 20.0) -> dict | None:
    """Compute world-to-pixel bounds that fit the entire scene.

    The same bounds are reused for every frame of a simulation so that pixel
    coordinates are comparable across frames (needed for trajectory overlay and
    click-to-select).
    """
    agents = env.get_global_agent_state()
    roads = env.get_road_edge_polylines()

    road_x: np.ndarray = roads["x"]
    road_y: np.ndarray = roads["y"]
    ax: np.ndarray = agents["x"]
    ay: np.ndarray = agents["y"]
    lengths_arr: np.ndarray = agents["length"]

    valid_mask = _render_valid_mask(ax, ay, lengths_arr)
    vax, vay = ax[valid_mask], ay[valid_mask]

    goal_x, goal_y = _goal_positions(env, agents)
    vgx, vgy = goal_x[valid_mask], goal_y[valid_mask]

    all_x = np.concatenate([road_x, vax, vgx]) if len(vax) else road_x
    all_y = np.concatenate([road_y, vay, vgy]) if len(vax) else road_y
    if len(all_x) == 0:
        return None

    min_x = float(all_x.min()) - margin
    max_x = float(all_x.max()) + margin
    min_y = float(all_y.min()) - margin
    max_y = float(all_y.max()) + margin

    world_w = max(max_x - min_x, 1.0)
    world_h = max(max_y - min_y, 1.0)
    scale = min(px_per_meter, 8192.0 / max(world_w, world_h))
    img_w = max(int(world_w * scale), 1)
    img_h = max(int(world_h * scale), 1)

    return {
        "min_x": min_x, "max_x": max_x,
        "min_y": min_y, "max_y": max_y,
        "scale": scale, "img_w": img_w, "img_h": img_h,
    }


def _world_to_px(x: float, y: float, bounds: dict) -> tuple[int, int]:
    return (
        int((x - bounds["min_x"]) * bounds["scale"]),
        int((bounds["max_y"] - y) * bounds["scale"]),
    )


# ── Static background rendering ───────────────────────────────────────────────

def render_static_bg(env, bounds: dict, style: RenderStyle) -> "Image.Image":
    """Render the scene background into a PIL Image: lanes, road edges, parked vehicles.

    This layer does not change between simulation steps. Call once after env.reset()
    and reuse the result every frame via agent_frame_data() + encode_image().

    Supersampling (style.supersample > 1) draws at a higher resolution then
    downscales with LANCZOS for clean anti-aliased lines.
    """
    from PIL import Image, ImageDraw

    min_x, max_y = bounds["min_x"], bounds["max_y"]
    scale = bounds["scale"]
    img_w, img_h = bounds["img_w"], bounds["img_h"]
    ss = max(1, style.supersample)
    draw_scale = scale * ss
    draw_w, draw_h = img_w * ss, img_h * ss

    def to_px(x: float, y: float) -> tuple[int, int]:
        return int((x - min_x) * draw_scale), int((max_y - y) * draw_scale)

    img = Image.new("RGB", (draw_w, draw_h), style.bg_color)
    draw = ImageDraw.Draw(img)

    # Lane centerlines (drawn beneath road edges)
    lanes = env.get_lane_polylines()
    lane_x, lane_y = lanes["x"], lanes["y"]
    lane_px_w = max(1, int(style.lane_width * draw_scale))
    ptr = 0
    for length in lanes["lengths"]:
        if length >= 2:
            pts = [to_px(lane_x[ptr + i], lane_y[ptr + i]) for i in range(length)]
            draw.line(pts, fill=style.lane_color, width=lane_px_w)
        ptr += int(length)

    # Road edges
    roads = env.get_road_edge_polylines()
    road_x, road_y = roads["x"], roads["y"]
    road_px_w = max(1, int(style.road_width * draw_scale))
    ptr = 0
    for length in roads["lengths"]:
        if length >= 2:
            pts = [to_px(road_x[ptr + i], road_y[ptr + i]) for i in range(length)]
            draw.line(pts, fill=style.road_color, width=road_px_w)
        ptr += int(length)

    if ss > 1:
        img = img.resize((img_w, img_h), Image.LANCZOS)
    return img


def encode_image(img: "Image.Image") -> str:
    """Encode a PIL Image to a lossless base64 PNG data URI."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def road_background_data(env, bounds: dict, style: RenderStyle) -> dict:
    """Extract lane and road-edge polylines as image-pixel data for JS canvas drawing.

    Returns a dict with colors, line widths, and polyline point lists in image-pixel
    coordinates. The JS renderer draws these directly on the canvas — crisp at any zoom.
    """
    scale = bounds["scale"]
    min_x, max_y = bounds["min_x"], bounds["max_y"]
    img_w, img_h = bounds["img_w"], bounds["img_h"]

    def to_pt(x: float, y: float) -> list:
        return [round((x - min_x) * scale, 1), round((max_y - y) * scale, 1)]

    def rgb_hex(t: tuple) -> str:
        return f"#{t[0]:02x}{t[1]:02x}{t[2]:02x}"

    lanes_data = env.get_lane_polylines()
    lx, ly = lanes_data["x"], lanes_data["y"]
    lane_segs = []
    ptr = 0
    for length in lanes_data["lengths"]:
        length = int(length)
        if length >= 2:
            lane_segs.append([to_pt(float(lx[ptr + i]), float(ly[ptr + i])) for i in range(length)])
        ptr += length

    roads_data = env.get_road_edge_polylines()
    road_x, road_y = roads_data["x"], roads_data["y"]
    road_segs = []
    ptr = 0
    for length in roads_data["lengths"]:
        length = int(length)
        if length >= 2:
            road_segs.append([to_pt(float(road_x[ptr + i]), float(road_y[ptr + i])) for i in range(length)])
        ptr += length

    return {
        "bg":         rgb_hex(style.bg_color),
        "lane_color": rgb_hex(style.lane_color),
        "road_color": rgb_hex(style.road_color),
        "lane_w":     round(max(0.5, style.lane_width * scale), 2),
        "road_w":     round(max(0.5, style.road_width * scale), 2),
        "lanes":      lane_segs,
        "roads":      road_segs,
        "img_w":      img_w,
        "img_h":      img_h,
    }


# ── Per-frame / per-scene data extraction ─────────────────────────────────────

def static_agent_data(env, bounds: dict) -> list[dict]:
    """Extract static (parked) vehicle states as pixel-space render data for the JS canvas.

    Each dict: cx, cy (center, image px), heading (canvas radians), hl, hw (half-dims, px).
    """
    scale = bounds["scale"]
    min_x, max_y = bounds["min_x"], bounds["max_y"]
    try:
        statics = env.get_static_agent_state()
    except Exception:
        return []
    sx, sy = statics["x"], statics["y"]
    s_headings, s_lengths, s_widths = statics["heading"], statics["length"], statics["width"]
    s_valid = _render_valid_mask(sx, sy, s_lengths)

    result = []
    for i in range(len(sx)):
        if not s_valid[i]:
            continue
        x, y = float(sx[i]), float(sy[i])
        cx = round((x - min_x) * scale, 2)
        cy = round((max_y - y) * scale, 2)
        result.append({
            "cx": cx, "cy": cy,
            "heading": round(-float(s_headings[i]), 4),
            "hl": round(max(1.0, (float(s_lengths[i]) / 2.0) * scale), 2),
            "hw": round(max(0.5, (float(s_widths[i])  / 2.0) * scale), 2),
            "slot": i,
            "id": str(i),
            "lx": round(cx + 2, 2),
            "ly": round(cy - 10, 2),
        })
    return result


def expert_frame_data(env, bounds: dict) -> list[dict]:
    """Extract current expert-agent states as pixel-space render data for the JS canvas.

    Expert agents follow recorded ground-truth trajectories and are rendered in orange.
    Each dict: cx, cy (center, image px), heading (canvas radians), hl, hw (half-dims, px).
    """
    scale = bounds["scale"]
    min_x, max_y = bounds["min_x"], bounds["max_y"]
    try:
        experts = env.get_expert_agent_state()
    except Exception:
        return []
    ex, ey = experts["x"], experts["y"]
    e_headings, e_lengths, e_widths = experts["heading"], experts["length"], experts["width"]
    e_valid = _render_valid_mask(ex, ey, e_lengths)

    result = []
    for i in range(len(ex)):
        if not e_valid[i]:
            continue
        x, y = float(ex[i]), float(ey[i])
        cx = (x - min_x) * scale
        cy = (max_y - y) * scale
        result.append({
            "cx": round(cx, 2),
            "cy": round(cy, 2),
            "heading": round(-float(e_headings[i]), 4),
            "hl": round(max(1.0, (float(e_lengths[i]) / 2.0) * scale), 2),
            "hw": round(max(0.5, (float(e_widths[i])  / 2.0) * scale), 2),
        })
    return result


def agent_frame_data(env, bounds: dict) -> list[dict]:
    """Extract current controlled-agent states as pixel-space render data for the JS canvas.

    Each dict: cx, cy (center, image px), heading (canvas radians, negated from world),
    hl, hw (half-dims, px), id (label), lx/ly (label anchor, image px).

    Float center+heading+dims instead of pre-computed integer corners avoids per-corner
    rounding distortion — JS rotates with ctx.translate/ctx.rotate at full precision.
    """
    scale = bounds["scale"]
    min_x, max_y = bounds["min_x"], bounds["max_y"]

    agents = env.get_global_agent_state()
    ax, ay = agents["x"], agents["y"]
    headings, lengths, widths = agents["heading"], agents["length"], agents["width"]
    agent_ids = agents["id"]
    valid_mask = _render_valid_mask(ax, ay, lengths)

    result = []
    for i in range(len(ax)):
        if not valid_mask[i]:
            continue
        x, y = float(ax[i]), float(ay[i])
        cx = (x - min_x) * scale
        cy = (max_y - y) * scale
        label = "SDC" if int(agent_ids[i]) == -2 else str(i)
        result.append({
            "cx": round(cx, 2), "cy": round(cy, 2),
            "heading": round(-float(headings[i]), 4),
            "hl": round(max(1.0, (float(lengths[i]) / 2.0  ) * scale), 2),
            "hw": round(max(0.5, (float(widths[i])  / 2.0  ) * scale), 2),
            "id": label,
            "slot": i,
            "lx": round(cx + 2, 2), "ly": round(cy - 10, 2),
        })
    return result


def goal_frame_data(env, bounds: dict, goal_overrides: dict | None = None, update_last: bool = True) -> list[dict]:
    """Compute goal-marker positions as image-fraction coords for the JS canvas overlay.

    Each dict describes one valid agent's goal:
      slot    : agent slot index
      fx, fy  : position as fractions [0, 1] of output-image width / height
      label   : display label

    Also updates last_goal_positions (needed by demo.py's handle_goal_drop) unless
    update_last=False (used when reading ghost env goals to avoid clobbering primary state).
    """
    global last_goal_positions

    agents = env.get_global_agent_state()
    ax, ay = agents["x"], agents["y"]
    lengths, agent_ids = agents["length"], agents["id"]
    valid_mask = _render_valid_mask(ax, ay, lengths)

    goal_x, goal_y = _goal_positions(env, agents)
    if goal_overrides:
        for slot, (wx, wy) in goal_overrides.items():
            if 0 <= slot < len(goal_x):
                goal_x[slot] = float(wx)
                goal_y[slot] = float(wy)

    img_w, img_h = bounds["img_w"], bounds["img_h"]
    to_px = _make_to_px(bounds)

    result = []
    for i in range(len(ax)):
        if not valid_mask[i]:
            continue
        gx_px, gy_px = to_px(float(goal_x[i]), float(goal_y[i]))
        label = "SDC" if int(agent_ids[i]) == -2 else str(i)
        result.append({"slot": i, "fx": gx_px / img_w, "fy": gy_px / img_h, "label": label})

    if update_last:
        last_goal_positions = result
    return result


# ── Simulation runner ─────────────────────────────────────────────────────────


_AGENT_STATUS_LABELS = {0: "Running", 1: "Paused", 2: "Crashed", 3: "Offroad", 4: "Goal reached"}


_last_recorded_actions: list = []


def collect_frames(
    env,
    num_steps: int = 91,
    save_every: int = 2,
    px_per_meter: float = 5.0,
    policy=None,
    style: "RenderStyle | None" = None,
    fixed_bounds: "dict | None" = None,
    replay_actions: "list | None" = None,
    diverge_step: int = 0,
) -> tuple[list[list[dict]], list[dict], dict, list[dict], list[list[str]], dict, list[list[dict]]]:
    """Run the simulation and collect rendering data for the browser.

    Returns:
        agent_render_frames  : per-frame dynamic agent data for JS canvas drawing.
        static_agents        : parked vehicle data (constant across all frames).
        map_data             : vector map data (lanes, roads, colors) for JS canvas drawing.
        agent_states         : per-frame world-space positions for server-side hit-testing.
        agent_status_frames  : per-frame status strings, one per agent slot.
        bounds               : world-to-pixel mapping for coordinate conversions.
        expert_render_frames : per-frame expert agent data for JS canvas drawing.

    Pass fixed_bounds to reuse an existing world-to-pixel mapping (e.g. ghost env overlay
    must share the primary env's coordinate space to align on the same canvas).
    """
    global initial_goal_positions, last_render_transform, _resim_step, _resim_total
    _resim_total = num_steps
    _resim_step = 0

    if style is None:
        style = RenderStyle()

    if fixed_bounds is not None:
        bounds = fixed_bounds
    else:
        bounds = compute_render_bounds(env, px_per_meter=px_per_meter)
        if bounds is None:
            return [], [], {}, [], [], {}, []
        last_render_transform = {
            "min_x": bounds["min_x"], "max_y": bounds["max_y"],
            "scale": bounds["scale"], "img_w": bounds["img_w"], "img_h": bounds["img_h"],
        }

    map_data = road_background_data(env, bounds, style)
    static_agents = static_agent_data(env, bounds)

    num_agents = env.num_agents
    # sticky terminal reason per agent slot: once set, persists across frames.
    terminal_reasons: dict[int, str] = {}

    agent_render_frames: list[list[dict]] = []
    expert_render_frames: list[list[dict]] = []
    agent_states: list[dict] = []
    agent_status_frames: list[list[str]] = []
    lstm_state: dict = {"lstm_h": None, "lstm_c": None, "hidden": None}
    recorded_actions: list = []
    first_frame = True

    for step in range(num_steps):
        _resim_step = step
        if step % save_every == 0:
            if first_frame:
                if fixed_bounds is None:
                    initial_goal_positions = goal_frame_data(env, bounds)
                first_frame = False

            agent_render_frames.append(agent_frame_data(env, bounds))
            expert_render_frames.append(expert_frame_data(env, bounds))

            agents = env.get_global_agent_state()
            ax, ay, lengths = agents["x"], agents["y"], agents["length"]
            valid = _render_valid_mask(ax, ay, lengths).tolist()
            agent_states.append({"x": ax.tolist(), "y": ay.tolist(), "valid": valid})

            frame_statuses = []
            for i in range(num_agents):
                if i in terminal_reasons:
                    frame_statuses.append(terminal_reasons[i])
                elif valid[i]:
                    frame_statuses.append("Running")
                else:
                    frame_statuses.append("Crashed")
            agent_status_frames.append(frame_statuses)

        if replay_actions is not None and step < diverge_step and step < len(replay_actions):
            actions = replay_actions[step]
        elif policy is not None:
            import torch
            obs = torch.tensor(env.observations, dtype=torch.float32)
            with torch.no_grad():
                if hasattr(policy, "forward_eval"):
                    logits, _ = policy.forward_eval(obs, lstm_state)
                else:
                    logits, _ = policy(obs)
            if policy.is_continuous:
                actions = logits.mean.cpu().numpy()
            else:
                if isinstance(logits, (list, tuple)):
                    actions = np.stack([l.argmax(-1).cpu().numpy() for l in logits], axis=1)
                else:
                    actions = logits.argmax(-1, keepdim=True).cpu().numpy()
        else:
            actions = env.action_space.sample()
        recorded_actions.append(actions)
        env.step(actions)

        # Read statuses immediately after step so crash/offroad metrics are still set.
        try:
            raw_statuses = env.get_agent_statuses()
            for i in range(min(num_agents, len(env.terminals))):
                if env.terminals[i] and i not in terminal_reasons:
                    if env.rewards[i] > 0.5:
                        terminal_reasons[i] = "Goal reached"
                    else:
                        terminal_reasons[i] = _AGENT_STATUS_LABELS.get(int(raw_statuses[i]), "Crashed")
        except Exception:
            pass

    global _last_recorded_actions
    _last_recorded_actions = recorded_actions

    # ── Aggregate episode metrics from terminal_reasons ───────────────────────
    n_terminated = len(terminal_reasons)
    n_goal      = sum(1 for r in terminal_reasons.values() if r == "Goal reached")
    n_collision = sum(1 for r in terminal_reasons.values() if r == "Crashed")
    n_offroad   = sum(1 for r in terminal_reasons.values() if r == "Offroad")
    denom = max(1, n_terminated)
    metrics = {
        "n_agents"        : num_agents,
        "n_terminated"    : n_terminated,
        "goal_rate"       : round(n_goal      / denom, 3),
        "collision_rate"  : round(n_collision / denom, 3),
        "offroad_rate"    : round(n_offroad   / denom, 3),
    }

    return agent_render_frames, static_agents, map_data, agent_states, agent_status_frames, bounds, expert_render_frames, metrics



def find_agent_at_pixel(
    click_img_x: float,
    click_img_y: float,
    frame_idx: int,
    agent_states: list[dict],
    bounds: dict,
    hit_radius: int = 30,
) -> int:
    """Return the index of the agent nearest to (click_img_x, click_img_y) in image pixels, or -1."""
    if not agent_states or frame_idx >= len(agent_states) or not bounds:
        return -1
    state = agent_states[frame_idx]
    best_idx = -1
    best_dist_sq = hit_radius * hit_radius
    for i, valid in enumerate(state["valid"]):
        if not valid:
            continue
        px, py = _world_to_px(state["x"][i], state["y"][i], bounds)
        dx = px - click_img_x
        dy = py - click_img_y
        dist_sq = dx * dx + dy * dy
        if dist_sq < best_dist_sq:
            best_dist_sq = dist_sq
            best_idx = i
    return best_idx


def find_static_agent_at_pixel(
    click_img_x: float,
    click_img_y: float,
    static_agents: list[dict],
    hit_radius: int = 30,
) -> int:
    """Return the slot of the static agent nearest to (click_img_x, click_img_y), or -1."""
    best_slot = -1
    best_dist_sq = hit_radius * hit_radius
    for a in static_agents:
        dx = a["cx"] - click_img_x
        dy = a["cy"] - click_img_y
        dist_sq = dx * dx + dy * dy
        if dist_sq < best_dist_sq:
            best_dist_sq = dist_sq
            best_slot = a["slot"]
    return best_slot


def find_expert_at_pixel(
    click_img_x: float,
    click_img_y: float,
    expert_frame: list[dict],
    hit_radius: int = 30,
) -> int:
    """Return the list index of the expert agent nearest to (click_img_x, click_img_y), or -1."""
    best_idx = -1
    best_dist_sq = hit_radius * hit_radius
    for i, a in enumerate(expert_frame):
        dx = a["cx"] - click_img_x
        dy = a["cy"] - click_img_y
        dist_sq = dx * dx + dy * dy
        if dist_sq < best_dist_sq:
            best_dist_sq = dist_sq
            best_idx = i
    return best_idx



# ── Lane-graph helpers ─────────────────────────────────────────────────────────

_LANE_CONNECT_THRESH = 3.0  # metres: max gap between lane end → next lane start


def build_lane_graph(env) -> tuple[list, dict]:
    """Parse env lane polylines into a directed graph for trajectory planning.

    Returns
    -------
    lanes : list of np.ndarray, shape (N,2)
        World-coordinate points for each lane polyline.
    successors : dict[int, list[int]]
        successor_lanes[i] = list of lane indices whose start is close to
        lane i's end (within _LANE_CONNECT_THRESH metres).
    """
    data = env.get_lane_polylines()
    lx, ly = np.asarray(data["x"], dtype=np.float32), np.asarray(data["y"], dtype=np.float32)
    lengths = data["lengths"]

    lanes: list[np.ndarray] = []
    ptr = 0
    for length in lengths:
        n = int(length)
        if n >= 2:
            pts = np.stack([lx[ptr:ptr + n], ly[ptr:ptr + n]], axis=1)
            lanes.append(pts)
        ptr += n

    ends   = np.array([lane[-1] for lane in lanes], dtype=np.float32)
    starts = np.array([lane[0]  for lane in lanes], dtype=np.float32)

    successors: dict[int, list[int]] = {i: [] for i in range(len(lanes))}
    thresh2 = _LANE_CONNECT_THRESH ** 2
    for i, end in enumerate(ends):
        dists2 = np.sum((starts - end) ** 2, axis=1)
        for j in np.where(dists2 <= thresh2)[0]:
            if j != i:
                successors[i].append(int(j))

    return lanes, successors


def _project_point_to_segment(px: float, py: float, ax: float, ay: float,
                               bx: float, by: float) -> tuple[float, float, float]:
    """Return (closest_x, closest_y, t) with t in [0,1] along segment AB."""
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 < 1e-12:
        return ax, ay, 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    return ax + t * dx, ay + t * dy, t


def _nearest_lane_point(x: float, y: float, lanes: list) -> tuple[int, int, float]:
    """Return (lane_idx, segment_idx, t) for the closest point on any lane."""
    best_dist2 = float("inf")
    best_lane = best_seg = 0
    best_t = 0.0
    for li, lane in enumerate(lanes):
        for si in range(len(lane) - 1):
            cx, cy, t = _project_point_to_segment(
                x, y,
                float(lane[si, 0]), float(lane[si, 1]),
                float(lane[si + 1, 0]), float(lane[si + 1, 1]),
            )
            d2 = (cx - x) ** 2 + (cy - y) ** 2
            if d2 < best_dist2:
                best_dist2, best_lane, best_seg, best_t = d2, li, si, t
    return best_lane, best_seg, best_t


def compute_lane_trajectory(
    env,
    sx: float, sy: float,
    ex: float, ey: float,
    num_steps: int,
    lanes: list | None = None,
    successors: dict | None = None,
) -> tuple | None:
    """BFS lane-graph path from (sx,sy) to (ex,ey), sampled to num_steps waypoints.

    Returns (xs, ys, headings) as float32 numpy arrays of length num_steps,
    or None if no connecting path exists.
    """
    if lanes is None or successors is None:
        lanes, successors = build_lane_graph(env)
    if not lanes:
        return None

    start_lane, start_seg, start_t = _nearest_lane_point(sx, sy, lanes)
    end_lane,   end_seg,   end_t   = _nearest_lane_point(ex, ey, lanes)

    # BFS from start_lane to end_lane
    from collections import deque
    queue: deque = deque([(start_lane, [start_lane])])
    visited = {start_lane}
    found_path: list[int] | None = None

    if start_lane == end_lane:
        found_path = [start_lane]
    else:
        while queue:
            node, path = queue.popleft()
            for nxt in successors.get(node, []):
                if nxt not in visited:
                    new_path = path + [nxt]
                    if nxt == end_lane:
                        found_path = new_path
                        break
                    visited.add(nxt)
                    queue.append((nxt, new_path))
            if found_path is not None:
                break

    if found_path is None:
        return None

    # Concatenate world-coordinate points along the path, trimming to start/end projections.
    # i0 = start_seg + 1: always skip to the point *after* the snap so the first step is forward.
    # i1 = end_seg: include points only up to the snap segment's start, then append proj_e.
    path_pts: list[np.ndarray] = []
    for lane_idx in found_path:
        lane = lanes[lane_idx]
        if lane_idx == start_lane and lane_idx == end_lane:
            i0 = start_seg + 1
            i1 = end_seg
            proj_s = np.array([[sx, sy]], dtype=np.float32)
            mid_pts = lane[i0:i1 + 1] if i0 <= i1 else np.empty((0, 2), dtype=np.float32)
            proj_e = np.array([[ex, ey]], dtype=np.float32)
            path_pts.append(np.concatenate([proj_s, mid_pts, proj_e]))
        elif lane_idx == start_lane:
            i0 = start_seg + 1
            proj_s = np.array([[sx, sy]], dtype=np.float32)
            path_pts.append(np.concatenate([proj_s, lane[i0:]]))
        elif lane_idx == end_lane:
            i1 = end_seg
            proj_e = np.array([[ex, ey]], dtype=np.float32)
            path_pts.append(np.concatenate([lane[:i1 + 1], proj_e]))
        else:
            path_pts.append(lane)

    pts = np.concatenate(path_pts, axis=0)  # (M, 2)

    diffs = np.diff(pts, axis=0)
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = float(cum[-1])
    if total < 1e-6:
        return None

    t_sample = np.linspace(0.0, total, num_steps, dtype=np.float32)
    xs = np.interp(t_sample, cum, pts[:, 0]).astype(np.float32)
    ys = np.interp(t_sample, cum, pts[:, 1]).astype(np.float32)

    dx = np.gradient(xs)
    dy = np.gradient(ys)
    hs = np.arctan2(dy, dx).astype(np.float32)

    return xs, ys, hs
