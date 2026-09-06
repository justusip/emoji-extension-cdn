"""
Build every font listed in fonts.json into fonts/ and write manifest.json.

    python scripts/build_all.py                 # build everything
    python scripts/build_all.py twemoji apple-emoji   # build a subset
    python scripts/build_all.py --refresh       # ignore the download cache

The build fails loudly if any output would break jsDelivr's limits, because
an oversized file does not error at publish time - it simply 404s forever
once the tag is live, and tags are immutable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import optimize_font as opt
import build_apple_emoji

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "build", "cache")
FONTS = os.path.join(ROOT, "fonts")
SOURCES = os.path.join(ROOT, "fonts.json")
MANIFEST = os.path.join(ROOT, "manifest.json")


def download(url, dest, refresh=False):
    if os.path.exists(dest) and not refresh:
        print("  using cached {} ({:.1f} MB)".format(os.path.basename(dest), os.path.getsize(dest) / 1e6))
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print("  downloading {}".format(url))
    req = urllib.request.Request(url, headers={"User-Agent": "emoji-extension-cdn/1.0"})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()
    with open(dest, "wb") as fh:
        fh.write(data)
    print("  downloaded {:.1f} MB".format(len(data) / 1e6))
    return dest


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def describe(path):
    """Record what the shipped font actually contains, for the manifest."""
    font = opt.load(path)
    info = {
        "color_tables": [t.strip() for t in opt.color_tables(font)],
        "codepoints": len(font.getBestCmap()),
        "glyphs": len(font.getGlyphOrder()),
        # Sequence composition (skin tones, ZWJ, flags, keycaps) needs GSUB.
        # AAT `morx` does not survive the browser's font sanitiser.
        "has_gsub": "GSUB" in font,
    }
    strikes = opt.strike_sizes(font)
    if strikes:
        info["bitmap_ppem"] = strikes[0]
    font.close()
    return info


def build_one(entry, refresh=False, max_bytes=19_000_000):
    fid = entry["id"]
    print("\n== {} ==".format(entry["title"]))

    if entry.get("builder") == "build_apple_emoji":
        opts = entry.get("optimize", {})
        result = build_apple_emoji.build(
            ppem=opts.get("bitmap_ppem_override"),
            colors=opts.get("quantize_colors", 256),
            refresh=refresh,
            max_bytes=max_bytes,
        )
        out = os.path.join(FONTS, result["file"])
        upstream = {"release": result["upstream_release"], "url": result["upstream_asset"]}
        size = result["bytes"]
    else:
        url = entry["url"]
        ext = ".woff2" if url.lower().endswith(".woff2") else ".ttf"
        # Key the cache on the URL, not just the font id. Otherwise pointing an
        # existing entry at a new upstream (as when Noto moved from the CBDT
        # build to COLRv1) silently reuses the old download and "rebuilds" the
        # font you were trying to replace.
        stamp = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        src = download(url, os.path.join(CACHE, "{}-{}{}".format(fid, stamp, ext)), refresh=refresh)

        report = opt.OptimizeReport()
        font = opt.load(src)
        print("    source colour tables: {}".format([t.strip() for t in opt.color_tables(font)]))
        opt.optimize(font, entry.get("optimize", {}), report)

        os.makedirs(FONTS, exist_ok=True)
        out = os.path.join(FONTS, fid + ".woff2")
        size = opt.save_woff2(font, out, report)
        font.close()
        upstream = {"url": url}

        if size > max_bytes:
            raise SystemExit(
                "FAIL: {} is {:.1f}MB, over the {:.0f}MB per-file budget.".format(
                    fid, size / 1e6, max_bytes / 1e6)
            )

    record = {
        "id": fid,
        "title": entry["title"],
        "description": entry["description"],
        "homepage": entry["homepage"],
        "license": entry["license"],
        "file": "fonts/" + os.path.basename(out),
        "bytes": size,
        "sha256": sha256(out),
        "upstream": upstream,
    }
    record.update(describe(out))
    if entry.get("note"):
        record["note"] = entry["note"]
    # Drawn in a single dark colour: the extension needs to know so the
    # chooser preview stays visible against a dark background.
    if entry.get("monochrome"):
        record["monochrome"] = True

    # A font meant to be in colour but carrying no colour table renders as
    # black outlines — exactly the bug the old OT-SVG Twemoji build had.
    # Styles declared monochrome are supposed to look like that.
    if not entry.get("monochrome") and not record["color_tables"]:
        raise SystemExit("FAIL: {} has no browser-renderable colour table".format(fid))

    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ids", nargs="*", help="font ids to build (default: all)")
    ap.add_argument("--refresh", action="store_true", help="re-download upstream sources")
    args = ap.parse_args()

    with open(SOURCES, encoding="utf-8") as fh:
        config = json.load(fh)

    max_file = config.get("max_file_bytes", 19_000_000)
    max_total = config.get("max_total_bytes", 140_000_000)

    entries = config["fonts"]
    if args.ids:
        known = {e["id"] for e in entries}
        unknown = set(args.ids) - known
        if unknown:
            raise SystemExit("Unknown font id(s): {}. Known: {}".format(
                ", ".join(sorted(unknown)), ", ".join(sorted(known))))
        entries = [e for e in entries if e["id"] in args.ids]

    # Preserve records for fonts we did not rebuild, so a partial build does
    # not silently drop entries from the manifest.
    existing = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as fh:
            for rec in json.load(fh).get("fonts", []):
                existing[rec["id"]] = rec

    built = {}
    for entry in entries:
        built[entry["id"]] = build_one(entry, refresh=args.refresh, max_bytes=max_file)

    records = []
    for entry in config["fonts"]:
        rec = built.get(entry["id"]) or existing.get(entry["id"])
        if rec:
            records.append(rec)

    total = sum(r["bytes"] for r in records)
    manifest = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_bytes": total,
        "fonts": records,
    }
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    print("\n" + "=" * 62)
    for rec in records:
        print("  {:34s} {:6.1f} MB  {}".format(
            rec["id"], rec["bytes"] / 1e6, ",".join(rec["color_tables"]) or "monochrome"))
    print("  {:34s} {:6.1f} MB total".format("", total / 1e6))

    if total > max_total:
        raise SystemExit(
            "FAIL: {:.0f}MB total exceeds the {:.0f}MB budget "
            "(jsDelivr rejects repos over 150MB).".format(total / 1e6, max_total / 1e6))
    print("\nWrote manifest.json. Next: python scripts/verify.py")


if __name__ == "__main__":
    main()
