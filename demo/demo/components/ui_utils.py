# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..constants.colors import _BG0, _TEXT2, _ACCENT
from ..constants.styles import _BTN

def _labeled(label: str, child: rx.Component) -> rx.Component:
    return rx.box(
        rx.text(label, style=dict(font_size="11px", color=_TEXT2, text_transform="uppercase")),
        child,
        style=dict(display="flex", flex_direction="column", gap="2px"),
    )


def _btn(label: str, on_click, color: str = _ACCENT, disabled=False) -> rx.Component:
    return rx.button(
        label,
        on_click=on_click,
        disabled=disabled,
        style={**_BTN, "background": color, "color": _BG0,
               "opacity": rx.cond(disabled, "0.45", "1")},
    )
