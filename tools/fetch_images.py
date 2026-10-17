"""
fetch_images.py — Download, resize and cache official BYD imagery.

Every image used by the showroom is listed in MANIFEST below together with the
official BYD page it was published on. Running this script:

  1. downloads each asset from www.byd.com (BYD Europe official site),
  2. resizes it to a sensible web width and re-encodes it as WebP,
  3. stores it under static/images/vehicles/<model>/<group>/<n>.webp,
  4. writes data/image_manifest.json and regenerates /image_sources.md.

Usage:  python tools/fetch_images.py          (skips files already cached)
        python tools/fetch_images.py --force  (re-download everything)
"""
from __future__ import annotations

import io
import json
import sys
from datetime import date
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "images" / "vehicles"
HOST = "https://www.byd.com/"
UA = {"User-Agent": "Mozilla/5.0 (BYD Canada showroom asset cache)"}
LICENSE = ("(c) BYD Auto Co., Ltd. Official manufacturer marketing imagery, "
           "used for non-commercial demonstration. Not for redistribution.")

# --------------------------------------------------------------------------
# Manifest: model -> source page + list of (local_rel_path, remote_path, label)
# --------------------------------------------------------------------------
def _gallery(base: str, colours: dict[str, str], n: int = 2):
    """Exterior gallery shots for each paint colour (folder slug -> local slug)."""
    out = []
    for remote, local in colours.items():
        for i in range(1, n + 1):
            out.append((f"{local}/{i}.webp", f"{base}exterior-gallery/{remote}/{i}.webp",
                        f"Exterior, {local.replace('-', ' ')}, view {i}"))
    return out


def _many(base: str, folder: str, local: str, idx, label: str):
    return [(f"{local}/{i}.webp", f"{base}{folder}/{i}.webp", f"{label} {i}") for i in idx]


def _swatches(base: str, names: dict[str, str]):
    return [(f"swatches/{local}.webp", f"{base}{remote}", f"Paint swatch, {local}")
            for remote, local in names.items()]


S = "material/byd-site/eu-v3/model/seal2026/pc/"
L = "material/byd-site/eu-v3/model/sealion7/pc/"
A = "material/byd-site/eu-v3/model/atto3-evo/pc/"
D = "material/__EU/byd-site/eu-v3/model/dolphin/pc/"
G = "material/byd-site/eu-v3/model/dolphin-surf/pc/"
T = "material/byd-site/eu/product/tang-2024/xl/"
H = "material/byd-site/eu/product/han/"

