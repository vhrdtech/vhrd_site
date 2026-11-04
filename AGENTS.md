# Working on vhrd_site

vhrd.tech, a static site built with Zola: Markdown in `content/`, Tera templates in `templates/`, hand-written CSS. It is the home for Donguru's launch, Pinsmith, the CAN line and the software, so every page answers: what it is, why it is good, what to do next.

## Zola version

**Zola 0.23.6**, pinned in `justfile` (`zola_version`). `just install` puts that release binary in `~/.local/bin`, and `just test` refuses any other version. Zola 0.23 uses Tera 2: there are no shortcodes and no macros, only components (`{% component %}`, called as `{{ <vh.card ... /> }}`). Undefined variables are errors, tests take keyword arguments (`is starting_with(pat=...)`) and arrays are indexed with `[0]`. Highlighting is configured under `[markdown.highlighting]`. Bump the pin on purpose, with a CHANGELOG line.

## FEATURES.md and CHANGELOG.md

[FEATURES.md](FEATURES.md) tracks what exists and what is planned, with stable IDs (`SITE-1`, `LOOK-3`, `BLOCK-2`, `PREVIEW-1`). Name them with their slug when talking to the user (`LOOK-3 grid-and-traces`). Get a new id with `tpm work claim AREA`. Update FEATURES.md in the same commit as the change.

[CHANGELOG.md](CHANGELOG.md) gets an entry for every visible change under `## [Unreleased]`. A branch never writes a version heading: `tpm land` turns `[Unreleased]` into `## [x.y.z] - date` and tags it. Every version gets its own section. Questions like "what's new" are answered from it, newest first, with FEATURES.md for current status.

## Layout

- `config.toml`: site settings; `[extra]` holds the company line, contact mail, header links and the notify button.
- `content/`: one Markdown file per page (`donguru.md` is `/donguru/`). Stubs carry `extra.stub = true`. No blog and no feed. WordPress is gone from vhrd.tech (4 Nov 2026): its old paths (posts, /feed/, /product/, /cart/, /checkout/, ...) redirect on the server with `deploy/redirects.map`, and nothing of WordPress (wp-*, PHP, those paths) may be generated here. `/shop/` is the site's own page; every other path gets the site's 404 page.
- `templates/base.html`: the page frame, with the view frame's four crosses (`.view-frame`) and an `intro` block the home page fills. `partials/header.html`, `partials/footer.html` (build stamp from `VHRD_GIT` and `VHRD_BUILT`, which the justfile sets) and `partials/wordmark.html` (generated).
- `templates/components.html`: the `vh.*` components, usable in templates and Markdown (README "Components").
- `templates/index.html`: the landing page; `partials/intro.html` is its oscilloscope intro, with its script in `partials/intro-script.html` at the end of the body (README "Intro"). `page.html` is a plain page, `section.html` is the blog list, and there are `404.html` and `robots.txt`.
- `static/css/brand/`: `tokens.css` and `vhrd.css` from vhrd_brand (`just brand`). Never edit these here; change vhrd_brand and pull.
- `static/css/site.css`: the site's own layer. `base.html` inlines all the CSS (fonts.css, the brand files and site.css) into each page with `load_data`, so there is no render-blocking request. `static/js/site.js`: theme toggle, tabs and the image placeholders' marking, nothing else.
- `static/fonts/`: IBM Plex woff2 subsets and `fonts.css`. `static/img/boards/` holds board renders (`just renders`, README "Board renders") and `static/img/lab/` lab photos.
- `tools/wordmark.py` draws the wordmark and favicon outlines. `tools/check_pages.py` is the browser check, `tools/perf.py` measures the first screen on a slow phone, `tools/fonts.py` cuts the Core font subsets and the small Greek faces (Ω, μ) from vhrd_brand's full fonts.
- `.github/workflows/deploy.yml`: the only way the site reaches vhrd.tech (README "Deploy"); `.github/deploy/known_hosts` pins the server's host key. `tools/check_live.py` checks a live build before upload and the site after it.
- `data/term/`: the terminal captures on /software (`captures.toml`, and per capture the screen as HTML and its TOML), recorded by `tools/term_capture.py` (`just captures`, README "Terminal captures") and shown by `vh.term`. Never edited by hand. `tools/term/units_demo` is the crate behind the exact_units compile error, `tools/term/ww_evolution` the API behind the evolution check.
- `data/links.toml`: our projects' names and where a mention leads (a page, a card on /open-source or a repo). `vh.ref` and `vh.linkify` read it, and `tools/mentions.py` (in the browser check) fails a page whose first mention of a name is not a link.
- `data/stack.toml`: the open-source crates in their /open-source order (layer, logos per theme, code sample, which are on crates.io); `front = true` puts one on the front page too. `partials/crate-stack.html` draws them for both pages, `templates/open-source.html` is the /open-source page. `data/repos.toml`: every other repository on /open-source, by area (`partials/repo-list.html`); its head names the repos left off and why.

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
just live             # the live site for https://vhrd.tech/ into target/live (indexable, nothing of WordPress), checked
just deploy           # start the Deploy workflow on GitHub; it waits for approval (README "Deploy")
just check-live       # the deployed site against target/live: pages 200, the footer stamp, the old paths' 301s, the 404
just check-draw [URL] # the traces (draw with the scroll, both ways) and first clicks: the local build by default, or a deployed site
just preview TOKEN    # noindex build for https://shadow.vhrd.tech/TOKEN/, uploaded with tpm share (README "Preview")
just check-preview URL  # the browser check against a deployed preview, screenshots into target/shots
just captures         # record the terminal captures on /software again (data/term/captures.toml)
just renders          # rebuild static/img/boards/ from ~/git/hw (KiCad); needs a machine-local 3D model
                       # library and the silkscreen fonts in fc-list (README "Board renders")
