# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""Flat horizontal color legend for the header bar.

Explains what each agent color means. Swatch colors are read from the loaded
RenderStyle (`_g._render_style`) using the same hex-format idiom as
canvas.py, so the legend always matches what is actually drawn. Parked vehicles
share the expert color, so they need no separate entry.
"""
import reflex as rx

from ..state import State
from ..constants.colors import _BG0, _TEXT, _TEXT2, _BORDER
from .. import globals as _g


def _hex(rgb: tuple) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _legend_item(fill: str, outline: str, label: str) -> rx.Component:
    """One swatch + label entry, laid out horizontally."""
    swatch = rx.box(style=dict(
        width="12px", height="12px", border_radius="3px",
        background=fill, border=f"1px solid {outline}", flex_shrink="0",
    ))
    return rx.box(
        swatch,
        rx.text(label, style=dict(font_size="11px", font_weight="600", color=_TEXT)),
        style=dict(display="flex", align_items="center", gap="5px", white_space="nowrap"),
    )


def legend() -> rx.Component:
    s = _g._render_style
    return rx.box(
        _legend_item(_hex(s.agent_fill), _hex(s.agent_outline), "Reactive Policy"),
        _legend_item(_hex(s.expert_fill), _hex(s.expert_outline), "Fixed Trajectory"),
        rx.cond(
            State.ghost_env_active,
            rx.box(
                _legend_item(_hex(s.ghost_fill), _hex(s.ghost_outline), "Ghost Reactive Policy"),
                _legend_item(_hex(s.ghost_expert_fill), _hex(s.ghost_expert_outline),
                             "Ghost Fixed Trajectory"),
                style=dict(display="flex", align_items="center", gap="16px"),
            ),
            rx.box(),
        ),
        style=dict(
            display="flex",
            flex_direction="row",
            align_items="center",
            gap="16px",
            flex_wrap="nowrap",
            background=_BG0,
            border=f"1px solid {_BORDER}",
            border_radius="8px",
            padding="5px 14px",
            white_space="nowrap",
        ),
    )
