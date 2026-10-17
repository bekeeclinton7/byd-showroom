"""
BYD Canada Virtual Showroom — Flask backend.

Pages     /  /showroom  /vehicle/<id>  /compare  /cart  /confirmation/<ref>
API       /api/vehicles            GET   filter / search / sort the lineup
          /api/vehicles/<id>       GET   full vehicle record
          /api/colors/<model>      GET   paint options
          /api/interiors/<model>   GET   interior options
          /api/meta                GET   provinces, taxes, dealers, launch deadline
          /api/preorder            POST  validate a configuration -> priced quote
          /api/cart                GET / POST / PATCH       cart summary, add line, settings
          /api/cart/<line_id>      PATCH / DELETE           change qty, remove line
          /api/checkout            POST  validate form, create order, clear cart
                                   (Idempotency-Key header makes retries safe)
Admin     /admin/sheets            GET   Google Sheets logging status (ADMIN_TOKEN)
          /admin/sheets/retry      POST  re-queue failed Sheets jobs
          /admin/sheets/check      POST  test the Sheets connection
Images    /img/vehicles/<path>     local cache first, then fetch from BYD + cache,
                                   then an SVG fallback (never a 404)
          /img/proxy?src=<url>     generic allow-listed proxy + cache

Cart persistence: SQLite (data/showroom.db), keyed by a cart id that the client
sends in the X-Cart-Id header (works inside iframes where cookies may be
blocked) with a cookie as a secondary channel.

Google Sheets logging (sheets_logger.py): every order is queued in the same
transaction as the order itself and delivered by a background worker, so the
customer always gets the confirmation page even if Google is unreachable.
Credentials are read from the environment / .env and never reach the browser.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import (Flask, abort, g, jsonify, make_response, redirect, render_template,
                   request, send_file, url_for)
from markupsafe import Markup

import sheets_logger

ROOT = Path(__file__).resolve().parent
sheets_logger.load_env(ROOT / ".env")   # server-side secrets; real env vars take precedence
DATA_FILE = ROOT / "data" / "vehicles.json"
MANIFEST_FILE = ROOT / "data" / "image_manifest.json"
DB_FILE = ROOT / "data" / "showroom.db"
IMG_DIR = ROOT / "static" / "images" / "vehicles"
CACHE_DIR = ROOT / "static" / "images" / "cache"
FALLBACK_SVG = ROOT / "static" / "images" / "fallback.svg"
FAVICON = ROOT / "static" / "images" / "brand" / "favicon.ico"
SPRITE = ROOT / "static" / "icons" / "sprite.svg"

ALLOWED_IMAGE_HOSTS = {"www.byd.com", "byd.com", "media.byd.com"}
MAX_QTY_PER_LINE = 2       # pre-order allocation per configuration
MAX_VEHICLES_PER_ORDER = 3

# Promotional codes are validated server-side only (never shipped to the client).
PROMOS = {
    "BYDLAUNCH": {"type": "flat", "amount": 500,
                  "label": "Launch bonus: $500 off per vehicle"},
    "CANADAEV": {"type": "percent", "rate": 0.02, "cap": 1000,
                 "label": "2% off MSRP (max $1,000 per vehicle)"},
    "EARLYBIRD": {"type": "expired", "label": "Early-bird offer"},
}

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
ASSET_VERSION = str(int(time.time()))


# ----------------------------------------------------------------- data store
@lru_cache(maxsize=1)
def load_data() -> dict:
    data = json.loads(DATA_FILE.read_text())
    data["by_id"] = {v["id"]: v for v in data["vehicles"]}
    return data


def vehicles() -> list[dict]:
    return load_data()["vehicles"]


def get_vehicle(vid: str) -> dict | None:
    return load_data()["by_id"].get(vid)


def market() -> dict:
    return load_data()["market"]


def _find(items: list[dict], key: str) -> dict | None:
    return next((i for i in items if i["id"] == key), None)


# ------------------------------------------------------------------ database
def db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def _close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS carts (
                id TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS orders (
                ref TEXT PRIMARY KEY, created REAL NOT NULL, data TEXT NOT NULL);
        """)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(orders)")}
        if "idem" not in columns:  # added for idempotent checkout retries
            conn.execute("ALTER TABLE orders ADD COLUMN idem TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS orders_idem ON orders(idem) "
                     "WHERE idem IS NOT NULL")
        sheets_logger.init_db(conn)


