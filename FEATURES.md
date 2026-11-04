# Features

Status: ✅ done · 🚧 in progress · 📋 planned · 💡 idea · 🐛 bug

## SITE: the site and its pages

- ✅ SITE-1 zola-skeleton: Zola site (version pinned in AGENTS.md), `config.toml`, base template, 404, robots.txt, sitemap, blog feed
- ✅ SITE-2 header-footer: header with the wordmark, Products, Software, Open source, Lab, Blog, theme toggle and the red "Get notified" button (a menu under 52rem); footer with Vhrd.tech AS, link columns and the build stamp (git hash and commit date)
- 🚧 SITE-3 page-stubs: stubs for /, /donguru, /report, /can, /software, /open-source, /lab, /services, /about, /blog, /shop, each marked draft; filled by later steps
- ✅ SITE-4 browser-checks: `tools/check_pages.py` drives every page in headless Chromium at 390, 820 and 1440 px, dark and light (console clean, no sideways scroll, theme toggle, keyboard tabs, skip link)

## LOOK: brand and motif

- ✅ LOOK-1 brand-sync: `tokens.css` and `vhrd.css` pulled from vhrd_brand by `just brand` and compared by `just test`; IBM Plex Sans, Mono and Serif self-hosted as woff2 subsets (OFL); the VHRD.TECH wordmark and favicon as Audiowide outlines (`just wordmark`)
- ✅ LOOK-2 theme-toggle: follows `prefers-color-scheme`, the toggle's choice is remembered (localStorage) and applied before first paint; code highlighting follows it
- ✅ LOOK-3 grid-and-traces: faint drawing grid, framed column with crosshairs where section rules meet it, mono caps labels, PCB traces in the signal colours between sections drawn in on scroll (CSS scroll-driven animation, no script; drawn at once under reduced motion)

## BLOCK: components for templates and content

- ✅ BLOCK-1 section-label: `vh.section` and `vh.label` (numbered mono caps label, hairline, crosshairs)
- ✅ BLOCK-2 card-specs: `vh.card` (render, badge, pitch, specs, link; wired in a signal colour), `vh.cards` grid, `vh.specs` list
- ✅ BLOCK-3 fig-caption: `vh.fig` with the datasheet's red corner marks and a "FIG. n" caption; a hatched placeholder until the image exists
- ✅ BLOCK-4 code-tabs: `vh.code_tabs`, Markdown panels as ARIA tabs (arrow keys); stacked without script

## PREVIEW: publishing

- ✅ PREVIEW-1 deploy-preview: `just deploy-preview` builds with noindex (meta robots, robots.txt Disallow all) for https://static.vhrd.tech/vhrd-site-preview/ and publishes it through the server's mover; the live footer hash is checked
- 📋 PREVIEW-2 static-replace: re-deploys without hand work, through a root helper on vhrd.tech (draft in `deploy/static/`, needs a security review and the symlink-race fix before Roman installs it)
