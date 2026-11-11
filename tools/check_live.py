"""Check a live build before it is uploaded, and the site once it is.

Usage: python3 tools/check_live.py built DIR [--stamp HASH]
       python3 tools/check_live.py redirects DIR
       python3 tools/check_live.py site URL --built DIR [--stamp HASH] [--full]

Standard library only: the deploy workflow runs it with the runner's python3, without uv.

`built` checks a folder made by `just live` (and, against target/test, by `just test`) before it goes to
vhrd.tech:
- the site's own files are there (index.html, 404.html, robots.txt, sitemap.xml);
- every file has a type the site ships (no PNG render source, no PHP, no manifest) and nothing is a symlink;
  a .png ships only under img/og/ (the share images) and a .cast only under term/ (a recorded terminal
  session), both refused everywhere else;
- no top-level name is a WordPress path (wp-*, *.php, /cart/, /product/, /feed/, ...): WordPress is gone, its paths
  redirect, and nothing of it ever ships;
- the redirects (deploy/redirects.map, as `redirects` checks them);
- it is the indexable build (robots.txt allows, no page but the mail links' says noindex) and the sitemap names
  https://vhrd.tech/;
- with --stamp, the front page's footer stamp is that hash;
- the default share image's two cards (deploy/nginx-og.conf): the location in deploy/nginx-og-location.conf is the
  front page's og:image, the map's default is that file, and every file the map names is in the build, a
  1200x627 truecolour JPEG;
- the twitter:image URL (deploy/nginx-og.conf's $og_twitter map): its location is the front page's twitter:image,
  the map's default is the og:image JPEG (for Telegram and everyone else, who would draw the transparent PNG's
  white headline on their own white page), and the Twitterbot entry is the location's own file, a 1200x627
  truecolour PNG with an alpha channel;
- every page's og:image and twitter:image end in `?v=` and the version of the build's img/og/ files
  (tools/og_version.py): the names never change, so a changed image without `just og` (or `python3
  tools/og_version.py`) would keep its old URL, and the crawlers, which cache a preview by it, the old image.

`redirects` checks deploy/redirects.map against a build: every target is a page of it, no redirect hides one of its
pages, every old WordPress path in deploy/old-urls.txt is a page or redirected, and every link in
deploy/golden-links.txt (what we have printed or sent) is a page, a file or redirected.

`site` checks a deployed site against that folder: the front page answers 200 and carries the stamp, a second page
and a stylesheet and script answer 200, one old path per redirect rule answers its 301 (the server's copy of the map
is installed by hand, so it can differ from the repo's), a missing path gets the site's own 404 page, and the default og:image URL answers LinkedInBot and WhatsApp with
the square card and a browser with the wide one, with Vary: User-Agent (deploy/nginx-og.conf, installed by hand
like the map). The twitter:image URL answers Telegram's own User-Agent and a browser with the og:image JPEG, and
Twitterbot with the PNG, also with Vary: User-Agent. Every one of those answers also carries the Cache-Control
deploy/nginx-og-location.conf's two locations add (an exact location drops the server's own, so both locations
repeat it). `built` has already checked the rest against the map, and rsync sets the same modes on every file.
With --full, every page of the sitemap, every old path and every golden link too.
"""

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from og_version import og_version

REQUIRED = ["index.html", "404.html", "robots.txt", "sitemap.xml"]
# What the site ships. Anything else (a .png render source, a .php, a manifest) stops the upload.
TYPES = {".html", ".css", ".js", ".svg", ".xml", ".txt", ".woff2", ".avif", ".webp", ".jpg", ".ico"}
NAMES = {"VERSION"}
# A type the site ships only under one path: a share image (ASSET-2 og-images) is the one PNG that ships (every
# other PNG is a board render source, kept out of the build), and a recorded terminal session (BLOCK-7 term-live)
# is the one .cast. Elsewhere those extensions are still refused.
EXTRA_TYPES = {".png": re.compile(r"^img/og/"), ".cast": re.compile(r"^term/")}
# WordPress paths. WordPress is gone from vhrd.tech (4 Nov 2026), and nothing like it ever ships.
WORDPRESS = re.compile(r"^(wp-.*|.*\.php|product|product-category|cart|checkout|my-account|feed|comments"
                       r"|category|tag|author|page|xmlrpc|wc-api|\.well-known)$")
