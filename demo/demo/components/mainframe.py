# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..constants.colors import _BG0, _TEXT
from .header import header
from .canvas import canvas_area
from .sidebar import info_panel
from .sidebar_ghost import ghost_panel
from .timeline import timeline
from .warnings import random_policy_warning

def index() -> rx.Component:
    return rx.box(
        header(),
        random_policy_warning(),
        # Content area (canvas + info panels + timeline). No longer the fullscreen target —
        # fullscreen now goes on pd-app-root below so the header is included.
        rx.box(
            rx.box(
                canvas_area(),
                info_panel(),
                ghost_panel(),
                style=dict(
                    display="flex",
                    flex_direction="row",
                    flex="1",
                    min_height="0",
                ),
            ),
            timeline(),
            id="pd-fs-root",
            style=dict(
                display="flex",
                flex_direction="column",
                flex="1",
                min_height="0",
                background=_BG0,
            ),
        ),
        # Fullscreen target (see _pdSetFullscreen in _MAIN_JS): native fullscreen goes on
        # THIS element — the whole app including the header — so policy/map selectors stay
        # visible while fullscreen. Keyboard Lock (Chromium) keeps Esc from force-exiting,
        # enabling staged Esc: first cancel an in-progress edit, then leave fullscreen.
        id="pd-app-root",
        style=dict(
            display="flex",
            flex_direction="column",
            height="100vh",
            background=_BG0,
            color=_TEXT,
            font_family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            overflow="hidden",
        ),
    )

