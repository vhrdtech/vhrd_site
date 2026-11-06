# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.47"]
# ///
"""Drive a built site in headless Chromium the way a visitor would and fail on what the web checklist names.

Usage: uv run tools/check_pages.py [BASE_URL] [--chromium PATH] [--shots DIR]

Without BASE_URL it builds the site with zola into target/check for a local port and serves it from there (what
`just check-browser` does); with one it checks that site as deployed (`just check-preview`).

For every page in the site map, at phone (390), tablet (820) and desktop (1440) widths, in dark and light:
no console errors or failed requests, no sideways scroll, the open-source stack's track through every via's centre.
Every code sample is the same code in its narrow and wide version, and a card shows the narrow one on a phone\nand the wide one on a wide screen, without a sideways scroll from 320 px up. /open-source
lists every repository of data/repos.toml, a public one linked, a private one marked as coming and not linked.
On the front page: the theme toggle switches and the choice survives a reload, the code tabs work by keyboard
(arrow keys, on /donguru), the skip link is the first tab stop.
First-view budget: what a phone loads for the front page before scrolling (HTML, CSS, script, fonts, images)
stays under BUDGET_KB as sent over the wire: text gzipped (as the local build would be served by a server that
compresses), fonts and images as they are; against a deployed site, the transfer sizes the browser saw. Every image
has alt text and its width and height.
The front page's intro: on every load it shows and clears by itself without waiting on a fast site, waits (LOADING)
for a late hero render and fires (TRIG'D), says after 5 s how to skip and a click skips it, a key skips it, the
replay button plays the slow path as a demo; never with a #fragment, under reduced motion or without JavaScript.
On every page the figures are numbered 1, 2, 3... in order, without a gap.
With --only draw (`just check-draw [URL]`, not part of the default run: it takes about 5 min against every page, in
Chromium and Firefox, on two phones and three desktops up to 2560x1440): the PCB traces and the footer's bus draw and
undraw with the scroll (undrawn below the fold, all drawn at the page's end, the bus falling when the page scrolls back
up and the same at the same place either way); on /lab the first click on each nav link, the wordmark, a footer link
and the GitHub link navigates.
Every text in a table cell is 4.5:1 on the cell's background, in dark and light.
Links: every page in the site map is reached from the front page by links (no orphans), and every internal
href on every page reached ends in '/' when it names a page and answers 200 without a redirect. On every page reached,
the first mention of each project in data/links.toml is a link to it (tools/mentions.py).
Mail: no page or file has an address in it ('@vhrd.tech'); with JavaScript every mail link is a mailto link with
its subject (projects@ on /services, donguru@ on /donguru and the front page, contact@ in the footer), and without
it a mail link is plain text ("projects at vhrd.tech") and a labelled one does not show.
A picture on its way shows as a small scope screen in its box and fades in when it comes, without a size change.
The signup form (only against the local build, which posts to a local notify service with a store of its own): with
JavaScript a good address shows the thanks in place and lands in the store, a refused one the error; without it the
service sends the visitor back to the page's #notify-ok or #notify-bad, which shows; the honeypot is not on screen.
CSS: a page inlines the styles of the intro, the open-source stack or the terminal captures exactly when it shows
them, and the CSS every page carries stays under SHARED_CSS_KB (Firefox's first paint of a page, AGENTS.md
"Performance").
The mail links' pages /notify/confirm/ and /notify/remove/ (also only against the local build, the service's answers
stubbed): the token after '#' fills the form, each answer shows its message; without JavaScript the token field shows.
They are the orphan rule's exception: noindex, out of the site map, and only our mail links to them.
With --shots, writes a full-page screenshot per width in dark (traces shown drawn: reduced motion).
"""

import argparse
import atexit
import functools
import gzip
import html.parser
import http.server
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright

import mentions
import samples

PAGES = ["", "donguru/", "pinsmith/", "can/", "software/", "open-source/", "lab/", "work/", "services/", "about/", "shop/",
         "privacy/", "faq/", "notify/confirm/", "notify/remove/", "no-such-page/"]
# Pages only our mail links to (NOTIFY-4 double-opt-in): the exception to the orphan rule. Each must answer 200, say
# noindex and stay out of the site map; their own links are checked like those of a page reached.
MAIL_ONLY = ["notify/confirm/", "notify/remove/"]
WIDTHS = {"phone": 390, "tablet": 820, "desktop": 1440}
BUDGET_KB = 200
# The CSS every page carries inline (fonts.css, the brand files, site.css): Firefox matches it against the whole page
# before its first paint, and until then it shows its own tab background between pages (AGENTS.md "Performance").
SHARED_CSS_KB = 56
# A part only some pages have, with its own styles inlined only there (extra.styles), and the class that marks it.
CSS_PARTS = {"intro": "scope", "stack": "stack", "term": "term", "about": "who-makes-it", "notify": "notify-link"}

# Everything the page fetched so far, the document first: URL, body size, transfer size.
FETCHED = """() => [performance.getEntriesByType("navigation")[0], ...performance.getEntriesByType("resource")]
  .map((e) => [e.name, e.decodedBodySize || 0, e.transferSize || 0])"""
TEXT = (".html", ".css", ".js", ".svg", ".json", ".xml", ".txt")
# The open-source stack: every via's centre against the centre of the track that runs through it, in px.
VIA_OFFSETS = """() => [...document.querySelectorAll('.layer')].map((l) => {
  const v = l.querySelector('.layer-head .via').getBoundingClientRect();
  const t = getComputedStyle(l, '::before');
  return v.left + v.width / 2 - (l.getBoundingClientRect().left + parseFloat(t.left) + parseFloat(t.width) / 2);
})"""
# Crate cards marked `fits` in data/stack.toml: how far each one's code scrolls sideways, in px.
CODE_OVERFLOW = """() => [...document.querySelectorAll('.crate[data-fits] .crate-code pre')]
  .map((p) => [p.closest('.crate').id, p.scrollWidth - p.clientWidth])"""
# Cards with a wide version: whether it is the one shown.
CODE_SHOWN = """() => [...document.querySelectorAll('.crate .code-wide')]
  .map((w) => [w.closest('.crate').id, getComputedStyle(w).display !== 'none'])"""
# Figure numbers in page order (FIG. n captions and code panel labels): they must run 1, 2, 3... without a gap.
FIG_NUMBERS = """() => [...document.querySelectorAll('.fig-no, .code-tabs-bar > .v-label')]
  .map((e) => e.textContent.match(/^FIG\\. (\\d+)/)).filter(Boolean).map((m) => +m[1])"""
IMAGES_WITHOUT = """() => [...document.images]
  .filter((i) => !i.hasAttribute("alt") || !i.getAttribute("width") || !i.getAttribute("height"))
  .map((i) => i.currentSrc || i.src)"""
OG_META = """() => { const m = (s) => document.querySelector(s)?.content || null;
  return [m('meta[property="og:image"]'), m('meta[property="og:image:width"]'), m('meta[property="og:image:height"]'),
          m('meta[property="og:image:alt"]'), m('meta[name="twitter:card"]'), m('meta[name="twitter:image"]')]; }"""

