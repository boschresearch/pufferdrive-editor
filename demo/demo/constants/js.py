# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

_MAIN_JS = """
(function () {
    var MIN_ZOOM = 0.5, MAX_ZOOM = 8, SENSITIVITY = 0.01;
    var _z = 1, _tx = 0, _ty = 0;
    var _currentTool = 'pan';
    var _isDragging = false, _dragStart = { x: 0, y: 0 };

    function _applyTransform() {
        window._pdViewState = { z: _z, tx: _tx, ty: _ty };
        var label = document.getElementById('pd-zoom-level');
        if (label) label.textContent = Math.round(_z * 100) + '%';
        if (window._pdRedraw) window._pdRedraw();
    }

    function _ensureZoomLabel() {
        if (document.getElementById('pd-zoom-level')) return;
        var overlay = document.getElementById('pd-zoom-overlay');
        if (!overlay) { setTimeout(_ensureZoomLabel, 200); return; }
        var el = document.createElement('div');
        el.id = 'pd-zoom-level';
        el.textContent = '100%';
        overlay.appendChild(el);
    }

    window._pdZoomReset = function () { _z = 1; _tx = 0; _ty = 0; _applyTransform(); };

    window._pdZoomStep = function (delta) {
        _z = delta > 0 ? Math.min(_z * 1.25, MAX_ZOOM) : Math.max(_z / 1.25, MIN_ZOOM);
        _applyTransform();
    };

    window._pdVehicleSizes = {
        add_agent:  {hl: 2.25, hw: 1.0},
        add_static: {hl: 2.25, hw: 1.0},
        add_expert: {hl: 2.25, hw: 1.0},
    };
    window._pdSetTool = function (tool) {
        _currentTool = tool;
        window._pdTool = tool;
        window._pdAgentPlacement = {step: 0};  // reset placement state on tool switch
        window._pdStaticPlacement = {step: 0}; // reset static placement state on tool switch
        window._pdExpertPlacement = {step: 0}; // reset expert placement state on tool switch
        window._pdMovePlacement = {step: 0};   // reset move state on tool switch
        // Only toggle active state on tool buttons that have a data-tool attribute.
        // Buttons without data-tool (e.g. mirror/"Both") are managed by Reflex state
        // and must not be touched here.
        document.querySelectorAll('.pd-tool-btn[data-tool]').forEach(function (btn) {
            btn.classList.toggle('pd-tool-active', btn.dataset.tool === tool);
        });
        var c = document.getElementById('pd-canvas-container');
        if (c) c.style.cursor = tool === 'select' ? 'default'
            : tool === 'add_agent' ? 'crosshair'
            : tool === 'add_static' ? 'crosshair'
            : tool === 'add_expert' ? 'crosshair'
            : (_isDragging ? 'grabbing' : 'grab');
        if (window._pdRedraw) window._pdRedraw();
    };

    // ── Fullscreen ────────────────────────────────────────────────────────────
    // Native fullscreen on the APP root (pd-app-root, which includes the header) so the
    // policy/map selectors stay visible while fullscreen. Normally the browser force-
    // exits native fullscreen on Esc, which would defeat the staged Esc handler below;
    // the Keyboard Lock API (Chromium) suppresses that, handing Esc back to JS. On
    // browsers without it (Firefox/Safari) Esc still hard-exits fullscreen — the staged
    // handler then degrades to "cancel edit AND exit" on the same press.
    window._pdIsFullscreen = false;  // mirrors document.fullscreenElement
    window._pdSetFullscreen = function (on) {
        if (on) {
            if (document.fullscreenElement) return;
            var root = document.getElementById('pd-app-root');
            if (!root || !root.requestFullscreen) return;
            var lock = function () {
                if (navigator.keyboard && navigator.keyboard.lock)
                    navigator.keyboard.lock(['Escape']).catch(function () {});
            };
            var p = root.requestFullscreen();
            if (p && p.then) p.then(lock).catch(function () {}); else lock();
        } else if (document.fullscreenElement) {
            document.exitFullscreen && document.exitFullscreen();
        }
    };
    window._pdToggleFullscreen = function () {
        window._pdSetFullscreen(!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', function () {
        window._pdIsFullscreen = !!document.fullscreenElement;
        if (!document.fullscreenElement && navigator.keyboard && navigator.keyboard.unlock)
            navigator.keyboard.unlock();
        if (window._pdRedraw) window._pdRedraw();
    });

    // True while any agent/expert/goal selection is active (mirrors Python selection
    // state, which pushes these flags on every select — see State._select_* scripts).
    function _pdHasSelection() {
        var r = window._pdAgentRenderer, g = window._pdGhostRenderer;
        if (r && (r.selectedSlot >= 0 || r.selectedStaticSlot >= 0 || r.selectedExpertSlot >= 0)) return true;
        if (g && (g.selectedSlot >= 0 || g.selectedStaticSlot >= 0 || g.selectedExpertSlot >= 0)) return true;
        if (window._pdSelectedExpertIdx >= 0 || window._pdSelectedNativeExpertIdx >= 0) return true;
        if (window._pdGhostSelectedExpertIdx >= 0 || window._pdGhostSelectedNativeExpertIdx >= 0) return true;
        return false;
    }

    function _attach() {
        var container = document.getElementById('pd-canvas-container');
        if (!container) { setTimeout(_attach, 200); return; }

        container.addEventListener('wheel', function (e) {
            e.preventDefault();
            var dy = e.deltaY;
            if (e.deltaMode === 1) dy *= 16;
            else if (e.deltaMode === 2) dy *= window.innerHeight;
            var factor = Math.max(0.85, Math.min(1.18, Math.exp(-dy * SENSITIVITY)));
            var newZ = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, _z * factor));
            // In side-by-side mode each pane has its own canvas and the drawing
            // pivot is that pane's center (canvas.width/2).  Use whichever pane
            // the cursor is currently over so the focal point stays under the mouse.
            var panWrap   = document.getElementById('pd-pan-wrapper');
            var ghostPane = document.getElementById('pd-ghost-pane');
            var ref;
            if (ghostPane && ghostPane.offsetWidth > 0 && panWrap) {
                var gr = ghostPane.getBoundingClientRect();
                ref = (e.clientX >= gr.left) ? gr : panWrap.getBoundingClientRect();
            } else {
                ref = panWrap ? panWrap.getBoundingClientRect() : container.getBoundingClientRect();
            }
            var mx = e.clientX - ref.left, my = e.clientY - ref.top;
            _tx += (mx - ref.width / 2 - _tx) * (1 - newZ / _z);
            _ty += (my - ref.height / 2 - _ty) * (1 - newZ / _z);
            _z = newZ; _applyTransform();
        }, { passive: false });

        container.addEventListener('mousedown', function (e) {
            if (_currentTool === 'pan') {
                e.preventDefault();
                _isDragging = true;
                _dragStart = { x: e.clientX - _tx, y: e.clientY - _ty };
                container.style.cursor = 'grabbing';
            }
        });
        container.addEventListener('mousemove', function (e) {
            if (_isDragging && _currentTool === 'pan') {
                _tx = e.clientX - _dragStart.x;
                _ty = e.clientY - _dragStart.y;
                _applyTransform();
                return;
            }
            if (_currentTool === 'select') {
                var canvas = document.getElementById('pd-canvas');
                var img    = document.getElementById('pd-frame-img');
                if (!canvas || !window._pdFit) return;
                if (!window._pdToCvsPreTf) return;
                var pre = window._pdToCvsPreTf(canvas, e.clientX, e.clientY);
                var f   = window._pdFit(canvas, img);
                if (!f) return;
                var imgX = (pre.cx - f.dx) / f.s;
                var imgY = (pre.cy - f.dy) / f.s;
                var HIT  = 30;
                var near = false;
                var frameIdx = (function() {
                    var el = document.getElementById('pd-current-frame-el');
                    return el ? (parseInt(el.textContent || '0', 10) || 0) : 0;
                })();
                var frames = (window._pdAllAgentFrames || [])[frameIdx] || [];
                for (var i = 0; i < frames.length && !near; i++) {
                    var a = frames[i];
                    var dx = a.cx - imgX, dy = a.cy - imgY;
                    if (dx*dx + dy*dy < HIT*HIT) near = true;
                }
                var statics = window._pdStaticAgents || [];
                for (var i = 0; i < statics.length && !near; i++) {
                    var a = statics[i];
                    var dx = a.cx - imgX, dy = a.cy - imgY;
                    if (dx*dx + dy*dy < HIT*HIT) near = true;
                }
                var exFrames = (window._pdExpertFrames || [])[frameIdx] || [];
                var nUser = window._pdUserExpertCount || 0;
                for (var i = 0; i < exFrames.length && !near; i++) {
                    var isUser = nUser > 0 && i >= exFrames.length - nUser;
                    if (!isUser) continue;
                    var a = exFrames[i];
                    var dx = a.cx - imgX, dy = a.cy - imgY;
                    if (dx*dx + dy*dy < HIT*HIT) near = true;
                }
                container.style.cursor = near ? 'pointer' : 'default';
            }
        });
        function _stopDrag() {
            if (_isDragging) {
                _isDragging = false;
                container.style.cursor = _currentTool === 'pan' ? 'grab' : 'crosshair';
            }
        }
        container.addEventListener('mouseup', _stopDrag);
        container.addEventListener('mouseleave', _stopDrag);

        document.addEventListener('keydown', function (e) {
            // Ignore shortcuts when typing in form fields.
            var tag = (e.target || document.activeElement || {}).tagName || '';
            if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;

            var k = e.key;
            // ── Escape (staged) ───────────────────────────────────────────────
            // Each Esc consumes ONE in-progress action; only once nothing is left to
            // cancel does a further Esc leave fullscreen. Order = most transient first.
            if (k === 'Escape') {
                // 1. In-progress expert waypoint / trajectory drag.
                if (window._pdAbortExpertDrag && window._pdAbortExpertDrag()) return;
                // 2. In-progress goal drag or agent move (drag + heading-aim phases).
                if (window._pdAbortGoalDrag && window._pdAbortGoalDrag()) return;
                // 3. Any active edit tool (move / goal / add agent / static / expert):
                //    drop it back to pan so Esc leaves the edit mode before touching fullscreen.
                //    _pdSetTool resets the placement state instantly; clicking pd-tool-pan
                //    syncs Python's edit-mode flags + toolbar highlight (same idiom as the P key).
                if (['move', 'goal', 'add_agent', 'add_static', 'add_expert'].indexOf(_currentTool) >= 0) {
                    window._pdSetTool('pan');
                    _click('pd-tool-pan');
                    return;
                }
                // 4. Active selection: clear it (and sync Python).
                if (_pdHasSelection()) {
                    if (window._pdAgentRenderer) {
                        window._pdAgentRenderer.setSelected(-1);
                        window._pdAgentRenderer.setSelectedStatic(-1);
                        window._pdAgentRenderer.setSelectedExpert(-1);
                    }
                    window._pdSelectedExpertIdx = -1;
                    window._pdSelectedNativeExpertIdx = -1;
                    window._pdGhostSelectedExpertIdx = -1;
                    window._pdGhostSelectedNativeExpertIdx = -1;
                    if (window._pdGhostRenderer) window._pdGhostRenderer.setSelectedExpert(-1);
                    if (window._pdRedraw) window._pdRedraw();
                    var btn = document.getElementById('pd-clear-sel-btn');
                    if (btn) btn.click();
                    return;
                }
                // 5. Nothing left to cancel — leave fullscreen if we're in it.
                if (document.fullscreenElement) { window._pdSetFullscreen(false); return; }
                return;
            }
            function _click(id) { var b = document.getElementById(id); if (b) b.click(); }
            // ── Playback ─────────────────────────────────────────────────────
            if (k === ' ') { e.preventDefault(); _click('pd-play-btn'); return; }
            if (k === 'ArrowLeft')  { e.preventDefault(); _click('pd-step-back-btn'); return; }
            if (k === 'ArrowRight') { e.preventDefault(); _click('pd-step-fwd-btn'); return; }
            if (k === 'Home') { e.preventDefault(); _click('pd-first-frame-btn'); return; }
            if (k === 'End')  { e.preventDefault(); _click('pd-last-frame-btn'); return; }
            // ── Tools (case-insensitive) ──────────────────────────────────────
            var ku = k.toUpperCase();
            if (ku === 'P') { window._pdSetTool('pan'); _click('pd-tool-pan'); return; }
            if (ku === 'S') { window._pdSetTool('select'); _click('pd-tool-select'); return; }
            if (ku === 'E') { _click('pd-tool-goal'); return; }
            if (ku === 'A') { _click('pd-tool-add-agent'); return; }
            if (ku === 'O') { _click('pd-tool-add-static'); return; }
            // ── View ─────────────────────────────────────────────────────────
            if (ku === 'R') { if (window._pdZoomReset) window._pdZoomReset(); return; }
            if (ku === 'F') { _click('pd-fullscreen-btn'); return; }
            if (k === '+' || k === '=') { _click('pd-zoom-in'); return; }
            if (k === '-') { _click('pd-zoom-out'); return; }
        });

        container.addEventListener('click', function (e) {
            if (e.target && e.target.id && e.target.id.indexOf('-trigger') !== -1) return;
            if (_currentTool !== 'select' || _isDragging) return;
            if (window._pdDragJustEnded) { window._pdDragJustEnded = false; return; }
            // In side-by-side mode the ghost canvas is a sibling inside this container.
            // Detect ghost canvas clicks so coordinates and signal routing are correct.
            var _clickedGhostCanvas = !!(e.target && e.target.id === 'pd-ghost-canvas');
            var canvas = document.getElementById(_clickedGhostCanvas ? 'pd-ghost-canvas' : 'pd-canvas');
            if (!canvas) return;
            var img = document.getElementById('pd-frame-img');
            var r = canvas.getBoundingClientRect();
            var cx = (e.clientX - r.left) * canvas.width  / r.width;
            var cy = (e.clientY - r.top)  * canvas.height / r.height;
            var vs = window._pdViewState || { z: 1, tx: 0, ty: 0 };
            var ox = canvas.width  / 2 + vs.tx - vs.z * canvas.width  / 2;
            var oy = canvas.height / 2 + vs.ty - vs.z * canvas.height / 2;
            var pcx = (cx - ox) / vs.z;
            var pcy = (cy - oy) / vs.z;
            if (!window._pdFit) return;
            var f = window._pdFit(canvas, img);
            if (!f) return;
            var relX = (pcx - f.dx) / f.dw;
            var relY = (pcy - f.dy) / f.dh;
            if (relX < 0 || relX > 1 || relY < 0 || relY > 1) return;
            if (img && img.naturalWidth > 0) {
                var _imgXc = relX * img.naturalWidth;
                var _imgYc = relY * img.naturalHeight;
                var _fEl = document.getElementById('pd-current-frame-el');
                var _fIdx = _fEl ? (parseInt(_fEl.textContent || '0', 10) || 0) : 0;
                // Ghost expert routing: side-by-side ghost canvas click OR overlay focus=ghost.
                var _ghostActiveC = window._pdGhostAllAgentFrames && window._pdGhostAllAgentFrames.length > 0;
                var _focusGhostC = _ghostActiveC && (
                    _clickedGhostCanvas ||
                    (!document.getElementById('pd-ghost-canvas') && window._pdEnvFocus === 'ghost')
                );
                var _exF = ((_focusGhostC ? window._pdGhostExpertFrames : window._pdExpertFrames) || [])[_fIdx] || [];
                var _nU = (_focusGhostC ? window._pdGhostUserExpertCount : window._pdUserExpertCount) || 0;
                var _exInId = _focusGhostC ? 'pd-ghost-expert-click-signal' : 'pd-expert-click-signal';
                var _HIT = 30;
                for (var _k = _exF.length - _nU; _k < _exF.length; _k++) {
                    var _ea = _exF[_k];
                    if (!_ea) continue;
                    var _dx = _ea.cx - _imgXc, _dy = _ea.cy - _imgYc;
                    if (_dx * _dx + _dy * _dy < _HIT * _HIT) {
                        var _uIdx = _k - (_exF.length - _nU);
                        var _exIn = document.getElementById(_exInId);
                        if (_exIn) {
                            var _exSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            _exSet.call(_exIn, String(_uIdx));
                            _exIn.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                        return;
                    }
                }
            }
            // Ghost canvas clicks in side-by-side mode go to a dedicated signal so Python
            // always routes them to the ghost env, independent of env_focus state.
            var _clickSigId = _clickedGhostCanvas ? 'pd-ghost-click-signal' : 'pd-click-signal';
            var input = document.getElementById(_clickSigId);
            if (input) {
                var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(input, relX.toFixed(6) + ',' + relY.toFixed(6));
                input.dispatchEvent(new Event('input', { bubbles: true }));
            }
        });
    }

    _ensureZoomLabel();
    _attach();

    // ── Scenario import: read the picked JSON file and push it to the Python handler ──
    (function _attachImport() {
        var fileEl = document.getElementById('pd-import-file');
        var sigEl = document.getElementById('pd-import-signal');
        if (!fileEl || !sigEl) { setTimeout(_attachImport, 400); return; }
        if (fileEl._pdWired) return;
        fileEl._pdWired = true;
        fileEl.addEventListener('change', function (e) {
            var file = e.target.files && e.target.files[0];
            if (!file) return;
            var reader = new FileReader();
            reader.onload = function (ev) {
                var setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(sigEl, String(ev.target.result));
                sigEl.dispatchEvent(new Event('input', { bubbles: true }));
                fileEl.value = '';  // allow re-importing the same file
            };
            reader.readAsText(file);
        });
    })();

})();
"""

