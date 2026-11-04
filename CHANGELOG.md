# Changelog

## [Unreleased]

### Added

- Zola site skeleton (Zola 0.23.6, Tera 2 components): base template, header, footer with the build stamp, 404, robots.txt, sitemap and blog feed.
- Brand from vhrd_brand: `tokens.css` and `vhrd.css` pulled by `just brand` (v0.9.9), IBM Plex Sans, Mono and Serif self-hosted (OFL, woff2 subsets), the VHRD.TECH wordmark and favicon as Audiowide outlines (`just wordmark`).
- Dark and light theme: follows the system, a toggle in the header remembers the choice.
- The look: drawing grid, framed column with crosshairs, mono caps labels, FIG. captions with corner marks, PCB traces in the signal colours between sections, drawn in on scroll (off under reduced motion).
- Components for templates and Markdown: `vh.section`, `vh.label`, `vh.trace`, `vh.card`, `vh.cards`, `vh.specs`, `vh.fig`, `vh.code_tabs`.
- Page stubs for the site map: /, /donguru, /report, /can, /software, /open-source, /lab, /services, /about, /blog, /shop.
- `tools/check_pages.py`: every page in headless Chromium at phone, tablet and desktop widths in both themes, part of `just test`.
- just recipes: `test`, `lint`, `install` (Zola into ~/.local/bin), `brand`, `wordmark`, `serve`, `build`, `check-browser`, `check-preview`, `deploy-preview` (noindex build to https://static.vhrd.tech/vhrd-site-preview/; a re-deploy needs the old dir moved away on the server first).
- `deploy/static/`: draft of a root helper for re-deploys to static.vhrd.tech, not installed (waits for a security review).