EMPTY_CART = {"items": [], "province": "ON", "promo": None}
CART_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def current_cart_id() -> str:
    """Cart id from header (preferred) or cookie; mint a new one if missing."""
    if "cart_id" in g:
        return g.cart_id
    cid = request.headers.get("X-Cart-Id") or request.cookies.get("byd_cart") or ""
    if not CART_ID_RE.match(cid):
        cid = secrets.token_hex(16)
    g.cart_id = cid
    return cid


def load_cart() -> dict:
    row = db().execute("SELECT data FROM carts WHERE id=?", (current_cart_id(),)).fetchone()
    cart = json.loads(row["data"]) if row else json.loads(json.dumps(EMPTY_CART))
    # Drop lines that no longer resolve (e.g. data file changed).
    cart["items"] = [i for i in cart["items"] if _resolve(i)]
    return cart


def save_cart(cart: dict) -> None:
    db().execute("INSERT INTO carts(id, data, updated) VALUES(?,?,?) "
                 "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated=excluded.updated",
                 (current_cart_id(), json.dumps(cart), time.time()))
    db().commit()


@app.after_request
def _attach_cart_cookie(resp):
    if "cart_id" in g:
        resp.set_cookie("byd_cart", g.cart_id, max_age=60 * 60 * 24 * 30,
                        httponly=True, samesite="Lax")
        resp.headers["X-Cart-Id"] = g.cart_id
    return resp


# ------------------------------------------------------------------- pricing
class ValidationError(Exception):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message, self.field = message, field


@app.errorhandler(ValidationError)
def _validation_error(err: ValidationError):
    return jsonify({"ok": False, "error": err.message, "field": err.field}), 422


def _resolve(item: dict):
    """Return (vehicle, trim, colour, interior) or None if any part is invalid."""
    v = get_vehicle(item.get("vehicle_id", ""))
    if not v:
        return None
    t = _find(v["trims"], item.get("trim_id", ""))
    c = _find(v["colours"], item.get("colour_id", ""))
    i = _find(v["interiors"], item.get("interior_id", ""))
    return (v, t, c, i) if t and c and i else None


def validate_config(payload: dict) -> dict:
    """Server-side validation of a pre-order configuration."""
    if not isinstance(payload, dict):
        raise ValidationError("Invalid request body.")
    v = get_vehicle(str(payload.get("vehicle_id", "")))
    if not v:
        raise ValidationError("Unknown vehicle.", "vehicle_id")
    if not _find(v["trims"], str(payload.get("trim_id", ""))):
        raise ValidationError(f"Choose a valid trim for the {v['name']}.", "trim_id")
    if not _find(v["colours"], str(payload.get("colour_id", ""))):
        raise ValidationError(f"Choose a valid colour for the {v['name']}.", "colour_id")
    if not _find(v["interiors"], str(payload.get("interior_id", ""))):
        raise ValidationError(f"Choose a valid interior for the {v['name']}.", "interior_id")
    try:
        qty = int(payload.get("qty", 1))
    except (TypeError, ValueError):
        raise ValidationError("Quantity must be a number.", "qty") from None
    if not 1 <= qty <= MAX_QTY_PER_LINE:
        raise ValidationError(f"Pre-orders are limited to {MAX_QTY_PER_LINE} per configuration.", "qty")
    return {"vehicle_id": v["id"], "trim_id": payload["trim_id"],
            "colour_id": payload["colour_id"], "interior_id": payload["interior_id"], "qty": qty}


def promo_per_vehicle(code: str | None, unit_msrp: float) -> float:
    p = PROMOS.get(code or "")
    if not p or p["type"] == "expired":
        return 0
    if p["type"] == "flat":
        return p["amount"]
    return round(min(unit_msrp * p["rate"], p["cap"]), 2)