_AGENT_RENDERER_JS = """
// ── Agent renderer ────────────────────────────────────────────────────────────
// Agent data format: { cx, cy, heading, hl, hw } in output-image pixel space.
// JS maps to canvas via fit.s/fit.dx/fit.dy, then rotates with ctx.translate +
// ctx.rotate — no per-corner integer rounding, so boxes are always crisp rectangles.
// ─────────────────────────────────────────────────────────────────────────────
(function () {
    const ARROW_CLR      = 'rgba(255,255,255,0.82)';
    const LABEL_CLR      = '#ffffff';
    const SHADOW         = '#000000';
    const SEL_FILL       = '#16a34a';
    const SEL_OUTLINE    = '#22c55e';

    function _c(key, fallback) {
        return window[key] || fallback;
    }

    function _drawBox(ctx, a, fit, fill, outline, drawArrow) {
        const cx = fit.dx + a.cx * fit.s;
        const cy = fit.dy + a.cy * fit.s;
        const hl = a.hl * fit.s;
        const hw = a.hw * fit.s;
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(a.heading);
        ctx.fillStyle   = fill;
        ctx.strokeStyle = outline;
        ctx.lineWidth   = Math.max(1, fit.s * 0.15);
        ctx.beginPath();
        ctx.rect(-hl, -hw, hl * 2, hw * 2);
        ctx.fill();
        ctx.stroke();
        if (drawArrow) {
            ctx.strokeStyle = ARROW_CLR;
            ctx.lineWidth   = Math.max(1, hl * 0.15);
            ctx.lineCap     = 'round';
            ctx.lineJoin    = 'round';
            ctx.beginPath();
            ctx.moveTo(-hl * 0.15, -hw * 0.55);
            ctx.lineTo( hl * 0.60,  0);
            ctx.lineTo(-hl * 0.15,  hw * 0.55);
            ctx.stroke();
            ctx.lineCap   = 'butt';
            ctx.lineJoin  = 'miter';
        }
        ctx.restore();
    }

    function _drawTrajectories(ctx, frames, frameIdx, fit, strokeStyle) {
        if (window._pdShowTrajectories === false) return;
        if (!frames || frames.length === 0) return;
        // Show each moving agent's FULL predefined route across the whole episode,
        // not just the trail traveled up to the current frame — so cap spans every
        // precomputed frame (frameIdx is no longer used to truncate the path).
        // Keyed by slot: only driven/moving agents carry a stable slot across frames,
        // so slot-less entries (e.g. expert frames) are skipped rather than collapsed
        // into one garbage polyline.
        var slotSegs = {};   // slot -> [[{cx,cy}]]
        var slotLast = {};   // slot -> last frame index seen
        var cap = frames.length;
        for (var i = 0; i < cap; i++) {
            var frame = frames[i] || [];
            for (var j = 0; j < frame.length; j++) {
                var a = frame[j];
                if (a.slot === undefined || a.slot === null) continue;
                var s = a.slot;
                if (slotSegs[s] === undefined) {
                    slotSegs[s] = [[{cx: a.cx, cy: a.cy}]];
                    slotLast[s] = i;
                } else {
                    var segs = slotSegs[s];
                    if (i - slotLast[s] > 1) {
                        segs.push([{cx: a.cx, cy: a.cy}]);
                    } else {
                        segs[segs.length - 1].push({cx: a.cx, cy: a.cy});
                    }
                    slotLast[s] = i;
                }
            }
        }
        ctx.save();
        ctx.setLineDash([3, 5]);
        ctx.lineWidth = Math.max(1, fit.s * 0.10);
        ctx.strokeStyle = strokeStyle || 'rgba(251,146,60,0.55)';
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        var slots = Object.keys(slotSegs);
        for (var si = 0; si < slots.length; si++) {
            var segs2 = slotSegs[slots[si]];
            for (var sg = 0; sg < segs2.length; sg++) {
                var seg = segs2[sg];
                if (seg.length < 2) continue;
                ctx.beginPath();
                ctx.moveTo(fit.dx + seg[0].cx * fit.s, fit.dy + seg[0].cy * fit.s);
                for (var k = 1; k < seg.length; k++) {
                    ctx.lineTo(fit.dx + seg[k].cx * fit.s, fit.dy + seg[k].cy * fit.s);
                }
                ctx.stroke();
            }
        }
        ctx.restore();
    }

    function _drawLabel(ctx, a, fit, fontSize, color) {
        const lx = fit.dx + a.lx * fit.s;
        const ly = fit.dy + a.ly * fit.s;
        ctx.font      = `bold ${fontSize}px sans-serif`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'alphabetic';
        ctx.fillStyle = color || LABEL_CLR;
        ctx.fillText(a.id, lx, ly);
    }

    window._pdAgentRenderer = {
        frames: [],
        expertFrames: [],
        staticAgents: [],
        selectedSlot: -1,
        selectedStaticSlot: -1,
        selectedExpertSlot: -1,

        setFrames(frames)           { this.frames = frames; },
        setExpertFrames(frames)     { this.expertFrames = frames; },
        setStatic(agents)           { this.staticAgents = agents; },
        setSelected(slot)           { this.selectedSlot = slot; },
        setSelectedStatic(slot)     { this.selectedStaticSlot = slot; },
        setSelectedExpert(slot)     { this.selectedExpertSlot = slot; },

        drawStatic(ctx, fit) {
            const staticFill = _c('_pdStaticFill', '#0153d6');   // = expert fill; parked shares expert color
            const staticLine = _c('_pdStaticOutline', '#64a0ff');
            const sel = this.selectedStaticSlot;
            for (const a of this.staticAgents) {
                const isSel = (sel >= 0 && a.slot === sel);
                _drawBox(ctx, a, fit, isSel ? SEL_FILL : staticFill, isSel ? SEL_OUTLINE : staticLine, false);
            }
            if (window._pdShowLabels !== false) {
                const fontSize = Math.max(10, Math.min(22, Math.round(fit.s * 8)));
                for (const a of this.staticAgents)
                    if (a.id != null) _drawLabel(ctx, a, fit, fontSize, staticLine);
            }
        },

        draw(ctx, frameIdx, fit) {
            // ── Driven trajectories (dashed trail behind each agent) ──────────
            _drawTrajectories(ctx, this.frames,       frameIdx, fit, 'rgba(251,146,60,0.50)');
            _drawTrajectories(ctx, this.expertFrames, frameIdx, fit, 'rgba(100,160,255,0.45)');

            const expertFill    = _c('_pdExpertFill',    '#0153d6');
            const expertLine    = _c('_pdExpertOutline', '#64a0ff');
            const experts = this.expertFrames[frameIdx] || [];
            const userExpertCount = window._pdUserExpertCount || 0;
            const selExIdx = (typeof window._pdSelectedExpertIdx !== 'undefined') ? window._pdSelectedExpertIdx : -1;
            const selNativeExIdx = (typeof window._pdSelectedNativeExpertIdx !== 'undefined') ? window._pdSelectedNativeExpertIdx : -1;
            const selExFrame = (selExIdx >= 0 && userExpertCount > 0)
                ? experts.length - userExpertCount + selExIdx : -1;
            for (let idx = 0; idx < experts.length; idx++) {
                const a = experts[idx];
                const isSelUser   = (selExFrame >= 0 && idx === selExFrame);
                const isSelNative = (selNativeExIdx >= 0 && idx < experts.length - userExpertCount && idx === selNativeExIdx);
                const isSel = isSelUser || isSelNative;
                _drawBox(ctx, a, fit, isSel ? SEL_FILL : expertFill, isSel ? SEL_OUTLINE : expertLine, true);
            }
            if (window._pdShowLabels !== false)
                for (const a of experts) _drawLabel(ctx, a, fit, Math.max(10, Math.min(22, Math.round(fit.s * 8))), expertLine);

            const agentFill = _c('_pdAgentFill', '#ea580c');
            const agentLine = _c('_pdAgentOutline', '#fb923c');
            const agents = window._pdGetLerpedFrame ? window._pdGetLerpedFrame(this.frames, frameIdx) : (this.frames[frameIdx] || []);
            if (agents.length === 0) return;
            const fontSize = Math.max(10, Math.min(22, Math.round(fit.s * 8)));
            const sel = this.selectedSlot;
            for (const a of agents) {
                const isSel = (sel >= 0 && a.slot === sel);
                _drawBox(ctx, a, fit, isSel ? SEL_FILL : agentFill, isSel ? SEL_OUTLINE : agentLine, true);
            }
            if (window._pdShowLabels !== false)
                for (const a of agents) _drawLabel(ctx, a, fit, fontSize, agentLine);
        },
    };

    // Ghost renderer — purple tint; opacity further controlled via ctx.globalAlpha.
    window._pdGhostRenderer = {
        frames: [],
        expertFrames: [],
        staticAgents: [],
        selectedExpertSlot: -1,
        selectedSlot: -1,
        selectedStaticSlot: -1,

        setFrames(f)              { this.frames = f; },
        setExpertFrames(f)        { this.expertFrames = f; },
        setStatic(a)              { this.staticAgents = a; },
        setSelectedExpert(slot)   { this.selectedExpertSlot = slot; },
        setSelected(slot)         { this.selectedSlot = slot; },
        setSelectedStatic(slot)   { this.selectedStaticSlot = slot; },

        drawStatic(ctx, fit) {
            const gsFill = _c('_pdGhostStaticFill', '#4c1d95');   // = ghost expert fill; parked shares expert color
            const gsLine = _c('_pdGhostStaticOutline', '#7c3aed');
            for (const a of this.staticAgents)
                _drawBox(ctx, a, fit, gsFill, gsLine, false);
            if (window._pdShowLabels !== false) {
                const fontSize = Math.max(10, Math.min(22, Math.round(fit.s * 8)));
                for (const a of this.staticAgents)
                    if (a.id != null) _drawLabel(ctx, a, fit, fontSize, gsLine);
            }
            const selStaticSlot = this.selectedStaticSlot;
            if (selStaticSlot >= 0) {
                for (const a of this.staticAgents) {
                    if (a.slot !== selStaticSlot) continue;
                    const acx = fit.dx + a.cx * fit.s;
                    const acy = fit.dy + a.cy * fit.s;
                    const hl = a.hl * fit.s;
                    const hw = a.hw * fit.s;
                    const gap = Math.max(3, fit.s * 0.6);
                    ctx.save();
                    ctx.translate(acx, acy);
                    ctx.rotate(a.heading);
                    ctx.strokeStyle = '#22c55e';
                    ctx.lineWidth = 2;
                    ctx.beginPath();
                    ctx.rect(-(hl + gap), -(hw + gap), (hl + gap) * 2, (hw + gap) * 2);
                    ctx.stroke();
                    ctx.restore();
                    break;
                }
            }
        },

        draw(ctx, frameIdx, fit) {
            // ── Ghost driven trajectories ─────────────────────────────────────
            _drawTrajectories(ctx, this.frames, frameIdx, fit, 'rgba(180,83,9,0.45)');
            _drawTrajectories(ctx, this.expertFrames, frameIdx, fit, 'rgba(124,58,237,0.40)');

            const geFill = _c('_pdGhostExpertFill', '#4c1d95');
            const geLine = _c('_pdGhostExpertOutline', '#7c3aed');
            const experts = this.expertFrames[frameIdx] || [];
            const fontSize = Math.max(10, Math.min(22, Math.round(fit.s * 8)));
            // Expert frames carry no slot — selection is matched by frame index,
            // mirroring the primary renderer (user experts are appended last).
            const userExpertCount = window._pdGhostUserExpertCount || 0;
            const selExIdx = (typeof window._pdGhostSelectedExpertIdx !== 'undefined') ? window._pdGhostSelectedExpertIdx : -1;
            const selNativeExIdx = (typeof window._pdGhostSelectedNativeExpertIdx !== 'undefined') ? window._pdGhostSelectedNativeExpertIdx : -1;
            const selExFrame = (selExIdx >= 0 && userExpertCount > 0)
                ? experts.length - userExpertCount + selExIdx : -1;
            const _isSelExpert = (idx) =>
                (selExFrame >= 0 && idx === selExFrame) ||
                (selNativeExIdx >= 0 && idx < experts.length - userExpertCount && idx === selNativeExIdx);
            for (let idx = 0; idx < experts.length; idx++) {
                const isSel = _isSelExpert(idx);
                _drawBox(ctx, experts[idx], fit, isSel ? '#166534' : geFill, isSel ? '#4ade80' : geLine, true);
            }
            if (window._pdShowLabels !== false)
                for (const a of experts) _drawLabel(ctx, a, fit, fontSize, geLine);
            for (let idx = 0; idx < experts.length; idx++) {
                if (!_isSelExpert(idx)) continue;
                const a = experts[idx];
                const acx = fit.dx + a.cx * fit.s;
                const acy = fit.dy + a.cy * fit.s;
                const hl = a.hl * fit.s;
                const hw = a.hw * fit.s;
                const gap = Math.max(3, fit.s * 0.6);
                ctx.save();
                ctx.translate(acx, acy);
                ctx.rotate(a.heading);
                ctx.strokeStyle = '#22c55e';
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.rect(-(hl + gap), -(hw + gap), (hl + gap) * 2, (hw + gap) * 2);
                ctx.stroke();
                ctx.restore();
                break;
            }
            const gFill = _c('_pdGhostFill', '#78280a');
            const gLine = _c('_pdGhostOutline', '#b45309');
            const agents = window._pdGetLerpedFrame ? window._pdGetLerpedFrame(this.frames, frameIdx) : (this.frames[frameIdx] || []);
            if (agents.length === 0) return;
            for (const a of agents) _drawBox(ctx, a, fit, gFill, gLine, true);
            if (window._pdShowLabels !== false)
                for (const a of agents) _drawLabel(ctx, a, fit, fontSize, gLine);
            const selAgentSlot = this.selectedSlot;
            if (selAgentSlot >= 0) {
                for (const a of agents) {
                    if (a.slot !== selAgentSlot) continue;
                    const acx = fit.dx + a.cx * fit.s;
                    const acy = fit.dy + a.cy * fit.s;
                    const hl = a.hl * fit.s;
                    const hw = a.hw * fit.s;
                    const gap = Math.max(3, fit.s * 0.6);
                    ctx.save();
                    ctx.translate(acx, acy);
                    ctx.rotate(a.heading);
                    ctx.strokeStyle = '#22c55e';
                    ctx.lineWidth = 2;
                    ctx.beginPath();
                    ctx.rect(-(hl + gap), -(hw + gap), (hl + gap) * 2, (hw + gap) * 2);
                    ctx.stroke();
                    ctx.restore();
                    break;
                }
            }
        },
    };
})();
"""

