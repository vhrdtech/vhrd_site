"""Per-page reading metrics (SITE-20 page-stats): how much there is to read on a page, and how it is shaped.

Built on the built site (zola output), each page's <main> only: the header, footer and nav sit outside it in
base.html and never count. Within <main>, "prose" is flowing text -- <p>, <li> and <blockquote> -- outside
headings, figure captions, code, terminal captures, key/value specs (vh.specs), labels, badges, draft notes
and calls to action: those are counted on their own, never mixed into word, paragraph or sentence counts.
Standard library only.

Usage: python3 tools/page_stats.py [PAGE] [--dir DIR] [--json FILE]
  no PAGE:  a compact table, one row per page
  PAGE:     the detailed view of one page, e.g. "donguru/" ("" for the front page)
  --dir DIR builds the site itself into target/page-stats by default; pass an already-built directory
            (e.g. target/test) to read that instead
  --json FILE  where the full per-page numbers are written, default target/page-stats.json, for a later
            comparison (diff two runs' files to see what a change moved)

Metrics, per page:
  1. word count and reading time. Reading time is words / wpm minutes, plus a falling allowance per image,
     the way Medium estimates it: the first image costs image_first_seconds, each one after that a little
     less, down a floor of image_min_seconds over image_falloff_count images, then every further image costs
     the floor. wpm and the image constants are in config.toml's [extra.page_stats], report-only (no budget).
  2. the longest run: the most prose words between two visual breaks (a heading, a figure -- an image or a
     terminal capture --, a video, a table, a FAQ-style <summary> or a call-to-action button, class v-btn),
     and how many such runs are over the soft budget longest_run_words.
  3. paragraph length (max, median words over every <p>/<li>/<blockquote>) and sentence length (median, max,
     and the share of sentences over long_sentence_words words); a soft budget paragraph_words and
     median_sentence_words warns, never fails.
  4. images and figures: every figure other than a terminal capture (a board render, a lab photo or an
     inline diagram; a decorative icon elsewhere on the page does not count) as one image, how many words
     share each one, and how many of the <img> elements actually inside those figures have no alt attribute
     at all (an empty alt="" is a deliberate decorative choice, not a miss).
  5. headings: how many, and words per heading (so a heading written as a full sentence stands out).
  6. links inside <main> (internal: a fragment, a site-relative path, or vhrd.tech; external: anything else)
     and calls to action (class v-btn, whether a link or a submit button).
  7. code blocks (a <pre>, outside a figure: a fenced sample, a code-tabs panel) and terminal captures
     (vh.term, a <figure class="fig term-fig">).
  8. Flesch reading ease, for English pages only (the page's own <html lang>): 206.835 - 1.015 * words per
     sentence - 84.6 * syllables per word, over the same prose text as 2 and 3. Syllables are a common
     heuristic (vowel groups, minus a few silent endings), not a dictionary count.

The sentence splitter is a plain regex (after ., ! or ? followed by a capital, a digit or an opening quote):
good enough for budgets, not grammar-aware (it misses "Mr. Smith" and the like).
"""

