"""The code samples of data/stack.toml and data/repos.toml (partials/code-sample.html), checked by
tools/check_pages.py and runnable alone. Every entry with `code` may also have `code_wide` and `wide`:

- `code` is the narrow version: every line at most 44 columns.
- `code_wide` is the same code with natural line breaks: equal to `code` once all whitespace and `//` are removed
  (only line breaks, indentation and the re-flow of comments may differ). Every line at most 80 columns.
- `wide` is the column bucket of `code_wide`: 50, 60, 70 or 80, at least its longest line.
Usage: python3 tools/samples.py [FILE.toml ...] (default: both data files)
"""

import re
import sys
import tomllib

NARROW = 44
BUCKETS = (50, 60, 70, 80)


def norm(s):
    return re.sub(r"\s+", "", s.replace("//", ""))


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
    found = problems(sys.argv[1:] or ("data/stack.toml", "data/repos.toml"))
    print("\n".join(found) or "all samples fine")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
