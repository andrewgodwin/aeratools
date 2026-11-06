/*
 * Gantt chart page: renders the projected schedule as SVG and edits the chart.
 */
(function () {
    'use strict';

    const S = window.GanttSchedule;
    const { token, chart } = window.GANTT;
    let rev = window.GANTT.rev;

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
    const ROW_H = 30;
    const GROUP_H = 28;
    const AXIS_H = 100;
    const BAR_INSET = 4;
    const BAR_PAD = 2;
    const LANE_STEP = 6;
    const ENTRY_STEP = 5;
    const GAP_W = 8;
    const MIN_WEEK_W = 64;
    const MAX_WEEK_W = 150;
    const MIN_WEEKS = 8;
    const MIN_LABEL_W = 140;
    const MAX_LABEL_W = 320;
    const INDENT = 16;
    const FONT_SIZE = 13;
    const BAR_FONT_SIZE = 15;
    const EXPORT_WIDTH = 1400;
    const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    const TEAM_COLORS = {
        blue: '#cfe2ff',
        green: '#c2f5c0',
        teal: '#b4f4ea',
        orange: '#ffdba1',
        pink: '#ffd3e0',
        purple: '#e0d4ff',
        yellow: '#fff1a8',
        grey: '#e6e8ec',
    };
    const BAR_INK = { stroke: '#333a45', text: '#1f2430', warn: '#d32f2f' };
    const DARK = {
        bg: '#0f0f13', fg: '#e8e8f0', muted: '#7b7b91', grid: '#2a2a3a', axis: '#4a4a5e',
        line: '#a0a0b4', milestone: '#9d90ff', group: '#1a1a24', summary: '#a0a0b4', late: '#ff7b72',
    };
    const LIGHT = {
        bg: '#f0f0f5', fg: '#0f0f1a', muted: '#6c6c80', grid: '#d6d6e0', axis: '#9a9aaa',
        line: '#4a505c', milestone: '#5b4fff', group: '#e0e0ea', summary: '#4a505c', late: '#c62828',
    };
    const EXPORT = { ...LIGHT, bg: '#ffffff', group: '#f0f0f5' };

    const svg = document.getElementById('chart');
    const scroller = document.getElementById('scroll');
    const dialog = document.getElementById('dialog');
    const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const measureContext = document.createElement('canvas').getContext('2d');

    let calendar;
    let plan;
    let liveLayout = null;

    /* ── Helpers ── */

    /* Create an HTML element with properties and children. */
    function h(tag, props, ...children) {
        const node = document.createElement(tag);
        for (const [key, value] of Object.entries(props || {})) {
            if (key === 'class') node.className = value;
            else if (key === 'text') node.textContent = value;
            else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
            else if (key in node) node[key] = value;
            else node.setAttribute(key, value);
        }
        node.append(...children.filter(Boolean));
        return node;
    }

    /* Create an SVG element with attributes inside a parent. */
    function s(tag, attrs, parent, text) {
        const node = document.createElementNS(SVG_NS, tag);
        for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
        if (text !== undefined) node.textContent = text;
        if (parent) parent.appendChild(node);
        return node;
    }

    /* Return a new unique row or type ID. */
    function newId() {
        return Math.random().toString(36).slice(2, 10);
    }

    /* Return the pixel width of a string in the chart font. */
    function textWidth(text, size = FONT_SIZE) {
        measureContext.font = `${size}px ${FONT}`;
        return measureContext.measureText(text).width;
    }

    /* Shorten text with an ellipsis to fit a pixel width. */
    function ellipsize(text, width) {
        if (textWidth(text) <= width) return text;
        let length = text.length;
        while (length > 0 && textWidth(text.slice(0, length) + '…') > width) length--;
        return text.slice(0, length) + '…';
    }

    /* Format an ISO date as "Jan 25". */
    function shortDate(iso) {
        return `${MONTHS[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}`;
    }

    /* Format an ISO date as "Jan 25, 2027". */
    function longDate(iso) {
        return `${shortDate(iso)}, ${iso.slice(0, 4)}`;
    }

    /* Return the people types a task uses, in the order they are defined. */
    function usedTypes(task) {
        return chart.types.filter(t => (task.needs || {})[t.id] > 0);
    }

    /* Return the people part of a task's automatic label, e.g. "2 LL/SB". */
    function peopleLabel(task) {
        return usedTypes(task)
            .map(t => (task.needs[t.id] > 1 ? `${task.needs[t.id]} ${t.abbr}` : t.abbr))
            .join('/');
    }

    /* Return a task's bar text, using its custom label if it has one. */
    function barLabel(task) {
        if (task.label) return task.label;
        const people = peopleLabel(task);
        const length = S.formatDuration(task.days);
        return people ? `${people} · ${length}` : length;
    }

    /* Return each row's enclosing group ID, or null for ungrouped rows. */
    function groupMembership() {
        const membership = new Map();
        let group = null;
        for (const row of chart.rows) {
            if (row.kind === 'group') group = row;
            else membership.set(row.id, group ? group.id : null);
        }
        return membership;
    }

    /* Return the IDs of a row and every row that depends on it, directly or not. */
    function downstreamOf(id) {
        const found = new Set([id]);
        let grew = true;
        while (grew) {
            grew = false;
            for (const row of chart.rows) {
                if (!found.has(row.id) && (row.deps || []).some(d => found.has(d))) {
                    found.add(row.id);
                    grew = true;
                }
            }
        }
        return found;
    }

    /* ── Saving ── */

    let saveTimer = null;
    let saving = false;
    let dirty = false;
    let conflicted = false;

    /* Show the save state in the page header. */
    function setStatus(text) {
        document.getElementById('save-status').textContent = text;
    }

    /* Queue the chart to be saved shortly. */
    function queueSave() {
        if (conflicted) return;
        dirty = true;
        setStatus('Saving…');
        clearTimeout(saveTimer);
        saveTimer = setTimeout(flushSave, 500);
    }

    /* Tell the user another tab changed the chart, stopping further saves. */
    function showConflict() {
        conflicted = true;
        setStatus('');
        const warning = document.getElementById('warning');
        warning.hidden = false;
        warning.replaceChildren(
            'This chart was changed elsewhere, so your latest edits were not saved. ',
            h('button', { class: 'g-btn', text: 'Reload', onclick: () => location.reload() })
        );
    }

    /* Send the chart to the server, retrying on failure. */
    async function flushSave() {
        if (saving || conflicted || !dirty) return;
        saving = true;
        dirty = false;
        let retry = false;
        try {
            const response = await fetch(`/${token}/data`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ rev, chart }),
            });
            if (response.status === 409) {
                showConflict();
            } else if (response.ok) {
                rev = (await response.json()).rev;
                if (!dirty) setStatus('Saved');
            } else {
                retry = true;
            }
        } catch (error) {
            retry = true;
        }
        saving = false;
        if (retry) {
            dirty = true;
            setStatus('Not saved, retrying…');
            saveTimer = setTimeout(flushSave, 5000);
        } else if (dirty) {
            flushSave();
        }
    }

    /* Recalculate and redraw after an edit, and save it. */
    function commit() {
        refresh();
        queueSave();
    }

    /* Add this chart to the browser's recently opened list. */
    function rememberChart() {
        try {
            const recent = JSON.parse(localStorage.getItem('gantt-recent')) || [];
            const others = recent.filter(item => item.token !== token);
            const updated = [{ token, title: chart.title }, ...others].slice(0, 20);
            localStorage.setItem('gantt-recent', JSON.stringify(updated));
        } catch (error) {
            // Recents are a convenience; the chart works without storage.
        }
    }

    /* ── Layout ── */

    /* Compute positions of every visible row and week for a total width. */
    function computeLayout(width) {
        const membership = groupMembership();
        const collapsed = new Map(
            chart.rows.filter(r => r.kind === 'group').map(r => [r.id, !!r.collapsed])
        );
        const rows = [];
        const rowY = new Map();
        let y = AXIS_H;
        let labelW = MIN_LABEL_W;
        chart.rows.forEach((row, index) => {
            const group = membership.get(row.id) || null;
            const indent = group ? INDENT : 0;
            labelW = Math.max(labelW, textWidth(row.name) + indent + 44);
            if (group && collapsed.get(group)) {
                rowY.set(row.id, rowY.get(group));
                return;
            }
            const height = row.kind === 'group' ? GROUP_H : ROW_H;
            rows.push({ row, index, y, height, indent });
            rowY.set(row.id, y + height / 2);
            y += height;
        });
        labelW = Math.min(labelW, MAX_LABEL_W);

        const lastDay = Math.max(plan.end, 1);
        const weeks = Math.max(MIN_WEEKS, Math.ceil(lastDay / S.WEEK_DAYS) + 1);
        const gapOffsets = [];
        let gapCount = 0;
        for (let week = 0; week <= weeks; week++) {
            if (calendar.gapBefore(week)) gapCount++;
            gapOffsets.push(gapCount * GAP_W);
        }
        const room = (width - labelW - 16 - gapOffsets[weeks - 1]) / weeks;
        const weekW = Math.min(MAX_WEEK_W, Math.max(MIN_WEEK_W, room));
        const left = labelW + 8;

        /* Return the x position of the start of a working day. */
        const dayX = day => {
            const week = Math.floor(day / S.WEEK_DAYS);
            const wholeWeek = Math.min(week, weeks);
            return left + wholeWeek * weekW + gapOffsets[wholeWeek] +
                (day - wholeWeek * S.WEEK_DAYS) * (weekW / S.WEEK_DAYS);
        };

        const chartW = dayX(weeks * S.WEEK_DAYS) + 8;
        return {
            rows, rowY, labelW, left, weeks, weekW, dayX,
            width: Math.max(width, chartW),
            height: y + 12,
            right: chartW,
            membership,
            collapsed,
        };
    }

    /* Return a bar's left and right x positions. */
    function barEdges(layout, task) {
        const placed = plan.rows.get(task.id);
        return {
            x0: layout.dayX(placed.start) + BAR_INSET,
            x1: layout.dayX(placed.end - 1) + layout.weekW / S.WEEK_DAYS - BAR_INSET,
        };
    }

    /* ── Rendering ── */

    /* Draw the week lines and excluded-week gaps. */
    function drawGrid(layer, layout, pal) {
        const bottom = layout.height - 12;
        for (let week = 0; week <= layout.weeks; week++) {
            const x = layout.dayX(week * S.WEEK_DAYS);
            s('line', { x1: x, x2: x, y1: AXIS_H, y2: bottom, stroke: pal.grid }, layer);
            if (calendar.gapBefore(week)) {
                const before = x - GAP_W + 2;
                s('line', { x1: before, x2: before, y1: AXIS_H, y2: bottom, stroke: pal.grid }, layer);
            }
        }
        s('line', { x1: layout.left, x2: layout.right, y1: bottom, y2: bottom, stroke: pal.axis }, layer);
    }

    /* Draw week dates and excluded-week labels above the chart. */
    function drawAxis(layer, layout, pal) {
        s('rect', { x: 0, y: 0, width: layout.width, height: AXIS_H, fill: pal.bg }, layer);
        let lastYear = null;
        for (let week = 0; week < layout.weeks; week++) {
            const x = layout.dayX(week * S.WEEK_DAYS);
            const iso = new Date(calendar.weekStart(week)).toISOString().slice(0, 10);
            const year = iso.slice(0, 4);
            const showYear = lastYear !== null && year !== lastYear;
            lastYear = year;
            s('text', {
                x: x + layout.weekW / 2,
                y: AXIS_H - 10,
                'text-anchor': 'middle',
                fill: pal.fg,
                'font-size': FONT_SIZE,
            }, layer, showYear ? `${shortDate(iso)} ’${year.slice(2)}` : shortDate(iso));
            const gap = calendar.gapBefore(week);
            if (gap && gap.label) {
                const gapX = x - GAP_W / 2;
                s('text', {
                    x: gapX,
                    y: AXIS_H - 26,
                    fill: pal.muted,
                    'font-size': 11,
                    transform: `rotate(-60 ${gapX} ${AXIS_H - 26})`,
                }, layer, ellipsize(gap.label, 96));
            }
        }
        s('line', {
            x1: layout.left, x2: layout.right, y1: AXIS_H, y2: AXIS_H,
            stroke: pal.axis, 'stroke-width': 2,
        }, layer);
    }

    /* Return the visible dependency lines, skipping those inside a collapsed group. */
    function dependencyEdges(layout) {
        const byId = new Map(chart.rows.map(r => [r.id, r]));
        const edges = [];
        for (const task of chart.rows) {
            if (task.kind === 'group' || plan.rows.get(task.id).cyclic) continue;
            const group = layout.membership.get(task.id);
            for (const id of new Set(task.deps || [])) {
                const pred = byId.get(id);
                if (!pred || pred.kind === 'group' || pred.id === task.id) continue;
                if (group && layout.collapsed.get(group) && layout.membership.get(id) === group) continue;
                edges.push({
                    pred,
                    task,
                    x0: pred.kind === 'milestone'
                        ? layout.dayX(plan.rows.get(pred.id).start)
                        : barEdges(layout, pred).x1,
                    x1: task.kind === 'milestone'
                        ? layout.dayX(plan.rows.get(task.id).start)
                        : barEdges(layout, task).x0,
                    fromY: layout.rowY.get(pred.id),
                    toY: layout.rowY.get(task.id),
                });
            }
        }
        return edges;
    }

    /*
     * Give each source its own vertical lane, as sources that end together would
     * otherwise draw on top of each other. Upper sources take the lanes further right
     * so that their lines pass beyond the lower sources' lines.
     */
    function assignLanes(edges) {
        const clusters = new Map();
        for (const edge of edges) {
            const key = `${edge.pred.kind}:${plan.rows.get(edge.pred.id).end}`;
            if (!clusters.has(key)) clusters.set(key, []);
            clusters.get(key).push(edge);
        }
        for (const cluster of clusters.values()) {
            const sources = [...new Set(cluster.map(edge => edge.pred.id))];
            const fromY = new Map(cluster.map(edge => [edge.pred.id, edge.fromY]));
            sources.sort((a, b) => fromY.get(b) - fromY.get(a));
            const left = Math.max(...cluster.map(edge => edge.x0));
            const right = Math.min(...cluster.map(edge => edge.x1));
            const step = Math.min(LANE_STEP, (right - left) / (sources.length + 1));
            for (const edge of cluster) {
                edge.lane = left + step * (sources.indexOf(edge.pred.id) + 1);
            }
        }
    }

    /*
     * Spread the lines entering each target vertically so they don't merge. Lines from
     * above take the upper entry points and lines from below the lower ones, ordered so
     * that none has to cross another to reach its entry point.
     */
    function assignEntries(edges) {
        const targets = new Map();
        for (const edge of edges) {
            if (!targets.has(edge.task.id)) targets.set(edge.task.id, []);
            targets.get(edge.task.id).push(edge);
        }
        const barHeight = ROW_H - BAR_PAD * 2;
        for (const entering of targets.values()) {
            const fromAbove = entering.filter(e => e.fromY <= e.toY).sort((a, b) => b.lane - a.lane);
            const fromBelow = entering.filter(e => e.fromY > e.toY).sort((a, b) => a.lane - b.lane);
            const ordered = [...fromAbove, ...fromBelow];
            const lines = ordered.length - 1;
            const step = lines ? Math.min(ENTRY_STEP, (barHeight - 8) / lines) : 0;
            ordered.forEach((edge, index) => {
                edge.entryY = edge.toY + (index - lines / 2) * step;
            });
        }
    }

    /* Draw every dependency: out of the source, along its lane, then across to the target. */
    function drawDependencies(layer, layout, pal) {
        const edges = dependencyEdges(layout);
        assignLanes(edges);
        assignEntries(edges);
        for (const { x0, x1, fromY, lane, entryY } of edges) {
            s('path', {
                d: `M${x0} ${fromY}H${lane}V${entryY}H${x1}`,
                fill: 'none',
                stroke: pal.line,
                'stroke-width': 1.5,
            }, layer);
        }
    }

    /* Draw a milestone's full-height line, which sits behind the bars. */
    function drawMilestoneLine(layer, layout, pal, row) {
        const x = layout.dayX(plan.rows.get(row.id).start);
        s('line', {
            x1: x, x2: x, y1: AXIS_H, y2: layout.height - 12,
            stroke: pal.milestone, 'stroke-width': 8, 'stroke-opacity': 0.5,
        }, layer);
    }

    /* Return a milestone's date text, including slip against any target. */
    function milestoneText(row) {
        const placed = plan.rows.get(row.id);
        const text = shortDate(calendar.dayToISO(placed.start));
        if (!row.target) return { text, late: false };
        const slip = placed.start - calendar.isoToDay(row.target);
        if (slip === 0) return { text: `${text}, on target`, late: false };
        const length = S.formatDuration(Math.abs(slip));
        return { text: `${text}, ${length} ${slip > 0 ? 'late' : 'early'}`, late: slip > 0 };
    }

    /* Draw a milestone's marker and date in its own row. */
    function drawMilestoneMarker(layer, layout, pal, entry, live) {
        const { row, y, height } = entry;
        const g = s('g', { class: 'g-clickable', 'data-id': row.id }, layer);
        const x = layout.dayX(plan.rows.get(row.id).start);
        const mid = y + height / 2;
        s('path', {
            d: `M${x} ${mid - 8}L${x + 8} ${mid}L${x} ${mid + 8}L${x - 8} ${mid}Z`,
            fill: pal.milestone,
            stroke: pal.bg,
            'stroke-width': 1.5,
        }, g);
        const { text, late } = milestoneText(row);
        const nearEdge = x + 16 + textWidth(text) > layout.right;
        s('text', {
            x: nearEdge ? x - 13 : x + 13,
            y: mid + 4.5,
            'text-anchor': nearEdge ? 'end' : 'start',
            fill: late ? pal.late : pal.milestone,
            'font-size': FONT_SIZE,
            'font-weight': 600,
        }, g, text);
        if (live) {
            s('title', {}, g, `${row.name}: ${longDate(calendar.dayToISO(plan.rows.get(row.id).start))}`);
        }
    }

    /* Draw a task's bar and label. */
    function drawBar(layer, layout, entry, live) {
        const { row, y, height } = entry;
        const placed = plan.rows.get(row.id);
        const { x0, x1 } = barEdges(layout, row);
        const type = usedTypes(row)[0];
        const g = s('g', { class: 'g-clickable', 'data-id': row.id }, layer);
        s('rect', {
            x: x0,
            y: y + BAR_PAD,
            width: x1 - x0,
            height: height - BAR_PAD * 2,
            fill: TEAM_COLORS[type ? type.color : 'grey'] || TEAM_COLORS.grey,
            stroke: placed.overLimit ? BAR_INK.warn : BAR_INK.stroke,
            'stroke-width': placed.overLimit ? 2 : 1,
            'stroke-dasharray': placed.overLimit ? '4 3' : 'none',
        }, g);
        const marks = (placed.overLimit ? '⚠ ' : '') + (row.notBefore ? '⚑ ' : '');
        const candidates = [marks + barLabel(row), S.formatDuration(row.days)];
        const label = candidates.find(text => textWidth(text, BAR_FONT_SIZE) <= x1 - x0 - 8);
        if (label) {
            s('text', {
                x: (x0 + x1) / 2,
                y: y + height / 2 + 5.5,
                'text-anchor': 'middle',
                fill: BAR_INK.text,
                'font-size': BAR_FONT_SIZE,
            }, g, label);
        }
        if (live) {
            const dates = `${shortDate(calendar.dayToISO(placed.start))} – ${shortDate(calendar.dayToISO(placed.end - 1))}`;
            const warning = placed.overLimit ? ' (needs more people than the limit)' : '';
            s('title', {}, g, `${row.name}: ${barLabel(row)}, ${dates}${warning}`);
        }
    }

    /* Draw a group's header band across the chart. */
    function drawGroupBand(layer, layout, pal, entry) {
        s('rect', {
            x: 0, y: entry.y, width: layout.right, height: entry.height, fill: pal.group,
        }, layer);
    }

    /* Draw a group's summary span over its tasks. */
    function drawGroupSummary(layer, layout, pal, entry) {
        const members = chart.rows.filter(
            r => layout.membership.get(r.id) === entry.row.id && r.kind === 'task'
        );
        if (!members.length) return;
        const x0 = Math.min(...members.map(r => barEdges(layout, r).x0));
        const x1 = Math.max(...members.map(r => barEdges(layout, r).x1));
        const mid = entry.y + entry.height / 2;
        s('rect', {
            x: x0, y: mid - 3, width: x1 - x0, height: 6, rx: 1,
            fill: pal.summary,
            'fill-opacity': 0.3,
        }, layer);
    }

    /* Draw the row names down the left of the chart. */
    function drawLabels(layer, layout, pal, live) {
        s('rect', { x: 0, y: 0, width: layout.labelW, height: layout.height, fill: pal.bg }, layer);
        for (const entry of layout.rows) {
            const { row, y, height, indent, index } = entry;
            const isGroup = row.kind === 'group';
            const g = s('g', { class: 'g-row', 'data-index': index, 'data-id': row.id }, layer);
            s('rect', {
                x: 0, y, width: layout.labelW, height,
                fill: isGroup ? pal.group : pal.bg,
                class: 'g-row-bg',
            }, g);
            let x = 8 + indent;
            if (isGroup) {
                if (live) {
                    s('text', {
                        x: 8,
                        y: y + height / 2 + 4,
                        fill: pal.muted,
                        'font-size': 12,
                        class: 'g-chevron',
                    }, g, row.collapsed ? '▸' : '▾');
                }
                x = live ? 24 : 8;
            }
            s('text', {
                x,
                y: y + height / 2 + 4.5,
                fill: pal.fg,
                'font-size': FONT_SIZE,
                'font-weight': isGroup ? 600 : 400,
            }, g, ellipsize(row.name || 'Untitled', layout.labelW - x - 8));
        }
    }

    /* Draw the whole chart into an SVG element. */
    function drawChart(target, layout, pal, live) {
        target.replaceChildren();
        target.setAttribute('width', layout.width);
        target.setAttribute('height', layout.height);
        target.setAttribute('viewBox', `0 0 ${layout.width} ${layout.height}`);
        target.setAttribute('font-family', FONT);
        s('rect', { x: 0, y: 0, width: layout.width, height: layout.height, fill: pal.bg }, target);

        const body = s('g', {}, target);
        for (const entry of layout.rows) {
            if (entry.row.kind === 'group') drawGroupBand(body, layout, pal, entry);
        }
        drawGrid(body, layout, pal);
        // Lines stay visible when a collapsed group hides the milestone's own row.
        for (const row of chart.rows) {
            if (row.kind === 'milestone') drawMilestoneLine(body, layout, pal, row);
        }
        drawDependencies(body, layout, pal);
        for (const entry of layout.rows) {
            if (entry.row.kind === 'group') drawGroupSummary(body, layout, pal, entry);
            if (entry.row.kind === 'task') drawBar(body, layout, entry, live);
        }
        for (const entry of layout.rows) {
            if (entry.row.kind === 'milestone') drawMilestoneMarker(body, layout, pal, entry, live);
        }

        const labels = s('g', { id: 'layer-labels' }, target);
        drawLabels(labels, layout, pal, live);
        const axis = s('g', { id: 'layer-axis' }, target);
        drawAxis(axis, layout, pal);
        const corner = s('g', { id: 'layer-corner' }, target);
        s('rect', { x: 0, y: 0, width: layout.labelW, height: AXIS_H, fill: pal.bg }, corner);
    }

    /* Keep the labels and axis in view while the chart scrolls. */
    function pinHeaders() {
        const { scrollLeft: x, scrollTop: y } = scroller;
        const set = (id, tx, ty) => {
            const layer = document.getElementById(id);
            if (layer) layer.setAttribute('transform', `translate(${tx} ${ty})`);
        };
        set('layer-labels', x, 0);
        set('layer-axis', 0, y);
        set('layer-corner', x, y);
    }

    /* Redraw the on-screen chart. */
    function renderChart() {
        const hasRows = chart.rows.length > 0;
        document.getElementById('empty').hidden = hasRows;
        liveLayout = computeLayout(scroller.clientWidth);
        drawChart(svg, liveLayout, darkQuery.matches ? DARK : LIGHT, true);
        pinHeaders();
    }

    /* Update the staffing steppers. */
    function renderLimits() {
        const container = document.getElementById('limits');
        container.replaceChildren(...chart.types.map(type => {
            /* Change this type's limit by a step. */
            const adjust = delta => {
                type.limit = Math.max(1, type.limit + delta);
                commit();
            };
            return h('div', { class: 'g-limit', title: `Maximum concurrent ${type.name}` },
                h('button', {
                    class: 'g-limit-name',
                    text: type.abbr,
                    style: `background: ${TEAM_COLORS[type.color] || TEAM_COLORS.grey}`,
                    title: 'Edit people types',
                    onclick: openPeople,
                }),
                h('button', {
                    class: 'g-step',
                    text: '−',
                    disabled: type.limit <= 1,
                    'aria-label': `Fewer ${type.name}`,
                    onclick: () => adjust(-1),
                }),
                h('span', { class: 'g-limit-value', text: String(type.limit) }),
                h('button', {
                    class: 'g-step',
                    text: '+',
                    'aria-label': `More ${type.name}`,
                    onclick: () => adjust(1),
                })
            );
        }));
    }

    /* Update the projected end date, milestones and warnings. */
    function renderOutcome() {
        const outcome = document.getElementById('outcome');
        const items = [];
        if (plan.end > 0) {
            items.push(h('span', { class: 'g-end' },
                'Ends ',
                h('strong', { text: longDate(calendar.dayToISO(plan.end - 1)) }),
                ` · ${plan.end} working days`
            ));
        }
        for (const row of chart.rows) {
            if (row.kind !== 'milestone') continue;
            const { text, late } = milestoneText(row);
            items.push(h('span', { class: late ? 'g-chip g-late' : 'g-chip' }, `${row.name}: ${text}`));
        }
        outcome.replaceChildren(...items);

        if (conflicted) return;
        const placed = [...plan.rows.values()];
        const over = placed.filter(p => p.overLimit).length;
        const cyclic = placed.filter(p => p.cyclic).length;
        const notes = [];
        if (over) {
            notes.push(`⚠ ${over} ${over === 1 ? 'task needs' : 'tasks need'} more people than the limit, so ${over === 1 ? 'it runs' : 'they run'} with everyone of that type.`);
        }
        if (cyclic) notes.push(`⚠ ${cyclic} circular ${cyclic === 1 ? 'dependency was' : 'dependencies were'} ignored.`);
        const warning = document.getElementById('warning');
        warning.hidden = !notes.length;
        warning.textContent = notes.join(' ');
    }

    /* Recalculate the schedule and redraw everything derived from it. */
    function refresh() {
        calendar = S.makeCalendar(chart.start, chart.excluded);
        plan = S.schedule(chart, calendar);
        const title = document.getElementById('title');
        if (document.activeElement !== title) title.value = chart.title;
        document.title = `${chart.title} - aeratools`;
        renderLimits();
        renderOutcome();
        renderChart();
    }

    /* ── Dialogs ── */

    /* Fill and open the dialog. */
    function showDialog(title, body, buttons) {
        const form = h('form', {
            method: 'dialog',
            onsubmit: event => {
                event.preventDefault();
                const submit = buttons.find(b => b.primary);
                if (submit) submit.action();
            },
        },
            h('h2', { text: title }),
            body,
            h('div', { class: 'g-dialog-actions' }, ...buttons.map(button => h('button', {
                type: button.primary ? 'submit' : 'button',
                class: `g-btn ${button.primary ? 'g-primary' : ''} ${button.danger ? 'g-danger' : ''}`,
                text: button.text,
                onclick: button.primary ? undefined : button.action,
            })))
        );
        dialog.replaceChildren(form);
        document.getElementById('prefs-popup').classList.remove('open');
        if (!dialog.open) dialog.showModal();
    }

    /* Close the dialog. */
    function closeDialog() {
        dialog.close();
    }

    /* Return a labelled form field. */
    function field(label, control, hint) {
        return h('label', { class: 'g-field' },
            h('span', { class: 'g-field-label', text: label }),
            control,
            hint ? h('span', { class: 'g-hint', text: hint }) : null
        );
    }

    /* Build the checkbox list for choosing a row's dependencies. */
    function dependencyPicker(row) {
        const excluded = row.id ? downstreamOf(row.id) : new Set();
        const chosen = new Set(row.deps || []);
        const list = h('div', { class: 'g-dep-list' });
        const items = [];
        for (const candidate of chart.rows) {
            if (candidate.kind === 'group') {
                items.push({ header: true, node: h('div', { class: 'g-dep-group', text: candidate.name }) });
            } else if (!excluded.has(candidate.id)) {
                const box = h('input', {
                    type: 'checkbox',
                    checked: chosen.has(candidate.id),
                    onchange: () => {
                        if (box.checked) chosen.add(candidate.id);
                        else chosen.delete(candidate.id);
                    },
                });
                items.push({
                    name: candidate.name.toLowerCase(),
                    node: h('label', { class: 'g-dep' }, box, candidate.name || 'Untitled'),
                });
            }
        }
        list.append(...items.map(item => item.node));
        const filter = h('input', {
            type: 'search',
            placeholder: 'Filter tasks',
            'aria-label': 'Filter dependencies',
            oninput: () => {
                const term = filter.value.toLowerCase();
                for (const item of items) item.node.hidden = term !== '' && (item.header || !item.name.includes(term));
            },
            onkeydown: event => {
                if (event.key === 'Enter') event.preventDefault();
            },
        });
        const hasChoices = items.some(item => !item.header);
        const node = h('div', { class: 'g-field' },
            h('span', { class: 'g-field-label', text: 'Starts after' }),
            hasChoices ? filter : null,
            hasChoices ? list : h('span', { class: 'g-hint', text: 'No other tasks to depend on.' })
        );
        return { node, chosen };
    }

    /* Return the row index a new row in the given group should be inserted at. */
    function endOfGroup(groupId) {
        if (!groupId) {
            const firstGroup = chart.rows.findIndex(r => r.kind === 'group');
            return firstGroup === -1 ? chart.rows.length : firstGroup;
        }
        let index = chart.rows.findIndex(r => r.id === groupId) + 1;
        while (index < chart.rows.length && chart.rows[index].kind !== 'group') index++;
        return index;
    }

    /* Open the editor for a task or milestone; a row without an ID is a new one. */
    function openRowEditor(row, defaultGroup) {
        const isNew = !row.id;
        const membership = groupMembership();
        const currentGroup = isNew ? defaultGroup : membership.get(row.id);

        const name = h('input', { type: 'text', value: row.name || '', required: true, maxLength: 200 });
        const kind = h('select', { onchange: () => syncKind() },
            h('option', { value: 'task', text: 'Task' }),
            h('option', { value: 'milestone', text: 'Milestone' })
        );
        kind.value = row.kind;
        const days = h('input', { type: 'text', value: S.formatDuration(row.days || 5), required: true });
        const counts = chart.types.map(type => ({
            type,
            input: h('input', {
                type: 'number', min: 0, max: 99, step: 1,
                value: (row.needs || {})[type.id] || 0,
                'aria-label': `${type.name} needed`,
            }),
        }));
        const label = h('input', { type: 'text', value: row.label || '', placeholder: 'Automatic', maxLength: 80 });
        const notBefore = h('input', { type: 'date', value: row.notBefore || '' });
        const target = h('input', { type: 'date', value: row.target || '' });
        const groups = chart.rows.filter(r => r.kind === 'group');
        const group = h('select', {},
            h('option', { value: '', text: 'No group' }),
            ...groups.map(g => h('option', { value: g.id, text: g.name }))
        );
        group.value = currentGroup || '';
        const deps = dependencyPicker(row);

        const taskFields = h('div', { class: 'g-fields' },
            field('Duration', days, 'Working days, e.g. 3d, 2w or 1w 2d'),
            h('div', { class: 'g-field' },
                h('span', { class: 'g-field-label', text: 'People needed' }),
                h('div', { class: 'g-counts' }, ...counts.map(({ type, input }) => h('label', {},
                    h('span', {
                        class: 'g-swatch',
                        style: `background: ${TEAM_COLORS[type.color] || TEAM_COLORS.grey}`,
                        text: type.abbr,
                    }),
                    input
                )))
            ),
            field('Bar label', label)
        );
        const milestoneFields = h('div', { class: 'g-fields' },
            field('Target date', target, 'Optional; shows how early or late the milestone lands')
        );

        /* Show only the fields for the selected kind. */
        function syncKind() {
            const isTask = kind.value === 'task';
            taskFields.hidden = !isTask;
            milestoneFields.hidden = isTask;
            days.required = isTask;
        }
        syncKind();

        /* Validate the form and apply it to the chart. */
        function save() {
            const parsed = S.parseDuration(days.value);
            if (kind.value === 'task' && parsed === null) {
                days.setCustomValidity('Use a duration such as 3d, 2w or 1w 2d');
                days.reportValidity();
                return;
            }
            const needs = {};
            for (const { type, input } of counts) {
                const count = Math.min(99, Math.max(0, Math.floor(+input.value) || 0));
                if (count) needs[type.id] = count;
            }
            const updated = {
                id: row.id || newId(),
                kind: kind.value,
                name: name.value.trim(),
                deps: [...deps.chosen],
                notBefore: notBefore.value || null,
            };
            if (kind.value === 'task') {
                Object.assign(updated, { days: parsed, needs, label: label.value.trim() || null });
            } else {
                updated.target = target.value || null;
            }
            let index = chart.rows.findIndex(r => r.id === updated.id);
            if (!isNew && (group.value || null) === (currentGroup || null)) {
                chart.rows[index] = updated;
            } else {
                if (!isNew) chart.rows.splice(index, 1);
                index = endOfGroup(group.value || null);
                chart.rows.splice(index, 0, updated);
            }
            closeDialog();
            commit();
        }

        /* Delete this row after confirmation. */
        function remove() {
            if (!confirm(`Delete "${row.name}"?`)) return;
            chart.rows = chart.rows.filter(r => r.id !== row.id);
            for (const other of chart.rows) {
                if (other.deps) other.deps = other.deps.filter(id => id !== row.id);
            }
            closeDialog();
            commit();
        }

        days.addEventListener('input', () => days.setCustomValidity(''));
        const buttons = [];
        if (!isNew) buttons.push({ text: 'Delete', danger: true, action: remove });
        buttons.push(
            { text: 'Cancel', action: closeDialog },
            { text: isNew ? 'Add' : 'Save', primary: true, action: save }
        );
        showDialog(
            isNew ? `New ${row.kind}` : `Edit ${row.kind}`,
            h('div', { class: 'g-fields' },
                field('Name', name),
                field('Type', kind),
                taskFields,
                milestoneFields,
                deps.node,
                field('Not before', notBefore, 'Optional; holds this back until the date'),
                groups.length ? field('Group', group) : null
            ),
            buttons
        );
        name.focus();
    }

    /* Open the editor for a group header; a row without an ID is a new one. */
    function openGroupEditor(row) {
        const isNew = !row.id;
        const name = h('input', { type: 'text', value: row.name || '', required: true, maxLength: 200 });

        /* Apply the form to the chart. */
        function save() {
            if (isNew) {
                chart.rows.push({ id: newId(), kind: 'group', name: name.value.trim(), collapsed: false });
            } else {
                row.name = name.value.trim();
            }
            closeDialog();
            commit();
        }

        const buttons = [];
        if (!isNew) {
            buttons.push(
                {
                    text: 'Delete group',
                    danger: true,
                    action: () => {
                        chart.rows = chart.rows.filter(r => r.id !== row.id);
                        closeDialog();
                        commit();
                    },
                },
                {
                    text: 'Add task here',
                    action: () => openRowEditor(
                        { kind: 'task', name: '', days: 5, needs: {}, deps: [] },
                        row.id
                    ),
                }
            );
        }
        buttons.push(
            { text: 'Cancel', action: closeDialog },
            { text: isNew ? 'Add' : 'Save', primary: true, action: save }
        );
        showDialog(
            isNew ? 'New group' : 'Edit group',
            h('div', { class: 'g-fields' },
                field('Name', name),
                isNew ? null : h('p', { class: 'g-hint', text: 'Deleting a group keeps its tasks.' })
            ),
            buttons
        );
        name.focus();
    }

    /* Open the editor for the types of people. */
    function openPeople() {
        const drafts = chart.types.map(type => ({ ...type }));
        const list = h('div', { class: 'g-people' });

        /* Redraw the editable list of types. */
        function draw() {
            list.replaceChildren(...drafts.map(draft => h('div', { class: 'g-person' },
                h('input', {
                    type: 'text',
                    value: draft.abbr,
                    required: true,
                    maxLength: 8,
                    placeholder: 'Abbr',
                    'aria-label': 'Abbreviation',
                    oninput: event => { draft.abbr = event.target.value; },
                }),
                h('input', {
                    type: 'text',
                    value: draft.name,
                    required: true,
                    maxLength: 80,
                    placeholder: 'Name',
                    'aria-label': 'Name',
                    oninput: event => { draft.name = event.target.value; },
                }),
                (() => {
                    const color = h('select', {
                        'aria-label': 'Colour',
                        onchange: event => { draft.color = event.target.value; },
                    }, ...Object.keys(TEAM_COLORS).map(key => h('option', { value: key, text: key })));
                    color.value = draft.color;
                    return color;
                })(),
                h('button', {
                    type: 'button',
                    class: 'g-btn',
                    'aria-label': `Remove ${draft.name}`,
                    onclick: () => {
                        drafts.splice(drafts.indexOf(draft), 1);
                        draw();
                    },
                }, h('i', { class: 'bi-trash' }))
            )));
        }

        /* Apply the drafts to the chart, removing any deleted type from every task. */
        function save() {
            const kept = new Set(drafts.map(d => d.id));
            for (const row of chart.rows) {
                for (const id of Object.keys(row.needs || {})) {
                    if (!kept.has(id)) delete row.needs[id];
                }
            }
            chart.types = drafts;
            closeDialog();
            commit();
        }

        draw();
        showDialog('People types', h('div', { class: 'g-fields' },
            list,
            h('button', {
                type: 'button',
                class: 'g-btn',
                text: 'Add type',
                onclick: () => {
                    const colors = Object.keys(TEAM_COLORS);
                    drafts.push({
                        id: newId(),
                        abbr: '',
                        name: '',
                        color: colors[drafts.length % colors.length],
                        limit: 1,
                    });
                    draw();
                },
            })
        ), [
            { text: 'Cancel', action: closeDialog },
            { text: 'Save', primary: true, action: save },
        ]);
    }

    /* Open the editor for the chart start and the excluded weeks. */
    function openTimeline() {
        const WEEKS_LISTED = 78;
        const labels = new Map(chart.excluded.map(e => [S.mondayOf(e.week), e.label || '']));
        const start = h('input', { type: 'date', value: chart.start, required: true, onchange: draw });
        const list = h('div', { class: 'g-weeks' });

        /* Redraw the list of weeks from the chart start. */
        function draw() {
            if (!start.value) return;
            const first = Date.parse(`${S.mondayOf(start.value)}T00:00:00Z`);
            const rows = [];
            for (let week = 0; week < WEEKS_LISTED; week++) {
                const iso = new Date(first + week * 7 * 86400000).toISOString().slice(0, 10);
                const text = h('input', {
                    type: 'text',
                    value: labels.get(iso) || '',
                    placeholder: 'Label, e.g. Thanksgiving',
                    disabled: !labels.has(iso),
                    maxLength: 60,
                    'aria-label': `Label for week of ${longDate(iso)}`,
                    oninput: () => labels.set(iso, text.value),
                });
                const box = h('input', {
                    type: 'checkbox',
                    checked: labels.has(iso),
                    onchange: () => {
                        if (box.checked) labels.set(iso, text.value);
                        else labels.delete(iso);
                        text.disabled = !box.checked;
                    },
                });
                rows.push(h('div', { class: 'g-week' },
                    h('label', {}, box, longDate(iso)),
                    text
                ));
            }
            list.replaceChildren(...rows);
        }

        /* Apply the timeline to the chart. */
        function save() {
            chart.start = S.mondayOf(start.value);
            chart.excluded = [...labels].sort().map(([week, label]) => ({ week, label }));
            closeDialog();
            commit();
        }

        draw();
        showDialog('Timeline', h('div', { class: 'g-fields' },
            field('Chart start', start, 'Moves to the Monday of the week you pick'),
            h('div', { class: 'g-field' },
                h('span', { class: 'g-field-label', text: 'Weeks off' }),
                h('span', { class: 'g-hint', text: 'Ticked weeks are skipped by the schedule and collapse on the chart.' }),
                list
            )
        ), [
            { text: 'Cancel', action: closeDialog },
            { text: 'Save', primary: true, action: save },
        ]);
    }

    /* ── Exporting ── */

    /* Return the chart as a standalone SVG string in light colours. */
    function exportSvg() {
        const target = document.createElementNS(SVG_NS, 'svg');
        target.setAttribute('xmlns', SVG_NS);
        const layout = computeLayout(EXPORT_WIDTH);
        drawChart(target, layout, EXPORT, false);
        return {
            text: new XMLSerializer().serializeToString(target),
            width: layout.width,
            height: layout.height,
        };
    }

    /* Prompt the browser to save a blob as a file. */
    function download(blob, extension) {
        const url = URL.createObjectURL(blob);
        const slug = chart.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        const link = h('a', { href: url, download: `${slug || 'gantt'}.${extension}` });
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
    }

    /* Save the chart as an SVG file. */
    function downloadSvg() {
        download(new Blob([exportSvg().text], { type: 'image/svg+xml' }), 'svg');
    }

    /* Save the chart as a double-resolution PNG file. */
    function downloadPng() {
        const { text, width, height } = exportSvg();
        const url = URL.createObjectURL(new Blob([text], { type: 'image/svg+xml' }));
        const image = new Image();
        image.onload = () => {
            const canvas = h('canvas', { width: width * 2, height: height * 2 });
            canvas.getContext('2d').drawImage(image, 0, 0, width * 2, height * 2);
            URL.revokeObjectURL(url);
            canvas.toBlob(blob => download(blob, 'png'), 'image/png');
        };
        image.src = url;
    }

    /* ── Interaction ── */

    /* Open the right editor for a row. */
    function openEditor(row) {
        if (row.kind === 'group') openGroupEditor(row);
        else openRowEditor(row);
    }

    /* Return the chart row with an ID. */
    function rowById(id) {
        return chart.rows.find(r => r.id === id);
    }

    /* Move a row, or a group with its tasks, to before the row at an index. */
    function moveRow(from, before) {
        const row = chart.rows[from];
        let count = 1;
        if (row.kind === 'group') {
            while (from + count < chart.rows.length && chart.rows[from + count].kind !== 'group') count++;
        }
        if (before >= from && before <= from + count) return false;
        const block = chart.rows.splice(from, count);
        let index = before > from ? before - count : before;
        if (row.kind === 'group') {
            // A group can't land inside another, as that would capture its tasks.
            while (index < chart.rows.length && chart.rows[index].kind !== 'group') index++;
        }
        chart.rows.splice(index, 0, ...block);
        return true;
    }

    /* Return the row index a drag at a vertical position would drop before. */
    function dropIndex(pointerY) {
        for (const entry of liveLayout.rows) {
            if (pointerY < entry.y + entry.height / 2) return { index: entry.index, y: entry.y };
        }
        const last = liveLayout.rows[liveLayout.rows.length - 1];
        return { index: chart.rows.length, y: last.y + last.height };
    }

    /* Handle a click on a bar or milestone. */
    svg.addEventListener('click', event => {
        const target = event.target.closest('.g-clickable');
        if (target) openEditor(rowById(target.dataset.id));
    });

    /* Handle a press on a row name, which is a click, a toggle or the start of a drag. */
    svg.addEventListener('pointerdown', event => {
        const rowNode = event.target.closest('.g-row');
        if (!rowNode || event.button !== 0) return;
        const from = +rowNode.dataset.index;
        const row = chart.rows[from];
        const onChevron = event.target.classList.contains('g-chevron');
        const startY = event.clientY;
        let dragging = false;
        let indicator = null;

        /* Return the pointer's vertical position within the chart. */
        const chartY = moveEvent => moveEvent.clientY - svg.getBoundingClientRect().top;

        /* Track the drag and show where the row would land. */
        const onMove = moveEvent => {
            if (!dragging && Math.abs(moveEvent.clientY - startY) < 5) return;
            dragging = true;
            const { y } = dropIndex(chartY(moveEvent));
            if (!indicator) {
                indicator = s('line', {
                    x1: 0, x2: liveLayout.right,
                    stroke: (darkQuery.matches ? DARK : LIGHT).milestone,
                    'stroke-width': 2,
                }, svg);
            }
            indicator.setAttribute('y1', y);
            indicator.setAttribute('y2', y);
        };

        /* Stop tracking the press. */
        const stopTracking = () => {
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
            window.removeEventListener('pointercancel', stopTracking);
            if (indicator) indicator.remove();
        };

        /* Finish the press, as a drop if the pointer moved or a click if it didn't. */
        const onUp = upEvent => {
            stopTracking();
            if (dragging) {
                if (moveRow(from, dropIndex(chartY(upEvent)).index)) commit();
            } else if (onChevron) {
                row.collapsed = !row.collapsed;
                commit();
            } else {
                openEditor(row);
            }
        };

        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
        window.addEventListener('pointercancel', stopTracking);
    });

    scroller.addEventListener('scroll', pinHeaders);
    new ResizeObserver(() => {
        if (plan) renderChart();
    }).observe(scroller);
    darkQuery.addEventListener('change', renderChart);
    window.addEventListener('beforeunload', event => {
        if (dirty || saving) event.preventDefault();
    });

    document.getElementById('title').addEventListener('input', event => {
        chart.title = event.target.value;
        document.title = `${chart.title} - aeratools`;
        rememberChart();
        queueSave();
    });
    document.getElementById('add-task').addEventListener('click', () => {
        const groups = chart.rows.filter(r => r.kind === 'group');
        const last = groups[groups.length - 1];
        openRowEditor({ kind: 'task', name: '', days: 5, needs: {}, deps: [] }, last ? last.id : null);
    });
    document.getElementById('add-milestone').addEventListener('click', () => {
        const groups = chart.rows.filter(r => r.kind === 'group');
        const last = groups[groups.length - 1];
        openRowEditor({ kind: 'milestone', name: '', deps: [] }, last ? last.id : null);
    });
    document.getElementById('add-group').addEventListener('click', () => openGroupEditor({ kind: 'group' }));
    document.getElementById('open-people').addEventListener('click', openPeople);
    document.getElementById('open-timeline').addEventListener('click', openTimeline);
    document.getElementById('export-svg').addEventListener('click', downloadSvg);
    document.getElementById('export-png').addEventListener('click', downloadPng);

    rememberChart();
    refresh();
})();