# Photos (img/lab/) and the B135 render are never cropped: shown at their own ratio or letterboxed (contain).
CROPPED = """() => [...document.images]
  .filter((i) => ["/img/lab/", "b135_"].some((k) => (i.getAttribute("src") || "").includes(k)))
  .filter((i) => i.getBoundingClientRect().width > 0)
  .filter((i) => {
    const cs = getComputedStyle(i);
    if (cs.objectFit === "contain" || cs.objectFit === "scale-down") return false;
    const r = i.getBoundingClientRect(), box = r.width / r.height;
    const natural = i.getAttribute("width") / i.getAttribute("height");
    return Math.abs(box - natural) / natural > 0.02;
  })
  .map((i) => i.getAttribute("src"))"""


# Table text against its cell: every text in a th or td (badges and links in it too), its colour on the first
# background behind it that is not transparent (half-transparent ones blended on), answered where under 4.5:1.
TABLE_CONTRAST = r"""() => {
  const rgba = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const v = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number); return [v[0], v[1], v[2], v.length > 3 ? v[3] : 1]; };
  const over = (a, b) => [0, 1, 2].map((i) => a[i] * a[3] + b[i] * (1 - a[3])).concat(1);
  const behind = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = rgba(getComputedStyle(e).backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    return layers.reduceRight((acc, c) => over(c, acc), [255, 255, 255, 1]);
  };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const bad = [];
  let n = 0;
  for (const cell of document.querySelectorAll('table th, table td')) {
    const walk = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
    for (let t; (t = walk.nextNode());) {
      if (!t.data.trim()) continue;
      const el = t.parentElement, cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || el.getClientRects().length === 0) continue;
      const fg0 = rgba(cs.color);
      if (!fg0) { bad.push(`${t.data.trim().slice(0, 30)}: colour ${cs.color} not rgb`); continue; }
      const bg = behind(el), fg = over(fg0, bg);
      const l1 = lum(fg), l2 = lum(bg), r = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      n++;
      if (r < 4.5) bad.push(`"${t.data.trim().slice(0, 30)}" ${r.toFixed(2)}:1 (${cs.color} on rgb(${bg.slice(0, 3).map(Math.round)}))`);
    }
  }
  return [n, bad];
}"""

def wire_bytes(fetched, base, out):
    """Bytes as sent: for the local build, text files gzipped and the rest as they are; else the transfer sizes."""
    if out is None:
        return sum(t for _, _, t in fetched)
    total = 0
    for url, size, _ in fetched:
        path = urlsplit(url).path[len(urlsplit(base).path):]
        f = out / path
        if f.is_dir() or not path:
            f = f / "index.html"
        if f.is_file():
            data = f.read_bytes()
            total += len(gzip.compress(data, 6)) if f.suffix in TEXT else len(data)
        else:
            total += size
    return total


def serve_build():
    """Build the site for a free local port, serve it in a thread, return its address."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}/"
    root = Path(__file__).resolve().parent.parent
    out = root / "target/check"
    api = start_notify(root, f"http://127.0.0.1:{port}")
    subprocess.run(["zola", "build", "--base-url", base, "--output-dir", str(out), "--force"], cwd=root,
                   check=True, stdout=subprocess.DEVNULL, env={**os.environ, "VHRD_NOTIFY_API": api})
    handler = functools.partial(Quiet, directory=str(out))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return base, out


NOTIFY_STORE = None


def start_notify(root, origin):
    """Build and start the notify service for the local build on a free port, with a store in a temp folder that goes
    when the check ends; returns the form's endpoint."""
    global NOTIFY_STORE
    subprocess.run(["cargo", "build", "--quiet", "-p", "vhrd_notify_cli"], cwd=root, check=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    tmp = tempfile.TemporaryDirectory(prefix="vhrd_notify-check-")
    cfg = Path(tmp.name) / "notify.toml"
    # every check posts from 127.0.0.1: a limit the check never reaches (the Rust tests cover the limit)
    consent = tomllib.loads((root / "config.toml").read_text())["extra"]["notify_consent"]
    cfg.write_text(f'listen = "127.0.0.1:{port}"\nstore = "signups.tsv"\nsite_origin = "{origin}"\n'
                   f'consent_versions = ["{consent}"]\n'
                   'client_ip_header = ""\nrate_limit = 1000\nrate_limit_network = 1000\n')
    NOTIFY_STORE = Path(tmp.name) / "signups.tsv"
    proc = subprocess.Popen([root / "target/debug/vhrd_notify", "serve", "--config", cfg], stderr=subprocess.DEVNULL)
    atexit.register(tmp.cleanup)
    atexit.register(proc.wait)
    atexit.register(proc.terminate)
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        proc.poll() is None or sys.exit("notify service did not start")
        threading.Event().wait(0.05)
    return f"http://127.0.0.1:{port}/api/notify"


def check_notify(browser, base):
    """The signup form with and without JavaScript, in dark and light, against the local service's store."""
    failures = []
    # a signup is in the intake first, until the service's worker folds it into the store
    files = [NOTIFY_STORE, NOTIFY_STORE.with_name(NOTIFY_STORE.name + ".intake")]
    stored = lambda: "".join(f.read_text() for f in files if f.exists())  # noqa: E731
    cases = [  # page, JavaScript, theme, address, message expected
        ("donguru/", True, "dark", "check-js@example.com", "ok"),
        ("donguru/", True, "light", "nope@localhost", "bad"),
        ("", True, "light", "check-home@example.com", "ok"),
        ("", False, "dark", "check-nojs@example.com", "ok"),
        ("donguru/", False, "light", "nope@localhost", "bad"),
    ]
    for path, js, theme, address, want in cases:
        where = f"notify: {path or '/'} {'with' if js else 'without'} JavaScript, {theme}"
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=js,
                                  reduced_motion="reduce")
        if theme == "light":
            ctx.add_init_script("try { localStorage.setItem('theme', 'light') } catch (e) {}")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + path)
        hp = page.locator(".notify-hp").bounding_box()
        if hp is None or hp["x"] + hp["width"] > 0:
            failures.append(f"{where}: the honeypot is on screen")
        if page.locator(".notify-msg:visible").count():
            failures.append(f"{where}: a message shows before anything was sent")
        page.fill("#notify-email", address)
        page.click(".notify-form button[type=submit]")
        msg = page.locator(f"#notify-{want}")
        try:
            msg.wait_for(state="visible", timeout=5000)
        except Exception:
            failures.append(f"{where}: #notify-{want} did not show (at {page.url})")
        if page.locator(".notify-msg:visible").count() != 1:
            failures.append(f"{where}: {page.locator('.notify-msg:visible').count()} messages show, expected one")
        if not js and not page.url.startswith(base + path) or not js and not page.url.endswith(f"#notify-{want}"):
            failures.append(f"{where}: sent back to {page.url}, expected {base + path}#notify-{want}")
        if (want == "ok") != (f"\t{address}\t" in stored()):
            failures.append(f"{where}: {address} {'not ' if want == 'ok' else ''}in the store")
        failures += [f"{where}: {e}" for e in errors]
        ctx.close()
    return failures


