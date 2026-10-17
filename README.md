# BYD Canada — Virtual Showroom

A multi-page virtual showroom and pre-order experience for BYD's Canadian
launch lineup. It has an HTML/CSS/JS front end (no framework, no animation
library) and a Python Flask backend with SQLite for carts and orders.

> **Demonstration project.** Prices are estimated Canadian MSRPs. Pre-order
> discounts, promo codes and dealer locations are illustrative. No payment is
> taken. Vehicle photography © BYD Auto Co., Ltd.; see `image_sources.md`.

---

## Quick start

```bash
cd byd-showroom
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py            # serves http://0.0.0.0:5000
```

The SQLite database (`data/showroom.db`) is created on first run.

Environment variables (optional):

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `5000` | HTTP port |
| `HOST` | `0.0.0.0` | Bind address |
| `SHEETS_*`, `GOOGLE_SERVICE_ACCOUNT_*`, `ADMIN_TOKEN` | empty | Google Sheets order logging and its admin page. See below |

Settings can also go in a `.env` file next to `app.py` (copy `.env.example`).
Real environment variables take precedence. `.env` is git-ignored and never served.

## Google Sheets order logging

Every successful checkout is written to a Google Sheet, **one row per vehicle**,
with these columns: Order Reference Number, Date & Time, Customer Name, Email Address,
Province, Selected Dealer, Vehicle Model, Trim, Color, Deposit Amount, Discount
Applied, Subtotal, Tax (GST/PST), Total Amount. These are followed by Quantity, Interior,
Promo Code, Tax Breakdown, Phone and Line Item.

- **Server-side only.** The checkout form posts to `/api/checkout` with `fetch()`.
  Python talks to Google; no URL, key or secret reaches the browser.
- **Never blocks the customer.** The order and a "log to sheet" job are saved in
  one transaction and the confirmation is shown immediately. A background worker
  delivers the row and retries failures with backoff (30 s to 12 h, 8 attempts).
- **Errors are logged for the admin** in `logs/sheets.log` and at `/admin/sheets`
  (HTTP Basic auth, password `ADMIN_TOKEN`). The admin page has *Test connection*
  and *Retry failed orders* buttons.
- **No duplicates.** An `Idempotency-Key` per checkout attempt, plus a
  reference-number check in the sheet.

Two ways to connect:
1. **Apps Script web app** (recommended, about 5 min): paste
   `integrations/google_sheets/Code.gs` into the sheet's Apps Script and deploy it as a Web app.
   Then set `SHEETS_WEBHOOK_URL` + `SHEETS_WEBHOOK_SECRET`. Requests are HMAC-signed.
2. **Sheets API service account:** set `GOOGLE_SERVICE_ACCOUNT_FILE` (or `_JSON`)
   + `SHEETS_SPREADSHEET_ID`, then share the sheet with the service account email.

**Step-by-step instructions: [docs/google-sheets-setup.md](docs/google-sheets-setup.md).**

```bash
python sheets_logger.py check      # test the connection (writes nothing)
python sheets_logger.py status     # queue counts and recent errors
python sheets_logger.py backfill   # send orders placed before logging was enabled
python sheets_logger.py retry      # re-send orders that gave up
```

---

## Pages

| Route | Page | Highlights |
|---|---|---|
| `/` | Home | Hero, launch countdown, featured lineup, Blade Battery value props, featured model, how pre-orders work, FAQ |
| `/showroom` | Showroom | Server-side filters (body, price, range, seating), search, sort, URL-synced state, compare tray (up to 3) |
| `/vehicle/<id>` | Vehicle detail | Inspection viewer with hotspots, trim / paint / interior configurator, live + server-verified pricing, spec sheet, gallery lightbox |
| `/compare?ids=a,b,c` | Compare | Three slots, grouped spec table, best value per row highlighted |
| `/cart` | Pre-order | Line items, quantity limits, promo codes, GST/HST/PST/QST by province, dealer picker filtered by province, validated checkout |
| `/confirmation/<ref>` | Confirmation | Order reference (copy), reserved vehicles, totals, next-steps timeline, print styles |

Every page shares the same sticky header (logo, centred menu, theme toggle,
cart), footer, cart drawer and toast region (`templates/base.html`).

## API

