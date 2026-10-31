# Bundled music font

`Bravura.woff2` is the unmodified Bravura music font from Steinberg Media
Technologies GmbH, distributed under the SIL Open Font License 1.1.
The full copyright notice and license are in [Bravura-LICENSE.txt](Bravura-LICENSE.txt).
The font is served locally; the practice room does not fetch third-party assets.

- Source: [steinbergmedia/bravura](https://github.com/steinbergmedia/bravura)
- Commit: `37b194378b710cc40e406ab6c4b07608bb9548ae`
- Original file: `redist/woff/Bravura.woff2`
- SHA-256: `e68df66446e3ffa6f474ce9eb2949e938102406f12d8f40ad8754398c50f55d4`

Legacy JSON scores use SVG and a small set of SMuFL glyphs from this font.

## ABC notation

New scores use [abcjs](https://github.com/paulrosen/abcjs), pinned to 6.7.2 (MIT).
`abcjs.min.js` is its locally served browser bundle. `abc-parser.cjs` bundles the
same version's parser for a Node subprocess; it needs no npm packages at runtime.
Keep `abcjs-LICENSE.md` and `abcjs.min.js.LICENSE` with both artifacts.
Run `npm ci` and `npm run build:notation` to reproduce them using the locked
esbuild development dependency. No CDN, soundfont download or remote script is used.
The parser adapter and rendering geometry use version-specific internals: update
them only together with parser/rendering/playback regression checks.

## PDF material extraction

`pypdfium2` and Pillow are installed from `uv.lock`, not vendored into Git.
pypdfium2 carries BSD-3-Clause/Apache-2.0 and PDFium dependency notices; Pillow
uses MIT-CMU. Their installed distributions include the full license files.
PDFium runs in a disposable bounded subprocess. Downloaded lessons, PDF pages and
reviewed transcriptions stay in the local material cache; these software licenses
do not relicense teaching material. Source metadata retains the original links.