def check_notify_links(browser, base):
    """The mail links' pages (NOTIFY-4 double-opt-in), with the service's answers stubbed: with JavaScript the token
    after '#' fills the form's field, which hides, and the button's answer shows in place (200 done, 404 gone, 429
    wait, 503 err) with the token gone from the address; without it the field shows, and a #notify-done or -gone
    shows its message without the button."""
    failures = []
    token = "AQ" + "x" * 42
    for path in MAIL_ONLY:
        for status, want in [(200, "done"), (404, "gone"), (429, "wait"), (503, "err")]:
            where = f"notify link: {path} with JavaScript, answer {status}"
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
            page = ctx.new_page()
            posted = []

            def answer(route, request, status=status):
                posted.append(request.post_data or "")
                # the local build posts to another port: the answer allows that, as the local service does
                route.fulfill(status=status, body="{}", content_type="application/json",
                              headers={"Access-Control-Allow-Origin": "*"})
            page.route("**/api/notify/**", answer)
            page.goto(f"{base}{path}#{token}")
            if page.locator("#notify-token").is_visible() or page.input_value("#notify-token") != token:
                failures.append(f"{where}: the token field shows, or does not hold the token")
            page.click(".notify-link button[type=submit]")
            try:
                page.locator(f"#notify-{want}").wait_for(state="visible", timeout=5000)
            except Exception:
                failures.append(f"{where}: #notify-{want} did not show")
            if page.locator(".notify-msg:visible").count() != 1:
                failures.append(f"{where}: {page.locator('.notify-msg:visible').count()} messages show, expected one")
            action = path.split("/")[1]
            if posted != [f"from={action}&token={token}"]:
                failures.append(f"{where}: posted {posted}, expected from={action}&token=...")
            finished = want in ("done", "gone")
            if page.locator(".notify-link button").is_visible() == finished:
                failures.append(f"{where}: the button {'still shows' if finished else 'went'}")
            if finished and token in page.url:
                failures.append(f"{where}: the token stayed in the address")
            ctx.close()
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=False)
        page = ctx.new_page()
        page.goto(base + path)
        if not page.locator("#notify-token").is_visible() or page.locator(".notify-msg:visible").count():
            failures.append(f"notify link: {path} without JavaScript: no token field, or a message before a post")
        for hash, button in [("notify-done", False), ("notify-gone", False), ("notify-wait", True), ("notify-err", True)]:
            page.goto(f"{base}{path}#{hash}")
            if not page.locator(f"#{hash}").is_visible() or page.locator(".notify-link button").is_visible() != button:
                failures.append(f"notify link: {path}#{hash} without JavaScript: the message or the button is wrong")
        ctx.close()
    return failures


