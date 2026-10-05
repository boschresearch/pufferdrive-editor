# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..state import State
from ..constants.colors import _BG0, _BG1, _BG2, _ACCENT, _TEXT, _TEXT2, _BORDER, _MONO
from ..constants.styles import _SELECT_STYLE, _INPUT_STYLE, _TOOL_BTN_STYLE, _BTN
from ..constants.icons import _ICON_RESET
from .. import viewer
from .ui_utils import _labeled, _btn

_EYEBROW = dict(font_size="11px", color=_ACCENT, text_transform="uppercase",
                letter_spacing="0.06em", font_weight="700")
_OUTLINE_BTN = {**_BTN, "background": "transparent", "color": _ACCENT,
                "border": f"1px solid {_BORDER}"}
_GHOST_BTN = {**_BTN, "background": "transparent", "color": _TEXT2,
              "border": f"1px solid {_BORDER}"}
_DIALOG_STYLE = dict(background=_BG1, border=f"1px solid {_BORDER}",
                     border_radius="12px", max_width="460px",
                     box_shadow="0 16px 48px rgba(0,0,0,0.5)")


def _export_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.trigger(
            rx.button(
                "Export",
                disabled=State.is_busy | ~State.is_loaded,
                style={**_OUTLINE_BTN,
                       "opacity": rx.cond(State.is_loaded & ~State.is_busy, "1", "0.45")},
            ),
        ),
        rx.dialog.content(
            rx.dialog.title(
                "Export scenario",
                style=dict(color=_TEXT, font_size="15px", font_weight="700", margin="0"),
            ),
            rx.dialog.description(
                "Saves the whole scene — map, policies, edits, ghost env — into demo/scenarios/.",
                style=dict(color=_TEXT2, font_size="12px", margin="6px 0 16px"),
            ),
            rx.text("File name", style={**_EYEBROW, "color": _TEXT2, "margin_bottom": "4px"}),
            rx.el.input(
                placeholder="leave blank for a timestamped name",
                value=State.scenario_name,
                on_change=State.set_scenario_name,
                style={**_INPUT_STYLE, "width": "100%", "text_align": "left",
                       "font_family": _MONO},
            ),
            rx.box(
                rx.dialog.close(rx.button("Cancel", style=_GHOST_BTN)),
                rx.dialog.close(
                    rx.button("Save scenario", on_click=State.export_scenario,
                              style={**_BTN, "background": _ACCENT, "color": _BG0}),
                ),
                style=dict(display="flex", gap="8px", justify_content="flex-end",
                           margin_top="18px"),
            ),
            style=_DIALOG_STYLE,
        ),
    )


