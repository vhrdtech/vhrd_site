# Changelog

## [Unreleased]

### Added

- Fast first load (SITE-8 fast-first-load). On a phone the front page's first view went from 187 KB to 143 KB and from 14 to 10 requests; on a slow 4G phone the first paint came at 484 ms instead of 724 ms and the largest paint at 1400 ms instead of 1592 ms. All CSS is inline, the hero render is preloaded with high priority, three Core font subsets are preloaded, and the PNG render sources no longer ship with the site (54 MB to 17 MB built).
- `just perf` (`tools/perf.py`): the front page's first screen on a slow phone, as Lighthouse's mobile run measures it, and when the intro clears.
- `just fonts` (`tools/fonts.py`): Core subsets of the IBM Plex Latin1 faces, about 30 % smaller.
- Board renders at 480 px for the cards, and `just renders --variants` to make missing widths from the PNG sources without KiCad.
- Zola site skeleton (Zola 0.23.6, Tera 2 components): base template, header, footer with the build stamp, 404, robots.txt, sitemap and blog feed.
- Brand from vhrd_brand: `tokens.css` and `vhrd.css` pulled by `just brand` (v0.9.9), IBM Plex Sans, Mono and Serif self-hosted (OFL, woff2 subsets), the VHRD.TECH wordmark and favicon as Audiowide outlines (`just wordmark`).
- Dark and light theme: follows the system, a toggle in the header remembers the choice.
- The look: drawing grid, framed column with crosshairs, mono caps labels, FIG. captions with corner marks, PCB traces in the signal colours between sections, drawn in on scroll (off under reduced motion).
- Components for templates and Markdown: `vh.section`, `vh.label`, `vh.trace`, `vh.card`, `vh.cards`, `vh.specs`, `vh.fig`, `vh.code_tabs`.
- Page stubs for the site map: /, /donguru, /report, /can, /software, /open-source, /lab, /services, /about, /blog, /shop.
- `tools/check_pages.py`: every page in headless Chromium at phone, tablet and desktop widths in both themes, part of `just test`.
- `scripts/portfolio-photos/`: `extract_pages.py` (dump a PDF's pages and embedded
  images for review) and `build_lab_images.py` (crop/encode the picked images into
  `static/img/lab/`), so the selection can be reproduced or extended later.
- Own-work lab photos from Roman's portfolio, cropped and compressed to AVIF + WebP
  (640/1280/1920px wide, never upscaled) under `static/img/lab/<slug>/`, one
  `manifest.toml` per item (title, portfolio page, facts, alt text, tools). Covers
  the 11 items cleared 4 Nov 2026: thermocouple AFE, CAN servo controller,
  Raspberry Pi carrier board, BMS (6-10S, 50A/100A), torque sensor AFE, 6-step and
  FOC motor controller, propeller test stand, the lab, 3D laser scanner (AOI),
  granite CNC, eSkate. No employer work included. (P2633#4nov-0920)
- `just renders` (`scripts/render_boards.py`, uv): rebuilds `static/img/boards/<bnnn>-<slug>/`
  from the newest revision of each board's KiCad project in `~/git/hw` — hero (whole board,
  3/4 angle, with margin), detail (tighter 3/4 close-up), top and bottom views via
  `kicad-cli pcb render` (transparent, raytraced), cropped tight, 2400px PNG source plus
  AVIF/WebP at 640/1280/1920px, with a `manifest.toml` per board (product, revision, source
  file, hw git hash, per-view alt text). Every render forces a black solder mask / white
  silkscreen on a temp copy of the board source, never touching `~/git/hw`; the silkscreen
  fonts each board names are checked against `fc-list` first, failing loudly on a missing one
  instead of silently falling back. Covers the front-page boards: Donguru (B153), rePort
  (B200), B125, B135; the rest of `~/git/hw`'s boards are a later task. (P2633#4nov-0919d)
