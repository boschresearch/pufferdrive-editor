# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

import os
import reflex as rx

_host = os.environ.get("HOST_IP", "localhost")

config = rx.Config(
    app_name="demo",
    api_url=f"http://{_host}:8000",
    backend_host="0.0.0.0",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)