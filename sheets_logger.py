"""
sheets_logger.py — Log completed checkouts to a Google Sheet, server-side only.

Two interchangeable backends, chosen from environment variables (see .env.example):

  1. Apps Script web app (recommended, no Google Cloud project needed)
       SHEETS_WEBHOOK_URL      https://script.google.com/macros/s/<id>/exec
       SHEETS_WEBHOOK_SECRET   long random string, also stored in the script's
                               Script Properties as WEBHOOK_SECRET
     Every request is signed: sig = HMAC-SHA256(secret, f"{ts}.{data}") and the
     script rejects bad signatures and requests older than 5 minutes.

  2. Google Sheets API with a service account
       GOOGLE_SERVICE_ACCOUNT_FILE  path to the JSON key   (or)
       GOOGLE_SERVICE_ACCOUNT_JSON  the JSON key contents
       SHEETS_SPREADSHEET_ID        the id from the sheet URL
       SHEETS_WORKSHEET             tab name (default "Pre-orders")

Delivery model (why the checkout never waits for, or fails because of, Google):

  * The checkout inserts the order AND a row in the `sheet_jobs` outbox table in
    the same SQLite transaction, then responds to the customer immediately.
  * A background worker thread sends pending jobs. Failures are retried with
    exponential backoff (30 s → 12 h, 8 attempts) and every error is written to
    logs/sheets.log and to the job row, visible at /admin/sheets.
  * If no backend is configured yet, jobs simply wait; once you configure one,
    the backlog is delivered automatically.
  * Each order reference is written once: both backends skip a reference that
    is already in column A, so retries never create duplicate rows.

CLI (run from the project folder):
  python sheets_logger.py check     test the connection without writing rows
  python sheets_logger.py status    show queue counts and recent errors
  python sheets_logger.py flush     send everything that is due now
  python sheets_logger.py retry     re-queue jobs that gave up, then flush
  python sheets_logger.py backfill  queue orders placed before logging was enabled
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote

import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"

# Column layout. The first 14 are the required columns, in the required order.
HEADERS = [
    "Order Reference Number",
    "Date & Time",
    "Customer Name",
    "Email Address",
    "Province",
    "Selected Dealer",
    "Vehicle Model",
    "Trim",
    "Color",
    "Deposit Amount",
    "Discount Applied",
    "Subtotal",
    "Tax (GST/PST)",
    "Total Amount",
    # Extra context, appended after the required columns:
    "Quantity",
    "Interior",
    "Promo Code",
    "Tax Breakdown",
    "Phone",
    "Line Item",
]
MONEY_COLUMNS = ["Deposit Amount", "Discount Applied", "Subtotal", "Tax (GST/PST)", "Total Amount"]

BACKOFF_SECONDS = [30, 120, 600, 1800, 3600, 3 * 3600, 6 * 3600, 12 * 3600]
MAX_ATTEMPTS = len(BACKOFF_SECONDS)
POLL_SECONDS = 30
LOCK_SECONDS = 120          # a claimed job is reserved for this long
HTTP_TIMEOUT = (5, 25)      # connect, read (seconds)


class SheetsError(Exception):
    """Raised when a backend call fails; the message is stored for the admin."""


# ------------------------------------------------------------------- logging
def _build_logger() -> logging.Logger:
    log = logging.getLogger("byd.sheets")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [sheets] %(message)s")
    LOG_DIR.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(LOG_DIR / "sheets.log", maxBytes=1_000_000, backupCount=5)
    file_handler.setFormatter(fmt)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    log.addHandler(file_handler)
    log.addHandler(stream)
    log.propagate = False
    return log


log = _build_logger()


# ---------------------------------------------------------------- formatting
def _timezone():
    name = os.environ.get("SHEETS_TIMEZONE", "America/Toronto")
    try:
        return ZoneInfo(name) if ZoneInfo else None
    except Exception:  # noqa: BLE001 - unknown zone name or missing tzdata
        return None


def _format_time(ts: float) -> str:
    tz = _timezone()
    dt = datetime.fromtimestamp(ts, tz) if tz else datetime.utcfromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S ") + (dt.tzname() or "UTC")


def _money(value) -> float:
    return round(float(value or 0), 2)


def build_rows(order: dict) -> list[list]:
    """One row per vehicle line. Order-level fields repeat on every line.

    Per line: Deposit = line deposit, Discount = pre-order discount + promo,
    Subtotal = price after discounts, Tax = that line's share of the order's
    taxes (rounding remainder goes to the last line so the rows add up to the
    order total exactly), Total = Subtotal + Tax.
    """
    items = order.get("items") or []
    totals = order.get("totals") or {}
    taxes = totals.get("taxes") or []
    customer = order.get("customer") or {}
    promo = (order.get("promo") or {}).get("code") or ""
    when = _format_time(order.get("created_ts") or time.time())
    province = f"{order.get('province_name', '')} ({order.get('province', '')})".strip()

    rows: list[list] = []
    allocated = {t["label"]: 0.0 for t in taxes}
    for idx, it in enumerate(items, start=1):
        last = idx == len(items)
        line_taxes = []
        for t in taxes:
            if last:  # remainder keeps the sheet consistent with the order total
                amount = round(float(t["amount"]) - allocated[t["label"]], 2)
            else:
                amount = round(float(it["line_total"]) * float(t["rate"]), 2)
                allocated[t["label"]] += amount
            line_taxes.append((t["label"], amount))
        tax = round(sum(a for _, a in line_taxes), 2)
        subtotal = _money(it["line_total"])
        colour = it["colour"] + (" (colour simulation)" if it.get("colour_simulated") else "")
        rows.append([
            order["ref"],
            when,
            customer.get("name", ""),
            customer.get("email", ""),
            province,
            order.get("dealer", ""),
            it["name"],
            it["trim"],
            colour,
            _money(it["line_deposit"]),
            _money(float(it.get("line_discount", 0)) + float(it.get("line_promo", 0))),
            subtotal,
            tax,
            round(subtotal + tax, 2),
            int(it.get("qty", 1)),
            it.get("interior", ""),
            promo,
            "; ".join(f"{label}: ${amount:,.2f}" for label, amount in line_taxes),
            customer.get("phone", ""),
            f"{idx} of {len(items)}",
        ])
    return rows


# ------------------------------------------------------------------ backends
def _text_snippet(text: str, limit: int = 160) -> str:
    """Readable excerpt of an error response (HTML tags and scripts removed)."""
    import re
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = " ".join(text.split())
    return (text[:limit] + "…") if len(text) > limit else (text or "(empty response)")


class WebhookBackend:
    """Google Apps Script web app bound to the spreadsheet (see integrations/)."""

    name = "Apps Script webhook"

    def __init__(self, url: str, secret: str):
        if not url.startswith("https://script.google.com/"):
            raise SheetsError("SHEETS_WEBHOOK_URL must start with https://script.google.com/")
        if len(secret) < 24:
            raise SheetsError("SHEETS_WEBHOOK_SECRET must be at least 24 characters")
        self.url, self.secret = url, secret

    @property
    def target(self) -> str:
        return self.url[:48] + "…" if len(self.url) > 48 else self.url

    def _call(self, payload: dict) -> dict:
        data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        ts = str(int(time.time()))
        sig = hmac.new(self.secret.encode(), f"{ts}.{data}".encode(), hashlib.sha256).hexdigest()
        try:
            # Apps Script answers POST with a 302 to googleusercontent.com;
            # requests follows it (as a GET) and returns the script's output.
            resp = requests.post(self.url, json={"ts": ts, "data": data, "sig": sig},
                                 timeout=HTTP_TIMEOUT, allow_redirects=True)
        except requests.RequestException as exc:
            raise SheetsError(f"Network error contacting Apps Script: {exc}") from exc
        if resp.status_code in (401, 403):
            raise SheetsError(f"Apps Script refused access (HTTP {resp.status_code}). In Deploy > Manage "
                              "deployments set 'Who has access' to 'Anyone'.")
        if resp.status_code == 404:
            raise SheetsError("Apps Script web app not found (HTTP 404). Check SHEETS_WEBHOOK_URL is the "
                              "/exec URL of an active deployment.")
        if resp.status_code >= 400:
            raise SheetsError(f"Apps Script HTTP {resp.status_code}: {_text_snippet(resp.text)}")
        try:
            body = resp.json()
        except ValueError:
            raise SheetsError("Apps Script did not return JSON. Check the deployment is a Web app "
                              f"with access 'Anyone'. Response: {_text_snippet(resp.text)}") from None
        if not body.get("ok"):
            raise SheetsError(f"Apps Script error: {body.get('error', 'unknown error')}")
        return body

    def check(self) -> str:
        body = self._call({"action": "ping", "headers": HEADERS})
        return f"Connected to Apps Script; writing to tab '{body.get('sheet', '?')}'."

    def append(self, ref: str, rows: list[list]) -> str:
        body = self._call({"action": "append", "ref": ref, "headers": HEADERS, "rows": rows})
        return body.get("status", "appended")


class ServiceAccountBackend:
    """Google Sheets API v4 using a service-account key (server-to-server)."""

    name = "Google Sheets API (service account)"
    API = "https://sheets.googleapis.com/v4/spreadsheets"
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, spreadsheet_id: str, worksheet: str, key_file: str = "", key_json: str = ""):
        try:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account
        except ImportError as exc:
            raise SheetsError("The google-auth package is required: pip install -r requirements.txt") from exc
        try:
            if key_json:
                info = json.loads(key_json)
                creds = service_account.Credentials.from_service_account_info(info, scopes=self.SCOPES)
            else:
                path = Path(key_file)
                if not path.is_absolute():
                    path = ROOT / path
                creds = service_account.Credentials.from_service_account_file(str(path), scopes=self.SCOPES)
        except (OSError, ValueError, KeyError) as exc:
            raise SheetsError(f"Could not load service-account credentials: {exc}") from exc
        self.client_email = creds.service_account_email
        self.session = AuthorizedSession(creds)
        self.spreadsheet_id = spreadsheet_id
        self.worksheet = worksheet
        self._ready = False

    @property
    def target(self) -> str:
        return f"{self.spreadsheet_id[:10]}… / {self.worksheet}"

    def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            resp = self.session.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
        except Exception as exc:  # noqa: BLE001 - google-auth raises several types
            raise SheetsError(f"Network error contacting Google Sheets API: {exc}") from exc
        if resp.status_code == 403:
            raise SheetsError("Permission denied (403). Share the spreadsheet with "
                              f"{self.client_email} as an Editor.")
        if resp.status_code == 404:
            raise SheetsError("Spreadsheet not found (404). Check SHEETS_SPREADSHEET_ID.")
        if resp.status_code >= 400:
            raise SheetsError(f"Sheets API HTTP {resp.status_code}: {_text_snippet(resp.text, 200)}")
        return resp.json() if resp.content else {}

    def _range(self, a1: str) -> str:
        sheet = self.worksheet.replace("'", "''")
        return quote(f"'{sheet}'!{a1}", safe="")

    def _ensure_ready(self) -> None:
        """Create the tab and header row on first use."""
        if self._ready:
            return
        base = f"{self.API}/{self.spreadsheet_id}"
        meta = self._request("GET", base, params={"fields": "sheets.properties(sheetId,title)"})
        sheets = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
        if self.worksheet not in sheets:
            res = self._request("POST", f"{base}:batchUpdate", json={"requests": [
                {"addSheet": {"properties": {"title": self.worksheet}}}]})
            sheets[self.worksheet] = res["replies"][0]["addSheet"]["properties"]["sheetId"]
        first_row = self._request("GET", f"{base}/values/{self._range('1:1')}").get("values")
        if not first_row:
            self._request("PUT", f"{base}/values/{self._range('A1')}",
                          params={"valueInputOption": "RAW"}, json={"values": [HEADERS]})
            sid = sheets[self.worksheet]
            money_start = HEADERS.index(MONEY_COLUMNS[0])
            self._request("POST", f"{base}:batchUpdate", json={"requests": [
                {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                                "fields": "userEnteredFormat.textFormat.bold"}},
                {"updateSheetProperties": {"properties": {"sheetId": sid,
                                                          "gridProperties": {"frozenRowCount": 1}},
                                           "fields": "gridProperties.frozenRowCount"}},
                {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1,
                                          "startColumnIndex": money_start,
                                          "endColumnIndex": money_start + len(MONEY_COLUMNS)},
                                "cell": {"userEnteredFormat": {"numberFormat": {
                                    "type": "CURRENCY", "pattern": "$#,##0.00"}}},
                                "fields": "userEnteredFormat.numberFormat"}},
            ]})
        self._ready = True

    def check(self) -> str:
        self._ensure_ready()
        return (f"Connected as {self.client_email}; writing to tab '{self.worksheet}' "
                f"of spreadsheet {self.spreadsheet_id}.")

    def append(self, ref: str, rows: list[list]) -> str:
        self._ensure_ready()
        base = f"{self.API}/{self.spreadsheet_id}"
        col_a = self._request("GET", f"{base}/values/{self._range('A:A')}").get("values", [])
        if any(r and r[0] == ref for r in col_a):
            return "duplicate"
        # RAW: values are stored exactly as sent (no formula evaluation).
        # OVERWRITE fills the next empty rows so they keep the data-row
        # formatting (INSERT_ROWS would copy the header row's style).
        self._request("POST", f"{base}/values/{self._range('A1')}:append",
                      params={"valueInputOption": "RAW", "insertDataOption": "OVERWRITE"},
                      json={"values": rows})
        return "appended"


_backend_cache: dict[str, object] = {}


def get_backend():
    """Return the configured backend, or None when Sheets logging is not set up.

    Raises SheetsError when configuration is present but invalid."""
    url = os.environ.get("SHEETS_WEBHOOK_URL", "").strip()
    secret = os.environ.get("SHEETS_WEBHOOK_SECRET", "").strip()
    sheet_id = os.environ.get("SHEETS_SPREADSHEET_ID", "").strip()
    key_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    worksheet = os.environ.get("SHEETS_WORKSHEET", "Pre-orders").strip() or "Pre-orders"

    if url or secret:
        key = f"webhook|{url}|{hashlib.sha256(secret.encode()).hexdigest()}"
        if key not in _backend_cache:
            if not (url and secret):
                raise SheetsError("Set both SHEETS_WEBHOOK_URL and SHEETS_WEBHOOK_SECRET")
            _backend_cache[key] = WebhookBackend(url, secret)
        return _backend_cache[key]
    if sheet_id or key_file or key_json:
        key = f"api|{sheet_id}|{worksheet}|{key_file}|{hashlib.sha256(key_json.encode()).hexdigest()}"
        if key not in _backend_cache:
            if not sheet_id or not (key_file or key_json):
                raise SheetsError("Set SHEETS_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_FILE "
                                  "(or GOOGLE_SERVICE_ACCOUNT_JSON)")
            _backend_cache[key] = ServiceAccountBackend(sheet_id, worksheet, key_file, key_json)
        return _backend_cache[key]
    return None


def describe_backend() -> dict:
    """Configuration summary for the admin page (never includes secrets)."""
    try:
        backend = get_backend()
    except SheetsError as exc:
        return {"configured": False, "name": "Misconfigured", "target": "", "error": str(exc)}
    if backend is None:
        return {"configured": False, "name": "Not configured", "target": "", "error": ""}
    return {"configured": True, "name": backend.name, "target": backend.target, "error": ""}


# -------------------------------------------------------------------- outbox
SCHEMA = """
CREATE TABLE IF NOT EXISTS sheet_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ref           TEXT NOT NULL UNIQUE,
    payload       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',   -- pending | sent | failed
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    result        TEXT,
    next_attempt  REAL NOT NULL,
    locked_until  REAL NOT NULL DEFAULT 0,
    created       REAL NOT NULL,
    updated       REAL NOT NULL,
    sent_at       REAL
);
CREATE INDEX IF NOT EXISTS sheet_jobs_due ON sheet_jobs(status, next_attempt);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def enqueue(conn: sqlite3.Connection, order: dict) -> None:
    """Queue an order for logging. Call inside the checkout transaction (no commit here)."""
    now = time.time()
    conn.execute(
        "INSERT OR IGNORE INTO sheet_jobs(ref, payload, next_attempt, created, updated) "
        "VALUES(?,?,?,?,?)",
        (order["ref"], json.dumps({"rows": build_rows(order)}), now, now, now))


