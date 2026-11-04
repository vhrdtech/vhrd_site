# vhrd_site

vhrd.tech: the company site, built with [Zola](https://www.getzola.org/) from Markdown and hand-written templates and CSS. No framework; the only script is the theme toggle and the code tabs.

## Use

```sh
just install         # Zola (the version pinned in AGENTS.md) into ~/.local/bin, no root
just serve           # http://127.0.0.1:1111 with live reload
just test            # zola check + build, every page in headless Chromium, brand files match vhrd_brand
just lint            # whitespace, the tools parse
just perf            # the front page's first screen on a slow phone: requests, KB, FCP, LCP
just preview TOKEN   # noindex build for https://shadow.vhrd.tech/TOKEN/ (README "Preview")
```

`just test` needs `chromium` and `uv` (the browser check is `tools/check_pages.py`, run with uv).

## Brand

Colours, type and the web stylesheet come from [vhrd_brand](https://github.com/vhrdtech/vhrd_brand) and are never edited here:

- `static/css/brand/tokens.css` and `vhrd.css` are copies of vhrd_brand's `web/` files. `just brand` pulls them from `~/git/vhrd_brand` (or `$VHRD_BRAND`) and writes the vhrd_brand version to `static/css/brand/VERSION`. `just test` fails when they differ from that checkout.
- `static/css/site.css` is this site's layer on top: grid, frame, traces, components. It uses tokens only, never hex values.
- Fonts are IBM Plex Sans, Mono and Serif, self-hosted as woff2 under `static/fonts/` (OFL, `OFL-IBMPlex.txt`). They are the Latin1, Latin2 and Pi subsets of IBM's npm releases (`@ibm/plex-sans` 1.1.0, `plex-mono` 2.5.0, `plex-serif` 2.0.0). The browser loads a subset only when a page uses one of its characters.
- Each Latin1 face also has a Core subset: ASCII and the few marks the site uses (· © – × µ, the smart quotes), about 30 % smaller. `just fonts` (`tools/fonts.py`) writes the Core files and their @font-face blocks and narrows the Latin1 ranges to the rest, so an English page loads only Core.
- The VHRD.TECH wordmark and the favicon are Audiowide outlines (OFL), so the font itself is never published. `just wordmark` redraws them from vhrd_brand's `Audiowide-Regular.ttf` with `tools/wordmark.py`. The output is `templates/partials/wordmark.html` (inline, coloured by CSS), `static/img/wordmark.svg` (stand-alone, dark colours) and `static/favicon.svg`.

## Components

Tera components in `templates/components.html` work in templates and in Markdown content alike, with no import:

```jinja
{% <vh.section label="Products" n="01" id="products" title="What we make"> %}
{% <vh.cards> %}
{{ <vh.card title="Donguru" href="/donguru/" sig="usb" n="2" badge="Coming Q1–Q2 2027"
   pitch="One cable to your board." specs={["Host: USB-C, USB 2.0", "MCU: STM32G0B1"]} /> }}
{% </vh.cards> %}
{% </vh.section> %}

{{ <vh.trace sig="power" from={8} to={50} label="VBUS 5 V" /> }}
{{ <vh.fig src="img/boards/b153.webp" alt="Donguru, top side" n="1" caption="B153 Donguru · rev B" width="1200" height="800" /> }}
```

- `vh.section`: a section with a numbered mono label, a title and a hairline with crosshairs.
- `vh.label`: the label alone.
- `vh.trace`: a PCB trace between two sections, in a signal colour: `power`, `usb`, `can`, `bus`, `analog` or `ctrl`.
- `vh.card` and `vh.cards`: a product card, and the ruled grid that holds cards.
- `vh.specs`: a mono key/value list from `"Key: value"` strings.
- `vh.fig`: a figure with the datasheet's corner marks and a "FIG. n" caption. Without `src` it shows a hatched placeholder.
- `vh.code_tabs`: Markdown panels split by a line `=== tab ===`, shown as tabs.

Images go under `static/img/boards/` (board renders) and `static/img/lab/` (lab photos).

## Board renders

`just renders` (`scripts/render_boards.py`, run with `uv`) rebuilds `static/img/boards/<bnnn>-<slug>/` from the newest revision of each board's KiCad project in `~/git/hw` (read-only, never written to). Per board it writes four views — `hero` (whole board, 3/4 angle, with margin), `detail` (a tighter 3/4 close-up), `top` and `bottom` — as a 2400px-wide PNG source plus AVIF/WebP at 480/640/1280/1920px, with a `manifest.toml` (product, revision, source file, hw git hash, per-view alt text).

- **The PNG sources never ship.** `config.toml` leaves them out of the build (`ignored_static`); the pages use the AVIF/WebP variants. Cards take 480/640/1280, the hero 640/1280/1920.
- **A new width without KiCad.** `just renders --variants` makes only the web variants that are missing, from the PNG sources in the repo, and updates the manifests.
- **Black solder mask, white silkscreen.** The real boards are mostly green; for the site every render forces a black mask with `kicad-cli pcb render --use-board-stackup-colors` against a **temporary copy** of the board's source directory whose stackup colours the script patches to black/white before rendering (`make_mask_black_copy` in the script). The files under `~/git/hw` are never changed.
- **3D model libraries** (generic KiCad parts plus our own `vhrd_mcu_stm_h7` etc.) are machine-local, not committed: the script reads `KICAD6_3DMODEL_DIR`..`KICAD10_3DMODEL_DIR` and `VHRD_3DMODEL_DIR` from the environment, defaulting to gpd-omarchy's layout (`~/sync/hw_tracking/kicad-packages3D`, `~/git/kicad-library/3dmodels`, Syncthing folder `hw_tracking`). A PC without that library (e.g. build-1) can't run `just renders` itself until it gets one too.
- **Cross-machine workflow**, when you're on a PC without the 3D library (never push/pull/rebase into another PC's checkout — fetch from it instead):
  ```sh
  # on the PC that has the library (e.g. gpd-omarchy):
  git init -q /tmp/site-render && cd /tmp/site-render
  git fetch -q <other-pc>:/path/to/vhrd_site <branch>
  git checkout -q --detach FETCH_HEAD
  just renders
  # on the PC with the working checkout: pull the output back and commit
  rsync -az <that-pc>:/tmp/site-render/static/img/boards/ static/img/boards/
  git add static/img/boards/ && git commit ...
  ```

### Fonts used in renders

Six of the boards' silkscreen text items name specific fonts (`(face "...")` in the `.kicad_pcb`). KiCad silently falls back to a default font when one is missing, which looks wrong without saying so, so `just renders` checks every named font against `fc-list` first and fails loudly (listing exactly what's missing and which board needs it) instead of rendering with the wrong glyphs.

