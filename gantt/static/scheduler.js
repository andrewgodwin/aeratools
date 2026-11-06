/*
 * Calendar and resource-constrained scheduling for Gantt charts.
 *
 * Everything is scheduled in "working days": integers counting Monday-to-Friday days
 * from the chart start, with excluded weeks absent altogether. A task with start 0 and
 * end 5 occupies the whole first working week; end is exclusive.
 */
(function (root) {
    'use strict';

    const DAY_MS = 86400000;
    const WEEK_DAYS = 5;
    const MAX_DAYS = 2600; // Ten years; bounds durations and "not before" dates.

    /* Parse a YYYY-MM-DD string to UTC milliseconds. */
    function parseISO(iso) {
        return Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
    }

    /* Format UTC milliseconds as a YYYY-MM-DD string. */
    function toISO(ms) {
        return new Date(ms).toISOString().slice(0, 10);
    }

    /* Return the Monday on or before an ISO date. */
    function mondayOf(iso) {
        const ms = parseISO(iso);
        return toISO(ms - ((new Date(ms).getUTCDay() + 6) % 7) * DAY_MS);
    }

    /* Build the mapping between working days and calendar dates. */
    function makeCalendar(start, excluded) {
        const skip = new Map(excluded.map(e => [mondayOf(e.week), e.label || '']));
        const mondays = [];
        const gaps = new Map();
        let cursor = parseISO(mondayOf(start));

        /* Ensure working weeks up to index i are known. */
        function extend(i) {
            while (mondays.length <= i) {
                const labels = [];
                let weeks = 0;
                while (skip.has(toISO(cursor))) {
                    const label = skip.get(toISO(cursor));
                    if (label && !labels.includes(label)) labels.push(label);
                    weeks++;
                    cursor += 7 * DAY_MS;
                }
                if (weeks) gaps.set(mondays.length, { label: labels.join(' / '), weeks });
                mondays.push(cursor);
                cursor += 7 * DAY_MS;
            }
        }

        /* Return the UTC milliseconds of the Monday of working week i. */
        function weekStart(i) {
            extend(i);
            return mondays[i];
        }

        /* Return the ISO date of a working day. */
        function dayToISO(day) {
            const week = Math.floor(day / WEEK_DAYS);
            return toISO(weekStart(week) + (day - week * WEEK_DAYS) * DAY_MS);
        }

        /* Return the first working day on or after an ISO date. */
        function isoToDay(iso) {
            const target = parseISO(iso);
            for (let week = 0; week * WEEK_DAYS < MAX_DAYS; week++) {
                const monday = weekStart(week);
                if (target < monday) return week * WEEK_DAYS;
                const offset = Math.round((target - monday) / DAY_MS);
                if (offset < WEEK_DAYS) return week * WEEK_DAYS + offset;
            }
            return MAX_DAYS;
        }

        /* Return the excluded-weeks gap before working week i, if there is one. */
        function gapBefore(i) {
            extend(i);
            return gaps.get(i) || null;
        }

        return { weekStart, dayToISO, isoToDay, gapBefore };
    }

    /* Return each schedulable row's in-chart dependencies, with cycles broken. */
    function resolveDependencies(tasks) {
        const known = new Set(tasks.map(t => t.id));
        const deps = new Map(tasks.map(t => [
            t.id,
            new Set((t.deps || []).filter(id => known.has(id) && id !== t.id)),
        ]));
        const successors = new Map(tasks.map(t => [t.id, []]));
        for (const [id, preds] of deps) {
            for (const pred of preds) successors.get(pred).push(id);
        }
        const waiting = new Map(tasks.map(t => [t.id, deps.get(t.id).size]));
        const ordered = [];
        const cyclic = new Set();
        const pending = new Set(tasks.map(t => t.id));

        /* Move every task with no unmet dependencies into the ordering. */
        function drain() {
            let progressed = true;
            while (progressed) {
                progressed = false;
                for (const id of pending) {
                    if (waiting.get(id) === 0) {
                        pending.delete(id);
                        ordered.push(id);
                        for (const next of successors.get(id)) {
                            waiting.set(next, waiting.get(next) - 1);
                        }
                        progressed = true;
                    }
                }
            }
        }

        drain();
        while (pending.size) {
            // Only a cycle can leave tasks stuck; drop the first stuck task's unmet deps.
            const id = pending.values().next().value;
            cyclic.add(id);
            for (const pred of [...deps.get(id)]) {
                if (pending.has(pred)) {
                    deps.get(id).delete(pred);
                    successors.set(pred, successors.get(pred).filter(s => s !== id));
                }
            }
            waiting.set(id, 0);
            drain();
        }
        return { deps, successors, ordered, cyclic };
    }

    /*
     * Schedule a chart, returning {rows: Map(id -> {start, end, overLimit, cyclic}), end}.
     *
     * Tasks are placed one at a time at their earliest slot with enough free staff,
     * longest remaining chain of work first and then in row order. A task needing more
     * of a type than the limit allows takes the whole limit instead, and is flagged.
     */
    function schedule(chart, calendar) {
        const tasks = chart.rows.filter(r => r.kind !== 'group');
        const { deps, successors, ordered, cyclic } = resolveDependencies(tasks);
        const byId = new Map(tasks.map(t => [t.id, t]));
        const rowOrder = new Map(tasks.map((t, i) => [t.id, i]));
        const limits = new Map(chart.types.map(t => [t.id, Math.max(1, t.limit)]));

        /* Return how many days a row runs for. */
        const duration = task => (task.kind === 'milestone' ? 0 : task.days);

        const tail = new Map();
        for (const id of [...ordered].reverse()) {
            const rest = successors.get(id).map(next => tail.get(next));
            tail.set(id, duration(byId.get(id)) + Math.max(0, ...rest));
        }

        const usage = new Map(chart.types.map(t => [t.id, []]));
        const rows = new Map();
        const unplaced = new Set(tasks.map(t => t.id));
        let end = 0;

        /* Return the effective staffing of a task, clamped to the limits. */
        function staffing(task) {
            const needs = [];
            let overLimit = false;
            if (task.kind === 'task') {
                for (const [type, count] of Object.entries(task.needs || {})) {
                    if (!limits.has(type) || count <= 0) continue;
                    if (count > limits.get(type)) overLimit = true;
                    needs.push([type, Math.min(count, limits.get(type))]);
                }
            }
            return { needs, overLimit };
        }

        /* Return the last day in a range with too few staff, or -1 if there is none. */
        function lastClash(needs, from, to) {
            for (let day = to - 1; day >= from; day--) {
                for (const [type, count] of needs) {
                    if ((usage.get(type)[day] || 0) + count > limits.get(type)) return day;
                }
            }
            return -1;
        }

        while (unplaced.size) {
            let id = null;
            for (const candidate of unplaced) {
                if ([...deps.get(candidate)].some(pred => unplaced.has(pred))) continue;
                if (
                    id === null ||
                    tail.get(candidate) > tail.get(id) ||
                    (tail.get(candidate) === tail.get(id) &&
                        rowOrder.get(candidate) < rowOrder.get(id))
                ) {
                    id = candidate;
                }
            }
            const task = byId.get(id);
            const { needs, overLimit } = staffing(task);
            const days = duration(task);
            let start = task.notBefore ? calendar.isoToDay(task.notBefore) : 0;
            for (const pred of deps.get(id)) start = Math.max(start, rows.get(pred).end);
            for (let clash; (clash = lastClash(needs, start, start + days)) >= 0;) {
                start = clash + 1;
            }
            for (const [type, count] of needs) {
                const profile = usage.get(type);
                for (let day = start; day < start + days; day++) {
                    profile[day] = (profile[day] || 0) + count;
                }
            }
            rows.set(id, { start, end: start + days, overLimit, cyclic: cyclic.has(id) });
            end = Math.max(end, start + days);
            unplaced.delete(id);
        }
        return { rows, end };
    }

    /* Parse a duration such as "2w", "3d", "1w 2d" or "4" into working days, or null. */
    function parseDuration(text) {
        const match = /^\s*(?:(\d+)\s*w(?:ee)?k?s?)?\s*(?:(\d+)\s*d?(?:ays?)?)?\s*$/i.exec(text);
        if (!match || (match[1] === undefined && match[2] === undefined)) return null;
        const days = (+match[1] || 0) * WEEK_DAYS + (+match[2] || 0);
        return days >= 1 && days <= MAX_DAYS ? days : null;
    }

    /* Format a number of working days as a compact duration. */
    function formatDuration(days) {
        return days % WEEK_DAYS === 0 ? `${days / WEEK_DAYS}w` : `${days}d`;
    }

    root.GanttSchedule = {
        WEEK_DAYS,
        makeCalendar,
        mondayOf,
        schedule,
        parseDuration,
        formatDuration,
    };
})(window);
