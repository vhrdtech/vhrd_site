# Working on vhrd_site

vhrd.tech, a static site built with Zola: Markdown in `content/`, Tera templates in `templates/`, hand-written CSS. Its one server-side part is `vhrd_notify`, a small Rust service for the Get notified forms (`server/`, "Notify service" below). It is the home for Donguru's launch, Pinsmith, the CAN line and the software, so every page answers: what it is, why it is good, what to do next.

## Zola version

**Zola 0.23.6**, pinned in `justfile` (`zola_version`). `just install` puts that release binary in `~/.local/bin`, and `just test` refuses any other version. Zola 0.23 uses Tera 2: there are no shortcodes and no macros, only components (`{% component %}`, called as `{{ <vh.card ... /> }}`). Undefined variables are errors, tests take keyword arguments (`is starting_with(pat=...)`) and arrays are indexed with `[0]`. Highlighting is configured under `[markdown.highlighting]`. Bump the pin on purpose, with a CHANGELOG line.

## FEATURES.md and CHANGELOG.md

[FEATURES.md](FEATURES.md) tracks what exists and what is planned, with stable IDs (`SITE-1`, `LOOK-3`, `BLOCK-2`, `PREVIEW-1`). Name them with their slug when talking to the user (`LOOK-3 grid-and-traces`). Get a new id with `tpm work claim AREA`. Update FEATURES.md in the same commit as the change.

[CHANGELOG.md](CHANGELOG.md) gets an entry for every visible change under `## [Unreleased]`. A branch never writes a version heading: `tpm land` turns `[Unreleased]` into `## [x.y.z] - date` and tags it. Every version gets its own section. Questions like "what's new" are answered from it, newest first, with FEATURES.md for current status.

## Layout

- `config.toml`: site settings; `[extra]` holds the company line, contact mail, header links and the notify button.
- `content/`: one Markdown file per page (`donguru.md` is `/donguru/`). Stubs carry `extra.stub = true`. No blog and no feed. WordPress is gone from vhrd.tech: its old paths (posts, /feed/, /product/, /cart/, /checkout/, ...) redirect on the server with `deploy/redirects.map`, and nothing of WordPress (wp-*, PHP, those paths) may be generated here. `/shop/` is the site's own page; every other path gets the site's 404 page.
- `templates/base.html`: the page frame, with the view frame's four crosses (`.view-frame`) and an `intro` block the home page fills. `partials/header.html`, `partials/footer.html` (build stamp from `VHRD_GIT` and `VHRD_BUILT`, which the justfile sets) and `partials/wordmark.html` (generated).
- `templates/components.html`: the `vh.*` components, usable in templates and Markdown ("Components" below).
- `templates/index.html`: the landing page; `partials/intro.html` is its oscilloscope intro, with its script in `partials/intro-script.html` at the end of the body ("Intro" below). `page.html` is a plain page, `section.html` is the blog list, and there are `404.html` and `robots.txt`.
- `static/css/brand/`: `tokens.css` and `vhrd.css` from vhrd_brand (`just brand`). Never edit these here; change vhrd_brand and pull.
- `static/css/site.css`: the site's own layer. `base.html` inlines all the CSS (fonts.css, the brand files and site.css) into each page with `load_data`, so there is no render-blocking request. A part only some pages have keeps its styles in its own file, inlined only where `extra.styles` names it (`intro.css`, `stack.css`, `term.css`; "Performance" below). A light flash between pages in desktop Firefox is Firefox's own tab background, not the site's: "The light blink between pages in Firefox" below before chasing it again. `static/js/site.js`: theme toggle, tabs, the image placeholders' marking and the signup form's fetch, nothing else.
- `static/fonts/`: IBM Plex woff2 subsets and `fonts.css` ("Brand and fonts" below). `static/img/boards/` holds board renders (`just renders`, "Board renders" below) and `static/img/lab/` lab photos.
- `tools/wordmark.py` draws the wordmark and favicon outlines. `tools/check_pages.py` is the browser check, `tools/perf.py` measures the first screen on a slow phone, `tools/fonts.py` cuts the Core font subsets and the small Greek faces (Ω, μ) from vhrd_brand's full fonts, `tools/og_images.py` writes the link-preview images under `static/img/og/` ("Link previews" below).
- `server/`: the Cargo workspace (`Cargo.toml` at the root) of the notify service: `vhrd_notify` (library: `email.rs` the address check, `store.rs` the intake and the records, `list.rs` what happens to a record, `token.rs` the links' tokens, `mail.rs` composing and sending a mail, `outbox.rs` the worker, `limit.rs` the rate limit, `server.rs` the signup endpoint, `links.rs` the confirm, remove and unsubscribe endpoints, `config.rs` the settings; `mail/confirm.txt` the confirmation text), `vhrd_notify_cli` (the `vhrd_notify` binary: serve, list, count, export, send, mail-test, delete) and `vhrd_notify_activate` (the activator that takes a release the Deploy workflow uploaded, root's on the server, a crate of its own so an upload never checks itself; its end-to-end tests in `tests/activate.rs` are also the fake systemctl and service, and run one at a time, `.config/nextest.toml`). `deploy/notify.toml` is its settings on the server, `deploy/vhrd-notify.service` its user unit (user vhrd-notify), `deploy/vhrd-notify-activate.path` and `.service` the activator's units, `deploy/nginx-notify.conf` the nginx block, `ship.toml` what `tpm ship` ships when GitHub can't (fallback only). Dependencies without default features and with no C library (no SQLite: the store is a plain file at this size).
- `content/privacy.md`: the privacy note the forms link to. Any change to what the site or the service keeps changes it in the same commit.
- `.github/workflows/deploy.yml`: the only way the site and the notify service reach vhrd.tech ("Deploy" below); `.github/deploy/known_hosts` pins the server's host key. `tools/check_live.py` checks a live build before upload and the site after it. `tools/notify_plan.py` decides whether a run ships the notify service.
- `data/term/`: the terminal captures on /software (`captures.toml`, and per capture the screen as HTML and its TOML), recorded by `tools/term_capture.py` (`just captures`, "Terminal captures" below) and shown by `vh.term`. Never edited by hand. `tools/term/units_demo` is the crate behind the exact_units compile error, `tools/term/ww_evolution` the API behind the evolution check.
- `data/links.toml`: our projects' names and where a mention leads (a page, a card on /open-source or a repo). `vh.ref` and `vh.linkify` read it, and `tools/mentions.py` (in the browser check) fails a page whose first mention of a name is not a link.
- `data/stack.toml`: the open-source crates in their /open-source order (layer, logos per theme, code sample, which are on crates.io); `front = true` puts one on the front page too. `partials/crate-stack.html` draws them for both pages, `templates/open-source.html` is the /open-source page. `data/repos.toml`: every other repository on /open-source, by area (`partials/repo-list.html`); its head names the repos left off and why.

## Brand and fonts

