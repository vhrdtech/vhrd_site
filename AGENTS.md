# Working on vhrd_site

vhrd.tech, a static site built with Zola: Markdown in `content/`, Tera templates in `templates/`, hand-written CSS. It is the home for Donguru's launch, rePort, the CAN line and the software, so every page answers: what it is, why it is good, what to do next.

## Zola version

**Zola 0.23.6**, pinned in `justfile` (`zola_version`). `just install` puts that release binary in `~/.local/bin`, and `just test` refuses any other version. Zola 0.23 uses Tera 2: there are no shortcodes and no macros, only components (`{% component %}`, called as `{{ <vh.card ... /> }}`). Undefined variables are errors, tests take keyword arguments (`is starting_with(pat=...)`) and arrays are indexed with `[0]`. Highlighting is configured under `[markdown.highlighting]`. Bump the pin on purpose, with a CHANGELOG line.

## FEATURES.md and CHANGELOG.md

[FEATURES.md](FEATURES.md) tracks what exists and what is planned, with stable IDs (`SITE-1`, `LOOK-3`, `BLOCK-2`, `PREVIEW-1`). Name them with their slug when talking to the user (`LOOK-3 grid-and-traces`). Get a new id with `tpm work claim AREA`. Update FEATURES.md in the same commit as the change.

[CHANGELOG.md](CHANGELOG.md) gets an entry for every visible change under `## [Unreleased]`. A branch never writes a version heading: `tpm land` turns `[Unreleased]` into `## [x.y.z] - date` and tags it. Every version gets its own section. Questions like "what's new" are answered from it, newest first, with FEATURES.md for current status.

## Layout

- `config.toml`: site settings; `[extra]` holds the company line, contact mail, header links and the notify button.
- `content/`: one Markdown file per page (`donguru.md` is `/donguru/`), `blog/` is a section. Stubs carry `extra.stub = true`.
- `templates/base.html`: the page frame. `partials/header.html`, `partials/footer.html` (build stamp from `VHRD_GIT` and `VHRD_BUILT`, which the justfile sets) and `partials/wordmark.html` (generated).
- `templates/components.html`: the `vh.*` components, usable in templates and Markdown (README "Components").
- `templates/index.html`: the landing page; `partials/donguru-diagram.html` is its block diagram and `partials/intro.html` its oscilloscope intro (README "Intro"). `page.html` is a plain page, `section.html` is the blog list, and there are `404.html` and `robots.txt`.
- `static/css/brand/`: `tokens.css` and `vhrd.css` from vhrd_brand (`just brand`). Never edit these here; change vhrd_brand and pull.
- `static/css/site.css`: the site's own layer. `base.html` inlines all the CSS (fonts.css, the brand files and site.css) into each page with `load_data`, so there is no render-blocking request. `static/js/site.js`: theme toggle, tabs and the image placeholders' marking, nothing else.
- `static/fonts/`: IBM Plex woff2 subsets and `fonts.css`. `static/img/boards/` holds board renders (`just renders`, README "Board renders") and `static/img/lab/` lab photos.
- `tools/wordmark.py` draws the wordmark and favicon outlines. `tools/check_pages.py` is the browser check, `tools/perf.py` measures the first screen on a slow phone, `tools/fonts.py` cuts the Core font subsets.
- `data/stack.toml`: the open-source crates in their /open-source order (layer, logos per theme, code sample, which are on crates.io); `front = true` puts one on the front page too. `partials/crate-stack.html` draws them for both pages, `templates/open-source.html` is the /open-source page.

## Commands

```sh
just install          # Zola 0.23.6 into ~/.local/bin
just serve            # live reload on :1111
just test             # zola check, build, browser check of every page, brand files match vhrd_brand
just lint             # git diff --check, the tools parse
just brand            # pull tokens.css and vhrd.css from ~/git/vhrd_brand ($VHRD_BRAND)
just wordmark         # redraw the wordmark and favicon from vhrd_brand's Audiowide
just check-browser    # the browser check alone
just perf             # first screen on a slow phone: requests, KB, FCP, LCP (median of 3 runs)
just fonts            # Core subsets of the IBM Plex Latin1 faces, and fonts.css
just preview TOKEN    # noindex build for https://shadow.vhrd.tech/TOKEN/, uploaded with tpm share (README "Preview")
just check-preview URL  # the browser check against a deployed preview, screenshots into target/shots
just renders          # rebuild static/img/boards/ from ~/git/hw (KiCad); needs a machine-local 3D model
                       # library and the silkscreen fonts in fc-list (README "Board renders")
just renders --variants  # only the missing web widths, from the PNG sources (no KiCad)
```

`just test` accepts and ignores `--changed`: the site is one unit, and a full test takes about a minute.

## Conventions

- **Colours only through tokens** (`var(--accent)`, `var(--signal-usb)`), never hex values in templates or `site.css`. The brand red is used sparingly: one word of the hero headline, the main button, the wordmark, the MCU in diagrams and figure corner marks. Headlines are in the text colour. Power is orange, never red.
- **Dark first, light equal.** Every change is checked in both themes. The theme follows `prefers-color-scheme`; the toggle stores an override in localStorage, and choosing the system's own theme clears it.
- **Almost no JavaScript, no framework.** Animation is CSS (scroll-driven for the traces), off under `prefers-reduced-motion`. The page must work without `site.js`. The front page's intro has a small inline script; without it the intro never shows.
- **Links through `get_url`**, so the preview under a sub-path works. Internal Markdown links use `@/page.md`.
- **The name is VHRD; the address is vhrd.tech.** VHRD in titles, copy, product names and the footer; vhrd.tech always lowercase, for URLs and mail. Never "Vhrd.tech AS", "VHRD Tech", "VHRD.tech" or "Vhrd.Tech" (Roman, 4 Nov 2026). The wordmark is drawn, not text.
- **Draft copy is marked** (`<span class="v-badge">draft</span>` or `extra.stub = true`) until Marketing and PM have read it.
- **Nothing private on the site or the preview.** A share link is public to anyone who has it. No employer work in the lab pages (decided 4 Nov 2026).
- **Write for reading:** short complete sentences, one fact per list item, open with what it is about.
- Planning and review notes don't belong in this repo. They live in the tpm project folder (P2633 `design/`).

## Checks before ready

`just test` and `just lint`. For a visible change, also look at screenshots at 390 and 1440 px in both themes (`just check-browser` covers console, overflow, keyboard and the toggle). The checklist is the UX/UI web checklist: phone, tablet and desktop widths, keyboard, contrast in both themes, a clean console, reduced motion.

## Commits

Short imperative subject, one topic per commit, FEATURES.md and CHANGELOG.md in the same commit.