import argparse
import html.parser
import json
import re
import statistics
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_BUDGETS = {
    "wpm": 230,
    "image_first_seconds": 12,
    "image_min_seconds": 3,
    "image_falloff_count": 10,
    "longest_run_words": 250,
    "paragraph_words": 90,
    "median_sentence_words": 20,
    "long_sentence_words": 25,
}

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# Never prose, never a break: invisible chrome (the site's header and footer are outside <main> already; an
# inline SVG diagram's own <text> labels, a decorative trace's aria-hidden label).
DROP_TAGS = {"nav", "script", "style", "svg", "template"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
PARA_TAGS = ("p", "li", "blockquote")
# A label, a badge, a spec list, a crate's links, a repo's meta line, a draft note: structure, not prose.
SKIP_CLASSES = {"v-label", "v-badge", "specs", "term", "crate-links", "repo-meta", "draft-note"}
CTA_CLASS = "v-btn"
TERM_CLASS = "term-fig"


@dataclass
class _Node:
    tag: str
    skip: bool
    collect_images: bool = False
    opened_para: bool = False


def syllables(word):
    """A common heuristic (vowel groups, minus a silent e or -ed/-es ending), not a dictionary lookup."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]e|[^laeiouy]es|ed)$", "", w)
    w = re.sub(r"^y", "", w)
    groups = re.findall(r"[aeiouy]{1,2}", w)
    return max(1, len(groups))


_SENTENCE_END = re.compile(r"(?<=[.!?])[\"'’”)\]]*\s+(?=[A-Z0-9\"'‘“(])")


def split_sentences(text):
    """A plain heuristic: split after ./!/? followed by whitespace and a capital, a digit or an opening quote."""
    text = " ".join(text.split())
    if not text:
        return []
    return [p for p in (s.strip() for s in _SENTENCE_END.split(text)) if p]


def image_cost(i, budgets):
    """Seconds for the i-th image (1-indexed): falls from image_first_seconds to image_min_seconds over
    image_falloff_count images, then stays at the floor (as Medium's read-time estimate does)."""
    first, floor, n = budgets["image_first_seconds"], budgets["image_min_seconds"], budgets["image_falloff_count"]
    if n <= 1 or i > n:
        return floor
    step = (first - floor) / (n - 1) if n > 1 else 0
    return max(floor, first - step * (i - 1))


def reading_minutes(word_count, images, budgets):
    seconds = word_count / budgets["wpm"] * 60 + sum(image_cost(i, budgets) for i in range(1, images + 1))
    return seconds / 60


def flesch_reading_ease(word_count, sentence_count, syllable_count):
    if word_count == 0 or sentence_count == 0:
        return None
    return 206.835 - 1.015 * (word_count / sentence_count) - 84.6 * (syllable_count / word_count)


class MainParser(html.parser.HTMLParser):
    """Walks <main>...</main> of one built page and collects reading metrics in document order."""

    def __init__(self, base_netloc):
        super().__init__(convert_charrefs=True)
        self.base_netloc = base_netloc
        self.stack = []
        self.runs = []
        self._run_words = 0
        self.paragraphs = []
        self._para_stack = []  # one accumulator per open <p>/<li>/<blockquote>, innermost last
        self.sentence_lengths = []
        self.syllable_count = 0
        self.headings = []
        self._heading_chunks = None
        self._heading_level = 0
        self.image_figures = 0
        self.terminal_captures = 0
        self.images = 0
        self.images_without_alt = 0
        self.videos = 0
        self.tables = 0
        self.ctas = 0
        self.links_internal = 0
        self.links_external = 0
        self.code_blocks = 0

    @property
    def in_main(self):
        return any(n.tag == "main" for n in self.stack)

    @property
    def parent_skip(self):
        return any(n.skip for n in self.stack)

    def _flush_run(self):
        self.runs.append(self._run_words)
        self._run_words = 0

    def _count_link(self, href):
        href = href.strip()
        if not href or href.startswith("#") or href.startswith(("/", "./", "../")):
            self.links_internal += 1
            return
        u = urlsplit(href)
        if not u.scheme:
            self.links_internal += 1
        elif u.netloc == self.base_netloc:
            self.links_internal += 1
        else:
            self.links_external += 1

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        in_main = self.in_main

        if tag == "img":
            if in_main and any(n.collect_images for n in self.stack):
                self.images += 1
                if "alt" not in a:
                    self.images_without_alt += 1
            return

        if tag == "a" and in_main and a.get("href") is not None:
            self._count_link(a["href"])

        if tag in VOID:
            return

        skip = False
        collect_images = False
        opened_para = False
        if in_main and not self.parent_skip:
            is_cta = tag in ("a", "button") and CTA_CLASS in classes
            if tag in HEADING_TAGS:
                self._flush_run()
                self._heading_chunks = []
                self._heading_level = int(tag[1])
                skip = True
            elif tag == "figure":
                self._flush_run()
                if TERM_CLASS in classes:
                    self.terminal_captures += 1
                else:
                    self.image_figures += 1
                    collect_images = True
                skip = True
            elif tag == "video":
                self._flush_run()
                self.videos += 1
                skip = True
            elif tag == "table":
                self._flush_run()
                self.tables += 1
                skip = True
            elif tag == "summary":
                self._flush_run()
                skip = True
            elif tag == "pre":
                self._flush_run()
                self.code_blocks += 1
                skip = True
            elif is_cta:
                self._flush_run()
                self.ctas += 1
                skip = True
            elif tag in ("figcaption", "dt") or (classes & SKIP_CLASSES):
                skip = True
            elif tag in DROP_TAGS or "aria-hidden" in a:
                skip = True

            if tag in PARA_TAGS and not skip:
                self._para_stack.append([])
                opened_para = True

        self.stack.append(_Node(tag, skip, collect_images, opened_para))

    def handle_data(self, data):
        if not self.in_main:
            return
        if self.parent_skip:
            # Inside a break's own subtree (a heading, a caption, code, a spec, a label, a CTA...): never
            # prose, even when an ancestor paragraph is still open around it. Only a heading's own text is
            # kept, for the headings metric.
            if self._heading_chunks is not None:
                top = next((n for n in reversed(self.stack) if n.skip), None)
                if top is not None and top.tag in HEADING_TAGS:
                    self._heading_chunks.append(data)
            return
        if self._para_stack:
            self._para_stack[-1].append(data)

    def handle_endtag(self, tag):
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                idx = i
                break
        if idx is None:
            return
        node = self.stack[idx]
        if tag in HEADING_TAGS and self._heading_chunks is not None:
            text = "".join(self._heading_chunks).strip()
            self.headings.append((self._heading_level, len(text.split())))
            self._heading_chunks = None
        if node.opened_para:
            text = "".join(self._para_stack.pop()).strip()
            if text:
                words = text.split()
                self.paragraphs.append(len(words))
                self._run_words += len(words)
                for s in split_sentences(text):
                    n = len(s.split())
                    if n:
                        self.sentence_lengths.append(n)
                for w in words:
                    self.syllable_count += syllables(w)
        del self.stack[idx:]

    def close(self):
        super().close()
        self._flush_run()


def analyze_html(html_text, base_netloc, budgets=DEFAULT_BUDGETS):
    """The metrics of one built page's HTML, as a dict (also what the JSON report and the detail view use)."""
    lang_m = re.search(r'<html[^>]*\blang="([^"]*)"', html_text)
    language = lang_m.group(1) if lang_m else None

    p = MainParser(base_netloc)
    p.feed(html_text)
    p.close()

    body_words = sum(p.paragraphs)
    heading_words = sum(w for _, w in p.headings)
    word_count = body_words + heading_words
    runs = p.runs
    sentence_lengths = p.sentence_lengths

    return {
        "word_count": word_count,
        "reading_minutes": reading_minutes(word_count, p.image_figures, budgets),
        "longest_run_words": max(runs, default=0),
        "runs_over_budget": sum(1 for r in runs if r > budgets["longest_run_words"]),
        "runs": runs,
        "paragraph_max_words": max(p.paragraphs, default=0),
        "paragraph_median_words": statistics.median(p.paragraphs) if p.paragraphs else 0,
        "sentence_median_words": statistics.median(sentence_lengths) if sentence_lengths else 0,
        "sentence_max_words": max(sentence_lengths, default=0),
        "sentence_over_budget_share": (
            sum(1 for s in sentence_lengths if s > budgets["long_sentence_words"]) / len(sentence_lengths)
            if sentence_lengths else 0.0
        ),
        "images": p.image_figures,
        "words_per_image": body_words / p.image_figures if p.image_figures else None,
        "images_without_alt": p.images_without_alt,
        "headings": len(p.headings),
        "heading_list": p.headings,
        "words_per_heading": heading_words / len(p.headings) if p.headings else None,
        "links_internal": p.links_internal,
        "links_external": p.links_external,
        "ctas": p.ctas,
        "code_blocks": p.code_blocks,
        "terminal_captures": p.terminal_captures,
        "flesch_reading_ease": (
            flesch_reading_ease(body_words, len(sentence_lengths), p.syllable_count)
            if language and language.startswith("en") else None
        ),
    }


def load_budgets():
    cfg = tomllib.loads((ROOT / "config.toml").read_text())
    budgets = dict(DEFAULT_BUDGETS)
    budgets.update(cfg.get("extra", {}).get("page_stats", {}))
    base_netloc = urlsplit(cfg["base_url"]).netloc
    return budgets, base_netloc


def build():
    out = ROOT / "target/page-stats"
    subprocess.run(["zola", "build", "--output-dir", str(out), "--force"], cwd=ROOT, check=True,
                    stdout=subprocess.DEVNULL)
    return out


def page_path(index_html, root):
    rel = index_html.parent.relative_to(root).as_posix()
    return "" if rel == "." else rel + "/"


def collect(root, budgets, base_netloc):
    """Every built page, by its path: {"": {...}, "donguru/": {...}, ...}."""
    pages = {}
    for f in sorted(root.rglob("index.html")):
        path = page_path(f, root)
        pages[path] = analyze_html(f.read_text(), base_netloc, budgets)
    return pages


def print_table(pages, budgets):
    cols = [
        ("page", lambda p, m: p or "/"),
        ("words", lambda p, m: m["word_count"]),
        ("read", lambda p, m: f'{m["reading_minutes"]:.1f}m'),
        ("run", lambda p, m: m["longest_run_words"]),
        ("runs>", lambda p, m: m["runs_over_budget"]),
        ("para.max", lambda p, m: m["paragraph_max_words"]),
        ("sent.med", lambda p, m: m["sentence_median_words"]),
        ("flesch", lambda p, m: "-" if m["flesch_reading_ease"] is None else f'{m["flesch_reading_ease"]:.0f}'),
        ("img", lambda p, m: m["images"]),
        ("h", lambda p, m: m["headings"]),
        ("links", lambda p, m: f'{m["links_internal"]}/{m["links_external"]}'),
        ("cta", lambda p, m: m["ctas"]),
        ("code", lambda p, m: m["code_blocks"]),
        ("term", lambda p, m: m["terminal_captures"]),
    ]
    rows = [[str(f(path, m)) for _, f in cols] for path, m in pages.items()]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, (h, _) in enumerate(cols)]
    header = "  ".join(h.rjust(w) if i else h.ljust(w) for i, ((h, _), w) in enumerate(zip(cols, widths)))
    print(header)
    for row in rows:
        print("  ".join(c.rjust(w) if i else c.ljust(w) for i, (c, w) in enumerate(zip(row, widths))))
    over = [path for path, m in pages.items() if m["runs_over_budget"] or
            m["paragraph_max_words"] > budgets["paragraph_words"] or
            m["sentence_median_words"] > budgets["median_sentence_words"]]
    for path in over:
        m = pages[path]
        bits = []
        if m["runs_over_budget"]:
            bits.append(f'{m["runs_over_budget"]} run(s) over {budgets["longest_run_words"]} words '
                        f'(longest {m["longest_run_words"]})')
        if m["paragraph_max_words"] > budgets["paragraph_words"]:
            bits.append(f'a paragraph of {m["paragraph_max_words"]} words (budget {budgets["paragraph_words"]})')
        if m["sentence_median_words"] > budgets["median_sentence_words"]:
            bits.append(f'median sentence {m["sentence_median_words"]} words '
                        f'(budget {budgets["median_sentence_words"]})')
        print(f'WARN {path or "/"}: {"; ".join(bits)}')


def print_detail(path, m, budgets):
    print(f'{path or "/"}')
    print(f'  words {m["word_count"]}, reading time {m["reading_minutes"]:.1f} min '
          f'({budgets["wpm"]} wpm + falling image time)')
    print(f'  longest run {m["longest_run_words"]} words (budget {budgets["longest_run_words"]}), '
          f'{m["runs_over_budget"]} run(s) over budget, {len(m["runs"])} run(s) in all')
    print(f'  paragraphs: max {m["paragraph_max_words"]}, median {m["paragraph_median_words"]:.0f} words '
          f'(budget {budgets["paragraph_words"]})')
    print(f'  sentences: median {m["sentence_median_words"]:.0f}, max {m["sentence_max_words"]} words, '
          f'{m["sentence_over_budget_share"] * 100:.0f}% over {budgets["long_sentence_words"]} words '
          f'(budget median {budgets["median_sentence_words"]})')
    wpi = "-" if m["words_per_image"] is None else f'{m["words_per_image"]:.0f}'
    print(f'  images {m["images"]} ({m["images_without_alt"]} without alt), {wpi} words per image')
    wph = "-" if m["words_per_heading"] is None else f'{m["words_per_heading"]:.0f}'
    print(f'  headings {m["headings"]}, {wph} words per heading:')
    for level, words in m["heading_list"]:
        print(f'    h{level}: {words} words')
    print(f'  links: {m["links_internal"]} internal, {m["links_external"]} external; {m["ctas"]} call(s) to action')
    print(f'  code blocks {m["code_blocks"]}, terminal captures {m["terminal_captures"]}')
    flesch = "n/a (not an English page)" if m["flesch_reading_ease"] is None else f'{m["flesch_reading_ease"]:.1f}'
    print(f'  Flesch reading ease: {flesch}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", help='a built page\'s path, e.g. "donguru/" ("" for the front page); '
                                              "omitted: the table for every page")
    ap.add_argument("--dir", help="an already-built site to read (e.g. target/test); default: build one")
    ap.add_argument("--json", default="target/page-stats.json")
    a = ap.parse_args()

    budgets, base_netloc = load_budgets()
    root = Path(a.dir) if a.dir else build()
    pages = collect(root, budgets, base_netloc)

    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(pages, indent=2) + "\n")

    if a.page is not None:
        if a.page not in pages:
            sys.exit(f'no such built page: {a.page!r} (have: {", ".join(sorted(pages)) or "none"})')
        print_detail(a.page, pages[a.page], budgets)
    else:
        print_table(pages, budgets)
        print(f'\n{len(pages)} pages; full numbers in {a.json}')


if __name__ == "__main__":
    main()
