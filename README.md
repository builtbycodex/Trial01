# PingBadge

Free uptime badges and public status pages for small projects.

PingBadge is the first product from the Built by Codex autonomy experiment. It runs
with Python's standard library and SQLite, so it can be hosted on a USD 0.00
infrastructure budget.

## What It Does

- Creates a monitor for any public HTTP(S) URL.
- Checks monitored URLs on a schedule.
- Shows a public status page with recent checks and uptime.
- Serves an embeddable SVG badge.

## Public Launch Status

The app is deployed on the Ubuntu server and listening on port 80. The expected
public URL is:

`http://79.76.49.242/`

Launch verified: the app responds publicly on TCP port 80.

## Run Locally

```sh
python3 app.py
```

Then open `http://127.0.0.1:8000`.

Configuration is via environment variables:

- `PINGBADGE_HOST` defaults to `127.0.0.1`
- `PINGBADGE_PORT` defaults to `8000`
- `PINGBADGE_DB` defaults to `data/pingbadge.sqlite3`
- `PINGBADGE_CHECK_INTERVAL` defaults to `300`

## Deployment

The app is designed to run directly on the provided Ubuntu server with systemd:

```sh
sudo systemctl status pingbadge
```

No paid services are required.
