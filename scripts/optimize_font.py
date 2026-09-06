"""
Shared font-optimisation helpers for the emoji CDN.

Everything here exists to get colour emoji fonts under jsDelivr's 20 MB
per-file limit without visibly degrading them. Three levers, in order of
how much they save:

1. Drop colour tables the browser will never use. Several upstream fonts
   ship the same artwork two or three times over (Fluent carries SVG +
   CBDT + COLR). Chrome/Blink renders COLR, CBDT/CBLC and sbix but
   *ignores* OT-SVG entirely, so an SVG table is always dead weight here.
2. Keep only the largest bitmap strike. Apple ships eight (20-96 px); the
   browser only ever needs the one it scales from.
3. Re-encode the remaining bitmaps to a 256-colour palette. This is the
   big one: it cuts Apple's 96 px strike from 38 MB to ~12 MB with no
   visible difference at emoji sizes, because emoji artwork is flat
   shading and gradients rather than photography.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

from fontTools.ttLib import TTFont
from PIL import Image

# Colour tables Blink can actually rasterise, best first. OT-SVG is
# deliberately absent: Chrome has never supported it, and a font that
# relies on it renders as flat black outlines from the `glyf` fallback.
CHROME_COLOR_TABLES = ("COLR", "sbix", "CBDT")
DEAD_COLOR_TABLES = ("SVG ",)

# Tables that carry no rendering value on the web.
DROPPABLE = ("DSIG",)


@dataclass
class OptimizeReport:
    steps: list = field(default_factory=list)

    def add(self, msg):
        self.steps.append(msg)
        print("    " + msg)


def load(path):
    # fontNumber=0 so .ttc collections load their first face.
    return TTFont(path, fontNumber=0)


def color_tables(font):
    return [t for t in ("COLR", "sbix", "CBDT", "SVG ") if t in font]


def drop_dead_tables(font, report):
    """Remove OT-SVG and signature tables - never useful in-browser."""
    for tag in DEAD_COLOR_TABLES + DROPPABLE:
        if tag in font:
            del font[tag]
            report.add("dropped " + tag.strip() + " table")


def prefer_color_table(font, keep, report):
    """
    Keep exactly one colour representation.

    `keep` should be a table Blink supports. When a font carries both
    vector (COLR) and bitmap (CBDT) artwork, COLR is dramatically smaller
    and scales cleanly, so it is the right choice at any size.
    """
    if keep not in font:
        report.add("WARNING: requested " + keep + " not present, keeping existing colour tables")
        return
    removed = []
    if keep == "COLR":
        for tag in ("CBDT", "CBLC", "sbix"):
            if tag in font:
                del font[tag]
                removed.append(tag)
    elif keep in ("CBDT", "sbix"):
        for tag in ("COLR", "CPAL"):
            if tag in font:
                del font[tag]
                removed.append(tag)
    if removed:
        report.add("kept " + keep + ", dropped " + ", ".join(t.strip() for t in removed))


def strip_glyph_names(font, report):
    """post 3.0 discards the glyph-name strings; nothing on the web reads them."""
    post = font.get("post")
    if post is not None and post.formatType != 3.0:
        post.formatType = 3.0
        post.glyphOrder = None
        report.add("post table -> format 3.0 (glyph names stripped)")


# --------------------------------------------------------------------------
# CBDT/CBLC bitmap handling
# --------------------------------------------------------------------------

def _strike_glyph_names(strike):
    names = []
    for sub in strike.indexSubTables:
        names.extend(sub.names)
    return names


def strike_sizes(font):
    if "CBLC" not in font:
        return []
    return [s.bitmapSizeTable.ppemX for s in font["CBLC"].strikes]


def keep_largest_strike(font, report):
    """
    Collapse a multi-strike bitmap font down to its highest-resolution strike.

    The browser picks the strike closest to the requested pixel size and
    scales it, so a single large strike covers every rendering size. Apple
    ships eight strikes; seven of them are pure overhead for our use.
    """
    if "CBLC" not in font or "CBDT" not in font:
        return None
    cblc, cbdt = font["CBLC"], font["CBDT"]
    if not cblc.strikes:
        return None
    sizes = [s.bitmapSizeTable.ppemX for s in cblc.strikes]
    if len(cblc.strikes) == 1:
        return sizes[0]

    best = max(range(len(sizes)), key=lambda i: sizes[i])
    cblc.strikes = [cblc.strikes[best]]
    cbdt.strikeData = [cbdt.strikeData[best]]
    dropped = sorted(s for i, s in enumerate(sizes) if i != best)
    report.add("kept only the {}px strike (dropped {})".format(sizes[best], dropped))
    return sizes[best]


def _scale_metrics(metrics, factor, new_w, new_h):
    """Bitmap glyph metrics are in pixels at the strike's ppem, so they have
    to move with the image when we resample it."""
    if hasattr(metrics, "width"):
        metrics.width = new_w
    if hasattr(metrics, "height"):
        metrics.height = new_h
    for attr in ("BearingX", "BearingY", "Advance"):
        if hasattr(metrics, attr):
            setattr(metrics, attr, int(round(getattr(metrics, attr) * factor)))


def recode_bitmaps(font, report, colors=256, target_ppem=None):
    """
    Re-encode every PNG in the (single) CBDT strike.

    `colors` applies an adaptive palette. Pillow's FASTOCTREE is the only
    quantiser that handles RGBA, which emoji need for their alpha channel.
    `target_ppem` additionally resamples; leave it None to keep the source
    resolution, which is usually what you want once the palette has done
    the heavy lifting.
    """
    if "CBDT" not in font or "CBLC" not in font:
        return
    cblc, cbdt = font["CBLC"], font["CBDT"]
    if not cblc.strikes:
        return
    strike = cblc.strikes[0]
    size_table = strike.bitmapSizeTable
    src_ppem = size_table.ppemX
    dst_ppem = target_ppem or src_ppem
    factor = float(dst_ppem) / float(src_ppem)

    before = 0
    after = 0
    converted = 0
    skipped = 0
    for name in _strike_glyph_names(strike):
        glyph = cbdt.strikeData[0].get(name)
        data = getattr(glyph, "imageData", None)
        if not data:
            continue
        before += len(data)
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
            im = im.convert("RGBA")
        except Exception:
            # Not a PNG we can touch (or a corrupt record) - pass it through
            # untouched rather than dropping a glyph.
            after += len(data)
            skipped += 1
            continue

        if factor != 1.0:
            w = max(1, int(round(im.width * factor)))
            h = max(1, int(round(im.height * factor)))
            im = im.resize((w, h), Image.LANCZOS)

        out = im
        if colors:
            # FASTOCTREE is the only RGBA-capable method in Pillow; the
            # others raise on an alpha channel.
            out = im.quantize(colors=colors, method=Image.FASTOCTREE)

        buf = io.BytesIO()
        out.save(buf, "PNG", optimize=True)
        encoded = buf.getvalue()

        # Never let "optimisation" make a glyph bigger.
        if len(encoded) < len(data) or factor != 1.0:
            glyph.imageData = encoded
            after += len(encoded)
            converted += 1
        else:
            after += len(data)
            skipped += 1

        if factor != 1.0 and hasattr(glyph, "metrics"):
            _scale_metrics(glyph.metrics, factor, im.width, im.height)

    if factor != 1.0:
        size_table.ppemX = dst_ppem
        size_table.ppemY = dst_ppem
        for axis in ("hori", "vert"):
            line = getattr(size_table, axis, None)
            if line is None:
                continue
            for attr in ("ascender", "descender", "widthMax", "minOriginSB",
                         "minAdvanceSB", "maxBeforeBL", "minAfterBL"):
                if hasattr(line, attr):
                    setattr(line, attr, int(round(getattr(line, attr) * factor)))
        report.add("resampled bitmaps {}px -> {}px".format(src_ppem, dst_ppem))

    if colors:
        report.add(
            "re-encoded {} bitmaps to {} colours ({:.1f}MB -> {:.1f}MB, {} left as-is)".format(
                converted, colors, before / 1e6, after / 1e6, skipped
            )
        )


def save_woff2(font, out_path, report):
    # Reproducible builds. fontTools stamps head.modified with the current
    # time on every save, so an otherwise byte-identical rebuild rewrites
    # every file: 26 MB of meaningless git churn, and manifest.json hashes
    # that no longer match what a published tag is serving. Nothing on the
    # web reads this timestamp.
    font.recalcTimestamp = False
    font.flavor = "woff2"
    font.save(out_path)
    size = os.path.getsize(out_path)
    report.add("wrote {} ({:.1f}MB)".format(os.path.basename(out_path), size / 1e6))
    return size


def optimize(font, opts, report):
    """Apply the configured optimisation pipeline to an open font."""
    drop_dead_tables(font, report)

    preferred = opts.get("prefer_color_table")
    if preferred:
        prefer_color_table(font, preferred, report)

    if "CBDT" in font:
        keep_largest_strike(font, report)
        recode_bitmaps(
            font,
            report,
            colors=opts.get("quantize_colors", 256),
            target_ppem=opts.get("bitmap_ppem"),
        )

    strip_glyph_names(font, report)