# The pages behind the mail links (NOTIFY-4) are noindex in the live build too.
NOINDEX = {"notify/confirm/index.html", "notify/remove/index.html"}
LIVE = "https://vhrd.tech/"
ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "deploy/redirects.map"
OLD = ROOT / "deploy/old-urls.txt"
GOLDEN = ROOT / "deploy/golden-links.txt"
NOT_FOUND = "No trace here"  # the 404 page's headline
OG_MAP = ROOT / "deploy/nginx-og.conf"
OG_LOCATION = ROOT / "deploy/nginx-og-location.conf"
# What the crawlers send: LinkedIn's and WhatsApp's own, and a desktop browser's.
UA_SQUARE = ["LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)",
             "WhatsApp/2.23.20.0 A"]
UA_WIDE = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
# Telegram's own User-Agent, which also matches "~*Twitterbot" case-insensitively (it contains "TwitterBot"):
# the $og_twitter map's TelegramBot entry must come first, so this gets the JPEG, not X's PNG.
UA_TELEGRAM = "TelegramBot (like TwitterBot)"
UA_TWITTERBOT = "Twitterbot/1.0"


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
            allowed = EXTRA_TYPES.get(path.suffix)
            if not allowed or not allowed.match(rel):
                problems.append(f"{rel}: not a type the site ships")
    for top in sorted(folder.iterdir()):
        if WORDPRESS.match(top.name):
            problems.append(f"{top.name}: a WordPress path; nothing of WordPress ships")
    problems += redirects(folder)
    robots = (folder / "robots.txt").read_text() if (folder / "robots.txt").is_file() else ""
    if re.search(r"^Disallow:\s*/\s*$", robots, re.M):
        problems.append("robots.txt disallows everything: a preview build, not the live one")
    for page in folder.rglob("*.html"):
        noindex = 'name="robots" content="noindex' in page.read_text()
        if noindex != (page.relative_to(folder).as_posix() in NOINDEX):
            problems.append(f"{page.relative_to(folder)}: {'noindex' if noindex else 'not noindex'}")
    locs = sitemap(folder)
    if not locs or any(not loc.startswith(LIVE) for loc in locs):
        problems.append(f"sitemap.xml: not every page is under {LIVE}")
    if stamp:
        front = (folder / "index.html").read_text() if (folder / "index.html").is_file() else ""
        if f"<code>{stamp}</code>" not in front:
            problems.append(f"index.html: the footer stamp is not {stamp}")
    problems += og_cards(folder)
    problems += og_versions(folder)
    return problems


def og_map():
    """deploy/nginx-og.conf's $og_default map and its location: (the og:image path, the default file, the
    files for a cropping crawler), each a URL path."""
    path = re.search(r"^location = (\S+) \{\s*try_files \$og_default\b", OG_LOCATION.read_text(), re.M).group(1)
    body = re.search(r"map \$http_user_agent \$og_default \{(.*?)^\}", OG_MAP.read_text(), re.M | re.S).group(1)
    entries = dict(re.findall(r"^\s*(\S+)\s+(/\S+);$", body, re.M))
    return path, entries.pop("default"), sorted(set(entries.values()))


def jpeg_size(data):
    """(width, height, components) of a baseline or progressive JPEG, or None."""
    i = 2
    while data[:2] == b"\xff\xd8" and i + 9 < len(data) and data[i] == 0xFF:
        if data[i + 1] in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big"), data[i + 9]
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def og_twitter_map():
    """deploy/nginx-og.conf's $og_twitter map and its location in deploy/nginx-og-location.conf: the
    twitter:image URL, the og:image JPEG everyone but Twitterbot gets there (Telegram's own User-Agent
    included, AGENTS.md "Link previews"), and Twitterbot's own PNG."""
    path = re.search(r"^location = (\S+) \{\s*try_files \$og_twitter\b", OG_LOCATION.read_text(), re.M).group(1)
    body = re.search(r"map \$http_user_agent \$og_twitter \{(.*?)^\}", OG_MAP.read_text(), re.M | re.S).group(1)
    entries = dict(re.findall(r"^\s*(\S+)\s+(/\S+);$", body, re.M))
    return path, entries["default"], entries["~*Twitterbot"]


