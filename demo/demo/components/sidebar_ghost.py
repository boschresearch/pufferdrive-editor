# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..state import State
from ..globals import MAX_AGENTS
from ..constants.colors import _TEXT, _TEXT2, _MONO
from ..constants.css import _AGENT_ROW_CSS
from .sidebar import (
    _native_expert_row, _user_expert_row, _agent_row, _static_vehicle_row, _section_hdr,
)


def _ghost_native_expert_row(item: list) -> rx.Component:
    return _native_expert_row(item, ghost=True)


def _ghost_user_expert_row(item: list) -> rx.Component:
    return _user_expert_row(item, ghost=True)


def _ghost_agent_row(item: list) -> rx.Component:
    return _agent_row(item, ghost=True)


def _ghost_static_row(item: list) -> rx.Component:
    return _static_vehicle_row(item, ghost=True)


def ghost_panel() -> rx.Component:
    """Secondary sidebar for the ghost (comparison) environment."""
    focus_btn = rx.button(
        rx.text(
            rx.cond(State.env_focus == "ghost", "← Primary", "Focus Ghost →"),
            style=dict(font_size="10px", font_weight="600"),
        ),
        on_click=State.toggle_env_focus,
        title=rx.cond(
            State.env_focus == "ghost",
            "Switch focus back to primary environment",
            "Switch focus to ghost environment",
        ),
        style=dict(
            height="22px", border="none", border_radius="4px",
            background=rx.cond(
                State.env_focus == "ghost",
                "rgba(124,58,237,0.30)",
                "rgba(124,58,237,0.12)",
            ),
            color=rx.cond(State.env_focus == "ghost", "#e9d5ff", "#a78bfa"),
            cursor="pointer", display="flex", align_items="center",
            padding="0 6px",
            transition="all 0.15s", flex_shrink="0",
        ),
    )

    header_bar = rx.box(
        rx.text("Ghost Env", style=dict(
            font_size="11px", font_weight="700", color="#a78bfa",
            text_transform="uppercase", letter_spacing="0.07em",
        )),
        focus_btn,
        style=dict(
            display="flex", align_items="center", justify_content="space-between",
            padding="0 0 8px", border_bottom=f"1px solid rgba(124,58,237,0.35)",
            flex_shrink="0",
        ),
    )

    return rx.cond(
        State.ghost_env_active,
        rx.box(
            rx.el.style(_AGENT_ROW_CSS),
            header_bar,
            rx.box(
                rx.el.span("Available Slots", style=dict(
                    color=_TEXT2, font_size="10px", font_family=_MONO,
                )),
                rx.el.span(": ", style=dict(
                    color=_TEXT2, font_size="10px", font_family=_MONO,
                    margin_right="6px",
                )),
                rx.el.span(State.ghost_demo_slots_remaining, style=dict(
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
            rx.box(
                _section_hdr("Reactive Agents"),
                rx.foreach(State.ghost_agent_sidebar_items, _ghost_agent_row),
                _section_hdr("Fixed Trajectory Agents"),
                rx.box(
                    rx.foreach(State.ghost_native_expert_sidebar_items, _ghost_native_expert_row),
                    rx.foreach(State.ghost_user_expert_items, _ghost_user_expert_row),
                    style=dict(display="flex", flex_direction="column", gap="2px"),
                ),
                _section_hdr("Static Agents"),
                rx.foreach(State.ghost_static_sidebar_items, _ghost_static_row),
                style=dict(
                    flex="1", overflow_y="auto",
                    display="flex", flex_direction="column", min_height="0",
                ),
            ),
            style=dict(
                width="200px",
                flex_shrink="0",
                background=rx.cond(
                    State.env_focus == "ghost",
                    "rgba(124,58,237,0.13)",
                    "rgba(124,58,237,0.04)",
                ),
                border_left=rx.cond(
                    State.env_focus == "ghost",
                    "1px solid rgba(124,58,237,0.65)",
                    "1px solid rgba(124,58,237,0.35)",
                ),
                padding="12px 8px",
                display="flex",
                flex_direction="column",
                overflow="hidden",
                transition="background 0.2s, border 0.2s",
            ),
        ),
        rx.box(),
    )
