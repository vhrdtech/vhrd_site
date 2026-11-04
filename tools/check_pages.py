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
A crate card marked `fits` in data/stack.toml shows its code without a sideways scroll from 320 px up.
On the front page: the theme toggle switches and the choice survives a reload, the code tabs work by keyboard
(arrow keys), the skip link is the first tab stop.
First-view budget: what a phone loads for the front page before scrolling (HTML, CSS, script, fonts, images)
stays under BUDGET_KB as sent over the wire: text gzipped (as the local build would be served by a server that
compresses), fonts and images as they are; against a deployed site, the transfer sizes the browser saw. Every image
has alt text and its width and height.
The front page's intro: on every load it shows and clears by itself without waiting on a fast site, waits (LOADING)
for a late hero render and fires (TRIG'D), says after 5 s how to skip and a click skips it, a key skips it, the
replay button plays it again; never with a #fragment, under reduced motion or without JavaScript.
A picture on its way shows as a small scope screen in its box and fades in when it comes, without a size change.
With --shots, writes a full-page screenshot per width in dark (traces shown drawn: reduced motion).
"""

import argparse
import functools
import gzip
import http.server
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

PAGES = ["", "donguru/", "report/", "can/", "software/", "open-source/", "lab/", "services/", "about/",
         "blog/", "shop/", "no-such-page/"]
WIDTHS = {"phone": 390, "tablet": 820, "desktop": 1440}
BUDGET_KB = 200

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
IMAGES_WITHOUT = """() => [...document.images]
  .filter((i) => !i.hasAttribute("alt") || !i.getAttribute("width") || !i.getAttribute("height"))
  .map((i) => i.currentSrc || i.src)"""


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
    subprocess.run(["zola", "build", "--base-url", base, "--output-dir", str(out), "--force"], cwd=root,
                   check=True, stdout=subprocess.DEVNULL)
    handler = functools.partial(Quiet, directory=str(out))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return base, out


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


def check_code_fits(browser, base):
    """The crate cards marked `fits` show their code without a sideways scroll, from a 320px phone up."""
    failures = []
    for w in (320, 360, 390, 430, 820, 960, 1440):
        ctx = browser.new_context(viewport={"width": w, "height": 900}, reduced_motion="reduce")
        page = ctx.new_page()
        for path in ("", "open-source/"):
            page.goto(base + path)
            for crate, px in page.evaluate(CODE_OVERFLOW):
                if px > 0:
                    failures.append(f"{path or '/'} {w}px: the {crate} card's code scrolls sideways by {px}px")
        ctx.close()
    return failures


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
            page.wait_for_function(f"!({INTRO_ON})", timeout=3000)
        except Exception:
            failures.append(f"intro: still on 3 s after the {load}")
        if page.evaluate("window.__waited"):
            failures.append(f"intro: waited (LOADING) on the {load} of a fast local site")
    replay = page.locator(".replay")
    if not replay.is_visible():
        failures.append("intro: no replay button")
    else:
        replay.click()
        if not page.evaluate(INTRO_ON):
            failures.append("intro: the replay button does not play it")
        try:
            page.wait_for_function(f"!({INTRO_ON})", timeout=3000)
        except Exception:
            failures.append("intro: the replay does not clear")
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
        page.wait_for_timeout(2000)
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
            page.wait_for_function(f"!({INTRO_ON})", timeout=1500)
        except Exception:
            failures.append(f"intro: not cleared after {why}")
        for r in held if not release else ():
            r.abort()
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?")
    ap.add_argument("--chromium", default=shutil.which("chromium") or shutil.which("chromium-browser"))
    ap.add_argument("--shots")
    a = ap.parse_args()
    base, out = (a.base, None) if a.base else serve_build()
    base = base.rstrip("/") + "/"
    failures = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=a.chromium)
        for scheme in ("dark", "light"):
            for name, w in WIDTHS.items():
                ctx = browser.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme,
                                          reduced_motion="reduce")
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
        failures += check_intro(browser, base)
        failures += check_placeholders(browser, base)

        # Interactions, on a desktop page in the dark scheme (the intro skipped by the first click)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(base)
        page.wait_for_function("!document.documentElement.classList.contains('intro')")
        theme = lambda: page.evaluate(  # noqa: E731
            "getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
        if theme() != "#0f0f10":
            failures.append(f"dark scheme: --bg is {theme()}")
        page.click(".theme-toggle")
        if theme() != "#f6f6f6":
            failures.append(f"toggle: --bg is {theme()} after one click, expected light")
        page.reload()
        if theme() != "#f6f6f6":
            failures.append("toggle: the light choice did not survive a reload")
        page.click(".theme-toggle")
        page.reload()
        if theme() != "#0f0f10" or page.evaluate("localStorage.getItem('theme')") is not None:
            failures.append("toggle: back to the system theme should clear the stored choice")

        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.className") != "skip":
            failures.append("keyboard: the skip link is not the first tab stop")
        tabs = page.locator('[role="tab"]')
        if tabs.count() >= 2:
            tabs.nth(0).focus()
            page.keyboard.press("ArrowRight")
            if tabs.nth(1).get_attribute("aria-selected") != "true":
                failures.append("tabs: ArrowRight did not select the next tab")
            if not page.locator('[role="tabpanel"]').nth(0).is_hidden():
                failures.append("tabs: the first panel still shows after switching")
        else:
            failures.append("tabs: no code tabs on the front page")
        ctx.close()
        browser.close()

    for f in failures:
        print("FAIL", f)
    print(f"{len(failures)} failures" if failures else "all checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