MANIFEST: dict[str, dict] = {
    "seal": {
        "page": "https://www.byd.com/eu/electric-cars/seal",
        "items": [
            *_gallery(S, {"atlantisgrey": "atlantis-grey", "black": "obsidian-black",
                          "indigogrey": "indigo-grey", "lavendergrey": "lavender-grey",
                          "red": "ruby-red", "white": "polar-white"}),
            *_many(S, "interior", "interior", [1, 2], "Interior"),
            *_many(S, "interior-detail", "interior-detail", [1, 2, 3], "Interior detail"),
            *_many(S, "exterior-detail", "exterior-detail", [1, 2, 3], "Exterior detail"),
            ("dimension/1.webp", S + "exterior-dimension/1.webp", "Dimensions"),
            ("tech/1.webp", S + "tech/1.webp", "Technology"),
            ("charging/1.webp", S + "charge/charging.webp", "Charging"),
            *_swatches("material/byd-site/configuration/byd-seal-2026/icons/exterior/", {
                "atlantisgrey.webp": "atlantis-grey", "obsidianblack.webp": "obsidian-black",
                "indigogrey.webp": "indigo-grey", "lavendergrey.webp": "lavender-grey",
                "rubyred.webp": "ruby-red", "polarwhite.webp": "polar-white"}),
        ],
    },
    "sealion-7": {
        "page": "https://www.byd.com/eu/electric-cars/sealion-7",
        "items": [
            *_gallery(L, {"altantisgrey": "atlantis-grey", "black": "obsidian-black",
                          "indigogrey": "indigo-grey", "white": "polar-white"}),
            *_many(L, "interior", "interior", [1, 2, 3], "Interior"),
            *_many(L, "interior-detail", "interior-detail", [1, 2, 3], "Interior detail"),
            *_many(L, "exterior-detail", "exterior-detail", [1, 2, 3], "Exterior detail"),
            ("dimension/1.webp", L + "exterior-dimension/1.webp", "Dimensions"),
            ("tech/1.webp", L + "tech/1.webp", "Technology"),
            ("charging/1.webp", L + "charge/charging.webp", "Charging"),
            *_swatches("material/byd-site/configuration/byd-sealion-7/icons/exterior/", {
                "Atlantisgrey.jpg": "atlantis-grey", "obsidianblack.webp": "obsidian-black",
                "Indigogrey.jpg": "indigo-grey", "polarwhite.webp": "polar-white"}),
        ],
    },
    "atto-3": {
        "page": "https://www.byd.com/eu/electric-cars/atto-3-evo",
        "items": [
            *_gallery(A, {"altantisblue": "atlantis-blue", "black": "obsidian-black",
                          "grey": "time-grey", "irisblue": "iris-blue",
                          "red": "ruby-red", "white": "skiing-white"}),
            *_many(A, "interior", "interior", [1, 2, 3], "Interior"),
            *_many(A, "interior-detail", "interior-detail", [1, 2, 3], "Interior detail"),
            *_many(A, "exterior", "exterior-detail", [1, 2], "Exterior detail"),
            ("dimension/1.webp", A + "exterior-dimension/1.webp", "Dimensions"),
            ("tech/1.webp", A + "tech/1.webp", "Technology"),
            ("charging/1.webp", A + "charging/charging.webp", "Charging"),
            *_swatches("material/byd-site/configuration/byd-atto-3-evo/icons/exterior/", {
                "atlantisblue.webp": "atlantis-blue", "obsidianblack.webp": "obsidian-black",
                "timegrey.webp": "time-grey", "irisblue.webp": "iris-blue",
                "rubyred.webp": "ruby-red", "skiingwhite.webp": "skiing-white"}),
        ],
    },
    "dolphin": {
        "page": "https://www.byd.com/eu/electric-cars/dolphin",
        "items": [
            *_gallery(D, {"black": "obsidian-black", "creamwhite": "cream-white",
                          "urbangrey": "urban-grey"}),
            *_many(D, "interior", "interior", [1, 2, 3], "Interior"),
            *_many(D, "interior-detail", "interior-detail", [1, 2, 3], "Interior detail"),
            *_many(D, "exterior", "exterior-detail", [1, 2], "Exterior detail"),
            ("dimension/1.webp", D + "exterior-dimension/1.webp", "Dimensions"),
            ("tech/1.webp", D + "tech/1.webp", "Technology"),
            ("charging/1.webp", D + "charge/charging.webp", "Charging"),
            *_swatches("material/byd-site/configuration/byd-dolphin/icons-v3/exterior/", {
                "obsidianblack.webp": "obsidian-black", "skiingwhite.webp": "cream-white",
                "timegrey.webp": "urban-grey"}),
        ],
    },
    "seagull": {
        "page": "https://www.byd.com/eu/electric-cars/dolphin-surf",
        "items": [
            *_gallery(G, {"black": "polar-night-black", "blue": "ice-blue",
                          "green": "lemon-green", "white": "apricity-white"}),
            *_many(G, "interior", "interior", [1, 2], "Interior"),
            *_many(G, "interior-detail", "interior-detail", [1, 2, 3], "Interior detail"),
            *_many(G, "exterior-detail", "exterior-detail", [1, 2, 3], "Exterior detail"),
            ("dimension/1.webp", G + "exterior-dimension/1.webp", "Dimensions"),
            ("tech/1.webp", G + "tech/1.webp", "Technology"),
            ("charging/1.webp", G + "charge/charging.webp", "Charging"),
            *_swatches("material/byd-site/configuration/byd-dolphin-surf/icons/exterior/", {
                "polarnightblack.webp": "polar-night-black", "iceblue.webp": "ice-blue",
                "lemongreen.webp": "lemon-green", "apricitywhite.webp": "apricity-white"}),
        ],
    },
    "tang": {
        "page": "https://www.byd.com/eu/electric-cars/tang",
        "items": [
            ("hero/1.webp", T + "Tang2024-1stBanner-xl.jpg", "Hero banner"),
            ("obsidian-black/1.webp", T + "Tang2024-exterior-04-black-xl.jpg", "Exterior, obsidian black"),
            ("time-grey/1.webp", T + "Tang2024-exterior-04-grey-xl.jpg", "Exterior, time grey"),
            ("crystal-white/1.webp", T + "Tang2024-exterior-04-white-xl.jpg", "Exterior, crystal white"),
            ("exterior-detail/1.webp", T + "Tang2024-exterior-01-xl.jpg", "Exterior detail 1"),
            ("exterior-detail/2.webp", T + "Tang2024-exterior-02-xl.jpg", "Exterior detail 2"),
            ("exterior-detail/3.webp", T + "Tang2024-exterior-03-xl.jpg", "Exterior detail 3"),
            ("interior/1.webp", T + "Tang2024-interior-01-space-xl.jpg", "Interior 1"),
            ("interior/2.webp", T + "Tang2024-interior-02-xl.jpg", "Interior 2"),
            ("interior/3.webp", T + "Tang2024-interior-03-xl.jpg", "Interior 3"),
            ("interior-detail/1.webp", T + "Tang2024-interior-04-xl.jpg", "Interior detail 1"),
            ("interior-detail/2.webp", T + "Tang2024-interior-05-xl.jpg", "Interior detail 2"),
            ("interior-detail/3.webp", T + "Tang2024-interior-06-xl.jpg", "Interior detail 3"),
            ("charging/1.webp", T + "Tang2024-charging-01-xl.jpg", "Charging"),
        ],
    },
    "han": {
        "page": "https://www.byd.com/eu/electric-cars/han",
        "items": [
            ("hero/1.webp", H + "banner-pc-20221102.jpg", "Hero banner, city road"),
            ("ocean-blue/1.webp", H + "F04.jpg", "Exterior, studio front three-quarter"),
            ("ocean-blue/2.webp", H + "F04-Sub02.jpg", "Exterior, studio profile"),
            ("exterior-detail/1.webp", H + "F04-Sub03.jpg", "Exterior detail, front"),
            ("exterior-detail/2.webp", H + "F04-Sub04.jpg", "Exterior detail, rear three-quarter"),
            ("exterior-detail/3.webp", H + "F06-pc-20221102.jpg", "Exterior, street"),
            ("interior/1.webp", H + "F05.jpg", "Interior, cockpit"),
            ("tech/1.webp", H + "F01.jpg", "Blade Battery"),
            ("tech/2.webp", H + "F02.jpg", "Battery pack"),
            ("tech/3.webp", H + "F03.jpg", "Heat pump"),
            ("charging/1.webp", H + "F08.jpg", "Charging at night"),
        ],
    },
}