def price_line(item: dict, promo: str | None = None) -> dict:
    v, t, c, i = _resolve(item)
    unit_msrp = t["price"] + c["price"] + i["price"]
    discount = v["preorder"]["discount"]
    promo_amt = promo_per_vehicle(promo, unit_msrp)
    image = c["images"][0] if c["images"] else v["card_image"]
    qty = item.get("qty", 1)
    return {
        "line_id": item.get("line_id"),
        "vehicle_id": v["id"], "name": v["full_name"], "body": v["body"],
        "trim_id": t["id"], "trim": t["name"],
        "colour_id": c["id"], "colour": c["name"], "colour_hex": c["hex"],
        "colour_simulated": c["source"] != "photo",
        "interior_id": i["id"], "interior": i["name"],
        "image": image, "qty": qty,
        "base_price": t["price"], "colour_price": c["price"], "interior_price": i["price"],
        "unit_msrp": unit_msrp, "unit_discount": discount, "unit_promo": promo_amt,
        "unit_price": unit_msrp - discount - promo_amt,
        "unit_deposit": v["preorder"]["deposit"],
        "line_msrp": unit_msrp * qty, "line_discount": discount * qty,
        "line_promo": promo_amt * qty,
        "line_total": (unit_msrp - discount - promo_amt) * qty,
        "line_deposit": v["preorder"]["deposit"] * qty,
        "delivery": v["delivery"],
    }


def summarise(cart: dict) -> dict:
    promo = cart.get("promo")
    lines = [price_line(i, promo) for i in cart["items"]]
    msrp = sum(l["line_msrp"] for l in lines)
    preorder = sum(l["line_discount"] for l in lines)
    promo_total = sum(l["line_promo"] for l in lines)
    subtotal = msrp - preorder - promo_total
    prov = market()["provinces"].get(cart.get("province") or "ON", market()["provinces"]["ON"])
    taxes = [{"label": f"{name} ({rate * 100:g}%)", "rate": rate,
              "amount": round(subtotal * rate, 2)} for name, rate in prov["taxes"]]
    tax_total = round(sum(t["amount"] for t in taxes), 2)
    return {
        "ok": True, "cart_id": current_cart_id(), "items": lines,
        "count": sum(l["qty"] for l in lines),
        "province": cart.get("province") or "ON", "province_name": prov["name"],
        "promo": {"code": promo, "label": PROMOS[promo]["label"]} if promo in PROMOS else None,
        "totals": {
            "msrp": msrp, "preorder_savings": preorder, "promo_savings": promo_total,
            "subtotal": subtotal, "taxes": taxes, "tax_total": tax_total,
            "estimated_total": round(subtotal + tax_total, 2),
            "due_today": sum(l["line_deposit"] for l in lines),
        },
        "limits": {"per_line": MAX_QTY_PER_LINE, "per_order": MAX_VEHICLES_PER_ORDER},
    }


# ---------------------------------------------------------------- templating
@lru_cache(maxsize=1)
def _sprite_markup() -> str:
    return SPRITE.read_text()


@app.context_processor
def inject_globals():
    return {
        "icon_sprite": Markup(_sprite_markup()),
        "asset_v": ASSET_VERSION,
        "nav_vehicles": vehicles(),
        "launch_deadline": market()["launch_deadline"],
        "current_year": time.localtime().tm_year,
        "deposit_from": min(v["preorder"]["deposit"] for v in vehicles()),
    }


@app.template_filter("cad")
def cad(value, cents: bool = False) -> str:
    value = float(value or 0)
    return f"${value:,.0f}" if value == int(value) and not cents else f"${value:,.2f}"


# --------------------------------------------------------------------- pages
@app.get("/favicon.ico")
def favicon():
    return send_file(FAVICON, mimetype="image/vnd.microsoft.icon", max_age=60 * 60 * 24 * 7)


@app.route("/")
def home():
    featured = [v for v in vehicles() if v["status"] == "Launch lineup"]
    return render_template("home.html", page="home", featured=featured, all_vehicles=vehicles())


