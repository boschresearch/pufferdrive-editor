# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..state import State
from ..globals import MAX_AGENTS
from ..constants.colors import _BG1, _BG2, _ACCENT, _TEXT, _TEXT2, _BORDER, _MONO
from ..constants.styles import _SEC_LABEL
from ..constants.icons import _ICON_EYE, _ICON_EYE_OFF
from ..constants.css import _AGENT_ROW_CSS

def _status_dot(status: rx.Var) -> rx.Component:
    """Colored circle whose color depends on the status string Var."""
    color = rx.cond(
        status == "Running",      "#22c55e",
        rx.cond(status == "Goal reached", "#eab308",
        rx.cond(status == "Crashed",      "#ef4444",
        rx.cond(status == "Offroad",      "#f97316",
                                          "#94a3b8"))))
    return rx.box(style=dict(
        width="8px", height="8px", border_radius="50%",
        background=color, flex_shrink="0",
    ))


def _type_tag(type_str: rx.Var) -> rx.Component:
    """Small coloured pill: blue for 'default', red for 'added'."""
    bg = rx.cond(type_str == "added", "#7f1d1d", "#0c4a6e")
    fg = rx.cond(type_str == "added", "#fca5a5", "#7dd3fc")
    return rx.box(
        rx.text(type_str, style=dict(font_size="9px", font_weight="600", color=fg,
                                     line_height="1", white_space="nowrap")),
        style=dict(background=bg, border_radius="3px", padding="2px 5px", flex_shrink="0"),
    )


def _agent_row(item: list, *, ghost: bool = False) -> rx.Component:
    """item = [id_str, label, status_str, type_str, user_idx_str, sdc_str]"""
    agent_id_str = item[0]
    label = item[1]
    status = item[2]
    type_str = item[3]
    user_idx = item[4]
    is_sdc = item[5] == "sdc"

    if ghost:
        is_selected = State.selected_ghost_agent_str == agent_id_str
        remove_user_fn = State.remove_ghost_user_agent(user_idx)
        remove_default_fn = State.remove_ghost_vehicle(agent_id_str)
        policy_is_random = State.ghost_policy_is_random
        policy_name_var = State.ghost_policy_display_name
        active_class = "pd-ghost-active-agent-row"
        row_id = "pd-ghost-agent-row-" + agent_id_str
        select_fn = State.select_ghost_agent(agent_id_str)
    else:
        is_selected = State.selected_agent_str == agent_id_str
        remove_user_fn = State.remove_user_agent(user_idx)
        remove_default_fn = State.remove_vehicle(agent_id_str)
        policy_is_random = State.policy_is_random
        policy_name_var = State.selected_policy_display_name
        active_class = "pd-active-agent-row"
        row_id = "pd-agent-row-" + agent_id_str
        select_fn = State.select_agent(agent_id_str)

    row_class = rx.cond(
        is_selected,
        f"pd-agent-row {active_class} pd-agent-selected",
        f"pd-agent-row {active_class}",
    )

    return rx.box(
        rx.box(
            rx.text(
                rx.cond(is_sdc, agent_id_str, label),
                style=dict(
                    font_weight=rx.cond(is_selected, "700", "500"),
                    font_size="12px", color=_TEXT, flex="1",
                ),
            ),
            rx.cond(is_sdc, _sdc_badge(), rx.fragment()),
            _type_tag(type_str),
            rx.cond(
                type_str == "added",
                rx.button("×", on_click=remove_user_fn,
                          style=dict(background="transparent", border="none", color=_TEXT2,
                                     font_size="18px", line_height="1", padding="0 0 0 4px",
                                     cursor="pointer", flex_shrink="0")),
                rx.button("×", on_click=remove_default_fn,
                          style=dict(background="transparent", border="none", color=_TEXT2,
                                     font_size="18px", line_height="1", padding="0 0 0 4px",
                                     cursor="pointer", flex_shrink="0")),
            ),
            style=dict(display="flex", align_items="center", gap="4px"),
        ),
        rx.box(
            _status_dot(status),
            rx.text(status, style=dict(font_size="10px")),
            rx.cond(
                policy_is_random,
                rx.box(
                    rx.text("random actions", style=dict(
                        font_size="9px", font_weight="700", color="#ea580c", line_height="1",
                    )),
                    style=dict(
                        background="rgba(234,88,12,0.15)", border="1px solid rgba(234,88,12,0.45)",
                        border_radius="3px", padding="2px 5px",
                    ),
                ),
                # Not random ⇒ a policy is loaded; the display-name var always resolves to
                # a real label (configured name, checkpoint stem, or "default").
                rx.box(
                    rx.text(policy_name_var, style=dict(
                        font_size="9px", font_weight="600", color="#7dd3fc", line_height="1",
                    )),
                    style=dict(
                        background="rgba(12,74,110,0.5)", border="1px solid rgba(125,211,252,0.25)",
                        border_radius="3px", padding="2px 5px",
                    ),
                ),
            ),
            class_name="pd-status-badge",
        ),
        id=row_id,
        class_name=row_class,
        on_click=select_fn,
        style=dict(cursor="pointer"),
    )


