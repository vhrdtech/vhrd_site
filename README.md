# vhrd_site

vhrd.tech: the company site, built with [Zola](https://www.getzola.org/) from Markdown and hand-written templates and CSS. No framework; the only script is the theme toggle and the code tabs.

## Use

```sh
just install         # Zola (the version pinned in AGENTS.md) into ~/.local/bin, no root
just serve           # http://127.0.0.1:1111 with live reload
just test            # zola check + build, every page in headless Chromium, brand files match vhrd_brand
just lint            # whitespace, the tools parse
just deploy-preview  # noindex build to https://static.vhrd.tech/vhrd-site-preview/
```

`just test` needs `chromium` and `uv` (the browser check is `tools/check_pages.py`, run with uv).

## Brand

Colours, type and the web stylesheet come from [vhrd_brand](https://github.com/vhrdtech/vhrd_brand) and are never edited here:

- `static/css/brand/tokens.css` and `vhrd.css` are copies of vhrd_brand's `web/` files. `just brand` pulls them from `~/git/vhrd_brand` (or `$VHRD_BRAND`) and writes the vhrd_brand version to `static/css/brand/VERSION`. `just test` fails when they differ from that checkout.
- `static/css/site.css` is this site's layer on top: grid, frame, traces, components. It uses tokens only, never hex values.
- Fonts are IBM Plex Sans, Mono and Serif, self-hosted as woff2 under `static/fonts/` (OFL, `OFL-IBMPlex.txt`). They are the Latin1, Latin2 and Pi subsets of IBM's npm releases (`@ibm/plex-sans` 1.1.0, `plex-mono` 2.5.0, `plex-serif` 2.0.0). The browser loads a subset only when a page uses one of its characters.
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

## Preview

`just deploy-preview` builds with `VHRD_NOINDEX=1`, which adds `<meta name="robots" content="noindex, nofollow">` to every page and a robots.txt that disallows everything. It builds for the base URL `https://static.vhrd.tech/vhrd-site-preview/`. It then uploads with rsync to the deploy user's inbox on vhrd.tech and runs the server's mover. The last step checks that the live footer shows this build's git hash.

- static.vhrd.tech is public and lists its directories. Nothing private goes there.
- The robots.txt sits in a subdirectory, where crawlers don't read it. The meta tag on each page is what keeps the preview out of search results.
- The upload needs a PC whose ssh key the deploy user accepts.
- **Re-deploys:** the server's mover only creates new dirs. When `vhrd-site-preview` already exists, it prints `mv: cannot overwrite`, exits 0, and leaves the upload in the inbox owned by www-data. Before a re-deploy, Roman moves the old dir away on the server: the live `/usr/share/nginx/static.vhrd.tech/vhrd-site-preview` and any leftover `/home/deploy/to_static/vhrd-site-preview`. A helper that does this safely is drafted in `deploy/static/` and is not installed (see its README).
