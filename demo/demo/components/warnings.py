# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import reflex as rx

from ..state import State
from ..constants.colors import _TEXT2

def random_policy_warning() -> rx.Component:
    primary_msg = rx.cond(
        State.policy_is_random & State.is_loaded,
        rx.el.span(
            "Primary: random actions (", State.policy_random_reason, ")",
            style=dict(font_weight="600"),
            title=State.policy_load_error,
        ),
        rx.fragment(),
    )
    ghost_msg = rx.cond(
        State.ghost_policy_is_random & State.ghost_env_active,
        rx.el.span(
            "Ghost: random actions (", State.ghost_policy_random_reason, ")",
            style=dict(font_weight="600"),
            title=State.ghost_policy_load_error,
        ),
        rx.fragment(),
    )
    sep = rx.cond(
        State.policy_is_random & State.is_loaded & State.ghost_policy_is_random & State.ghost_env_active,
        rx.el.span("  ·  "),
        rx.fragment(),
    )
    return rx.cond(
        (State.policy_is_random & State.is_loaded) | (State.ghost_policy_is_random & State.ghost_env_active),
        rx.box(
            rx.el.span("⚠ No policy loaded — using random actions:  "),
            primary_msg,
            sep,
            ghost_msg,
            style=dict(
                background="#78350f",
                color="#fef3c7",
                font_size="12px",
                padding="5px 18px",
                text_align="center",
                letter_spacing="0.01em",
                flex_shrink="0",
            ),
        ),
    )