MAX_W = 1600      # big photos
SWATCH_W = 160    # paint chips


def fetch(force: bool = False) -> list[dict]:
    records, failures = [], []
    for model, spec in MANIFEST.items():
        for rel, remote, label in spec["items"]:
            dest = OUT / model / rel
            url = HOST + remote
            rec = {"model": model, "file": f"static/images/vehicles/{model}/{rel}",
                   "label": label, "source_url": url, "source_page": spec["page"],
                   "credit": "BYD Auto (official, BYD Europe)", "license": LICENSE}
            if dest.exists() and not force:
                with Image.open(dest) as im:
                    rec["width"], rec["height"] = im.size
                records.append(rec)
                continue
            try:
                r = requests.get(url, headers=UA, timeout=30)
                r.raise_for_status()
                im = Image.open(io.BytesIO(r.content))
                # Official cut-outs are transparent PNG/WebP: flatten onto a
                # white studio background (alpha -> RGB would turn it black).
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[3])
                    im = bg
                else:
                    im = im.convert("RGB")
                limit = SWATCH_W if rel.startswith("swatches/") else MAX_W
                if im.width > limit:
                    im = im.resize((limit, round(im.height * limit / im.width)), Image.LANCZOS)
                dest.parent.mkdir(parents=True, exist_ok=True)
                im.save(dest, "WEBP", quality=80, method=6)
                rec["width"], rec["height"] = im.size
                records.append(rec)
                print(f"  ok   {model}/{rel}  {im.size}")
            except Exception as exc:  # noqa: BLE001 — report and keep going
                failures.append((model, rel, url, str(exc)))
                print(f"  FAIL {model}/{rel}: {exc}")
    (ROOT / "data" / "image_manifest.json").write_text(json.dumps(records, indent=2))
    write_sources_md(records)
    if failures:
        print(f"\n{len(failures)} failures")
    return records


