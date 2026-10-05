# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

"""Functions that generate JavaScript payloads sent to the frontend canvas."""
import json

from .. import viewer
from .trajectory import _compute_expert_waypoints


def _agent_frames_js(frames: list[list[dict]], static_agents: list[dict], map_data: dict,
                     expert_frames: list[list[dict]] | None = None,
                     n_user_experts: int = 0) -> str:
    """Return JS that sends dynamic agent, expert agent, static agent, and map data to the canvas renderer."""
    expert_frames = expert_frames or []
    return (
        f"window._pdAllAgentFrames = {json.dumps(frames)};"
        f"window._pdExpertFrames = {json.dumps(expert_frames)};"
        f"window._pdStaticAgents = {json.dumps(static_agents)};"
        f"window._pdMapData = {json.dumps(map_data)};"
        f"window._pdUserExpertCount = {n_user_experts};"
        f"if (window._pdAgentRenderer) {{"
        f"  window._pdAgentRenderer.setFrames(window._pdAllAgentFrames);"
        f"  window._pdAgentRenderer.setExpertFrames(window._pdExpertFrames);"
        f"  window._pdAgentRenderer.setStatic(window._pdStaticAgents);"
        f"}}"
        f"if (window._pdRedraw) window._pdRedraw();"
    )


def _ghost_frames_js(frames: list[list[dict]], static_agents: list[dict],
                     expert_frames: list[list[dict]] | None = None,
                     n_user_experts: int = 0) -> str:
    """Return JS that sends ghost env frame data to the ghost canvas renderer."""
    expert_frames = expert_frames or []
    return (
        f"window._pdGhostAllAgentFrames = {json.dumps(frames)};"
        f"window._pdGhostExpertFrames = {json.dumps(expert_frames)};"
        f"window._pdGhostStaticAgents = {json.dumps(static_agents)};"
        f"window._pdGhostUserExpertCount = {n_user_experts};"
        f"if (window._pdGhostRenderer) {{"
        f"  window._pdGhostRenderer.setFrames(window._pdGhostAllAgentFrames);"
        f"  window._pdGhostRenderer.setExpertFrames(window._pdGhostExpertFrames);"
        f"  window._pdGhostRenderer.setStatic(window._pdGhostStaticAgents);"
        f"}}"
        f"if (window._pdRedraw) window._pdRedraw();"
    )


def _ghost_frames_clear_js() -> str:
    """Return JS that clears all ghost env rendering data from the canvas."""
    return (
        "window._pdGhostAllAgentFrames = [];"
        "window._pdGhostExpertFrames = [];"
        "window._pdGhostStaticAgents = [];"
        "if (window._pdGhostRenderer) {"
        "  window._pdGhostRenderer.setFrames([]);"
        "  window._pdGhostRenderer.setExpertFrames([]);"
        "  window._pdGhostRenderer.setStatic([]);"
        "}"
        "if (window._pdRedraw) window._pdRedraw();"
    )