def _static_vehicle_row(item: list, *, ghost: bool = False) -> rx.Component:
    """item = [slot_str, type_str, user_idx_str, display_label]"""
    slot_str = item[0]
    type_str = item[1]
    user_idx = item[2]
    display_label = item[3]

    if ghost:
        is_selected = State.selected_ghost_static_slot_str == slot_str
        remove_user_fn = State.remove_ghost_user_static_agent(user_idx)
        remove_default_fn = State.remove_ghost_static_vehicle(slot_str)
        row_props = dict(
            id="pd-ghost-static-row-" + slot_str,
            on_click=State.select_ghost_static_agent(slot_str),
            class_name=rx.cond(is_selected, "pd-agent-row pd-agent-selected", "pd-agent-row"),
            style=dict(cursor="pointer"),
        )
    else:
        is_selected = State.selected_static_slot_str == slot_str
        remove_user_fn = State.remove_user_static_agent(user_idx)
        remove_default_fn = State.remove_static_vehicle(slot_str)
        row_props = dict(
            id="pd-static-row-" + slot_str,
            on_click=State.select_static_agent(slot_str),
            class_name=rx.cond(is_selected, "pd-agent-row pd-agent-selected", "pd-agent-row"),
            style=dict(cursor="pointer"),
        )

    return rx.box(
        rx.box(
            rx.text(display_label, style=dict(font_weight="500", font_size="12px", color=_TEXT, flex="1")),
            _type_tag(type_str),
            rx.cond(
                type_str == "added",
                rx.button("×", on_click=remove_user_fn,
                          style=dict(background="transparent", border="none", color=_TEXT2,
                                     font_size="18px", line_height="1", padding="0 0 0 4px",
                                     cursor="pointer", flex_shrink="0")),
                rx.button("×", on_click=remove_default_fn,
                          style=dict(background="transparent", border="none", color=_TEXT2,
                                     font_size="18px", line_height="1", padding="0 0 0 4px",
                                     cursor="pointer", flex_shrink="0")),
            ),
            style=dict(display="flex", align_items="center", gap="4px"),
        ),
        **row_props,
    )


def _sdc_badge() -> rx.Component:
    """Small teal pill label for native SDC (expert trajectory) agents."""
    return rx.box(
        rx.text("SDC", style=dict(font_size="9px", font_weight="700", color="#5eead4",
                                  line_height="1", white_space="nowrap")),
        style=dict(background="rgba(20,184,166,0.15)", border="1px solid rgba(94,234,212,0.35)",
                   border_radius="3px", padding="2px 5px", flex_shrink="0"),
    )


def _expert_row(item: list) -> rx.Component:
    """item = [idx_str, type_str]  — type_str is 'default' (SDC) or 'added' (user-placed)"""
    idx_str = item[0]
    type_str = item[1]
    return rx.box(
        rx.text(idx_str, style=dict(font_weight="500", font_size="12px", color=_TEXT, flex="1")),
        rx.cond(
            type_str == "default",
            _sdc_badge(),
            _type_tag(type_str),
        ),
        rx.cond(
            type_str == "added",
            rx.button("×", on_click=State.remove_user_expert_agent(idx_str),
                      style=dict(background="transparent", border="none", color=_TEXT2,
                                 font_size="18px", line_height="1", padding="0 0 0 4px",
                                 cursor="pointer", flex_shrink="0")),
            rx.fragment(),
        ),
        style=dict(
            display="flex", align_items="center", gap="4px",
            padding="5px 8px", border_radius="6px",
            font_family=_MONO, color=_TEXT2,
            border=f"1px solid {_BORDER}",
        ),
    )


