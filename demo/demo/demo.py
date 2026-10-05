# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""PufferDrive interactive demo — map picker + pre-rendered timeline viewer."""

import reflex as rx

from .state import State
from .components import index, debug_page
from .constants.colors import _BG0

app = rx.App(style=dict(background=_BG0))
app.add_page(index, route="/", on_load=State.on_load)
app.add_page(debug_page, route="/debug")
