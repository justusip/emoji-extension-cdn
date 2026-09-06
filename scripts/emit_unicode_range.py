"""
Generate the CSS `unicode-range` used by the extension's @font-face rule.

The extension restricts its emoji @font-face to a unicode-range so the font
is only consulted for emoji codepoints. Getting that list wrong is a silent
failure: any emoji outside the range falls back to the system font, so it
renders in the OS style while everything around it uses the selected style.
A hand-written range missed 372 of them, including the entire U+1FA00-1FAFF
block added since Unicode 14.

This derives the range from Unicode's own emoji-test.txt instead of guessing.

    python scripts/emit_unicode_range.py

Paste the output into emoji-extension/src/lib/emoji-font.ts. Re-run when a
new Unicode emoji version ships.

ASCII is excluded on purpose: emoji fonts map #, * and 0-9 as keycap bases
(1 as in 1-FE0F-20E3), and letting the emoji font claim those would render
every digit on every page as an emoji glyph. The cost is that keycap
sequences cannot compose, since the base digit never reaches the font.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import make_gsub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "build", "cache")

# Anything below this is ASCII punctuation/digits used as keycap bases.
# (c) U+00A9 is the first codepoint we actually want.
MIN_CODEPOINT = 0x00A9

# Ranges closer together than this get merged. Over-inclusion is harmless:
# unicode-range only says which codepoints to *consider* the font for, and
# the browser falls back normally when the font has no glyph. Under-
# inclusion is what breaks rendering, so err wide and keep the CSS short.
MERGE_GAP = 16

_SEQ_LINE = re.compile(r"^([0-9A-Fa-f ]+);\s*(\S+)")


def collect_codepoints(path):
    codepoints = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            match = _SEQ_LINE.match(line)
            if not match:
                continue
            for part in match.group(1).split():
                codepoints.add(int(part, 16))
    return codepoints


def to_ranges(codepoints, merge_gap=MERGE_GAP):
    ordered = sorted(codepoints)
    ranges = []
    start = prev = ordered[0]
    for cp in ordered[1:]:
        if cp == prev + 1:
            prev = cp
            continue
        ranges.append((start, prev))
        start = prev = cp
    ranges.append((start, prev))

    merged = []
    for lo, hi in ranges:
        if merged and lo - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return merged


def fmt(lo, hi):
    return "U+{:04X}".format(lo) if lo == hi else "U+{:04X}-{:04X}".format(lo, hi)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="re-download emoji-test.txt")
    ap.add_argument("--per-line", type=int, default=5, help="ranges per output line")
    args = ap.parse_args()

    test_file = make_gsub.fetch_emoji_test(
        os.path.join(CACHE, "emoji-test.txt"), refresh=args.refresh)

    all_cps = collect_codepoints(test_file)
    kept = {c for c in all_cps if c >= MIN_CODEPOINT}
    dropped = sorted(all_cps - kept)
    ranges = to_ranges(kept)

    print("{} codepoints -> {} ranges".format(len(kept), len(ranges)))
    print("excluded ASCII keycap bases: {}".format(
        " ".join("U+{:04X}".format(c) for c in dropped)))

    # Verify before printing something that will be pasted into the source.
    def covered(cp):
        return any(lo <= cp <= hi for lo, hi in ranges)

    assert all(covered(c) for c in kept), "range does not cover every emoji"
    assert not any(covered(c) for c in (0x23, 0x2A, 0x30, 0x39)), "range leaks ASCII"
    print("verified: every non-ASCII emoji covered, no ASCII digits claimed\n")

    parts = [fmt(lo, hi) for lo, hi in ranges]
    print("export const EMOJI_UNICODE_RANGE =")
    for i in range(0, len(parts), args.per_line):
        chunk = ", ".join(parts[i:i + args.per_line])
        last = i + args.per_line >= len(parts)
        print('    "{}{}"{}'.format(chunk, "" if last else ", ", ";" if last else " +"))


if __name__ == "__main__":
    main()
