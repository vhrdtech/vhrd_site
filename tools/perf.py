# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.47"]
# ///
"""Measure the front page's first screen on a slow phone, the way Lighthouse's mobile run does.

Usage: uv run tools/perf.py [BASE_URL] [--chromium PATH] [--runs N] [--path PATH]

Without BASE_URL it builds the site into target/check and serves it locally (as tools/check_pages.py does). The page
is loaded at 390 x 844 under Lighthouse's mobile throttling: 150 ms round trip, 1.6 Mbit/s down, 750 kbit/s up, the
CPU four times slower. Each run is a fresh browser profile (an empty cache, a first visit). Printed, the median of
the runs: requests and bytes for the first screen (no scrolling), first contentful paint, largest contentful paint
and layout shift, when the front page's intro cleared, and the largest element.
"""

import argparse
import shutil
import statistics

from playwright.sync_api import sync_playwright

from check_pages import FETCHED, serve_build, wire_bytes

THROTTLE = {"offline": False, "latency": 150, "downloadThroughput": 1.6e6 / 8, "uploadThroughput": 750e3 / 8}
CPU_SLOWDOWN = 4

# Paint and layout-shift entries the page buffered; read after the load settles.
VITALS = """() => new Promise((done) => {
  const out = {fcp: 0, lcp: 0, cls: 0, lcpEl: ""};
  const fcp = performance.getEntriesByName("first-contentful-paint")[0];
  if (fcp) out.fcp = fcp.startTime;
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) { out.lcp = e.startTime; out.lcpEl = e.element ? e.element.outerHTML.slice(0, 80) : e.url; }
  }).observe({type: "largest-contentful-paint", buffered: true});
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) if (!e.hadRecentInput) out.cls += e.value;
  }).observe({type: "layout-shift", buffered: true});
  setTimeout(() => done(out), 100);
})"""


def run_once(browser, url, base, out):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
                              has_touch=True, color_scheme="dark")
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", THROTTLE)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": CPU_SLOWDOWN})
    # When the front page's intro clears (html.intro removed); 0 when it never played.
    page.add_init_script("""window.__introEnd = 0; new MutationObserver((m, o) => {
      const c = document.documentElement && document.documentElement.classList;
      if (!c) return;
      if (c.contains("intro")) window.__introSeen = true;
      else if (window.__introSeen) { window.__introEnd = performance.now(); o.disconnect(); }
    }).observe(document, {attributes: true, subtree: true, attributeFilter: ["class"]});""")
    page.goto(url, wait_until="load")
    page.wait_for_load_state("networkidle")
    page.wait_for_function("!document.documentElement.classList.contains('intro')", timeout=10000)
    page.wait_for_timeout(500)
    fetched = page.evaluate(FETCHED)
    intro = page.evaluate("window.__introEnd")
    vitals = page.evaluate(VITALS)
    ctx.close()
    return {"requests": len(fetched), "kb": wire_bytes(fetched, base, out) / 1024, "intro": intro, **vitals,
            "files": fetched}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?")
    ap.add_argument("--chromium", default=shutil.which("chromium") or shutil.which("chromium-browser"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--path", default="", help="page under the base, e.g. donguru/")
    ap.add_argument("--list", action="store_true", help="also list what the first run fetched")
    a = ap.parse_args()
    base, out = (a.base, None) if a.base else serve_build()
    base = base.rstrip("/") + "/"

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=a.chromium)
        runs = [run_once(browser, base + a.path, base, out) for _ in range(a.runs)]
        browser.close()

    med = lambda k: statistics.median(r[k] for r in runs)  # noqa: E731
    print(f"first screen on a slow phone (390 px, slow 4G, CPU / {CPU_SLOWDOWN}), median of {len(runs)}:")
    print(f"  requests {med('requests'):.0f}, {med('kb'):.0f} KB over the wire")
    print(f"  FCP {med('fcp'):.0f} ms, LCP {med('lcp'):.0f} ms, CLS {med('cls'):.3f}")
    print(f"  intro cleared at {med('intro'):.0f} ms (0: it did not play)")
    print(f"  largest element: {runs[-1]['lcpEl']}")
    if a.list:
        for url, size, _ in runs[0]["files"]:
            print(f"  {size / 1024:7.1f} KB  {url[len(base):] or '/'}")


if __name__ == "__main__":
    main()
