# aeratools

A collection of single-purpose HTML tools, lightweight and with very minimal dependencies.

## Architecture

Each tool is a Docker container, that serves HTTP on port 80, with its application assumed to live at the root of the HTTP path. They're meant to be served one-per-domain.

Tools should persist their state in one of two ways:

- In the HTTP path, for simple/insecure tools
- In an S3 compatible object store, for more complex tools

There are no logins; if a tool persists private data, it should do so via a long unique token encoded in the URL that points to a document in the object store, such that knowing the URL lets you access the item.

A small number of global settings can be persisted as cookies on the top-level domain common to all the tools; for example colour scheme/theme and unit preferences.

Each container should expect the following as environment variables:

- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, auth tokens for the object store
- `S3_ENDPOINT_URL`, the endpoint for the object store
- `S3_BUCKET`. the bucket to store things in
- `ROOT_DOMAIN`, the root domain to use for preference cookies

## Design

Every tool should be designed to fill the window if it's less than 1000 pixels wide, and to limit itself to that width if it's wider.

Tools are likely to be embedded in other pages (e.g. via the Dashboard tool), so that needs to be borne in mind.

Any configuration options for a tool should be set in a popup dialog that opens from a small cog item in the upper right corner, and should persist in the query string of the page if there's no server-side component.
