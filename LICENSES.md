# Licensing of the fonts in this repo

The build scripts in `scripts/` are MIT. The font binaries in `fonts/` are
**not** covered by that — each is redistributed under its own upstream terms,
and they are not all equally permissive.

Read this before making the repo public or shipping it to an extension store.

---

## ⚠️ Apple Emoji — proprietary, not licensed for redistribution

`fonts/apple-emoji.woff2`

Apple Color Emoji is copyright Apple Inc. Apple does not grant a licence to
redistribute it, extract it, or serve it to non-Apple devices. The macOS EULA
restricts the bundled fonts to use on Apple hardware.

Publishing this file on a public CDN is copyright infringement, regardless of
the fact that dozens of community repos do exactly this and have done for
years. Practically:

- Apple has not, historically, pursued takedowns against these mirrors.
- Chrome Web Store and AMO review have not historically blocked extensions
  that reference them.
- Neither of those is a licence, and neither is a guarantee. A DMCA takedown
  of the CDN repo would break the Apple style for every installed user.

**This is a risk you are accepting, not one the build resolves.** If you want
to avoid it, drop the `apple-emoji` entry from `fonts.json`, rebuild, and the
extension will simply not offer that style.

Source: [samuelngs/apple-emoji-ttf](https://github.com/samuelngs/apple-emoji-ttf),
which republishes the macOS system font.

---

## The rest

| Font | Licence | Attribution required |
|---|---|---|
| Microsoft Fluent 3D | MIT | Microsoft |
| Microsoft Fluent Flat | MIT | Microsoft |
| Microsoft Fluent High Contrast | MIT | Microsoft |
| Google Noto Color Emoji | OFL-1.1 | Google |
| Noto Emoji Mono | OFL-1.1 | Google |
| Google Blobmoji | Apache-2.0 / OFL-1.1 | Google, C1710 |
| Twemoji | CC-BY-4.0 (artwork), MIT (code) | **Yes** — Twitter / jdecked |
| OpenMoji Color | CC-BY-SA-4.0 | **Yes** — OpenMoji |
| OpenMoji Black | CC-BY-SA-4.0 | **Yes** — OpenMoji |
| Firefox OS Emoji | Apache-2.0 (code), CC-BY-4.0 (artwork) | **Yes** — Mozilla |

Four of these require attribution in anything that ships them:

- **Firefox OS Emoji** — the code is Apache-2.0 and the artwork CC-BY 4.0.
  Credit Mozilla.
- **Twemoji** — CC-BY 4.0. Credit Twitter and the twemoji project.
- **OpenMoji** (both variants) — CC-BY-SA 4.0. Credit openmoji.org. Note the
  **ShareAlike** clause: derivative *artwork* must be shared alike. Serving the
  font unmodified alongside a credit satisfies this; the extension's own source
  is not a derivative of the artwork.

The extension surfaces this by showing each style's `homepage` and `license`
from `definitions.json`, which is generated from this repo's `manifest.json`.

## Optimisation and licence terms

The build re-encodes bitmaps to a 256-colour palette and drops redundant
tables. This is a technical format change, not a redesign of the artwork —
it does not create a new copyright interest, and it does not exempt anything
here from the terms above.