_GOAL_CANVAS_JS = """
(function () {
    // Goal positions in image-fraction space; updated from Python after each render.
    window._pdGoalPositions = window._pdGoalPositions || [];
    window._pdGhostGoalPositions = window._pdGhostGoalPositions || [];
    window._pdSelectedNativeExpertIdx = window._pdSelectedNativeExpertIdx !== undefined ? window._pdSelectedNativeExpertIdx : -1;
    window._pdGhostSelectedExpertIdx = window._pdGhostSelectedExpertIdx !== undefined ? window._pdGhostSelectedExpertIdx : -1;
    window._pdGhostSelectedNativeExpertIdx = window._pdGhostSelectedNativeExpertIdx !== undefined ? window._pdGhostSelectedNativeExpertIdx : -1;
    window._pdGhostExpertWaypoints = window._pdGhostExpertWaypoints || [];
    window._pdDragResult    = null;

    function _agentFill()    { return window._pdAgentFill    || '#ea580c'; }
    function _agentOutline() { return window._pdAgentOutline || '#fb923c'; }

    let _dragSlot = -1;
    let _startX = 0, _startY = 0;
    window._pdGoalDragIsGhost = false;
    window._pdGhostDragFx = undefined; window._pdGhostDragFy = undefined;
    window._pdCursorOnGhost = false; // true while mouse pointer is over pd-ghost-canvas
    // True while the active goal drag targets the ghost env (focus-ghost overlay).
    let _dragGoalIsGhost = false;
    let _dragCx = 0, _dragCy = 0;  // live canvas coords during goal drag

    let _wpDragAgentIdx = -1, _wpDragWpIdx = -1;
    let _wpDragStartX = 0, _wpDragStartY = 0;
    let _wpDragLiveFx = -1, _wpDragLiveFy = -1;

    let _trajDragAgentIdx = -1, _trajDragTrajStep = -1;
    let _trajDragStartX = 0, _trajDragStartY = 0;
    let _trajDragLiveFx = -1, _trajDragLiveFy = -1;
    // True while the active waypoint/trajectory drag targets the ghost env (focus-ghost overlay).
    let _dragIsGhost = false;
    window._pdDragJustEnded = false;

    // Map image dimensions into the canvas buffer (object-fit:contain).
    // ── Lane-graph helpers for live expert-placement preview ─────────────────
    function _ensureLaneGraph() {
        const md = window._pdMapData;
        if (!md || !md.lanes || md.lanes.length === 0) return null;
        if (window._pdLaneGraph && window._pdLaneGraph._src === md) return window._pdLaneGraph;
        const scale = window._pdScale || 1;
        const th2 = (0.5 * scale) * (0.5 * scale);
        const lanes = md.lanes;
        const n = lanes.length;
        const successors = [];
        for (let i = 0; i < n; i++) {
            successors.push([]);
            const last = lanes[i][lanes[i].length - 1];
            for (let j = 0; j < n; j++) {
                if (i === j) continue;
                const first = lanes[j][0];
                const dx = last[0] - first[0], dy = last[1] - first[1];
                if (dx*dx + dy*dy <= th2) successors[i].push(j);
            }
        }
        window._pdLaneGraph = { lanes, n, successors, _src: md };
        return window._pdLaneGraph;
    }
    function _snapToLaneJS(graph, ix, iy) {
        let best = -1, bseg = 0, bpx = ix, bpy = iy, minD2 = Infinity;
        for (let i = 0; i < graph.n; i++) {
            const lane = graph.lanes[i];
            for (let j = 0; j < lane.length - 1; j++) {
                const x1 = lane[j][0], y1 = lane[j][1];
                const x2 = lane[j+1][0], y2 = lane[j+1][1];
                const dx = x2-x1, dy = y2-y1, len2 = dx*dx+dy*dy;
                let t = len2 > 1e-9 ? ((ix-x1)*dx+(iy-y1)*dy)/len2 : 0;
                t = t < 0 ? 0 : t > 1 ? 1 : t;
                const px = x1+t*dx, py = y1+t*dy;
                const d2 = (ix-px)*(ix-px)+(iy-py)*(iy-py);
                if (d2 < minD2) { minD2 = d2; best = i; bseg = j; bpx = px; bpy = py; }
            }
        }
        return { lane: best, seg: bseg, px: bpx, py: bpy };
    }
    function _lanePathJS(graph, sl, ss, gl, gs) {
        if (sl === gl && gs >= ss) return [sl];
        const n = graph.n;
        const prev = new Int32Array(n).fill(-1);
        const vis  = new Uint8Array(n);
        const q    = new Int32Array(n);
        let qh = 0, qt = 0;
        q[qt++] = sl; vis[sl] = 1;
        let found = false;
        while (qh < qt && !found) {
            const cur = q[qh++];
            if (cur === gl && prev[cur] !== -1) { found = true; break; }
            for (const nxt of graph.successors[cur])
                if (!vis[nxt]) { prev[nxt] = cur; vis[nxt] = 1; q[qt++] = nxt; }
        }
        if (!found) return null;
        const path = [];
        let c = gl;
        while (c !== -1) { path.push(c); c = prev[c]; }
        path.reverse();
        return path;
    }
    function _trajPointsJS(graph, sl, ss, spx, spy, gl, gs, gpx, gpy, path, nSteps) {
        const wx = [spx], wy = [spy];
        const add = (x, y) => {
            if (Math.abs(x-wx[wx.length-1])>0.001||Math.abs(y-wy[wy.length-1])>0.001)
                { wx.push(x); wy.push(y); }
        };
        for (let p = 0; p < path.length; p++) {
            const lane = graph.lanes[path[p]];
            const sf = p === 0 ? ss+1 : 0;
            const st = p === path.length-1 ? gs : lane.length-1;
            for (let s = sf; s <= st; s++) add(lane[s][0], lane[s][1]);
        }
        add(gpx, gpy);
        const nw = wx.length;
        const arc = new Float32Array(nw);
        for (let i = 1; i < nw; i++) {
            const dx=wx[i]-wx[i-1], dy=wy[i]-wy[i-1];
            arc[i] = arc[i-1] + Math.sqrt(dx*dx+dy*dy);
        }
        const total = arc[nw-1];
        const pts = [];
        let j = 0;
        for (let t = 0; t < nSteps; t++) {
            const s = nSteps > 1 ? total*t/(nSteps-1) : 0;
            while (j < nw-2 && arc[j+1] < s) j++;
            const sl2 = arc[j+1]-arc[j];
            const a = sl2 > 1e-6 ? (s-arc[j])/sl2 : 0;
            pts.push([wx[j]+a*(wx[j+1]-wx[j]), wy[j]+a*(wy[j+1]-wy[j])]);
        }
        return { pts, totalPx: total };
    }

    // Falls back to window._pdMapData.img_w/img_h when the hidden img has no pixels.
    function _fit(canvas, img) {
        const iw = (img && img.naturalWidth) || (window._pdMapData && window._pdMapData.img_w) || 0;
        const ih = (img && img.naturalHeight) || (window._pdMapData && window._pdMapData.img_h) || 0;
        if (!iw || !ih) return null;
        const s  = Math.min(canvas.width / iw, canvas.height / ih);
        const dw = iw * s, dh = ih * s;
        return { dx: (canvas.width - dw) / 2, dy: (canvas.height - dh) / 2,
                 dw, dh, s, iw, ih };
    }

    // Convert viewport clientX/Y → logical canvas pixel coords.
    function _toCvs(canvas, clientX, clientY) {
        const r = canvas.getBoundingClientRect();
        return { cx: (clientX - r.left) * canvas.width  / r.width,
                 cy: (clientY - r.top)  * canvas.height / r.height };
    }

    // Expose _fit so _MAIN_JS can use it for the select-tool click handler.
    window._pdFit = _fit;

    // Like _toCvs but also applies the inverse of the canvas zoom/pan transform,
    // returning coords in "pre-transform" space (same space as _fit / image fractions).
    function _toCvsPreTf(canvas, clientX, clientY) {
        const r  = canvas.getBoundingClientRect();
        const cx = (clientX - r.left) * canvas.width  / r.width;
        const cy = (clientY - r.top)  * canvas.height / r.height;
        const vs = window._pdViewState || { z: 1, tx: 0, ty: 0 };
        const ox = canvas.width  / 2 + vs.tx - vs.z * canvas.width  / 2;
        const oy = canvas.height / 2 + vs.ty - vs.z * canvas.height / 2;
        return { cx: (cx - ox) / vs.z, cy: (cy - oy) / vs.z };
    }
    window._pdToCvsPreTf = _toCvsPreTf;

    function _currentFrame() {
        const el = document.getElementById('pd-current-frame-el');
        return el ? (parseInt(el.textContent || '0', 10) || 0) : 0;
    }

    // Draw a rotated car rectangle + chevron on the canvas.
    // canvasAngle = Math.atan2(dy, dx) in canvas space (Y-down).
    function _drawAgentShape(ctx, cx, cy, canvasAngle, halfL, halfW, fill, stroke) {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(canvasAngle);
        ctx.fillStyle = fill;
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.rect(-halfL, -halfW, halfL * 2, halfW * 2);
        ctx.fill(); ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(-halfL * 0.1, -halfW * 0.55);
        ctx.lineTo(halfL * 0.6, 0);
        ctx.lineTo(-halfL * 0.1, halfW * 0.55);
        ctx.strokeStyle = stroke; ctx.lineWidth = 1.5; ctx.stroke();
        ctx.restore();
    }

    // Draw the map (vector lanes/roads, or the raster fallback) into a transformed ctx.
    function _drawMapBase(ctx, f, img) {
        const md = window._pdMapData;
        if (md) {
            // Vector map — crisp at any zoom level.
            ctx.lineCap = 'round'; ctx.lineJoin = 'round';
            ctx.strokeStyle = md.lane_color;
            ctx.lineWidth = md.lane_w * f.s;
            for (const seg of md.lanes) {
                ctx.beginPath();
                ctx.moveTo(f.dx + seg[0][0] * f.s, f.dy + seg[0][1] * f.s);
                for (let i = 1; i < seg.length; i++)
                    ctx.lineTo(f.dx + seg[i][0] * f.s, f.dy + seg[i][1] * f.s);
                ctx.stroke();
            }
            ctx.strokeStyle = md.road_color;
            ctx.lineWidth = md.road_w * f.s;
            for (const seg of md.roads) {
                ctx.beginPath();
                ctx.moveTo(f.dx + seg[0][0] * f.s, f.dy + seg[0][1] * f.s);
                for (let i = 1; i < seg.length; i++)
                    ctx.lineTo(f.dx + seg[i][0] * f.s, f.dy + seg[i][1] * f.s);
                ctx.stroke();
            }
            ctx.lineCap = 'butt'; ctx.lineJoin = 'miter';
        } else if (img && img.naturalWidth) {
            ctx.drawImage(img, f.dx, f.dy, f.dw, f.dh);
        }
    }

    // Ghost goal markers — drawn on the main canvas overlay or the side-by-side pane.
    // overrideSlot/ovCx/ovCy give the live cursor-follow preview while dragging a ghost
    // goal (focus-ghost overlay only); -1 means draw every goal at its stored position.
    function _drawGhostGoalsOn(ctx, f, overrideSlot, ovCx, ovCy) {
        if (overrideSlot === undefined) overrideSlot = -1;
        if (window._pdShowGoals === false || !(window._pdGhostGoalPositions || []).length) return;
        // Both/mirror: while a goal is dragged in the PRIMARY pane, this (ghost) pane's same-slot
        // goal follows the cursor live too (shared fraction _pdGoalLiveFx).
        const _ggMb = document.getElementById('pd-tool-mirror');
        const _ggMirror = !!(_ggMb && _ggMb.classList.contains('pd-tool-active'))
            && !window._pdGoalDragIsGhost && _dragSlot >= 0 && window._pdGoalLiveFx !== undefined;
        const pxPerM = (window._pdScale || 1) * f.s;
        const rDot = 3;
        const r2m  = Math.max(5, 2.0 * pxPerM);
        const r5m  = Math.max(9, 5.0 * pxPerM);
        const fontSize = Math.max(10, r2m * 1.1);
        // Selected active vehicle's goal is drawn green to match the highlighted box.
        const _selSlot = (window._pdGhostRenderer && window._pdGhostRenderer.selectedSlot >= 0)
            ? window._pdGhostRenderer.selectedSlot : -1;
        ctx.font = `bold ${fontSize}px sans-serif`;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        for (const g of window._pdGhostGoalPositions) {
            if ((overrideSlot >= 0 && g.slot === overrideSlot) || (window._pdGoalDragIsGhost && g.slot === _dragSlot) || (_ggMirror && g.slot === _dragSlot)) continue; // drawn at cursor below
            const isSel = (_selSlot >= 0 && g.slot === _selSlot);
            const gx = f.dx + g.fx * f.dw;
            const gy = f.dy + g.fy * f.dh;
            ctx.beginPath(); ctx.arc(gx, gy, rDot, 0, Math.PI * 2);
            ctx.fillStyle = isSel ? '#fff' : '#a78bfa'; ctx.fill();
            if (window._pdShowGoalRadius !== false) {
                ctx.beginPath(); ctx.arc(gx, gy, r2m, 0, Math.PI * 2);
                ctx.strokeStyle = isSel ? '#16a34a' : '#7c3aed'; ctx.lineWidth = 2; ctx.stroke();
                ctx.setLineDash([4, 4]);
                ctx.beginPath(); ctx.arc(gx, gy, r5m, 0, Math.PI * 2);
                ctx.strokeStyle = isSel ? '#22c55e' : '#a78bfa'; ctx.lineWidth = 1.5; ctx.stroke();
                ctx.setLineDash([]);
            }
            if (window._pdShowLabels !== false) {
                const lblOff = (window._pdShowGoalRadius !== false) ? r5m : rDot;
                const lbl = g.label != null ? String(g.label) : String(g.slot);
                ctx.fillStyle = isSel ? '#22c55e' : '#a78bfa'; ctx.fillText(lbl, gx, gy - lblOff - fontSize * 0.6);
            }
        }
        if (overrideSlot >= 0) {
            const dragged = window._pdGhostGoalPositions.find(g => g.slot === overrideSlot);
            const dlbl = dragged && dragged.label != null ? String(dragged.label) : String(overrideSlot);
            ctx.beginPath(); ctx.arc(ovCx, ovCy, rDot, 0, Math.PI * 2);
            ctx.fillStyle = '#a78bfa'; ctx.fill();
            if (window._pdShowGoalRadius !== false) {
                ctx.beginPath(); ctx.arc(ovCx, ovCy, r2m, 0, Math.PI * 2);
                ctx.strokeStyle = '#eab308'; ctx.lineWidth = 2.5; ctx.stroke();
                ctx.setLineDash([4, 4]);
                ctx.beginPath(); ctx.arc(ovCx, ovCy, r5m, 0, Math.PI * 2);
                ctx.strokeStyle = '#fde047'; ctx.lineWidth = 1.5; ctx.stroke();
                ctx.setLineDash([]);
            }
            if (window._pdShowLabels !== false) {
                const dlblOff = (window._pdShowGoalRadius !== false) ? r5m : rDot;
                ctx.fillStyle = '#fde047'; ctx.fillText(dlbl, ovCx, ovCy - dlblOff - fontSize * 0.6);
            }
        }
        // Ghost goal drag override: draw dragged slot at live cursor position.
        if (window._pdGoalDragIsGhost && _dragSlot >= 0 && window._pdGhostDragFx !== undefined) {
            const dcx = f.dx + window._pdGhostDragFx * f.dw;
            const dcy = f.dy + window._pdGhostDragFy * f.dh;
            const dragged = (window._pdGhostGoalPositions || []).find(g => g.slot === _dragSlot);
            const dlbl = dragged && dragged.label != null ? String(dragged.label) : String(_dragSlot);
            ctx.beginPath(); ctx.arc(dcx, dcy, rDot, 0, Math.PI * 2);
            ctx.fillStyle = '#a78bfa'; ctx.fill();
            if (window._pdShowGoalRadius !== false) {
                ctx.beginPath(); ctx.arc(dcx, dcy, r2m, 0, Math.PI * 2);
                ctx.strokeStyle = '#eab308'; ctx.lineWidth = 2.5; ctx.stroke();
                ctx.setLineDash([4, 4]);
                ctx.beginPath(); ctx.arc(dcx, dcy, r5m, 0, Math.PI * 2);
                ctx.strokeStyle = '#fde047'; ctx.lineWidth = 1.5; ctx.stroke();
                ctx.setLineDash([]);
            }
            if (window._pdShowLabels !== false) {
                const dlblOff = (window._pdShowGoalRadius !== false) ? r5m : rDot;
                ctx.fillStyle = '#fde047'; ctx.fillText(dlbl, dcx, dcy - dlblOff - fontSize * 0.6);
            }
        }
        // Both/mirror: draw this pane's dragged-slot ghost goal at the live cursor fraction
        // mirrored from the primary pane's drag.
        if (_ggMirror) {
            const dcx = f.dx + window._pdGoalLiveFx * f.dw;
            const dcy = f.dy + window._pdGoalLiveFy * f.dh;
            const dragged = (window._pdGhostGoalPositions || []).find(g => g.slot === _dragSlot);
            const dlbl = dragged && dragged.label != null ? String(dragged.label) : String(_dragSlot);
            ctx.beginPath(); ctx.arc(dcx, dcy, rDot, 0, Math.PI * 2);
            ctx.fillStyle = '#a78bfa'; ctx.fill();
            if (window._pdShowGoalRadius !== false) {
                ctx.beginPath(); ctx.arc(dcx, dcy, r2m, 0, Math.PI * 2);
                ctx.strokeStyle = '#eab308'; ctx.lineWidth = 2.5; ctx.stroke();
                ctx.setLineDash([4, 4]);
                ctx.beginPath(); ctx.arc(dcx, dcy, r5m, 0, Math.PI * 2);
                ctx.strokeStyle = '#fde047'; ctx.lineWidth = 1.5; ctx.stroke();
                ctx.setLineDash([]);
            }
            if (window._pdShowLabels !== false) {
                const dlblOff = (window._pdShowGoalRadius !== false) ? r5m : rDot;
                ctx.fillStyle = '#fde047'; ctx.fillText(dlbl, dcx, dcy - dlblOff - fontSize * 0.6);
            }
        }
    }

    // Trajectory for the selected ghost user expert. Editable in both overlay mode
    // (routed via _dragIsGhost from primary canvas handlers) and side-by-side mode
    // (gc mousedown/mousemove set _dragIsGhost=true; mouseup uses gc for coords).
    // Visually distinct from the primary trajectory: purple points (ghost expert color)
    // ringed in green, vs. the primary's solid-green dots.
    // Live spline preview during a timestep drag: mirror Python _spline_fit_trajectory
    // (detrended + renormalized Gaussian displacement, sigma=2 timesteps, start & goal
    // pinned) so the previewed curve is visually identical to the trajectory the server
    // commits on drop. Fraction-space is affine to world-space, so applying the weighted
    // displacement directly to fx/fy matches the world-space computation. Returns tpts
    // unchanged when not dragging.
    function _splineFitTrajLive(tpts, agentIdx, isGhost, sigma) {
        // In mirror/Both mode the live drag preview is mirrored onto BOTH panes as it moves,
        // so ignore the _dragIsGhost/isGhost match (the selected expert index is aligned
        // across envs). Without mirror, only the pane the drag started on previews live.
        const _mBtn = document.getElementById('pd-tool-mirror');
        const _mOn = !!(_mBtn && _mBtn.classList.contains('pd-tool-active'));
        if ((!_mOn && _dragIsGhost !== isGhost) || _trajDragAgentIdx !== agentIdx || _trajDragLiveFx < 0)
            return tpts;
        const orig = tpts.find(tp => tp.t === _trajDragTrajStep);
        if (!orig) return tpts;
        const dFx = _trajDragLiveFx - orig.fx, dFy = _trajDragLiveFy - orig.fy;
        const s2 = 2.0 * sigma * sigma;
        const step = _trajDragTrajStep;
        const lastT = tpts.length ? tpts[tpts.length - 1].t : -1;
        const draggingGoal = (step === lastT);
        const g = (tt) => Math.exp(-((tt - step) ** 2) / s2);
        const w0 = g(0), wN = g(lastT);
        // Detrend so displacement tapers to 0 at the pinned endpoints (matches Python).
        const wRaw = (tt) => {
            let w = g(tt);
            if (lastT > 0) {
                const s = tt / lastT;
                w -= draggingGoal ? w0 * (1.0 - s) : (w0 * (1.0 - s) + wN * s);
            }
            return w;
        };
        const peak = wRaw(step) || 1.0;  // renormalize so dragged point lands on target
        return tpts.map(tp => {
            if (tp.t === 0) return tp;  // start always pinned
            const w = wRaw(tp.t) / peak;
            return { t: tp.t, fx: tp.fx + w * dFx, fy: tp.fy + w * dFy };
        });
    }

    function _drawGhostSelExpertOn(ctx, f) {
        const idx = (window._pdGhostSelectedExpertIdx !== undefined) ? window._pdGhostSelectedExpertIdx : -1;
        if (idx < 0 || !window._pdGhostExpertWaypoints || window._pdGhostExpertWaypoints.length === 0) return;
        const agent = window._pdGhostExpertWaypoints.find(a => a.agent_idx === idx);
        if (!agent) return;
        const pxPerM = (window._pdScale || 1) * f.s;
        const rDot = 3;
        const r2m  = Math.max(5, 2.0 * pxPerM);
        // Live spline preview while dragging a timestep dot (focus-ghost overlay only).
        const tpts = _splineFitTrajLive(agent.traj_pts || [], agent.agent_idx, true, 2.0);
        if (tpts.length >= 2) {
            ctx.beginPath();
            ctx.moveTo(f.dx + tpts[0].fx * f.dw, f.dy + tpts[0].fy * f.dh);
            for (let i = 1; i < tpts.length; i++)
                ctx.lineTo(f.dx + tpts[i].fx * f.dw, f.dy + tpts[i].fy * f.dh);
            ctx.strokeStyle = '#4ade80'; ctx.lineWidth = Math.max(1.5, f.s * 0.4);
            ctx.setLineDash([]); ctx.stroke();
        }
        // Purple dots ringed in green.
        const _geFill = window._pdGhostExpertFill || '#4c1d95';
        const _ringW  = Math.max(1, f.s * 0.25);
        for (const tp of tpts) {
            const px = f.dx + tp.fx * f.dw, py = f.dy + tp.fy * f.dh;
            ctx.beginPath();
            ctx.arc(px, py, Math.max(1.5, pxPerM * 0.18), 0, Math.PI * 2);
            ctx.fillStyle = _geFill; ctx.fill();
            ctx.strokeStyle = '#22c55e'; ctx.lineWidth = _ringW; ctx.stroke();
        }
        if (agent.points && agent.points.length > 0) {
            const gp = agent.points[agent.points.length - 1];
            const gx = f.dx + gp.fx * f.dw, gy = f.dy + gp.fy * f.dh;
            ctx.beginPath(); ctx.arc(gx, gy, rDot, 0, Math.PI * 2);
            ctx.fillStyle = '#fff'; ctx.fill();
            ctx.beginPath(); ctx.arc(gx, gy, r2m, 0, Math.PI * 2);
            ctx.strokeStyle = '#16a34a'; ctx.lineWidth = 2; ctx.stroke();
        }
    }

    // Side-by-side ghost pane: same map + view transform as the main canvas,
    // but only the ghost env's agents/goals, at full opacity.
    function _drawGhostPane() {
        const canvas = document.getElementById('pd-ghost-canvas');
        if (!canvas) return;
        const r = canvas.getBoundingClientRect();
        const w = Math.round(r.width), h = Math.round(r.height);
        if (!w || !h) return;
        if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
        const img = document.getElementById('pd-frame-img');
        const f = _fit(canvas, img);
        if (!f) return;
        const ctx = canvas.getContext('2d');
        const vs = window._pdViewState || { z: 1, tx: 0, ty: 0 };
        const ox = canvas.width  / 2 + vs.tx - vs.z * canvas.width  / 2;
        const oy = canvas.height / 2 + vs.ty - vs.z * canvas.height / 2;
        const md = window._pdMapData;
        ctx.fillStyle = (md && md.bg) || '#0f172a';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.setTransform(vs.z, 0, 0, vs.z, ox, oy);
        _drawMapBase(ctx, f, img);
        if (window._pdGhostRenderer) {
            window._pdGhostRenderer.drawStatic(ctx, f);
            window._pdGhostRenderer.draw(ctx, _currentFrame(), f);
        }
        _drawGhostGoalsOn(ctx, f);
        _drawGhostSelExpertOn(ctx, f);
        // Draw placement/interaction visuals when ghost env is focused, or whenever mirror
        // mode is active. In mirror mode the preview is mirrored onto BOTH panes at the same
        // fractional location regardless of which canvas the cursor is physically over, so we
        // must NOT gate this on _pdCursorOnGhost (that hid the ghost-side mirror while the
        // cursor was on the focus canvas).
        const _gMirrorBtn = document.getElementById('pd-tool-mirror');
        const _gMirrorOn = !!(_gMirrorBtn && _gMirrorBtn.classList.contains('pd-tool-active'));
        const _gShowPrev = window._pdEnvFocus === 'ghost' || _gMirrorOn;
        if (_gShowPrev) {
            const pxPerM2 = (window._pdScale || 1) * f.s;
            const rDot2 = 3;
            const r2m2  = Math.max(5, 2.0 * pxPerM2);
            const r5m2  = Math.max(9, 5.0 * pxPerM2);
            const gFill  = window._pdGhostFill    || '#4c1d95';
            const gLine  = window._pdGhostOutline  || '#8b5cf6';
            const gsFill = window._pdGhostStaticFill    || '#1e3a8a';
            const gsLine = window._pdGhostStaticOutline || '#3b82f6';
            ctx.textBaseline = 'middle';

            // Agent placement preview with ghost colours.
            const apG = window._pdAgentPlacement;
            if (apG && window._pdTool === 'add_agent') {
                const _aszG = (window._pdVehicleSizes && window._pdVehicleSizes.add_agent) || {hl: 2.25, hw: 1.0};
                const halfL = pxPerM2 * _aszG.hl, halfW = pxPerM2 * _aszG.hw;
                const hasCur = apG.curFx !== undefined;
                const curCx = hasCur ? f.dx + apG.curFx * f.dw : null;
                const curCy = hasCur ? f.dy + apG.curFy * f.dh : null;
                if (apG.step === 0) {
                    if (hasCur) {
                        ctx.globalAlpha = 0.55;
                        _drawAgentShape(ctx, curCx, curCy, 0, halfL, halfW, gFill, gLine);
                        ctx.globalAlpha = 1.0;
                        ctx.fillStyle = gLine;
                        ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                        ctx.fillText('› click to place', curCx + halfL + 4, curCy - halfW - 4);
                    }
                } else if (apG.step === 1) {
                    const pcx = f.dx + apG.fx * f.dw, pcy = f.dy + apG.fy * f.dh;
                    const ang = (hasCur && (curCx !== pcx || curCy !== pcy))
                        ? Math.atan2(curCy - pcy, curCx - pcx) : 0;
                    _drawAgentShape(ctx, pcx, pcy, ang, halfL, halfW, gFill, gLine);
                    if (hasCur) {
                        ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(curCx, curCy);
                        ctx.strokeStyle = gLine; ctx.lineWidth = 1.5;
                        ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
                    }
                    ctx.fillStyle = gLine;
                    ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    ctx.fillText('› click heading', pcx + halfL + 4, pcy - halfW - 4);
                } else if (apG.step === 2) {
                    const pcx = f.dx + apG.fx * f.dw, pcy = f.dy + apG.fy * f.dh;
                    const hcx = f.dx + apG.hfx * f.dw, hcy = f.dy + apG.hfy * f.dh;
                    const ang = Math.atan2(hcy - pcy, hcx - pcx);
                    _drawAgentShape(ctx, pcx, pcy, ang, halfL, halfW, gFill, gLine);
                    if (hasCur) {
                        ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(curCx, curCy);
                        ctx.strokeStyle = gLine; ctx.lineWidth = 1.5;
                        ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]);
                        ctx.beginPath(); ctx.arc(curCx, curCy, rDot2, 0, Math.PI * 2);
                        ctx.fillStyle = gLine; ctx.fill();
                        ctx.beginPath(); ctx.arc(curCx, curCy, r2m2, 0, Math.PI * 2);
                        ctx.strokeStyle = gLine; ctx.lineWidth = 1.5; ctx.stroke();
                    }
                    ctx.fillStyle = gLine;
                    ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    ctx.fillText('› click goal', pcx + halfL + 4, pcy - halfW - 4);
                }
            }

            // Static placement preview with ghost-static colours.
            const spG = window._pdStaticPlacement;
            if (spG && window._pdTool === 'add_static') {
                const _sszG = (window._pdVehicleSizes && window._pdVehicleSizes.add_static) || {hl: 2.25, hw: 1.0};
                const halfL = pxPerM2 * _sszG.hl, halfW = pxPerM2 * _sszG.hw;
                const hasCur = spG.curFx !== undefined;
                const curCx = hasCur ? f.dx + spG.curFx * f.dw : null;
                const curCy = hasCur ? f.dy + spG.curFy * f.dh : null;
                if (spG.step === 0) {
                    if (hasCur) {
                        ctx.globalAlpha = 0.55;
                        _drawAgentShape(ctx, curCx, curCy, 0, halfL, halfW, gsFill, gsLine);
                        ctx.globalAlpha = 1.0;
                        ctx.fillStyle = gsLine;
                        ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                        ctx.fillText('› click to place', curCx + halfL + 4, curCy - halfW - 4);
                    }
                } else if (spG.step === 1) {
                    const pcx = f.dx + spG.fx * f.dw, pcy = f.dy + spG.fy * f.dh;
                    const ang = (hasCur && (curCx !== pcx || curCy !== pcy))
                        ? Math.atan2(curCy - pcy, curCx - pcx) : 0;
                    _drawAgentShape(ctx, pcx, pcy, ang, halfL, halfW, gsFill, gsLine);
                    if (hasCur) {
                        ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(curCx, curCy);
                        ctx.strokeStyle = gsLine; ctx.lineWidth = 1.5;
                        ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
                    }
                    ctx.fillStyle = gsLine;
                    ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    ctx.fillText('› click heading', pcx + halfL + 4, pcy - halfW - 4);
                }
            }

            // Move tool preview on ghost canvas (ghost drag, or mirror-active primary drag).
            const mvpG = window._pdMovePlacement;
            const _gmpMirrorBtn = document.getElementById('pd-tool-mirror');
            const _gmpMirrorOn = !!(_gmpMirrorBtn && _gmpMirrorBtn.classList.contains('pd-tool-active'));
            const _showGhostMove = mvpG && mvpG.car && window._pdTool === 'move' &&
                (mvpG.isGhost || _gmpMirrorOn);
            if (_showGhostMove) {
                const mhl = Math.max(6, mvpG.car.hl * f.s), mhw = Math.max(3, mvpG.car.hw * f.s);
                const mHasCur = mvpG.curFx !== undefined;
                const mcx = mHasCur ? f.dx + mvpG.curFx * f.dw : null;
                const mcy = mHasCur ? f.dy + mvpG.curFy * f.dh : null;
                const mFill = gFill, mLine = gLine;
                if (mvpG.step === 1 && mvpG.car.kind === 'e' && mHasCur) {
                    const graph = _ensureLaneGraph();
                    let trajPts = null, snapStart = null, startHeading = mvpG.car.heading || 0;
                    if (graph && mvpG.car.goalCx !== undefined) {
                        snapStart = _snapToLaneJS(graph, mvpG.curFx * f.iw, mvpG.curFy * f.ih);
                        const snapGoal = _snapToLaneJS(graph, mvpG.car.goalCx, mvpG.car.goalCy);
                        if (snapStart.lane >= 0 && snapGoal.lane >= 0) {
                            const ld = graph.lanes[snapStart.lane], sd = snapStart.seg;
                            startHeading = Math.atan2(ld[sd+1][1]-ld[sd][1], ld[sd+1][0]-ld[sd][0]);
                            const path = _lanePathJS(graph, snapStart.lane, snapStart.seg, snapGoal.lane, snapGoal.seg);
                            if (path) {
                                const res = _trajPointsJS(graph,
                                    snapStart.lane, snapStart.seg, snapStart.px, snapStart.py,
                                    snapGoal.lane, snapGoal.seg, snapGoal.px, snapGoal.py, path, 91);
                                trajPts = res.pts;
                            }
                        }
                    }
                    const scx = (snapStart && snapStart.lane >= 0) ? f.dx + snapStart.px * f.s : mcx;
                    const scy = (snapStart && snapStart.lane >= 0) ? f.dy + snapStart.py * f.s : mcy;
                    ctx.globalAlpha = 0.6;
                    _drawAgentShape(ctx, scx, scy, startHeading, mhl, mhw, mFill, mLine);
                    ctx.globalAlpha = 1.0;
                    ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    if (trajPts) {
                        ctx.beginPath();
                        ctx.moveTo(f.dx + trajPts[0][0] * f.s, f.dy + trajPts[0][1] * f.s);
                        for (let ti = 1; ti < trajPts.length; ti++)
                            ctx.lineTo(f.dx + trajPts[ti][0] * f.s, f.dy + trajPts[ti][1] * f.s);
                        ctx.strokeStyle = 'rgba(139,92,246,0.8)'; ctx.lineWidth = 2;
                        ctx.setLineDash([5, 4]); ctx.stroke(); ctx.setLineDash([]);
                        ctx.fillStyle = mLine; ctx.fillText('› release to drop', scx + mhl + 4, scy - mhw - 4);
                    } else {
                        ctx.fillStyle = '#f87171'; ctx.fillText('✕ no road-lane path here', mcx + mhl + 4, mcy - mhw - 4);
                    }
                } else if (mvpG.step === 1 && mHasCur) {
                    ctx.globalAlpha = 0.6;
                    _drawAgentShape(ctx, mcx, mcy, mvpG.car.heading || 0, mhl, mhw, mFill, mLine);
                    ctx.globalAlpha = 1.0;
                    ctx.fillStyle = mLine; ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    ctx.fillText('› release to drop', mcx + mhl + 4, mcy - mhw - 4);
                } else if (mvpG.step === 2) {
                    const pcx = f.dx + mvpG.dfx * f.dw, pcy = f.dy + mvpG.dfy * f.dh;
                    const ang = (mHasCur && (mcx !== pcx || mcy !== pcy))
                        ? Math.atan2(mcy - pcy, mcx - pcx) : (mvpG.car.heading || 0);
                    _drawAgentShape(ctx, pcx, pcy, ang, mhl, mhw, mFill, mLine);
                    if (mHasCur) {
                        ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(mcx, mcy);
                        ctx.strokeStyle = mLine; ctx.lineWidth = 1.5;
                        ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
                    }
                    ctx.fillStyle = mLine; ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    ctx.fillText('› click to aim heading', pcx + mhl + 4, pcy - mhw - 4);
                }
            }

            // Expert placement preview (same green colours regardless of env).
            const epG = window._pdExpertPlacement;
            if (epG && window._pdTool === 'add_expert') {
                const _eszG = (window._pdVehicleSizes && window._pdVehicleSizes.add_expert) || {hl: 2.25, hw: 1.0};
                const halfL = pxPerM2 * _eszG.hl, halfW = pxPerM2 * _eszG.hw;
                const hasCur = epG.curFx !== undefined;
                const curCx = hasCur ? f.dx + epG.curFx * f.dw : null;
                const curCy = hasCur ? f.dy + epG.curFy * f.dh : null;
                if (epG.step === 0) {
                    if (hasCur) {
                        ctx.globalAlpha = 0.55;
                        _drawAgentShape(ctx, curCx, curCy, 0, halfL, halfW, '#065f46', '#34d399');
                        ctx.globalAlpha = 1.0;
                        ctx.fillStyle = '#34d399';
                        ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                        ctx.fillText('› click start (follows road lane)', curCx + halfL + 4, curCy - halfW - 4);
                    }
                } else if (epG.step === 1) {
                    const graph2 = _ensureLaneGraph();
                    let startHeading2 = 0, trajPts2 = null, noPath2 = false;
                    let snapStart2 = null, snapGoal2 = null;
                    if (graph2 && hasCur) {
                        const six2 = epG.sfx * f.iw, siy2 = epG.sfy * f.ih;
                        const gix2 = epG.curFx * f.iw, giy2 = epG.curFy * f.ih;
                        snapStart2 = _snapToLaneJS(graph2, six2, siy2);
                        snapGoal2  = _snapToLaneJS(graph2, gix2, giy2);
                        if (snapStart2.lane >= 0 && snapGoal2.lane >= 0) {
                            const ld2 = graph2.lanes[snapStart2.lane];
                            const sd2 = snapStart2.seg;
                            startHeading2 = Math.atan2(ld2[sd2+1][1]-ld2[sd2][1], ld2[sd2+1][0]-ld2[sd2][0]);
                            const path2 = _lanePathJS(graph2, snapStart2.lane, snapStart2.seg,
                                                       snapGoal2.lane, snapGoal2.seg);
                            if (path2) {
                                const res2 = _trajPointsJS(graph2,
                                    snapStart2.lane, snapStart2.seg, snapStart2.px, snapStart2.py,
                                    snapGoal2.lane, snapGoal2.seg, snapGoal2.px, snapGoal2.py,
                                    path2, 91);
                                trajPts2 = res2.pts;
                                epG._avgSpeedMs = (res2.totalPx / (window._pdScale || 1)) / 9.0;
                            } else { noPath2 = true; }
                        }
                    }
                    const scx2 = snapStart2 ? f.dx + snapStart2.px * f.s : f.dx + epG.sfx * f.dw;
                    const scy2 = snapStart2 ? f.dy + snapStart2.py * f.s : f.dy + epG.sfy * f.dh;
                    _drawAgentShape(ctx, scx2, scy2, startHeading2, halfL, halfW, '#065f46', '#34d399');
                    ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    if (trajPts2) {
                        ctx.beginPath();
                        ctx.moveTo(f.dx + trajPts2[0][0] * f.s, f.dy + trajPts2[0][1] * f.s);
                        for (let ti = 1; ti < trajPts2.length; ti++)
                            ctx.lineTo(f.dx + trajPts2[ti][0] * f.s, f.dy + trajPts2[ti][1] * f.s);
                        ctx.strokeStyle = 'rgba(52,211,153,0.7)'; ctx.lineWidth = 2;
                        ctx.setLineDash([5, 4]); ctx.stroke(); ctx.setLineDash([]);
                        const dotR2 = Math.max(1.5, pxPerM2 * 0.18);
                        ctx.fillStyle = '#34d399';
                        for (let ti = 0; ti < trajPts2.length; ti++) {
                            ctx.beginPath();
                            ctx.arc(f.dx + trajPts2[ti][0] * f.s, f.dy + trajPts2[ti][1] * f.s,
                                    dotR2, 0, Math.PI * 2);
                            ctx.fill();
                        }
                        const gcx2 = f.dx + snapGoal2.px * f.s, gcy2 = f.dy + snapGoal2.py * f.s;
                        ctx.beginPath(); ctx.arc(gcx2, gcy2, rDot2, 0, Math.PI * 2);
                        ctx.fillStyle = '#fff'; ctx.fill();
                        ctx.beginPath(); ctx.arc(gcx2, gcy2, r2m2, 0, Math.PI * 2);
                        ctx.strokeStyle = '#34d399'; ctx.lineWidth = 2; ctx.stroke();
                        ctx.setLineDash([4, 4]);
                        ctx.beginPath(); ctx.arc(gcx2, gcy2, r5m2, 0, Math.PI * 2);
                        ctx.strokeStyle = '#6ee7b7'; ctx.lineWidth = 1.5; ctx.stroke();
                        ctx.setLineDash([]);
                        const avgMs2 = epG._avgSpeedMs || 0;
                        const lbl2 = avgMs2.toFixed(1) + ' m/s (' + (avgMs2 * 3.6).toFixed(1) + ' km/h)';
                        ctx.strokeStyle = '#000'; ctx.lineWidth = 3;
                        ctx.strokeText(lbl2, gcx2 + r5m2 + 4, gcy2);
                        ctx.fillStyle = '#34d399'; ctx.fillText(lbl2, gcx2 + r5m2 + 4, gcy2);
                        ctx.fillText('› click goal', scx2 + halfL + 4, scy2 - halfW - 4);
                    } else if (noPath2 && hasCur) {
                        ctx.beginPath(); ctx.arc(curCx, curCy, r2m2, 0, Math.PI * 2);
                        ctx.fillStyle = 'rgba(220,38,38,0.25)'; ctx.fill();
                        ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 2; ctx.stroke();
                        ctx.fillStyle = '#ef4444';
                        ctx.fillText('no path — pick another goal', curCx + r2m2 + 4, curCy - 4);
                        ctx.fillStyle = '#34d399';
                        ctx.fillText('› click goal', scx2 + halfL + 4, scy2 - halfW - 4);
                    } else if (hasCur) {
                        ctx.beginPath(); ctx.moveTo(scx2, scy2); ctx.lineTo(curCx, curCy);
                        ctx.strokeStyle = '#34d399'; ctx.lineWidth = 1.5;
                        ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
                        ctx.beginPath(); ctx.arc(curCx, curCy, rDot2, 0, Math.PI * 2);
                        ctx.fillStyle = '#fff'; ctx.fill();
                        ctx.beginPath(); ctx.arc(curCx, curCy, r2m2, 0, Math.PI * 2);
                        ctx.strokeStyle = '#34d399'; ctx.lineWidth = 2; ctx.stroke();
                        ctx.fillStyle = '#34d399';
                        ctx.fillText('› click goal', scx2 + halfL + 4, scy2 - halfW - 4);
                    }
                }
            }
        }
        ctx.restore();
    }

    // Draw the frame image; if overrideSlot >= 0, overdraw that goal marker
    // at (cx, cy) in logical canvas pixels (live drag feedback).

    // ── Occlusion overlay (computed live in JS for one ego agent) ─────────────
    // Shadows (grey polygons) + occluded cars (light diagonal stripes), in image-px
    // space (same as agent cx/cy), so they overlay the interactive canvas directly.
    function _occBoxCorners(a) {
        const ch = Math.cos(a.heading), sh = Math.sin(a.heading);
        const out = [];
        for (const [dx, dy] of [[a.hl, a.hw], [a.hl, -a.hw], [-a.hl, -a.hw], [-a.hl, a.hw]])
            out.push([a.cx + dx * ch - dy * sh, a.cy + dx * sh + dy * ch]);
        return out;
    }
    // Combine dynamic agents + static + expert cars into one list of occlusion makers,
    // each tagged with a unique key so occluded cars of any kind can be striped.
    function _occCars(agents, statics, experts) {
        const cars = [];
        for (const a of (agents || []))
            cars.push({ cx: a.cx, cy: a.cy, hl: a.hl, hw: a.hw, heading: a.heading, key: 'a' + a.slot });
        for (const s of (statics || []))
            cars.push({ cx: s.cx, cy: s.cy, hl: s.hl, hw: s.hw, heading: s.heading, key: 's' + s.slot });
        for (let i = 0; i < (experts || []).length; i++) {
            const e = experts[i];
            cars.push({ cx: e.cx, cy: e.cy, hl: e.hl, hw: e.hw, heading: e.heading, key: 'e' + i });
        }
        return cars;
    }
    // egoKey identifies the ego car; all OTHER cars (agents/static/expert) occlude.
    function _computeOcclusion(cars, egoKey) {
        const res = { shadows: [], occluded: new Set() };
        const ego = cars.find(c => c.key === egoKey);
        if (!ego) return res;
        const ex = ego.cx, ey = ego.cy;
        const scale = window._pdScale || 1;
        const rangePx = 50.0 * scale;       // ~50 m sensor range
        const rayPx = rangePx * 2.0;        // shadow length
        const N = 720, thresh = 0.6, TAU = 2 * Math.PI;
        const norm = x => ((x % TAU) + TAU) % TAU;
        const others = [];
        for (const a of cars) {
            if (a.key === egoKey) continue;
            const d = Math.hypot(a.cx - ex, a.cy - ey);
            if (d < 1e-6 || d > rangePx) continue;
            others.push({ d, a });
        }
        others.sort((p, q) => p.d - q.d);
        const covered = new Uint8Array(N);
        for (const { a } of others) {
            const corners = _occBoxCorners(a);
            const angs = corners.map(([px, py]) => Math.atan2(py - ey, px - ex));
            const order = [0, 1, 2, 3].sort((i, j) => angs[i] - angs[j]);
            const sa = order.map(i => angs[i]);
            // Largest cyclic gap; the box subtends the complement of that gap.
            let gmax = 0, gbest = -1;
            for (let i = 0; i < 4; i++) {
                const g = norm(sa[(i + 1) % 4] - sa[i]);
                if (g > gbest) { gbest = g; gmax = i; }
            }
            const iStart = order[(gmax + 1) % 4], iEnd = order[gmax];
            const aStart = angs[iStart], aEnd = angs[iEnd];
            const pMin = corners[iStart], pMax = corners[iEnd];
            const b0 = Math.floor(norm(aStart) / TAU * N);
            const b1 = Math.floor(norm(aEnd) / TAU * N);
            const span = (((b1 - b0) % N) + N) % N;
            let ncov = 0;
            const bins = [];
            for (let k = 0; k <= span; k++) { const b = (b0 + k) % N; bins.push(b); if (covered[b]) ncov++; }
            if (bins.length && ncov / bins.length >= thresh) {
                res.occluded.add(a.key);
            } else {
                res.shadows.push([
                    pMin,
                    [pMin[0] + rayPx * Math.cos(aStart), pMin[1] + rayPx * Math.sin(aStart)],
                    [pMax[0] + rayPx * Math.cos(aEnd), pMax[1] + rayPx * Math.sin(aEnd)],
                    pMax,
                ]);
                for (const b of bins) covered[b] = 1;
            }
        }
        return res;
    }
    // Build the occlusion state for one env (or null if disabled / ego missing).
    function _occState(agents, statics, experts, egoSlot) {
        if (!window._pdShowOcclusions || typeof egoSlot !== 'number' || egoSlot < 0) return null;
        const cars = _occCars(agents, statics, experts);
        const egoKey = 'a' + egoSlot;
        if (!cars.some(c => c.key === egoKey)) return null;
        return { cars, egoKey, occ: _computeOcclusion(cars, egoKey) };
    }
    function _drawOcclusionShadows(ctx, f, st) {
        if (!st || !st.occ.shadows.length) return;
        ctx.save();
        ctx.fillStyle = 'rgba(160,160,160,0.32)';
        for (const poly of st.occ.shadows) {
            ctx.beginPath();
            for (let i = 0; i < poly.length; i++) {
                const px = f.dx + poly[i][0] * f.s, py = f.dy + poly[i][1] * f.s;
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            }
            ctx.closePath(); ctx.fill();
        }
        ctx.restore();
    }
    function _drawOcclusionCars(ctx, f, st) {
        if (!st) return;
        for (const a of st.cars) {
            if (!st.occ.occluded.has(a.key)) continue;
            const cx = f.dx + a.cx * f.s, cy = f.dy + a.cy * f.s, hl = a.hl * f.s, hw = a.hw * f.s;
            ctx.save();
            ctx.translate(cx, cy); ctx.rotate(a.heading);
            ctx.beginPath(); ctx.rect(-hl, -hw, hl * 2, hw * 2); ctx.clip();
            ctx.fillStyle = 'rgba(90,90,90,0.6)';
            ctx.fillRect(-hl, -hw, hl * 2, hw * 2);
            ctx.strokeStyle = 'rgba(235,235,235,0.95)';
            ctx.lineWidth = Math.max(1, f.s * 0.07);
            const step = Math.max(4, f.s * 0.5);
            ctx.beginPath();
            for (let d = -(hl + 2 * hw); d <= hl; d += step) { ctx.moveTo(d, -hw); ctx.lineTo(d + 2 * hw, hw); }
            ctx.stroke();
            ctx.restore();
            ctx.save();
            ctx.translate(cx, cy); ctx.rotate(a.heading);
            ctx.strokeStyle = 'rgba(235,235,235,0.95)';
            ctx.lineWidth = Math.max(1, f.s * 0.12);
            ctx.beginPath(); ctx.rect(-hl, -hw, hl * 2, hw * 2); ctx.stroke();
            ctx.restore();
        }
        const ego = st.cars.find(c => c.key === st.egoKey);
        if (ego) {
            const cx = f.dx + ego.cx * f.s, cy = f.dy + ego.cy * f.s, hl = ego.hl * f.s, hw = ego.hw * f.s;
            ctx.save();
            ctx.translate(cx, cy); ctx.rotate(ego.heading);
            ctx.strokeStyle = '#facc15';
            ctx.lineWidth = Math.max(2, f.s * 0.18);
            ctx.beginPath(); ctx.rect(-hl - 2, -hw - 2, (hl + 2) * 2, (hw + 2) * 2); ctx.stroke();
            ctx.restore();
        }
    }

    // Move tool: hit-test the current frame's cars (agents+static+expert) in canvas space.
    // Returns the grabbed car with its kind ('a'/'s'/'e'); experts also carry their
    // goal point (final recorded position) for the drag preview.
    function _pdHitCar(mcx, mcy, f) {
        const fr = _currentFrame();
        const groups = [
            ['a', (window._pdAllAgentFrames || [])[fr] || []],
            ['s', (window._pdAgentRenderer ? window._pdAgentRenderer.staticAgents : []) || []],
            ['e', (window._pdExpertFrames || [])[fr] || []],
        ];
        for (const grp of groups) {
            const kind = grp[0], list = grp[1];
            for (let i = 0; i < list.length; i++) {
                const a = list[i];
                const ccx = f.dx + a.cx * f.s, ccy = f.dy + a.cy * f.s;
                const dx = mcx - ccx, dy = mcy - ccy;
                const ca = Math.cos(-a.heading), sa = Math.sin(-a.heading);
                const lx = dx * ca - dy * sa, ly = dx * sa + dy * ca;
                if (Math.abs(lx) <= a.hl * f.s + 4 && Math.abs(ly) <= a.hw * f.s + 4) {
                    const car = { cx: a.cx, cy: a.cy, hl: a.hl, hw: a.hw, heading: a.heading, kind: kind };
                    if (kind === 'e') {
                        const ef = window._pdExpertFrames || [];
                        for (let fi = ef.length - 1; fi >= 0; fi--) {
                            if (ef[fi] && ef[fi][i]) { car.goalCx = ef[fi][i].cx; car.goalCy = ef[fi][i].cy; break; }
                        }
                    }
                    return car;
                }
            }
        }
        return null;
    }

    function _pdHitGhostCar(mcx, mcy, f) {
        const fr = _currentFrame();
        const groups = [
            ['a', (window._pdGhostAllAgentFrames || [])[fr] || []],
            ['s', (window._pdGhostRenderer ? window._pdGhostRenderer.staticAgents : []) || []],
            ['e', (window._pdGhostExpertFrames || [])[fr] || []],
        ];
        for (const grp of groups) {
            const kind = grp[0], list = grp[1];
            for (let i = 0; i < list.length; i++) {
                const a = list[i];
                const ccx = f.dx + a.cx * f.s, ccy = f.dy + a.cy * f.s;
                const dx = mcx - ccx, dy = mcy - ccy;
                const ca = Math.cos(-a.heading), sa = Math.sin(-a.heading);
                const lx = dx * ca - dy * sa, ly = dx * sa + dy * ca;
                if (Math.abs(lx) <= a.hl * f.s + 4 && Math.abs(ly) <= a.hw * f.s + 4) {
                    const car = { cx: a.cx, cy: a.cy, hl: a.hl, hw: a.hw, heading: a.heading, kind: kind };
                    if (kind === 'e') {
                        const ef = window._pdGhostExpertFrames || [];
                        for (let fi = ef.length - 1; fi >= 0; fi--) {
                            if (ef[fi] && ef[fi][i]) { car.goalCx = ef[fi][i].cx; car.goalCy = ef[fi][i].cy; break; }
                        }
                    }
                    return car;
                }
            }
        }
        return null;
    }

    function _draw(overrideSlot, cx, cy) {
        const canvas = document.getElementById('pd-canvas');
        if (!canvas) return;
        const img = document.getElementById('pd-frame-img');
        const f = _fit(canvas, img);
        if (!f) return;
        const ctx = canvas.getContext('2d');
        const vs = window._pdViewState || { z: 1, tx: 0, ty: 0 };
        const z  = vs.z, tx = vs.tx, ty = vs.ty;
        const ox = canvas.width  / 2 + tx - z * canvas.width  / 2;
        const oy = canvas.height / 2 + ty - z * canvas.height / 2;
        const md = window._pdMapData;
        ctx.fillStyle = (md && md.bg) || '#0f172a';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.setTransform(z, 0, 0, z, ox, oy);
        _drawMapBase(ctx, f, img);
        // Focused env = 1.0; unfocused env = window._pdGhostOpacity (configurable via default.ini).
        // In side-by-side mode the ghost env is drawn on its own pane instead of overlaid here.
        const ghostActive = window._pdGhostAllAgentFrames && window._pdGhostAllAgentFrames.length > 0;
        const sideBySide = ghostActive && !!document.getElementById('pd-ghost-canvas');
        const _mirrorActive = (function() { const b = document.getElementById('pd-tool-mirror'); return !!(b && b.classList.contains('pd-tool-active')); })();
        // Suppress primary-canvas placement preview only when ghost is the exclusive focus
        // (mirror off) OR the cursor is physically on the ghost canvas right now.
        // With mirror ON both envs are live, so a cursor-on-ghost preview must ALSO mirror
        // back onto the focus (primary) canvas — never suppress it here in that case.
        const ghostFocusedSplit = sideBySide && !_mirrorActive && (
            (window._pdEnvFocus === 'ghost') || window._pdCursorOnGhost
        );
        const isFocusPrimary = sideBySide || (window._pdEnvFocus !== 'ghost');
        const _ghostDim = (window._pdGhostOpacity !== undefined) ? window._pdGhostOpacity : 0.55;
        const primaryAlpha = (!ghostActive || isFocusPrimary) ? 1.0 : _ghostDim;
        const ghostAlpha   = !ghostActive ? 0.85 : (isFocusPrimary ? _ghostDim : 1.0);

        // Draw unfocused env first (behind), focused env last (on top).
        if (ghostActive && !sideBySide && isFocusPrimary) {
            // Primary focused: ghost behind, primary on top.
            ctx.globalAlpha = ghostAlpha;
            window._pdGhostRenderer.drawStatic(ctx, f);
            window._pdGhostRenderer.draw(ctx, _currentFrame(), f);
            ctx.globalAlpha = 1.0;
        }
        if (window._pdAgentRenderer) {
            ctx.globalAlpha = primaryAlpha;
            window._pdAgentRenderer.drawStatic(ctx, f);
            window._pdAgentRenderer.draw(ctx, _currentFrame(), f);
            ctx.globalAlpha = 1.0;
        }
        if (ghostActive && !sideBySide && !isFocusPrimary) {
            // Ghost focused: primary already drawn behind, ghost on top.
            ctx.globalAlpha = ghostAlpha;
            window._pdGhostRenderer.drawStatic(ctx, f);
            window._pdGhostRenderer.draw(ctx, _currentFrame(), f);
            ctx.globalAlpha = 1.0;
        }
        // Always draw goal markers from JS (not baked into PNG) so drag has no ghost.
        // _pdScale = pixels/meter at render resolution; multiply by f.s to get canvas pixels/meter.
        const pxPerM = (window._pdScale || 1) * f.s;
        const rDot = 3;
        const r2m  = Math.max(5, 2.0 * pxPerM);
        const r5m  = Math.max(9, 5.0 * pxPerM);
        const fontSize = Math.max(10, r2m * 1.1);
        // The cursor-follow override applies to whichever env the drag targets.
        const _primOverride  = _dragGoalIsGhost ? -1 : overrideSlot;
        const _ghostOverride = _dragGoalIsGhost ? overrideSlot : -1;
        // Both/mirror: while a goal is dragged in the GHOST pane, this pane's same-slot goal
        // follows the cursor live too (shared fraction _pdGoalLiveFx). Only when no native
        // primary override is already active.
        const _pGhostMirror = _mirrorActive && window._pdGoalDragIsGhost && _dragSlot >= 0
            && window._pdGoalLiveFx !== undefined && _primOverride < 0;
        const _drawPrimaryGoals = () => {
            if (window._pdShowGoals === false) return;
            // Selected active vehicle's goal is drawn green to match the highlighted box.
            const _selSlot = (window._pdAgentRenderer && window._pdAgentRenderer.selectedSlot >= 0)
                ? window._pdAgentRenderer.selectedSlot : -1;
            ctx.font = `bold ${fontSize}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            for (const g of (window._pdGoalPositions || [])) {
                if (_primOverride >= 0 && g.slot === _primOverride) continue; // drawn at cursor below
                if (_pGhostMirror && g.slot === _dragSlot) continue; // mirrored drag, drawn at cursor below
                const isSel = (_selSlot >= 0 && g.slot === _selSlot);
                const gx = f.dx + g.fx * f.dw;
                const gy = f.dy + g.fy * f.dh;
                ctx.beginPath(); ctx.arc(gx, gy, rDot, 0, Math.PI * 2);
                ctx.fillStyle = isSel ? '#fff' : _agentOutline(); ctx.fill();
                if (window._pdShowGoalRadius !== false) {
                    ctx.beginPath(); ctx.arc(gx, gy, r2m, 0, Math.PI * 2);
                    ctx.strokeStyle = isSel ? '#16a34a' : _agentFill(); ctx.lineWidth = 2; ctx.stroke();
                    ctx.setLineDash([4, 4]);
                    ctx.beginPath(); ctx.arc(gx, gy, r5m, 0, Math.PI * 2);
                    ctx.strokeStyle = isSel ? '#22c55e' : _agentOutline(); ctx.lineWidth = 1.5; ctx.stroke();
                    ctx.setLineDash([]);
                }
                if (window._pdShowLabels !== false) {
                    const lblOff = (window._pdShowGoalRadius !== false) ? r5m : rDot;
                    const lbl = g.label != null ? String(g.label) : String(g.slot);
                    ctx.fillStyle = isSel ? '#22c55e' : _agentOutline(); ctx.fillText(lbl, gx, gy - lblOff - fontSize * 0.6);
                }
            }
            if (_primOverride >= 0) {
                const dragged = (window._pdGoalPositions || []).find(g => g.slot === _primOverride);
                const dlbl = dragged && dragged.label != null ? String(dragged.label) : String(_primOverride);
                ctx.beginPath(); ctx.arc(cx, cy, rDot, 0, Math.PI * 2);
                ctx.fillStyle = _agentOutline(); ctx.fill();
                if (window._pdShowGoalRadius !== false) {
                    ctx.beginPath(); ctx.arc(cx, cy, r2m, 0, Math.PI * 2);
                    ctx.strokeStyle = '#eab308'; ctx.lineWidth = 2.5; ctx.stroke();
                    ctx.setLineDash([4, 4]);
                    ctx.beginPath(); ctx.arc(cx, cy, r5m, 0, Math.PI * 2);
                    ctx.strokeStyle = '#fde047'; ctx.lineWidth = 1.5; ctx.stroke();
                    ctx.setLineDash([]);
                }
                if (window._pdShowLabels !== false) {
                    const dlblOff = (window._pdShowGoalRadius !== false) ? r5m : rDot;
                    ctx.fillStyle = '#fde047'; ctx.fillText(dlbl, cx, cy - dlblOff - fontSize * 0.6);
                }
            }
            // Both/mirror: draw this pane's dragged-slot goal at the live cursor fraction
            // mirrored from the ghost pane's drag.
            if (_pGhostMirror) {
                const _mcx = f.dx + window._pdGoalLiveFx * f.dw;
                const _mcy = f.dy + window._pdGoalLiveFy * f.dh;
                const dragged = (window._pdGoalPositions || []).find(g => g.slot === _dragSlot);
                const dlbl = dragged && dragged.label != null ? String(dragged.label) : String(_dragSlot);
                ctx.beginPath(); ctx.arc(_mcx, _mcy, rDot, 0, Math.PI * 2);
                ctx.fillStyle = _agentOutline(); ctx.fill();
                if (window._pdShowGoalRadius !== false) {
                    ctx.beginPath(); ctx.arc(_mcx, _mcy, r2m, 0, Math.PI * 2);
                    ctx.strokeStyle = '#eab308'; ctx.lineWidth = 2.5; ctx.stroke();
                    ctx.setLineDash([4, 4]);
                    ctx.beginPath(); ctx.arc(_mcx, _mcy, r5m, 0, Math.PI * 2);
                    ctx.strokeStyle = '#fde047'; ctx.lineWidth = 1.5; ctx.stroke();
                    ctx.setLineDash([]);
                }
                if (window._pdShowLabels !== false) {
                    const dlblOff = (window._pdShowGoalRadius !== false) ? r5m : rDot;
                    ctx.fillStyle = '#fde047'; ctx.fillText(dlbl, _mcx, _mcy - dlblOff - fontSize * 0.6);
                }
            }
        };
        // Mirror the agent depth/opacity logic: unfocused env goals behind, focused env goals on top.
        if (ghostActive && !sideBySide && isFocusPrimary) {
            ctx.globalAlpha = ghostAlpha;
            _drawGhostGoalsOn(ctx, f);
            ctx.globalAlpha = 1.0;
        }
        ctx.globalAlpha = primaryAlpha;
        _drawPrimaryGoals();
        ctx.globalAlpha = 1.0;
        if (ghostActive && !sideBySide && !isFocusPrimary) {
            ctx.globalAlpha = ghostAlpha;
            _drawGhostGoalsOn(ctx, f, _ghostOverride, cx, cy);
            ctx.globalAlpha = 1.0;
        }

        // Placement previews: suppress on primary canvas when ghost is focused in split mode
        // (they are drawn on the ghost canvas instead, via _drawGhostPane).
        if (!ghostFocusedSplit) {
        // Move tool preview: grabbed car follows the cursor (drag), then aims its heading.
        const mvp = window._pdMovePlacement;
        if (mvp && mvp.car && window._pdTool === 'move') {
            const mhl = Math.max(6, mvp.car.hl * f.s), mhw = Math.max(3, mvp.car.hw * f.s);
            const mHasCur = mvp.curFx !== undefined;
            const mcx = mHasCur ? f.dx + mvp.curFx * f.dw : null;
            const mcy = mHasCur ? f.dy + mvp.curFy * f.dh : null;
            if (mvp.step === 1 && mvp.car.kind === 'e' && mHasCur) {
                // Expert: live lane-graph trajectory from the dragged start to the expert's
                // goal, with intermediate timestep dots — same preview as inserting an expert.
                const graph = _ensureLaneGraph();
                let trajPts = null, snapStart = null, startHeading = mvp.car.heading || 0;
                if (graph && mvp.car.goalCx !== undefined) {
                    snapStart = _snapToLaneJS(graph, mvp.curFx * f.iw, mvp.curFy * f.ih);
                    const snapGoal = _snapToLaneJS(graph, mvp.car.goalCx, mvp.car.goalCy);
                    if (snapStart.lane >= 0 && snapGoal.lane >= 0) {
                        const ld = graph.lanes[snapStart.lane], sd = snapStart.seg;
                        startHeading = Math.atan2(ld[sd + 1][1] - ld[sd][1], ld[sd + 1][0] - ld[sd][0]);
                        const path = _lanePathJS(graph, snapStart.lane, snapStart.seg, snapGoal.lane, snapGoal.seg);
                        if (path) {
                            const res = _trajPointsJS(graph,
                                snapStart.lane, snapStart.seg, snapStart.px, snapStart.py,
                                snapGoal.lane, snapGoal.seg, snapGoal.px, snapGoal.py, path, 91);
                            trajPts = res.pts;
                        }
                    }
                }
                const scx = (snapStart && snapStart.lane >= 0) ? f.dx + snapStart.px * f.s : mcx;
                const scy = (snapStart && snapStart.lane >= 0) ? f.dy + snapStart.py * f.s : mcy;
                ctx.globalAlpha = 0.6;
                _drawAgentShape(ctx, scx, scy, startHeading, mhl, mhw, '#f59e0b', '#fde68a');
                ctx.globalAlpha = 1.0;
                ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                if (trajPts) {
                    ctx.beginPath();
                    ctx.moveTo(f.dx + trajPts[0][0] * f.s, f.dy + trajPts[0][1] * f.s);
                    for (let ti = 1; ti < trajPts.length; ti++)
                        ctx.lineTo(f.dx + trajPts[ti][0] * f.s, f.dy + trajPts[ti][1] * f.s);
                    ctx.strokeStyle = 'rgba(245,158,11,0.8)'; ctx.lineWidth = 2;
                    ctx.setLineDash([5, 4]); ctx.stroke(); ctx.setLineDash([]);
                    const dotR = Math.max(1.5, pxPerM * 0.18);
                    ctx.fillStyle = '#fde68a';
                    for (let ti = 0; ti < trajPts.length; ti++) {
                        ctx.beginPath();
                        ctx.arc(f.dx + trajPts[ti][0] * f.s, f.dy + trajPts[ti][1] * f.s, dotR, 0, Math.PI * 2);
                        ctx.fill();
                    }
                    ctx.fillStyle = '#fde68a'; ctx.fillText('› release to drop', scx + mhl + 4, scy - mhw - 4);
                } else {
                    ctx.fillStyle = '#f87171'; ctx.fillText('✕ no road-lane path here', mcx + mhl + 4, mcy - mhw - 4);
                }
            } else if (mvp.step === 1 && mHasCur) {
                ctx.globalAlpha = 0.6;
                _drawAgentShape(ctx, mcx, mcy, mvp.car.heading || 0, mhl, mhw, '#f59e0b', '#fde68a');
                ctx.globalAlpha = 1.0;
                ctx.fillStyle = '#fde68a'; ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                ctx.fillText('› release to drop', mcx + mhl + 4, mcy - mhw - 4);
            } else if (mvp.step === 2) {
                const pcx = f.dx + mvp.dfx * f.dw, pcy = f.dy + mvp.dfy * f.dh;
                const ang = (mHasCur && (mcx !== pcx || mcy !== pcy))
                    ? Math.atan2(mcy - pcy, mcx - pcx) : (mvp.car.heading || 0);
                _drawAgentShape(ctx, pcx, pcy, ang, mhl, mhw, '#f59e0b', '#fde68a');
                if (mHasCur) {
                    ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(mcx, mcy);
                    ctx.strokeStyle = '#fde68a'; ctx.lineWidth = 1.5;
                    ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
                }
                ctx.fillStyle = '#fde68a'; ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                ctx.fillText('› click to aim heading', pcx + mhl + 4, pcy - mhw - 4);
            }
        }
        // Draw in-progress agent placement preview.
        const ap = window._pdAgentPlacement;
        if (ap && window._pdTool === 'add_agent') {
            const _asz = (window._pdVehicleSizes && window._pdVehicleSizes.add_agent) || {hl: 2.25, hw: 1.0};
            const halfL = pxPerM * _asz.hl;
            const halfW = pxPerM * _asz.hw;
            const hasCur = ap.curFx !== undefined;
            const curCx = hasCur ? f.dx + ap.curFx * f.dw : null;
            const curCy = hasCur ? f.dy + ap.curFy * f.dh : null;
            const apFill = '#065f46', apLine = '#34d399';

            if (ap.step === 0) {
                // Phantom car follows cursor before first click.
                if (hasCur) {
                    ctx.globalAlpha = 0.55;
                    _drawAgentShape(ctx, curCx, curCy, 0, halfL, halfW, apFill, apLine);
                    ctx.globalAlpha = 1.0;
                    ctx.fillStyle = apLine;
                    ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    ctx.fillText('› click to place', curCx + halfL + 4, curCy - halfW - 4);
                }
            } else if (ap.step === 1) {
                // Car placed; it rotates to point toward cursor so user picks heading.
                const pcx = f.dx + ap.fx * f.dw;
                const pcy = f.dy + ap.fy * f.dh;
                const ang = (hasCur && (curCx !== pcx || curCy !== pcy))
                    ? Math.atan2(curCy - pcy, curCx - pcx) : 0;
                _drawAgentShape(ctx, pcx, pcy, ang, halfL, halfW, apFill, apLine);
                if (hasCur) {
                    ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(curCx, curCy);
                    ctx.strokeStyle = apLine; ctx.lineWidth = 1.5;
                    ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
                }
                ctx.fillStyle = apLine;
                ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                ctx.fillText('› click heading', pcx + halfL + 4, pcy - halfW - 4);
            } else if (ap.step === 2) {
                // Car with fixed heading; goal circle follows cursor.
                const pcx = f.dx + ap.fx * f.dw;
                const pcy = f.dy + ap.fy * f.dh;
                const hcx = f.dx + ap.hfx * f.dw;
                const hcy = f.dy + ap.hfy * f.dh;
                const ang = Math.atan2(hcy - pcy, hcx - pcx);
                _drawAgentShape(ctx, pcx, pcy, ang, halfL, halfW, apFill, apLine);
                if (hasCur) {
                    ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(curCx, curCy);
                    ctx.strokeStyle = apLine; ctx.lineWidth = 1.5;
                    ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]);
                    ctx.beginPath(); ctx.arc(curCx, curCy, rDot, 0, Math.PI * 2);
                    ctx.fillStyle = apLine; ctx.fill();
                    ctx.beginPath(); ctx.arc(curCx, curCy, r2m, 0, Math.PI * 2);
                    ctx.strokeStyle = apLine; ctx.lineWidth = 1.5; ctx.stroke();
                }
                ctx.fillStyle = apLine;
                ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                ctx.fillText('› click goal', pcx + halfL + 4, pcy - halfW - 4);
            }
        }

        // Draw in-progress static agent placement preview (2-click: position + heading).
        const sp = window._pdStaticPlacement;

        if (sp && window._pdTool === 'add_static') {
            const _ssz = (window._pdVehicleSizes && window._pdVehicleSizes.add_static) || {hl: 2.25, hw: 1.0};
            const halfL = pxPerM * _ssz.hl;
            const halfW = pxPerM * _ssz.hw;
            const hasCur = sp.curFx !== undefined;
            const curCx = hasCur ? f.dx + sp.curFx * f.dw : null;
            const curCy = hasCur ? f.dy + sp.curFy * f.dh : null;

            const spFill = '#065f46', spLine = '#34d399';
            if (sp.step === 0) {
                if (hasCur) {
                    ctx.globalAlpha = 0.55;
                    _drawAgentShape(ctx, curCx, curCy, 0, halfL, halfW, spFill, spLine);
                    ctx.globalAlpha = 1.0;
                    ctx.fillStyle = spLine;
                    ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    ctx.fillText('› click to place', curCx + halfL + 4, curCy - halfW - 4);
                }
            } else if (sp.step === 1) {
                const pcx = f.dx + sp.fx * f.dw;
                const pcy = f.dy + sp.fy * f.dh;
                const ang = (hasCur && (curCx !== pcx || curCy !== pcy))
                    ? Math.atan2(curCy - pcy, curCx - pcx) : 0;
                _drawAgentShape(ctx, pcx, pcy, ang, halfL, halfW, spFill, spLine);
                if (hasCur) {
                    ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(curCx, curCy);
                    ctx.strokeStyle = spLine; ctx.lineWidth = 1.5;
                    ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
                }
                ctx.fillStyle = spLine;
                ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                ctx.fillText('› click heading', pcx + halfL + 4, pcy - halfW - 4);
            }
        }

        // Draw in-progress expert trajectory placement preview (2-click: start + end).
        const ep = window._pdExpertPlacement;
        if (ep && window._pdTool === 'add_expert') {
            const _esz = (window._pdVehicleSizes && window._pdVehicleSizes.add_expert) || {hl: 2.25, hw: 1.0};
            const halfL = pxPerM * _esz.hl;
            const halfW = pxPerM * _esz.hw;
            const hasCur = ep.curFx !== undefined;
            const curCx = hasCur ? f.dx + ep.curFx * f.dw : null;
            const curCy = hasCur ? f.dy + ep.curFy * f.dh : null;
            if (ep.step === 0) {
                if (hasCur) {
                    ctx.globalAlpha = 0.55;
                    _drawAgentShape(ctx, curCx, curCy, 0, halfL, halfW, '#065f46', '#34d399');
                    ctx.globalAlpha = 1.0;
                    ctx.fillStyle = '#34d399';
                    ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                    ctx.fillText('› click start (follows road lane)', curCx + halfL + 4, curCy - halfW - 4);
                }
            } else if (ep.step === 1) {
                // Live BFS preview: snap both endpoints, run lane-graph BFS.
                const graph = _ensureLaneGraph();
                let startHeading = 0, trajPts = null, noPath = false;
                let snapStart = null, snapGoal = null;
                if (graph && hasCur) {
                    const six = ep.sfx * f.iw, siy = ep.sfy * f.ih;
                    const gix = ep.curFx * f.iw, giy = ep.curFy * f.ih;
                    snapStart = _snapToLaneJS(graph, six, siy);
                    snapGoal  = _snapToLaneJS(graph, gix, giy);
                    if (snapStart.lane >= 0 && snapGoal.lane >= 0) {
                        const ld = graph.lanes[snapStart.lane];
                        const sd = snapStart.seg;
                        startHeading = Math.atan2(ld[sd+1][1]-ld[sd][1], ld[sd+1][0]-ld[sd][0]);
                        const path = _lanePathJS(graph, snapStart.lane, snapStart.seg,
                                                  snapGoal.lane, snapGoal.seg);
                        if (path) {
                            const res = _trajPointsJS(graph,
                                snapStart.lane, snapStart.seg, snapStart.px, snapStart.py,
                                snapGoal.lane, snapGoal.seg, snapGoal.px, snapGoal.py,
                                path, 91);
                            trajPts = res.pts;
                            ep._avgSpeedMs = (res.totalPx / (window._pdScale || 1)) / 9.0;
                        } else { noPath = true; }
                    }
                }
                const scx = snapStart ? f.dx + snapStart.px * f.s : f.dx + ep.sfx * f.dw;
                const scy = snapStart ? f.dy + snapStart.py * f.s : f.dy + ep.sfy * f.dh;
                _drawAgentShape(ctx, scx, scy, startHeading, halfL, halfW, '#065f46', '#34d399');
                ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'left';
                if (trajPts) {
                    // Dashed lane-following trajectory.
                    ctx.beginPath();
                    ctx.moveTo(f.dx + trajPts[0][0] * f.s, f.dy + trajPts[0][1] * f.s);
                    for (let ti = 1; ti < trajPts.length; ti++)
                        ctx.lineTo(f.dx + trajPts[ti][0] * f.s, f.dy + trajPts[ti][1] * f.s);
                    ctx.strokeStyle = 'rgba(52,211,153,0.7)'; ctx.lineWidth = 2;
                    ctx.setLineDash([5, 4]); ctx.stroke(); ctx.setLineDash([]);
                    // Timestep dots.
                    const dotR = Math.max(1.5, pxPerM * 0.18);
                    ctx.fillStyle = '#34d399';
                    for (let ti = 0; ti < trajPts.length; ti++) {
                        ctx.beginPath();
                        ctx.arc(f.dx + trajPts[ti][0] * f.s, f.dy + trajPts[ti][1] * f.s,
                                dotR, 0, Math.PI * 2);
                        ctx.fill();
                    }
                    // Snapped goal marker.
                    const gcx = f.dx + snapGoal.px * f.s, gcy = f.dy + snapGoal.py * f.s;
                    ctx.beginPath(); ctx.arc(gcx, gcy, rDot, 0, Math.PI * 2);
                    ctx.fillStyle = '#fff'; ctx.fill();
                    ctx.beginPath(); ctx.arc(gcx, gcy, r2m, 0, Math.PI * 2);
                    ctx.strokeStyle = '#34d399'; ctx.lineWidth = 2; ctx.stroke();
                    ctx.setLineDash([4, 4]);
                    ctx.beginPath(); ctx.arc(gcx, gcy, r5m, 0, Math.PI * 2);
                    ctx.strokeStyle = '#6ee7b7'; ctx.lineWidth = 1.5; ctx.stroke();
                    ctx.setLineDash([]);
                    // Speed label.
                    const avgMs = ep._avgSpeedMs || 0;
                    const lbl = avgMs.toFixed(1) + ' m/s (' + (avgMs * 3.6).toFixed(1) + ' km/h)';
                    ctx.strokeStyle = '#000'; ctx.lineWidth = 3;
                    ctx.strokeText(lbl, gcx + r5m + 4, gcy);
                    ctx.fillStyle = '#34d399'; ctx.fillText(lbl, gcx + r5m + 4, gcy);
                    ctx.fillText('› click goal', scx + halfL + 4, scy - halfW - 4);
                } else if (noPath && hasCur) {
                    // No path: red goal ring + hint.
                    ctx.beginPath(); ctx.arc(curCx, curCy, r2m, 0, Math.PI * 2);
                    ctx.fillStyle = 'rgba(220,38,38,0.25)'; ctx.fill();
                    ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 2; ctx.stroke();
                    ctx.fillStyle = '#ef4444';
                    ctx.fillText('no path — pick another goal', curCx + r2m + 4, curCy - 4);
                    ctx.fillStyle = '#34d399';
                    ctx.fillText('› click goal', scx + halfL + 4, scy - halfW - 4);
                } else if (hasCur) {
                    // No lane data yet: simple dashed line + goal ring.
                    ctx.beginPath(); ctx.moveTo(scx, scy); ctx.lineTo(curCx, curCy);
                    ctx.strokeStyle = '#34d399'; ctx.lineWidth = 1.5;
                    ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
                    ctx.beginPath(); ctx.arc(curCx, curCy, rDot, 0, Math.PI * 2);
                    ctx.fillStyle = '#fff'; ctx.fill();
                    ctx.beginPath(); ctx.arc(curCx, curCy, r2m, 0, Math.PI * 2);
                    ctx.strokeStyle = '#34d399'; ctx.lineWidth = 2; ctx.stroke();
                    ctx.fillStyle = '#34d399';
                    ctx.fillText('› click goal', scx + halfL + 4, scy - halfW - 4);
                }
            }
        }
        } // end if (!ghostFocusedSplit) — placement previews

        // Draw trajectory dots and goal for the selected (primary) expert agent (green).
        const _selExpert = (window._pdSelectedExpertIdx !== undefined) ? window._pdSelectedExpertIdx : -1;
        if (_selExpert >= 0 && window._pdExpertWaypoints && window._pdExpertWaypoints.length > 0) {
            const agent = window._pdExpertWaypoints.find(a => a.agent_idx === _selExpert);
            if (agent) {
                // Live spline preview while dragging a timestep dot.
                const liveTpts = _splineFitTrajLive(agent.traj_pts || [], agent.agent_idx, false, 2.0);
                // Green trajectory line.
                if (liveTpts.length >= 2) {
                    ctx.beginPath();
                    ctx.moveTo(f.dx + liveTpts[0].fx * f.dw, f.dy + liveTpts[0].fy * f.dh);
                    for (let i = 1; i < liveTpts.length; i++)
                        ctx.lineTo(f.dx + liveTpts[i].fx * f.dw, f.dy + liveTpts[i].fy * f.dh);
                    ctx.strokeStyle = '#22c55e'; ctx.lineWidth = Math.max(1.5, f.s * 0.4);
                    ctx.setLineDash([]); ctx.stroke();
                }
                // Timestep dots — solid green, no outline, same size as placement preview.
                ctx.fillStyle = '#22c55e';
                for (const tp of liveTpts) {
                    const px = f.dx + tp.fx * f.dw, py = f.dy + tp.fy * f.dh;
                    ctx.beginPath(); ctx.arc(px, py, Math.max(1.5, pxPerM * 0.18), 0, Math.PI * 2);
                    ctx.fill();
                }
                // Goal marker — same style as regular goals but in green.
                if (agent.points && agent.points.length > 0) {
                    const gp = agent.points[agent.points.length - 1];
                    const gx = f.dx + gp.fx * f.dw, gy = f.dy + gp.fy * f.dh;
                    ctx.beginPath(); ctx.arc(gx, gy, rDot, 0, Math.PI * 2);
                    ctx.fillStyle = '#fff'; ctx.fill();
                    ctx.beginPath(); ctx.arc(gx, gy, r2m, 0, Math.PI * 2);
                    ctx.strokeStyle = '#16a34a'; ctx.lineWidth = 2; ctx.stroke();
                    ctx.setLineDash([4, 4]);
                    ctx.beginPath(); ctx.arc(gx, gy, r5m, 0, Math.PI * 2);
                    ctx.strokeStyle = '#22c55e'; ctx.lineWidth = 1.5; ctx.stroke();
                    ctx.setLineDash([]);
                }
            }
        }

        // Draw trajectory for selected ghost user expert (on the ghost pane in side-by-side mode).
        if (!sideBySide) _drawGhostSelExpertOn(ctx, f);
        ctx.restore();
    }

    function _redraw() {
        const canvas = document.getElementById('pd-canvas');
        if (!canvas) return;
        // Set canvas buffer to its own laid-out size so the image stays crisp
        // (the canvas is half-width when the side-by-side ghost pane is open).
        const r = canvas.getBoundingClientRect();
        const w = Math.round(r.width), h = Math.round(r.height);
        if (w && h && (canvas.width !== w || canvas.height !== h)) { canvas.width = w; canvas.height = h; }
        _draw(_dragSlot >= 0 ? _dragSlot : -1, _dragCx, _dragCy);
        _drawGhostPane();
    }

    function _attach() {
        const cont = document.getElementById('pd-canvas-container');
        if (!cont) { setTimeout(_attach, 200); return; }
        const img    = document.getElementById('pd-frame-img');
        const canvas = document.getElementById('pd-canvas');
        if (!img || !canvas) { setTimeout(_attach, 200); return; }

        // Redraw when the static background image loads.
        const obs = new MutationObserver(() => {
            if (img.complete && img.naturalWidth) _redraw();
            else img.onload = _redraw;
        });
        obs.observe(img, { attributes: true, attributeFilter: ['src'] });
        if (img.complete && img.naturalWidth) _redraw(); else img.onload = _redraw;

        // Redraw when Reflex advances the frame index (updates #pd-current-frame-el).
        // Guard: skip redraw when rAF is active — rAF owns the draw loop then.
        // Without this guard, the sync observer and redraw observer both fire on the
        // same DOM mutation as independent microtasks; if redraw wins the race before
        // _pdRafFracFrame is updated, agents are lerped between the wrong frames (flicker).
        function _attachFrameObs() {
            const el = document.getElementById('pd-current-frame-el');
            if (!el) { setTimeout(_attachFrameObs, 200); return; }
            new MutationObserver(function() {
                if (!window._pdRafActive) _redraw();
            }).observe(el, { childList: true, subtree: true, characterData: true });
        }
        _attachFrameObs();

        new ResizeObserver(_redraw).observe(cont);
        // The pan wrapper shrinks/grows when the side-by-side ghost pane toggles.
        const panWrap = document.getElementById('pd-pan-wrapper');
        if (panWrap) new ResizeObserver(_redraw).observe(panWrap);

        // ── Goal drag-and-drop (mirrors viewer_template.html canvas approach) ──

        canvas.addEventListener('mousedown', function (e) {
            // In split view, when the GHOST is focused and mirror is off, the primary canvas
            // is read-only — edits go only to the focused (ghost) env via the ghost canvas.
            // Pan/select still work for viewing; block the editing tools here.
            {
                const _mb = document.getElementById('pd-tool-mirror');
                const _mirrorOn = !!(_mb && _mb.classList.contains('pd-tool-active'));
                const _primaryReadOnly = !!document.getElementById('pd-ghost-canvas') &&
                    window._pdEnvFocus === 'ghost' && !_mirrorOn;
                const _editTools = ['move', 'goal', 'add_agent', 'add_static', 'add_expert'];
                if (_primaryReadOnly && _editTools.indexOf(window._pdTool) >= 0) return;
            }
            // ── Move tool: grab a car (step 0→1), confirm heading (step 2) ────
            if (window._pdTool === 'move') {
                const { cx: mcx, cy: mcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const f2 = _fit(canvas, document.getElementById('pd-frame-img'));
                if (!f2) return;
                const fx2 = Math.min(1, Math.max(0, (mcx - f2.dx) / f2.dw));
                const fy2 = Math.min(1, Math.max(0, (mcy - f2.dy) / f2.dh));
                window._pdMovePlacement = window._pdMovePlacement || { step: 0 };
                const mp = window._pdMovePlacement;
                // In focus-ghost overlay mode (no split), primary canvas hits ghost cars.
                const _mvGhostOverlay = window._pdEnvFocus === 'ghost' &&
                    !document.getElementById('pd-ghost-canvas');
                if (mp.step === 2 && !mp.isGhost) {
                    window._pdMoveResult = { sfx: mp.sfx, sfy: mp.sfy, dfx: mp.dfx, dfy: mp.dfy, hfx: fx2, hfy: fy2 };
                    window._pdMovePlacement = { step: 0 };
                    window._pdDragJustEnded = true;
                    _redraw();
                    const btn = document.getElementById('pd-agent-move-trigger');
                    if (btn) btn.click();
                } else if (mp.step === 2 && mp.isGhost) {
                    // Ghost grab heading aim via primary canvas (overlay mode).
                    window._pdGhostMoveResult = { sfx: mp.sfx, sfy: mp.sfy, dfx: mp.dfx, dfy: mp.dfy, hfx: fx2, hfy: fy2 };
                    window._pdMovePlacement = { step: 0 };
                    window._pdDragJustEnded = true;
                    _redraw();
                    const btn = document.getElementById('pd-ghost-agent-move-trigger');
                    if (btn) btn.click();
                } else if (mp.step === 0) {
                    const car = _mvGhostOverlay
                        ? _pdHitGhostCar(mcx, mcy, f2) : _pdHitCar(mcx, mcy, f2);
                    if (car) {
                        mp.car = car; mp.sfx = fx2; mp.sfy = fy2;
                        mp.curFx = fx2; mp.curFy = fy2; mp.step = 1;
                        mp.isGhost = _mvGhostOverlay;
                        _redraw();
                    }
                }
                e.preventDefault(); e.stopPropagation();
                return;
            }
            // ── Add-agent 3-click placement ──────────────────────────────────
            if (window._pdTool === 'add_agent') {
                const { cx: mcx, cy: mcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const img2 = document.getElementById('pd-frame-img');
                const f2 = _fit(canvas, img2);
                if (!f2) return;
                const fx2 = Math.min(1, Math.max(0, (mcx - f2.dx) / f2.dw));
                const fy2 = Math.min(1, Math.max(0, (mcy - f2.dy) / f2.dh));
                window._pdAgentPlacement = window._pdAgentPlacement || {step: 0};
                const ap = window._pdAgentPlacement;
                if (ap.step === 0) {
                    ap.fx = fx2; ap.fy = fy2;
                    ap.curFx = fx2; ap.curFy = fy2;
                    ap.step = 1;
                    _redraw();
                } else if (ap.step === 1) {
                    ap.hfx = fx2; ap.hfy = fy2;
                    ap.curFx = fx2; ap.curFy = fy2;
                    ap.step = 2;
                    _redraw();
                } else if (ap.step === 2) {
                    window._pdAgentPlaceResult = {
                        pfx: ap.fx, pfy: ap.fy,
                        hfx: ap.hfx, hfy: ap.hfy,
                        gfx: fx2, gfy: fy2,
                    };
                    ap.step = 0;
                    ap.curFx = undefined; ap.curFy = undefined;
                    _redraw();
                    const btn = document.getElementById('pd-agent-place-trigger');
                    if (btn) btn.click();
                }
                e.preventDefault(); e.stopPropagation();
                return;
            }
            // ── Add-static 2-click placement ─────────────────────────────────
            if (window._pdTool === 'add_static') {
                const { cx: mcx, cy: mcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const img2 = document.getElementById('pd-frame-img');
                const f2 = _fit(canvas, img2);
                if (!f2) return;
                const fx2 = Math.min(1, Math.max(0, (mcx - f2.dx) / f2.dw));
                const fy2 = Math.min(1, Math.max(0, (mcy - f2.dy) / f2.dh));
                window._pdStaticPlacement = window._pdStaticPlacement || {step: 0};
                const sp = window._pdStaticPlacement;
                if (sp.step === 0) {
                    sp.fx = fx2; sp.fy = fy2;
                    sp.curFx = fx2; sp.curFy = fy2;
                    sp.step = 1;
                    _redraw();
                } else if (sp.step === 1) {
                    window._pdStaticPlaceResult = {
                        pfx: sp.fx, pfy: sp.fy,
                        hfx: fx2, hfy: fy2,
                    };
                    sp.step = 0;
                    sp.curFx = undefined; sp.curFy = undefined;
                    _redraw();
                    const btn = document.getElementById('pd-static-place-trigger');
                    if (btn) btn.click();
                }
                e.preventDefault(); e.stopPropagation();
                return;
            }
            if (window._pdTool === 'add_expert') {
                const { cx: mcx, cy: mcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const img2 = document.getElementById('pd-frame-img');
                const f2 = _fit(canvas, img2);
                if (!f2) return;
                const fx2 = Math.min(1, Math.max(0, (mcx - f2.dx) / f2.dw));
                const fy2 = Math.min(1, Math.max(0, (mcy - f2.dy) / f2.dh));
                window._pdExpertPlacement = window._pdExpertPlacement || {step: 0};
                const ep = window._pdExpertPlacement;
                if (ep.step === 0) {
                    ep.sfx = fx2; ep.sfy = fy2;
                    ep.curFx = fx2; ep.curFy = fy2;
                    ep.step = 1;
                    _redraw();
                } else if (ep.step === 1) {
                    window._pdExpertPlaceResult = {
                        pfx: ep.sfx, pfy: ep.sfy,
                        hfx: ep.sfx, hfy: ep.sfy,
                        efx: fx2, efy: fy2,
                    };
                    ep.step = 0;
                    ep.curFx = undefined; ep.curFy = undefined;
                    _redraw();
                    const btn = document.getElementById('pd-expert-place-trigger');
                    if (btn) btn.click();
                }
                e.preventDefault(); e.stopPropagation();
                return;
            }
            // Trajectory edits target whichever expert is selected. Ghost and primary
            // selections are mutually exclusive in JS, so a selected ghost expert (overlay
            // mode, no side-by-side pane) means the edit drives the ghost env.
            const _sideBySide  = !!document.getElementById('pd-ghost-canvas');
            const _ghostSel    = (window._pdGhostSelectedExpertIdx !== undefined) ? window._pdGhostSelectedExpertIdx : -1;
            const _primSel     = (window._pdSelectedExpertIdx !== undefined) ? window._pdSelectedExpertIdx : -1;
            const _focusGhost  = !_sideBySide && _ghostSel >= 0;
            const _wps = _focusGhost ? window._pdGhostExpertWaypoints : window._pdExpertWaypoints;
            const _selExpertDrag = _focusGhost ? _ghostSel : _primSel;
            if (window._pdTool !== 'goal' && _selExpertDrag < 0) return;
            // ── Trajectory timestep drag (only for selected expert) ────────────
            if (_selExpertDrag >= 0) {
                const { cx: tpcx, cy: tpcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const fw2 = _fit(canvas, document.getElementById('pd-frame-img'));
                if (fw2 && _wps) {
                    const hitR = Math.max(4, fw2.s * 1.0);
                    const selAgent = _wps.find(a => a.agent_idx === _selExpertDrag);
                    if (selAgent) {
                        for (const tp of (selAgent.traj_pts || [])) {
                            const px = fw2.dx + tp.fx * fw2.dw, py = fw2.dy + tp.fy * fw2.dh;
                            if (Math.hypot(tpcx - px, tpcy - py) < hitR) {
                                _trajDragAgentIdx = selAgent.agent_idx;
                                _trajDragTrajStep = tp.t;
                                _trajDragLiveFx   = tp.fx; _trajDragLiveFy = tp.fy;
                                _trajDragStartX   = e.clientX; _trajDragStartY = e.clientY;
                                _dragIsGhost      = _focusGhost;
                                canvas.style.cursor = 'grabbing';
                                e.preventDefault(); e.stopPropagation();
                                return;
                            }
                        }
                    }
                }
            }
            if (window._pdTool !== 'goal') return;
            // ── Expert waypoint drag hit-test (takes priority over goal drag) ──
            {
                const { cx: wpcx, cy: wpcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const fw = _fit(canvas, document.getElementById('pd-frame-img'));
                if (fw && _wps && _wps.length > 0) {
                    const hitR = Math.max(6, fw.s * 1.5);
                    for (const agent of _wps) {
                        for (const pt of agent.points) {
                            const px = fw.dx + pt.fx * fw.dw, py = fw.dy + pt.fy * fw.dh;
                            if (Math.hypot(wpcx - px, wpcy - py) < hitR) {
                                _wpDragAgentIdx = agent.agent_idx;
                                _wpDragWpIdx    = pt.wp_idx;
                                _wpDragLiveFx   = pt.fx; _wpDragLiveFy = pt.fy;
                                _wpDragStartX   = e.clientX; _wpDragStartY = e.clientY;
                                _dragIsGhost    = _focusGhost;
                                canvas.style.cursor = 'grabbing';
                                e.preventDefault(); e.stopPropagation();
                                return;
                            }
                        }
                    }
                }
            }
            const { cx, cy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
            const img2 = document.getElementById('pd-frame-img');
            const f    = _fit(canvas, img2);
            if (!f) return;
            const fx   = Math.min(1, Math.max(0, (cx - f.dx) / f.dw));
            const fy   = Math.min(1, Math.max(0, (cy - f.dy) / f.dh));
            const hitX = 15 / f.iw, hitY = 15 / f.ih;
            _dragSlot = -1;
            // Split-mode: use ghost goals only when ghost has exclusive focus (mirror off).
            const _gdMirrorBtn = document.getElementById('pd-tool-mirror');
            const _gdMirrorOn = !!(_gdMirrorBtn && _gdMirrorBtn.classList.contains('pd-tool-active'));
            const _gFocSplit = window._pdEnvFocus === 'ghost' && !_gdMirrorOn && !!document.getElementById('pd-ghost-canvas');
            window._pdGoalDragIsGhost = false;
            const _goalHitList = _gFocSplit ? (window._pdGhostGoalPositions || []) : (window._pdGoalPositions || []);
            // Overlay-mode: track whether drag targets ghost env (used in hit-test body below).
            const _ghostActiveG = window._pdGhostAllAgentFrames && window._pdGhostAllAgentFrames.length > 0;
            const _goalFocusGhost = _ghostActiveG && !_sideBySide && window._pdEnvFocus === 'ghost';
            for (const g of _goalHitList) {
                if (Math.abs(fx - g.fx) < hitX && Math.abs(fy - g.fy) < hitY) {
                    _dragSlot = g.slot;
                    _dragGoalIsGhost = _goalFocusGhost;
                    _startX   = e.clientX;
                    _startY   = e.clientY;
                    window._pdGoalDragIsGhost = _gFocSplit;
                    canvas.style.cursor = 'grabbing';
                    e.preventDefault();
                    e.stopPropagation();  // don't let _MAIN_JS also start a pan
                    return;
                }
            }
        });

        // When ghost env is focused in split mode, clear the placement cursor position
        // so the preview disappears from primary canvas as cursor leaves it.
        canvas.addEventListener('mouseleave', function () {
            const _mlMirrorBtn = document.getElementById('pd-tool-mirror');
            const _mlMirrorOn = !!(_mlMirrorBtn && _mlMirrorBtn.classList.contains('pd-tool-active'));
            // Only clear placement state when ghost has EXCLUSIVE focus (mirror off).
            // When mirror is on, both canvases are active so leaving primary is fine.
            const _gfs = !!document.getElementById('pd-ghost-canvas') &&
                window._pdEnvFocus === 'ghost' && !_mlMirrorOn;
            if (!_gfs) return;
            let changed = false;
            if (window._pdAgentPlacement && window._pdAgentPlacement.curFx !== undefined)
                { window._pdAgentPlacement.curFx = undefined; window._pdAgentPlacement.curFy = undefined; changed = true; }
            if (window._pdStaticPlacement && window._pdStaticPlacement.curFx !== undefined)
                { window._pdStaticPlacement.curFx = undefined; window._pdStaticPlacement.curFy = undefined; changed = true; }
            if (window._pdExpertPlacement && window._pdExpertPlacement.curFx !== undefined)
                { window._pdExpertPlacement.curFx = undefined; window._pdExpertPlacement.curFy = undefined; changed = true; }
            if (changed) _redraw();
        });

        canvas.addEventListener('mousemove', function (e) {
            // Skip primary-canvas cursor tracking only when ghost has EXCLUSIVE focus (mirror off).
            // When mirror is on, both canvases track independently.
            const _mirrorBtn2 = document.getElementById('pd-tool-mirror');
            const _mirrorOn2 = !!(_mirrorBtn2 && _mirrorBtn2.classList.contains('pd-tool-active'));
            const _skipPrimary = !!document.getElementById('pd-ghost-canvas') &&
                window._pdEnvFocus === 'ghost' && !_mirrorOn2;
            // Track cursor for the move tool (drag + heading-aim phases).
            if (window._pdTool === 'move' && !_skipPrimary) {
                const mp = window._pdMovePlacement;
                // Allow primary tracking for overlay ghost grabs (no split canvas to take over).
                const _mvOverlayGhost = mp && mp.isGhost && !document.getElementById('pd-ghost-canvas');
                if (mp && (mp.step === 1 || mp.step === 2) && (!mp.isGhost || _mvOverlayGhost)) {
                    const { cx: mcx, cy: mcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                    const f2 = _fit(canvas, document.getElementById('pd-frame-img'));
                    if (f2) {
                        mp.curFx = Math.min(1, Math.max(0, (mcx - f2.dx) / f2.dw));
                        mp.curFy = Math.min(1, Math.max(0, (mcy - f2.dy) / f2.dh));
                        _redraw();
                    }
                }
            }
            // Track cursor for add_agent preview (all steps including step 0 phantom).
            if (window._pdTool === 'add_agent' && !_skipPrimary) {
                window._pdAgentPlacement = window._pdAgentPlacement || {step: 0};
                const ap = window._pdAgentPlacement;
                const { cx: mcx, cy: mcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const img2 = document.getElementById('pd-frame-img');
                const f2 = _fit(canvas, img2);
                if (f2) {
                    ap.curFx = Math.min(1, Math.max(0, (mcx - f2.dx) / f2.dw));
                    ap.curFy = Math.min(1, Math.max(0, (mcy - f2.dy) / f2.dh));
                    _redraw();
                }
            }
            // Track cursor for add_static preview (all steps including phantom).
            if (window._pdTool === 'add_static' && !_skipPrimary) {
                window._pdStaticPlacement = window._pdStaticPlacement || {step: 0};
                const sp = window._pdStaticPlacement;
                const { cx: mcx, cy: mcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const img2 = document.getElementById('pd-frame-img');
                const f2 = _fit(canvas, img2);
                if (f2) {
                    sp.curFx = Math.min(1, Math.max(0, (mcx - f2.dx) / f2.dw));
                    sp.curFy = Math.min(1, Math.max(0, (mcy - f2.dy) / f2.dh));
                    _redraw();
                }
            }
            // Track cursor for add_expert preview.
            if (window._pdTool === 'add_expert' && !_skipPrimary) {
                window._pdExpertPlacement = window._pdExpertPlacement || {step: 0};
                const ep = window._pdExpertPlacement;
                const { cx: mcx, cy: mcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const img2 = document.getElementById('pd-frame-img');
                const f2 = _fit(canvas, img2);
                if (f2) {
                    ep.curFx = Math.min(1, Math.max(0, (mcx - f2.dx) / f2.dw));
                    ep.curFy = Math.min(1, Math.max(0, (mcy - f2.dy) / f2.dh));
                    _redraw();
                }
            }
            // Live feedback for expert waypoint drag.
            if (_wpDragAgentIdx >= 0) {
                const { cx, cy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const fw = _fit(canvas, document.getElementById('pd-frame-img'));
                if (fw) {
                    _wpDragLiveFx = Math.min(1, Math.max(0, (cx - fw.dx) / fw.dw));
                    _wpDragLiveFy = Math.min(1, Math.max(0, (cy - fw.dy) / fw.dh));
                    _redraw();
                }
                return;
            }
            // Live feedback for trajectory timestep drag.
            if (_trajDragAgentIdx >= 0) {
                const { cx, cy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                const fw = _fit(canvas, document.getElementById('pd-frame-img'));
                if (fw) {
                    _trajDragLiveFx = Math.min(1, Math.max(0, (cx - fw.dx) / fw.dw));
                    _trajDragLiveFy = Math.min(1, Math.max(0, (cy - fw.dy) / fw.dh));
                    _redraw();
                }
                return;
            }
            // Hover cursor: 'grab' when near a trajectory dot of the selected expert.
            if (window._pdTool === 'select') {
                const _ghostSelH = (window._pdGhostSelectedExpertIdx !== undefined) ? window._pdGhostSelectedExpertIdx : -1;
                const _focusGhostH = !document.getElementById('pd-ghost-canvas') && _ghostSelH >= 0;
                const _wpsH = _focusGhostH ? window._pdGhostExpertWaypoints : window._pdExpertWaypoints;
                const selEx2 = _focusGhostH
                    ? _ghostSelH
                    : ((window._pdSelectedExpertIdx !== undefined) ? window._pdSelectedExpertIdx : -1);
                if (selEx2 >= 0 && _wpsH) {
                    const { cx: hcx, cy: hcy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
                    const fwh = _fit(canvas, document.getElementById('pd-frame-img'));
                    if (fwh) {
                        const hitRh = Math.max(10, fwh.s * 2.5);
                        const selAgentH = _wpsH.find(a => a.agent_idx === selEx2);
                        let nearDot = false;
                        if (selAgentH) {
                            for (const tp of (selAgentH.traj_pts || [])) {
                                const px = fwh.dx + tp.fx * fwh.dw, py = fwh.dy + tp.fy * fwh.dh;
                                if (Math.hypot(hcx - px, hcy - py) < hitRh) { nearDot = true; break; }
                            }
                        }
                        canvas.style.cursor = nearDot ? 'grab' : '';
                    }
                } else {
                    canvas.style.cursor = '';
                }
            }
            if (_dragSlot < 0) return;
            const { cx, cy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
            _dragCx = cx; _dragCy = cy;
            if (window._pdGoalDragIsGhost) {
                const _fmv = _fit(canvas, document.getElementById('pd-frame-img'));
                if (_fmv) {
                    window._pdGhostDragFx = Math.min(1, Math.max(0, (cx - _fmv.dx) / _fmv.dw));
                    window._pdGhostDragFy = Math.min(1, Math.max(0, (cy - _fmv.dy) / _fmv.dh));
                }
                _draw(-1);
                _drawGhostPane();
            } else {
                // Both/mirror: publish the live cursor fraction so the ghost pane's same-slot
                // goal follows too, and repaint it.
                const _gmb = document.getElementById('pd-tool-mirror');
                const _gMirror = !!(_gmb && _gmb.classList.contains('pd-tool-active'));
                if (_gMirror) {
                    const _fmv = _fit(canvas, document.getElementById('pd-frame-img'));
                    if (_fmv) {
                        window._pdGoalLiveFx = Math.min(1, Math.max(0, (cx - _fmv.dx) / _fmv.dw));
                        window._pdGoalLiveFy = Math.min(1, Math.max(0, (cy - _fmv.dy) / _fmv.dh));
                    }
                }
                _draw(_dragSlot, cx, cy);
                if (_gMirror) _drawGhostPane();
            }
        });

        // document-level so releasing outside the canvas still commits the drop.
        document.addEventListener('mouseup', function (e) {
            window._pdDragResult = null;
            // Move tool: end the drag (step 1). Experts finalize here (trajectory sets the
            // heading); active/static enter the heading-aim phase (step 2).
            if (window._pdTool === 'move') {
                const mp = window._pdMovePlacement;
                if (mp && mp.step === 1) {
                    // Use the ghost canvas for coordinate mapping when the grab started there.
                    const dropCvs = mp.isGhost
                        ? (document.getElementById('pd-ghost-canvas') || canvas) : canvas;
                    const { cx: mcx, cy: mcy } = _toCvsPreTf(dropCvs, e.clientX, e.clientY);
                    const f2 = _fit(dropCvs, document.getElementById('pd-frame-img'));
                    if (f2) {
                        mp.dfx = Math.min(1, Math.max(0, (mcx - f2.dx) / f2.dw));
                        mp.dfy = Math.min(1, Math.max(0, (mcy - f2.dy) / f2.dh));
                        if (mp.car && mp.car.kind === 'e') {
                            // Send the lane-SNAPPED start + goal (matching the preview) so the
                            // server reproduces it instead of re-snapping the raw drop.
                            let dfx = mp.dfx, dfy = mp.dfy, gfx, gfy;
                            const graph = _ensureLaneGraph();
                            if (graph) {
                                const ss = _snapToLaneJS(graph, mp.dfx * f2.iw, mp.dfy * f2.ih);
                                if (ss.lane >= 0) { dfx = ss.px / f2.iw; dfy = ss.py / f2.ih; }
                                if (mp.car.goalCx !== undefined) {
                                    const sg = _snapToLaneJS(graph, mp.car.goalCx, mp.car.goalCy);
                                    if (sg.lane >= 0) { gfx = sg.px / f2.iw; gfy = sg.py / f2.ih; }
                                }
                            }
                            const result = { sfx: mp.sfx, sfy: mp.sfy, dfx: dfx, dfy: dfy,
                                             hfx: dfx, hfy: dfy, gfx: gfx, gfy: gfy };
                            window._pdMovePlacement = { step: 0 };
                            _redraw();
                            if (mp.isGhost) {
                                window._pdGhostMoveResult = result;
                                const btn = document.getElementById('pd-ghost-agent-move-trigger');
                                if (btn) btn.click();
                            } else {
                                window._pdMoveResult = result;
                                const btn = document.getElementById('pd-agent-move-trigger');
                                if (btn) btn.click();
                            }
                        } else {
                            mp.curFx = mp.dfx; mp.curFy = mp.dfy; mp.step = 2;
                            _redraw();
                        }
                    }
                    window._pdDragJustEnded = true;
                    return;
                }
            }
            // Expert waypoint drop commit.
            if (_wpDragAgentIdx >= 0) {
                const agentIdx = _wpDragAgentIdx, wpIdx = _wpDragWpIdx;
                const isGhost = _dragIsGhost;
                _wpDragAgentIdx = -1; _wpDragWpIdx = -1; _dragIsGhost = false;
                canvas.style.cursor = '';
                const _wpGcEl = document.getElementById('pd-ghost-canvas'); if (_wpGcEl) _wpGcEl.style.cursor = '';
                if (Math.hypot(e.clientX - _wpDragStartX, e.clientY - _wpDragStartY) < 5) {
                    _wpDragLiveFx = -1; _wpDragLiveFy = -1;
                    _redraw();
                    window._pdDragJustEnded = true;
                    return;
                }
                const _wpDropCvs = (isGhost && document.getElementById('pd-ghost-canvas')) || canvas;
                const { cx, cy } = _toCvsPreTf(_wpDropCvs, e.clientX, e.clientY);
                const fw = _fit(_wpDropCvs, document.getElementById('pd-frame-img'));
                if (fw) {
                    const drop = {
                        agent_idx: agentIdx, wp_idx: wpIdx,
                        pfx: Math.min(1, Math.max(0, (cx - fw.dx) / fw.dw)),
                        pfy: Math.min(1, Math.max(0, (cy - fw.dy) / fw.dh)),
                    };
                    window._pdDragJustEnded = true;
                    if (isGhost) {
                        window._pdGhostExpertWpDropResult = drop;
                        const btn = document.getElementById('pd-ghost-expert-wp-drop-trigger');
                        if (btn) btn.click();
                    } else {
                        window._pdExpertWpDropResult = drop;
                        const btn = document.getElementById('pd-expert-wp-drop-trigger');
                        if (btn) btn.click();
                    }
                }
                _wpDragLiveFx = -1; _wpDragLiveFy = -1;
                return;
            }
            // Trajectory timestep drop commit.
            if (_trajDragAgentIdx >= 0) {
                const agentIdx = _trajDragAgentIdx, trajStep = _trajDragTrajStep;
                const isGhost = _dragIsGhost;
                _trajDragAgentIdx = -1; _trajDragTrajStep = -1; _dragIsGhost = false;
                canvas.style.cursor = '';
                const _tdGcEl = document.getElementById('pd-ghost-canvas'); if (_tdGcEl) _tdGcEl.style.cursor = '';
                if (Math.hypot(e.clientX - _trajDragStartX, e.clientY - _trajDragStartY) < 5) {
                    _trajDragLiveFx = -1; _trajDragLiveFy = -1;
                    _redraw();
                    window._pdDragJustEnded = true;
                    return;
                }
                const _tdDropCvs = (isGhost && document.getElementById('pd-ghost-canvas')) || canvas;
                const { cx, cy } = _toCvsPreTf(_tdDropCvs, e.clientX, e.clientY);
                const fw = _fit(_tdDropCvs, document.getElementById('pd-frame-img'));
                if (fw) {
                    const drop = {
                        agent_idx: agentIdx, traj_step: trajStep,
                        pfx: Math.min(1, Math.max(0, (cx - fw.dx) / fw.dw)),
                        pfy: Math.min(1, Math.max(0, (cy - fw.dy) / fw.dh)),
                    };
                    window._pdDragJustEnded = true;
                    if (isGhost) {
                        window._pdGhostExpertTrajDropResult = drop;
                        const btn = document.getElementById('pd-ghost-expert-traj-drop-trigger');
                        if (btn) btn.click();
                    } else {
                        window._pdExpertTrajDropResult = drop;
                        const btn = document.getElementById('pd-expert-traj-drop-trigger');
                        if (btn) btn.click();
                    }
                }
                _trajDragLiveFx = -1; _trajDragLiveFy = -1;
                return;
            }
            if (_dragSlot < 0) return;
            const slot = _dragSlot;
            _dragSlot  = -1;
            const _wasGhostDrag = window._pdGoalDragIsGhost;
            window._pdGoalDragIsGhost = false;
            window._pdGhostDragFx = undefined; window._pdGhostDragFy = undefined;
            window._pdGoalLiveFx = undefined; window._pdGoalLiveFy = undefined;
            _dragGoalIsGhost = false;
            canvas.style.cursor = '';
            const _gcDrop = document.getElementById('pd-ghost-canvas');
            if (_gcDrop) _gcDrop.style.cursor = '';

            if (Math.hypot(e.clientX - _startX, e.clientY - _startY) < 5) {
                _redraw();  // snap back — not a real drag
                return;
            }

            // Use the ghost canvas for coordinate conversion when ghost drag, since both
            // canvases share the same scene coordinate system the fractions are equivalent.
            const _dropCvs = (_wasGhostDrag && document.getElementById('pd-ghost-canvas'))
                ? document.getElementById('pd-ghost-canvas') : canvas;
            const { cx, cy } = _toCvsPreTf(_dropCvs, e.clientX, e.clientY);
            const img2 = document.getElementById('pd-frame-img');
            const f    = _fit(_dropCvs, img2);
            if (!f) return;
            window._pdDragResult = {
                slot,
                x: Math.min(1, Math.max(0, (cx - f.dx) / f.dw)),
                y: Math.min(1, Math.max(0, (cy - f.dy) / f.dh)),
            };
            // Trigger the Reflex drop handler via a hidden button — more reliable
            // than programmatic img.click() in React's synthetic event system.
            const btn = document.getElementById('pd-goal-drop-trigger');
            if (btn) btn.click();
        });

        // ── Coordinate display (bottom-right, world coords under cursor) ──────
        cont.addEventListener('mousemove', function (e) {
            const disp = document.getElementById('pd-coord-display');
            if (!disp) return;
            const rt = window._pdRenderTransform;
            if (!rt) { disp.style.display = 'none'; return; }
            const { cx, cy } = _toCvsPreTf(canvas, e.clientX, e.clientY);
            const img2 = document.getElementById('pd-frame-img');
            const f = _fit(canvas, img2);
            if (!f) { disp.style.display = 'none'; return; }
            const fx = (cx - f.dx) / f.dw;
            const fy = (cy - f.dy) / f.dh;
            if (fx < 0 || fx > 1 || fy < 0 || fy > 1) { disp.style.display = 'none'; return; }
            const wx = fx * rt.img_w / rt.scale + rt.min_x;
            const wy = rt.max_y - fy * rt.img_h / rt.scale;
            disp.textContent = `x: ${wx.toFixed(1)}  y: ${wy.toFixed(1)}`;
            disp.style.display = 'block';
        });
        cont.addEventListener('mouseleave', function () {
            const disp = document.getElementById('pd-coord-display');
            if (disp) disp.style.display = 'none';
        });

        // ── Ghost canvas direct interaction ──────────────────────────────────────
        // When ghost env is focused in split mode, the ghost canvas has pointer-events:auto
        // so the user can interact directly with it.  We attach handlers here (retrying
        // until the canvas appears) so cursor tracking, placement clicks, and goal drag
        // all work on the right pane with the cursor visually aligned with the preview.
        function _attachGhost() {
            const gc = document.getElementById('pd-ghost-canvas');
            if (!gc) { setTimeout(_attachGhost, 400); return; }

            function _gFocused() {
                if (!document.getElementById('pd-ghost-canvas')) return false;
                const _mb = document.getElementById('pd-tool-mirror');
                const _mirrorOn = !!(_mb && _mb.classList.contains('pd-tool-active'));
                return window._pdEnvFocus === 'ghost' || _mirrorOn;
            }

            gc.addEventListener('mousemove', function (e) {
                if (!_gFocused()) return;
                window._pdCursorOnGhost = true;
                const tool = window._pdTool;
                const img2 = document.getElementById('pd-frame-img');
                const f2 = _fit(gc, img2);
                if (!f2) return;
                const { cx: gcx, cy: gcy } = _toCvsPreTf(gc, e.clientX, e.clientY);
                const gfx = Math.min(1, Math.max(0, (gcx - f2.dx) / f2.dw));
                const gfy = Math.min(1, Math.max(0, (gcy - f2.dy) / f2.dh));
                // Live feedback for ghost expert wp/traj drag initiated on gc.
                if (_wpDragAgentIdx >= 0 && _dragIsGhost) {
                    _wpDragLiveFx = gfx; _wpDragLiveFy = gfy;
                    gc.style.cursor = 'grabbing';
                    _redraw(); return;
                }
                if (_trajDragAgentIdx >= 0 && _dragIsGhost) {
                    _trajDragLiveFx = gfx; _trajDragLiveFy = gfy;
                    gc.style.cursor = 'grabbing';
                    _redraw(); return;
                }
                // Hover cursor: 'grab' when near a traj dot of the selected ghost expert.
                if (tool === 'select') {
                    const _ghostSelHG = (window._pdGhostSelectedExpertIdx !== undefined) ? window._pdGhostSelectedExpertIdx : -1;
                    if (_ghostSelHG >= 0 && window._pdGhostExpertWaypoints) {
                        const hitRhG = Math.max(10, f2.s * 2.5);
                        const selAgentHG = window._pdGhostExpertWaypoints.find(a => a.agent_idx === _ghostSelHG);
                        let nearDotG = false;
                        if (selAgentHG) {
                            for (const tp of (selAgentHG.traj_pts || [])) {
                                const px = f2.dx + tp.fx * f2.dw, py = f2.dy + tp.fy * f2.dh;
                                if (Math.hypot(gcx - px, gcy - py) < hitRhG) { nearDotG = true; break; }
                            }
                        }
                        gc.style.cursor = nearDotG ? 'grab' : '';
                    } else {
                        gc.style.cursor = '';
                    }
                    return;
                }
                if (tool === 'move') {
                    const mp = window._pdMovePlacement;
                    if (mp && (mp.step === 1 || mp.step === 2) && mp.isGhost) {
                        mp.curFx = gfx; mp.curFy = gfy;
                        _redraw();
                    }
                } else if (tool === 'add_agent') {
                    window._pdAgentPlacement = window._pdAgentPlacement || {step: 0};
                    window._pdAgentPlacement.curFx = gfx; window._pdAgentPlacement.curFy = gfy;
                    _redraw();
                } else if (tool === 'add_static') {
                    window._pdStaticPlacement = window._pdStaticPlacement || {step: 0};
                    window._pdStaticPlacement.curFx = gfx; window._pdStaticPlacement.curFy = gfy;
                    _redraw();
                } else if (tool === 'add_expert') {
                    window._pdExpertPlacement = window._pdExpertPlacement || {step: 0};
                    window._pdExpertPlacement.curFx = gfx; window._pdExpertPlacement.curFy = gfy;
                    _redraw();
                } else if (tool === 'goal' && _dragSlot >= 0 && window._pdGoalDragIsGhost) {
                    window._pdGhostDragFx = gfx; window._pdGhostDragFy = gfy;
                    // Both/mirror: publish live fraction so the primary pane's same-slot goal follows.
                    window._pdGoalLiveFx = gfx; window._pdGoalLiveFy = gfy;
                    _draw(-1); _drawGhostPane();
                }
            });

            gc.addEventListener('mouseleave', function () {
                window._pdCursorOnGhost = false;
                if (!_gFocused()) return;
                let changed = false;
                if (window._pdAgentPlacement && window._pdAgentPlacement.curFx !== undefined)
                    { window._pdAgentPlacement.curFx = undefined; window._pdAgentPlacement.curFy = undefined; changed = true; }
                if (window._pdStaticPlacement && window._pdStaticPlacement.curFx !== undefined)
                    { window._pdStaticPlacement.curFx = undefined; window._pdStaticPlacement.curFy = undefined; changed = true; }
                if (window._pdExpertPlacement && window._pdExpertPlacement.curFx !== undefined)
                    { window._pdExpertPlacement.curFx = undefined; window._pdExpertPlacement.curFy = undefined; changed = true; }
                if (changed) _redraw();
            });

            gc.addEventListener('mousedown', function (e) {
                if (!_gFocused()) return;
                const tool = window._pdTool;
                const img2 = document.getElementById('pd-frame-img');
                const f2 = _fit(gc, img2);
                if (!f2) return;
                const { cx: gcx, cy: gcy } = _toCvsPreTf(gc, e.clientX, e.clientY);
                const gfx = Math.min(1, Math.max(0, (gcx - f2.dx) / f2.dw));
                const gfy = Math.min(1, Math.max(0, (gcy - f2.dy) / f2.dh));

                // Ghost trajectory timestep drag (highest priority, any tool, when ghost expert selected).
                const _gwpSel = (window._pdGhostSelectedExpertIdx !== undefined) ? window._pdGhostSelectedExpertIdx : -1;
                if (_gwpSel >= 0 && window._pdGhostExpertWaypoints) {
                    const hitRtd = Math.max(4, f2.s * 1.0);
                    const selAgentTd = window._pdGhostExpertWaypoints.find(a => a.agent_idx === _gwpSel);
                    if (selAgentTd) {
                        for (const tp of (selAgentTd.traj_pts || [])) {
                            const px = f2.dx + tp.fx * f2.dw, py = f2.dy + tp.fy * f2.dh;
                            if (Math.hypot(gcx - px, gcy - py) < hitRtd) {
                                _trajDragAgentIdx = selAgentTd.agent_idx;
                                _trajDragTrajStep = tp.t;
                                _trajDragLiveFx   = tp.fx; _trajDragLiveFy = tp.fy;
                                _trajDragStartX   = e.clientX; _trajDragStartY = e.clientY;
                                _dragIsGhost      = true;
                                gc.style.cursor   = 'grabbing';
                                e.preventDefault(); e.stopPropagation(); return;
                            }
                        }
                    }
                }

                if (tool === 'move') {
                    window._pdMovePlacement = window._pdMovePlacement || { step: 0 };
                    const mp = window._pdMovePlacement;
                    if (mp.step === 2 && mp.isGhost) {
                        // Heading-aim click on ghost canvas — finalize move.
                        window._pdGhostMoveResult = { sfx: mp.sfx, sfy: mp.sfy, dfx: mp.dfx, dfy: mp.dfy, hfx: gfx, hfy: gfy };
                        window._pdMovePlacement = { step: 0 };
                        window._pdDragJustEnded = true;
                        _redraw();
                        const btn = document.getElementById('pd-ghost-agent-move-trigger');
                        if (btn) btn.click();
                    } else if (mp.step === 0) {
                        // Initial grab: hit-test ghost cars.
                        const car = _pdHitGhostCar(gcx, gcy, f2);
                        if (car) {
                            mp.car = car; mp.sfx = gfx; mp.sfy = gfy;
                            mp.curFx = gfx; mp.curFy = gfy; mp.step = 1; mp.isGhost = true;
                            _redraw();
                        }
                    }
                    e.preventDefault(); e.stopPropagation(); return;
                }
                if (tool === 'add_agent') {
                    window._pdAgentPlacement = window._pdAgentPlacement || {step: 0};
                    const apG = window._pdAgentPlacement;
                    if (apG.step === 0) {
                        apG.fx = gfx; apG.fy = gfy; apG.curFx = gfx; apG.curFy = gfy; apG.step = 1;
                        _redraw();
                    } else if (apG.step === 1) {
                        apG.hfx = gfx; apG.hfy = gfy; apG.curFx = gfx; apG.curFy = gfy; apG.step = 2;
                        _redraw();
                    } else if (apG.step === 2) {
                        window._pdAgentPlaceResult = { pfx: apG.fx, pfy: apG.fy, hfx: apG.hfx, hfy: apG.hfy, gfx, gfy };
                        apG.step = 0; apG.curFx = undefined; apG.curFy = undefined;
                        _redraw();
                        const btn = document.getElementById('pd-agent-place-trigger');
                        if (btn) btn.click();
                    }
                    e.preventDefault(); e.stopPropagation(); return;
                }
                if (tool === 'add_static') {
                    window._pdStaticPlacement = window._pdStaticPlacement || {step: 0};
                    const spG = window._pdStaticPlacement;
                    if (spG.step === 0) {
                        spG.fx = gfx; spG.fy = gfy; spG.curFx = gfx; spG.curFy = gfy; spG.step = 1;
                        _redraw();
                    } else if (spG.step === 1) {
                        window._pdStaticPlaceResult = { pfx: spG.fx, pfy: spG.fy, hfx: gfx, hfy: gfy };
                        spG.step = 0; spG.curFx = undefined; spG.curFy = undefined;
                        _redraw();
                        const btn = document.getElementById('pd-static-place-trigger');
                        if (btn) btn.click();
                    }
                    e.preventDefault(); e.stopPropagation(); return;
                }
                if (tool === 'add_expert') {
                    window._pdExpertPlacement = window._pdExpertPlacement || {step: 0};
                    const epG = window._pdExpertPlacement;
                    if (epG.step === 0) {
                        epG.sfx = gfx; epG.sfy = gfy; epG.curFx = gfx; epG.curFy = gfy; epG.step = 1;
                        _redraw();
                    } else if (epG.step === 1) {
                        window._pdExpertPlaceResult = {
                            pfx: epG.sfx, pfy: epG.sfy,
                            hfx: epG.sfx, hfy: epG.sfy,
                            efx: gfx, efy: gfy,
                        };
                        epG.step = 0; epG.curFx = undefined; epG.curFy = undefined;
                        _redraw();
                        const btn = document.getElementById('pd-expert-place-trigger');
                        if (btn) btn.click();
                    }
                    e.preventDefault(); e.stopPropagation(); return;
                }
                if (tool === 'goal') {
                    // Expert waypoint drag takes priority over goal drag.
                    const _gwpSel2 = (window._pdGhostSelectedExpertIdx !== undefined) ? window._pdGhostSelectedExpertIdx : -1;
                    if (_gwpSel2 >= 0 && window._pdGhostExpertWaypoints && window._pdGhostExpertWaypoints.length > 0) {
                        const hitRwp = Math.max(6, f2.s * 1.5);
                        for (const agent of window._pdGhostExpertWaypoints) {
                            for (const pt of agent.points) {
                                const px = f2.dx + pt.fx * f2.dw, py = f2.dy + pt.fy * f2.dh;
                                if (Math.hypot(gcx - px, gcy - py) < hitRwp) {
                                    _wpDragAgentIdx = agent.agent_idx;
                                    _wpDragWpIdx    = pt.wp_idx;
                                    _wpDragLiveFx   = pt.fx; _wpDragLiveFy = pt.fy;
                                    _wpDragStartX   = e.clientX; _wpDragStartY = e.clientY;
                                    _dragIsGhost    = true;
                                    gc.style.cursor = 'grabbing';
                                    e.preventDefault(); e.stopPropagation(); return;
                                }
                            }
                        }
                    }
                    const hitX = 15 / f2.iw, hitY = 15 / f2.ih;
                    _dragSlot = -1; window._pdGoalDragIsGhost = false;
                    for (const g of (window._pdGhostGoalPositions || [])) {
                        if (Math.abs(gfx - g.fx) < hitX && Math.abs(gfy - g.fy) < hitY) {
                            _dragSlot = g.slot; _startX = e.clientX; _startY = e.clientY;
                            window._pdGoalDragIsGhost = true;
                            gc.style.cursor = 'grabbing';
                            e.preventDefault(); e.stopPropagation(); return;
                        }
                    }
                }
            });
        }
        _attachGhost();
    }
    window._pdRedraw = _redraw;
    // Abort an in-progress expert waypoint / trajectory-timestep drag (e.g. on Esc).
    // Nothing is committed until mouse-up, so this just resets the transient drag
    // state and redraws, snapping the dragged point back to its committed position.
    // Returns true iff a drag was actually in progress and got cancelled.
    window._pdAbortExpertDrag = function () {
        if (_wpDragAgentIdx < 0 && _trajDragAgentIdx < 0) return false;
        _wpDragAgentIdx = -1; _wpDragWpIdx = -1;
        _trajDragAgentIdx = -1; _trajDragTrajStep = -1;
        _wpDragLiveFx = -1; _wpDragLiveFy = -1;
        _trajDragLiveFx = -1; _trajDragLiveFy = -1;
        _dragIsGhost = false;
        var c = document.getElementById('pd-canvas');
        if (c) c.style.cursor = '';
        var gc2 = document.getElementById('pd-ghost-canvas');
        if (gc2) gc2.style.cursor = '';
        window._pdDragJustEnded = true;  // suppress the click that may follow on release
        if (window._pdRedraw) window._pdRedraw();
        return true;
    };

    // Abort an in-progress goal drag or agent-move (drag + heading-aim phases) on Esc.
    // Nothing is committed until mouse-up, so this just clears the transient drag state
    // and redraws, snapping the marker back to its committed position. Returns true iff
    // something was actually in progress.
    window._pdAbortGoalDrag = function () {
        var moving = !!(window._pdMovePlacement && window._pdMovePlacement.step > 0);
        if (_dragSlot < 0 && !moving) return false;
        _dragSlot = -1;
        _dragGoalIsGhost = false;
        window._pdGoalDragIsGhost = false;
        window._pdGhostDragFx = undefined; window._pdGhostDragFy = undefined;
        window._pdGoalLiveFx = undefined; window._pdGoalLiveFy = undefined;
        window._pdMovePlacement = { step: 0 };
        var c = document.getElementById('pd-canvas'); if (c) c.style.cursor = '';
        var gc2 = document.getElementById('pd-ghost-canvas'); if (gc2) gc2.style.cursor = '';
        window._pdDragJustEnded = true;  // suppress the click that may follow on release
        if (window._pdRedraw) window._pdRedraw();
        return true;
    };
    _attach();
})();
"""

