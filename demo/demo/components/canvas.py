# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..state import State
from ..constants.colors import _BG0, _BG1, _BG2, _ACCENT, _TEXT, _TEXT2, _BORDER, _MONO
from ..constants.styles import _ZOOM_BTN
from ..constants.icons import _ICON_ZOOM_FIT, _ICON_ZOOM_IN, _ICON_ZOOM_OUT, _ICON_HUD_SETTINGS
from ..constants.css import _ZOOM_BTN_HOVER_CSS, _HUD_CSS
from ..constants.js import _MAIN_JS, _AGENT_RENDERER_JS, _GOAL_CANVAS_JS, _RAF_PLAY_JS
from .. import globals as _g
from .toolbar import toolbar
from .legend import legend

def canvas_hud() -> rx.Component:
    """Top-right hover-expanding control panel: env focus + show goals/labels."""
    seg_focus = rx.box(
        rx.text("Env Focus", class_name="pd-hud-label"),
        rx.box(
            rx.button(
                "Primary",
                on_click=State.set_env_focus("primary"),
                class_name=rx.cond(State.env_focus == "primary",
                                   "pd-seg-btn seg-active", "pd-seg-btn"),
            ),
            rx.button(
                "Ghost",
                on_click=State.set_env_focus("ghost"),
                class_name=rx.cond(State.env_focus == "ghost",
                                   "pd-seg-btn seg-active", "pd-seg-btn"),
            ),
            style=dict(display="flex"),
        ),
        style=dict(display="flex", flex_direction="column", gap="3px"),
    )

    side_by_side_row = rx.el.label(
        rx.el.input(
            type="checkbox",
            checked=State.ghost_side_by_side,
            on_change=lambda _: State.toggle_ghost_side_by_side(),
        ),
        rx.el.span("Side-by-Side"),
        class_name="pd-hud-chk-row",
    )

    show_goals_row = rx.el.label(
        rx.el.input(
            type="checkbox",
            checked=State.show_goals,
            on_change=lambda _: State.toggle_show_goals(),
        ),
        rx.el.span("Show Goals"),
        class_name="pd-hud-chk-row",
    )

    show_goal_radius_row = rx.el.label(
        rx.el.input(
            type="checkbox",
            checked=State.show_goal_radius,
            on_change=lambda _: State.toggle_show_goal_radius(),
        ),
        rx.el.span("Show Goal Radius"),
        class_name="pd-hud-chk-row",
    )

    show_labels_row = rx.el.label(
        rx.el.input(
            type="checkbox",
            checked=State.show_labels,
            on_change=lambda _: State.toggle_show_labels(),
        ),
        rx.el.span("Show Labels"),
        class_name="pd-hud-chk-row",
    )

    show_trajectories_row = rx.el.label(
        rx.el.input(
            type="checkbox",
            checked=State.show_trajectories,
            on_change=lambda _: State.toggle_show_trajectories(),
        ),
        rx.el.span("Show Trajectories"),
        class_name="pd-hud-chk-row",
    )

    return rx.box(
        rx.el.style(_HUD_CSS),
        # Always-visible pill header
        rx.box(
            rx.html(_ICON_HUD_SETTINGS, style=dict(display="contents")),
            rx.text("View", style=dict(font_size="11px", color=_TEXT2)),
            style=dict(display="flex", align_items="center", gap="5px"),
        ),
        # Body shown on hover
        rx.box(
            rx.cond(State.ghost_env_active, seg_focus, rx.box()),
            rx.cond(State.ghost_env_active, side_by_side_row, rx.box()),
            show_goals_row,
            show_goal_radius_row,
            show_labels_row,
            show_trajectories_row,
            class_name="pd-hud-body",
        ),
        class_name="pd-canvas-hud",
        style=dict(
            position="absolute",
            top="12px",
            right="12px",
            background=_BG1,
            border=f"1px solid {_BORDER}",
            border_radius="8px",
            padding="6px 10px",
            z_index="10",
            cursor="default",
            min_width="110px",
        ),
    )



