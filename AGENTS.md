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
- `tools/wordmark.py` draws the wordmark and favicon outlines. `tools/check_pages.py` is the browser check, `tools/perf.py` measures the first screen on a slow phone, `tools/fonts.py` cuts the Core font subsets and the small Greek faces (Ω, μ) from vhrd_brand's full fonts.
- `server/`: the Cargo workspace (`Cargo.toml` at the root) of the notify service: `vhrd_notify` (library: `email.rs` the address check, `store.rs` the signups file, `limit.rs` the rate limit, `server.rs` the endpoint, `config.rs` the settings) and `vhrd_notify_cli` (the `vhrd_notify` binary: serve, list, count, export, delete). `deploy/notify.toml` is its settings on the server, `deploy/vhrd-notify.service` its user unit, `deploy/nginx-notify.conf` the nginx block, `ship.toml` what `tpm ship` ships. Dependencies without default features and with no C library (no SQLite: the store is a plain file at this size).
- `content/privacy.md`: the privacy note the forms link to. Any change to what the site or the service keeps changes it in the same commit.
- `.github/workflows/deploy.yml`: the only way the site reaches vhrd.tech ("Deploy" below); `.github/deploy/known_hosts` pins the server's host key. `tools/check_live.py` checks a live build before upload and the site after it.
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

- `data/term/captures.toml` lists each one: the command as typed, the checkout it runs in, the terminal's width.
- The command runs once in a pseudo-terminal, and a terminal emulator (pyte) keeps its screen. The screen is written to `data/term/ID.html` as spans; the command, the version (its `--version`), the commit it ran on and the date go to `data/term/ID.toml`.
- `vh.term` shows a capture as a figure: the command on a prompt line, the screen, and a caption with the version, the source and the date. Nothing runs when the site is built, and the page needs no script.
- A full-screen program that needs hardware (`cnt tui` on a board through a probe) is recorded on the bench with asciinema; `--cast ID=FILE` replays the recording to the second given in captures.toml through the same emulator.
- Nothing private: the tool refuses to write a capture with a home path, this PC's host or user name, a machine name or a tpm id. Paths from rustc go through its own `--remap-path-prefix` (`remap` in captures.toml), so they read as on any machine.
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
just deploy           # start the Deploy workflow on GitHub; it waits for approval ("Deploy" below)
just deploy-notify    # ship the notify service to the web server (tpm ship); prod, needs sign-off first ("Notify service" below)
just rollback-notify  # the notify service's previous release
just notify ARGS      # the signups on the server: count, list, export, delete ADDRESS
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

The "Get notified" forms on /donguru and the front page (`vh.notify`) post to `vhrd_notify`, a small Rust service on the web server behind nginx at `/api/notify`. It is the site's only server-side part.

- **Code:** a Cargo workspace in `server/`: `vhrd_notify` (library: the address check, the store, the rate limit, the HTTP endpoint, the settings) and `vhrd_notify_cli` (the `vhrd_notify` binary). axum without its default features, no TLS (nginx terminates it), no C library.
- **The form:** `email`, `list` (only `donguru`), `consent` (the version of the consent line shown, `extra.notify_consent`), `from` (the page) and `leave_empty`, a honeypot off screen (a name no browser or password manager fills in). At most 1 KB.
- **The address:** at most 254 characters and exactly one @. Before it, ASCII letters, digits and `. _ + -` (at most 64, no dot at either end, no two in a row); after it, letters, digits, dots and dashes, at least two labels, the last letters only. It is kept in lower case. Anything else is refused, never repaired.
- **Answers:** the page's script (`Accept: application/json`) gets 200 (signed up, or already on the list), 400, 429 or 503 with a fixed text. A form without JavaScript gets a 303 back to its page's `#notify-ok`, `#notify-bad`, `#notify-wait` or `#notify-err`, which CSS shows with `:target`. A request that is not the form (another content type, a body over the limit, an unknown or repeated field, an Origin of another site) gets a plain 400. Nothing the visitor sent is ever in an answer, and no cookie is set.
- **Rate limit:** five signups per client an hour (an IPv4 address, an IPv6 /64) and twenty per network (an IPv4 /24, an IPv6 /48). It lives in memory only and remembers at most 10,000 of each; when full, the one seen longest ago is forgotten, so a flood of new addresses never locks real visitors out. The client's address comes from nginx's `X-Real-IP`; when that header is missing the log says so once.
- **Store:** `~/vhrd_notify/signups.tsv` on the server, outside the web root, mode 0600. One line per signup: UTC time, list, address, consent version, tab-separated. Each signup is appended and fsynced before the visitor hears it worked; the same address on the same list is kept out, with the same answer and the same fsync, so neither the answer nor its timing tells whether an address is on the list. A last line without its newline (a full disk, a crash mid-write) is left out of reads and cut off by the next signup. The log warns when the store passes 80 % of `max_signups` (50,000). A lock file beside it keeps the service and the CLI apart.
- **Settings:** `deploy/notify.toml`, shipped beside the binary; every field and its default is in `server/vhrd_notify/src/config.rs`. A new consent text gets a new version in `consent_versions` first, then on the site. A broken settings file stops the service with exit code 78, which the unit does not restart.