_ZOOM_JS = """
(function () {
    const MIN_ZOOM = 1, MAX_ZOOM = 8;
    let _z = 1;

    function _applyZoom() {
        const layer = document.getElementById('pd-zoom-layer');
        if (layer) layer.style.transform = _z === 1 ? '' : `scale(${_z})`;
        const label = document.getElementById('pd-zoom-level');
        if (label) label.textContent = Math.round(_z * 100) + '%';
    }

    function _ensureLabel() {
        if (document.getElementById('pd-zoom-level')) return;
        const overlay = document.getElementById('pd-zoom-overlay');
        if (!overlay) { setTimeout(_ensureLabel, 200); return; }
        const el = document.createElement('div');
        el.id = 'pd-zoom-level';
        el.style.cssText = 'font-size:11px;color:#94a3b8;text-align:center;padding:4px;';
        el.textContent = '100%';
        overlay.appendChild(el);
    }

    window._pdZoomReset = function () { _z = 1; _applyZoom(); };

    window._pdZoomStep = function (delta) {
        _z = delta > 0
            ? Math.min(_z * 1.25, MAX_ZOOM)
            : Math.max(_z / 1.25, MIN_ZOOM);
        _applyZoom();
    };

    const SENSITIVITY = 0.01;
    function _wheelZoom(e) {
        e.preventDefault();
        let dy = e.deltaY;
        if (e.deltaMode === 1) dy *= 16;
        else if (e.deltaMode === 2) dy *= window.innerHeight;
        const factor = Math.max(0.85, Math.min(1.18, Math.exp(-dy * SENSITIVITY)));
        _z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, _z * factor));
        _applyZoom();
    }

    function _attach() {
        const container = document.getElementById('pd-canvas-container');
        if (!container) { setTimeout(_attach, 200); return; }
        container.addEventListener('wheel', _wheelZoom, { passive: false });
    }

    _ensureLabel();
    _attach();
})();
"""