def canvas_area() -> rx.Component:
    zoom_overlay = rx.box(
        rx.el.style(_ZOOM_BTN_HOVER_CSS),
        rx.button(
            rx.html(_ICON_ZOOM_FIT, style=dict(display="contents")),
            id="pd-zoom-fit",
            title="Fit to screen",
            on_click=State.reset_zoom,
            style=_ZOOM_BTN,
        ),
        rx.button(
            rx.html(_ICON_ZOOM_IN, style=dict(display="contents")),
            id="pd-zoom-in",
            title="Zoom In",
            on_click=State.zoom_in,
            style=_ZOOM_BTN,
        ),
        rx.button(
            rx.html(_ICON_ZOOM_OUT, style=dict(display="contents")),
            id="pd-zoom-out",
            title="Zoom Out",
            on_click=State.zoom_out,
            style=_ZOOM_BTN,
        ),
        id="pd-zoom-overlay",
        style=dict(
            position="absolute",
            bottom="12px",
            left="12px",
            display="flex",
            flex_direction="column",
            gap="2px",
            background=_BG1,
            padding="4px",
            border_radius="8px",
            border=f"1px solid {_BORDER}",
            z_index="10",
        ),
    )

    # Hidden img — Reflex keeps src in sync with the static background PNG.
    hidden_img = rx.image(
        src=State.frame_image,
        id="pd-frame-img",
        style=dict(display="none"),
    )

    # Hidden counter — Reflex updates its text when current_frame changes.
    # The JS frame observer watches this element to trigger canvas redraws
    # without a per-frame round-trip for the full image.
    frame_counter = rx.text(
        State.current_frame,
        id="pd-current-frame-el",
        style=dict(display="none"),
    )

    # Visible canvas — no native drag behaviour, so no "forbidden" cursor.
    map_canvas = rx.el.canvas(
        id="pd-canvas",
        style=dict(
            display="block",
            width="100%",
            height="100%",
            cursor="inherit",
        ),
    )

    # Hidden button clicked by JS after a successful drag to trigger the Python drop handler.
    drop_trigger = rx.button(
        id="pd-goal-drop-trigger",
        on_click=rx.cond(
            State.goal_edit_mode,
            rx.call_script("window._pdDragResult || null", callback=State.handle_goal_drop),
            rx.call_script("null"),
        ),
        style=dict(display="none"),
    )

    # Hidden button clicked by JS after 3rd click to trigger the Python agent-place handler.
    agent_place_trigger = rx.button(
        id="pd-agent-place-trigger",
        on_click=rx.call_script(
            "window._pdAgentPlaceResult || null", callback=State.handle_agent_place
        ),
        style=dict(display="none"),
    )

    # Hidden button clicked by JS after a move (drag + heading) to trigger the move handler.
    agent_move_trigger = rx.button(
        id="pd-agent-move-trigger",
        on_click=rx.call_script(
            "window._pdMoveResult || null", callback=State.handle_agent_move
        ),
        style=dict(display="none"),
    )

    # Hidden button clicked by JS after 2nd click for static agent placement.
    static_place_trigger = rx.button(
        id="pd-static-place-trigger",
        on_click=rx.call_script(
            "window._pdStaticPlaceResult || null", callback=State.handle_static_agent_place
        ),
        style=dict(display="none"),
    )

    # Hidden button clicked by JS after 2nd click for expert agent placement.
    expert_place_trigger = rx.button(
        id="pd-expert-place-trigger",
        on_click=rx.call_script(
            "window._pdExpertPlaceResult || null", callback=State.handle_expert_place
        ),
        style=dict(display="none"),
    )

    # Hidden button clicked by JS after dragging an expert trajectory waypoint.
    expert_wp_drop_trigger = rx.button(
        id="pd-expert-wp-drop-trigger",
        on_click=rx.call_script(
            "window._pdExpertWpDropResult || null", callback=State.handle_expert_wp_drop
        ),
        style=dict(display="none"),
    )

    # Hidden button clicked by JS after dragging an individual trajectory timestep.
    expert_traj_drop_trigger = rx.button(
        id="pd-expert-traj-drop-trigger",
        on_click=rx.call_script(
            "window._pdExpertTrajDropResult || null", callback=State.handle_expert_traj_point_drop
        ),
        style=dict(display="none"),
    )

    # Hidden button clicked by JS after a ghost-canvas move to trigger the ghost move handler.
    ghost_agent_move_trigger = rx.button(
        id="pd-ghost-agent-move-trigger",
        on_click=rx.call_script(
            "window._pdGhostMoveResult || null", callback=State.handle_ghost_agent_move
        ),
        style=dict(display="none"),
    )

    # Ghost-env counterparts: clicked by JS when editing a ghost expert trajectory
    # in focus-ghost overlay mode.
    ghost_expert_wp_drop_trigger = rx.button(
        id="pd-ghost-expert-wp-drop-trigger",
        on_click=rx.call_script(
            "window._pdGhostExpertWpDropResult || null", callback=State.handle_ghost_expert_wp_drop
        ),
        style=dict(display="none"),
    )

    ghost_expert_traj_drop_trigger = rx.button(
        id="pd-ghost-expert-traj-drop-trigger",
        on_click=rx.call_script(
            "window._pdGhostExpertTrajDropResult || null", callback=State.handle_ghost_expert_traj_point_drop
        ),
        style=dict(display="none"),
    )

    click_signal_input = rx.el.input(
        id="pd-click-signal",
        type="text",
        on_change=State.on_click_signal,
        style=dict(display="none"),
    )

    expert_click_signal_input = rx.el.input(
        id="pd-expert-click-signal",
        type="text",
        on_change=State.select_expert,
        style=dict(display="none"),
    )

    ghost_expert_click_signal_input = rx.el.input(
        id="pd-ghost-expert-click-signal",
        type="text",
        on_change=State.select_ghost_expert,
        style=dict(display="none"),
    )

    ghost_click_signal_input = rx.el.input(
        id="pd-ghost-click-signal",
        type="text",
        on_change=State.on_ghost_click_signal,
        style=dict(display="none"),
    )

    clear_sel_btn = rx.button(
        id="pd-clear-sel-btn",
        on_click=State.clear_selection,
        style=dict(display="none"),
    )

    # Scenario import: a hidden file picker (opened by the toolbar Import button) whose
    # selected file is read by JS (FileReader) and pushed into the signal input below.
    import_file_input = rx.el.input(
        id="pd-import-file",
        type="file",
        accept="application/json,.json",
        style=dict(display="none"),
    )
    import_signal_input = rx.el.input(
        id="pd-import-signal",
        type="text",
        on_change=State.on_import_signal,
        style=dict(display="none"),
    )

    # Hidden buttons triggered by keyboard shortcuts.
    kb_step_back   = rx.button(id="pd-step-back-btn",   on_click=State.step_back,       style=dict(display="none"))
    kb_step_fwd    = rx.button(id="pd-step-fwd-btn",    on_click=State.step_forward,     style=dict(display="none"))
    kb_first_frame = rx.button(id="pd-first-frame-btn", on_click=State.go_first_frame,   style=dict(display="none"))
    kb_last_frame  = rx.button(id="pd-last-frame-btn",  on_click=State.go_last_frame,    style=dict(display="none"))
    kb_fullscreen  = rx.button(
        id="pd-fullscreen-btn",
        on_click=rx.call_script("window._pdToggleFullscreen && window._pdToggleFullscreen()"),
        style=dict(display="none"),
    )

    canvas_group = rx.box(
        hidden_img,
        frame_counter,
        click_signal_input,
        expert_click_signal_input,
        ghost_expert_click_signal_input,
        ghost_click_signal_input,
        clear_sel_btn,
        import_file_input,
        import_signal_input,
        kb_step_back,
        kb_step_fwd,
        kb_first_frame,
        kb_last_frame,
        kb_fullscreen,
        map_canvas,
        drop_trigger,
        agent_place_trigger,
        agent_move_trigger,
        static_place_trigger,
        expert_place_trigger,
        expert_wp_drop_trigger,
        expert_traj_drop_trigger,
        ghost_agent_move_trigger,
        ghost_expert_wp_drop_trigger,
        ghost_expert_traj_drop_trigger,
        style=dict(width="100%", height="100%"),
    )

    return rx.box(
        rx.script(
            f"window._pdGhostOpacity = {_g._render_style.ghost_opacity};"
            + "".join(
                f"window.{k} = '{v}';"
                for k, v in [
                    ("_pdAgentFill",          "#{:02x}{:02x}{:02x}".format(*_g._render_style.agent_fill)),
                    ("_pdAgentOutline",        "#{:02x}{:02x}{:02x}".format(*_g._render_style.agent_outline)),
                    ("_pdExpertFill",          "#{:02x}{:02x}{:02x}".format(*_g._render_style.expert_fill)),
                    ("_pdExpertOutline",       "#{:02x}{:02x}{:02x}".format(*_g._render_style.expert_outline)),
                    ("_pdStaticFill",          "#{:02x}{:02x}{:02x}".format(*_g._render_style.static_fill)),
                    ("_pdStaticOutline",       "#{:02x}{:02x}{:02x}".format(*_g._render_style.static_outline)),
                    ("_pdGhostFill",           "#{:02x}{:02x}{:02x}".format(*_g._render_style.ghost_fill)),
                    ("_pdGhostOutline",        "#{:02x}{:02x}{:02x}".format(*_g._render_style.ghost_outline)),
                    ("_pdGhostExpertFill",     "#{:02x}{:02x}{:02x}".format(*_g._render_style.ghost_expert_fill)),
                    ("_pdGhostExpertOutline",  "#{:02x}{:02x}{:02x}".format(*_g._render_style.ghost_expert_outline)),
                    ("_pdGhostStaticFill",     "#{:02x}{:02x}{:02x}".format(*_g._render_style.ghost_static_fill)),
                    ("_pdGhostStaticOutline",  "#{:02x}{:02x}{:02x}".format(*_g._render_style.ghost_static_outline)),
                ]
            )
        ),
        rx.script(_AGENT_RENDERER_JS),
        rx.script(_GOAL_CANVAS_JS),
        rx.script(_RAF_PLAY_JS),
        rx.script(_MAIN_JS),
        rx.box(
            rx.box(
                # The canvas is always mounted (not gated behind rx.cond). Unmounting it
                # on unload would orphan the one-time canvas event listeners and, crucially,
                # the frame-index MutationObserver that drives playback redraws — after a
                # remount the slider would keep moving while the canvas froze. The "select
                # a map" prompt is shown as an overlay below instead of replacing it.
                canvas_group,
                id="pd-zoom-layer",
                style=dict(
                    width="100%",
                    height="100%",
                    display="flex",
                    align_items="center",
                    justify_content="center",
                    transform_origin="center center",
                    transition="transform 0.12s ease",
                ),
            ),
            rx.cond(
                ~State.is_loaded,
                rx.vstack(
                    rx.text("🗺", style=dict(font_size="48px")),
                    rx.text(
                        "Select a split, enter a map ID, and press Load.",
                        style=dict(color=_TEXT2, font_size="15px"),
                    ),
                    align="center",
                    justify="center",
                    style=dict(
                        position="absolute",
                        inset="0",
                        background=_BG0,
                        z_index="5",
                    ),
                ),
                rx.box(),
            ),
            id="pd-pan-wrapper",
            style=dict(flex="1", min_width="0", height="100%", position="relative"),
        ),
        rx.cond(
            State.ghost_env_active & State.ghost_side_by_side,
            rx.box(
                rx.el.canvas(
                    id="pd-ghost-canvas",
                    style=dict(display="block", width="100%", height="100%", pointer_events="auto"),
                ),
                rx.text(
                    "Ghost",
                    style=dict(
                        position="absolute",
                        top="8px",
                        left="10px",
                        font_size="11px",
                        font_weight="600",
                        color="#a78bfa",
                        background=_BG1,
                        border=f"1px solid {_BORDER}",
                        border_radius="6px",
                        padding="2px 8px",
                    ),
                ),
                id="pd-ghost-pane",
                style=dict(
                    position="relative",
                    flex="1",
                    min_width="0",
                    height="100%",
                    border_left=f"1px solid {_BORDER}",
                    overflow="hidden",
                    pointer_events="none",
                ),
            ),
            rx.box(style=dict(display="none")),
        ),
        toolbar(),
        zoom_overlay,
        canvas_hud(),
        # ── legend overlay: agent color key, top-left of the canvas ───────────
        rx.cond(
            State.is_loaded,
            rx.box(
                legend(),
                style=dict(
                    position="absolute",
                    top="12px",
                    left="50%",
                    transform="translateX(-50%)",
                    z_index="10",
                ),
            ),
            rx.box(),
        ),
        rx.box(
            id="pd-coord-display",
            style=dict(
                position="absolute",
                bottom="12px",
                right="12px",
                display="none",
                background=_BG1,
                border=f"1px solid {_BORDER}",
                border_radius="6px",
                padding="4px 10px",
                font_family=_MONO,
                font_size="11px",
                color=_TEXT2,
                z_index="10",
                pointer_events="none",
                white_space="nowrap",
            ),
        ),
        rx.cond(
            State.active_slots_full | State.static_slots_full,
            rx.box(
                rx.cond(
                    State.demo_slots_full,
                    rx.box(
                        rx.html("""<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14" style="flex-shrink:0"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>""",
                                style=dict(display="contents")),
                        rx.text(State.demo_slots_full_label,
                                style=dict(font_size="12px", font_weight="600")),
                        style=dict(display="flex", align_items="center", gap="6px"),
                    ),
                    rx.box(),
                ),
                style=dict(
                    position="absolute",
                    top="12px",
                    right="140px",  # offset left of the HUD
                    display="flex",
                    flex_direction="column",
                    gap="6px",
                    background="rgba(120,53,15,0.92)",
                    border="1px solid #f97316",
                    border_radius="8px",
                    padding="8px 14px",
                    color="#fed7aa",
                    z_index="20",
                    pointer_events="none",
                    box_shadow="0 0 18px rgba(249,115,22,0.35)",
                ),
            ),
            rx.box(),
        ),
        id="pd-canvas-container",
        style=dict(
            position="relative",
            display="flex",
            flex="1",
            background=_BG0,
            overflow="hidden",
            min_height="0",
            cursor="grab",
        ),
    )