def write_sources_md(records: list[dict]) -> None:
    lines = [
        "# Image Sources & Attribution", "",
        f"_Generated by `tools/fetch_images.py` on {date.today().isoformat()}._", "",
        "All vehicle photography in this project is **official BYD manufacturer imagery** "
        "downloaded from the BYD Europe website (www.byd.com/eu). Images are resized and "
        "re-encoded as WebP and cached locally so the site never hotlinks.", "",
        f"**License / usage:** {LICENSE}", "",
        '## Brand logo',
        '',
        '| File | Use | Source |',
        '| --- | --- | --- |',
        '| `static/images/brand/byd-logo.png` | Header and footer logo (320 px wide, transparent PNG) | Official BYD logo supplied by the project owner (`BYD_Company,_Ltd._-_Logo.svg.png`), trimmed and resized |',
        '| `static/images/brand/favicon-32.png`, `favicon-64.png`, `favicon.ico` | Browser tab icons | Derived from the same logo |',
        '| `static/images/brand/apple-touch-icon.png` | iOS home-screen icon (logo on white) | Derived from the same logo |',
        '',
        '**Trademark:** The BYD name and logo are trademarks of BYD Company Ltd., used here to identify the brand in a demonstration project.',
        "",
        "## Fallback / illustrative imagery", "",
        "| Where | What | Method |", "| --- | --- | --- |",
        "| Han — every colour except Ocean Blue (the photographed paint) | Paint colour preview | **Option A**: canvas recolour of the real Han photo (`static/js/configurator.js`), labeled *Colour simulation* in the UI |",
        "| All models — interior material choices | Seat / dash / trim materials | **Option C**: real base interior photo with swatch overlay + legend, labeled *Material preview* |",
        "| Tang — paint swatches | Swatch chips | CSS colour chips (no official chip image published) |",
        "",
    ]
    by_model: dict[str, list[dict]] = {}
    for r in records:
        by_model.setdefault(r["model"], []).append(r)
    for model, recs in by_model.items():
        lines += [f"## {model}", "", f"Source page: <{recs[0]['source_page']}>", "",
                  "| Local file | Description | Original URL |", "| --- | --- | --- |"]
        for r in recs:
            lines.append(f"| `{r['file']}` | {r['label']} | <{r['source_url']}> |")
        lines.append("")
    (ROOT / "image_sources.md").write_text("\n".join(lines))


if __name__ == "__main__":
    fetch(force="--force" in sys.argv)
