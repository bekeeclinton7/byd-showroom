"""
build_data.py — Generates data/vehicles.json (the showroom's vehicle data store).

Specs are taken from BYD Europe's published technical data (WLTP figures).
Canadian prices are *estimated* launch MSRPs (CAD) based on public reporting
(BYD has not published official Canadian pricing). Run:

    python tools/build_data.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG = "/img/vehicles"  # served by the image proxy/cache route in app.py


def trim(tid, name, price, **spec):
    return {"id": tid, "name": name, "price": price, "spec": spec}


def colour(cid, name, hex_, price=0, *, model, views=2, swatch=True, source="photo"):
    """A paint option. source='photo' => real BYD photos exist for this colour.
    source='simulated' => configurator recolours the base photo on a canvas."""
    if source == "photo":
        images = [f"{IMG}/{model}/{cid}/{i}.webp" for i in range(1, views + 1)]
    else:
        images = []
    return {"id": cid, "name": name, "hex": hex_, "price": price, "source": source,
            "images": images,
            "swatch": f"{IMG}/{model}/swatches/{cid}.webp" if swatch and source == "photo" else None}


def interior(iid, name, price, seat, dash, trim_, *, photo, real):
    """An interior option. real=False => Option C: real base photo + swatch overlay."""
    return {"id": iid, "name": name, "price": price, "real": real, "photo": photo,
            "materials": [
                {"part": "Seats", "name": seat[0], "hex": seat[1]},
                {"part": "Dashboard", "name": dash[0], "hex": dash[1]},
                {"part": "Trim & accents", "name": trim_[0], "hex": trim_[1]},
            ]}


def hs(x, y, title, text, icon="info"):
    return {"x": x, "y": y, "title": title, "text": text, "icon": icon}


# Refundable pre-order deposit per vehicle (CAD). Set per model in "preorder"
# if tiers are ever needed; the UI reads "from <lowest deposit>" automatically.
DEPOSIT = 2000

GALLERY_SIZE = 9  # 1 feature tile (2x2) + 8 tiles = complete rows at 4 and 2 columns


def gallery(model, items):
    """Photo gallery. Technical renders on white (tech/, dimension/) are shown
    with object-fit: contain and are dropped first when trimming to GALLERY_SIZE."""
    out = [{"src": f"{IMG}/{model}/{p}", "caption": c,
            "fit": "contain" if p.startswith(("tech/", "dimension/")) else "cover"} for p, c in items]
    while len(out) > GALLERY_SIZE and any(g["fit"] == "contain" for g in out):
        idx = max(i for i, g in enumerate(out) if g["fit"] == "contain")
        out.pop(idx)
    return out[:GALLERY_SIZE]


VEHICLES = []

# ---------------------------------------------------------------- Seagull
m = "seagull"
VEHICLES.append({
    "id": m, "name": "Seagull", "full_name": "BYD Seagull",
    "tagline": "Small footprint. Big personality.",
    "body": "Hatchback", "seats": 4, "status": "Launch lineup", "delivery": "Late 2026",
    "note": "Sold in Europe as the BYD Dolphin Surf.",
    "summary": "A nimble city EV with Blade Battery safety, a rotating 10.1-inch touchscreen and up to 322 km of range — the most accessible way into a BYD.",
    "preorder": {"deposit": DEPOSIT, "discount": 1000},
    "dimensions": {"length": 3990, "width": 1720, "height": 1590, "wheelbase": 2500},
    "cargo_l": 308, "warranty": "8 yr / 160,000 km battery",
    "trims": [
        trim("active", "Active", 24990, battery_kwh=30.1, range_km=220, power_hp=88, power_kw=65, torque_nm=175, accel_s=12.1, drive="FWD", dc_kw=65, dc_time="30–80% in 24 min", ac_kw=11, top_speed=130),
        trim("boost", "Boost", 27990, battery_kwh=43.2, range_km=322, power_hp=88, power_kw=65, torque_nm=175, accel_s=11.1, drive="FWD", dc_kw=85, dc_time="30–80% in 23 min", ac_kw=11, top_speed=130),
        trim("comfort", "Comfort", 30490, battery_kwh=43.2, range_km=310, power_hp=156, power_kw=115, torque_nm=220, accel_s=9.1, drive="FWD", dc_kw=85, dc_time="30–80% in 23 min", ac_kw=11, top_speed=150),
    ],
    "colours": [
        colour("apricity-white", "Apricity White", "#ece8df", model=m),
        colour("ice-blue", "Ice Blue", "#a9c4e2", model=m),
        colour("lemon-green", "Lemon Green", "#c9dc3a", 500, model=m),
        colour("polar-night-black", "Polar Night Black", "#1d1f23", model=m),
    ],
    "interiors": [
        interior("ocean", "Ocean Blue & Black", 0, ("Black vegan leather", "#1c1f24"), ("Ocean Blue soft-touch", "#1f5fa8"), ("Gloss black", "#111317"), photo=f"{IMG}/{m}/interior/1.webp", real=True),
        interior("graphite", "Graphite & Lime", 350, ("Graphite vegan leather", "#3a3d42"), ("Charcoal soft-touch", "#2a2c30"), ("Lime stitching", "#c9dc3a"), photo=f"{IMG}/{m}/interior/1.webp", real=False),
    ],
    "hotspots": {
        "front": [hs(27, 46, "LED headlights", "Full-LED headlamps with signature light graphic.", "eye"),
                  hs(45, 60, "16-inch alloys", "Aero-optimised 16-inch alloy wheels.", "gauge"),
                  hs(40, 31, "Compact cabin", "Four seats and 308 L of cargo in under 4 metres.", "users"),
                  hs(68, 56, "Blade Battery", "LFP Blade Battery integrated under the floor for a low centre of gravity.", "battery")],
        "profile": [hs(31, 63, "Front-wheel drive", "Up to 156 hp from a compact e-Platform motor.", "zap"),
                    hs(52, 31, "Panoramic glass", "Expansive glasshouse for an airy, bright cabin.", "eye"),
                    hs(70, 41, "Tail lights", "Full-width LED tail light signature.", "eye"),
                    hs(50, 64, "Low floor battery", "43.2 kWh Blade Battery (Boost/Comfort).", "battery")],
        "interior": [hs(65, 50, "10.1-inch rotating screen", "Rotates between landscape and portrait.", "maximize"),
                     hs(38, 45, "Digital cluster", "7-inch digital driver display.", "gauge"),
                     hs(60, 74, "Wireless charging", "Phone charging pad in the centre console.", "zap")],
    },
    "gallery": gallery(m, [("ice-blue/1.webp", "Ice Blue, front three-quarter"), ("exterior-detail/1.webp", "Side detail"), ("exterior-detail/2.webp", "Front detail"), ("exterior-detail/3.webp", "Rear spoiler and lights"), ("interior/1.webp", "Cockpit"), ("interior/2.webp", "Driver's seat"), ("interior-detail/1.webp", "Rotating touchscreen"), ("interior-detail/3.webp", "Seating"), ("charging/1.webp", "Charging"), ("tech/1.webp", "Blade Battery"), ("dimension/1.webp", "Dimensions")]),
    "details": [f"{IMG}/{m}/exterior-detail/{i}.webp" for i in (1, 2, 3)],
    "hero_image": f"{IMG}/{m}/charging/1.webp",
})

# ---------------------------------------------------------------- Dolphin
m = "dolphin"
VEHICLES.append({
    "id": m, "name": "Dolphin", "full_name": "BYD Dolphin",
    "tagline": "The everyday EV, refined.",
    "body": "Hatchback", "seats": 5, "status": "Launch lineup", "delivery": "Late 2026",
    "note": None,
    "summary": "A spacious five-seat hatchback on the e-Platform 3.0 with up to 427 km of WLTP range, a heat pump for Canadian winters and Vehicle-to-Load.",
    "preorder": {"deposit": DEPOSIT, "discount": 1500},
    "dimensions": {"length": 4290, "width": 1770, "height": 1570, "wheelbase": 2700},
    "cargo_l": 345, "warranty": "8 yr / 160,000 km battery",
    "trims": [
        trim("active", "Active", 32990, battery_kwh=44.9, range_km=340, power_hp=95, power_kw=70, torque_nm=180, accel_s=12.3, drive="FWD", dc_kw=60, dc_time="30–80% in 30 min", ac_kw=11, top_speed=150),
        trim("comfort", "Comfort", 36490, battery_kwh=60.4, range_km=427, power_hp=204, power_kw=150, torque_nm=310, accel_s=7.0, drive="FWD", dc_kw=88, dc_time="30–80% in 29 min", ac_kw=11, top_speed=160),
        trim("design", "Design", 38490, battery_kwh=60.4, range_km=427, power_hp=204, power_kw=150, torque_nm=310, accel_s=7.0, drive="FWD", dc_kw=88, dc_time="30–80% in 29 min", ac_kw=11, top_speed=160),
    ],
    "colours": [
        colour("cream-white", "Cream White", "#ecebe6", model=m),
        colour("urban-grey", "Urban Grey", "#7c838b", model=m),
        colour("obsidian-black", "Obsidian Black", "#1b1c20", model=m),
    ],
    "interiors": [
        interior("graphite", "Graphite Black", 0, ("Black vegan leather", "#24272c"), ("Dark grey soft-touch", "#3b4047"), ("Satin silver", "#a7adb4"), photo=f"{IMG}/{m}/interior/1.webp", real=True),
        interior("coral", "Black & Coral", 400, ("Black vegan leather", "#24272c"), ("Coral pink panels", "#e0817a"), ("Coral stitching", "#e0817a"), photo=f"{IMG}/{m}/interior/1.webp", real=False),
    ],
    "hotspots": {
        "front": [hs(37, 47, "Ocean X face", "LED headlights with the signature Ocean X front design.", "eye"),
                  hs(56, 59, "17-inch alloys", "Aero alloy wheels (Comfort/Design).", "gauge"),
                  hs(45, 33, "Glass roof", "Panoramic glass roof on the Design trim.", "eye"),
                  hs(71, 57, "Heat pump", "Standard heat pump improves winter efficiency.", "snowflake")],
        "profile": [hs(31, 60, "e-Platform 3.0", "Integrated 8-in-1 electric powertrain.", "zap"),
                    hs(52, 35, "2,700 mm wheelbase", "Mid-size cabin space in a compact footprint.", "ruler"),
                    hs(72, 46, "Light-blade tails", "Connected LED rear light bar.", "eye"),
                    hs(53, 62, "Blade Battery", "Up to 60.4 kWh LFP Blade Battery.", "battery")],
        "interior": [hs(55, 40, "12.8-inch rotating screen", "Rotating infotainment with Apple CarPlay and Android Auto.", "maximize"),
                     hs(32, 50, "Multifunction wheel", "Heated steering wheel (Comfort/Design).", "gauge"),
                     hs(25, 85, "Heated front seats", "Vegan leather seats, heated and power-adjustable.", "armchair")],
    },
    "gallery": gallery(m, [("urban-grey/1.webp", "Urban Grey, front three-quarter"), ("exterior-detail/1.webp", "Seaside, front"), ("exterior-detail/2.webp", "Seaside, rear"), ("interior/1.webp", "Cockpit"), ("interior/2.webp", "Rear seats"), ("interior/3.webp", "Cargo space"), ("interior-detail/1.webp", "Dashboard"), ("interior-detail/3.webp", "Glass roof"), ("charging/1.webp", "Charging"), ("tech/1.webp", "Blade Battery"), ("dimension/1.webp", "Dimensions")]),
    "details": [f"{IMG}/{m}/exterior-detail/{i}.webp" for i in (1, 2)],
    "hero_image": f"{IMG}/{m}/charging/1.webp",
})

# ---------------------------------------------------------------- Atto 3
m = "atto-3"
VEHICLES.append({
    "id": m, "name": "Atto 3", "full_name": "BYD Atto 3",
    "tagline": "The compact SUV, electrified.",
    "body": "SUV", "seats": 5, "status": "Launch lineup", "delivery": "Late 2026",
    "note": "Extended Range trims are based on the Atto 3 Evo.",
    "summary": "A five-seat compact SUV with a 490 L cargo area. Extended Range trims add a 74.8 kWh battery, 220 kW charging and up to 449 hp all-wheel drive.",
    "preorder": {"deposit": DEPOSIT, "discount": 2000},
    "dimensions": {"length": 4455, "width": 1875, "height": 1615, "wheelbase": 2720},
    "cargo_l": 490, "warranty": "8 yr / 160,000 km battery",
    "trims": [
        trim("standard", "Standard Range", 38990, battery_kwh=60.5, range_km=420, power_hp=204, power_kw=150, torque_nm=310, accel_s=7.3, drive="FWD", dc_kw=88, dc_time="30–80% in 29 min", ac_kw=11, top_speed=160),
        trim("design", "Extended Range RWD", 44990, battery_kwh=74.8, range_km=510, power_hp=313, power_kw=230, torque_nm=380, accel_s=5.5, drive="RWD", dc_kw=220, dc_time="10–80% in 25 min", ac_kw=11, top_speed=180),
        trim("excellence", "Extended Range AWD", 50990, battery_kwh=74.8, range_km=470, power_hp=449, power_kw=330, torque_nm=560, accel_s=3.9, drive="AWD", dc_kw=220, dc_time="10–80% in 25 min", ac_kw=11, top_speed=200),
    ],
    "colours": [
        colour("atlantis-blue", "Atlantis Blue", "#4f6f9a", model=m),
        colour("iris-blue", "Iris Blue", "#2d5bb0", 650, model=m),
        colour("ruby-red", "Ruby Red", "#b81d2c", 650, model=m),
        colour("time-grey", "Time Grey", "#6c737b", model=m),
        colour("skiing-white", "Ski White", "#e9ebec", model=m),
        colour("obsidian-black", "Obsidian Black", "#1b1d22", model=m),
    ],
    "interiors": [
        interior("dawn", "Dawn Beige", 0, ("Beige vegan leather", "#d9cdb8"), ("Beige & black two-tone", "#c8bba4"), ("Bronze accents", "#8a6a45"), photo=f"{IMG}/{m}/interior/3.webp", real=True),
        interior("midnight", "Midnight Black", 0, ("Black vegan leather", "#202226"), ("Black soft-touch", "#2a2c31"), ("Dark chrome", "#6c7178"), photo=f"{IMG}/{m}/interior/3.webp", real=False),
    ],
    "hotspots": {
        "front": [hs(39, 43, "Dragon Face LED", "Full-LED headlights with the Dragon Face design.", "eye"),
                  hs(52, 59, "18-inch alloys", "Two-tone machined alloy wheels.", "gauge"),
                  hs(46, 28, "Panoramic sunroof", "Electric panoramic sunroof with shade.", "eye"),
                  hs(69, 57, "AWD option", "Dual-motor AWD with 449 hp on Extended Range AWD.", "zap")],
        "profile": [hs(31, 59, "Rear-wheel drive", "Extended Range trims move to a 313 hp rear motor.", "zap"),
                    hs(52, 30, "Roof rails", "Integrated roof rails for Canadian adventures.", "route"),
                    hs(73, 40, "Through-type tail light", "Full-width LED rear signature.", "eye"),
                    hs(48, 62, "74.8 kWh Blade Battery", "Cell-to-Body Blade Battery in Extended Range trims.", "battery")],
        "interior": [hs(68, 63, "15.6-inch screen", "Rotating 15.6-inch infotainment display.", "maximize"),
                     hs(45, 53, "Driver display", "8.8-inch digital cluster and available head-up display.", "gauge"),
                     hs(64, 80, "Signature vents", "Sculpted console with wireless phone charging.", "zap")],
    },
    "gallery": gallery(m, [("atlantis-blue/1.webp", "Atlantis Blue, front three-quarter"), ("exterior-detail/1.webp", "Front"), ("exterior-detail/2.webp", "Wheel detail"), ("charging/1.webp", "Charging at home"), ("interior/3.webp", "Cockpit"), ("interior/2.webp", "Centre console"), ("interior-detail/1.webp", "Dashboard"), ("interior-detail/2.webp", "Rear seats"), ("interior/1.webp", "Rear vents"), ("tech/1.webp", "Platform"), ("dimension/1.webp", "Dimensions")]),
    "details": [f"{IMG}/{m}/exterior-detail/{i}.webp" for i in (1, 2)],
    "hero_image": f"{IMG}/{m}/charging/1.webp",
})

# ---------------------------------------------------------------- Seal
m = "seal"
VEHICLES.append({
    "id": m, "name": "Seal", "full_name": "BYD Seal",
    "tagline": "The electric sports sedan.",
    "body": "Sedan", "seats": 5, "status": "Launch lineup", "delivery": "Late 2026",
    "note": None,
    "summary": "A low, sleek sports sedan with Cell-to-Body construction, up to 570 km of range and 530 hp all-wheel drive that reaches 100 km/h in 3.8 seconds.",
    "preorder": {"deposit": DEPOSIT, "discount": 2500},
    "dimensions": {"length": 4800, "width": 1875, "height": 1460, "wheelbase": 2920},
    "cargo_l": 453, "warranty": "8 yr / 160,000 km battery",
    "trims": [
        trim("design", "Design RWD", 44990, battery_kwh=82.5, range_km=570, power_hp=313, power_kw=230, torque_nm=360, accel_s=5.9, drive="RWD", dc_kw=150, dc_time="30–80% in 26 min", ac_kw=11, top_speed=180),
        trim("excellence", "Excellence AWD", 54990, battery_kwh=82.5, range_km=520, power_hp=530, power_kw=390, torque_nm=670, accel_s=3.8, drive="AWD", dc_kw=150, dc_time="30–80% in 26 min", ac_kw=11, top_speed=180),
    ],
    "colours": [
        colour("atlantis-grey", "Atlantis Grey", "#6f7f93", model=m),
        colour("ruby-red", "Ruby Red", "#b3121f", 750, model=m),
        colour("lavender-grey", "Lavender Grey", "#8f8798", 750, model=m),
        colour("indigo-grey", "Indigo Grey", "#9a9ca3", model=m),
        colour("polar-white", "Polar White", "#eef0f2", model=m),
        colour("obsidian-black", "Obsidian Black", "#1b1d22", model=m),
    ],
    "interiors": [
        interior("obsidian", "Obsidian Black Nappa", 0, ("Black Nappa leather", "#1c1d21"), ("Black suede-wrapped dash", "#25272b"), ("Crystal gear selector", "#c9d4de"), photo=f"{IMG}/{m}/interior/1.webp", real=True),
        interior("stone", "Stone Grey Nappa", 900, ("Stone grey Nappa", "#a7a49d"), ("Charcoal dash", "#2f3135"), ("Satin silver", "#b8bcc2"), photo=f"{IMG}/{m}/interior/1.webp", real=False),
    ],
    "hotspots": {
        "front": [hs(35, 47, "Ocean Aesthetics lights", "Full-LED headlights with water-drop daytime running lights.", "eye"),
                  hs(49, 57, "19-inch alloys", "Performance wheels with ventilated discs.", "gauge"),
                  hs(46, 33, "Glass roof", "Full panoramic glass roof with UV and IR protection.", "eye"),
                  hs(72, 56, "Cell-to-Body", "Blade Battery forms part of the body structure.", "battery")],
        "profile": [hs(31, 59, "AWD performance", "Dual motors, 530 hp, 0–100 km/h in 3.8 s (Excellence).", "zap"),
                    hs(60, 34, "Cd 0.219", "Coupe roofline delivers an exceptionally low drag coefficient.", "route"),
                    hs(82, 44, "Light-band tail", "Wave-pattern full-width LED tail lights.", "eye"),
                    hs(53, 62, "82.5 kWh battery", "Up to 570 km WLTP range on a single charge.", "battery")],
        "interior": [hs(55, 45, "15.6-inch rotating screen", "Rotating display with voice assistant and OTA updates.", "maximize"),
                     hs(48, 64, "Crystal gear selector", "Crystal-finish selector on a floating console.", "sparkle"),
                     hs(60, 86, "Nappa sport seats", "Heated and ventilated front seats with diamond quilting.", "armchair"),
                     hs(75, 62, "Ambient lighting", "Multi-colour ambient lighting throughout the cabin.", "sun")],
    },
    "gallery": gallery(m, [("ruby-red/1.webp", "Ruby Red, front three-quarter"), ("exterior-detail/1.webp", "Studio, front three-quarter"), ("exterior-detail/2.webp", "Studio, front"), ("exterior-detail/3.webp", "Studio, rear three-quarter"), ("interior/1.webp", "Cockpit"), ("interior/2.webp", "Nappa seats"), ("interior-detail/1.webp", "Centre console"), ("interior-detail/2.webp", "Glass roof"), ("interior-detail/3.webp", "Front trunk"), ("charging/1.webp", "Charging"), ("tech/1.webp", "Platform"), ("dimension/1.webp", "Dimensions")]),
    "details": [f"{IMG}/{m}/exterior-detail/{i}.webp" for i in (1, 2, 3)],
    "hero_image": f"{IMG}/{m}/exterior-detail/1.webp",
})

# ---------------------------------------------------------------- Sealion 7
m = "sealion-7"
VEHICLES.append({
    "id": m, "name": "Sealion 7", "full_name": "BYD Sealion 7",
    "tagline": "Coupe-SUV with grand-touring range.",
    "body": "SUV", "seats": 5, "status": "Arriving 2027", "delivery": "Q2 2027",
    "note": None,
    "summary": "A coupe-styled SUV with up to 502 km of range, 230 kW fast charging on the 91.3 kWh pack and 530 hp dual-motor performance.",
    "preorder": {"deposit": DEPOSIT, "discount": 2500},
    "dimensions": {"length": 4830, "width": 1925, "height": 1620, "wheelbase": 2930},
    "cargo_l": 558, "warranty": "8 yr / 160,000 km battery",
    "trims": [
        trim("comfort", "Comfort RWD", 51990, battery_kwh=82.5, range_km=482, power_hp=313, power_kw=230, torque_nm=380, accel_s=6.7, drive="RWD", dc_kw=150, dc_time="10–80% in 32 min", ac_kw=11, top_speed=215),
        trim("design", "Design AWD", 56990, battery_kwh=82.5, range_km=456, power_hp=530, power_kw=390, torque_nm=690, accel_s=4.5, drive="AWD", dc_kw=150, dc_time="10–80% in 32 min", ac_kw=11, top_speed=215),
        trim("excellence", "Excellence AWD", 61990, battery_kwh=91.3, range_km=502, power_hp=530, power_kw=390, torque_nm=690, accel_s=4.5, drive="AWD", dc_kw=230, dc_time="10–80% in 24 min", ac_kw=11, top_speed=215),
    ],
    "colours": [
        colour("atlantis-grey", "Atlantis Grey", "#6d7d90", model=m),
        colour("indigo-grey", "Indigo Grey", "#a3a7ab", model=m),
        colour("polar-white", "Polar White", "#eef0f2", model=m),
        colour("obsidian-black", "Obsidian Black", "#1b1d22", model=m),
    ],
    "interiors": [
        interior("lunar", "Lunar Grey", 0, ("Light grey Nappa", "#c7c9cb"), ("Dark grey wrap", "#3a3d42"), ("Blue ambient", "#2f86d9"), photo=f"{IMG}/{m}/interior/1.webp", real=True),
        interior("obsidian", "Obsidian Black", 0, ("Black Nappa", "#1d1e22"), ("Black wrap", "#26282c"), ("Satin silver", "#b4b8be"), photo=f"{IMG}/{m}/interior/1.webp", real=False),
    ],
    "hotspots": {
        "front": [hs(38, 47, "Ocean X lighting", "LED matrix headlights with signature DRL.", "eye"),
                  hs(49, 59, "20-inch alloys", "Large-diameter aero wheels (Design/Excellence).", "gauge"),
                  hs(45, 30, "Panoramic roof", "Fixed panoramic glass roof with electric shade.", "eye"),
                  hs(68, 59, "Dual motor AWD", "530 hp combined output, 0–100 km/h in 4.5 s.", "zap")],
        "profile": [hs(32, 60, "e-Platform 3.0 Evo", "Cell-to-Body with an 800V-capable architecture.", "zap"),
                    hs(52, 33, "Coupe roofline", "Fastback silhouette with an integrated spoiler.", "route"),
                    hs(77, 46, "LED tail lights", "Full-width illuminated rear band.", "eye"),
                    hs(50, 62, "91.3 kWh option", "Up to 502 km WLTP range on Excellence.", "battery")],
        "interior": [hs(20, 42, "15.6-inch display", "Rotating centre screen plus a 10.25-inch cluster.", "maximize"),
                     hs(40, 38, "Heated wheel", "Heated steering wheel and head-up display.", "gauge"),
                     hs(80, 55, "Ventilated Nappa", "Heated and ventilated front seats with massage.", "armchair"),
                     hs(20, 31, "Ambient lighting", "Light-strip ambient lighting across the dash.", "sun")],
    },
    "gallery": gallery(m, [("atlantis-grey/1.webp", "Atlantis Grey, front three-quarter"), ("exterior-detail/1.webp", "Studio, elevated"), ("exterior-detail/2.webp", "Studio, front"), ("exterior-detail/3.webp", "Rear detail"), ("charging/1.webp", "Charging"), ("interior/1.webp", "Front cabin"), ("interior/2.webp", "Rear seats"), ("interior/3.webp", "Cargo area"), ("interior-detail/1.webp", "Centre screen"), ("interior-detail/3.webp", "Dynaudio speaker"), ("tech/1.webp", "Blade Battery"), ("dimension/1.webp", "Dimensions")]),
    "details": [f"{IMG}/{m}/exterior-detail/{i}.webp" for i in (1, 2, 3)],
    "hero_image": f"{IMG}/{m}/charging/1.webp",
})

# ---------------------------------------------------------------- Tang
m = "tang"
VEHICLES.append({
    "id": m, "name": "Tang", "full_name": "BYD Tang",
    "tagline": "Seven seats. Zero compromise.",
    "body": "SUV", "seats": 7, "status": "Arriving 2027", "delivery": "Q2 2027",
    "note": None,
    "summary": "A seven-seat family SUV with a 108.8 kWh Blade Battery, 517 hp all-wheel drive and a quilted-leather cabin with Dynaudio sound.",
    "preorder": {"deposit": DEPOSIT, "discount": 3000},
    "dimensions": {"length": 4900, "width": 1950, "height": 1725, "wheelbase": 2820},
    "cargo_l": 235, "warranty": "8 yr / 160,000 km battery",
    "trims": [
        trim("flagship", "Flagship AWD", 64990, battery_kwh=108.8, range_km=400, power_hp=517, power_kw=380, torque_nm=700, accel_s=4.6, drive="AWD", dc_kw=110, dc_time="30–80% in 30 min", ac_kw=11, top_speed=180),
        trim("executive", "Executive AWD", 69990, battery_kwh=108.8, range_km=400, power_hp=517, power_kw=380, torque_nm=700, accel_s=4.6, drive="AWD", dc_kw=110, dc_time="30–80% in 30 min", ac_kw=11, top_speed=180),
    ],
    "colours": [
        colour("obsidian-black", "Obsidian Black", "#18191d", model=m, views=1, swatch=False),
        colour("time-grey", "Time Grey", "#3d4046", model=m, views=1, swatch=False),
        colour("crystal-white", "Crystal White", "#eceeef", model=m, views=1, swatch=False),
    ],
    "interiors": [
        interior("obsidian", "Obsidian Black Quilted", 0, ("Black quilted leather", "#1e1f23"), ("Black soft-touch", "#2a2c30"), ("Blue ambient light", "#2f7fe0"), photo=f"{IMG}/{m}/interior/2.webp", real=True),
        interior("cognac", "Cognac Brown", 1200, ("Cognac quilted leather", "#8a4f2a"), ("Black soft-touch", "#2a2c30"), ("Brushed aluminium", "#b9bcc0"), photo=f"{IMG}/{m}/interior/2.webp", real=False),
    ],
    "hotspots": {
        "front": [hs(46, 48, "Dragon Face lights", "LED headlights with Dragon Face design.", "eye"),
                  hs(56, 64, "22-inch alloys", "Large alloy wheels and adaptive damping.", "gauge"),
                  hs(52, 35, "Panoramic roof", "Opening panoramic glass sunroof.", "eye"),
                  hs(71, 61, "517 hp AWD", "Dual motors, 700 Nm, 0–100 km/h in 4.6 s.", "zap")],
        "interior": [hs(25, 75, "Quilted front seats", "Heated and ventilated with massage.", "armchair"),
                     hs(50, 45, "Seven seats", "Three rows with an electrically folding third row.", "users"),
                     hs(50, 10, "Panoramic roof", "Bright cabin for every row.", "sun")],
    },
    "gallery": gallery(m, [("hero/1.webp", "At home, charging"), ("crystal-white/1.webp", "Crystal White"), ("exterior-detail/1.webp", "Profile"), ("exterior-detail/2.webp", "Front detail"), ("exterior-detail/3.webp", "Rear detail"), ("interior/1.webp", "Folding seats"), ("interior/2.webp", "Quilted seats"), ("interior/3.webp", "Rotating screen"), ("interior-detail/1.webp", "Dynaudio speaker"), ("interior-detail/2.webp", "Ambient lighting"), ("interior-detail/3.webp", "Family space"), ("charging/1.webp", "Charging")]),
    "details": [f"{IMG}/{m}/exterior-detail/{i}.webp" for i in (1, 2, 3)],
    "hero_image": f"{IMG}/{m}/hero/1.webp",
})

# ---------------------------------------------------------------- Han
m = "han"
VEHICLES.append({
    "id": m, "name": "Han", "full_name": "BYD Han",
    "tagline": "The flagship executive sedan.",
    "body": "Sedan", "seats": 5, "status": "Arriving 2027", "delivery": "Q2 2027",
    "note": "Colours other than Ocean Blue are shown as colour simulations.",
    "summary": "BYD's flagship executive sedan: 517 hp all-wheel drive, 0–100 km/h in 3.9 seconds, 521 km of WLTP range and a hand-finished Nappa cabin.",
    "preorder": {"deposit": DEPOSIT, "discount": 3500},
    "dimensions": {"length": 4995, "width": 1910, "height": 1495, "wheelbase": 2920},
    "cargo_l": 410, "warranty": "8 yr / 160,000 km battery",
    "trims": [
        trim("executive", "Executive AWD", 71990, battery_kwh=85.4, range_km=521, power_hp=517, power_kw=380, torque_nm=700, accel_s=3.9, drive="AWD", dc_kw=120, dc_time="30–80% in 25 min", ac_kw=11, top_speed=180),
    ],
    "colours": [
        colour("ocean-blue", "Ocean Blue", "#1f4fb5", model=m, swatch=False),
        colour("graphite-black", "Graphite Black", "#1c1d21", model=m, source="simulated"),
        colour("arctic-white", "Arctic White", "#e9ecee", model=m, source="simulated"),
        colour("time-grey", "Time Grey", "#7d838b", model=m, source="simulated"),
        colour("crimson-red", "Crimson Red", "#a3151f", 750, model=m, source="simulated"),
    ],
    "interiors": [
        interior("saddle", "Saddle Tan Nappa", 0, ("Tan Nappa leather", "#b06a3b"), ("Black & tan wrap", "#3a2a22"), ("Satin chrome", "#b8bcc2"), photo=f"{IMG}/{m}/interior/1.webp", real=True),
        interior("obsidian", "Obsidian Black Nappa", 0, ("Black Nappa leather", "#1d1e22"), ("Black wrap", "#26282c"), ("Satin chrome", "#b8bcc2"), photo=f"{IMG}/{m}/interior/1.webp", real=False),
    ],
    "hotspots": {
        "front": [hs(56, 57, "Dragon Face LED", "Matrix LED headlights with the Han signature light bar.", "eye"),
                  hs(40, 68, "Brembo brakes", "Red Brembo calipers and 19-inch alloys.", "gauge"),
                  hs(50, 37, "Frameless doors", "Frameless windows and a fastback roofline.", "eye"),
                  hs(68, 63, "3.9 s to 100", "Dual-motor AWD with 517 hp.", "zap")],
        "profile": [hs(27, 63, "Adaptive suspension", "Frequency-selective damping for a quiet ride.", "route"),
                    hs(55, 32, "Cd 0.233", "Low-drag executive silhouette.", "route"),
                    hs(50, 66, "Blade Battery", "85.4 kWh Blade Battery, 521 km WLTP.", "battery")],
        "interior": [hs(50, 43, "15.6-inch screen", "Rotating centre display and 12.3-inch cluster.", "maximize"),
                     hs(30, 82, "Nappa seats", "Heated, ventilated and massaging front seats.", "armchair"),
                     hs(80, 56, "Hand-stitched trim", "Diamond-quilted door panels.", "sparkle")],
    },
    "gallery": gallery(m, [("hero/1.webp", "On the road"), ("ocean-blue/1.webp", "Studio, front three-quarter"), ("ocean-blue/2.webp", "Studio, profile"), ("exterior-detail/1.webp", "Front"), ("exterior-detail/2.webp", "Rear three-quarter"), ("exterior-detail/3.webp", "Street"), ("interior/1.webp", "Nappa cabin"), ("charging/1.webp", "Charging at night"), ("tech/1.webp", "Blade Battery"), ("tech/2.webp", "Battery pack"), ("tech/3.webp", "Heat pump")]),
    "details": [f"{IMG}/{m}/exterior-detail/{i}.webp" for i in (1, 2, 3)],
    "hero_image": f"{IMG}/{m}/hero/1.webp",
})

# ------------------------------------------------------------- derived fields
for v in VEHICLES:
    v["price_from"] = min(t["price"] for t in v["trims"])
    v["range_max"] = max(t["spec"]["range_km"] for t in v["trims"])
    v["power_max"] = max(t["spec"]["power_hp"] for t in v["trims"])
    v["accel_best"] = min(t["spec"]["accel_s"] for t in v["trims"])
    v["dc_max"] = max(t["spec"]["dc_kw"] for t in v["trims"])
    v["battery_max"] = max(t["spec"]["battery_kwh"] for t in v["trims"])
    first = next(c for c in v["colours"] if c["source"] == "photo")
    v["card_image"] = first["images"][0]

MARKET = {
    "currency": "CAD",
    "launch_deadline": "2026-12-01T09:00:00-05:00",
    "provinces": {
        "AB": {"name": "Alberta", "taxes": [["GST", 0.05]]},
        "BC": {"name": "British Columbia", "taxes": [["GST", 0.05], ["PST", 0.07]]},
        "MB": {"name": "Manitoba", "taxes": [["GST", 0.05], ["RST", 0.07]]},
        "NB": {"name": "New Brunswick", "taxes": [["HST", 0.15]]},
        "NL": {"name": "Newfoundland and Labrador", "taxes": [["HST", 0.15]]},
        "NS": {"name": "Nova Scotia", "taxes": [["HST", 0.14]]},
        "NT": {"name": "Northwest Territories", "taxes": [["GST", 0.05]]},
        "NU": {"name": "Nunavut", "taxes": [["GST", 0.05]]},
        "ON": {"name": "Ontario", "taxes": [["HST", 0.13]]},
        "PE": {"name": "Prince Edward Island", "taxes": [["HST", 0.15]]},
        "QC": {"name": "Quebec", "taxes": [["GST", 0.05], ["QST", 0.09975]]},
        "SK": {"name": "Saskatchewan", "taxes": [["GST", 0.05], ["PST", 0.06]]},
        "YT": {"name": "Yukon", "taxes": [["GST", 0.05]]},
    },
    # Planned launch cities (BYD has announced Toronto, Vancouver, Montreal and
    # Calgary). Locations are placeholders until BYD confirms retail partners.
    "dealers": [
        {"id": "tor-dt", "name": "Toronto — Downtown", "province": "ON"},
        {"id": "tor-gta", "name": "Toronto — GTA West", "province": "ON"},
        {"id": "van-dt", "name": "Vancouver — Downtown", "province": "BC"},
        {"id": "van-rmd", "name": "Vancouver — Richmond", "province": "BC"},
        {"id": "mtl-ctr", "name": "Montréal — Centre", "province": "QC"},
        {"id": "mtl-lvl", "name": "Montréal — Laval", "province": "QC"},
        {"id": "cgy", "name": "Calgary", "province": "AB"},
        {"id": "home", "name": "Home delivery (any province)", "province": "*"},
    ],
}

if __name__ == "__main__":
    out = {"vehicles": VEHICLES, "market": MARKET}
    (ROOT / "data" / "vehicles.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"wrote {len(VEHICLES)} vehicles")
