"""
Build an optimised web font from the latest Apple Color Emoji artwork.

Apple does not distribute AppleColorEmoji for the web, and the copy that
ships with macOS is an sbix .ttc that browsers on other platforms will not
load. We therefore track samuelngs/apple-emoji-ttf, which republishes the
system font as a CBDT/CBLC TTF on every macOS release, and optimise that.

Pipeline:

  latest release (macOS 26 / iOS 26 artwork)
    -> AppleColorEmoji-Linux.ttf        ~116 MB, 8 strikes (20-96 px)
    -> keep the 96 px strike only        ~38 MB
    -> 256-colour palette re-encode      ~12 MB
    -> synthesise GSUB from AAT `morx`   (see make_gsub.py - without this
                                          every skin tone, ZWJ family, flag
                                          and keycap breaks apart in-browser)
    -> woff2                             fits jsDelivr's 20 MB file cap

Run directly to rebuild just this font:

    python scripts/build_apple_emoji.py

Options:
    --ppem N        resample the kept strike to N px (default: keep 96)
    --colors N      palette size, 0 disables quantisation (default: 256)
    --refresh       ignore the cached download and re-fetch upstream
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import optimize_font as opt
import make_gsub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "build", "cache")
FONTS = os.path.join(ROOT, "fonts")

# The upstream repo redirects; this is its stable numeric id, which keeps
# working even if the project is renamed again (it already moved from
# apple-emoji-linux to apple-emoji-ttf).
RELEASES_API = "https://api.github.com/repositories/158348890/releases/latest"
ASSET_NAME = "AppleColorEmoji-Linux.ttf"

FONT_ID = "apple-emoji"


def _get(url, binary=True):
    req = urllib.request.Request(url, headers={"User-Agent": "emoji-extension-cdn/1.0"})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()
    return data if binary else data.decode("utf-8")


def resolve_latest():
    """Return (tag, asset_url) for the newest upstream release."""
    meta = json.loads(_get(RELEASES_API, binary=False))
    tag = meta["tag_name"]
    for asset in meta.get("assets", []):
        if asset["name"] == ASSET_NAME:
            return tag, asset["browser_download_url"]
    raise SystemExit(
        "Upstream release {} has no {} asset. Assets: {}".format(
            tag, ASSET_NAME, [a["name"] for a in meta.get("assets", [])]
        )
    )


def download(url, dest, refresh=False):
    if os.path.exists(dest) and not refresh:
        print("  using cached {} ({:.0f} MB)".format(os.path.basename(dest), os.path.getsize(dest) / 1e6))
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print("  downloading {} ...".format(url))
    data = _get(url)
    with open(dest, "wb") as fh:
        fh.write(data)
    print("  downloaded {:.0f} MB".format(len(data) / 1e6))
    return dest


def build(ppem=None, colors=256, refresh=False, max_bytes=19_000_000):
    tag, url = resolve_latest()
    print("Apple Color Emoji: upstream release {}".format(tag))

    src = download(url, os.path.join(CACHE, ASSET_NAME), refresh=refresh)
    with open(os.path.join(CACHE, "apple-release-tag.txt"), "w", encoding="utf-8") as fh:
        fh.write(tag)

    report = opt.OptimizeReport()
    font = opt.load(src)
    print("    source strikes: {}".format(opt.strike_sizes(font)))

    opt.optimize(font, {"quantize_colors": colors or None, "bitmap_ppem": ppem}, report)

    # Must happen before saving and after optimisation: optimisation never
    # reorders glyphs, so glyph ids still line up with the source font that
    # HarfBuzz reads the AAT rules out of.
    make_gsub.add_gsub_from_aat(font, src, CACHE, report, refresh=refresh)
    make_gsub.drop_aat_tables(font, report)

    os.makedirs(FONTS, exist_ok=True)
    out = os.path.join(FONTS, FONT_ID + ".woff2")
    size = opt.save_woff2(font, out, report)
    font.close()

    if size > max_bytes:
        raise SystemExit(
            "FAIL: {:.1f}MB exceeds the {:.0f}MB budget (jsDelivr rejects files over 20MB).\n"
            "Retry with a smaller strike, e.g. --ppem 72, or --colors 128.".format(
                size / 1e6, max_bytes / 1e6
            )
        )

    return {
        "id": FONT_ID,
        "file": FONT_ID + ".woff2",
        "bytes": size,
        "upstream_release": tag,
        "upstream_asset": url,
        "steps": report.steps,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ppem", type=int, default=None,
                    help="resample the kept strike to this pixel size (default: keep source)")
    ap.add_argument("--colors", type=int, default=256,
                    help="palette size for bitmap re-encoding; 0 disables (default: 256)")
    ap.add_argument("--refresh", action="store_true", help="re-download even if cached")
    args = ap.parse_args()

    result = build(ppem=args.ppem, colors=args.colors, refresh=args.refresh)
    print("\nBuilt {} from {} -> {:.1f}MB".format(
        result["file"], result["upstream_release"], result["bytes"] / 1e6))


if __name__ == "__main__":
    main()
