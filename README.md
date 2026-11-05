# vhrd_site

vhrd.tech: the company site, built with [Zola](https://www.getzola.org/) from Markdown and hand-written templates and CSS, plus `vhrd_notify`, a small Rust signup service in `server/`. Working instructions, conventions and every recipe (build, test, deploy, previews, board renders, the notify service) are in [AGENTS.md](AGENTS.md).

## Use

```sh
just install   # Zola into ~/.local/bin
just serve     # build and serve with live reload, prints the URL to open
just test      # the full check: notify service tests, zola build, browser check
```

## Deploy

https://vhrd.tech/ is deployed by hand from the Deploy workflow on GitHub Actions, after approval (AGENTS.md "Deploy").

## Licence

The code — templates, CSS, JS, `tools/`, `scripts/`, the `vhrd_notify` service in `server/` — is licensed under either of [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option.

The content — texts in `content/`, photos, board renders, screenshots, terminal captures, the VHRD wordmark and the brand files — is © VHRD.TECH AS. All rights reserved.

The IBM Plex fonts under `static/fonts/` keep their own OFL licence (`OFL-IBMPlex.txt`).
