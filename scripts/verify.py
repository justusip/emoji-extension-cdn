"""
Render every built font in headless Edge/Chrome and produce a contact sheet.

Optimising a colour font can break it in ways no size check will catch, so
this renders the real thing in the real engine. Look at build/verify.png
after every build and check for:

  * flat black outlines  -> the colour table the browser wanted is gone
    (Chrome ignores OT-SVG; a font that only has SVG renders from `glyf`)
  * split sequences      -> shaping is broken. ZWJ families, flags and skin
    tones are single glyphs only if the font's shaping table survived.
    Apple's font carries AAT `morx` rather than OpenType GSUB; HarfBuzz
    handles that, but it is exactly the sort of thing a rebuild can lose.
  * tofu / blanks        -> the codepoint is missing from that font

    python scripts/verify.py
    python scripts/verify.py --font-size 44 --open
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "fonts")
BUILD = os.path.join(ROOT, "build")

# Each row is (label, text). These are chosen to exercise a different part
# of the font rather than to look pretty.
SAMPLES = [
    ("basic", "\U0001F600\U0001F44D\U0001F436\U0001F30D\U0001F355"),
    ("unicode 14+", "\U0001FAE0\U0001FA77\U0001FAE8\U0001F979"),
    ("skin tone", "\U0001F44D\U0001F3FD\U0001F64C\U0001F3FF"),
    ("ZWJ", "\U0001F468\u200D\U0001F469\u200D\U0001F467\u200D\U0001F466\U0001F469\u200D\U0001F4BB"),
    ("flags", "\U0001F1EF\U0001F1F5\U0001F1FA\U0001F1F8\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"),
    ("keycap", "1\uFE0F\u20E32\uFE0F\u20E3#\uFE0F\u20E3"),
]

EDGE_CANDIDATES = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]


def find_browser():
    env = os.environ.get("EMOJI_CDN_BROWSER")
    if env and os.path.exists(env):
        return env
    for path in EDGE_CANDIDATES:
        if os.path.exists(path):
            return path
    for name in ("msedge", "chrome", "chromium", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit(
        "No Chromium-based browser found. Set EMOJI_CDN_BROWSER to a "
        "chrome/msedge executable."
    )


def build_html(font_files, font_size):
    faces = []
    rows = []
    for path in font_files:
        fid = os.path.splitext(os.path.basename(path))[0]
        url = "file:///" + os.path.abspath(path).replace("\\", "/")
        faces.append(
            '@font-face{{font-family:"F-{0}";src:url("{1}") format("woff2");font-display:block}}'.format(fid, url)
        )
        cells = "".join(
            '<td class="s"><span style=\'font-family:"F-{0}"\'>{1}</span></td>'.format(fid, text)
            for _label, text in SAMPLES
        )
        rows.append('<tr><th>{0}</th>{1}</tr>'.format(fid, cells))

    headers = "".join("<td class=h>{0}</td>".format(label) for label, _ in SAMPLES)
    return """<!doctype html><meta charset="utf-8"><style>
{faces}
html,body{{margin:0;background:#fff;font:13px/1.3 -apple-system,Segoe UI,sans-serif;color:#222}}
table{{border-collapse:collapse}}
th{{text-align:right;padding:6px 12px;font-weight:600;white-space:nowrap;color:#444}}
td.h{{font-size:11px;color:#888;padding:4px 10px;text-align:center;text-transform:uppercase;letter-spacing:.04em}}
td.s{{padding:6px 10px;font-size:{size}px;line-height:1.35;white-space:nowrap;border-left:1px solid #eee}}
tr:nth-child(even){{background:#fafafa}}
</style><table><tr><th></th>{headers}</tr>
{rows}
</table>""".format(faces="\n".join(faces), size=font_size, headers=headers, rows="\n".join(rows))


def render(html, out_png, browser, width, height):
    tmp = tempfile.mkdtemp(prefix="emoji-verify-")
    html_path = os.path.join(tmp, "verify.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=2",
        # Fonts load asynchronously; virtual time lets the screenshot wait
        # for them without a fixed sleep.
        "--virtual-time-budget=15000",
        "--screenshot=" + out_png,
        "--window-size={},{}".format(width, height),
        "file:///" + html_path.replace("\\", "/"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(out_png):
        raise SystemExit("Render failed.\n{}\n{}".format(proc.stdout, proc.stderr))
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--font-size", type=int, default=40)
    ap.add_argument("--open", action="store_true", help="open the sheet when done")
    args = ap.parse_args()

    font_files = sorted(glob.glob(os.path.join(FONTS, "*.woff2")))
    if not font_files:
        raise SystemExit("No fonts built yet. Run: python scripts/build_all.py")

    os.makedirs(BUILD, exist_ok=True)
    out_png = os.path.join(BUILD, "verify.png")

    width = 260 + len(SAMPLES) * (args.font_size * 6)
    height = 90 + len(font_files) * int(args.font_size * 1.9)

    browser = find_browser()
    print("Rendering {} fonts with {}".format(len(font_files), os.path.basename(browser)))
    render(build_html(font_files, args.font_size), out_png, browser, width, height)
    print("Wrote {}".format(out_png))
    print("Check for black outlines (missing colour table), split sequences "
          "(broken shaping) and blanks (missing coverage).")

    if args.open:
        os.startfile(out_png)  # noqa: S606 - Windows only, developer tool


if __name__ == "__main__":
    main()
