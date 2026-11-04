"""Check a live build before it is uploaded, and the site once it is.

Usage: python3 tools/check_live.py built DIR [--stamp HASH]
       python3 tools/check_live.py site URL --built DIR [--stamp HASH]

Standard library only: the deploy workflow runs it with the runner's python3, without uv.

`built` checks a folder made by `just live` before it goes to vhrd.tech:
- the site's own files are there (index.html, 404.html, robots.txt, sitemap.xml);
- every file has a type the site ships (no PNG render source, no PHP, no manifest) and nothing is a symlink;
- no top-level name is one the old WordPress site owns (/shop/, /cart/, /wp-admin/, ...): a file there would hide
  WordPress's page behind it;
- it is the indexable build (robots.txt allows, no page says noindex) and the sitemap names https://vhrd.tech/;
- with --stamp, the front page's footer stamp is that hash.

`site` checks a deployed site against that folder: every page of its sitemap answers 200 at URL without a
redirect, the front page carries the stamp, and /shop/ still reaches WordPress.
"""

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REQUIRED = ["index.html", "404.html", "robots.txt", "sitemap.xml"]
# What the site ships. Anything else (a .png render source, a .php, a manifest) stops the upload.
TYPES = {".html", ".css", ".js", ".svg", ".xml", ".txt", ".woff2", ".avif", ".webp", ".jpg", ".ico"}
NAMES = {"VERSION"}
# Paths the WordPress site behind vhrd.tech answers. A static file at one of these would shadow it.
WORDPRESS = re.compile(r"^(wp-.*|.*\.php|shop|product|product-category|cart|checkout|my-account|feed|comments"
                       r"|category|tag|author|page|xmlrpc|wc-api|\.well-known)$")
LIVE = "https://vhrd.tech/"
SHOP = "shop/"


def built(folder, stamp):
    """The problems in a live build folder, one line each."""
    problems = []
    for name in REQUIRED:
        if not (folder / name).is_file():
            problems.append(f"{name} missing")
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if path.is_symlink():
            problems.append(f"{rel}: a symlink")
        elif path.is_file() and path.suffix not in TYPES and path.name not in NAMES:
            problems.append(f"{rel}: not a type the site ships")
    for top in sorted(folder.iterdir()):
        if WORDPRESS.match(top.name):
            problems.append(f"{top.name}: a WordPress path, it would hide WordPress's page")
    robots = (folder / "robots.txt").read_text() if (folder / "robots.txt").is_file() else ""
    if re.search(r"^Disallow:\s*/\s*$", robots, re.M):
        problems.append("robots.txt disallows everything: a preview build, not the live one")
    for page in folder.rglob("*.html"):
        if 'name="robots" content="noindex' in page.read_text():
            problems.append(f"{page.relative_to(folder)}: noindex")
    locs = sitemap(folder)
    if not locs or any(not loc.startswith(LIVE) for loc in locs):
        problems.append(f"sitemap.xml: not every page is under {LIVE}")
    if stamp:
        front = (folder / "index.html").read_text() if (folder / "index.html").is_file() else ""
        if f"<code>{stamp}</code>" not in front:
            problems.append(f"index.html: the footer stamp is not {stamp}")
    return problems


def sitemap(folder):
    """The page URLs in the build's sitemap.xml."""
    path = folder / "sitemap.xml"
    return re.findall(r"<loc>([^<]+)</loc>", path.read_text()) if path.is_file() else []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(url):
    """Status and body of a GET, redirects not followed."""
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "vhrd-site-deploy-check"})
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""


def site(base, folder, stamp):
    """The problems of the deployed site at base, one line each."""
    problems = []
    base = base.rstrip("/") + "/"
    locs = sitemap(folder)
    if not locs:
        return [f"{folder}/sitemap.xml: no pages"]
    for loc in locs:
        url = base + loc.removeprefix(LIVE)
        status, body = fetch(url)
        if status != 200:
            problems.append(f"{url}: {status}")
        elif stamp and url == base and f"<code>{stamp}</code>" not in body:
            problems.append(f"{url}: the footer stamp is not {stamp}")
        print(f"{status} {url}")
    status, _ = fetch(base + SHOP)
    print(f"{status} {base + SHOP}")
    if status != 200:
        problems.append(f"{base + SHOP}: {status}, WordPress behind the site should answer it")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="what", required=True)
    one = sub.add_parser("built", help="check a live build folder before upload")
    one.add_argument("dir", type=Path)
    one.add_argument("--stamp", help="the git hash the footer must show")
    two = sub.add_parser("site", help="check the deployed site against its build folder")
    two.add_argument("url")
    two.add_argument("--built", type=Path, required=True)
    two.add_argument("--stamp", help="the git hash the front page's footer must show")
    args = parser.parse_args()
    if args.what == "built":
        problems = built(args.dir, args.stamp)
    else:
        problems = site(args.url, args.built, args.stamp)
    for line in problems:
        print(f"FAIL {line}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print("ok")


if __name__ == "__main__":
    main()