Colours, type and the web stylesheet come from [vhrd_brand](https://github.com/vhrdtech/vhrd_brand) and are never edited here:

- `static/css/brand/tokens.css` and `vhrd.css` are copies of vhrd_brand's `web/` files. `just brand` pulls them from `~/git/vhrd_brand` (or `$VHRD_BRAND`) and writes the vhrd_brand version to `static/css/brand/VERSION`. `just test` fails when they differ from that checkout.
- Fonts are IBM Plex Sans, Mono and Serif, self-hosted as woff2 under `static/fonts/` (OFL, `OFL-IBMPlex.txt`). They are the Latin1, Latin2 and Pi subsets of IBM's npm releases (`@ibm/plex-sans` 1.1.0, `plex-mono` 2.5.0, `plex-serif` 2.0.0). The browser loads a subset only when a page uses one of its characters.
- Each Latin1 face also has a Core subset: ASCII and the few marks the site uses (· © – × µ ° ± ², the smart quotes), about 30 % smaller. `just fonts` (`tools/fonts.py`) writes the Core files and their @font-face blocks and narrows the Latin1 ranges to the rest, so an English page loads only Core. The Plex web faces have no Greek, so it also cuts a Greek face (Ω, μ, about 1 KB) for Plex Mono Regular and Plex Sans Regular, Italic and SemiBold from vhrd_brand's full fonts (`$VHRD_BRAND/typst/vhrd/fonts`), loaded only where a page uses those letters.
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
- `vh.ref`: a link to one of our projects by its name, from `data/links.toml`: `{{ <vh.ref name="WireWeaver" /> }}`. Link the first mention of a project in each section; the browser check fails a page whose first mention is not a link (`tools/mentions.py`).
- `vh.linkify`: text from data with the first mention of each project in `data/links.toml` linked, once per address: `{{ <vh.linkify text={f} here={page.path} /> }}`. `md={true}` renders inline Markdown first; a name whose address is the page itself, or that is part of a longer word or code, stays plain.
- `vh.mail`: a mail link without the address in the HTML: `{{ <vh.mail to="projects" subject="Project" /> }}`. The inline script in `base.html` builds the mailto link; without JavaScript it reads "projects at vhrd.tech". With `text` (and `cls`) it is a labelled button that shows only once the script has made it a link.

Images go under `static/img/boards/` (board renders) and `static/img/lab/` (lab photos).

## Terminal captures

/software shows real runs of the command-line tools (cnt, ww's API tree and evolution check, bedrock-lint, an exact_units compile error) as text with their colours, not as pictures and not mocked up. `just captures` (`tools/term_capture.py`, run with uv) records them:

- `data/term/captures.toml` lists each one: the command as typed, the checkout it runs in, its natural width (`wide`).
- Each command runs twice: at `wide`, where no line may wrap (the tool stops when a line fills it), into `ID.html`, and at 44 columns for a phone into `ID.narrow.html`. A bench recording keeps its one width.
- Each run is in a pseudo-terminal, and a terminal emulator (pyte) keeps its screen, written as spans; the command, the version (its `--version`), the commit it ran on and the date go to `data/term/ID.toml`.
- `vh.term` shows a capture as a figure: the command on a prompt line, the screen, and a caption with the version, the source and the date. Nothing runs when the site is built, and the page needs no script.
- The figure takes the column's whole width, wider than the prose, which keeps its measure. A container query on the figure shows the wide screen from 40rem (or where it fits whole at the smallest face) and the narrow one below that.
- The face shrinks from 0.75rem to fit the longest line, down to 0.6875rem wide and 0.625rem narrow. Past that the box scrolls sideways, with a glow at the edge that has more beyond it and a visible scrollbar. Nothing is ever clipped, and the box opens at the start of its lines. The browser check holds every figure to this at 390, 768, 1440, 1920 and 2560 px.
- A full-screen program that needs hardware (`cnt tui` on a board through a probe) is recorded on the bench with asciinema; `--cast ID=FILE` replays the recording to the second given in captures.toml (from where the program takes over the full screen, not the recording's own start, below) through the same emulator.
- Nothing private: the tool refuses to write a capture with a home path, this PC's host or user name, a machine name or a tpm id. Paths from rustc go through its own `--remap-path-prefix` (`remap` in captures.toml), so they read as on any machine. A bench recording is trimmed to where the recorded program switches to the alternate screen buffer before anything is checked or written, so its own startup banner or a bench prompt before that (which once held the bench machine's home directory) never reaches the static screen or, with `live = true`, the shipped recording either.
- **A `live = true` capture also plays live** (BLOCK-7 term-live), not only as a frozen screen: `tools/term_capture.py` writes the trimmed bench recording to `static/term/ID.cast`, the one raw `.cast` a bench recording is allowed to become (otherwise they stay under `~/data/vhrd_site-casts/`, never committed). `vh.term` then also renders a hidden `.term-live` mount and a small inline script: once the figure scrolls into view, on a screen 40rem or wider and without `prefers-reduced-motion`, it loads a self-hosted [asciinema-player](https://docs.asciinema.org/manual/player/) (Apache-2.0, `static/js/asciinema-player.min.js` and `static/css/asciinema-player.css`, its licence at `static/js/asciinema-player.LICENSE.txt`; no CDN) and swaps it in for the static screen, themed with the same tokens (`--term-color-background`/`foreground`/`0`-`15` mapped to `--t-*` in `term.css`, `theme: "vhrd"` so none of the player's own built-in themes apply), looping, autoplaying, with its idle time trimmed. Below 40rem, without JavaScript, under reduced motion or for a crawler, the static screen (above) is all there is, unchanged; `tools/check_pages.py` checks the player's files load only on /software and only where the figure is wide enough, and that the static screen is hidden only once the player has actually mounted. Bump the version by hand (currently 3.18.0): download the npm package's `dist/bundle/asciinema-player.min.js` and `.css`, and `LICENSE`, over the files in `static/`.
- The 16 terminal colours come from the brand's status and category tokens (`.term` in `term.css`, inlined on /software only); a colour the program picks itself (256 or true colour) is kept inline as it wrote it. The panel is dark in both themes, like the terminal it came from.
- `tools/term/units_demo` is the crate behind the exact_units error, the README's first example of code that does not compile.
- `tools/term/ww_evolution` is behind the evolution check: wire_weaver's blinky_api example with its 0.1.0 snapshot, edited once in a compatible way and once in a breaking way, both bumped to 0.1.1.
- `steps` in captures.toml runs several commands on one screen, each on its own prompt line.
- `show` keeps a file the run read (`data/term/ID.src`, the source the exact_units error comes from), and `vh.term` shows it above the output, with the line the compiler points at (`--> FILE:LINE`) marked.

## Board renders

`just renders` (`scripts/render_boards.py`, run with `uv`) rebuilds `static/img/boards/<bnnn>-<slug>/` from the newest revision of each board's KiCad project in `~/git/hw` (read-only, never written to). Per board it writes four views — `hero` (whole board, 3/4 angle, with margin), `detail` (a tighter 3/4 close-up), `top` and `bottom` — as a 2400px-wide PNG source plus AVIF/WebP at 480/640/1280/1920px, with a `manifest.toml` (product, revision, source file, hw git hash, per-view alt text).

- **The PNG sources never ship.** `config.toml` leaves them out of the build (`ignored_static`); the pages use the AVIF/WebP variants. Cards take 480/640/1280, the hero 640/1280/1920.
- **Some boards only.** `just renders b129 b133` renders just the boards named; the others stay as they are.
- **A new width without KiCad.** `just renders --variants` makes only the web variants that are missing, from the PNG sources in the repo, and updates the manifests.
- **Black solder mask, white silkscreen.** The real boards are mostly green; for the site every render forces a black mask with `kicad-cli pcb render --use-board-stackup-colors` against a **temporary copy** of the board's source directory whose stackup colours the script patches to black/white before rendering (`make_mask_black_copy` in the script). The files under `~/git/hw` are never changed.
- **3D model libraries** (generic KiCad parts plus our own `vhrd_mcu_stm_h7` etc.) are machine-local, not committed: the script reads `KICAD6_3DMODEL_DIR`..`KICAD10_3DMODEL_DIR` and `VHRD_3DMODEL_DIR` from the environment, defaulting to one PC's layout (a Syncthing folder plus a local KiCad library checkout). A PC without that library can't run `just renders` itself until it gets one too.
- **Cross-machine workflow**, when you're on a PC without the 3D library (never push/pull/rebase into another PC's checkout — fetch from it instead):
  ```sh
  # on the PC that has the library:
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
| GOST type A | B135 | a personal design-fonts library (Syncthing, user-level, not installed by this repo) | |
| GOST type B | B153, B135 | same | |
| Venus Rising | all four | same | |
| Parsek | B125, B135 | same | |
| Seven Segment | B125 | same | |
| Noto Sans JP Thin | B153 | [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk), OFL-1.1 | installed at `~/.local/share/fonts/noto-sans-jp` |

On the PC with that library, a fontconfig include adds the synced design-fonts folder so `fc-list` sees the five design fonts without copying them anywhere; Noto Sans JP Thin was installed separately from its official OFL source. Licensing for the five design fonts is a call for whoever maintains that library, not this repo: the script only consumes what `fc-list` reports, and refuses to render instead of guessing when a font is missing.

## Performance

The front page is built to show fast on a slow phone. `just perf` (`tools/perf.py`) loads it at 390 px under Lighthouse's mobile throttling (150 ms round trip, 1.6 Mbit/s, CPU four times slower), with an empty cache, and prints the median requests, bytes, first and largest contentful paint and layout shift. The browser check keeps the first view on a phone under 200 KB.

- All CSS is inline in each page (about 11 KB gzipped): nothing blocks the first paint but the HTML.
- A part only some pages have brings its own styles, inlined only there: `extra.styles` in a page's front matter names files in `static/css/` (`intro` on the front page, `stack` on the front page and /open-source, `term` on /software, `about` on /about for the founder's photo). /donguru inlines `donguru.css` from its template. Every other page carries 54 KB of CSS instead of 75 KB. The browser check fails a page that shows such a part without its styles, inlines styles it does not use, or carries more than `SHARED_CSS_KB` of the shared CSS.
- Only the hero render is eager, with `fetchpriority="high"` and a preload; every other image is `loading="lazy"`.
- Three font faces are preloaded, the ones the first screen sets text in, as Core subsets, with `font-display: swap`.
- The local server of the checks gzips text, as a real server would.

### The light blink between pages in Firefox

Desktop Firefox can show a short light flash when moving from one page to another, on a site that is dark throughout. It is Firefox's own tab background, not the site's:

- Firefox keeps pages for back and forward in its parent process (`fission.bfcacheInParent`, on by default). A navigation away from a page that can be kept that way swaps in a new browsing context.
- Until the new page has painted, the window shows the tab panel's background. In a light Firefox theme that is #F9F9FB. In a dark theme the same gap is dark and nobody notices it.
- It is longer when the computer is busy and when the new page takes longer to paint. On an idle machine it is rare. A trivial dark test page flashes too (7 of 24 navigations with Firefox sharing a busy CPU core); vhrd.tech did on 18 of 24 live.
- Chromium keeps the old page until the new one paints and never showed a light frame. Firefox 157 has no cross-document view transitions, so `@view-transition` cannot help there.
- Plain Playwright never shows it: its Firefox turns `fission.bfcacheInParent` off, and headless Firefox has no tab panel. Reproducing it needs a headed Firefox with that pref on, and a screen recording.
- `Cache-Control: no-store` on the HTML removes it (0 of 24), because such a page is never kept for back and forward. Roman chose to keep the back/forward cache instead. The site's own share of the gap is small:
  - With Firefox sharing a busy core, the build without any CSS at all still flashed on about 13 of 24 navigations, against 17 with it. Removing the header's blur, the grid, the view frame or rendering below the fold lazily (`content-visibility`) made no difference beyond the noise (about ±4 of 24 between rounds).
  - The per-page styles above cut the shared CSS by 28 % with no visible change. Measured the same way, 96 navigations each, main flashed on 62 and the per-page styles on 59: no difference beyond the noise. First paint after the response, summed over 13 pages on an idle machine: 661 ms before, 634 ms after.
  - So the blink is Firefox's to fix. A visitor who sees it can use a dark Firefox theme, which makes the gap dark.

Mozilla's bugs on it: [1538414](https://bugzilla.mozilla.org/show_bug.cgi?id=1538414) (white flashes between pages), [1488384](https://bugzilla.mozilla.org/show_bug.cgi?id=1488384) (the tab panel follows the theme's colour scheme), [1712839](https://bugzilla.mozilla.org/show_bug.cgi?id=1712839) (flashing with Fission), [1740499](https://bugzilla.mozilla.org/show_bug.cgi?id=1740499) (visible redraws on page loads with Fission).

## Intro

The front page opens like an old CRT oscilloscope powering up (`templates/partials/intro.html`, its script `templates/partials/intro-script.html` at the end of the body, styles in `static/css/intro.css`, inlined on the front page only):

1. A dark screen: a phosphor dot fades in at the centre and holds.
2. The timebase starts: the dot spreads into a horizontal baseline, past the edges and back, the beam's head sweeping it.
3. The deflection ramps up: the baseline stretches into the screen, overshoots, wobbles and settles with its corners on the view frame's four crosses.
4. A 10 × 8 graticule fades in with the centre cross, minor ticks, the "CH1 1.00V/div" and "M 2.00ms" readouts and the trigger marker.
5. With the first screen ready (hero render loaded or failed, fonts ready) and `extra.intro_trace` on in config.toml (on by default; costs about 0.1 s on the first paint on a slow phone), the beam traces that screen like a vector display, in about 1.3 s, while the graticule dims and the baseline goes out. It draws what is really laid out at this viewport, measured at run time (and again on a resize): the header's edge, the wordmark and header buttons as boxes, the nav, the label and lead as strokes, the headline as stroked words left to right, the buttons, the FIG. 1 frame and its render as boxes, the PCB trace as far as it is drawn, with its vias, and the cards in view. A bright spot rides the stroke being drawn; a fresh stroke is blue-white and settles into the phosphor.
6. The screen fades to the page, which sits exactly under its traces: nothing moves.

On a slow link the screen waits instead: a sine takes the baseline's place with "LOADING" blinking, "SLOW LINK · CLICK TO SKIP" shows after 5 s, "TRIG'D" shows once the first screen is in and the beam traces it, and it waits at most 20 s.

The view frame (`.view-frame` in `base.html`) is on every page: a cross at each corner of the visible screen, on the column's edges, just under the header and 10 px above the bottom. It stays as part of the page's frame.

How it is built:

- The power-on is CSS animations of 2.8 s, the vector pass about 1.3 s, the fade 0.6 s: about 4.8 s in all on a fast link or from the cache.
- The inline script decides between the trace and the wait, draws the vector pass and clears the layer. The pass is one SVG over the viewport (`.scope-draw`): a path per box, edge and underline, animated with `stroke-dashoffset`, and an SVG `<text>` per headline word in the computed font, revealed left to right with a `clip-path` inset. One `requestAnimationFrame` loop runs it and moves the spot. Every stroke carries `data-k`, `data-sel` and `data-i`, so the browser check holds it to its element at 390 and 1440 px and after a resize.
- The page is in the HTML and painted underneath from the start; the intro only covers it. The largest paint is the hero render either way, at the same time. The growth is a transform: no layout shift.
- It plays on a first visit from outside the site and on every reload of the home page. It does not play when the visitor comes home from inside the site (a link such as the wordmark, so the referrer is this site), on back or forward (also from the browser's page cache), or when the URL has a #fragment (a link to a section goes straight there). The head script in `index.html` decides from the navigation's type and the referrer.
- A click, key, wheel, touch or scroll skips it. The footer's "Replay intro" button plays it again as a demo of the slow path, even with everything cached: the power-on, LOADING, the slow-link line from 5.5 s, TRIG'D at 9 s and the page at about 10 s. The page comes back scrolled to the top (it jumps there under the dark screen), and the replay ignores skips for its first 0.4 s, so the click, tap or key that started it, or a scroll still running out, does not end it at once.
- Under reduced motion and without JavaScript there is no intro and no replay button. A CSS failsafe hides the layer after 21 s (the 20 s cap plus the fade) whatever the script does.
- The phosphor is real P11 (ZnS:Ag,Cl, peak about 460 nm, CIE 1931 about x 0.14, y 0.07; source: the CRT phosphor table at curtpalme.com, "CRT Phosphors.pdf"), in sRGB #0029ff. The token `--phosphor-p11` in `site.css` is "P11 softened", #2f5bff, toward how a bright beam reads on camera. The glow, the persistence, the sine and the graticule's tint are in it. The beam's head is a hot blue-white core (`--beam`) that fades into the phosphor at its edges. The phosphor alone is 3.7:1 on #0f0f10, so the readouts and the status are blue-white (`--trace-text`, 7.5:1), and TRIG'D is in `--beam` (13.3:1). The image placeholders use the same colours.

## Image placeholders

A picture still on its way shows as a small oscilloscope screen in its own box, the same screen as the intro: dark glass, a faint graticule and the ringing step sweeping across. The picture fades in over it when it arrives.

- `site.js` marks the frames of pictures not yet loaded (`.img-wait`, then `.img-in` while the picture fades in). Without the script nothing changes.
- The eager hero is left out: hidden while it loads, its largest paint would wait for the fade. The intro covers it on a first visit.
- The screen is two pseudo-elements on `.fig-frame`: the glass and graticule as gradients, the trace as a mask over the token colour. No request, one keyframe.
- The box has the image's width and height from the start, so nothing shifts.
- Under reduced motion the screen stays, without the sweep, and the picture appears without a fade.

## Link previews

Every page has `author`, `og:title`, `og:description`, `og:type`, `og:url`, `og:site_name`, `og:locale`,
`og:image`, `og:image:width`, `og:image:height`, `og:image:alt` and `twitter:card` / `twitter:image` in
`templates/base.html`, so LinkedIn, Facebook, X and messengers show a made-for-it card instead of cropping
whatever render they pick out of the page themselves. There is no byline per page (no blog, no articles), so
`author` is the same for every page and there is no `article:author`.

- The image is `config.toml`'s `extra.og_image` (the Donguru hero render, `static/img/og/default.png`) unless
  the page's own front matter sets `extra.og_image` (and `extra.og_image_alt`): `/pinsmith`, `/can`, `/software`
  and `/work` each show their own board.
- `just og` (`tools/og_images.py`, uv, Pillow and cairosvg) writes `static/img/og/<name>.png`: a board's hero
  render, cropped to its own content, on a **transparent** background inside a 1200×627 canvas (1.91:1, what
  LinkedIn, Facebook and X use for a large card). A solid dark background read as a heavy black block on
  LinkedIn's white card; transparency lets each platform show it on its own background instead (LinkedIn and X
  honour it; Facebook, Messenger and some others fill it with their own card colour, usually white or a light
  grey).
  - The board is scaled to fit well inside the middle 580×480 of the canvas, with margin either side of the
    627×627 square crop LinkedIn and messengers make from a 1.91:1 card, so the whole board stays in view there
    too; the script refuses to write a file where it wouldn't.
  - A soft white halo (blurred, low opacity) sits behind the board: it blends away on a white or light card, and
    keeps a dark board's edge from vanishing into a black one.
  - Four red corner marks (brand red, like `.fig-frame`'s datasheet corners) and a small red VHRD.TECH wordmark
    (bottom right, from `static/img/wordmark.svg`, recoloured to the one red so it reads on white and on black
    alike) frame the board. The frame sits inside the square crop's edges too, so it survives a square-crop
    platform as well as the full card.
  - The composed image is colour-quantized (256 colours, no dither) before saving: a CAD render has few flat
    colours and a smooth glow needs few alpha steps, so this loses nothing visible and keeps a lossless,
    transparency-capable PNG well under the 400 KB budget (a losslessly-encoded render would otherwise run past
    a megabyte).
  - Run it again after a change to a board's hero render, the wordmark or the script itself; `just test` does
    not rebuild it.
- `tools/check_pages.py` (`just test`) checks every page: `og:image` is an absolute URL to a real 1200×627 PNG
  or JPEG that matches its own `og:image:width`/`height`, `og:image:alt` is not empty, and `twitter:image` is
  the same URL.
- `just og --check` also writes the default image composited onto the backgrounds a platform that doesn't
  honour transparency might fill it with — white (LinkedIn), X's two dark themes and Facebook's grey — at both
  the 1.91:1 card and the 1:1 square crop, into `target/shots/og2-*.png`, for a by-eye look before trusting a
  transparent image on a platform this repo can't open an account on to test directly.
- **LinkedIn caches a link's preview.** After a deploy, open the new URL in its [Post
  Inspector](https://www.linkedin.com/post-inspector/) to refresh it there; other platforms refetch on their own
  schedule.

## Commands

```sh
just install          # Zola 0.23.6 into ~/.local/bin
just serve [PORT]     # live reload on this PC's Tailscale address ("Serve on the tailnet" below)
just test             # the notify service's tests, zola check, build, browser check of every page, brand files match vhrd_brand
just lint             # git diff --check, rustfmt and clippy, the tools parse
just brand            # pull tokens.css and vhrd.css from ~/git/vhrd_brand ($VHRD_BRAND)
just wordmark         # redraw the wordmark and favicon from vhrd_brand's Audiowide
just check-browser    # the browser check alone
just perf             # first screen on a slow phone: requests, KB, FCP, LCP (median of 3 runs)
just fonts            # Core subsets of the IBM Plex Latin1 faces, and fonts.css
just live             # the live site for https://vhrd.tech/ into target/live (indexable, nothing of WordPress), checked
just deploy           # start the Deploy workflow on GitHub (site and notify service); it waits for approval ("Deploy" below)
just deploy-notify    # fallback without GitHub: tpm ship to the web-notify node; prod, needs sign-off first ("Notify service" below)
just rollback-notify  # fallback: the notify service's previous release (the activator rolls back by itself)
just notify ARGS      # the signups on the server, as vhrd-notify: count, list, export, delete ADDRESS
just stats [DAY]      # the visitor stats report from the server over ssh, opened here ("Visitor stats" below)
just check-live       # the deployed site against target/live: pages 200, the footer stamp, the old paths' 301s, the 404
just check-draw [URL] # the traces (draw with the scroll, both ways) and first clicks: the local build by default, or a deployed site
just preview TOKEN    # noindex build for https://shadow.vhrd.tech/TOKEN/, uploaded with tpm share ("Preview" below)
just check-preview URL  # the browser check against a deployed preview, screenshots into target/shots
just captures         # record the terminal captures on /software again (data/term/captures.toml)
just renders          # rebuild static/img/boards/ from ~/git/hw (KiCad); needs a machine-local 3D model
                       # library and the silkscreen fonts in fc-list ("Board renders" above)
just renders --variants  # only the missing web widths, from the PNG sources (no KiCad)
```

`just test` needs `chromium`, `uv`, Rust and `cargo nextest`. `just install` fetches Playwright's Firefox too; the browser check runs both.

`just test` accepts and ignores `--changed`: the site is one unit, and a full test takes about a minute. The traces' scroll-linked draw and the first clicks, on every page in two browsers at five screen sizes, are slow (about 5 min) and not part of it: run `just check-draw` after changing traces, scroll or intro code, and `just check-draw https://vhrd.tech` after a deploy. The CI deploy workflow does not run it.

### Serve on the tailnet

`just serve [PORT]` runs `zola serve` on this PC's Tailscale address, so any session or person can open the working tree live, with live reload, from another PC or a phone, without landing, deploying or taking screenshots:

1. `tools/serve.py` (run with `uv`) reads this PC's Tailscale IPv4 (`tailscale ip -4`) and MagicDNS name (`tailscale status --json` `Self.DNSName`), picks a free port (the port given, or the first free one from 1111 up, so several sessions can serve at once on one PC), and execs `zola serve --interface <tailscale IP> --port <port> --base-url <MagicDNS name or IP>`.
2. It never binds `0.0.0.0`: these PCs sit on public wifi too. When Tailscale is down it falls back to `127.0.0.1` with a clear message, reachable only on that PC.
3. It prints the URL to open: `http://<MagicDNS name or IP>:<port>/`. zola's live reload runs its websocket on that same port, so nothing beyond the one port needs to be reachable.
4. No firewall change is needed on these PCs: Tailscale traffic is already let through.

A session starts it with `run_in_background`, reads the printed URL from the task output for its parent, and leaves it running past `tpm work ready`, so the preview link still works afterwards — `just serve` never ends on its own. `tpm work done` stops it when the session folder closes.

### Preview

A preview is a noindex build behind a share link, `https://shadow.vhrd.tech/<token>/`, with a fresh token for every preview:

1. Get a token from the share tool (`mx3 share token`).
2. `just preview TOKEN` builds with `VHRD_NOINDEX=1` for the base path `/<token>/` into `target/preview/<token>`. Every page gets `<meta name="robots" content="noindex, nofollow">`, and robots.txt disallows everything.
3. Upload the folder as it is with the share tool; the recipe prints the command: `tpm share target/preview/<token> --token <token> -e 3m`.
4. `just check-preview https://shadow.vhrd.tech/<token>/` runs the browser check against it.

A build only works under the link it was built for, because every URL carries the token. The link is public to anyone who has it: nothing private goes into the site. The robots.txt sits in a subdirectory, where crawlers don't read it; the meta tag on each page is what keeps the preview out of search results.

## Notify service

The "Get notified" forms on /donguru and the front page (`vh.notify`) post to `vhrd_notify`, a small Rust service on the web server behind nginx at `/api/notify`. It is the site's only server-side part. Nothing goes on the list until the address's owner presses the button in our confirmation mail (double opt-in).

- **Code:** a Cargo workspace in `server/`: `vhrd_notify` (library) and `vhrd_notify_cli` (the `vhrd_notify` binary). axum without its default features; TLS only for mail out, through rustls with graviola's crypto (Rust and assembly, no C); no C library anywhere. graviola needs aes, ssse3, avx, avx2, adx, bmi2 and pclmulqdq on x86_64: without them the service refuses to start. If the server ever lacks one, the fallback is rustls's `ring` provider, which builds C (say so here then).
- **The form:** `email`, `list` (only `donguru`), `consent` (the version of the consent line shown, `extra.notify_consent`), `from` (the page) and `leave_empty`, a honeypot off screen (a name no browser or password manager fills in). At most 1 KB.
- **The address:** at most 254 characters and exactly one @. Before it, ASCII letters, digits and `. _ + -` (at most 64, no dot at either end, no two in a row); after it, letters, digits, dots and dashes, at least two labels, the last letters only. It is kept in lower case. Anything else is refused, never repaired.
- **Answers:** the page's script (`Accept: application/json`) gets 200 (accepted), 400, 429 or 503 with a fixed text. A form without JavaScript gets a 303 back to its page's `#notify-ok`, `#notify-bad`, `#notify-wait` or `#notify-err`, which CSS shows with `:target`. A request that is not the form (another content type, a body over the limit, an unknown or repeated field, an Origin of another site) gets a plain 400. Nothing the visitor sent is ever in an answer, and no cookie is set.
- **One answer for every address:** an accepted signup is one line appended to the intake (`signups.tsv.intake`) and fsynced, nothing more. Whether the address is new, waiting or confirmed is decided later by the worker and never shows in the answer or its timing.
- **The worker** (`outbox.rs`, beside the endpoint, woken by each signup and every minute) folds the intake into the records (`list.rs`). A new address becomes a pending record with its confirmation mail queued. A pending one gets that mail again at most once in `resend_hours` (24) and `max_confirm_mails` (3) times in all; a confirmed one gets nothing. Pending records are deleted after `pending_days` (7). New signups are held past `max_pending` (5,000) or `max_signups` (50,000).
- **Store:** `/home/vhrd-notify/vhrd_notify/signups.tsv` on the server (the service's own user, vhrd-notify), outside the web root, mode 0600, with a header line `# vhrd_notify state 2`. One record per address and list: random id and nonce, list, address, pending or confirmed, signup time, consent version, confirmation time, mails sent, last mail, the mail in the outbox, its tries and next try. It is only ever rewritten whole (a temporary file, fsynced, renamed, the folder fsynced). A file without the header is the first release's format: its lines are read as pending records with a mail queued. A lock file beside it keeps the service and the CLI apart.
- **Mail out:** SMTP submission to mail.vhrd.tech on port 465, TLS from the first byte, as donguru@vhrd.tech, with the login in `[mail]` and its password in `mail.password_file` (0600). Confirmation mails at most 60 an hour and 300 a day in all, list mails 20 a minute; past that they wait. MAIL, RCPT and DATA go one by one: only a 550, 551 or 553 to RCPT deletes a pending record; a 4xx is retried after `retry_secs`; another 5xx gives that mail up; a mail server that can't be reached or refuses the login costs no mail a try (the worker waits, up to 30 min). Plain text in 7bit, links on one line. A mail goes out at least once: a crash just after sending sends it again. Without `[mail]` nothing is sent (locally, in the tests).
- **Links never act on GET** (`links.rs`), because mail scanners open links. The confirm link is `/notify/confirm/#TOKEN` and the remove link `/notify/remove/#TOKEN`: pages with a button, the token after `#` (a browser never sends it, so it is in no log). The button POSTs to `/api/notify/confirm` or `/api/notify/remove`. List mails also carry RFC 8058's `List-Unsubscribe: <https://vhrd.tech/api/notify/unsubscribe?t=TOKEN>, <mailto:...>` and `List-Unsubscribe-Post`: a POST there removes the address, a GET only sends the browser to the remove page. Removing deletes the record; nothing of it is kept. The buttons have their own rate limit (20 a client, 100 a network an hour), the one-click a high one (2,000), since many people's come from one mail provider.
- **Tokens** (`token.rs`): one purpose byte, the record's id and 16 bytes of HMAC-SHA256 over the id and the record's nonce, base64url, 44 characters. The key is 32 random bytes in `token_key`, made by the service on its first start (0600) and never shipped. Nothing in the store opens a link.
- **Secrets** stay outside the folder releases go into and out of the repo, the upload, the log and every message: `/home/vhrd-notify/.config/vhrd-notify/token-key` and `smtp-password`. The service refuses to start (exit 78) when either is readable by others.
- **Rate limit:** five signups per client an hour (an IPv4 address, an IPv6 /64) and twenty per network (an IPv4 /24, an IPv6 /48), and forty per network a day, so one network can't use up the day's 300 confirmation mails. It lives in memory only and remembers at most 10,000 of each; when full, the one seen longest ago is forgotten, so a flood of new addresses never locks real visitors out. The client's address comes from nginx's `X-Real-IP`; when that header is missing the log says so once.
- **Log:** counts and SMTP codes only, never an address or a token.
- **Settings:** `deploy/notify.toml`, shipped beside the binary; every field and its default is in `server/vhrd_notify/src/config.rs`. A new consent text gets a new version in `consent_versions` first, then on the site. A broken settings file, a key or password file others can read, or a CPU graviola can't use stops the service with exit code 78, which the unit does not restart.

Managing the list, through `just notify` from a PC that can log in as roman on the server, or on the server with `sudo -u vhrd-notify /home/vhrd-notify/vhrd_notify/vhrd_notify --config /home/vhrd-notify/vhrd_notify/notify.toml ARGS`:

```sh
just notify count                      # confirmed and pending records per list
just notify list [--list donguru]      # every record, pending ones too
just notify export > donguru.csv       # CSV of the confirmed ones: email,list,signed_up,consent,confirmed
just notify delete someone@example.com # a removal request: every record of that address goes
just notify mail-test me@example.com   # one fixed test mail, now, outside the outbox
just notify send --list donguru --name launch-1 --subject "..." --text launch.txt --test me@example.com
just notify send --list donguru --name launch-1 --subject "..." --text launch.txt --yes
```

`send` queues a list mail (the launch) for every confirmed address; the service sends it with the one-click headers. Its text is a file that must hold `{remove}`, the address's remove link; it is kept beside the store as `signups.tsv.mail-NAME`. Without `--yes` it only says how many it would reach, and `--test ADDRESS` queues it for one confirmed address (yours) first. The text file needs to be on the server first. `delete` rewrites the store without that address.

`just notify` runs the CLI as the service's user through sudo. A sudoers rule lets roman do that without a password (`roman ALL=(vhrd-notify) NOPASSWD: /home/vhrd-notify/vhrd_notify/vhrd_notify`): it only reaches down, to a user with fewer rights. A second line keeps sudo from logging those command lines (`Defaults!/home/vhrd-notify/vhrd_notify/vhrd_notify !log_allowed`), since `delete`, `mail-test` and `send --test` carry an address. The files the CLI writes are 0600 whatever the umask.

**Locally:** `just serve` builds the service and starts it beside the site on the next free port, with its own settings and store in `target/notify-dev/`, and tells the site where it is (`VHRD_NOTIFY_API`). It has no `[mail]`, so mails stay in the outbox. The browser check does the same with a temp store and sends the form with and without JavaScript. The Rust tests run the whole double opt-in over real sockets against an SMTP server inside the test (`server/vhrd_notify/tests/optin.rs`). A preview on shadow.vhrd.tech has no service: its form answers with the error message.

### How it is deployed

The Deploy workflow ships the service with the site, in the same run ("Deploy" below). No PC holds a key for it.

The service is built and shipped only when it changed. Job `build-notify` first asks https://vhrd.tech/api/notify which release answers (`x-vhrd-release`). It skips the build and the upload only when that sha is a commit here, an ancestor of the commit being deployed, and nothing changed since outside the site-only paths (`SITE_ONLY` in `tools/notify_plan.py`: content, templates, static, the docs, ...). Any change to the workflow ships it too. Anything unclear ships it: no header, a fetch failure, not an ancestor, a tag or branch named like the sha. The run's summary says which and why. `tools/test_notify_plan.py` (in `just test`) holds those cases in temp git repos, and fails when a file under `server/` reads a site-only path. The input `notify` (Run workflow > "Build and ship the notify service", or `gh workflow run deploy.yml --ref main -f notify=true`) forces it; use it once after a `just deploy-notify` fallback, since that release was not built here.

1. **Build** (no secrets, job `build-notify`): the pinned Rust toolchain (`RUST_TOOLCHAIN` in the workflow) runs the workspace's tests and builds a static musl `vhrd_notify` with `--locked`. The release's version and git sha come from the binary's own `--version`; a dirty tree stops it. The binary, `deploy/notify.toml` and the server-side files root installs by hand (`setup/`: the activator and the three units) are packed with their sha256.
2. **Upload** (deploy job, after the approval): the manifest is written there, with each file's sha256 and a sequence number that grows with every run and re-run. rsync sends the files to `ci-notify@vhrd.tech`, then the manifest on its own. The ci-notify key is forced into `rrsync -wo -no-del -munge /home/ci-notify/incoming`: it can write files into that one folder and do nothing else, no reads, no deletes, no shell.
3. **Activate** (on the server, as vhrd-notify): `vhrd-notify-activate.path` starts `vhrd-notify-activate.service` when the manifest changes. Its program, `vhrd_notify_activate` (crate `server/vhrd_notify_activate`, a static binary root installs as `/usr/local/lib/vhrd-notify/vhrd_notify_activate`), treats the upload as untrusted. It is a crate of its own, apart from the service, so an uploaded release never checks itself. It takes only regular files of ci-notify with one link and below a size limit, never follows a symlink, and reads each file once and checks and writes those same bytes. The manifest must name every file by sha256, carry a version and sha of the expected shape, and a sequence number above the last one tried. The release becomes `~/vhrd_notify/releases/vhrd_notify-VERSION-SHA`; its `--version` must say so. A kept release is never overwritten with other bytes. The previous settings are saved and the activation is recorded as pending in `activate.toml`; then notify.toml is written, the `~/vhrd_notify/vhrd_notify` symlink switches, a line goes to `releases/history` and the service restarts. Besides those, `notify.toml.prev` and its lock file, the activator touches nothing in `~/vhrd_notify`: the service's own files (the signups) are never read.
4. **Check on the server:** the service is active, a probe on 127.0.0.1:8471 answers 400 with the new sha in `x-vhrd-release`, and the socket on that port is the service's own main process (not something that took the port while it restarted). The same again after five seconds, and every second for a minute after that. Otherwise the activator switches the symlink and notify.toml back to the previous release, restarts and checks that one. The same happens for any error, timeout or panic after the switch. An activation cut off by a crash, a kill or a reboot is still marked pending; the activator also runs when the user's units start, checks that release again and goes back if it fails. It keeps five releases, never the current or the previous. Each step is a line in the journal: `journalctl _SYSTEMD_USER_UNIT=vhrd-notify-activate.service`.
5. **Check from outside:** the workflow posts to https://vhrd.tech/api/notify until the answer is 400 from the new sha (at most three minutes), again 80 seconds later (after the activator's watch), and once with a bad address. Anything else fails the run before the site is uploaded: a new consent version or list must reach the service before the site's forms send it.

Every answer of the service names its release in `x-vhrd-release`, the short git sha the site's footer shows too. Since the service ships only when it changed, that sha can be older than the footer's stamp. The probe is a body that is not the form (`probe=1`), so it uses no rate limit.

**What each part can reach.** The ci-notify key writes into its upload folder only. But the manifest's sha256 values come over that same key, so they prove the upload is complete, not who made it: whoever holds the key, or gets a run through the gate, runs code as vhrd-notify on the server. That is why the service has its own user: it reaches the signup list, the token key and the SMTP password, not roman's account, the mesh key or sudo. A release can read those two secrets, so the gate below is also what keeps them; root-owned files handed over by systemd's `LoadCredential` would need a system unit (P2633#5nov-0809f). The activator binary is root's, so an upload can't change how the next upload is checked; the units and `activate.toml` are vhrd-notify's, so a bad release could change those. Signed builds (GitHub artifact attestations, checked on the server) would cut the key out of that, but they need GitHub Enterprise for a private repo. A stolen key is stopped by emptying `/home/ci-notify/.ssh/authorized_keys` (root).

**The gate is GitHub's settings, not the workflow file.** Anyone who can push a branch can run a workflow file of their own on it, without its main and DEPLOY_ACTORS checks. What stops that run from getting the keys is the `production` environment's deployment branch rule (main only) and the ruleset that protects main (tpm P2633 `design/ci-deploy.md`, "GitHub settings"). Both must stay in place. Renaming the workflow resets its run number, so every upload would be "not newer" on the server: the outside check then fails, and `last_seq` in `activate.toml` is reset by hand as vhrd-notify.

**Server layout** (the vhrd-notify user, linger on, user units in `~/.config/systemd/user/`):

```
/home/ci-notify/incoming/          ci-notify:vhrd-notify 2750, what the workflow uploads
/home/vhrd-notify/vhrd_notify/     0700
  vhrd_notify -> releases/vhrd_notify-0.1.0-abc1234
  notify.toml   signups.tsv   activate.toml (the last sequence number tried, an activation in progress)
  releases/     the kept releases and history
/usr/local/lib/vhrd-notify/vhrd_notify_activate   root's
```

**Root, once:** the server brief (tpm P2633 `design/ci-notify-server-brief.md`) creates the users, the folders, the units and the sudo rule, and moves the signups over from roman. The nginx block in `deploy/nginx-notify.conf` goes into the vhrd.tech `server { }`, then `nginx -t` and `systemctl reload nginx`. Only `/api/notify` and its `/confirm`, `/remove` and `/unsubscribe` reach the service, with no access log; the one-click `/unsubscribe` has its own block that writes errors only from crit up, since nginx's error log would hold its token. The rest of `/api/` is a 404. **Before the first release with `[mail]`** (double opt-in): the mail login and its password file (`/home/vhrd-notify/.config/vhrd-notify/smtp-password`, 0600, vhrd-notify's) must be on the server (tpm P2633 `design/notify-optin.md`, "Brief for Roman"). Without it the release stops with exit 78, the activator goes back to the running one, and the Deploy run fails before the site is uploaded. **After a change to the activator or a unit** root installs it again from `/home/ci-notify/incoming/setup/`: copy it into a root-only folder first, check the copy, and install the copy (the upload folder can change between a check and a copy). A unit is compared with `sha256sum deploy/...` at that commit. The activator binary is compared with the sha256 in that Deploy run's summary on GitHub (job build-notify), which the ci-notify key can't change; a change to `vhrd-notify.service` also needs `systemctl --user daemon-reload` as vhrd-notify.

**Without GitHub** (fallback only): `just deploy-notify` runs `tpm ship web-notify vhrd_notify` (`ship.toml`). It builds the static binary on a PC and installs it as the vhrd-notify user in the same layout and history, and the activator carries on from there. It needs a tpm node `web-notify` (`ssh = "vhrd-notify@vhrd.tech"`, `port = 7722`) and a key root adds for the occasion and removes after. tpm ship knows nothing of the activator: stop its path unit first (`systemctl --user stop vhrd-notify-activate.path` as vhrd-notify), and start it again after, so the two never switch at once. Neither exists on purpose. `just rollback-notify` goes back one release the same way.

Check by hand: `curl -si -X POST -H 'Accept: application/json' --data 'email=x' https://vhrd.tech/api/notify` answers 400 "bad request" with `x-vhrd-release`, and `just notify count` works.

## Visitor stats

Interest in the site is judged from the web server's own access log, with GoAccess, not from anything on the pages (SITE-18 site-stats). The server side is set up by a root brief (tpm P2633 `design/stats-server-brief.md`).

- No script, cookie or banner on the site. nginx's log `/var/log/nginx/vhrd.tech.access.log` is the only source.
- A daily timer runs GoAccess as the user `vhrd-stats`, which reads only that log (an ACL, not the adm group).
- Bots and crawlers are left out. Each IP address is shortened (`--anonymize-ip`) before it is counted, and the per-IP panel is off, so no visitor address is in the report or GoAccess's database.
- GoAccess keeps an incremental database of 730 days, so the counts outlive the log's 15 days. Each day also gets a report of its own, for views per page per day.
- Countries come from DB-IP's IP to Country Lite (CC BY 4.0: "IP Geolocation by DB-IP", with a link to db-ip.com wherever its results are shown), updated by a monthly timer.
- The report is never public: `/var/lib/vhrd-stats/report/index.html` (and `day/DATE.html`) is outside every web root and readable by roman only. `just stats [DATE]` fetches it over ssh into `target/stats/` and opens it.
- /privacy and the FAQ (`#tracking`) say what is counted and that the counts are kept 24 months. A change to what is counted or how long changes them in the same commit.

## Deploy

https://vhrd.tech/ and its notify service are deployed from GitHub Actions, by hand: the Deploy workflow (`.github/workflows/deploy.yml`) on main. `just deploy` starts it with `gh`, or Actions > Deploy vhrd.tech > Run workflow. One run ships both, the service first, and the service only when it changed since its live release (`-f notify=true` forces it); how the service's part works is in "Notify service", "How it is deployed".

1. **Build** (no secrets, two jobs): the notify service as a static binary (job `build-notify`), and the site (job `build`). Zola at the pinned version, checked by sha256, builds the live site as `just live` does. `tools/check_live.py built` stops it on a file type the site doesn't ship (PNG sources, manifests, PHP), a symlink, a WordPress path (wp-*, /cart/, /product/, ...), a redirect in `deploy/redirects.map` that leads nowhere or hides a page, a noindex build or a wrong footer stamp.
2. **Approval**: the deploy job runs in the `production` environment. It waits for a required reviewer where the GitHub plan has them, and its first step refuses anyone not listed in the repository variable `DEPLOY_ACTORS`.
3. **Upload**: only while the run's commit is still the head of main, so a re-run of an old run cannot roll the site back. Rollback is a revert commit. The notify release goes first, as `ci-notify` with the environment secret `NOTIFY_SSH_KEY`, and the run waits until https://vhrd.tech/api/notify answers from it; a release the server refuses or rolls back stops the run here. When the service was not shipped, the live release the build found must still answer, or the run stops here too. Then the site: rsync over SSH to `ci-site@vhrd.tech` on port 7722, with the build's sha256 checked first. The key is the environment secret `DEPLOY_SSH_KEY`, and the host key is the one in `.github/deploy/known_hosts`. New files land beside the old ones and are renamed into place at the end, and removed pages go after that.
4. **Check**: the front page shows the new stamp, a second page, a stylesheet and a script answer 200, one old WordPress path per redirect rule answers its 301 and a missing path gets the site's 404 page (`tools/check_live.py site`). `just check-live` adds every page of the sitemap, every path in `deploy/old-urls.txt` and every link in `deploy/golden-links.txt`.
   Add anything printed, mailed or posted to `deploy/golden-links.txt`: a build that would break such a link stops before it is uploaded.

On the server, the `ci-site` user's key is forced into `rrsync -wo -munge /usr/share/nginx/vhrd.tech-site`. It can write into that folder and nothing else: no shell, no reads, no paths outside it, and no working symlinks. nginx serves that folder and nothing else: WordPress is gone (4 Nov 2026). The old WordPress paths redirect with `deploy/redirects.map`, which the server has as `/etc/nginx/vhrd.tech-redirects.map`; a change to the map is copied there by hand, and the deploy's live check shows when it is missing. The server block needs:

```nginx
# in http { }
include /etc/nginx/vhrd.tech-redirects.map;
# in the vhrd.tech server { }
absolute_redirect off;
if ($vhrd_redirect) { return 301 $vhrd_redirect; }
error_page 404 /404.html;
location / { try_files $uri $uri/ =404; }
```

- **Roll back**: a revert commit on main and a new run, or put the previous build back into the folder on the server. The notify service rolls back by itself when its new release fails the check.
- **A new host key** is a reviewed commit to `.github/deploy/known_hosts`, after its fingerprint is checked on the server.
- **The workflow** passes actionlint and zizmor (`just lint`). Actions are pinned to commit SHAs, and a version bump updates the SHA and its comment together.

## Conventions

- **Colours only through tokens** (`var(--accent)`, `var(--signal-usb)`), never hex values in templates or `site.css`. The brand red is used sparingly: one word of the hero headline, the main button, the wordmark, the MCU in diagrams, figure corner marks and the Highlights group on /open-source. Headlines are in the text colour. Power is orange, never red.
- **Dark first, light equal.** Every change is checked in both themes. Dark is the default whatever the system prefers (`<html data-theme="dark">`); light only when the visitor picks it with the toggle, stored in localStorage and applied by the head script before the first paint. Back to dark clears it.
- **Almost no JavaScript, no framework.** Animation is CSS, off under `prefers-reduced-motion`. The traces draw and undraw with the scroll: a few lines of inline script at the end of `base.html` set each one's draw progress `--p` from its place on screen, the last ones completing at the page's end (scroll-driven CSS stalled on tall screens and does not exist in Firefox); without JavaScript they are simply drawn. The page must work without `site.js`. The front page's intro has a small inline script; without it the intro never shows.
- **Links through `get_url`**, so the preview under a sub-path works. A link to a page passes `trailing_slash=true` (`get_url(path="/work/", trailing_slash=true)`): without it Zola drops the slash and every click costs a redirect. Internal Markdown links use `@/page.md`. The browser check fails on an internal link without the slash, on one that does not answer 200, and on a page no link reaches.
- **The name is VHRD; the address is vhrd.tech.** VHRD in titles, copy, product names and the footer; vhrd.tech always lowercase, for URLs and mail; VHRD.TECH AS, the legal name, only in the copyright line (`extra.legal`) and on /privacy, where it names who keeps the data. Never "Vhrd.tech AS", "VHRD Tech", "VHRD.tech" or "Vhrd.Tech". The wordmark is drawn, not text.
- **Brand words** come from ~/git/tpm/area/marketing/brand.md. The one line (hero lead, meta description): "Instruments for embedded development, and the open-source software behind them." VHRD builds instruments, not dev boards to ship inside products, for everyone who works where code meets hardware (hardware, firmware and software engineers), not only hardware engineers. "From Norway" stays out of the hero and the meta; Asker, Norway is in the footer and on /about.
- **Draft copy is marked** (`<span class="v-badge">draft</span>` or `extra.stub = true`) until Marketing and PM have read it.
- **The signup list is personal data.** The service sets no cookie, echoes nothing a visitor sent, keeps the rate limit in memory only and writes signups only to its store on the server. Addresses never go into the repo, a log line, a test fixture (use example.com) or a message; `just notify` reads them on the server. A new use of the list, a new field or a longer retention needs a new consent version and an updated /privacy first.
- **Nothing private on the site or the preview.** A share link is public to anyone who has it. No employer work in the lab pages.
- **Write for reading:** short complete sentences, one fact per list item, open with what it is about.
- Planning and review notes don't belong in this repo. They live in the tpm project folder (P2633 `design/`).

## Checks before ready

`just test` and `just lint`. For a visible change, also look at screenshots at 390 and 1440 px in both themes (`just check-browser` covers console, overflow, keyboard and the toggle). The checklist is the UX/UI web checklist: phone, tablet and desktop widths, keyboard, contrast in both themes, a clean console, reduced motion.

## Commits

Short imperative subject, one topic per commit, FEATURES.md and CHANGELOG.md in the same commit.
