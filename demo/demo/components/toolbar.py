# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..state import State
from ..constants.colors import _BG1, _BG2, _ACCENT, _ACCENT_DIM, _TEXT, _TEXT2, _BORDER, _MONO
from ..constants.styles import _BTN, _TOOL_BTN_STYLE
from ..constants.icons import (
    _ICON_PAN, _ICON_SELECT, _ICON_GOAL, _ICON_ADD_AGENT,
    _ICON_ADD_STATIC, _ICON_ADD_EXPERT, _ICON_RESET, _ICON_MIRROR, _ICON_MOVE,
)
from ..constants.css import _TOOLBAR_CSS

def _tool_item(btn: rx.Component, label: str) -> rx.Component:
    """Icon button stacked with a short text label beneath it."""
    return rx.box(
        btn,
        rx.text(label, style=dict(
            font_size="9px",
            color=_TEXT2,
            text_align="center",
            line_height="1",
            user_select="none",
            pointer_events="none",
        )),
        style=dict(display="flex", flex_direction="column", align_items="center", gap="2px"),
    )


def toolbar() -> rx.Component:
    _panel_style = dict(
        display="flex",
        flex_direction="column",
        gap="4px",
        padding_top="4px",
        border_top=f"1px solid {_BORDER}",
    )
    _small_btn = {**_BTN, "background": _ACCENT_DIM, "color": _TEXT,
                  "font_size": "11px", "padding": "4px 10px",
                  "opacity": rx.cond(State.is_busy, "0.45", "1")}

    goal_panel = rx.cond(
        State.goal_edit_mode,
        rx.box(
            rx.text(State.goal_edit_hint,
                    style=dict(font_size="11px", color=_TEXT2,
                               white_space="nowrap", padding="2px 4px",
                               font_family=_MONO)),
            style=_panel_style,
        ),
        rx.box(),
    )

    def _size_row(sizes, active_size, on_click_map):
        return rx.box(
            rx.text("Size:", style=dict(font_size="9px", color=_TEXT2,
                                        font_family=_MONO, margin_right="4px",
                                        user_select="none")),
            *[
                rx.button(
                    sz,
                    on_click=on_click_map[sz],
                    class_name=rx.cond(
                        active_size == sz,
                        "pd-size-btn pd-size-active",
                        "pd-size-btn",
                    ),
                )
                for sz in sizes
            ],
            style=dict(display="flex", flex_direction="row", align_items="center",
                       gap="3px", padding="4px 4px 2px 4px", flex_wrap="nowrap"),
        )

    _SIZES = ["S", "M", "L", "XL"]

    agent_panel = rx.cond(
        State.agent_place_mode,
        rx.box(
            _size_row(_SIZES, State.agent_size, {
                "S": State.set_agent_size("S"), "M": State.set_agent_size("M"),
                "L": State.set_agent_size("L"), "XL": State.set_agent_size("XL"),
            }),
            rx.text("1. Click position  2. Click direction  3. Click goal",
                    style=dict(font_size="11px", color=_TEXT2,
                               white_space="nowrap", padding="2px 4px",
                               font_family=_MONO)),
            style=_panel_style,
        ),
        rx.box(),
    )

    static_agent_panel = rx.cond(
        State.static_agent_place_mode,
        rx.box(
            _size_row(_SIZES, State.static_size, {
                "S": State.set_static_size("S"), "M": State.set_static_size("M"),
                "L": State.set_static_size("L"), "XL": State.set_static_size("XL"),
            }),
            rx.text("1. Click position  2. Click direction",
                    style=dict(font_size="11px", color=_TEXT2,
                               white_space="nowrap", padding="2px 4px",
                               font_family=_MONO)),
            style=_panel_style,
        ),
        rx.box(),
    )

    expert_agent_panel = rx.cond(
        State.expert_place_mode,
        rx.box(
            _size_row(_SIZES, State.expert_size, {
                "S": State.set_expert_size("S"), "M": State.set_expert_size("M"),
                "L": State.set_expert_size("L"), "XL": State.set_expert_size("XL"),
            }),
            rx.text("1. Click start  2. Click goal (follows road lane)",
                    style=dict(font_size="11px", color=_TEXT2,
                               white_space="nowrap", padding="2px 4px",
                               font_family=_MONO)),
            style=_panel_style,
        ),
        rx.box(),
    )

    move_panel = rx.cond(
        State.move_mode,
        rx.box(
            rx.text("1. Drag a car  2. Click to aim heading  (fixed trajectories snap to a lane)",
                    style=dict(font_size="11px", color=_TEXT2,
                               white_space="nowrap", padding="2px 4px",
                               font_family=_MONO)),
            style=_panel_style,
        ),
        rx.box(),
    )

    return rx.box(
        rx.el.style(_TOOLBAR_CSS),
        rx.box(
            _tool_item(
                rx.button(
                    rx.html(_ICON_PAN, style=dict(display="contents")),
                    id="pd-tool-pan",
                    title="Pan — drag to move view",
                    data_tool="pan",
                    on_click=State.set_tool_pan,
                    class_name=rx.cond(State.pan_active, "pd-tool-btn pd-tool-active", "pd-tool-btn"),
                    style=_TOOL_BTN_STYLE,
                ),
                "Pan",
            ),
            _tool_item(
                rx.button(
                    rx.html(_ICON_SELECT, style=dict(display="contents")),
                    id="pd-tool-select",
                    title="Select vehicle — click to show trajectory",
                    data_tool="select",
                    on_click=State.set_tool_select,
                    class_name=rx.cond(State.select_mode, "pd-tool-btn pd-tool-active", "pd-tool-btn"),
                    style=_TOOL_BTN_STYLE,
                ),
                "Select",
            ),
            rx.cond(
                State.is_loaded,
                _tool_item(
                    rx.button(
                        rx.html(_ICON_MOVE, style=dict(display="contents")),
                        id="pd-tool-move",
                        title="Move — drag a car to a new spot, then click to aim its heading",
                        data_tool="move",
                        on_click=State.toggle_move,
                        class_name=rx.cond(State.move_mode, "pd-tool-btn pd-tool-active", "pd-tool-btn"),
                        style=_TOOL_BTN_STYLE,
                    ),
                    "Move",
                ),
                rx.box(),
            ),
            rx.cond(
                State.is_loaded,
                _tool_item(
                    rx.button(
                        rx.html(_ICON_GOAL, style=dict(display="contents")),
                        id="pd-tool-goal",
                        title="Set Goal — drag a goal marker to reposition it",
                        data_tool="goal",
                        on_click=State.toggle_goal_edit,
                        class_name=rx.cond(
                            State.goal_edit_mode,
                            "pd-tool-btn pd-tool-active",
                            "pd-tool-btn",
                        ),
                        style=_TOOL_BTN_STYLE,
                    ),
                    "Goals",
                ),
                rx.box(),
            ),
            rx.cond(
                State.is_loaded,
                _tool_item(
                    rx.button(
                        rx.html(_ICON_ADD_AGENT, style=dict(display="contents")),
                        id="pd-tool-add-agent",
                        title="Add Agent — 3 clicks: position, direction, goal",
                        data_tool="add_agent",
                        on_click=State.toggle_agent_place,
                        class_name=rx.cond(
                            State.agent_place_mode,
                            "pd-tool-btn pd-tool-active",
                            "pd-tool-btn",
                        ),
                        style=_TOOL_BTN_STYLE,
                    ),
                    "Agent",
                ),
                rx.box(),
            ),
            rx.cond(
                State.is_loaded,
                rx.fragment(
                    _tool_item(
                        rx.button(
                            rx.html(_ICON_ADD_STATIC, style=dict(display="contents")),
                            id="pd-tool-add-static",
                            title="Add Static — 2 clicks: position, direction",
                            data_tool="add_static",
                            on_click=State.toggle_static_agent_place,
                            class_name=rx.cond(
                                State.static_agent_place_mode,
                                "pd-tool-btn pd-tool-active",
                                "pd-tool-btn",
                            ),
                            style=_TOOL_BTN_STYLE,
                        ),
                        "Static",
                    ),
                    _tool_item(
                        rx.button(
                            rx.html(_ICON_ADD_EXPERT, style=dict(display="contents")),
                            id="pd-tool-add-expert",
                            title="Add Fixed Trajectory — 2 clicks: start, goal (follows road lane)",
                            data_tool="add_expert",
                            on_click=State.toggle_expert_place,
                            disabled=State.expert_slots_full,
                            class_name=rx.cond(
                                State.expert_place_mode,
                                "pd-tool-btn pd-tool-active",
                                "pd-tool-btn",
                            ),
                            style=_TOOL_BTN_STYLE,
                        ),
                        "Fixed Trajectory",
                    ),
                ),
                rx.box(),
            ),
            rx.cond(
                State.ghost_env_active & State.is_loaded,
                _tool_item(
                    rx.button(
                        rx.html(_ICON_MIRROR, style=dict(display="contents")),
                        id="pd-tool-mirror",
                        title="Mirror — place agents and goals in both envs simultaneously",
                        on_click=State.toggle_mirror_placement,
                        class_name=rx.cond(
                            State.mirror_placement,
                            "pd-tool-btn pd-tool-active",
                            "pd-tool-btn",
                        ),
                        style=_TOOL_BTN_STYLE,
                    ),
                    "Both",
                ),
                rx.box(),
            ),
            rx.cond(
                State.is_loaded,
                _tool_item(
                    rx.button(
                        rx.html(_ICON_RESET, style=dict(display="contents")),
                        id="pd-tool-reset",
                        title="Reset to default — clear all placed agents and goal overrides",
                        on_click=State.reset_to_default,
                        disabled=State.is_busy,
                        class_name="pd-tool-btn",
                        style=_TOOL_BTN_STYLE,
                    ),
                    "Reset",
                ),
                rx.box(),
            ),
            style=dict(display="flex", gap="4px"),
        ),
        goal_panel,
        agent_panel,
        static_agent_panel,
        expert_agent_panel,
        move_panel,
        class_name=rx.cond(
            State.mirror_placement & State.ghost_env_active,
            "pd-toolbar-mirror",
            rx.cond(
                State.ghost_env_active & (State.env_focus == "ghost"),
                "pd-toolbar-ghost",
                "",
            ),
        ),
        style=dict(
            position="absolute",
            top="12px",
            left="12px",
            display="flex",
            flex_direction="column",
            gap="4px",
            background=rx.cond(
                State.mirror_placement & State.ghost_env_active,
                f"linear-gradient(135deg, rgba(8,145,178,0.15) 50%, rgba(124,58,237,0.15) 50%)",
                rx.cond(
                    State.ghost_env_active & (State.env_focus == "ghost"),
                    "rgba(46,16,101,0.97)",
                    _BG1,
                ),
            ),
            padding="4px",
            border_radius="8px",
            border=rx.cond(
                State.mirror_placement & State.ghost_env_active,
                "1px solid transparent",
                rx.cond(
                    State.ghost_env_active & (State.env_focus == "ghost"),
                    "1px solid rgba(124,58,237,0.6)",
                    f"1px solid {_BORDER}",
                ),
            ),
            box_shadow=rx.cond(
                State.mirror_placement & State.ghost_env_active,
                "-2px -2px 0 1px #0891b2, 2px 2px 0 1px #7c3aed, 0 0 14px rgba(8,145,178,0.25)",
                rx.cond(
                    State.ghost_env_active & (State.env_focus == "ghost"),
                    "0 0 12px rgba(124,58,237,0.3)",
                    "none",
                ),
            ),
            z_index="10",
            transition="background 0.2s, border 0.2s, box-shadow 0.2s",
        ),
    )


