# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.47"]
# ///
"""Drive a built site in headless Chromium the way a visitor would and fail on what the web checklist names.

Usage: uv run tools/check_pages.py [BASE_URL] [--chromium PATH] [--shots DIR]

Without BASE_URL it builds the site with zola into target/check for a local port and serves it from there (what
`just check-browser` does); with one it checks that site as deployed (`just check-preview`).

For every page in the site map, at phone (390), tablet (820) and desktop (1440) widths, in dark and light:
no console errors or failed requests, no sideways scroll. On the front page: the theme toggle switches and the
choice survives a reload, the code tabs work by keyboard (arrow keys), the skip link is the first tab stop.
First-view budget: what a phone loads for the front page before scrolling (HTML, CSS, script, fonts, images)
stays under BUDGET_KB as sent over the wire: text gzipped (as the local build would be served by a server that
compresses), fonts and images as they are; against a deployed site, the transfer sizes the browser saw. Every image
has alt text and its width and height.
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
    def log_message(self, *args):
        pass


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

        # Interactions, on a desktop page in the dark scheme
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(base)
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
