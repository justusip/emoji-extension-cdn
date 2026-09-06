"""
Generate the extension's src/data/definitions.json from this repo's manifest.

Keeping the extension's font list generated rather than hand-maintained means
the CDN tag, file names and metadata can never drift out of sync with what was
actually published.

    python scripts/emit_definitions.py --user justusip --tag v1.0.0 \
        --out ../emoji-extension/src/data/definitions.json
"""

from __future__ import annotations

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "manifest.json")

CDN = "https://cdn.jsdelivr.net/gh/{user}/{repo}@{tag}/{path}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", required=True, help="GitHub user or org")
    ap.add_argument("--repo", default="emoji-extension-cdn")
    ap.add_argument("--tag", required=True, help="tag to pin (e.g. v1.0.0)")
    ap.add_argument("--out", required=True, help="path to definitions.json")
    args = ap.parse_args()

    with open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)

    if args.tag in ("main", "master", "HEAD"):
        print("WARNING: branch URLs are only cached for 12 hours and can change "
              "under your users. Tag a release and pin that instead.")

    # Helper fonts are published but never offered as styles; they are
    # referenced by the styles that borrow glyphs from them.
    by_id = {r["id"]: r for r in manifest["fonts"]}

    def cdn_url(record):
        return CDN.format(user=args.user, repo=args.repo,
                          tag=args.tag, path=record["file"])

    definitions = []
    for record in manifest["fonts"]:
        if record.get("helper"):
            continue
        entry = {
            "id": record["id"],
            "title": record["title"],
            "description": record["description"],
            "homepage": record["homepage"],
            "license": record["license"],
            # Served from the CDN; nothing is bundled in the extension.
            "path": cdn_url(record),
            "bytes": record["bytes"],
            # Static preview strip bundled with the extension, so the chooser
            # can show every style without downloading a single font.
            "preview": "/previews/{}.png".format(record["id"]),
        }
        if record.get("monochrome"):
            entry["monochrome"] = True
        # Sets with no flag glyphs of their own get them from a helper font,
        # layered in as a second @font-face limited to regional indicators.
        helper = by_id.get(record.get("flags_from") or "")
        if helper:
            entry["flagsPath"] = cdn_url(helper)
        definitions.append(entry)

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(definitions, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    total = sum(d["bytes"] for d in definitions)
    print("Wrote {} entries to {}".format(len(definitions), out))
    print("Pinned to {}@{} ({:.1f} MB across all styles, none bundled)".format(
        args.repo, args.tag, total / 1e6))


if __name__ == "__main__":
    main()
