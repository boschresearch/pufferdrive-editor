# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

from .colors import _BG0, _BG1, _BG2, _ACCENT, _ACCENT_DIM, _TEXT, _TEXT2, _BORDER, _MONO

_SELECT_STYLE = dict(
    background=_BG0,
    color=_TEXT,
    border=f"1px solid {_BORDER}",
    border_radius="6px",
    padding="5px 10px",
    font_size="13px",
    cursor="pointer",
)

_INPUT_STYLE = dict(
    background=_BG0,
    color=_TEXT,
    border=f"1px solid {_BORDER}",
    border_radius="6px",
    padding="5px 10px",
    font_size="13px",
    width="90px",
    text_align="right",
    outline="none",
)

_BTN = dict(
    border_radius="6px",
    padding="6px 16px",
    font_size="13px",
    font_weight="600",
    cursor="pointer",
    border="none",
)

_PLAY_BTN = dict(
    width="36px",
    height="36px",
    border_radius="50%",
    border="none",
    background=_ACCENT,
    color=_BG0,
    cursor="pointer",
    display="flex",
    align_items="center",
    justify_content="center",
    font_size="16px",
    box_shadow=f"0 0 12px rgba(34,211,238,0.3)",
    transition="transform 0.1s, box-shadow 0.15s",
    flex_shrink="0",
)

_TOOL_BTN_STYLE = dict(
    width="36px",
    height="36px",
    border="none",
    background="transparent",
    color=_TEXT2,
    border_radius="6px",
    cursor="pointer",
    display="flex",
    align_items="center",
    justify_content="center",
    transition="all 0.15s",
)

_ZOOM_BTN = dict(
    width="36px",
    height="36px",
    border="none",
    background="transparent",
    color=_TEXT2,
    border_radius="6px",
    cursor="pointer",
    display="flex",
    align_items="center",
    justify_content="center",
    transition="all 0.15s",
)


_SEC_LABEL = dict(
    font_size="11px",
    color=_TEXT2,
    text_transform="uppercase",
    letter_spacing="0.08em",
)