@app.route("/showroom")
def showroom():
    return render_template("showroom.html", page="showroom", all_vehicles=vehicles())


@app.route("/vehicle/<vid>")
def vehicle(vid: str):
    v = get_vehicle(vid)
    if not v:
        abort(404)
    others = [o for o in vehicles() if o["id"] != vid][:3]
    return render_template("vehicle.html", page="vehicle", v=v, others=others,
                           vehicle_json=Markup(json.dumps(v).replace("</", "<\\/")))


@app.route("/compare")
def compare():
    return render_template("compare.html", page="compare", all_vehicles=vehicles())


@app.route("/cart")
def cart_page():
    return render_template("cart.html", page="cart", market=market())


@app.route("/confirmation")
def confirmation_index():
    return redirect(url_for("cart_page"))


@app.route("/confirmation/<ref>")
def confirmation(ref: str):
    row = db().execute("SELECT data FROM orders WHERE ref=?", (ref.upper(),)).fetchone()
    if not row:
        abort(404)
    return render_template("confirmation.html", page="confirmation", order=json.loads(row["data"]))


@app.errorhandler(404)
def not_found(_err):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Not found"}), 404
    return render_template("404.html", page="error"), 404


# ----------------------------------------------------------------------- API
def _card(v: dict) -> dict:
    keys = ("id", "name", "full_name", "tagline", "body", "seats", "status", "delivery",
            "price_from", "range_max", "power_max", "accel_best", "dc_max", "battery_max",
            "card_image", "preorder", "summary", "dimensions", "cargo_l", "warranty", "note")
    out = {k: v[k] for k in keys}
    out["colours"] = [{"id": c["id"], "name": c["name"], "hex": c["hex"]} for c in v["colours"]]
    out["trims"] = [{"id": t["id"], "name": t["name"], "price": t["price"], "spec": t["spec"]}
                    for t in v["trims"]]
    return out


@app.get("/api/vehicles")
def api_vehicles():
    items = vehicles()
    args = request.args
    if args.get("body"):
        bodies = {b.strip().lower() for b in args["body"].split(",") if b.strip()}
        items = [v for v in items if v["body"].lower() in bodies]
    if args.get("max_price", type=float):
        items = [v for v in items if v["price_from"] <= args.get("max_price", type=float)]
    if args.get("min_range", type=float):
        items = [v for v in items if v["range_max"] >= args.get("min_range", type=float)]
    if args.get("seats", type=int):
        items = [v for v in items if v["seats"] >= args.get("seats", type=int)]
    if args.get("q"):
        q = args["q"].strip().lower()
        items = [v for v in items if q in " ".join([v["name"], v["full_name"], v["body"],
                                                    v["tagline"], v["summary"]]).lower()]
    sorters = {
        "price-asc": (lambda v: v["price_from"], False),
        "price-desc": (lambda v: v["price_from"], True),
        "range-desc": (lambda v: v["range_max"], True),
        "power-desc": (lambda v: v["power_max"], True),
        "name": (lambda v: v["name"], False),
    }
    key, rev = sorters.get(args.get("sort", "price-asc"), sorters["price-asc"])
    items = sorted(items, key=key, reverse=rev)
    all_v = vehicles()
    return jsonify({
        "ok": True, "count": len(items), "vehicles": [_card(v) for v in items],
        "facets": {
            "bodies": sorted({v["body"] for v in all_v}),
            "price": [min(v["price_from"] for v in all_v), max(v["price_from"] for v in all_v)],
            "range": [min(v["range_max"] for v in all_v), max(v["range_max"] for v in all_v)],
            "seats": sorted({v["seats"] for v in all_v}),
        },
    })


@app.get("/api/vehicles/<vid>")
def api_vehicle(vid: str):
    v = get_vehicle(vid)
    if not v:
        return jsonify({"ok": False, "error": "Vehicle not found"}), 404
    return jsonify({"ok": True, "vehicle": v})


