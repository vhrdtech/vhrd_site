"""Check a live build before it is uploaded, and the site once it is.

Usage: python3 tools/check_live.py built DIR [--stamp HASH]
       python3 tools/check_live.py redirects DIR
       python3 tools/check_live.py site URL --built DIR [--stamp HASH]

Standard library only: the deploy workflow runs it with the runner's python3, without uv.

`built` checks a folder made by `just live` before it goes to vhrd.tech:
- the site's own files are there (index.html, 404.html, robots.txt, sitemap.xml);
- every file has a type the site ships (no PNG render source, no PHP, no manifest) and nothing is a symlink;
- no top-level name is a WordPress path (wp-*, *.php, /cart/, /product/, /feed/, ...): WordPress is gone, its paths
  redirect, and nothing of it ever ships;
- the redirects (deploy/redirects.map, as `redirects` checks them);
- it is the indexable build (robots.txt allows, no page says noindex) and the sitemap names https://vhrd.tech/;
- with --stamp, the front page's footer stamp is that hash.

`redirects` checks deploy/redirects.map against a build: every target is a page of it, no redirect hides one of its
pages, and every old WordPress path in deploy/old-urls.txt is a page or redirected.

`site` checks a deployed site against that folder: every page of its sitemap answers 200 at URL without a
redirect, the front page carries the stamp, every old path answers its 301 (or 200 for a page), and a missing
path gets the site's own 404 page.
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
# WordPress paths. WordPress is gone from vhrd.tech (4 Nov 2026), and nothing like it ever ships.
WORDPRESS = re.compile(r"^(wp-.*|.*\.php|product|product-category|cart|checkout|my-account|feed|comments"
                       r"|category|tag|author|page|xmlrpc|wc-api|\.well-known)$")
LIVE = "https://vhrd.tech/"
ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "deploy/redirects.map"
OLD = ROOT / "deploy/old-urls.txt"
NOT_FOUND = "No trace here"  # the 404 page's headline


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
            problems.append(f"{top.name}: a WordPress path; nothing of WordPress ships")
    problems += redirects(folder)
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


def redirect_map():
    """The redirects of deploy/redirects.map: (pattern, target) in order, a plain key matched whole."""
    rules = []
    body = MAP.read_text().split("$vhrd_redirect {", 1)[1].rsplit("}", 1)[0]
    for line in body.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("default"):
            continue
        key, target = line.rstrip(";").rsplit(None, 1)
        key = key.strip().strip('"')
        rules.append((re.compile(key[1:] if key.startswith("~") else "^" + re.escape(key) + "$"), target))
    return rules


def redirect_for(path, rules):
    for pattern, target in rules:
        if pattern.search(path):
            return target
    return None


def old_paths():
    return [l.strip() for l in OLD.read_text().splitlines() if l.strip() and not l.startswith("#")]


def page_at(folder, path):
    return (folder / path.lstrip("/") / "index.html").is_file()


def redirects(folder):
    """The problems of deploy/redirects.map against a build folder."""
    problems, rules = [], redirect_map()
    for pattern, target in rules:
        if not re.fullmatch(r"/([a-z0-9-]+/)*", target):
            problems.append(f"{MAP.name}: {pattern.pattern} leads to {target}, not a path of this site")
        elif not page_at(folder, target):
            problems.append(f"{MAP.name}: {pattern.pattern} leads to {target}, which is not a page of the build")
    for page in folder.rglob("index.html"):
        path = "/" + page.parent.relative_to(folder).as_posix().removeprefix(".") + "/"
        path = path.replace("//", "/")
        if redirect_for(path, rules):
            problems.append(f"{MAP.name}: {path} is a page, but it redirects to {redirect_for(path, rules)}")
    for path in old_paths():
        if not page_at(folder, path) and not redirect_for(path, rules):
            problems.append(f"{OLD.name}: {path} is neither a page nor redirected")
    return problems


def sitemap(folder):
    """The page URLs in the build's sitemap.xml."""
    path = folder / "sitemap.xml"
    return re.findall(r"<loc>([^<]+)</loc>", path.read_text()) if path.is_file() else []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(url, location=False):
    """Status and body of a GET, redirects not followed; with location, the Location header too."""
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "vhrd-site-deploy-check"})
    try:
        with opener.open(request, timeout=30) as response:
            out = response.status, response.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as error:
        out = error.code, error.read().decode("utf-8", "replace"), error.headers.get("Location")
    return out if location else out[:2]


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
    rules = redirect_map()
    for path in old_paths():
        url, target = base + path.lstrip("/"), redirect_for(path, rules)
        status, _, location = fetch(url, location=True)
        print(f"{status} {url}{' -> ' + location if location else ''}")
        if target and (status != 301 or location not in (target, base + target.lstrip("/"))):
            problems.append(f"{url}: {status} to {location!r}, expected 301 to {target}")
        elif not target and status != 200:
            problems.append(f"{url}: {status}, expected the page")
    url = base + "no-such-page-" + (stamp or "x") + "/"
    status, body = fetch(url)
    print(f"{status} {url}")
    if status != 404 or NOT_FOUND not in body:
        problems.append(f"{url}: {status}, expected the site's own 404 page")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="what", required=True)
    one = sub.add_parser("built", help="check a live build folder before upload")
    one.add_argument("dir", type=Path)
    one.add_argument("--stamp", help="the git hash the footer must show")
    red = sub.add_parser("redirects", help="check deploy/redirects.map against a build folder")
    red.add_argument("dir", type=Path)
    two = sub.add_parser("site", help="check the deployed site against its build folder")
    two.add_argument("url")
    two.add_argument("--built", type=Path, required=True)
    two.add_argument("--stamp", help="the git hash the front page's footer must show")
    args = parser.parse_args()
    if args.what == "built":
        problems = built(args.dir, args.stamp)
    elif args.what == "redirects":
        problems = redirects(args.dir)
    else:
        problems = site(args.url, args.built, args.stamp)
    for line in problems:
        print(f"FAIL {line}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print("ok")


if __name__ == "__main__":
    main()