Managing the list, on the server or through `just notify` from a PC with the server's ssh key:

```sh
just notify count                      # signups per list
just notify list [--list donguru]      # every line
just notify export > donguru.csv       # CSV: email,list,time,consent, for the launch mail
just notify delete someone@example.com # a removal request: every line of that address goes
```

`delete` rewrites the file without that address (a temporary file, fsynced, renamed over the old one). Run the CLI as the service's user (`just notify` does): the files it writes are 0600 whatever the umask. Double opt-in (a confirmation mail before an address counts) is a later option, not built.

**Locally:** `just serve` builds the service and starts it beside the site on the next free port, with its own settings and store in `target/notify-dev/`, and tells the site where it is (`VHRD_NOTIFY_API`). The browser check does the same with a temp store and sends the form with and without JavaScript. A preview on shadow.vhrd.tech has no service: its form answers with the error message.

**Deploy** (prod; needs sign-off first; nothing here deploys it by itself):

1. `just deploy-notify` (`tpm ship web-server vhrd_notify`, `ship.toml`): builds a static musl binary here, uploads it to `~/vhrd_notify/releases/` with `deploy/notify.toml` and the user unit `deploy/vhrd-notify.service`, switches the symlink, restarts and checks `--version`. It runs as the server's login user (linger is on for the mesh node already), listens on localhost only. `just rollback-notify` goes back one release.
2. Root, once: the block in `deploy/nginx-notify.conf` goes into the vhrd.tech `server { }` in `/etc/nginx/conf.d/vhrd.tech.conf`, then `nginx -t` and `systemctl reload nginx`. Only `POST /api/notify` reaches the service; the rest of `/api/` is a 404.
3. Then the site itself (`just deploy`), whose forms post to `/api/notify`.

Check after: `curl -si -X POST -H 'Accept: application/json' --data 'email=x' https://vhrd.tech/api/notify` answers 400 "bad request", and `just notify count` works.

## Deploy

https://vhrd.tech/ is deployed from GitHub Actions, by hand: the Deploy workflow (`.github/workflows/deploy.yml`) on main. `just deploy` starts it with `gh`, or Actions > Deploy vhrd.tech > Run workflow.

1. **Build** (no secrets): Zola at the pinned version, checked by sha256, builds the live site as `just live` does. `tools/check_live.py built` stops it on a file type the site doesn't ship (PNG sources, manifests, PHP), a symlink, a WordPress path (wp-*, /cart/, /product/, ...), a redirect in `deploy/redirects.map` that leads nowhere or hides a page, a noindex build or a wrong footer stamp.
2. **Approval**: the deploy job runs in the `production` environment. It waits for a required reviewer where the GitHub plan has them, and its first step refuses anyone not listed in the repository variable `DEPLOY_ACTORS`.
3. **Upload**: only while the run's commit is still the head of main, so a re-run of an old run cannot roll the site back. Rollback is a revert commit. rsync over SSH to `ci-site@vhrd.tech`, with the build's sha256 checked first. The key is the environment secret `DEPLOY_SSH_KEY`, and the host key is the one in `.github/deploy/known_hosts`. New files land beside the old ones and are renamed into place at the end, and removed pages go after that.
4. **Check**: the front page shows the new stamp, a second page, a stylesheet and a script answer 200, one old WordPress path per redirect rule answers its 301 and a missing path gets the site's 404 page (`tools/check_live.py site`). `just check-live` adds every page of the sitemap, every path in `deploy/old-urls.txt` and every link in `deploy/golden-links.txt`.
   Add anything printed, mailed or posted to `deploy/golden-links.txt`: a build that would break such a link stops before it is uploaded.

On the server, the `ci-site` user's key is forced into `rrsync -wo -munge /usr/share/nginx/vhrd.tech-site`. It can write into that folder and nothing else: no shell, no reads, no paths outside it, and no working symlinks. nginx serves that folder and nothing else: WordPress is gone. The old WordPress paths redirect with `deploy/redirects.map`, which the server has as `/etc/nginx/vhrd.tech-redirects.map`; a change to the map is copied there by hand, and the deploy's live check shows when it is missing. The server block needs:

```nginx
# in http { }
include /etc/nginx/vhrd.tech-redirects.map;
# in the vhrd.tech server { }
absolute_redirect off;
if ($vhrd_redirect) { return 301 $vhrd_redirect; }
error_page 404 /404.html;
location / { try_files $uri $uri/ =404; }
```

- **Roll back**: a revert commit on main and a new run, or put the previous build back into the folder on the server.
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
