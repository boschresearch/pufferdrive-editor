# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..state import State
from ..constants.colors import _BG0, _BG1, _BG2, _ACCENT, _TEXT, _TEXT2, _BORDER, _MONO


def _row(label: str, value: rx.Component) -> rx.Component:
    return rx.flex(
        rx.text(
            label,
            style=dict(
                color=_TEXT2,
                width="280px",
                flex_shrink="0",
                font_size="13px",
            ),
        ),
        rx.text(
            value,
            style=dict(
                color=_TEXT,
                font_family=_MONO,
                font_size="13px",
                word_break="break-all",
            ),
        ),
        style=dict(
            padding="5px 0",
            border_bottom=f"1px solid {_BORDER}",
            align_items="flex-start",
        ),
    )


def _section(title: str, *rows: rx.Component) -> rx.Component:
    return rx.box(
        rx.text(
            title,
            style=dict(
                font_size="11px",
                font_weight="700",
                letter_spacing="0.1em",
                text_transform="uppercase",
                color=_ACCENT,
                padding="10px 0 6px",
                margin_bottom="4px",
                border_bottom=f"2px solid {_ACCENT}",
            ),
        ),
        *rows,
        style=dict(margin_bottom="28px"),
    )


def debug_page() -> rx.Component:
    return rx.box(
        # Header
        rx.flex(
            rx.text(
                "Debug",
                style=dict(
                    font_size="18px",
                    font_weight="700",
                    color=_TEXT,
                    letter_spacing="0.05em",
                ),
            ),
            rx.link(
                "← Back to app",
                href="/",
                style=dict(
                    color=_ACCENT,
                    font_size="13px",
                    text_decoration="none",
                ),
            ),
            style=dict(
                padding="14px 24px",
                background=_BG1,
                border_bottom=f"1px solid {_BORDER}",
                align_items="center",
                justify_content="space-between",
            ),
        ),
        # Body
        rx.box(
            _section(
                "Load Status",
                _row("is_loaded", State.is_loaded.to_string()),
                _row("is_busy", State.is_busy.to_string()),
                _row("status", State.status),
            ),
            _section(
                "Map / Config",
                _row("selected_ini_path", State.selected_ini_path),
                _row("selected_split", State.selected_split),
                _row("selected_map", State.selected_map.to_string()),
                _row("selected_map_path", State.selected_map_path),
                _row("map_count", State.map_count.to_string()),
            ),
            _section(
                "Policy",
                _row("selected_policy_name", State.selected_policy_name),
                _row("selected_policy_path", State.selected_policy_path),
                _row("policy_is_random", State.policy_is_random.to_string()),
                _row("policy_load_error", State.policy_load_error),
            ),
            _section(
                "Ghost Environment",
                _row("ghost_env_active", State.ghost_env_active.to_string()),
                _row("env_focus", State.env_focus),
                _row("ghost_policy_name", State.ghost_policy_name),
                _row("ghost_policy_is_random", State.ghost_policy_is_random.to_string()),
                _row("ghost_policy_load_error", State.ghost_policy_load_error),
                _row("ghost_diverge_frame", State.ghost_diverge_frame.to_string()),
                _row("agent_place_target", State.agent_place_target),
                _row("static_place_target", State.static_place_target),
            ),
            _section(
                "Playback",
                _row("current_frame", State.current_frame.to_string()),
                _row("num_frames", State.num_frames.to_string()),
                _row("is_playing", State.is_playing.to_string()),
                _row("play_speed", State.play_speed.to_string()),
                _row("loop_enabled", State.loop_enabled.to_string()),
            ),
            _section(
                "Tools / UI",
                _row("select_mode", State.select_mode.to_string()),
                _row("goal_edit_mode", State.goal_edit_mode.to_string()),
                _row("agent_place_mode", State.agent_place_mode.to_string()),
                _row("static_agent_place_mode", State.static_agent_place_mode.to_string()),
                _row("expert_place_mode", State.expert_place_mode.to_string()),
                _row("show_goals", State.show_goals.to_string()),
                _row("show_goal_radius", State.show_goal_radius.to_string()),
                _row("show_labels", State.show_labels.to_string()),
            ),
            _section(
                "Agent Selection",
                _row("selected_agent_idx", State.selected_agent_idx.to_string()),
                _row("selected_agent_label", State.selected_agent_label),
                _row("selected_static_slot_str", State.selected_static_slot_str),
                _row("selected_expert_idx", State.selected_expert_idx.to_string()),
                _row("selected_native_expert_idx", State.selected_native_expert_idx.to_string()),
                _row("selected_goal_slot", State.selected_goal_slot.to_string()),
            ),
            _section(
                "Agent Counts",
                _row("demo_slots_used", State.demo_slots_used.to_string()),
                _row("demo_slots_total", State.demo_slots_total.to_string()),
                _row("demo_slots_remaining", State.demo_slots_remaining.to_string()),
                _row("user_agent_count", State.user_agent_count.to_string()),
                _row("user_static_agent_count", State.user_static_agent_count.to_string()),
                _row("user_expert_count", State.user_expert_count.to_string()),
                _row("ghost_user_agent_count", State.ghost_user_agent_count.to_string()),
                _row("ghost_user_static_agent_count", State.ghost_user_static_agent_count.to_string()),
                _row("ghost_user_expert_count", State.ghost_user_expert_count.to_string()),
            ),
            _section(
                "Simulation",
                _row("sim_steps", State.sim_steps.to_string()),
                _row("sim_steps_editing", State.sim_steps_editing.to_string()),
            ),
            _section(
                "Globals Cache",
                _row("dbg_env_loaded", State.dbg_env_loaded.to_string()),
                _row("dbg_ghost_env_loaded", State.dbg_ghost_env_loaded.to_string()),
                _row("dbg_policy_loaded", State.dbg_policy_loaded.to_string()),
                _row("dbg_ghost_policy_loaded", State.dbg_ghost_policy_loaded.to_string()),
                _row("dbg_frame_cache_size", State.dbg_frame_cache_size.to_string()),
                _row("dbg_sim_steps", State.dbg_sim_steps.to_string()),
            ),
            style=dict(
                padding="24px 32px",
                max_width="900px",
                margin="0 auto",
            ),
        ),
        style=dict(
            display="flex",
            flex_direction="column",
            min_height="100vh",
            background=_BG0,
            color=_TEXT,
            font_family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            overflow_y="auto",
        ),
    )
