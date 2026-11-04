"""Cross-links: the first mention of each of our projects on a page links to its page or repository.

The names and where they lead are data/links.toml, the table the `vh.ref` component reads. A page's prose is the
text in <main> outside headings, captions, labels, badges, code, key/value specs, terminal captures and navigation.
On each page the first time a name appears in that prose it must sit inside a link to its address (or its
repository, `repo`); a name whose address is this page itself is left alone. A linked title (a card's heading) counts as
a mention that is linked; an unlinked title, label or code does not count at all. check_pages.py runs this on every page of the site.

Usage: python3 tools/mentions.py DIR   (a built site, e.g. target/test; for a quick look without the browser)
"""

import html.parser
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parent.parent
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# Never read: navigation and what is not text (the site's header and footer are outside <main>).
DROP_TAGS = {"nav", "script", "style", "svg", "template"}
# Not prose: a mention in these is a title, a label or code, never a sentence to link from.
SKIP_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "figcaption", "code", "pre", "dt", "button", "summary"}
SKIP_CLASSES = {"v-label", "v-badge", "specs", "term", "crate-links", "repo-meta", "draft-note"}


def table():
    """The names, longest first (so "CAN line" is tried before a shorter name inside it), with their addresses."""
    links = tomllib.loads((ROOT / "data/links.toml").read_text())["link"]
    return sorted(((x["name"], [x["url"]] + ([x["repo"]] if "repo" in x else [])) for x in links),
                  key=lambda x: -len(x[0]))


def pattern(name):
    return re.compile(r"(?<![\w/#.-])" + re.escape(name) + r"(?![\w-])")


class Prose(html.parser.HTMLParser):
    """The text of <main> in order: each piece, the href of the link around it (or None), and whether it is prose."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, drops, skips, href)
        self.pieces = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        drops = tag in DROP_TAGS or "aria-hidden" in a
        skips = tag in SKIP_TAGS or bool(classes & SKIP_CLASSES)
        self.stack.append((tag, drops, skips, a.get("href") if tag == "a" else None))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not any(t == "main" for t, *_ in self.stack) or any(d for _, d, _, _ in self.stack):
            return
        href = next((h for t, _, _, h in reversed(self.stack) if t == "a"), None)
        self.pieces.append((data, href, not any(s for _, _, s, _ in self.stack)))


def leads(href, urls, page_url, base):
    return any(same(href, u, page_url, base) for u in urls)


def same(href, url, page_url, base):
    """Whether a link's href leads to the table's address: the same page (the fragment aside) or the same repo."""
    if href is None:
        return False
    got = urlsplit(urljoin(page_url, href))
    if url.startswith(("http://", "https://")):
        return urljoin(page_url, href).rstrip("/").startswith(url.rstrip("/"))
    want = urlsplit(urljoin(base, url.lstrip("/")))
    return (got.netloc, got.path) == (want.netloc, want.path)


def problems(page_url, body, base):
    """Names whose first mention in this page's prose is not linked to their address."""
    p = Prose()
    p.feed(body)
    here = urlsplit(page_url).path
    where = here[len(urlsplit(base).path) - 1:] or "/"
    out = []
    for name, urls in table():
        url = urls[0]
        if not url.startswith(("http://", "https://")) and urlsplit(urljoin(base, url.lstrip("/"))).path == here:
            continue
        rx = pattern(name)
        for text, href, prose in p.pieces:
            m = rx.search(text)
            if not m:
                continue
            linked = leads(href, urls, page_url, base)
            if not linked and not prose:
                continue
            if not linked:
                around = " ".join(text[max(0, m.start() - 30):m.end() + 30].split())
                out.append(f"cross-links: {where} first mentions {name} without a link to {url}: \"…{around}…\"")
            break
    return out


def main():
    root = Path(sys.argv[1])
    base = tomllib.loads((ROOT / "config.toml").read_text())["base_url"].rstrip("/") + "/"
    found = []
    for f in sorted(root.rglob("index.html")):
        rel = f.parent.relative_to(root).as_posix()
        url = base + ("" if rel == "." else rel + "/")
        found += problems(url, f.read_text(), base)
    for x in found:
        print(x)
    print(f"{len(found)} unlinked first mentions")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