def _deep_reset_js() -> str:
    """Return JS that tears down ALL frontend canvas state back to a blank slate.

    Clears primary + ghost scene data, every selection/placement tool, the view
    transform and both renderers, then resets the tool to pan and redraws. Used by
    the deep reset (header button + config change) to recover from any desynced or
    faulty client state. Renderer/function globals (_pdRedraw, _pdSetTool, …) are
    left intact — only the data/state they operate on is wiped."""
    return (
        # primary scene data
        "window._pdAllAgentFrames = [];"
        "window._pdExpertFrames = [];"
        "window._pdStaticAgents = [];"
        "window._pdMapData = {};"
        "window._pdUserExpertCount = 0;"
        "window._pdGoalPositions = [];"
        "window._pdExpertWaypoints = [];"
        "window._pdLaneGraph = null;"
        # ghost scene data
        "window._pdGhostAllAgentFrames = [];"
        "window._pdGhostExpertFrames = [];"
        "window._pdGhostStaticAgents = [];"
        "window._pdGhostUserExpertCount = 0;"
        "window._pdGhostGoalPositions = [];"
        "window._pdGhostExpertWaypoints = [];"
        # selection state (primary + ghost)
        "window._pdSelectedNativeExpertIdx = -1;"
        "window._pdSelectedExpertIdx = -1; window._pdSelectedExpertSlot = -1;"
        "window._pdGhostSelectedNativeExpertIdx = -1;"
        "window._pdGhostSelectedExpertIdx = -1; window._pdGhostSelectedExpertSlot = -1;"
        # in-progress placement tools
        "window._pdAgentPlacement = {step:0};"
        "window._pdStaticPlacement = {step:0};"
        "window._pdExpertPlacement = {step:0};"
        "window._pdMovePlacement = {step:0};"
        # env focus + view transform
        "window._pdEnvFocus = 'primary';"
        "window._pdRenderTransform = null;"
        "window._pdScale = 1;"
        # renderers
        "if (window._pdAgentRenderer) {"
        "  window._pdAgentRenderer.setFrames([]);"
        "  window._pdAgentRenderer.setExpertFrames([]);"
        "  window._pdAgentRenderer.setStatic([]);"
        "  window._pdAgentRenderer.setSelected(-1);"
        "  window._pdAgentRenderer.setSelectedStatic(-1);"
        "  window._pdAgentRenderer.setSelectedExpert(-1);"
        "}"
        "if (window._pdGhostRenderer) {"
        "  window._pdGhostRenderer.setFrames([]);"
        "  window._pdGhostRenderer.setExpertFrames([]);"
        "  window._pdGhostRenderer.setStatic([]);"
        "  window._pdGhostRenderer.setSelected(-1);"
        "  window._pdGhostRenderer.setSelectedStatic(-1);"
        "  window._pdGhostRenderer.setSelectedExpert(-1);"
        "}"
        "if (window._pdSetTool) window._pdSetTool('pan');"
        "if (window._pdRedraw) window._pdRedraw();"
    )


def _restart_wait_js() -> str:
    """Return JS that overlays a 'restarting' banner and reloads the page once the
    backend is reachable again.

    The header Reset button asks the supervising run.sh loop to relaunch the whole
    app (fresh Python process; the C extension is NOT rebuilt). While the server is
    down the websocket drops, so we poll the origin and hard-reload as soon as it
    answers — the user lands on a clean, freshly-started session."""
    return (
        "(function(){"
        "  if (document.getElementById('pd-restart-overlay')) return;"
        "  var o=document.createElement('div');"
        "  o.id='pd-restart-overlay';"
        "  o.textContent='\\u21bb Restarting\\u2026 the page will reload automatically.';"
        "  o.setAttribute('style','position:fixed;inset:0;z-index:99999;display:flex;"
        "align-items:center;justify-content:center;background:rgba(10,12,16,0.92);"
        "color:#e6edf3;font:600 16px system-ui,sans-serif;');"
        "  document.body.appendChild(o);"
        "  var tries=0;"
        "  function ping(){"
        "    tries++;"
        "    fetch(window.location.origin+'/?_pd='+Date.now(),{cache:'no-store'})"
        "      .then(function(r){ if(r&&r.ok){ location.reload(); } else { retry(); } })"
        "      .catch(retry);"
        "  }"
        "  function retry(){ if(tries<180){ setTimeout(ping,1000); } }"
        "  setTimeout(ping,3000);"
        "})();"
    )


def _ghost_goal_js() -> str:
    """Return JS that sets _pdGhostGoalPositions and _pdGhostExpertWaypoints for ghost env display."""
    from .trajectory import _compute_ghost_expert_waypoints, _compute_ghost_goal_positions
    waypoints = _compute_ghost_expert_waypoints()
    positions = _compute_ghost_goal_positions()
    return (
        f"window._pdGhostGoalPositions = {json.dumps(positions)};"
        f"window._pdGhostExpertWaypoints = {json.dumps(waypoints)};"
        f"if (window._pdRedraw) window._pdRedraw();"
    )


def _goal_js(positions: list[dict]) -> str:
    """Return JS that sets _pdGoalPositions + _pdExpertWaypoints + _pdScale + _pdRenderTransform, then redraws."""
    t = viewer.last_render_transform
    scale = t["scale"] if t else 1.0
    rt = json.dumps(t) if t else "null"
    waypoints = _compute_expert_waypoints()
    return (
        f"window._pdGoalPositions = {json.dumps(positions)};"
        f"window._pdExpertWaypoints = {json.dumps(waypoints)};"
        f"window._pdScale = {scale};"
        f"window._pdRenderTransform = {rt};"
        f"if (window._pdRedraw) window._pdRedraw();"
    )