def header() -> rx.Component:
    return rx.box(
        # ── left group: title, config, map, load ──────────────────────────────
        rx.box(
            rx.text(
                "⬡ PufferDrive",
                style=dict(font_size="16px", font_weight="700", color=_ACCENT, white_space="nowrap"),
            ),

            rx.button(
                rx.html(_ICON_RESET, style=dict(display="contents")),
                on_click=State.deep_reset,
                disabled=State.is_busy,
                title="Restart — relaunch the whole app from scratch (no C rebuild)",
                class_name="pd-tool-btn",
                style={**_TOOL_BTN_STYLE, "color": _ACCENT,
                       "opacity": rx.cond(State.is_busy, "0.45", "1")},
            ),

            _labeled(
                "Config",
                rx.el.select(
                    rx.el.option("— none —", value=""),
                    rx.foreach(
                        State.available_ini_files,
                        lambda item: rx.el.option(item[0], value=item[1]),
                    ),
                    value=State.selected_ini_path,
                    on_change=State.set_ini,
                    style=_SELECT_STYLE,
                ),
            ),

            rx.cond(
                State.has_demo_maps,
                _labeled(
                    "Map",
                    rx.el.select(
                        rx.foreach(
                            State.demo_maps,
                            lambda item: rx.el.option(item[0], value=item[1]),
                        ),
                        # Exported scenes (session-only) selectable from the same Map dropdown.
                        rx.foreach(
                            State.session_maps,
                            lambda item: rx.el.option("★ " + item[0], value=item[1]),
                        ),
                        value=State.selected_map_choice,
                        on_change=State.set_demo_map,
                        style=_SELECT_STYLE,
                    ),
                ),
                rx.box(
                    _labeled(
                        "Split",
                        rx.el.select(
                            *[rx.el.option(s, value=s) for s in viewer.SPLITS],
                            default_value="training",
                            on_change=State.set_split,
                            style=_SELECT_STYLE,
                        ),
                    ),
                    _labeled(
                        "Map ID",
                        rx.el.input(
                            type="number",
                            min="0",
                            placeholder="0",
                            value=State.map_id_input,
                            on_change=State.set_map_id_input,
                            style=_INPUT_STYLE,
                        ),
                    ),
                    # In split/map-id mode there's no Map dropdown, so exported scenes get their
                    # own "Map" selector once at least one exists (empty value = use split/id above).
                    rx.cond(
                        State.session_maps,
                        _labeled(
                            "Map",
                            rx.el.select(
                                rx.el.option("— use map id —", value=""),
                                rx.foreach(
                                    State.session_maps,
                                    lambda item: rx.el.option("★ " + item[0], value=item[1]),
                                ),
                                value=State.selected_map_choice,
                                on_change=State.set_demo_map,
                                style=_SELECT_STYLE,
                            ),
                        ),
                    ),
                    style=dict(display="contents"),
                ),
            ),

            _btn("Load", State.load_map, disabled=State.is_busy),

            # ── scenario save (writes to the demo/scenarios/ folder) ───────────────
            _export_dialog(),

            style=dict(
                flex="1",
                display="flex",
                align_items="flex-end",   # bottom-align so bare buttons line up with the labeled selects
                gap="14px",
                flex_wrap="nowrap",       # keep config/map/split/load/export/import on ONE line
                min_width="max-content",  # size to content so items never clip or wrap under
                justify_content="flex-start",
            ),
        ),

        # ── center group: policy + ghost policy selectors ─────────────────────
        rx.box(
            rx.cond(
                State.has_demo_policies,
                rx.box(
                    _labeled(
                        "Policy",
                        rx.el.select(
                            rx.foreach(
                                State.demo_policies,
                                lambda item: rx.el.option(item[0], value=item[1] + "||" + item[2]),
                            ),
                            value=State.selected_policy_key,
                            on_change=State.set_demo_policy,
                            style=_SELECT_STYLE,
                        ),
                    ),
                    rx.cond(
                        State.policy_load_error != "",
                        rx.text(
                            "Failed to load: " + State.policy_load_error,
                            style=dict(font_size="11px", color="#f87171", margin_top="2px", max_width="220px"),
                        ),
                    ),
                    style=dict(display="flex", flex_direction="column", gap="0px"),
                ),
                rx.box(),
            ),

            rx.cond(
                State.has_demo_policies,
                rx.box(
                    _labeled(
                        "Ghost Reactive Policy",
                        rx.el.select(
                            rx.foreach(
                                State.demo_policies,
                                lambda item: rx.el.option(item[0], value=item[1] + "||" + item[2]),
                            ),
                            value=State.ghost_policy_key,
                            on_change=State.set_ghost_policy,
                            style=_SELECT_STYLE,
                        ),
                    ),
                    rx.cond(
                        State.ghost_policy_load_error != "",
                        rx.text(
                            "Failed to load: " + State.ghost_policy_load_error,
                            style=dict(font_size="11px", color="#f87171", margin_top="2px", max_width="220px"),
                        ),
                    ),
                    style=dict(display="flex", flex_direction="column", gap="0px"),
                ),
                rx.box(),
            ),

            style=dict(
                flex="1",
                display="flex",
                align_items="center",
                gap="14px",
                flex_wrap="wrap",
                justify_content="center",
            ),
        ),

        # ── right group: status ───────────────────────────────────────────────
        rx.box(
            rx.text(
                State.status,
                style=dict(font_size="12px", color=_TEXT2),
            ),
            style=dict(
                flex="1",
                display="flex",
                align_items="center",
                justify_content="flex-end",
            ),
        ),

        rx.button(
            "⛶",
            id="pd-fullscreen-header-btn",
            title="Toggle fullscreen (F)",
            on_click=rx.call_script("window._pdToggleFullscreen && window._pdToggleFullscreen()"),
            style=dict(
                background="transparent",
                border=f"1px solid {_BORDER}",
                color=_TEXT2,
                border_radius="6px",
                padding="5px 8px",
                cursor="pointer",
                font_size="16px",
                line_height="1",
                flex_shrink="0",
            ),
        ),

        style=dict(
            background=_BG1,
            padding="10px 18px",
            display="flex",
            align_items="center",
            gap="14px",
            flex_wrap="wrap",
        ),
    )


