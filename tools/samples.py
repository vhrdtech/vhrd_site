"""The code samples of data/stack.toml and data/repos.toml (partials/code-sample.html), checked by
tools/check_pages.py and runnable alone. Every entry with `code` may also have `code_wide` and `wide`:

- `code` is the narrow version: every line at most 44 columns.
- `code_wide` is the same code with natural line breaks: equal to `code` once all whitespace, `//` and `#` are removed
  (only line breaks, indentation and the re-flow of comments may differ). Every line at most 80 columns.
- `wide` is the column bucket of `code_wide`: 50, 60, 70 or 80, at least its longest line.
- `source` (data/repos.toml): where the sample is taken from as it is, `README` (a code block of README.md) or
  `examples/NAME`. The sample is consecutive whole lines of it; only line breaks, indentation and the re-flow of
  comments differ, and rustdoc's hidden `# ` lines are left out. Checked against a checkout in $VHRD_REPOS/NAME
  (default ~/git), and skipped with a note where there is none. Not compiled.
Usage: python3 tools/samples.py [FILE.toml ...] (default: both data files)
"""

import os
import pathlib
import re
import sys
import tomllib

NARROW = 44
BUCKETS = (50, 60, 70, 80)


def norm(s):
    """Code without whitespace and comment markers (`//`, `#`), so line breaks and re-flowed comments compare equal."""
    return re.sub(r"\s+", "", s.replace("//", "").replace("#", ""))


def readme_blocks(text):
    """The fenced code blocks of a README, as lists of lines; rustdoc's hidden lines are dropped from Rust blocks."""
    blocks, cur, rust = [], None, False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            if cur is None:
                cur, rust = [], line.strip()[3:].startswith("rust")
            else:
                blocks.append(cur)
                cur = None
        elif cur is not None and not (rust and re.match(r"#(\s|$)", line)):
            cur.append(line)
    return blocks


def from_block(sample, block):
    """Whether the sample is a run of consecutive whole lines of the block, up to whitespace and comment re-flow."""
    want = norm(sample)
    parts = [norm(line) for line in block]
    parts = [p for p in parts if p]
    for start in range(len(parts)):
        rest = want
        for part in parts[start:]:
            if not rest.startswith(part):
                break
            rest = rest[len(part):]
            if rest == "":
                return True
    return False


def check_source(entry):
    """`source`: every version of the sample comes from one code block of the repo's README.md, or from the file
    under examples/ it names."""
    source = entry.get("source")
    if not source:
        return [], None
    if source != "README" and not source.startswith("examples/"):
        return [f"{entry['name']}: source must be README or examples/NAME, not {source!r}"], None
    repos = pathlib.Path(os.environ.get("VHRD_REPOS", pathlib.Path.home() / "git"))
    path = repos / entry["name"] / ("README.md" if source == "README" else source)
    if not path.exists():
        return [], f"{entry['name']}: no {path}, its sample is not checked"
    text = path.read_text()
    blocks = readme_blocks(text) if path.suffix == ".md" else [text.split("\n")]
    out = []
    for key in ("code", "code_wide"):
        if entry.get(key) and not any(from_block(entry[key], b) for b in blocks):
            out.append(f"{entry['name']}: {key} is not taken as it is from {path}")
    return out, None


def width(s):
    return max((len(line) for line in s.strip("\n").split("\n")), default=0)


def check(entry):
    out = []
    name = entry.get("name", "?")
    code = entry.get("code")
    if not code:
        if entry.get("code_wide"):
            out.append(f"{name}: code_wide without code")
        return out
    if width(code) > NARROW:
        out.append(f"{name}: code is {width(code)} columns, at most {NARROW}")
    out += check_source(entry)[0]
    wide = entry.get("code_wide")
    if wide is None:
        return out
    if norm(wide) != norm(code):
        a, b = norm(code), norm(wide)
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
        out.append(f"{name}: code_wide is not the same code as code (first difference near {a[max(0, i - 20):i + 20]!r} / {b[max(0, i - 20):i + 20]!r})")
    if entry.get("wide") not in BUCKETS:
        out.append(f"{name}: wide must be one of {BUCKETS}")
    elif width(wide) > entry["wide"]:
        out.append(f"{name}: code_wide is {width(wide)} columns, more than wide = {entry['wide']}")
    return out


def problems(paths=("data/stack.toml", "data/repos.toml")):
    out = []
    for path in paths:
        data = tomllib.load(open(path, "rb"))
        out += [f"{path}: {p}" for key in ("repo", "crate") for e in data.get(key, []) for p in check(e)]
    return out


def main():
    paths = sys.argv[1:] or ("data/stack.toml", "data/repos.toml")
    for path in paths:
        for e in tomllib.load(open(path, "rb")).get("repo", []):
            note = check_source(e)[1]
            if note:
                print(f"{path}: note: {note}")
    found = problems(paths)
    print("\n".join(found) or "all samples fine")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