just renders --variants  # only the missing web widths, from the PNG sources (no KiCad)
```

The browser check runs Chromium and Playwright's Firefox (`just install` fetches it).

`just test` accepts and ignores `--changed`: the site is one unit, and a full test takes about a minute. The traces'
scroll-linked draw and the first clicks, on every page in two browsers at five screen sizes, are slow (about 5 min)
and not part of it: run `just check-draw` after changing traces, scroll or intro code, and `just check-draw
https://vhrd.tech` after a deploy. The CI deploy workflow does not run it.

## Conventions

- **Colours only through tokens** (`var(--accent)`, `var(--signal-usb)`), never hex values in templates or `site.css`. The brand red is used sparingly: one word of the hero headline, the main button, the wordmark, the MCU in diagrams, figure corner marks and the Highlights group on /open-source. Headlines are in the text colour. Power is orange, never red.
- **Dark first, light equal.** Every change is checked in both themes. Dark is the default whatever the system prefers (`<html data-theme="dark">`, Roman, 4 Nov 2026); light only when the visitor picks it with the toggle, stored in localStorage and applied by the head script before the first paint. Back to dark clears it.
- **Almost no JavaScript, no framework.** Animation is CSS, off under `prefers-reduced-motion`. The traces draw and undraw with the scroll: a few lines of inline script at the end of `base.html` set each one's draw progress `--p` from its place on screen, the last ones completing at the page's end (scroll-driven CSS stalled on tall screens and does not exist in Firefox); without JavaScript they are simply drawn. The page must work without `site.js`. The front page's intro has a small inline script; without it the intro never shows.
- **Links through `get_url`**, so the preview under a sub-path works. A link to a page passes `trailing_slash=true` (`get_url(path="/work/", trailing_slash=true)`): without it Zola drops the slash and every click costs a redirect. Internal Markdown links use `@/page.md`. The browser check fails on an internal link without the slash, on one that does not answer 200, and on a page no link reaches.
- **The name is VHRD; the address is vhrd.tech.** VHRD in titles, copy, product names and the footer; vhrd.tech always lowercase, for URLs and mail; VHRD.TECH AS, the legal name, only in the copyright line (`extra.legal`). Never "Vhrd.tech AS", "VHRD Tech", "VHRD.tech" or "Vhrd.Tech" (Roman, 4 Nov 2026). The wordmark is drawn, not text.
- **Brand words** come from ~/git/tpm/area/marketing/brand.md (Roman, 4 Nov 2026). The one line (hero lead, meta description): "Instruments for embedded development, and the open-source software behind them." VHRD builds instruments, not dev boards to ship inside products, for everyone who works where code meets hardware (hardware, firmware and software engineers), not only hardware engineers. "From Norway" stays out of the hero and the meta; Asker, Norway is in the footer and on /about.
- **Draft copy is marked** (`<span class="v-badge">draft</span>` or `extra.stub = true`) until Marketing and PM have read it.
- **Nothing private on the site or the preview.** A share link is public to anyone who has it. No employer work in the lab pages (decided 4 Nov 2026).
- **Write for reading:** short complete sentences, one fact per list item, open with what it is about.
- Planning and review notes don't belong in this repo. They live in the tpm project folder (P2633 `design/`).

## Checks before ready

`just test` and `just lint`. For a visible change, also look at screenshots at 390 and 1440 px in both themes (`just check-browser` covers console, overflow, keyboard and the toggle). The checklist is the UX/UI web checklist: phone, tablet and desktop widths, keyboard, contrast in both themes, a clean console, reduced motion.

## Commits

Short imperative subject, one topic per commit, FEATURES.md and CHANGELOG.md in the same commit.
