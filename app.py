#!/usr/bin/env python3
from __future__ import annotations

import html
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import ssl
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


APP_NAME = "PingBadge"
HOST = os.environ.get("PINGBADGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("PINGBADGE_PORT", "8000"))
DB_PATH = Path(os.environ.get("PINGBADGE_DB", "data/pingbadge.sqlite3"))
CHECK_INTERVAL_SECONDS = int(os.environ.get("PINGBADGE_CHECK_INTERVAL", "300"))
CHECK_TIMEOUT_SECONDS = float(os.environ.get("PINGBADGE_CHECK_TIMEOUT", "8"))
USER_AGENT = "PingBadge/0.1 (+https://github.com/builtbycodex/Trial01)"
PUBLIC_ORIGIN = os.environ.get("PINGBADGE_PUBLIC_ORIGIN", "").rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


NO_REDIRECT_OPENER = build_opener(NoRedirect, HTTPSHandler(context=ssl.create_default_context()))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(db()) as conn:
        conn.executescript(
            """
            pragma journal_mode = wal;

            create table if not exists monitors (
                id integer primary key autoincrement,
                slug text not null unique,
                token text not null unique,
                target_url text not null,
                display_name text not null,
                contact_email text,
                created_at text not null,
                last_checked_at text,
                last_ok integer,
                last_status_code integer,
                last_latency_ms integer,
                last_error text
            );

            create table if not exists checks (
                id integer primary key autoincrement,
                monitor_id integer not null references monitors(id) on delete cascade,
                checked_at text not null,
                ok integer not null,
                status_code integer,
                latency_ms integer,
                error text
            );

            create index if not exists idx_checks_monitor_time
            on checks(monitor_id, checked_at desc);
            """
        )
        conn.commit()


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def page(title: str, body: str, status: int = 200) -> tuple[int, str, str]:
    return (
        status,
        "text/html; charset=utf-8",
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} | {APP_NAME}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17211b;
      --muted: #647067;
      --line: #d9e1da;
      --paper: #fbfcf8;
      --panel: #ffffff;
      --ok: #147a45;
      --bad: #b42318;
      --warn: #a15c07;
      --accent: #2454a6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 16px/1.5 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--paper);
    }}
    header, main, footer {{ max-width: 980px; margin: 0 auto; padding: 22px; }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
    a {{ color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 3px; }}
    .brand {{ color: var(--ink); font-weight: 800; text-decoration: none; letter-spacing: 0; }}
    .hero {{ display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(280px, .9fr); gap: 28px; align-items: start; padding-top: 24px; }}
    h1 {{ font-size: clamp(2rem, 4vw, 4.4rem); line-height: .98; margin: 0 0 18px; letter-spacing: 0; }}
    h2 {{ font-size: 1.35rem; margin: 0 0 12px; }}
    p {{ margin: 0 0 16px; color: var(--muted); }}
    .panel, .status-panel, .metric, .check {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 0 rgba(23, 33, 27, .04);
    }}
    .panel {{ padding: 18px; }}
    label {{ display: block; font-weight: 700; margin: 12px 0 6px; }}
    input {{
      width: 100%;
      border: 1px solid #b9c5bc;
      border-radius: 6px;
      padding: 11px 12px;
      font: inherit;
      background: #fff;
    }}
    button, .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      border: 0;
      border-radius: 6px;
      background: var(--ink);
      color: white;
      padding: 0 16px;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
      text-decoration: none;
    }}
    .button.secondary {{ background: #eef2ef; color: var(--ink); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }}
    .fineprint {{ font-size: .9rem; color: var(--muted); margin-top: 10px; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
    .metric {{ padding: 14px; }}
    .metric b {{ display: block; font-size: 1.45rem; }}
    .status-row {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 14px 0; }}
    .pill {{ display: inline-flex; align-items: center; min-height: 30px; padding: 0 10px; border-radius: 999px; font-weight: 800; }}
    .up {{ background: #dff7e9; color: var(--ok); }}
    .down {{ background: #ffe8e4; color: var(--bad); }}
    .unknown {{ background: #fff2d8; color: var(--warn); }}
    code {{ overflow-wrap: anywhere; background: #eef2ef; padding: 2px 5px; border-radius: 4px; }}
    .checks {{ display: grid; gap: 8px; margin-top: 14px; }}
    .check {{ display: grid; grid-template-columns: 130px 88px minmax(0, 1fr) 88px; gap: 10px; padding: 10px; align-items: center; }}
    .muted {{ color: var(--muted); }}
    .error {{ color: var(--bad); font-weight: 700; }}
    footer {{ color: var(--muted); font-size: .9rem; }}
    @media (max-width: 760px) {{
      header {{ align-items: flex-start; flex-direction: column; }}
      .hero, .grid {{ grid-template-columns: 1fr; }}
      .check {{ grid-template-columns: 1fr; gap: 4px; }}
    }}
  </style>
</head>
<body>
  <header>
    <a class="brand" href="/">{APP_NAME}</a>
    <nav><a href="/trust">Trust</a> &nbsp; <a href="https://github.com/builtbycodex/Trial01">GitHub</a></nav>
  </header>
  <main>{body}</main>
  <footer>Built by Codex, an AI autonomy experiment sponsored by y0u.se.</footer>
</body>
</html>""",
    )


def public_origin(headers: Any) -> str:
    if PUBLIC_ORIGIN:
        return PUBLIC_ORIGIN
    host = headers.get("Host") or f"127.0.0.1:{PORT}"
    scheme = headers.get("X-Forwarded-Proto") or "http"
    return f"{scheme}://{host}"


def get_client_ip(headers: Any, fallback: str) -> str:
    forwarded = headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return fallback


def normalize_target(raw_url: str) -> tuple[str | None, str | None]:
    raw_url = raw_url.strip()
    if len(raw_url) > 500:
        return None, "URL is too long."
    parsed = urlparse(raw_url)
    if not parsed.scheme:
        raw_url = "https://" + raw_url
        parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        return None, "Only http and https URLs are supported."
    if not parsed.hostname:
        return None, "Enter a URL with a hostname."
    if parsed.username or parsed.password:
        return None, "URLs with usernames or passwords are not allowed."
    if parsed.port and parsed.port not in {80, 443, 8080, 8443}:
        return None, "Only ports 80, 443, 8080, and 8443 are allowed."
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return None, "Hostname could not be resolved."
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global:
            return None, "Only public internet targets are allowed."
    path = parsed.path or "/"
    netloc = parsed.hostname.lower()
    if parsed.port:
        netloc += f":{parsed.port}"
    normalized = parsed._replace(netloc=netloc, path=path, params="", fragment="").geturl()
    return normalized, None


def display_name_for(url: str, provided: str) -> str:
    provided = " ".join(provided.strip().split())
    if provided:
        return provided[:80]
    host = urlparse(url).hostname or "Monitor"
    return host[:80]


def make_slug(display_name: str) -> str:
    stem = "".join(ch.lower() if ch.isalnum() else "-" for ch in display_name).strip("-")
    stem = "-".join(part for part in stem.split("-") if part)[:34] or "monitor"
    suffix = secrets.token_hex(3)
    return f"{stem}-{suffix}"


def create_monitor(target_url: str, display_name: str, contact_email: str) -> sqlite3.Row:
    slug = make_slug(display_name)
    token = secrets.token_urlsafe(18)
    with closing(db()) as conn:
        conn.execute(
            """
            insert into monitors
            (slug, token, target_url, display_name, contact_email, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (slug, token, target_url, display_name, contact_email.strip()[:160] or None, iso_now()),
        )
        conn.commit()
        row = conn.execute("select * from monitors where slug = ?", (slug,)).fetchone()
        assert row is not None
        return row


def list_monitors_due(limit: int = 20) -> list[sqlite3.Row]:
    threshold = utcnow() - timedelta(seconds=CHECK_INTERVAL_SECONDS)
    with closing(db()) as conn:
        rows = conn.execute(
            """
            select * from monitors
            where last_checked_at is null or last_checked_at < ?
            order by coalesce(last_checked_at, '') asc
            limit ?
            """,
            (threshold.isoformat(timespec="seconds"), limit),
        ).fetchall()
        return list(rows)


def get_monitor(slug: str) -> sqlite3.Row | None:
    with closing(db()) as conn:
        return conn.execute("select * from monitors where slug = ?", (slug,)).fetchone()


def status_label(row: sqlite3.Row) -> tuple[str, str]:
    if row["last_checked_at"] is None:
        return "unknown", "Pending"
    if row["last_ok"]:
        return "up", "Up"
    return "down", "Down"


def check_target(row: sqlite3.Row) -> None:
    started = time.monotonic()
    status_code = None
    error = None
    ok = False
    try:
        normalized, validation_error = normalize_target(row["target_url"])
        if validation_error or not normalized:
            raise ValueError(validation_error or "Invalid target.")
        req = Request(normalized, method="GET", headers={"User-Agent": USER_AGENT})
        with NO_REDIRECT_OPENER.open(req, timeout=CHECK_TIMEOUT_SECONDS) as response:
            status_code = response.getcode()
            response.read(4096)
        ok = 200 <= int(status_code) < 400
    except HTTPError as exc:
        status_code = exc.code
        ok = 200 <= int(status_code) < 400
        error = f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        error = str(exc)[:240]
    latency_ms = int((time.monotonic() - started) * 1000)
    checked_at = iso_now()
    with closing(db()) as conn:
        conn.execute(
            """
            insert into checks (monitor_id, checked_at, ok, status_code, latency_ms, error)
            values (?, ?, ?, ?, ?, ?)
            """,
            (row["id"], checked_at, 1 if ok else 0, status_code, latency_ms, error),
        )
        conn.execute(
            """
            update monitors
            set last_checked_at = ?, last_ok = ?, last_status_code = ?,
                last_latency_ms = ?, last_error = ?
            where id = ?
            """,
            (checked_at, 1 if ok else 0, status_code, latency_ms, error, row["id"]),
        )
        conn.execute(
            """
            delete from checks
            where id in (
                select id from checks
                where monitor_id = ?
                order by checked_at desc
                limit -1 offset 500
            )
            """,
            (row["id"],),
        )
        conn.commit()


def scheduler() -> None:
    while True:
        for row in list_monitors_due():
            check_target(row)
        time.sleep(max(10, min(CHECK_INTERVAL_SECONDS, 60)))


def uptime_stats(monitor_id: int) -> dict[str, tuple[int, int, float | None]]:
    windows = {"24h": 1, "7d": 7, "30d": 30}
    result: dict[str, tuple[int, int, float | None]] = {}
    with closing(db()) as conn:
        for label, days in windows.items():
            since = (utcnow() - timedelta(days=days)).isoformat(timespec="seconds")
            row = conn.execute(
                "select count(*) as total, sum(ok) as ok from checks where monitor_id = ? and checked_at >= ?",
                (monitor_id, since),
            ).fetchone()
            total = int(row["total"] or 0)
            ok_count = int(row["ok"] or 0)
            pct = (ok_count / total * 100) if total else None
            result[label] = (ok_count, total, pct)
    return result


def recent_checks(monitor_id: int, limit: int = 40) -> list[sqlite3.Row]:
    with closing(db()) as conn:
        return list(
            conn.execute(
                """
                select * from checks
                where monitor_id = ?
                order by checked_at desc
                limit ?
                """,
                (monitor_id, limit),
            ).fetchall()
        )


def pct_value(stats: dict[str, tuple[int, int, float | None]], key: str) -> float | None:
    return stats[key][2]


def monitor_payload(row: sqlite3.Row, origin: str) -> dict[str, Any]:
    cls, label = status_label(row)
    stats = uptime_stats(row["id"])
    checks = recent_checks(row["id"], 12)
    return {
        "slug": row["slug"],
        "name": row["display_name"],
        "target_url": row["target_url"],
        "status": cls,
        "status_label": label,
        "status_page_url": f"{origin}/m/{quote(row['slug'])}",
        "badge_url": f"{origin}/badge/{quote(row['slug'])}",
        "last_checked_at": row["last_checked_at"],
        "last_ok": bool(row["last_ok"]) if row["last_checked_at"] else None,
        "last_status_code": row["last_status_code"],
        "last_latency_ms": row["last_latency_ms"],
        "uptime": {
            "24h": pct_value(stats, "24h"),
            "7d": pct_value(stats, "7d"),
            "30d": pct_value(stats, "30d"),
        },
        "recent_checks": [
            {
                "checked_at": check["checked_at"],
                "ok": bool(check["ok"]),
                "status_code": check["status_code"],
                "latency_ms": check["latency_ms"],
                "error": check["error"],
            }
            for check in checks
        ],
    }


def json_document(data: Any) -> tuple[int, str, str]:
    return 200, "application/json; charset=utf-8", json.dumps(data, indent=2, sort_keys=True)


def text_document(body: str, content_type: str = "text/plain; charset=utf-8") -> tuple[int, str, str]:
    return 200, content_type, body


def trust_page() -> tuple[int, str, str]:
    return page(
        "Trust",
        """
<section class="panel">
  <h1>Trust</h1>
  <p>PingBadge monitors public HTTP and HTTPS URLs and publishes public uptime pages. It is built for low-stakes public projects, open-source demos, and experiments.</p>
  <h2>Data</h2>
  <p>Monitor URLs, display names, optional contact emails, check timestamps, HTTP status codes, latency, and short error messages are stored in SQLite on the service host.</p>
  <h2>Limits</h2>
  <p>Private network, localhost, credentialed URLs, and unusual ports are blocked. Creation is rate-limited globally while the service is young.</p>
  <h2>Contact</h2>
  <p>Email <a href="mailto:builtbycodex@y0u.se">builtbycodex@y0u.se</a> for removal requests, bug reports, or abuse reports.</p>
</section>
""",
    )


def privacy_page() -> tuple[int, str, str]:
    return page(
        "Privacy",
        """
<section class="panel">
  <h1>Privacy</h1>
  <p>PingBadge is public by design. Do not submit secrets, private URLs, or URLs that expose sensitive operational information.</p>
  <p>Optional contact emails are used only to understand who owns a monitor or to respond to abuse and removal requests. There is no paid analytics, advertising tracker, or mailing list.</p>
  <p>Server logs may include IP addresses and requested paths for operational debugging.</p>
</section>
""",
    )


def landing(error: str = "") -> tuple[int, str, str]:
    with closing(db()) as conn:
        monitors = conn.execute(
            "select * from monitors order by created_at desc limit 8"
        ).fetchall()
    recent = ""
    if monitors:
        recent_items = []
        for row in monitors:
            cls, label = status_label(row)
            recent_items.append(
                f"""<div class="check">
  <span class="pill {cls}">{esc(label)}</span>
  <a href="/m/{esc(row['slug'])}">{esc(row['display_name'])}</a>
  <span class="muted">{esc(row['target_url'])}</span>
  <span class="muted">{esc(row['last_latency_ms'] or '-')} ms</span>
</div>"""
            )
        recent = f"<section><h2>Recent monitors</h2><div class=\"checks\">{''.join(recent_items)}</div></section>"
    error_html = f"<p class=\"error\">{esc(error)}</p>" if error else ""
    return page(
        "Free uptime badges",
        f"""
<section class="hero">
  <div>
    <h1>Free uptime badges for public projects.</h1>
    <p>Create a monitor, share a status page, and embed a live SVG badge. Built on a zero-dollar stack by an autonomous AI founder.</p>
    <div class="actions">
      <a class="button secondary" href="/m/pingbadge-d881c6">Service status</a>
      <a class="button secondary" href="https://github.com/builtbycodex/Trial01">View the build log</a>
    </div>
  </div>
  <form class="panel" method="post" action="/monitors">
    <h2>Create a monitor</h2>
    {error_html}
    <label for="target_url">Public URL</label>
    <input id="target_url" name="target_url" required placeholder="https://example.com">
    <label for="display_name">Display name</label>
    <input id="display_name" name="display_name" placeholder="Example status">
    <label for="contact_email">Contact email</label>
    <input id="contact_email" name="contact_email" type="email" placeholder="optional">
    <button type="submit" style="margin-top:14px;width:100%">Create status page</button>
    <p class="fineprint">Only public HTTP(S) targets are accepted. Private network and localhost targets are blocked.</p>
  </form>
</section>
{recent}
""",
    )


def monitor_page(row: sqlite3.Row, origin: str, manage_token: str = "") -> tuple[int, str, str]:
    cls, label = status_label(row)
    badge_url = f"{origin}/badge/{quote(row['slug'])}"
    page_url = f"{origin}/m/{quote(row['slug'])}"
    stats = uptime_stats(row["id"])
    checks = recent_checks(row["id"])
    metric_html = []
    for label_text, (_ok, total, pct) in stats.items():
        value = "Pending" if pct is None else f"{pct:.1f}%"
        metric_html.append(f"<div class=\"metric\"><b>{esc(value)}</b><span>{esc(label_text)} uptime</span><br><span class=\"muted\">{total} checks</span></div>")
    check_html = []
    for check in checks:
        check_cls = "up" if check["ok"] else "down"
        check_label = "Up" if check["ok"] else "Down"
        details = f"HTTP {check['status_code']}" if check["status_code"] else esc(check["error"] or "No response")
        check_html.append(
            f"""<div class="check">
  <span class="muted">{esc(check['checked_at'][:16].replace('T', ' '))}</span>
  <span class="pill {check_cls}">{check_label}</span>
  <span>{details}</span>
  <span class="muted">{esc(check['latency_ms'])} ms</span>
</div>"""
        )
    if not check_html:
        check_html.append("<p class=\"muted\">The first check is queued.</p>")
    manage = ""
    if manage_token and secrets.compare_digest(manage_token, row["token"]):
        manage = f"""
<section class="panel">
  <h2>Owner links</h2>
  <p>Keep this URL private. It lets you trigger a manual check.</p>
  <form method="post" action="/m/{esc(row['slug'])}/check?token={esc(row['token'])}">
    <button type="submit">Run check now</button>
  </form>
</section>"""
    return page(
        row["display_name"],
        f"""
<section class="status-panel panel">
  <h1>{esc(row['display_name'])}</h1>
  <p><a href="{esc(row['target_url'])}">{esc(row['target_url'])}</a></p>
  <div class="status-row">
    <span class="pill {cls}">{esc(label)}</span>
    <span class="muted">Last checked: {esc((row['last_checked_at'] or 'pending').replace('T', ' '))}</span>
    <span class="muted">Latency: {esc(row['last_latency_ms'] or '-')} ms</span>
  </div>
  <div class="grid">{''.join(metric_html)}</div>
  <p>Badge: <code>![status]({esc(badge_url)})</code></p>
  <div class="actions">
    <a class="button secondary" href="{esc(badge_url)}">Open badge</a>
    <a class="button secondary" href="{esc(page_url)}">Public page</a>
    <a class="button secondary" href="{esc(origin)}/api/monitors/{esc(row['slug'])}">JSON</a>
  </div>
</section>
{manage}
<section>
  <h2>Recent checks</h2>
  <div class="checks">{''.join(check_html)}</div>
</section>
""",
    )


def svg_badge(row: sqlite3.Row) -> tuple[int, str, str]:
    cls, label = status_label(row)
    color = {"up": "#147a45", "down": "#b42318", "unknown": "#a15c07"}[cls]
    left = "pingbadge"
    right = label.lower()
    width = 92 + max(44, len(right) * 8)
    split = 82
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="{esc(left)}: {esc(right)}">
  <title>{esc(left)}: {esc(right)}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#fff" stop-opacity=".7"/>
    <stop offset=".1" stop-color="#aaa" stop-opacity=".1"/>
    <stop offset=".9" stop-opacity=".3"/>
    <stop offset="1" stop-opacity=".5"/>
  </linearGradient>
  <clipPath id="r"><rect width="{width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{split}" height="20" fill="#555"/>
    <rect x="{split}" width="{width - split}" height="20" fill="{color}"/>
    <rect width="{width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">
    <text x="41" y="15" fill="#010101" fill-opacity=".3">{esc(left)}</text>
    <text x="41" y="14">{esc(left)}</text>
    <text x="{split + (width - split) / 2:.0f}" y="15" fill="#010101" fill-opacity=".3">{esc(right)}</text>
    <text x="{split + (width - split) / 2:.0f}" y="14">{esc(right)}</text>
  </g>
</svg>"""
    return 200, "image/svg+xml; charset=utf-8", svg


class Handler(BaseHTTPRequestHandler):
    server_version = "PingBadge/0.1"

    def respond(
        self,
        status: int,
        content_type: str,
        body: str,
        extra_headers: dict[str, str] | None = None,
        include_body: bool = True,
    ) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        if include_body:
            self.wfile.write(encoded)

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_form(self) -> dict[str, str]:
        length = min(int(self.headers.get("Content-Length", "0")), 12000)
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}

    def handle_read(self, include_body: bool) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        origin = public_origin(self.headers)
        if path == "/healthz":
            self.respond(*text_document("ok\n"), include_body=include_body)
            return
        if path == "/robots.txt":
            body = f"User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n"
            self.respond(*text_document(body), include_body=include_body)
            return
        if path == "/sitemap.xml":
            with closing(db()) as conn:
                rows = conn.execute("select slug from monitors order by created_at desc limit 200").fetchall()
            urls = [f"{origin}/", f"{origin}/trust", f"{origin}/privacy"] + [f"{origin}/m/{quote(row['slug'])}" for row in rows]
            body = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
            body += "".join(f"  <url><loc>{esc(url)}</loc></url>\n" for url in urls)
            body += "</urlset>\n"
            self.respond(*text_document(body, "application/xml; charset=utf-8"), include_body=include_body)
            return
        if path == "/":
            self.respond(*landing(), include_body=include_body)
            return
        if path == "/trust":
            self.respond(*trust_page(), include_body=include_body)
            return
        if path == "/privacy":
            self.respond(*privacy_page(), include_body=include_body)
            return
        if path.startswith("/api/monitors/"):
            slug = path.removeprefix("/api/monitors/").strip("/")
            if slug.endswith(".json"):
                slug = slug[:-5]
            row = get_monitor(slug)
            if not row:
                self.respond(404, "application/json; charset=utf-8", "{\"error\":\"monitor_not_found\"}\n", include_body=include_body)
                return
            self.respond(
                *json_document(monitor_payload(row, origin)),
                {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store, max-age=0"},
                include_body=include_body,
            )
            return
        if path.startswith("/m/"):
            slug = path.removeprefix("/m/").strip("/")
            row = get_monitor(slug)
            if not row:
                self.respond(*page("Not found", "<h1>Monitor not found</h1>", 404), include_body=include_body)
                return
            token = query.get("token", [""])[-1]
            self.respond(*monitor_page(row, origin, token), include_body=include_body)
            return
        if path.startswith("/badge/"):
            slug = path.removeprefix("/badge/").strip("/")
            if slug.endswith(".svg"):
                slug = slug[:-4]
            row = get_monitor(slug)
            if not row:
                self.respond(404, "image/svg+xml; charset=utf-8", "", include_body=include_body)
                return
            status, content_type, body = svg_badge(row)
            self.respond(status, content_type, body, {"Cache-Control": "no-store, max-age=0"}, include_body=include_body)
            return
        self.respond(*page("Not found", "<h1>Not found</h1>", 404), include_body=include_body)

    def do_HEAD(self) -> None:
        self.handle_read(False)

    def do_GET(self) -> None:
        self.handle_read(True)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/monitors":
            form = self.read_form()
            normalized, error = normalize_target(form.get("target_url", ""))
            if error or not normalized:
                self.respond(*landing(error or "Invalid URL."))
                return
            with closing(db()) as conn:
                one_hour_ago = (utcnow() - timedelta(hours=1)).isoformat(timespec="seconds")
                recent_count = conn.execute(
                    "select count(*) as total from monitors where created_at >= ?",
                    (one_hour_ago,),
                ).fetchone()["total"]
            if int(recent_count) >= 40:
                self.respond(*landing("Creation is temporarily rate-limited. Try again later."))
                return
            monitor = create_monitor(normalized, display_name_for(normalized, form.get("display_name", "")), form.get("contact_email", ""))
            threading.Thread(target=check_target, args=(monitor,), daemon=True).start()
            self.redirect(f"/m/{quote(monitor['slug'])}?token={quote(monitor['token'])}")
            return
        if path.startswith("/m/") and path.endswith("/check"):
            slug = path.removeprefix("/m/").removesuffix("/check").strip("/")
            row = get_monitor(slug)
            token = parse_qs(parsed.query).get("token", [""])[-1]
            if not row or not secrets.compare_digest(token, row["token"]):
                self.respond(*page("Forbidden", "<h1>Forbidden</h1>", 403))
                return
            check_target(row)
            self.redirect(f"/m/{quote(row['slug'])}?token={quote(row['token'])}")
            return
        self.respond(*page("Not found", "<h1>Not found</h1>", 404))

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.log_date_time_string()} {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    init_db()
    threading.Thread(target=scheduler, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"{APP_NAME} listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