- `vh.fig` takes images by path: `stem` and `widths` give AVIF and WebP in several widths with `sizes`; width and height come from the file; the placeholder shows until the file exists, so board renders appear when they land in `static/img/boards/`.
- The browser check holds the first view on a phone to 200 KB on the wire and fails on an image without alt, width or height.
- just recipes: `test`, `lint`, `install` (Zola into ~/.local/bin), `brand`, `wordmark`, `serve`, `build`, `check-browser`, `check-preview URL`, `preview TOKEN` (noindex build for a share link, https://shadow.vhrd.tech/TOKEN/, uploaded with `tpm share`).
- /open-source lists every public crate from `data/stack.toml` in order: wire_weaver, shrink_wrap, exact_units, embedded_bedrock, canzone (marked work in progress), choreograph, egui_tabular, vhrd_egui.
- Lab photo of the 3D laser scanner's linear rails (portfolio page 14), and `build_lab_images.py` can build single images by name.
- The front page, every section filled (draft copy, facts from the project and crate READMEs): hero, the three products (Donguru, rePort, the CAN line), the Donguru spotlight with its block diagram, the software panel (GUI, debugger, code tabs) with IOWeaver, RockFace and WireWeaver, "Work we are proud of" from four areas (B125 Ethernet to CAN FD, B135 USB to CAN FD, the 3D laser scanner on its linear rails, RockFace with its log view and icon), the open-source stack "from register to GUI" (wire_weaver, shrink_wrap, exact_units and embedded_bedrock, with their logos in the theme's variant, a code sample each and, where published, the crates.io version and downloads fetched at build time), notify and contact.
- RockFace screenshots from the portfolio (page 9, its old name "MCU tracer - debugger"): the whole window, with transparent rounded corners, in the software panel's Debugger tab, and the log view on the lab card, where the text stays readable at card size. `build_lab_images.py` takes an optional corner radius for app windows; `vh.card` takes an `icon` shown before the title.
- Image placeholders (LOOK-5 scope-placeholders): a picture still on its way shows as a small oscilloscope screen in its own box, graticule and sweeping trace like the intro, and fades in over it when it arrives. No request, no layout shift, no sweep under reduced motion. The browser check covers it.
- Intro on the front page (LOOK-4 scope-intro), like an old CRT oscilloscope powering up: a bright dot in the centre opens into a rectangle that overshoots, wobbles and settles with its corners on four crosses at the corners of the visible screen, then fades to the page (about 1.4 s). On a slow link a sine runs with "LOADING", "SLOW LINK · CLICK TO SKIP" after 5 s, "TRIG'D" when the hero render and fonts are in (at most 20 s). It plays on every load of the home page (not with a #fragment), a click, key, wheel, touch or scroll skips it, the footer's "Replay intro" plays it again, and it never shows under reduced motion or without JavaScript. The page is painted underneath from the start: the largest paint stays at 1.4 s on a slow phone, no layout shift. The browser check covers the fast path, the slow path and the replay.
- The view frame: a cross at each corner of the visible screen on every page, under the header and at the bottom, on the column's edges.

### Changed

- cnt joins the open-source stack after embedded_bedrock, on the front page and /open-source: a counter in an interrupt without a log or a critical section, read over the debug probe with `cnt tui`. The sample compiles for Cortex-M0+ and M4F.
- Every code card fits a phone without a sideways scroll: the samples are written to 44 columns, and below 26rem the code runs to the card's edges in a smaller face. The browser check holds every card marked `fits` at seven widths from 320 to 1440 px.
- The name is VHRD everywhere: page titles ("VHRD · Tools for people who build hardware"), the feed, the footer ("© 2026 VHRD · vhrd.tech") and the home links' labels. No more "VHRD Tech" or "Vhrd.tech AS".
- Lab copy toned down: the lab page says "Selected work from our own bench: digital, power, communications and motors.", and the front page's lab lead names the four pieces instead of areas.
- wire_weaver and shrink_wrap show their icon SVGs from wire_weaver's docs, the dark variant on the dark theme, instead of the PNG logos.
- The RockFace lab card shows the timeline view (portfolio page 9, cropped 4:3 to stay readable) instead of the log table.
- The Donguru product card shows the same render as the hero, so a phone loads it once; with the board renders in place the first view on a phone is 187 KB of the 200 KB budget.
- Traces between sections are routed like PCB tracks: vertical and horizontal runs, 45° corners, a via at each end and the net name on the run (they used to be stretched diagonals).
- Headlines are in the text colour; the brand red marks one word of the hero and stays for accents.
- Arrows after links are CSS masks instead of arrow characters, so no page loads the Pi font subsets for them; the skip link uses the medium weight, so the semibold face is not loaded either.
- The shrink_wrap card shows the bit-packing: an I2C write (a 7- or 10-bit address, two flags, a nibble, an optional 10-bit timeout and a payload) is 7 bytes on the wire, 20 as a repr(C) struct. The bytes come from running it against shrink_wrap 0.2.0.
- The exact_units card shows that V/V and W/W are different kinds: 2 V/V is +6.02 dB (20·lg), 2 W/W is +3.01 dB (10·lg), `db!(-6)` is 501 mV/V but 251 mW/W, and a plain Ratio has no dB at all (a compile error). The values come from running it against exact_units.
- The embedded_bedrock card fits a phone without a sideways scroll (35 columns, down to 320 px wide) and shows the shared clock: steered by the host over WireWeaver, locked within 2 ms, `ww sync` locks the boards in 1.2-1.6 s, about 1.5 KB of flash on Donguru, and a task that waits for a shared instant. It compiles for a Cortex-M0+ against bedrock_sync.

### Fixed

- The open-source stack's vias sit on the track's centre (they were 6 px to the left, the track running along their side). The browser check now checks it on every page, width and theme.

