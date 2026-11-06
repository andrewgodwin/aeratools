# Gantt

Build Gantt charts with dependencies and staffing needs, then change how many people of
each type can work at once and watch the schedule and end date reproject.

The chart needs the room, so this tool fills the window rather than limiting itself to
the usual 1000 pixels.

## Charts

Each chart lives at a long random token URL, with no login. Anyone who has the URL can
edit it. Charts are stored as `{rev, chart}` in the object store under the `__gantt__`
namespace; saves carry the `rev` they were based on, and are refused if it is outdated.

## Scheduling

Scheduling runs in the browser (`static/scheduler.js`), so changing a limit is instant.
It works in working days, Monday to Friday, with excluded weeks removed altogether.

- Tasks have a fixed duration and hold their people for all of it. More people let more
  tasks run at once, but never shorten a task.
- Dependencies are finish-to-start.
- Tasks are placed one at a time at the earliest slot with enough free staff, longest
  remaining chain of work first, then in row order. This is a heuristic: it is usually
  close to the best schedule but isn't guaranteed to be, and in rare cases adding a
  person can push an end date back.
- A task needing more people than the limit takes all of that type instead, and is
  flagged, so an end date is always available.
- A "not before" date holds a task back. Milestones take no time or people, and land on
  the next working day after their dependencies finish.