class Quiet(http.server.SimpleHTTPRequestHandler):
    """Serves the build like a web server would: text gzipped when the browser accepts it, no request log."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        f = Path(self.translate_path(self.path))
        if f.is_dir() and self.path.split("?")[0].endswith("/"):
            f = f / "index.html"
        if f.suffix not in TEXT or not f.is_file() or "gzip" not in self.headers.get("Accept-Encoding", ""):
            return super().do_GET()
        body = gzip.compress(f.read_bytes(), 6)
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(f)))
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


INTRO_ON = "document.documentElement.classList.contains('intro')"
SCOPE_SHOWN = "getComputedStyle(document.querySelector('.scope')).display !== 'none'"
# The intro's vector pass: every stroke against the element it traces, measured here on its own. A box is the
# element's box, an edge its bottom edge, an underline lies under a line of its text, a word is drawn where the word
# is laid out, a wire runs from its top via. Answers the strokes per kind and what is off.
TRACES_MATCH = r"""() => {
  const near = (a, b, t = 1.5) => Math.abs(a - b) <= t;
  const bad = [], kinds = {};
  for (const n of document.querySelectorAll('.scope-draw [data-k]')) {
    const k = n.dataset.k, el = document.querySelectorAll(n.dataset.sel)[+n.dataset.i];
    kinds[k] = (kinds[k] || 0) + 1;
    if (!el) { bad.push(`${k} ${n.dataset.sel} #${n.dataset.i}: no such element`); continue; }
    const b = n.getBoundingClientRect(), r = el.getBoundingClientRect();
    let ok = true;
    if (k === 'box') ok = near(b.left, r.left) && near(b.top, r.top) && near(b.width, r.width) && near(b.height, r.height);
    else if (k === 'edge') ok = near(b.left, r.left) && near(b.right, r.right) && near(b.top, r.bottom);
    else if (k === 'under') ok = b.width > 0 && b.left >= r.left - 1.5 && b.right <= r.right + 1.5 && b.top >= r.top && b.top <= r.bottom + 1.5;
    else if (k === 'wire') {
      const v = el.querySelector('.via-top').getBoundingClientRect();
      ok = near(b.left, Math.min(b.left, v.left + v.width / 2)) && near(b.top, v.top + v.height / 2) && b.bottom <= r.bottom + 1.5 && b.left >= r.left - 1.5 && b.right <= r.right + 1.5;
    } else if (k === 'text') {
      const words = [];
      const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let t; (t = walk.nextNode());) for (const m of t.data.matchAll(/\S+/g)) {
        const g = document.createRange(); g.setStart(t, m.index); g.setEnd(t, m.index + m[0].length);
        words.push(g.getBoundingClientRect());
      }
      const w = words[+n.dataset.w];
      ok = !!w && near(b.left, w.left, 3) && near(b.right, w.right, Math.max(3, w.width * 0.04)) && b.top >= w.top - 3 && b.bottom <= w.bottom + 3;
    }
    if (!ok) bad.push(`${k} ${n.dataset.sel} #${n.dataset.i}${n.dataset.w ? ' word ' + n.dataset.w : ''}: drawn at ${[b.left, b.top, b.width, b.height].map(Math.round)}, the element at ${[r.left, r.top, r.width, r.height].map(Math.round)}`);
  }
  return [kinds, bad];
}"""


def check_code_fits(browser, base):
    """Every code sample is the same code in its narrow and wide version (tools/samples.py), and the cards show one
    without a sideways scroll from a 320px phone up: the narrow one on a phone, the wide one on a wide screen."""
    failures = list(samples.problems())
    for w in (320, 360, 390, 430, 600, 820, 960, 1280, 1440):
        ctx = browser.new_context(viewport={"width": w, "height": 900}, reduced_motion="reduce")
        page = ctx.new_page()
        for path in ("", "open-source/"):
            page.goto(base + path)
            for crate, px in page.evaluate(CODE_OVERFLOW):
                if px > 0:
                    failures.append(f"{path or '/'} {w}px: the {crate} card's code scrolls sideways by {px}px")
            for crate, wide in page.evaluate(CODE_SHOWN):
                if w <= 430 and wide:
                    failures.append(f"{path or '/'} {w}px: the {crate} card shows its wide code on a phone")
                if w >= 1280 and not wide:
                    failures.append(f"{path or '/'} {w}px: the {crate} card is held to its narrow code on a wide screen")
        ctx.close()
    return failures


def check_repos(browser, base):
    """/open-source: a Highlights group (the crates marked `front` in data/stack.toml, in that order), then one group
    per area of data/repos.toml, every repository once, the highlights again in their areas (`stack = true`). A public card links to its source and shows its code sample
    or "example: TBD"; a private one says it is coming and has no link or code. Inside an area the cards follow one
    rule: on crates.io, then public, then work in progress, then coming in the future, by name within each. The jump
    row on top names the same groups in the same order and colours, at a phone's and a desktop's width."""
    stack = [c for c in tomllib.loads(Path("data/stack.toml").read_text())["crate"] if c.get("front")]
    data = tomllib.loads(Path("data/repos.toml").read_text())
    repos = data["repo"]
    rank = lambda r: 3 if r.get("private") else 2 if r.get("wip") else 0 if r.get("crate") else 1
    groups = [("highlights", [c["name"] for c in stack])] + [
        (a["id"], [r["name"] for r in sorted((r for r in repos if r["area"] == a["id"]), key=lambda r: (rank(r), r["name"]))])
        for a in data["area"]]
    by_name = {c["name"]: c for c in stack}
    want = {c["name"]: (c["repo"], c) for c in stack} | {
        r["name"]: (f"https://github.com/{r['owner']}/{r['name']}", r) for r in repos if not r.get("stack")}
    failures = [f"data/repos.toml: {r['name']} is stack = true but not a highlight in data/stack.toml, or its crate differs"
                for r in repos if r.get("stack") and (r["name"] not in by_name or r.get("crate") != by_name[r["name"]].get("crate"))]
    for w in (390, 1440):
        ctx = browser.new_context(viewport={"width": w, "height": 900}, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(base + "open-source/")
        seen = page.evaluate("""() => [...document.querySelectorAll('.repo-area')].map((g) => [g.id,
          getComputedStyle(g.querySelector('.layer-head .via')).borderTopColor,
          [...g.querySelectorAll('.repo')].map((r) => [r.id.replace(/^highlight-/, ''), r.querySelector('h3 a')?.href ?? null,
            !!r.querySelector('.v-badge:not(:empty)') && r.querySelector('.repo-meta .v-badge') !== null,
            !!r.querySelector('.crate-code'), !!r.querySelector('.repo-tbd')])])""")
        jump = page.evaluate("""() => [...document.querySelectorAll('.groups li')].map((li) => [
          li.querySelector('a').getAttribute('href'), getComputedStyle(li.querySelector('.group-via')).borderTopColor])""")
        products = page.locator(".stack-top").count()
        ids = page.evaluate("() => [...document.querySelectorAll('[id]')].map((e) => e.id)")
        failures += [f"/open-source {w}px: the id {i} is there twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
        ctx.close()
        if [g[0] for g in seen] != [g[0] for g in groups]:
            failures.append(f"/open-source {w}px: the groups are {[g[0] for g in seen]}, expected {[g[0] for g in groups]}")
        if [(h, c) for h, c in jump] != [("#" + g[0], g[1]) for g in seen]:
            failures.append(f"/open-source {w}px: the jump row {jump} does not match the groups below (order and colour)")
        if w != 390:
            continue
        for (gid, colour, cards), (_, order) in zip(seen, groups):
            if [c[0] for c in cards] != order:
                failures.append(f"/open-source: {gid} shows {[c[0] for c in cards]}, expected {order}")
        for gid, colour, cards in seen:
            for name, href, badge, code, tbd in cards:
                url, r = want.get(name, (None, None))
                if r is None:
                    failures.append(f"/open-source: {name} is not in the data")
                elif r.get("private") and (href or not badge or code or tbd):
                    failures.append(f"/open-source: private {name} has a link, code or no 'coming in the future' badge")
                elif not r.get("private") and href != url:
                    failures.append(f"/open-source: {name} links to {href}, not {url}")
                elif not r.get("private") and (code != bool(r.get("code")) or tbd == code):
                    failures.append(f"/open-source: {name} shows {'its code' if code else 'no code'}{' and example: TBD' if tbd else ''}")
        if products:
            failures.append("/open-source: the products line of the front page's stack is there")
    return failures


def replay_holds(page, how):
    """The replay started by `how` plays and stays on for its first second: the event that started it is no skip."""
    seen = []
    for _ in range(10):
        seen.append(page.evaluate(INTRO_ON + " && !document.documentElement.classList.contains('intro-skip')"))
        page.wait_for_timeout(100)
    if not seen[0]:
        return [f"intro: the replay button does not play it ({how})"]
    if not all(seen):
        return [f"intro: the replay started by {how} blinks off at once"]
    return []


def check_intro(browser, base):
    """The intro on every load: fast path straight to the page, slow path LOADING / hint / TRIG'D, replay, skip;
    never with a #fragment, under reduced motion or without JS."""
    failures = []
    # Waiting is remembered on the page, so the fast path can be told from a short wait.
    seen = """window.__waited = false; new MutationObserver(() => {
      if (document.documentElement.classList.contains('intro-wait')) window.__waited = true;
    }).observe(document, {attributes: true, subtree: true, attributeFilter: ['class']});"""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    ctx.add_init_script(seen)
    page = ctx.new_page()
    for load in ("first load", "reload"):
        page.goto(base) if load == "first load" else page.reload()
        if not page.evaluate(SCOPE_SHOWN):
            failures.append(f"intro: the scope does not show on the {load}")
        if not page.locator("h1").is_visible():
            failures.append("intro: the headline is not rendered under the intro")
        try:
            page.wait_for_function(f"!({INTRO_ON})", timeout=7000)
        except Exception:
            failures.append(f"intro: still on 7 s after the {load}")
        if page.evaluate("window.__waited"):
            failures.append(f"intro: waited (LOADING) on the {load} of a fast local site")
    replay = page.locator(".replay")
    if not replay.is_visible():
        failures.append("intro: no replay button")
    else:
        # The replay is a demo of the slow path although everything is cached: LOADING after the power-on, the
        # hint from 5.5 s, TRIG'D at 9 s, the page at about 10 s. It is started down the page, by a real click right
        # after a wheel scroll, and ends with the page at the top.
        page.mouse.move(700, 400)
        for _ in range(30):
            page.mouse.wheel(0, 1000)
        box = replay.bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.wheel(0, 200)  # a wheel's scroll still running out
        failures += replay_holds(page, "a click after a scroll")
        page.wait_for_timeout(4000)
        if page.locator(".scope-status").inner_text().upper() != "LOADING":
            failures.append("intro: the replay shows no LOADING after the power-on")
        page.wait_for_timeout(2500)
        if not page.locator(".scope-hint").is_visible():
            failures.append("intro: the replay shows no slow-link hint by 6.5 s")
        try:
            page.wait_for_function("document.documentElement.classList.contains('intro-trig')", timeout=3500)
        except Exception:
            failures.append("intro: the replay does not fire (TRIG'D) by 10 s")
        try:
            page.wait_for_function(f"!({INTRO_ON})", timeout=3500)
        except Exception:
            failures.append("intro: the replay does not clear")
        if page.evaluate("scrollY") != 0:
            failures.append(f"intro: the page comes back from the replay at {page.evaluate('scrollY')}px, not the top")
        # From the keyboard: Enter and Space on the focused button play it too, and it holds.
        for key in ("Enter", "Space"):
            replay.focus()
            page.keyboard.press(key)
            failures += replay_holds(page, key)
            page.keyboard.press("Escape")
            try:
                page.wait_for_function(f"!({INTRO_ON})", timeout=1000)
            except Exception:
                failures.append(f"intro: a key does not skip the replay started by {key}")
    page.goto(base + "#notify")
    if page.evaluate(INTRO_ON):
        failures.append("intro: plays although a #fragment links to a section")
    ctx.close()

    ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="light")
    page = ctx.new_page()
    page.goto(base)
    page.wait_for_timeout(300)
    page.keyboard.press("Escape")
    try:
        page.wait_for_function(f"!({INTRO_ON})", timeout=500)
    except Exception:
        failures.append("intro: a key press did not skip it within 0.5 s")
    ctx.close()

    # A slow hero render: the scope waits (LOADING) and fires (TRIG'D) once the render is in; never received, it
    # says after 5 s how to skip, and a click does.
    for release, why in ((True, "a late hero"), (False, "a hero that never comes")):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        page = ctx.new_page()
        held = []
        page.route("**/b153_hero-*", lambda route: held.append(route))
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)  # the power-on takes 2.8 s
        if not page.evaluate("document.documentElement.classList.contains('intro-wait')"):
            failures.append(f"intro: does not wait for {why}")
        elif page.locator(".scope-status").inner_text().upper() != "LOADING":
            failures.append(f"intro: no LOADING status while waiting for {why}")
        if release:
            for r in held:
                r.continue_()
            try:
                page.wait_for_function("document.documentElement.classList.contains('intro-trig')", timeout=1500)
                if page.locator(".scope-status").inner_text().upper() != "TRIG'D":
                    failures.append("intro: no TRIG'D when it fires")
            except Exception:
                failures.append("intro: does not fire once the hero is in")
        else:
            page.wait_for_timeout(5000)
            if not page.locator(".scope-hint").is_visible():
                failures.append("intro: no slow-link hint after 5 s of waiting")
            page.mouse.click(10, 10)
        try:
            page.wait_for_function(f"!({INTRO_ON})", timeout=3500)
        except Exception:
            failures.append(f"intro: not cleared after {why}")
        for r in held if not release else ():
            r.abort()
        ctx.close()

    # When it plays: on an entry from outside and on a reload, not on the way home from inside the site (the wordmark)
    # nor on back. Each judged at once, before the page's own scripts could clear it.
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    page = ctx.new_page()
    page.goto(base, referer="https://example.com/")
    if not page.evaluate(INTRO_ON):
        failures.append("intro: does not play on an entry from another site")
    page.goto(base + "lab/")
    page.click(".site-header .brand")
    page.wait_for_load_state("domcontentloaded")
    if page.evaluate(INTRO_ON) or page.evaluate(SCOPE_SHOWN):
        failures.append("intro: plays on the way home from inside the site (the wordmark)")
    page.reload()
    if not page.evaluate(INTRO_ON):
        failures.append("intro: does not play on a reload of the home page")
    page.wait_for_function(f"!({INTRO_ON})", timeout=8000)
    page.click(".site-header .nav a[href*='/lab']")
    page.wait_for_load_state("domcontentloaded")
    page.go_back()
    page.wait_for_load_state("domcontentloaded")
    if page.evaluate(INTRO_ON) or page.evaluate(SCOPE_SHOWN):
        failures.append("intro: plays on back to the home page")
    ctx.close()

    # The vector pass: the beam traces the first screen where it lays out, at a phone's and a desktop's width and
    # again after a resize in the middle of it; the headline is written word by word; the page does not move.
    traced = tomllib.loads(Path("config.toml").read_text())["extra"].get("intro_trace", False)
    for w, h in ((390, 844), (1440, 900)) if traced else ():
        ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(base)
        h1 = page.evaluate("JSON.stringify(document.querySelector('h1').getBoundingClientRect())")
        try:
            page.wait_for_function("document.documentElement.classList.contains('intro-draw')", timeout=8000)
        except Exception:
            failures.append(f"intro {w}px: no vector pass")
            ctx.close()
            continue
        sizes = [(w, h)] + ([(1200, 800)] if w == 1440 else [])
        for vw, vh in sizes:
            if (vw, vh) != (w, h):
                page.set_viewport_size({"width": vw, "height": vh})
                page.wait_for_timeout(150)
            kinds, bad = page.evaluate(TRACES_MATCH)
            failures += [f"intro {vw}px: a stroke off its element: {b}" for b in bad[:5]]
            missing = [k for k in ("edge", "box", "under", "text") if not kinds.get(k)]
            if missing:
                failures.append(f"intro {vw}px: the vector pass draws no {', '.join(missing)}")
            if kinds.get("text") != page.evaluate("document.querySelector('h1').textContent.trim().split(/\\s+/).length"):
                failures.append(f"intro {vw}px: the headline is not written word by word ({kinds.get('text')} words)")
        try:
            page.wait_for_function(f"!({INTRO_ON})", timeout=3000)
        except Exception:
            failures.append(f"intro {w}px: does not clear after the vector pass")
        if len(sizes) == 1 and page.evaluate("JSON.stringify(document.querySelector('h1').getBoundingClientRect())") != h1:
            failures.append(f"intro {w}px: the headline moved under the intro")
        ctx.close()

    for opts, why in (({"reduced_motion": "reduce"}, "reduced motion"), ({"java_script_enabled": False}, "no JS")):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, **opts)
        page = ctx.new_page()
        page.goto(base)
        if page.locator(".scope").is_visible():
            failures.append(f"intro: shows under {why}")
        if page.locator(".replay").is_visible():
            failures.append(f"intro: the replay button shows under {why}")
        ctx.close()
    return failures


