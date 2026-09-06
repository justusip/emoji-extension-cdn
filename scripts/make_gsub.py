"""
Synthesise an OpenType GSUB table for a font that only ships Apple's AAT
shaping tables.

Why this exists
---------------
Apple Color Emoji composes sequences - skin tones, ZWJ families, flags,
keycaps - with an AAT `morx` table rather than an OpenType GSUB. That works
in macOS and in HarfBuzz when the font is loaded from disk, but it does NOT
work as a web font: Chrome and Firefox pass every @font-face through OTS
(the OpenType Sanitiser), which drops AAT tables outright. The result is a
font that renders single emoji perfectly and shatters every sequence:

    thumbs-up + skin-tone-4  ->  thumbs-up, brown square
    family                   ->  man, woman, girl, boy
    flag of Japan            ->  nothing at all

The fix is to give the font a real GSUB. We cannot read the sequences out
of the glyph names (Apple uses descriptive names like `outline.handshakeLeft`),
so we recover them empirically: HarfBuzz *does* honour `morx` when it loads
the font directly, so we shape every emoji sequence Unicode defines, keep
the ones that collapse to a single glyph, and emit those as GSUB ligature
rules under `ccmp` - the same feature Apple's own web-converted builds use.
"""

from __future__ import annotations

import os
import re
import urllib.request

import uharfbuzz as hb
from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables as ot
from fontTools.otlLib import builder as otl

EMOJI_TEST_URL = "https://www.unicode.org/Public/emoji/latest/emoji-test.txt"

# `ccmp` is applied unconditionally by HarfBuzz's default shaper, which is
# what emoji sequences need. This mirrors how existing web builds of Apple
# Color Emoji register their ligatures.
FEATURE_TAG = "ccmp"

_SEQ_LINE = re.compile(r"^([0-9A-Fa-f ]+);\s*(\S+)")


def fetch_emoji_test(cache_path, refresh=False):
    """Download Unicode's emoji-test.txt, which enumerates every sequence."""
    if os.path.exists(cache_path) and not refresh:
        return cache_path
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    req = urllib.request.Request(
        EMOJI_TEST_URL, headers={"User-Agent": "emoji-extension-cdn/1.0"}
    )
    with urllib.request.urlopen(req) as resp:
        data = resp.read()
    with open(cache_path, "wb") as fh:
        fh.write(data)
    return cache_path


def parse_sequences(path):
    """Every multi-codepoint emoji sequence in emoji-test.txt."""
    sequences = []
    seen = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            match = _SEQ_LINE.match(line)
            if not match:
                continue
            codepoints = tuple(int(p, 16) for p in match.group(1).split())
            # Single codepoints need no ligature; the cmap already covers them.
            if len(codepoints) < 2 or codepoints in seen:
                continue
            seen.add(codepoints)
            sequences.append(codepoints)
    return sequences


def derive_ligatures(font_path, sequences, cmap, glyph_order):
    """
    Shape each sequence with HarfBuzz and keep the ones that become one glyph.

    HarfBuzz applies `morx` when a font has no GSUB, so this reads the
    composition rules straight out of Apple's own shaping logic instead of
    guessing at them.
    """
    blob = hb.Blob.from_file_path(font_path)
    face = hb.Face(blob)
    hb_font = hb.Font(face)

    ligatures = {}
    unmapped = 0
    unshaped = 0

    for codepoints in sequences:
        # The GSUB input is whatever glyphs the cmap produces for this
        # sequence. If any codepoint is missing, no rule can be written.
        try:
            inputs = tuple(cmap[cp] for cp in codepoints)
        except KeyError:
            unmapped += 1
            continue

        buf = hb.Buffer()
        buf.add_codepoints(list(codepoints))
        buf.guess_segment_properties()
        hb.shape(hb_font, buf)

        infos = buf.glyph_infos
        if len(infos) != 1:
            # Did not compose - the font has no single glyph for it.
            unshaped += 1
            continue
        gid = infos[0].codepoint
        if gid == 0 or gid >= len(glyph_order):
            unshaped += 1
            continue

        ligatures[inputs] = glyph_order[gid]

    return ligatures, {"unmapped": unmapped, "did_not_compose": unshaped}


def build_gsub_table(ligatures):
    """Wrap ligature rules in a minimal GSUB: one lookup, ccmp, DFLT script."""
    subtable = otl.buildLigatureSubstSubtable(ligatures)
    lookup = otl.buildLookup([subtable], flags=0)

    lookup_list = ot.LookupList()
    lookup_list.Lookup = [lookup]
    lookup_list.LookupCount = 1

    feature = ot.Feature()
    feature.FeatureParams = None
    feature.LookupListIndex = [0]
    feature.LookupCount = 1
    feature_record = ot.FeatureRecord()
    feature_record.FeatureTag = FEATURE_TAG
    feature_record.Feature = feature
    feature_list = ot.FeatureList()
    feature_list.FeatureRecord = [feature_record]
    feature_list.FeatureCount = 1

    lang_sys = ot.LangSys()
    lang_sys.LookupOrder = None
    lang_sys.ReqFeatureIndex = 0xFFFF
    lang_sys.FeatureIndex = [0]
    lang_sys.FeatureCount = 1
    script = ot.Script()
    script.DefaultLangSys = lang_sys
    script.LangSysRecord = []
    script.LangSysCount = 0
    script_record = ot.ScriptRecord()
    script_record.ScriptTag = "DFLT"
    script_record.Script = script
    script_list = ot.ScriptList()
    script_list.ScriptRecord = [script_record]
    script_list.ScriptCount = 1

    gsub = ot.GSUB()
    gsub.Version = 0x00010000
    gsub.ScriptList = script_list
    gsub.FeatureList = feature_list
    gsub.LookupList = lookup_list

    table = newTable("GSUB")
    table.table = gsub
    return table


def add_gsub_from_aat(font, source_path, cache_dir, report, refresh=False):
    """
    Give `font` a GSUB derived from `source_path`'s AAT shaping.

    `font` must have the same glyph order as the font at `source_path` -
    i.e. call this on the optimised font before saving, since optimisation
    re-encodes bitmaps but never reorders or removes glyphs.
    """
    test_file = fetch_emoji_test(os.path.join(cache_dir, "emoji-test.txt"), refresh=refresh)
    sequences = parse_sequences(test_file)

    cmap = font.getBestCmap()
    glyph_order = font.getGlyphOrder()

    ligatures, stats = derive_ligatures(source_path, sequences, cmap, glyph_order)
    if not ligatures:
        raise SystemExit(
            "Could not derive any ligatures - the source font's AAT shaping "
            "produced nothing. Refusing to ship a font whose sequences are broken."
        )

    font["GSUB"] = build_gsub_table(ligatures)
    report.add(
        "synthesised GSUB from AAT: {} ligature rules from {} sequences "
        "({} not in cmap, {} did not compose)".format(
            len(ligatures), len(sequences), stats["unmapped"], stats["did_not_compose"]
        )
    )
    return len(ligatures)


def drop_aat_tables(font, report):
    """
    Remove Apple-only tables once GSUB carries the shaping.

    OTS strips these from web fonts anyway, so they are pure payload - but
    only drop them after a GSUB exists, or the font loses all composition.
    """
    if "GSUB" not in font:
        raise SystemExit("Refusing to drop AAT tables: font has no GSUB to replace them.")
    removed = []
    for tag in ("morx", "feat", "trak", "bgcl", "meta", "kerx", "ltag", "mort", "prop"):
        if tag in font:
            del font[tag]
            removed.append(tag)
    if removed:
        report.add("dropped AAT tables: " + ", ".join(removed))
