"""
Check that every font in manifest.json is actually live on jsDelivr.

Run this after pushing a tag and before pointing the extension at it. A
tagged jsDelivr URL is immutable once fetched, so it is worth ten seconds
to confirm the tag resolves and the bytes match what you built.

    python scripts/check_published.py --user justusip --tag v1.0.0
    python scripts/check_published.py --user justusip --tag v1.0.0 --verify-hash
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "manifest.json")

CDN = "https://cdn.jsdelivr.net/gh/{user}/{repo}@{tag}/{path}"


def check(url, want_bytes, verify_hash, want_sha):
    req = urllib.request.Request(
        url,
        method="GET" if verify_hash else "HEAD",
        headers={"User-Agent": "emoji-extension-cdn/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            ctype = resp.headers.get("content-type", "")
            length = int(resp.headers.get("content-length") or 0)
            body = resp.read() if verify_hash else b""
    except urllib.error.HTTPError as exc:
        return False, "HTTP {}".format(exc.code)
    except Exception as exc:  # noqa: BLE001 - report any transport failure
        return False, str(exc)

    problems = []
    if status != 200:
        problems.append("HTTP {}".format(status))
    if "font" not in ctype and "octet-stream" not in ctype:
        problems.append("content-type {}".format(ctype))
    if verify_hash:
        got = hashlib.sha256(body).hexdigest()
        if got != want_sha:
            problems.append("sha256 mismatch")
        length = len(body)
    if length and want_bytes and abs(length - want_bytes) > 0:
        problems.append("{} bytes, expected {}".format(length, want_bytes))

    return (not problems), "; ".join(problems) or "{:.1f} MB".format(length / 1e6)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", required=True, help="GitHub user or org")
    ap.add_argument("--repo", default="emoji-extension-cdn")
    ap.add_argument("--tag", required=True, help="tag, branch or commit (e.g. v1.0.0)")
    ap.add_argument("--verify-hash", action="store_true",
                    help="download each font and compare SHA-256 (slower, thorough)")
    args = ap.parse_args()

    with open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)

    print("Checking {} fonts at @{}\n".format(len(manifest["fonts"]), args.tag))
    failures = 0
    for record in manifest["fonts"]:
        url = CDN.format(user=args.user, repo=args.repo, tag=args.tag, path=record["file"])
        ok, detail = check(url, record["bytes"], args.verify_hash, record.get("sha256"))
        print("  {} {:34s} {}".format("OK  " if ok else "FAIL", record["id"], detail))
        if not ok:
            print("       {}".format(url))
            failures += 1

    if failures:
        raise SystemExit(
            "\n{} font(s) not served correctly. Common causes: the repo is "
            "private, the tag was not pushed, or a file is over jsDelivr's "
            "20 MB limit.".format(failures)
        )
    print("\nAll fonts live. Now point the extension at this tag:\n"
          "  python scripts/emit_definitions.py --user {} --tag {} "
          "--out ../emoji-extension/src/data/definitions.json".format(args.user, args.tag))


if __name__ == "__main__":
    main()