FRAME = "document.querySelector('#products .card:nth-child(2) .fig-frame')"


def check_placeholders(browser, base):
    """A picture on its way shows as a scope screen in its own box, then fades in; the box never changes size."""
    failures = []
    for motion in ("no-preference", "reduce"):
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="light", reduced_motion=motion)
        page = ctx.new_page()
        held = []
        page.route("**/b200_hero-*", lambda route: held.append(route))
        page.goto(base)
        page.wait_for_function(f"!({INTRO_ON})")
        if page.evaluate("document.querySelector('.hero-fig .fig-frame').matches('.img-wait, .img-in')"):
            failures.append(f"placeholder ({motion}): the hero got one, so its largest paint waits for the fade")
        page.evaluate(f"{FRAME}.scrollIntoView()")
        page.wait_for_timeout(300)
        before = page.evaluate(f"""(() => {{ const f = {FRAME}, i = f.querySelector('img');
          return [f.className, getComputedStyle(f, '::before').content, getComputedStyle(f, '::after').animationName,
                  getComputedStyle(i).opacity, i.getBoundingClientRect().height]; }})()""")
        if "img-wait" not in before[0] or before[1] == "none" or before[3] != "0":
            failures.append(f"placeholder ({motion}): a picture on its way shows no scope screen: {before[:4]}")
        sweep = "img-sweep" if motion == "no-preference" else "none"
        if before[2] != sweep:
            failures.append(f"placeholder ({motion}): the sweep is {before[2]}, expected {sweep}")
        for r in held:
            r.continue_()
        try:
            page.wait_for_function(f"!{FRAME}.classList.contains('img-wait')", timeout=3000)
            page.wait_for_timeout(600)
        except Exception:
            failures.append(f"placeholder ({motion}): still waiting after the picture came")
        after = page.evaluate(f"""(() => {{ const i = {FRAME}.querySelector('img');
          return [getComputedStyle(i).opacity, i.getBoundingClientRect().height]; }})()""")
        if after[0] != "1":
            failures.append(f"placeholder ({motion}): the picture did not fade in (opacity {after[0]})")
        if abs(after[1] - before[4]) > 0.5:
            failures.append(f"placeholder ({motion}): the box changed height {before[4]} -> {after[1]}")
        ctx.close()
    return failures