All responses are JSON. Errors return `{"ok": false, "error": "...", "field": "..."}`
with status 404 or 422.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/vehicles` | Lineup. Query: `body` (csv), `max_price`, `min_range`, `seats`, `q`, `sort` (`price-asc`, `price-desc`, `range-desc`, `power-desc`, `name`) |
| GET | `/api/vehicles/<id>` | Full vehicle record |
| GET | `/api/colors/<id>` | Paints, with `source: photo / simulated` and image paths |
| GET | `/api/interiors/<id>` | Interiors, with `real` flag and material swatches |
| GET | `/api/meta` | Provinces, tax rates, dealers, launch deadline |
| POST | `/api/preorder` | Validate and price a configuration (no side effects) |
| GET | `/api/cart` | Current cart summary (server-priced) |
| POST | `/api/cart` | Add `{vehicle_id, trim_id, colour_id, interior_id, qty}` |
| PATCH | `/api/cart` | `{province?, promo?}`; promo codes are validated here |
| PATCH | `/api/cart/<line_id>` | `{qty}` |
| DELETE | `/api/cart/<line_id>` | Remove a line |
| POST | `/api/checkout` | `{name, email, phone?, province, dealer, consent}` → `{ref, redirect}`. Optional `Idempotency-Key` header makes retries return the same order. Queues the Google Sheets row |
| GET | `/admin/sheets` | Sheets logging status (Basic auth with `ADMIN_TOKEN`; 404 if unset) |
| POST | `/admin/sheets/check`, `/admin/sheets/retry` | Test the connection / re-queue failed rows (CSRF-protected) |
| GET | `/img/vehicles/<path>` | Local image. If missing, re-fetched from the manifest source, then the labelled fallback SVG |
| GET | `/img/proxy?src=<url>` | Allow-listed image proxy with local WebP cache (`static/images/cache/`) |

The cart is identified by an `X-Cart-Id` header (kept in `localStorage`), with
a cookie fallback, so it works in embedded previews where cookies are blocked.

**Server-side rules:**
- configurations must match valid trim/paint/interior ids
- max 2 of a configuration, 3 vehicles per order
- the dealer must be in the buyer's province, or home delivery
- consent is required

**Refundable deposit:** $2,000 per vehicle, set by `DEPOSIT` in `tools/build_data.py`
(or per model in each vehicle's `preorder` block). Page copy reads "from" the lowest
deposit automatically.

**Demo promo codes:**
- `BYDLAUNCH`: $500 off per vehicle
- `CANADAEV`: 2% off MSRP, max $1,000 per vehicle
- `EARLYBIRD`: expired, to show the error state

## Project structure

```
app.py                     Flask app: pages, API, validation, pricing, image proxy, admin
sheets_logger.py           Google Sheets logging: row builder, Apps Script + Sheets API backends, outbox worker, CLI
integrations/google_sheets/Code.gs   Apps Script web app that receives signed rows
docs/google-sheets-setup.md          Step-by-step Google Sheets setup and troubleshooting
.env.example               Template for server-side settings (copy to .env)
credentials/               Service-account key location (git-ignored)
logs/sheets.log            Sheets delivery log (created at runtime, git-ignored)
templates/                 base.html (shell), macros.html (icon, vehicle_card), one template per page, admin_sheets.html
static/css/
  tokens.css               Design tokens: colour, type, 8px spacing, radius, shadow, motion; dark theme
  base.css                 Reset, typography, layout, header, mobile nav, footer
  components.css           Buttons, badges, cards, forms, swatches, drawer, lightbox, toast, countdown…
  pages.css                Page layouts (home, showroom, vehicle, compare, cart, confirmation, print)
  motion.css               Load/scroll reveals, keyframes, prefers-reduced-motion