def png_size(data):
    """(width, height, IHDR colour type) of a PNG from its own header: 6 is truecolour with alpha."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"), data[25]


def og_cards(folder):
    """The problems of the default share image's cards in a build folder: og:image's two (og_map) and
    twitter:image's two (og_twitter_map)."""
    problems = []
    path, wide, square = og_map()
    front = (folder / "index.html").read_text() if (folder / "index.html").is_file() else ""
    image = re.search(r'<meta property="og:image" content="([^"]+)"', front)
    if not image or not image.group(1).split("?")[0].endswith(path):
        problems.append(f"{OG_LOCATION.name}: location {path}, but the front page's og:image is "
                        f"{image and image.group(1)}")
    if wide != path:
        problems.append(f"{OG_MAP.name}: the default is {wide}, not the location's own {path}")
    for name in [wide] + square:
        file = folder / name.lstrip("/")
        size = jpeg_size(file.read_bytes()) if file.is_file() else None
        if size != (1200, 627, 3):
            problems.append(f"{name}: {size or 'missing or not a JPEG'}, expected a 1200x627 truecolour JPEG")
    twitter_path, twitter_default, twitter_png = og_twitter_map()
    timage = re.search(r'<meta name="twitter:image" content="([^"]+)"', front)
    if not timage or not timage.group(1).split("?")[0].endswith(twitter_path):
        problems.append(f"{OG_LOCATION.name}: location {twitter_path}, but the front page's twitter:image is "
                        f"{timage and timage.group(1)}")
    if twitter_default != wide:
        problems.append(f"{OG_MAP.name}: $og_twitter's default is {twitter_default}, not the og:image card {wide}")
    if twitter_png != twitter_path:
        problems.append(f"{OG_MAP.name}: $og_twitter's Twitterbot entry is {twitter_png}, "
                        f"not the location's own {twitter_path}")
    file = folder / twitter_png.lstrip("/")
    size = png_size(file.read_bytes()) if file.is_file() else None
    if size != (1200, 627, 6):
        problems.append(f"{twitter_png}: {size or 'missing or not a PNG'}, expected a 1200x627 truecolour+alpha PNG")
    return problems


def og_versions(folder):
    """The pages whose og:image or twitter:image is not the build's image with `?v=` and the version of the build's
    share images (tools/og_version.py, data/og.toml)."""
    problems = []
    og = folder / "img/og"
    want = og_version(og) if og.is_dir() else None
    for page in sorted(folder.rglob("*.html")):
        html = page.read_text()
        for tag in ('property="og:image"', 'name="twitter:image"'):
            meta = re.search(rf'<meta {tag} content="([^"]+)"', html)
            if not meta:
                continue
            label, url = tag.split('"')[1], meta.group(1)
            where = f"{page.relative_to(folder)}: {label}"
            path, _, query = url.partition("?")
            if "/img/og/" not in path or not (og / path.rsplit("/", 1)[1]).is_file():
                problems.append(f"{where} {url} is not a share image of the build")
            elif query != f"v={want}":
                problems.append(f"{where} is {url}, expected ?v={want} "
                                "(the share images changed: `just og`, or `python3 tools/og_version.py`)")
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


def paths_in(file):
    return [l.strip() for l in file.read_text().splitlines() if l.strip() and not l.startswith("#")]


def old_paths():
    return paths_in(OLD)


def golden_paths():
    return paths_in(GOLDEN)


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
    for path in golden_paths():
        if not page_at(folder, path) and not (folder / path.lstrip("/")).is_file() and not redirect_for(path, rules):
            problems.append(f"{GOLDEN.name}: {path} is a link we promised, and this build breaks it")
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


def fetch_image(url, agent):
    """Status, body bytes, Vary and Cache-Control headers of a GET as that User-Agent."""
    request = urllib.request.Request(url, headers={"User-Agent": agent})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return (response.status, response.read(), response.headers.get("Vary", ""),
                     response.headers.get("Cache-Control", ""))
    except urllib.error.HTTPError as error:
        return error.code, b"", "", ""


def og_cache_control():
    """The Cache-Control value deploy/nginx-og-location.conf's two locations both add (an exact location wins
    over the server's own /(css|fonts|img|js)/ one, which would otherwise set it): parsed, not hardcoded here,
    so the check cannot drift from the file."""
    values = set(re.findall(r'add_header Cache-Control "([^"]+)"', OG_LOCATION.read_text()))
    if len(values) != 1:
        raise SystemExit(f"{OG_LOCATION.name}: its locations' Cache-Control values differ: {sorted(values)}")
    return values.pop()