def _native_expert_row(item: list, *, ghost: bool = False) -> rx.Component:
    """item = [display_label, 'default', frame_idx_str] — clickable native expert row."""
    display_label = item[0]
    frame_idx_str = item[2]

    if ghost:
        is_selected = State.selected_ghost_native_expert_idx_str == frame_idx_str
        on_click = State.select_ghost_native_expert(frame_idx_str)
        on_remove = State.remove_ghost_native_expert(frame_idx_str)
        row_id = "pd-ghost-native-expert-row-" + frame_idx_str
    else:
        is_selected = State.selected_native_expert_idx_str == frame_idx_str
        on_click = State.select_native_expert(frame_idx_str)
        on_remove = State.remove_native_expert(frame_idx_str)
        row_id = "pd-native-expert-row-" + frame_idx_str

    return rx.box(
        rx.box(
            rx.text(display_label, style=dict(font_weight="500", font_size="12px", color=_TEXT, flex="1")),
            _type_tag("default"),
            rx.button("×", on_click=on_remove,
                      style=dict(background="transparent", border="none", color=_TEXT2,
                                 font_size="18px", line_height="1", padding="0 0 0 4px",
                                 cursor="pointer", flex_shrink="0")),
            style=dict(display="flex", align_items="center", gap="4px"),
        ),
        id=row_id,
        on_click=on_click,
        class_name=rx.cond(is_selected, "pd-agent-row pd-agent-selected", "pd-agent-row"),
    )




def _user_expert_row(item: list, *, ghost: bool = False) -> rx.Component:
    """item = [idx_str, label]"""
    idx_str = item[0]
    label = item[1]

    if ghost:
        is_selected = State.selected_ghost_expert_idx_str == idx_str
        on_click = State.select_ghost_expert(idx_str)
        on_remove = State.remove_ghost_user_expert_agent(idx_str)
        row_id = "pd-ghost-user-expert-row-" + idx_str
    else:
        is_selected = State.selected_expert_idx_str == idx_str
        on_click = State.select_expert(idx_str)
        on_remove = State.remove_user_expert_agent(idx_str)
        row_id = "pd-user-expert-row-" + idx_str

    return rx.box(
        rx.box(
            rx.text(label, style=dict(font_weight="500", font_size="12px", color=_TEXT, flex="1")),
            _type_tag("added"),
            rx.button("×", on_click=on_remove,
                      style=dict(background="transparent", border="none", color=_TEXT2,
                                 font_size="18px", line_height="1", padding="0 0 0 4px",
                                 cursor="pointer", flex_shrink="0")),
            style=dict(display="flex", align_items="center", gap="4px"),
        ),
        id=row_id,
        on_click=on_click,
        class_name=rx.cond(is_selected, "pd-agent-row pd-agent-selected", "pd-agent-row"),
    )



def _counter_badge(cur, total) -> rx.Component:
    return rx.box(
        rx.el.span(cur, style=dict(color=_TEXT, font_size="10px", font_family=_MONO)),
        rx.el.span(" / ", style=dict(color=_TEXT2, font_size="10px", font_family=_MONO)),
        rx.el.span(total, style=dict(color=_TEXT2, font_size="10px", font_family=_MONO)),
        style=dict(
            background=_BG2, border_radius="10px", padding="1px 8px",
            flex_shrink="0", display="flex", align_items="center",
        ),
    )



def _section_hdr(title: str, badge=None) -> rx.Component:
    return rx.box(
        rx.text(title, style=_SEC_LABEL),
        badge if badge is not None else rx.box(),
        style=dict(
            display="flex", align_items="center",
            justify_content="space-between",
            padding="10px 4px 4px",
            flex_shrink="0",
        ),
    )