# ── Smooth playback: client-side rAF with pose interpolation ─────────────────
_RAF_PLAY_JS = """
(function () {
    var _rafId = null;
    var _rafLastT = null;
    // SNAP_DIST: if distance between consecutive frames > this (image pixels), skip lerp
    var SNAP_DIST = 80;

    function _lerp(a, b, t) { return a + (b - a) * t; }
    function _lerpAngle(a, b, t) {
        var d = b - a;
        while (d >  Math.PI) d -= 2 * Math.PI;
        while (d < -Math.PI) d += 2 * Math.PI;
        return a + d * t;
    }

    // Build a slot-keyed map for fast lookup.
    function _slotMap(frame) {
        var m = {};
        if (!frame) return m;
        for (var i = 0; i < frame.length; i++) m[frame[i].slot] = frame[i];
        return m;
    }

    // Return lerped copy of frameA toward frameB at fraction t.
    function _lerpFrame(frameA, frameB, t) {
        if (!frameA || !frameA.length) return [];
        if (!t || !frameB || !frameB.length) return frameA;
        var bm = _slotMap(frameB);
        var out = [];
        for (var j = 0; j < frameA.length; j++) {
            var a = frameA[j];
            var b = bm[a.slot];
            if (!b) { out.push(a); continue; }
            var dx = b.cx - a.cx, dy = b.cy - a.cy;
            if (dx * dx + dy * dy > SNAP_DIST * SNAP_DIST) { out.push(a); continue; }
            out.push({
                cx: _lerp(a.cx, b.cx, t),
                cy: _lerp(a.cy, b.cy, t),
                heading: _lerpAngle(a.heading, b.heading, t),
                hl: a.hl, hw: a.hw, slot: a.slot, id: a.id,
                lx: _lerp(a.lx, b.lx, t),
                ly: _lerp(a.ly, b.ly, t),
            });
        }
        return out;
    }

    // Called by the agent renderer when rAF playback is active.
    window._pdGetLerpedFrame = function (frames, frameIdx) {
        var frac = window._pdRafFracFrame;
        if (frac === undefined || !window._pdRafActive) return frames[frameIdx] || [];
        // Sub-frame progress measured RELATIVE to the server's authoritative integer
        // frame (frameIdx). Both the lerp base (frameIdx) and the amount (t) are now
        // on the same clock. The old code used `frac - Math.floor(frac)`, mixing the
        // server integer (frameIdx) with the client rAF clock's own fractional part;
        // when the rAF clock crossed an integer boundary before the server tick bumped
        // frameIdx, t snapped back toward 0 while the base index stayed put, rendering
        // the agent one frame BACKWARD — then forward again on the next server tick.
        // That two-clock race was the back-and-forth flicker.
        var t = frac - frameIdx;
        if (t <= 0.001) return frames[frameIdx] || [];   // rAF behind server → snap to server frame
        if (t > 1) t = 1;                                 // rAF ahead → hold at next frame, no overshoot
        return _lerpFrame(frames[frameIdx] || [], frames[frameIdx + 1] || null, t);
    };

    function _rafTick(ts) {
        if (!window._pdRafActive) { _rafId = null; _rafLastT = null; return; }
        if (_rafLastT !== null) {
            var dt = (ts - _rafLastT) / 1000;
            var speed   = window._pdPlaySpeed   || 1.0;
            var dtFrame = (window._pdRafDT || 0.1) * (window._pdRafSaveEvery || 2);
            window._pdRafFracFrame = (window._pdRafFracFrame || 0) + dt * speed / dtFrame;
            if (window._pdRedraw) window._pdRedraw();
        }
        _rafLastT = ts;
        _rafId = requestAnimationFrame(_rafTick);
    }

    window._pdStartRaf = function (speed, dt, saveEvery) {
        if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
        window._pdRafActive = true;
        window._pdPlaySpeed    = speed;
        window._pdRafDT        = dt;
        window._pdRafSaveEvery = saveEvery;
        window._pdRafFracFrame = 0;
        _rafLastT = null;
        _rafId = requestAnimationFrame(_rafTick);
    };

    window._pdStopRaf = function () {
        window._pdRafActive = false;
        window._pdRafFracFrame = undefined;
        if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
        _rafLastT = null;
    };

    // Sync rAF frame to server-driven integer whenever Reflex updates the counter.
    function _attachSyncObs() {
        var el = document.getElementById('pd-current-frame-el');
        if (!el) { setTimeout(_attachSyncObs, 300); return; }
        new MutationObserver(function () {
            if (!window._pdRafActive) return;
            var fi = parseInt(el.textContent || '0', 10) || 0;
            var subT = (window._pdRafFracFrame || 0) - Math.floor(window._pdRafFracFrame || 0);
            window._pdRafFracFrame = fi + subT;
        }).observe(el, { childList: true, subtree: true, characterData: true });
    }
    _attachSyncObs();
})();
"""