def _connect(db_file: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_file, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


_last_config_error = ""


def process_due(db_file: Path, limit: int = 20) -> dict:
    """Send due jobs. Returns counts. Never raises for delivery errors."""
    counts = {"sent": 0, "retry": 0, "failed": 0, "skipped": 0}
    global _last_config_error
    try:
        backend = get_backend()
    except SheetsError as exc:
        if str(exc) != _last_config_error:  # log each distinct problem once, not every poll
            log.error("Configuration error, orders stay queued until it is fixed: %s", exc)
            _last_config_error = str(exc)
        return counts
    _last_config_error = ""
    if backend is None:
        return counts  # not configured yet: jobs wait, nothing to report

    now = time.time()
    with _connect(db_file) as conn:
        due = conn.execute(
            "SELECT id FROM sheet_jobs WHERE status='pending' AND next_attempt<=? "
            "AND locked_until<? ORDER BY id LIMIT ?", (now, now, limit)).fetchall()
    for row in due:
        with _connect(db_file) as conn:
            claimed = conn.execute(  # atomic claim, safe with several worker processes
                "UPDATE sheet_jobs SET locked_until=? WHERE id=? AND status='pending' AND locked_until<?",
                (time.time() + LOCK_SECONDS, row["id"], time.time())).rowcount
            if not claimed:
                counts["skipped"] += 1
                continue
            job = conn.execute("SELECT * FROM sheet_jobs WHERE id=?", (row["id"],)).fetchone()
        rows = json.loads(job["payload"])["rows"]
        attempts = job["attempts"] + 1
        try:
            result = backend.append(job["ref"], rows)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, never raised
            message = str(exc) if isinstance(exc, SheetsError) else f"{type(exc).__name__}: {exc}"
            gave_up = attempts >= MAX_ATTEMPTS
            delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
            with _connect(db_file) as conn:
                conn.execute(
                    "UPDATE sheet_jobs SET status=?, attempts=?, last_error=?, next_attempt=?, "
                    "locked_until=0, updated=? WHERE id=?",
                    ("failed" if gave_up else "pending", attempts, message[:1000],
                     time.time() + delay, time.time(), job["id"]))
            if gave_up:
                counts["failed"] += 1
                log.error("Order %s NOT logged after %d attempts, giving up (retry from /admin/sheets): %s",
                          job["ref"], attempts, message)
            else:
                counts["retry"] += 1
                log.warning("Order %s not logged (attempt %d/%d), retrying in %ds: %s",
                            job["ref"], attempts, MAX_ATTEMPTS, delay, message)
            continue
        with _connect(db_file) as conn:
            conn.execute(
                "UPDATE sheet_jobs SET status='sent', attempts=?, last_error=NULL, result=?, "
                "locked_until=0, updated=?, sent_at=? WHERE id=?",
                (attempts, result, time.time(), time.time(), job["id"]))
        counts["sent"] += 1
        log.info("Order %s logged to Google Sheets (%s, %d row%s)",
                 job["ref"], result, len(rows), "" if len(rows) == 1 else "s")
    return counts


def backfill(db_file: Path) -> int:
    """Queue orders that were placed before Sheets logging existed."""
    added = 0
    with _connect(db_file) as conn:
        init_db(conn)
        rows = conn.execute("SELECT o.ref, o.created, o.data FROM orders o "
                            "LEFT JOIN sheet_jobs j ON j.ref = o.ref "
                            "WHERE j.ref IS NULL ORDER BY o.created").fetchall()
        for row in rows:
            order = json.loads(row["data"])
            order.setdefault("created_ts", row["created"])
            try:
                enqueue(conn, order)
                added += 1
            except Exception as exc:  # noqa: BLE001
                log.error("Could not backfill order %s: %s", row["ref"], exc)
    return added


def retry_failed(db_file: Path) -> int:
    """Re-queue jobs that gave up so they are attempted again immediately."""
    with _connect(db_file) as conn:
        return conn.execute(
            "UPDATE sheet_jobs SET status='pending', attempts=0, next_attempt=?, locked_until=0, "
            "updated=? WHERE status='failed'", (time.time(), time.time())).rowcount


def stats(db_file: Path, recent: int = 50) -> dict:
    with _connect(db_file) as conn:
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM sheet_jobs GROUP BY status")}
        jobs = [dict(r) for r in conn.execute(
            "SELECT ref, status, attempts, last_error, result, next_attempt, created, sent_at "
            "FROM sheet_jobs ORDER BY id DESC LIMIT ?", (recent,))]
    return {"pending": counts.get("pending", 0), "sent": counts.get("sent", 0),
            "failed": counts.get("failed", 0), "jobs": jobs}


# -------------------------------------------------------------------- worker
class _Worker(threading.Thread):
    def __init__(self, db_file: Path):
        super().__init__(name="sheets-logger", daemon=True)
        self.db_file = db_file
        self.wake_event = threading.Event()
        self.wake_event.set()  # deliver any backlog at startup

    def run(self) -> None:
        while True:
            self.wake_event.wait(timeout=POLL_SECONDS)
            self.wake_event.clear()
            try:
                process_due(self.db_file)
            except Exception:  # noqa: BLE001 - the worker must never die
                log.exception("Unexpected error in the Sheets worker")


_worker: _Worker | None = None
_worker_lock = threading.Lock()


def start_worker(db_file: Path) -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = _Worker(db_file)
            _worker.start()


def wake() -> None:
    """Ask the worker to send immediately (called right after a checkout)."""
    if _worker is not None:
        _worker.wake_event.set()


# ----------------------------------------------------------------------- CLI
def load_env(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines; existing environment wins."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _cli(argv: list[str]) -> int:
    load_env(ROOT / ".env")
    db_file = ROOT / "data" / "showroom.db"
    with _connect(db_file) as conn:
        init_db(conn)
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "check":
        try:
            backend = get_backend()
            if backend is None:
                print("Not configured. Copy .env.example to .env and fill in one backend.")
                return 1
            print(f"{backend.name}: {backend.check()}")
            return 0
        except SheetsError as exc:
            print(f"FAILED: {exc}")
            return 1
    if cmd == "backfill":
        print(f"Queued {backfill(db_file)} earlier order(s).")
        cmd = "flush"
    if cmd == "retry":
        print(f"Re-queued {retry_failed(db_file)} failed job(s).")
        cmd = "flush"
    if cmd == "flush":
        print(process_due(db_file, limit=500))
        return 0
    if cmd == "status":
        s = stats(db_file, recent=10)
        print(f"Backend: {describe_backend()}")
        print(f"pending={s['pending']} sent={s['sent']} failed={s['failed']}")
        for j in s["jobs"]:
            print(f"  {j['ref']:24} {j['status']:8} attempts={j['attempts']} {j['last_error'] or ''}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
