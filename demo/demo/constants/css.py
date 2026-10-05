# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

from .colors import _BG0, _BG1, _BG2, _ACCENT, _ACCENT_DIM, _TEXT, _TEXT2, _BORDER, _MONO

_TOOLBAR_CSS = f"""
.pd-tool-btn:hover {{
    background: {_BG2} !important;
    color: {_TEXT} !important;
}}
.pd-tool-btn.pd-tool-active {{
    background: {_ACCENT} !important;
    color: {_BG0} !important;
}}
.pd-toolbar-ghost .pd-tool-btn.pd-tool-active {{
    background: #7c3aed !important;
    color: #fff !important;
    box-shadow: 0 0 8px rgba(124,58,237,0.5);
}}
.pd-toolbar-ghost .pd-tool-btn:hover {{
    background: rgba(124,58,237,0.25) !important;
    color: #c4b5fd !important;
}}
.pd-toolbar-mirror .pd-tool-btn.pd-tool-active {{
    background: linear-gradient(135deg, {_ACCENT_DIM} 50%, #7c3aed 50%) !important;
    color: #fff !important;
    box-shadow: 0 0 8px rgba(8,145,178,0.4) !important;
}}
.pd-toolbar-mirror .pd-tool-btn:hover {{
    background: rgba(8,145,178,0.18) !important;
    color: {_ACCENT} !important;
}}
#pd-zoom-level {{
    font-size: 11px;
    color: {_TEXT2};
    text-align: center;
    padding: 4px;
}}
.pd-size-btn {{
    padding: 0px 16px;
    min-width: 44px;
    border: 1px solid {_BORDER};
    background: transparent;
    color: {_TEXT2};
    border-radius: 4px;
    cursor: pointer;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.03em;
    transition: all 0.12s;
    line-height: 1.0;
}}
.pd-size-btn:hover {{
    background: {_BG2};
    color: {_TEXT};
    border-color: {_TEXT2};
}}
.pd-size-btn.pd-size-active {{
    background: {_ACCENT_DIM};
    color: {_BG0};
    border-color: {_ACCENT};
}}
"""

_ZOOM_BTN_HOVER_CSS = f"""
#pd-zoom-fit:hover, #pd-zoom-in:hover, #pd-zoom-out:hover {{
    background: {_BG2};
    color: {_TEXT};
}}
"""

_HUD_CSS = f"""
.pd-canvas-hud .pd-hud-body {{
    display: none;
    flex-direction: column;
    gap: 7px;
    padding-top: 8px;
    border-top: 1px solid {_BORDER};
    margin-top: 4px;
}}
.pd-canvas-hud:hover .pd-hud-body {{
    display: flex;
}}
.pd-seg-btn {{
    padding: 3px 12px;
    border: none;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.1s;
    white-space: nowrap;
}}
.pd-seg-btn.seg-active {{
    background: {_ACCENT};
    color: {_BG0};
}}
.pd-seg-btn:not(.seg-active) {{
    background: {_BG2};
    color: {_TEXT2};
}}
.pd-seg-btn:not(.seg-active):hover {{
    background: #475569;
    color: {_TEXT};
}}
.pd-seg-btn:first-child {{ border-radius: 5px 0 0 5px; }}
.pd-seg-btn:last-child  {{ border-radius: 0 5px 5px 0; }}
.pd-hud-label {{
    font-size: 10px;
    color: {_TEXT2};
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 2px;
}}
.pd-hud-chk-row {{
    display: flex;
    align-items: center;
    gap: 7px;
    cursor: pointer;
    user-select: none;
}}
.pd-hud-chk-row input {{
    accent-color: {_ACCENT};
    width: 13px;
    height: 13px;
    cursor: pointer;
    flex-shrink: 0;
}}
.pd-hud-chk-row span {{
    font-size: 12px;
    color: {_TEXT2};
}}
"""

_AGENT_ROW_CSS = f"""
.pd-agent-row {{
    display: flex;
    flex-direction: column;
    gap: 3px;
    padding: 6px 8px;
    border-radius: 6px;
    cursor: pointer;
    font-family: {_MONO};
    font-size: 13px;
    color: {_TEXT2};
    transition: background 0.1s, color 0.1s;
    user-select: none;
    border: 1px solid {_BORDER};
}}
.pd-agent-row:hover {{
    background: {_BG2};
    color: {_TEXT};
}}
.pd-agent-row.pd-active-agent-row {{
    background: rgba(251,146,60,0.15);
    border-color: #fb923c;
}}
.pd-agent-row.pd-active-agent-row:hover {{
    background: rgba(251,146,60,0.22);
    border-color: #fdba74;
}}
.pd-agent-row.pd-agent-selected {{
    background: rgba(22,163,74,0.18);
    border-color: #16a34a;
    color: {_TEXT};
    font-weight: 700;
}}
.pd-agent-row.pd-active-agent-row.pd-agent-selected {{
    background: rgba(22,163,74,0.25);
    border-color: #22c55e;
    color: {_TEXT};
    font-weight: 700;
}}
.pd-agent-row .pd-status-badge {{
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    opacity: 0.85;
}}
.pd-agent-row.pd-agent-selected .pd-status-badge {{
    opacity: 1;
}}
.pd-agent-row.pd-ghost-active-agent-row {{
    background: rgba(124,58,237,0.15);
    border-color: #a78bfa;
}}
.pd-agent-row.pd-ghost-active-agent-row:hover {{
    background: rgba(124,58,237,0.22);
    border-color: #c4b5fd;
}}
.pd-agent-row.pd-ghost-active-agent-row.pd-agent-selected {{
    background: rgba(22,163,74,0.25);
    border-color: #22c55e;
    color: {_TEXT};
    font-weight: 700;
}}
"""
