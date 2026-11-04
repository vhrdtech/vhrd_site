# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.47"]
# ///
"""Drive a built site in headless Chromium the way a visitor would and fail on what the web checklist names.

Usage: uv run tools/check_pages.py BASE_URL [--chromium PATH] [--shots DIR]

For every page in the site map, at phone (390), tablet (820) and desktop (1440) widths, in dark and light:
no console errors or failed requests, no sideways scroll. On the front page: the theme toggle switches and the
choice survives a reload, the code tabs work by keyboard (arrow keys), the skip link is the first tab stop.
With --shots, writes a full-page screenshot per width in dark (traces shown drawn: reduced motion).
"""

import argparse
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ["", "donguru/", "report/", "can/", "software/", "open-source/", "lab/", "services/", "about/",
         "blog/", "shop/", "no-such-page/"]
WIDTHS = {"phone": 390, "tablet": 820, "desktop": 1440}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--chromium", default=shutil.which("chromium") or shutil.which("chromium-browser"))
    ap.add_argument("--shots")
    a = ap.parse_args()
    base = a.base.rstrip("/") + "/"
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
                    if want == 404:
                        # the server's own 404 may not be ours (python's http.server); only ours is checked
                        errors = [e for e in errors if "404" not in e]
                    sideways = page.evaluate("document.documentElement.scrollWidth - innerWidth")
                    if sideways > 0:
                        failures.append(f"{path or '/'} {name} {scheme}: scrolls sideways by {sideways}px")
                    for e in errors:
                        failures.append(f"{path or '/'} {name} {scheme}: console: {e}")
                if a.shots and scheme == "dark" and name != "tablet":
                    page.goto(base)
                    Path(a.shots).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=f"{a.shots}/home-{scheme}-{w}.png", full_page=True)
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