These fonts are machine-local (`~/.local/share/fonts` and similar), not fetched by this script or committed to this repo:

| Font | Boards | Source | Notes |
| --- | --- | --- | --- |
| GOST type A | B135 | Roman's design-fonts library (`~/sync/design/Graphics/Fonts`, Syncthing, user-level, not installed by this repo) | |
| GOST type B | B153, B135 | same | |
| Venus Rising | all four | same | |
| Parsek | B125, B135 | same | |
| Seven Segment | B125 | same | |
| Noto Sans JP Thin | B153 | [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk), OFL-1.1 | installed at `~/.local/share/fonts/noto-sans-jp` |

On gpd-omarchy, `~/.config/fontconfig/conf.d/60-sync-design-fonts.conf` includes Roman's synced folder so `fc-list` sees the five design fonts without copying them anywhere; Noto Sans JP Thin was installed separately from its official OFL source. Licensing for the five design fonts is Roman's own call (he supplied the library and the source); this repo and script only consume what `fc-list` reports, and refuse to render instead of guessing when a font is missing.

## Speed

The front page is built to show fast on a slow phone. `just perf` (`tools/perf.py`) loads it at 390 px under Lighthouse's mobile throttling (150 ms round trip, 1.6 Mbit/s, CPU four times slower), with an empty cache, and prints the median requests, bytes, first and largest contentful paint and layout shift. The browser check keeps the first view on a phone under 200 KB.

- All CSS is inline in each page (about 11 KB gzipped): nothing blocks the first paint but the HTML.
- Only the hero render is eager, with `fetchpriority="high"` and a preload; every other image is `loading="lazy"`.
- Three font faces are preloaded, the ones the first screen sets text in, as Core subsets, with `font-display: swap`.
- The local server of the checks gzips text, as a real server would.

## Intro

The front page opens like an oscilloscope (`templates/partials/intro.html`, styles under "Intro" in `site.css`):

1. A dark screen with a faint graticule switches on, like a CRT.
2. A phosphor trace sweeps a step that rings and settles, with a glow, a bright beam spot and a slowly dimming trail.
3. The screen grows out to FIG. 1's red corner marks and becomes that frame, while the cover over the page clears.

How it is built:

- About 1.55 s in all: power-on 0.25 s, sweep 0.7 s, growth and reveal 0.6 s. The timings are CSS animations; the inline script (about 1.3 KB) only starts the growth when the sweep ends and clears the layer.
- The page is in the HTML and painted underneath from the start; the intro only covers it. The largest paint is the hero render either way, at the same time.
- The growth is a transform (no layout shift). The screen has the render's proportions, so the corners keep their size as they land.
- A click, key, wheel, touch or scroll skips it. It plays once per tab (sessionStorage), not when the URL has a #fragment, never under reduced motion and never without JavaScript. A CSS failsafe hides the layer after 4 s whatever the script does.
- The trace is the CAN cyan at a fixed phosphor brightness: the brightest signal colour on #0f0f10 and the colour a scope channel is read as. The brand red stays on the corners.

## Preview

A preview is a noindex build behind a share link, `https://shadow.vhrd.tech/<token>/`, with a fresh token for every preview:

1. Get a token from the share tool (`mx3 share token`).
2. `just preview TOKEN` builds with `VHRD_NOINDEX=1` for the base path `/<token>/` into `target/preview/<token>`. Every page gets `<meta name="robots" content="noindex, nofollow">`, and robots.txt disallows everything.
3. Upload the folder as it is with the share tool; the recipe prints the command: `tpm share target/preview/<token> --token <token> -e 3m`.
4. `just check-preview https://shadow.vhrd.tech/<token>/` runs the browser check against it.

- A build only works under the link it was built for, because every URL carries the token.
- The link is public to anyone who has it. Nothing private goes into the site.
- The robots.txt sits in a subdirectory, where crawlers don't read it. The meta tag on each page is what keeps the preview out of search results.