def image_size(data):
    """Pixel width and height from a PNG or JPEG's own header, without a dependency."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data) and data[i] == 0xFF:
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def check_og_image(browser, base):
    """Every page: og:image is an absolute URL to a real 1200x627 file, matched by og:image:width/height and a
    non-empty og:image:alt, and twitter:card is summary_large_image with twitter:image the same URL (AGENTS.md
    "Link previews"): so LinkedIn, Facebook, X and messengers show it instead of cropping a render themselves."""
    failures = []
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = ctx.new_page()
    cache = {}
    for path in PAGES[:-1]:
        page.goto(base + path)
        image, mw, mh, alt, card, timg = page.evaluate(OG_META)
        where = path or "/"
        if not image or not image.startswith("http"):
            failures.append(f"{where}: og:image is {image!r}, expected an absolute URL")
            continue
        if card != "summary_large_image" or timg != image:
            failures.append(f"{where}: twitter:card/image is {card!r}/{timg!r}, expected summary_large_image/{image!r}")
        if not alt:
            failures.append(f"{where}: og:image:alt is empty")
        if image not in cache:
            try:
                with urllib.request.urlopen(image, timeout=10) as r:
                    cache[image] = (r.status, r.read())
            except urllib.error.HTTPError as e:
                cache[image] = (e.code, b"")
        status, data = cache[image]
        if status != 200:
            failures.append(f"{where}: og:image {image} answers {status}")
            continue
        size = image_size(data)
        if size is None:
            failures.append(f"{where}: og:image {image} is not a PNG or JPEG")
            continue
        if (mw, mh) != (str(size[0]), str(size[1])):
            failures.append(f"{where}: og:image:width/height is {mw}/{mh}, the file is {size[0]}x{size[1]}")
        if size != (1200, 627):
            failures.append(f"{where}: og:image {image} is {size[0]}x{size[1]}, expected 1200x627")
    ctx.close()
    return failures


def check_table_contrast(browser, base):
    """Every table cell's text is 4.5:1 on its cell, on every page, in dark and in light (the stored choice)."""
    failures = []
    for scheme in ("dark", "light"):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        if scheme == "light":
            ctx.add_init_script("try { localStorage.setItem('theme', 'light') } catch (e) {}")
        page = ctx.new_page()
        cells = 0
        for path in PAGES[:-1]:
            page.goto(base + path)
            n, bad = page.evaluate(TABLE_CONTRAST)
            cells += n
            failures += [f"{path or '/'} {scheme}: table text under 4.5:1: {b}" for b in bad]
        print(f"table contrast, {scheme}: {cells} texts in table cells")
        ctx.close()
    return failures

# No mail address is written into the site (vh.mail puts it together in the browser).
ADDRESS = b"@vhrd.tech"
# (a link in a signup form's message is hidden until that message shows, so it counts as shown)
MAIL_LINKS = """() => [...document.querySelectorAll('a[data-mail]')].map((a) =>
  [a.getAttribute('href'), a.textContent, a.hasAttribute('data-keep'),
   a.getClientRects().length > 0 || !!a.closest('.notify-msg')])"""
# Mail links each page must have, as the script makes them.
MAIL_WANTED = {
    "": ["mailto:donguru@vhrd.tech?subject=Donguru%20launch", "mailto:contact@vhrd.tech"],
    "donguru/": ["mailto:donguru@vhrd.tech?subject=Donguru%20launch"],
    "services/": ["mailto:projects@vhrd.tech?subject=Project"],
    "about/": ["mailto:contact@vhrd.tech"],
}


def check_mail(browser, base, out):
    """No address in the built files; mail links work with JavaScript and read as text without it."""
    failures = []
    if out is not None:
        for f in sorted(out.rglob("*")):
            if f.suffix in TEXT and ADDRESS in f.read_bytes():
                failures.append(f"mail: {f.relative_to(out)} has an address in it ({ADDRESS.decode()})")
    for js in (True, False):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, java_script_enabled=js,
                                  reduced_motion="reduce")
        page = ctx.new_page()
        for path in PAGES[:-1]:
            page.goto(base + path)
            links = page.evaluate(MAIL_LINKS)
            if not links:
                failures.append(f"mail: {path or '/'} has no mail link (the footer has one)")
            for href, text, keep, shown in links:
                if js:
                    if not (href or "").startswith("mailto:") or (not keep and text != href[7:].split("?")[0]):
                        failures.append(f"mail: {path or '/'}: {text!r} is {href!r} with JavaScript")
                    if not shown:
                        failures.append(f"mail: {path or '/'}: {text!r} does not show with JavaScript")
                elif href is not None or (keep and shown) or (not keep and not text.endswith(" at vhrd.tech")):
                    failures.append(f"mail: {path or '/'}: {text!r} without JavaScript: href {href!r}, shown {shown}")
            if js:
                hrefs = [h for h, *_ in links]
                failures += [f"mail: {path or '/'} has no {w}" for w in MAIL_WANTED.get(path, []) if w not in hrefs]
        ctx.close()
    return failures


class Hrefs(html.parser.HTMLParser):
    """The href of every <a> and <link>, the src of every <img>, <source> srcset and <script>."""

    def __init__(self):
        super().__init__()
        self.links, self.files = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "link" and a.get("href"):
            self.files.append(a["href"])
        elif tag in ("img", "script") and a.get("src"):
            self.files.append(a["src"])
        for key in ("srcset", "imagesrcset"):
            for part in (a.get(key) or "").split(","):
                if part.strip():
                    self.files.append(part.split()[0])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(opener, url, method="GET"):
    """Status and body, without following a redirect."""
    try:
        with opener.open(urllib.request.Request(url, method=method), timeout=20) as r:
            return r.status, r.read() if method == "GET" else b""
    except urllib.error.HTTPError as e:
        return e.code, b""


def check_css(out):
    """Every page in the local build inlines a part's styles exactly when it shows that part, and the CSS left for
    every page stays under SHARED_CSS_KB."""
    root = Path(__file__).resolve().parent.parent
    parts = {name: (root / f"static/css/{name}.css").read_text() for name in CSS_PARTS}
    own = (root / "static/css/donguru.css").read_text()
    failures = []
    for f in sorted(out.rglob("*.html")):
        rel = f.relative_to(out)
        page = "/" + (str(rel.parent).strip(".") + "/" if f.name == "index.html" else str(rel)).lstrip("/")
        html_ = f.read_text()
        style = "".join(re.findall(r"<style>(.*?)</style>", html_, flags=re.S))
        classes = " ".join(re.findall(r'class="([^"]*)"', html_[html_.find("<body"):]))
        shared = len(style)
        for name, css in parts.items():
            inlined = css.strip() in style
            shown = re.search(rf"(?<![\w-]){CSS_PARTS[name]}(?![\w-])", classes) is not None
            if inlined and not shown:
                failures.append(f"{page}: inlines {name}.css but has no .{CSS_PARTS[name]}")
            if shown and not inlined:
                failures.append(f"{page}: has .{CSS_PARTS[name]} but does not inline {name}.css (extra.styles)")
            shared -= len(css.strip()) if inlined else 0
        shared -= len(own.strip()) if own.strip() in style else 0
        if shared > SHARED_CSS_KB * 1024:
            failures.append(f"{page}: {shared / 1024:.0f} KB of CSS every page carries, budget {SHARED_CSS_KB} KB")
    return failures