@app.get("/api/colors/<vid>")
def api_colours(vid: str):
    v = get_vehicle(vid)
    if not v:
        return jsonify({"ok": False, "error": "Vehicle not found"}), 404
    return jsonify({"ok": True, "vehicle_id": vid, "colours": v["colours"]})


@app.get("/api/interiors/<vid>")
def api_interiors(vid: str):
    v = get_vehicle(vid)
    if not v:
        return jsonify({"ok": False, "error": "Vehicle not found"}), 404
    return jsonify({"ok": True, "vehicle_id": vid, "interiors": v["interiors"]})


@app.get("/api/meta")
def api_meta():
    m = market()
    return jsonify({"ok": True, "launch_deadline": m["launch_deadline"],
                    "provinces": m["provinces"], "dealers": m["dealers"]})


@app.post("/api/preorder")
def api_preorder():
    """Validate a configuration and return a server-verified quote (no side effects)."""
    item = validate_config(request.get_json(silent=True) or {})
    quote = price_line(item)
    return jsonify({"ok": True, "quote": quote,
                    "terms": f"Fully refundable {cad(quote['unit_deposit'])} deposit. Pre-order pricing is locked "
                             "until delivery when reserved before the launch deadline."})


@app.get("/api/cart")
def api_cart_get():
    return jsonify(summarise(load_cart()))


@app.post("/api/cart")
def api_cart_add():
    item = validate_config(request.get_json(silent=True) or {})
    cart = load_cart()
    same = next((l for l in cart["items"] if all(l[k] == item[k] for k in
                 ("vehicle_id", "trim_id", "colour_id", "interior_id"))), None)
    current = sum(l["qty"] for l in cart["items"])
    if current + item["qty"] > MAX_VEHICLES_PER_ORDER:
        raise ValidationError(f"A single pre-order can include up to {MAX_VEHICLES_PER_ORDER} vehicles.", "qty")
    if same:
        if same["qty"] + item["qty"] > MAX_QTY_PER_LINE:
            raise ValidationError(f"You already have this configuration reserved (max {MAX_QTY_PER_LINE}).", "qty")
        same["qty"] += item["qty"]
        line_id = same["line_id"]
    else:
        line_id = secrets.token_hex(6)
        cart["items"].append({**item, "line_id": line_id})
    save_cart(cart)
    out = summarise(cart)
    out["added"] = line_id
    return jsonify(out), 201


@app.patch("/api/cart")
def api_cart_settings():
    """Update province and/or promo code. Promo codes are validated here."""
    body = request.get_json(silent=True) or {}
    cart = load_cart()
    if "province" in body:
        if body["province"] not in market()["provinces"]:
            raise ValidationError("Choose a valid province or territory.", "province")
        cart["province"] = body["province"]
    if "promo" in body:
        code = (body["promo"] or "").strip().upper()
        if not code:
            cart["promo"] = None
        elif code not in PROMOS:
            raise ValidationError("That code isn't valid.", "promo")
        elif PROMOS[code]["type"] == "expired":
            raise ValidationError("That code has expired.", "promo")
        else:
            cart["promo"] = code
    save_cart(cart)
    return jsonify(summarise(cart))


@app.patch("/api/cart/<line_id>")
def api_cart_update(line_id: str):
    body = request.get_json(silent=True) or {}
    cart = load_cart()
    line = next((l for l in cart["items"] if l["line_id"] == line_id), None)
    if not line:
        return jsonify({"ok": False, "error": "Item not found"}), 404
    try:
        qty = int(body.get("qty"))
    except (TypeError, ValueError):
        raise ValidationError("Quantity must be a number.", "qty") from None
    if not 1 <= qty <= MAX_QTY_PER_LINE:
        raise ValidationError(f"Quantity must be between 1 and {MAX_QTY_PER_LINE}.", "qty")
    others = sum(l["qty"] for l in cart["items"] if l is not line)
    if others + qty > MAX_VEHICLES_PER_ORDER:
        raise ValidationError(f"A single pre-order can include up to {MAX_VEHICLES_PER_ORDER} vehicles.", "qty")
    line["qty"] = qty
    save_cart(cart)
    return jsonify(summarise(cart))


