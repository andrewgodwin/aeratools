# dashboard

A configurable dashboard that displays URLs in iframes arranged in three areas: a full-width header, a left column, and a right column.

## Configuration

Click the gear icon (top-right) to open the config panel. Each of the three areas (Header, Left Column, Right Column) can have zero or more entries. Each entry has:

- **URL** — the page to embed
- **Height** — the iframe height in pixels

Click **Apply** to save and render the layout. Configuration is stored in the page's query string (`?config=...`) as base64-encoded JSON, so the URL is shareable and bookmarkable.

## Layout

```
┌─────────────────────────────────┐
│           Header iframes        │
│         (stacked, full width)   │
├─────────────────┬───────────────┤
│  Left column    │  Right column │
│  (stacked)      │  (stacked)    │
└─────────────────┴───────────────┘
```

Areas with no entries are hidden. If only header entries exist, the two-column section is not shown.