def check_links(base):
    """Walk the site from the front page by its links: every internal href ends in '/' when it names a page and
    answers 200 without a redirect, and every page of the site map is reached (no orphan pages)."""
    failures = []
    opener = urllib.request.build_opener(NoRedirect)
    host, root = urlsplit(base).netloc, urlsplit(base).path
    seen, files, todo = {base}, set(), [base]
    mail_only = [base + p for p in MAIL_ONLY]
    for url in mail_only:
        status, body = fetch(opener, url)
        if status != 200:
            failures.append(f"links: {urlsplit(url).path}: HTTP {status}, expected 200")
        if b'<meta name="robots" content="noindex' not in body:
            failures.append(f"links: {urlsplit(url).path} has no noindex")
    seen.update(mail_only)
    todo += mail_only
    while todo:
        page = todo.pop()
        status, body = fetch(opener, page)
        if status != 200:
            continue  # reported where it was linked from
        p = Hrefs()
        p.feed(body.decode("utf-8", "replace"))
        where = urlsplit(page).path[len(root):] or "/"
        if ADDRESS in body:
            failures.append(f"mail: {where} has an address in its HTML ({ADDRESS.decode()})")
        failures += mentions.problems(page, body.decode("utf-8", "replace"), base)
        for href, is_page in [(h, True) for h in p.links] + [(h, False) for h in p.files]:
            u = urlsplit(urljoin(page, href))
            if u.scheme not in ("http", "https") or u.netloc != host:
                continue
            if root != "/" and u.path == root.rstrip("/"):
                failures.append(f"links: {where} links {href}, without the trailing '/' (a redirect)")
                continue
            if not u.path.startswith(root):
                continue
            rel = u.path[len(root):]
            target = f"{u.scheme}://{u.netloc}{u.path}"
            named_page = is_page and "." not in rel.rsplit("/", 1)[-1]
            if named_page and not u.path.endswith("/"):
                failures.append(f"links: {where} links {href}, without the trailing '/' (a redirect)")
            if target in seen or target in files:
                continue
            code, _ = fetch(opener, target, "GET" if named_page else "HEAD")
            if code != 200:
                failures.append(f"links: {where} links {href}: HTTP {code}, expected 200 without a redirect")
            if named_page:
                seen.add(target)
                if code == 200:
                    todo.append(target)
            else:
                files.add(target)
    status, body = fetch(opener, base + "sitemap.xml")
    pages = [m.split("</loc>")[0] for m in body.decode().split("<loc>")[1:]]
    if status != 200 or not pages:
        failures.append(f"links: no site map (HTTP {status})")
    for url in pages:
        if url in mail_only:
            failures.append(f"links: {urlsplit(url).path} is in the site map, but only our mail links to it")
        elif url not in seen:
            failures.append(f"links: {urlsplit(url).path} is in the site map but no link leads there from the front page")
    print(f"links: {len(seen) - len(mail_only)} pages and {len(files)} files reached from the front page, "
          f"{len(mail_only)} only from our mail, {len(pages)} in the site map")
    return failures


# The traces (site.css "Drawn as you scroll"): per trace and the bus, its draw progress as the page shows it (from
# the computed clip-path: the track's bottom inset, the bus's right one) and whether it starts below the fold.
PROGRESS = """() => [...document.querySelectorAll('.trace, .bus')].map((t) => {
  const bus = t.classList.contains('bus'), w = t.querySelector(bus ? '.bus-lines' : '.trace-wire');
  const c = getComputedStyle(w).clipPath, m = c.match(/^inset\\(([^)]*)\\)$/);
  if (c === 'none') return [1, t.getBoundingClientRect().top >= innerHeight];
  if (!m) return [null, c];
  const v = m[1].split(' '), side = [v[0], v[1] ?? v[0], v[2] ?? v[0], v[3] ?? v[1] ?? v[0]][bus ? 1 : 2];
  return [1 - (side.endsWith('%') ? parseFloat(side) / 100 : 0), t.getBoundingClientRect().top >= innerHeight];
})"""
FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"
# Waits until the scroll has come to rest (three frames without a change), then one frame more for the traces.
SETTLED = """() => new Promise((done) => { let last = -1, same = 0; const f = () => {
  same = scrollY === last ? same + 1 : 0; last = scrollY; same >= 3 ? requestAnimationFrame(done) : requestAnimationFrame(f); };
  requestAnimationFrame(f); })"""
# Screens the traces are checked on: two phones and three desktops (two of them 1920 and 2560 wide).
DRAW_SIZES = [("Pixel 7", None), ("iPhone 14", None), ("desktop", (1440, 900)), ("desktop", (1920, 1080)),
              ("desktop", (2560, 1440))]


def browsers(p, chromium):
    """Chromium and Firefox (Playwright's own build: `uv run --with playwright playwright install firefox`)."""
    yield "chromium", chromium
    firefox = p.firefox.launch()
    yield "firefox", firefox
    firefox.close()


def check_draw(name, p, browser, base):
    """The traces follow the scroll, both ways: below the fold they start undrawn; at the page's end every one is drawn;
    near the end the bus's progress rises as the page scrolls down to it, reaches 1 exactly at the end, falls again
    when it scrolls back up and is the same at the same place either way. Phones scroll by script (Playwright has no
    swipe), desktops with the mouse wheel."""
    failures = []
    for device, size in DRAW_SIZES:
        if device == "desktop":
            opts = {"viewport": {"width": size[0], "height": size[1]}}
            label = f"{size[0]}x{size[1]}"
        else:
            opts = dict(p.devices[device])
            if name == "firefox":  # no mobile emulation in Firefox: the phone's screen size only
                opts = {"viewport": opts["viewport"], "device_scale_factor": opts["device_scale_factor"]}
            label = device
        ctx = browser.new_context(**opts, reduced_motion="no-preference")
        page = ctx.new_page()
        where = lambda path: f"draw {name} {label}: {path or '/'}"  # noqa: E731

        def scroll(dy):
            if device == "desktop":
                page.mouse.move(4, size[1] / 2)  # the margin: no scrolling box under the pointer
                page.mouse.wheel(0, dy)
            else:
                page.evaluate(f"scrollBy(0, {dy})")
            page.evaluate(SETTLED)

        for path in PAGES[:-1]:
            page.goto(base + path + "#main")  # a fragment: no intro on the front page
            page.evaluate("scrollTo(0, 0)")
            page.evaluate(SETTLED)
            start = page.evaluate(PROGRESS)
            if not start or any(v is None for v, _ in start):
                failures.append(f"{where(path)}: traces without a draw progress: {start}")
                continue
            if any(v > 0.001 for v, below in start if below):
                failures.append(f"{where(path)}: a trace below the fold is drawn before it is seen: {start}")
            for _ in range(400):
                if page.evaluate("scrollY + innerHeight >= document.documentElement.scrollHeight - 1"):
                    break
                scroll(400)
            end = [v for v, _ in page.evaluate(PROGRESS)]
            if any(v < 0.999 for v in end):
                failures.append(f"{where(path)}: not every trace is drawn at the page's end: {end}")
            room = page.evaluate("scrollY")
            if room < 300:
                continue  # too short to scroll back and forth
            bus = lambda: (page.evaluate("scrollY"), page.evaluate(PROGRESS)[-1][0])  # noqa: E731
            up = [bus()]
            for _ in range(6):
                scroll(-100)
                up.append(bus())
            down = [up[-1]]
            for _ in range(6):
                scroll(100)
                down.append(bus())
            ups = [v for _, v in up]
            if not any(v < 0.999 for v in ups[1:]):
                failures.append(f"{where(path)}: the bus stays drawn when the page scrolls back up: {up}")
            elif ups[1] >= 0.999:
                failures.append(f"{where(path)}: the bus is drawn before the page's end: {up[:2]}")
            if any(b > a + 0.001 for a, b in zip(ups, ups[1:])):
                failures.append(f"{where(path)}: the bus draws in while the page scrolls up: {up}")
            back = dict(down)
            for y, v in up:
                if y in back and abs(back[y] - v) > 0.01:
                    failures.append(f"{where(path)}: the bus is {v:.3f} at {y} going up, {back[y]:.3f} coming down")
                    break
            if down[-1][1] < 0.999:
                failures.append(f"{where(path)}: the bus is not drawn back at the page's end: {down}")
        ctx.close()
    return failures