static/js/
  main.js                  Entry: boots theme, motion and cart, lazy-loads the page module
  api.js, format.js, icons.js, theme.js, toast.js
  motion.js                Staggered load, IntersectionObserver reveals, header shrink, countdowns
  cart.js                  Cart store (server is source of truth) + accessible drawer
  viewer.js                Inspection viewer: photo sequence, drag/keys, hotspots, crossfade
  configurator.js          Canvas recolour engine + configurator (pricing, URL state, verification)
  lightbox.js              Gallery lightbox
  pages/*.js               showroom, vehicle, compare, cart, confirmation
static/icons/sprite.svg    63 inline SVG icons (24px grid, 1.5px stroke, currentColor), inlined once per page
static/images/brand/       Official BYD logo (byd-logo.png), favicons, Apple touch icon
static/images/vehicles/<model>/<colour>/1.webp   front three-quarter
static/images/vehicles/<model>/<colour>/2.webp   profile
static/images/vehicles/<model>/{interior,interior-detail,exterior-detail,tech,charging,dimension,swatches,hero}/
static/fonts/              Inter variable (self-hosted)
data/vehicles.json         Generated vehicle and market data (do not edit by hand)
tools/build_data.py        Source of truth for vehicle data → writes data/vehicles.json
tools/fetch_images.py      Downloads official images, writes data/image_manifest.json and image_sources.md
image_sources.md           Source URL and licence note for every image
```

## Imagery and fallbacks

All primary vehicle photography is official BYD imagery from byd.com (EU
model pages and configurator), cached locally as WebP. Nothing is fabricated.
Where official imagery doesn't exist, the UI uses a clearly labelled fallback:

| Situation | Fallback | Label shown |
|---|---|---|
| Paint without an official photo (Han: Graphite Black, Arctic White, Time Grey, Crimson Red) | **Option A:** the official Ocean Blue photo is recoloured on a `<canvas>` (hue-band mask; shading and highlights preserved) | "Colour simulation" badge on the viewer, "(colour simulation)" in names, alt text and the cart |
| Interior trim without a photo | **Option C:** the real base interior photo plus a material swatch legend (seats, dashboard, trim) | "Material preview" badge and an explanatory note |
| Paint without an official swatch chip (Tang) | CSS colour chip from the paint's hex value | (decorative only) |
| Image missing and source unreachable | `static/images/fallback.svg` | "Image unavailable" |

To refresh images, run `python tools/fetch_images.py`. To change vehicle data,
edit `tools/build_data.py` and run `python tools/build_data.py`.

## Design system

- **Colour:** BYD red `#D0142C` (accent text uses a darker AA-compliant red), near-black, white and a neutral grey ramp. Dark theme via `[data-theme="dark"]` on `<html>`, persisted in `localStorage` and applied before first paint.
- **Type:** Inter variable, self-hosted. Fluid display sizes and tabular numerals for prices and specs.
- **Spacing:** 8px grid (`--sp-1` = 8px … `--sp-12` = 96px).
- **Breakpoints:** mobile-first, with layouts checked at 360, 768, 1024 and 1440px.
- **Icons:** one SVG sprite. No emoji anywhere.

## Motion

- **Easing:** `cubic-bezier(0.22, 1, 0.36, 1)` throughout. Durations are 150–700ms, and only transform and opacity are animated.
- **Page load:** hero and page-head elements reveal in a stagger (80ms apart).
- **Scroll:** IntersectionObserver reveals (fade-up with slight scale), cascading within grids.
- **Header:** blurs and shrinks on scroll; menu underlines slide in on hover or for the active page.
- **Cards:** lift with a shadow on hover, and the image zooms slowly.
- **Configurator:** viewer crossfades between images, swatches ripple, the price total ticks, and spec values flash when the trim changes.
- **Cart:** the drawer slides in over a blurred backdrop and its items animate in sequence; the badge bumps; lines animate in and out.
- **Buttons:** press scale; primary CTAs have a sheen sweep.
- **Countdown:** digits flip as they change; the separators pulse.
- **Loading:** skeleton shimmer while the showroom loads.
- **Reduced motion:** `prefers-reduced-motion: reduce` disables all non-essential motion.

## Accessibility

- **Navigation:** a skip link, landmark regions and `aria-current` on the nav.
- **Focus:** visible focus rings (`:focus-visible`). The drawer and lightbox trap focus, close with Esc and restore focus afterwards.
- **Viewer:** tabs follow the WAI-ARIA tab pattern. Hotspots are buttons with `aria-expanded`. The stage responds to ←/→.
- **Configurator:** paint swatches are an ARIA radiogroup with roving tabindex and arrow-key navigation.
- **Forms:** labelled fields, inline errors linked with `aria-describedby`, `aria-invalid`, and focus moves to the first error.
- **Live regions:** result counts, toasts and cart updates are announced.
- **Contrast:** AA for text in both themes.

## Production notes

- Run behind a WSGI server (for example `gunicorn -w 2 -b 0.0.0.0:5000 app:app`).
- Swap SQLite for Postgres if you need multiple instances.
- Each gunicorn worker runs its own Sheets delivery thread. Jobs are claimed atomically, so rows are not sent twice.
- Serve over HTTPS so the admin page's Basic-auth password is encrypted.
- Real deposits would need a payment provider (for example Stripe PaymentIntents) in `/api/checkout`, plus email delivery.
- Confirm image licensing with BYD Canada before any public deployment; see `image_sources.md`.