@app.delete("/api/cart/<line_id>")
def api_cart_remove(line_id: str):
    cart = load_cart()
    before = len(cart["items"])
    cart["items"] = [l for l in cart["items"] if l["line_id"] != line_id]
    if len(cart["items"]) == before:
        return jsonify({"ok": False, "error": "Item not found"}), 404
    save_cart(cart)
    return jsonify(summarise(cart))


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^[0-9+()\-.\s]{7,20}$")
IDEM_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")


def _order_created(ref: str):
    return jsonify({"ok": True, "ref": ref, "redirect": url_for("confirmation", ref=ref)}), 201


@app.post("/api/checkout")
def api_checkout():
    body = request.get_json(silent=True) or {}
    # A retried submission (double click, flaky network) carries the same key:
    # answer with the order that was already created instead of a second one.
    idem = request.headers.get("Idempotency-Key", "").strip()
    idem = idem if IDEM_RE.match(idem) else None
    if idem:
        row = db().execute("SELECT ref FROM orders WHERE idem=?", (idem,)).fetchone()
        if row:
            return _order_created(row["ref"])
    cart = load_cart()
    if not cart["items"]:
        raise ValidationError("Your pre-order is empty.")
    name = str(body.get("name", "")).strip()
    email = str(body.get("email", "")).strip()
    phone = str(body.get("phone", "")).strip()
    province = str(body.get("province", "")).strip()
    dealer_id = str(body.get("dealer", "")).strip()
    if not 2 <= len(name) <= 80:
        raise ValidationError("Enter your full name.", "name")
    if not EMAIL_RE.match(email) or len(email) > 120:
        raise ValidationError("Enter a valid email address.", "email")
    if phone and not PHONE_RE.match(phone):
        raise ValidationError("Enter a valid phone number or leave it blank.", "phone")
    if province not in market()["provinces"]:
        raise ValidationError("Choose your province or territory.", "province")
    dealer = _find(market()["dealers"], dealer_id)
    if not dealer:
        raise ValidationError("Choose a delivery location.", "dealer")
    if dealer["province"] not in ("*", province):
        raise ValidationError("That location isn't in your province. Choose another or select home delivery.", "dealer")
    if body.get("consent") is not True:
        raise ValidationError("Please accept the pre-order terms.", "consent")

    cart["province"] = province
    summary = summarise(cart)
    ref = f"BYD-CA-{time.strftime('%y%m%d')}-{secrets.token_hex(3).upper()}"
    now = time.time()
    order = {
        "ref": ref, "created": time.strftime("%B %d, %Y", time.localtime(now)),
        "created_ts": now,
        "customer": {"name": name, "email": email, "phone": phone},
        "province": province, "province_name": market()["provinces"][province]["name"],
        "dealer": dealer["name"], "items": summary["items"], "totals": summary["totals"],
        "promo": summary["promo"],
    }
    try:
        db().execute("INSERT INTO orders(ref, created, data, idem) VALUES(?,?,?,?)",
                     (ref, now, json.dumps(order), idem))
    except sqlite3.IntegrityError:
        db().rollback()  # a concurrent request with the same key won the race
        row = db().execute("SELECT ref FROM orders WHERE idem=?", (idem,)).fetchone()
        if row:
            return _order_created(row["ref"])
        raise
    # Queue the Google Sheets row in the same transaction. Delivery happens in
    # the background; nothing here may stop the customer's confirmation.
    try:
        sheets_logger.enqueue(db(), order)
    except Exception:  # noqa: BLE001
        sheets_logger.log.exception("Could not queue order %s for Google Sheets", ref)
    save_cart({**EMPTY_CART, "province": province})  # commits order + job + cart
    sheets_logger.wake()
    return _order_created(ref)


# --------------------------------------------------------------------- admin
def _admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", "").strip()


def _csrf_token() -> str:
    return hmac.new(_admin_token().encode(), b"sheets-admin-csrf", hashlib.sha256).hexdigest()


