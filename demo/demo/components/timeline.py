# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..state import State
from ..constants.colors import _BG0, _BG1, _BG2, _ACCENT, _TEXT, _TEXT2, _MONO
from ..constants.styles import _PLAY_BTN, _SELECT_STYLE, _INPUT_STYLE
from ..constants.icons import _ICON_RESET

def timeline() -> rx.Component:
    cur_t = State.cur_time_str
    tot_t = State.tot_time_str
    play_icon = rx.cond(State.is_playing, "⏸", "▶")

    slider_style = dict(
        width="100%",
        height="6px",
        appearance="none",
        webkit_appearance="none",
        cursor="pointer",
        border_radius="3px",
        accent_color=_ACCENT,
        background=rx.cond(
            State.num_frames > 0,
            f"linear-gradient(to right, {_ACCENT} var(--p), {_BG2} var(--p))",
            _BG2,
        ),
    )

    return rx.box(
        rx.box(
            rx.box(
                rx.button(
                    rx.cond(
                        State.is_busy,
                        rx.el.svg(
                            rx.el.circle(
                                cx="15", cy="15", r="11",
                                fill="none", stroke="#334155", stroke_width="2.5",
                            ),
                            rx.el.circle(
                                id="pd-resim-ring",
                                cx="15", cy="15", r="11",
                                fill="none", stroke="#22d3ee", stroke_width="2.5",
                                stroke_dasharray="69.115",
                                stroke_dashoffset="69.115",
                                stroke_linecap="round",
                                transform="rotate(-90 15 15)",
                                style=dict(transition="stroke-dashoffset 0.12s ease-out"),
                            ),
                            view_box="0 0 30 30", width="26", height="26",
                        ),
                        rx.html(_ICON_RESET, style=dict(display="contents")),
                    ),
                    on_click=State.resimulate,
                    disabled=rx.cond(State.is_loaded, State.is_busy, True),
                    title="Resimulate",
                    style=dict(
                        width="30px",
                        height="30px",
                        border_radius="50%",
                        border="none",
                        background=_BG2,
                        color=_TEXT2,
                        cursor="pointer",
                        display="flex",
                        align_items="center",
                        justify_content="center",
                        opacity=rx.cond(State.is_loaded, "1", "0.4"),
                        transition="background 0.15s, color 0.15s",
                        flex_shrink="0",
                    ),
                ),
                rx.button(
                    play_icon,
                    id="pd-play-btn",
                    on_click=State.toggle_play,
                    disabled=~State.is_loaded,
                    style={**_PLAY_BTN, "opacity": rx.cond(State.is_loaded, "1", "0.4")},
                ),
                rx.button(
                    rx.html("""<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" width="16" height="16"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>"""),
                    on_click=State.toggle_loop,
                    title="Toggle loop",
                    style=dict(
                        width="30px",
                        height="30px",
                        border_radius="50%",
                        border="none",
                        cursor="pointer",
                        display="flex",
                        align_items="center",
                        justify_content="center",
                        background=rx.cond(State.loop_enabled, _ACCENT, _BG2),
                        color=rx.cond(State.loop_enabled, _BG0, _TEXT2),
                        transition="background 0.15s, color 0.15s",
                        flex_shrink="0",
                    ),
                ),
                rx.el.select(
                    rx.el.option("0.25x", value="0.25"),
                    rx.el.option("0.5x", value="0.5"),
                    rx.el.option("1x", value="1", selected=True),
                    rx.el.option("2x", value="2"),
                    rx.el.option("4x", value="4"),
                    on_change=State.set_play_speed,
                    style={**_SELECT_STYLE, "font_size": "12px", "padding": "4px 8px"},
                ),
                style=dict(display="flex", align_items="center", gap="10px"),
            ),
            rx.box(
                rx.box(
                    rx.el.span(cur_t, style=dict(color=_TEXT)),
                    rx.el.span(" / ", style=dict(color=_TEXT2)),
                    rx.el.span(tot_t, style=dict(color=_TEXT2)),
                    rx.el.span("s", style=dict(color=_TEXT2, margin_left="2px")),
                    style=dict(
                        font_family=_MONO,
                        font_size="15px",
                        font_weight="500",
                        letter_spacing="0.5px",
                    ),
                ),
                rx.box(
                    rx.text(
                        "Frame ",
                        rx.cond(State.is_loaded, rx.el.span(State.current_frame, style=dict(color=_TEXT)), rx.el.span("–")),
                        " / ",
                        rx.cond(State.is_loaded, rx.el.span(State.num_frames - 1, style=dict(color=_TEXT2)), rx.el.span("–")),
                        style=dict(font_family=_MONO, font_size="11px", color=_TEXT2, opacity="0.8"),
                    ),
                    rx.cond(
                        State.sim_steps_editing,
                        rx.box(
                            rx.el.input(
                                type="number",
                                min="1",
                                value=State.sim_steps_input,
                                on_change=State.set_sim_steps_input,
                                on_blur=State.apply_sim_steps,
                                style={**_INPUT_STYLE, "width": "55px", "font_size": "10px", "padding": "1px 4px"},
                            ),
                            rx.button(
                                "✓",
                                on_click=State.apply_sim_steps,
                                style=dict(
                                    background=_ACCENT, color=_BG0, border="none",
                                    border_radius="4px", padding="1px 5px",
                                    cursor="pointer", font_size="11px", font_weight="700",
                                ),
                            ),
                            style=dict(display="flex", align_items="center", gap="3px"),
                        ),
                        rx.button(
                            "✏",
                            on_click=State.toggle_sim_steps_edit,
                            title="Edit simulation steps",
                            style=dict(
                                background="transparent", border="none", color=_TEXT2,
                                cursor="pointer", font_size="10px", padding="0 2px",
                                opacity="0.5", line_height="1",
                            ),
                        ),
                    ),
                    style=dict(display="flex", align_items="center", gap="4px"),
                ),
                style=dict(display="flex", flex_direction="column", align_items="flex_end", gap="1px"),
            ),
            style=dict(
                display="flex",
                align_items="center",
                justify_content="space-between",
                margin_bottom="10px",
            ),
        ),
        rx.el.input(
            type="range",
            min="0",
            max=State.frames_max,
            value=State.current_frame,
            on_change=State.scrub,
            disabled=~State.is_loaded,
            style={**slider_style, "--p": State.progress_pct},
        ),
        rx.cond(
            State.ghost_env_active & State.show_ghost_replay_slider,
            rx.box(
                rx.box(
                    rx.text(
                        "Ghost diverge: ",
                        rx.el.span(State.ghost_diverge_time_str, style=dict(color="#a78bfa")),
                        rx.el.span(" s", style=dict(color=_TEXT2)),
                        style=dict(font_size="11px", color=_TEXT2, user_select="none"),
                    ),
                    style=dict(margin_bottom="4px"),
                ),
                rx.el.input(
                    type="range",
                    min="0",
                    max=State.frames_max,
                    value=State.ghost_diverge_frame,
                    on_change=State.set_ghost_diverge,
                    disabled=~State.is_loaded,
                    style={
                        "width": "100%",
                        "height": "6px",
                        "appearance": "none",
                        "webkit-appearance": "none",
                        "cursor": "pointer",
                        "border-radius": "3px",
                        "accent-color": "#7c3aed",
                        "background": rx.cond(
                            State.num_frames > 0,
                            "linear-gradient(to right, #7c3aed var(--gp), #334155 var(--gp))",
                            "#334155",
                        ),
                        "--gp": State.ghost_diverge_pct,
                    },
                ),
                style=dict(margin_top="8px"),
            ),
        ),
        id="pd-timeline",
        style=dict(background=_BG1, padding="12px 20px 14px"),
    )


