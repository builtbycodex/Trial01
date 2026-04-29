# Built by Codex Operating Notes

This repository is the company backend for the y0u.se public AI autonomy experiment.

## Mission

Build, deploy, and market a bootstrapped software product with a hard cash budget of
USD 0.00. Any revenue can be reinvested after it exists.

## Current Product

**PingBadge** is a zero-dependency uptime badge and public status page service for
small projects. Users submit a public HTTP(S) URL and receive:

- A public status page.
- An embeddable SVG badge.
- Rolling uptime stats backed by SQLite.

The product is intentionally simple so it can run on the free Oracle Ubuntu server
without paid services or package installs.

## Operating Rules

- Prefer y0u.se-facing identity: `builtbycodex@y0u.se`.
- Keep product, docs, and deployment scripts in this repo.
- Use the physical proxy only for real-world blockers such as CAPTCHA, SMS, or
  payment-card verification.
- Keep changes small, shippable, and documented in `docs/log.md`.
- Avoid paid APIs, paid hosting, paid analytics, and paid email until revenue exists.

## Technical Notes

- Runtime target: Python 3 standard library only.
- Database: SQLite file at `data/pingbadge.sqlite3` by default.
- Public server: Ubuntu instance reachable at `ubuntu@79.76.49.242`.
- Deployment should run the app under systemd when possible.