def _require_admin() -> None:
    """HTTP Basic auth (any username, password = ADMIN_TOKEN). Hidden if unset."""
    token = _admin_token()
    if len(token) < 12:
        abort(404)
    auth = request.authorization
    supplied = (auth.password or "") if auth else ""
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        resp = make_response("Authentication required.", 401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="BYD showroom admin", charset="UTF-8"'
        abort(resp)
    if request.method == "POST" and not hmac.compare_digest(
            request.form.get("csrf", "").encode(), _csrf_token().encode()):
        abort(400)


def _admin_response(html: str):
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@app.get("/admin/sheets")
def admin_sheets():
    _require_admin()
    data = sheets_logger.stats(DB_FILE)
    fmt = lambda ts: time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else ""  # noqa: E731
    return _admin_response(render_template(
        "admin_sheets.html", page="admin", backend=sheets_logger.describe_backend(),
        stats=data, fmt_time=fmt, csrf=_csrf_token(), headers=sheets_logger.HEADERS,
        notice=request.args.get("notice", ""), notice_ok=request.args.get("ok") == "1"))


@app.post("/admin/sheets/retry")
def admin_sheets_retry():
    _require_admin()
    count = sheets_logger.retry_failed(DB_FILE)
    sheets_logger.wake()
    return redirect(url_for("admin_sheets", ok=1,
                            notice=f"Re-queued {count} failed order(s). They are being sent now."), 303)


@app.post("/admin/sheets/check")
def admin_sheets_check():
    _require_admin()
    try:
        backend = sheets_logger.get_backend()
        if backend is None:
            raise sheets_logger.SheetsError("Not configured. Add credentials to .env and restart.")
        message, ok = backend.check(), True
        sheets_logger.wake()
    except Exception as exc:  # noqa: BLE001 - shown to the admin, never to customers
        message, ok = f"Connection failed: {exc}", False
        sheets_logger.log.error("Admin connection test failed: %s", exc)
    return redirect(url_for("admin_sheets", ok=int(ok), notice=message), 303)


# -------------------------------------------------------- image proxy + cache
@lru_cache(maxsize=1)
def _manifest_index() -> dict:
    if not MANIFEST_FILE.exists():
        return {}
    return {r["file"].removeprefix("static/images/vehicles/"): r
            for r in json.loads(MANIFEST_FILE.read_text())}


def _fetch_and_cache(url: str, dest: Path, max_w: int = 1600) -> bool:
    """Download an allow-listed image, resize, store as WebP. Returns success."""
    if urlparse(url).hostname not in ALLOWED_IMAGE_HOSTS:
        return False
    try:
        from PIL import Image  # local import keeps app start fast
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[3])
            im = bg
        else:
            im = im.convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, round(im.height * max_w / im.width)))
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "WEBP", quality=80)
        return True
    except Exception:  # noqa: BLE001 — any failure falls back to the SVG
        return False


def _fallback():
    resp = make_response(send_file(FALLBACK_SVG, mimetype="image/svg+xml", max_age=300))
    resp.headers["X-Image-Fallback"] = "1"
    return resp


@app.get("/img/vehicles/<path:rel>")
def img_vehicle(rel: str):
    dest = (IMG_DIR / rel).resolve()
    if IMG_DIR.resolve() not in dest.parents:
        abort(404)
    if not dest.exists():
        rec = _manifest_index().get(rel)
        if not rec or not _fetch_and_cache(rec["source_url"], dest):
            return _fallback()
    return send_file(dest, mimetype="image/webp", max_age=60 * 60 * 24 * 7)


@app.get("/img/proxy")
def img_proxy():
    src = request.args.get("src", "")
    if urlparse(src).hostname not in ALLOWED_IMAGE_HOSTS:
        return _fallback()
    dest = CACHE_DIR / (hashlib.sha1(src.encode()).hexdigest() + ".webp")
    if not dest.exists() and not _fetch_and_cache(src, dest):
        return _fallback()
    return send_file(dest, mimetype="image/webp", max_age=60 * 60 * 24 * 7)


init_db()
sheets_logger.start_worker(DB_FILE)

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 5000)), debug=False)