def one_per_rule(paths, rules):
    """The first old path each redirect rule answers."""
    seen, out = set(), []
    for path in paths:
        rule = next((pattern for pattern, _ in rules if pattern.search(path)), None)
        if rule is not None and rule not in seen:
            seen.add(rule)
            out.append(path)
    return out


def site(base, folder, stamp, full=False):
    """The problems of the deployed site at base, one line each."""
    problems = []
    base = base.rstrip("/") + "/"
    locs = sitemap(folder)
    if not locs:
        return [f"{folder}/sitemap.xml: no pages"]
    if not full:
        locs = [loc for loc in locs if loc == LIVE] + [loc for loc in locs if loc != LIVE][:1]
    for loc in locs:
        url = base + loc.removeprefix(LIVE)
        status, body = fetch(url)
        if status != 200:
            problems.append(f"{url}: {status}")
        elif stamp and url == base and f"<code>{stamp}</code>" not in body:
            problems.append(f"{url}: the footer stamp is not {stamp}")
        print(f"{status} {url}")
    for pattern in ("css/*.css", "js/*.js"):
        for asset in sorted(folder.glob(pattern))[:1]:
            url = base + asset.relative_to(folder).as_posix()
            status, _ = fetch(url)
            print(f"{status} {url}")
            if status != 200:
                problems.append(f"{url}: {status}")
    rules = redirect_map()
    for path in old_paths() + golden_paths() if full else one_per_rule(old_paths(), rules):
        url, target = base + path.lstrip("/"), redirect_for(path, rules)
        status, _, location = fetch(url, location=True)
        print(f"{status} {url}{' -> ' + location if location else ''}")
        if target and (status != 301 or location not in (target, base + target.lstrip("/"))):
            problems.append(f"{url}: {status} to {location!r}, expected 301 to {target}")
        elif not target and status != 200:
            problems.append(f"{url}: {status}, expected the page")
    cache_control = og_cache_control()
    path, wide, square = og_map()
    url = base + path.lstrip("/")
    for agent, name in [(UA_WIDE, wide)] + [(agent, square[0]) for agent in UA_SQUARE]:
        status, data, vary, cache = fetch_image(url, agent)
        expected = (folder / name.lstrip("/")).read_bytes()
        print(f"{status} {url} as {agent.split('/')[0]}: {'the' if data == expected else 'not the'} {name}")
        if status != 200 or data != expected:
            problems.append(f"{url} as {agent!r}: {status}, not the bytes of {name} (deploy/nginx-og.conf installed?)")
        elif "user-agent" not in vary.lower():
            problems.append(f"{url} as {agent!r}: Vary is {vary!r}, expected User-Agent")
        elif cache != cache_control:
            problems.append(f"{url} as {agent!r}: Cache-Control is {cache!r}, expected {cache_control!r}")
    twitter_path, twitter_default, twitter_png = og_twitter_map()
    turl = base + twitter_path.lstrip("/")
    for agent, name in [(UA_TELEGRAM, twitter_default), (UA_WIDE, twitter_default), (UA_TWITTERBOT, twitter_png)]:
        status, data, vary, cache = fetch_image(turl, agent)
        expected = (folder / name.lstrip("/")).read_bytes()
        print(f"{status} {turl} as {agent.split('/')[0]}: {'the' if data == expected else 'not the'} {name}")
        if status != 200 or data != expected:
            problems.append(f"{turl} as {agent!r}: {status}, not the bytes of {name} (deploy/nginx-og.conf installed?)")
        elif "user-agent" not in vary.lower():
            problems.append(f"{turl} as {agent!r}: Vary is {vary!r}, expected User-Agent")
        elif cache != cache_control:
            problems.append(f"{turl} as {agent!r}: Cache-Control is {cache!r}, expected {cache_control!r}")
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
    two.add_argument("--full", action="store_true", help="every page and every old path, not a sample")
    args = parser.parse_args()
    if args.what == "built":
        problems = built(args.dir, args.stamp)
    elif args.what == "redirects":
        problems = redirects(args.dir)
    else:
        problems = site(args.url, args.built, args.stamp, args.full)
    for line in problems:
        print(f"FAIL {line}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print("ok")


if __name__ == "__main__":
    main()