def info_panel() -> rx.Component:
    ghost_toggle_btn = rx.button(
        rx.html(
            rx.cond(State.ghost_env_active, _ICON_EYE_OFF, _ICON_EYE),
            style=dict(display="contents"),
        ),
        rx.text(
            rx.cond(State.ghost_env_active, "Ghost Active", "Ghost Env"),
            style=dict(font_size="11px"),
        ),
        on_click=State.toggle_ghost_env,
        disabled=rx.cond(State.is_loaded, State.is_busy, True),
        title=rx.cond(State.ghost_env_active,
                      "Deactivate ghost environment",
                      "Activate ghost environment for comparison"),
        style=dict(
            display="flex", align_items="center", gap="6px",
            width="100%",
            background=rx.cond(State.ghost_env_active, "rgba(124,58,237,0.18)", _BG2),
            border=rx.cond(State.ghost_env_active,
                           "1px solid rgba(124,58,237,0.55)",
                           f"1px solid {_BORDER}"),
            color=rx.cond(State.ghost_env_active, "#a78bfa", _TEXT2),
            border_radius="6px",
            padding="5px 8px",
            cursor="pointer",
            font_size="11px",
            opacity=rx.cond(State.is_loaded, rx.cond(State.is_busy, "0.45", "1"), "0.4"),
            transition="all 0.15s",
            flex_shrink="0",
        ),
    )

    return rx.box(
        rx.el.style(_AGENT_ROW_CSS),
        # Ghost env toggle at top
        rx.box(
            ghost_toggle_btn,
            style=dict(padding="0 0 8px", border_bottom=f"1px solid {_BORDER}",
                       margin_bottom="0", flex_shrink="0"),
        ),
        # Available slots counter
        rx.cond(
            State.is_loaded,
            rx.box(
                rx.el.span("Available Slots", style=dict(
                    color=_TEXT2, font_size="10px", font_family=_MONO,
                )),
                rx.el.span(": ", style=dict(
                    color=_TEXT2, font_size="10px", font_family=_MONO,
                    margin_right="6px",
                )),
                rx.el.span(State.demo_slots_remaining, style=dict(
                    color=_TEXT, font_size="10px", font_family=_MONO,
                )),
                rx.el.span(f"/{MAX_AGENTS}", style=dict(
                    color=_TEXT2, font_size="10px", font_family=_MONO,
                )),
                style=dict(
                    padding="6px 4px 2px", flex_shrink="0",
                    display="flex", align_items="center",
                ),
            ),
            rx.box(),
        ),
        # One big scrollable list
        rx.box(
            # ── Reactive Agents ──
            _section_hdr("Reactive Agents"),
            rx.cond(
                State.is_loaded,
                rx.box(
                    rx.foreach(State.agent_sidebar_items, _agent_row),
                    style=dict(display="flex", flex_direction="column", gap="2px"),
                ),
                rx.text(
                    "Load a map to see agents.",
                    style=dict(font_size="12px", color=_TEXT2, padding="4px"),
                ),
            ),
            # ── Fixed Trajectory Agents ──
            _section_hdr("Fixed Trajectory Agents"),
            rx.cond(
                State.is_loaded,
                rx.box(
                    rx.foreach(State.expert_sidebar_items, _native_expert_row),
                    rx.foreach(State.user_expert_items, _user_expert_row),
                    style=dict(display="flex", flex_direction="column", gap="2px"),
                ),
                rx.box(),
            ),
            # ── Static Agents ──
            _section_hdr("Static Agents"),
            rx.cond(
                State.is_loaded,
                rx.box(
                    rx.foreach(State.static_sidebar_items, _static_vehicle_row),
                    style=dict(display="flex", flex_direction="column", gap="2px"),
                ),
                rx.box(),
            ),
            style=dict(
                flex="1",
                overflow_y="auto",
                display="flex",
                flex_direction="column",
                min_height="0",
            ),
        ),
        # ── Keyboard Shortcuts ────────────────────────────────────────────────
        rx.box(
            rx.el.details(
                rx.el.summary(
                    "Keyboard Shortcuts",
                    style=dict(
                        font_size="10px", color=_TEXT2, cursor="pointer",
                        user_select="none", padding="6px 4px",
                    ),
                ),
                rx.box(
                    *[
                        rx.box(
                            rx.el.span(k, style=dict(
                                font_family=_MONO, font_size="10px", color=_ACCENT,
                                background=_BG2, border_radius="3px", padding="1px 4px",
                                white_space="nowrap",
                            )),
                            rx.el.span(desc, style=dict(font_size="10px", color=_TEXT2)),
                            style=dict(display="flex", align_items="center",
                                       justify_content="space-between", gap="4px"),
                        )
                        for k, desc in [
                            ("Space", "Play / Pause"),
                            ("← →", "Step frame"),
                            ("Home / End", "First / Last"),
                            ("P", "Pan tool"),
                            ("S", "Select tool"),
                            ("E", "Goal edit"),
                            ("A", "Add agent"),
                            ("O", "Add static"),
                            ("R", "Reset zoom"),
                            ("F", "Fullscreen"),
                            ("+  −", "Zoom in / out"),
                            ("Esc", "Cancel / deselect"),
                        ]
                    ],
                    style=dict(display="flex", flex_direction="column", gap="3px", padding="0 4px 4px"),
                ),
            ),
            style=dict(
                border_top=f"1px solid {_BORDER}",
                flex_shrink="0",
            ),
        ),
        on_click=State.set_env_focus("primary"),
        id="pd-info-panel",
        style=dict(
            width="200px",
            flex_shrink="0",
            background=rx.cond(
                State.ghost_env_active & (State.env_focus == "ghost"),
                "rgba(255,255,255,0.02)",
                _BG1,
            ),
            border_left=f"1px solid {_BORDER}",
            padding="12px 8px",
            display="flex",
            flex_direction="column",
            overflow="hidden",
            transition="background 0.2s",
            cursor="default",
        ),
    )