def check_clicks(name, browser, base):
    """On /lab, at desktop width: the first click on each nav link, the wordmark, a footer link and the GitHub link
    navigates (a sanity check that nothing of the site's sits over them or swallows the click)."""
    failures = []
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.route("https://github.com/**", lambda r: r.fulfill(status=200, body="github", content_type="text/html"))
    page = ctx.new_page()
    targets = [f".site-header .nav a >> nth={i}" for i in range(page.goto(base + "lab/") and page.locator(".site-header .nav a").count())]
    targets += [".site-header .brand", ".site-footer a[href*='/about/']", ".site-footer a[href^='https://github.com']"]
    for sel in targets:
        page.goto(base + "lab/")
        link = page.locator(sel)
        href = link.get_attribute("href")
        link.scroll_into_view_if_needed()
        page.evaluate(FRAMES)
        box = link.bounding_box()
        try:
            with page.expect_navigation(timeout=5000):
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        except Exception:
            failures.append(f"click {name}: on /lab/ the first click on {href} did not navigate")
    ctx.close()
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?")
    ap.add_argument("--chromium", default=shutil.which("chromium") or shutil.which("chromium-browser"))
    ap.add_argument("--shots")
    ap.add_argument("--only", choices=["draw"], help="only the traces and the first clicks, in Chromium and Firefox")
    a = ap.parse_args()
    base, out = (a.base, None) if a.base else serve_build()
    base = base.rstrip("/") + "/"
    if a.only:
        failures = []
        with sync_playwright() as p:
            for name, b in browsers(p, p.chromium.launch(executable_path=a.chromium)):
                failures += check_draw(name, p, b, base) + check_clicks(name, b, base)
        for f in failures:
            print("FAIL", f)
        print(f"{len(failures)} failures" if failures else "all checks passed")
        sys.exit(1 if failures else 0)
    failures = check_links(base)
    if out is not None:
        failures += check_css(out)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=a.chromium)
        for scheme in ("dark", "light"):
            for name, w in WIDTHS.items():
                ctx = browser.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme,
                                          reduced_motion="reduce")
                if scheme == "light":  # dark is the default; light is the visitor's stored choice
                    ctx.add_init_script("try { localStorage.setItem('theme', 'light') } catch (e) {}")
                page = ctx.new_page()
                errors = []
                page.on("console", lambda m: m.type == "error" and errors.append(m.text))
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("requestfailed", lambda r: errors.append(f"failed {r.url}"))
                for path in PAGES:
                    errors.clear()
                    resp = page.goto(base + path)
                    status = resp.status if resp else 0
                    want = 404 if path == "no-such-page/" else 200
                    if status != want:
                        failures.append(f"{path or '/'}: HTTP {status}, expected {want}")
                    sideways = page.evaluate("document.documentElement.scrollWidth - innerWidth")
                    if sideways > 0:
                        failures.append(f"{path or '/'} {name} {scheme}: scrolls sideways by {sideways}px")
                    page.wait_for_load_state("load")
                    if name == "desktop" and scheme == "dark":
                        figs = page.evaluate(FIG_NUMBERS)
                        if figs != list(range(1, len(figs) + 1)):
                            failures.append(f"{path or '/'}: figures numbered {figs}, expected 1 to {len(figs)} in order")
                    for src in page.evaluate(CROPPED):
                        failures.append(f"{path or '/'} {name} {scheme}: image cropped: {src}")
                    if any(abs(d) > 0.5 for d in page.evaluate(VIA_OFFSETS)):
                        failures.append(f"{path or '/'} {name} {scheme}: a stack via is off its track's centre")
                    for e in errors:
                        # the missing page's own 404 is expected; the 404 page is the server's (static hosting)
                        if want == 404 and "404" in e:
                            continue
                        failures.append(f"{path or '/'} {name} {scheme}: console: {e}")
                if a.shots and scheme == "dark" and name != "tablet":
                    page.goto(base)
                    Path(a.shots).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=f"{a.shots}/home-{scheme}-{w}.png", full_page=True)
                ctx.close()

        # First view on a phone: the budget, and images that say what they show and how big they are
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(base)
        page.wait_for_load_state("networkidle")
        kb = wire_bytes(page.evaluate(FETCHED), base, out) / 1024
        print(f"first view on a phone: {kb:.0f} KB of {BUDGET_KB} KB")
        if kb > BUDGET_KB:
            failures.append(f"first view: {kb:.0f} KB, budget {BUDGET_KB} KB")
        for src in page.evaluate(IMAGES_WITHOUT):
            failures.append(f"image without alt, width or height: {src}")
        ctx.close()

        failures += check_code_fits(browser, base)
        failures += check_repos(browser, base)
        failures += check_intro(browser, base)
        failures += check_placeholders(browser, base)
        failures += check_table_contrast(browser, base)
        failures += check_og_image(browser, base)
        failures += check_mail(browser, base, out)
        if out is not None:
            failures += check_notify(browser, base)
            failures += check_notify_links(browser, base)

        # Interactions, on a desktop page in a browser that prefers light: dark all the same on a first visit (the
        # default, from the HTML, so no light flash), the toggle switches to light and remembers it, and back to dark
        # clears the choice.
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
        page = ctx.new_page()
        page.goto(base)
        page.wait_for_function("!document.documentElement.classList.contains('intro')")
        theme = lambda: page.evaluate(  # noqa: E731
            "getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
        if theme() != "#0f0f10":
            failures.append(f"first visit, light-preferring browser: --bg is {theme()}, expected dark")
        if page.evaluate("getComputedStyle(document.documentElement).colorScheme") != "dark":
            failures.append("first visit: color-scheme is not dark (form controls and scrollbars)")
        if 'data-theme="dark"' not in (page.request.get(base).text())[:2000]:
            failures.append("first visit: the HTML does not start dark (a light flash before the scripts)")
        page.click(".theme-toggle")
        if theme() != "#f6f6f6":
            failures.append(f"toggle: --bg is {theme()} after one click, expected light")
        page.reload()
        if theme() != "#f6f6f6":
            failures.append("toggle: the light choice did not survive a reload")
        page.click(".theme-toggle")
        page.reload()
        if theme() != "#0f0f10" or page.evaluate("localStorage.getItem('theme')") is not None:
            failures.append("toggle: back to dark should clear the stored choice")

        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.className") != "skip":
            failures.append("keyboard: the skip link is not the first tab stop")
        page.goto(base + "donguru/")  # the code tabs: the front page has none since FIG. 5 went
        tabs = page.locator('[role="tab"]')
        if tabs.count() >= 2:
            tabs.nth(0).focus()
            page.keyboard.press("ArrowRight")
            if tabs.nth(1).get_attribute("aria-selected") != "true":
                failures.append("tabs: ArrowRight did not select the next tab")
            if not page.locator('[role="tabpanel"]').nth(0).is_hidden():
                failures.append("tabs: the first panel still shows after switching")
        else:
            failures.append("tabs: no code tabs on /donguru")
        ctx.close()
        browser.close()

    for f in failures:
        print("FAIL", f)
    print(f"{len(failures)} failures" if failures else "all checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
