# /// script
# requires-python = ">=3.11"
# dependencies = ["pyte>=0.8.2"]
# ///
"""Record our tools' real terminal output for the site: each command runs once in a pseudo-terminal, a terminal
emulator (pyte) keeps the screen with its colours, and the screen is written as static HTML.

Usage: uv run tools/term_capture.py [ID ...] [--bin NAME=PATH ...] [--cast ID=FILE ...]

The captures are listed in data/term/captures.toml: the command as typed, where it runs, the terminal's size, and for
a full-screen program (a TUI) how long to wait before the screen is taken and the keys that end it. `steps` instead of
`cmd` runs several commands one after the other on one screen, each on its own prompt line. `remap` turns
paths under the home and the toolchain's sources into what any machine shows (rustc's --remap-path-prefix), `target`
is the cargo target dir under this repo. Without IDs every
capture is recorded again. `--bin` runs another binary for a command's name, e.g. one just built in a target dir.
A capture with `cast = true` is not run here: it was recorded on a bench with its hardware (asciinema, an asciicast v2
file given with `--cast`), and the same emulator replays it to the second `at`; its version and source are written in
captures.toml, as the recording's notes give them.

For each capture it writes data/term/ID.html, the screen as <span>s in classes (data/term/README.md), and
data/term/ID.toml: the command, the program's version (its `--version` line), the commit of the checkout it ran in,
the size and the date. The `vh.term` component shows them on a page; nothing runs when the site is built.

Nothing private may reach a capture: it refuses to write one that holds a home path, this PC's host or user name, a
machine name of ours or a tpm id, and says where.
"""

import argparse
import datetime
import getpass
import html
import json
import os
import pty
import re
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import termios
import fcntl
import time
import tomllib
from pathlib import Path

import pyte

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/term"
NAMED = {"black", "red", "green", "brown", "blue", "magenta", "cyan", "white"}
PRIVATE = [
    (re.compile(r"/home/|/Users/|/root\b"), "a home path"),
    (re.compile(r"\b(build|core|hetzner)-\d\b|omarchy|gpd-"), "a machine name"),
    (re.compile(r"\bP\d{4}\b|#\d{1,2}[a-z]{3}-\d{4}"), "a tpm id"),
]


class Screen(pyte.Screen):
    """pyte keeps no faint (SGR 2); the tools use it for tree lines and docs. It is kept in the blink flag, which
    none of them uses, and shown as faint."""

    def select_graphic_rendition(self, *attrs, **kw):
        mapped, i = [], 0
        while i < len(attrs):
            a = attrs[i]
            if a in (38, 48):  # a colour: 38;5;n or 38;2;r;g;b, whose 2 and 5 are not faint and blink
                n = 3 if attrs[i + 1:i + 2] == (5,) else 5
                mapped += attrs[i:i + n]
                i += n
                continue
            mapped += [5] if a == 2 else [22, 25] if a == 22 else [a]
            i += 1
        super().select_graphic_rendition(*mapped, **kw)


def run(argv, cwd, env, cols, rows, wait, keys):
    """Run argv in a pseudo-terminal of cols x rows; answer the bytes it wrote. A program that ends by itself is read
    to its end; a TUI (wait > 0) is read for `wait` seconds, then sent `keys` and given a second to quit."""
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvpe(argv[0], argv, env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    os.kill(pid, signal.SIGWINCH)
    out = bytearray()
    start = time.monotonic()
    sent = False
    while True:
        if wait and not sent and time.monotonic() - start >= wait:
            snapshot = bytes(out)
            os.write(fd, keys.encode())
            sent = True
            quit_by = time.monotonic() + 1
        if sent and time.monotonic() > quit_by:
            os.kill(pid, signal.SIGKILL)
            break
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            out += data
    os.waitpid(pid, 0)
    return snapshot if wait else bytes(out)


def style(c, fg, bg):
    """The classes and inline colour of one cell: named colours as classes (their tokens are in site.css), the
    256-colour and true-colour ones as the program's own value."""
    cls, css = [], []
    if c.reverse:
        fg, bg = (bg if bg != "default" else "bg"), (fg if fg != "default" else "fg")
    for kind, v in (("f", fg), ("b", bg)):
        if v == "default":
            continue
        name = v.removeprefix("bright")
        if name in NAMED or v in ("fg", "bg"):
            cls.append(f"{kind}-{v}")
        elif re.fullmatch(r"[0-9a-f]{6}", v):
            css.append(f"{'color' if kind == 'f' else 'background'}:#{v}")
    if c.bold:
        cls.append("t-b")
    if c.blink:
        cls.append("t-d")
    if c.italics:
        cls.append("t-i")
    if c.underscore:
        cls.append("t-u")
    return " ".join(cls), ";".join(css)


def render(screen, rows_used):
    """The screen as lines of spans, trailing blanks dropped."""
    lines = []
    for y in range(rows_used):
        row = screen.buffer[y]
        cells = [row[x] for x in range(screen.columns)]
        while cells and cells[-1].data in (" ", "") and cells[-1].bg == "default" and not cells[-1].reverse:
            cells.pop()
        parts, cur, text = [], None, ""
        for c in cells:
            key = style(c, c.fg, c.bg)
            if key != cur and text:
                parts.append(span(cur, text))
                text = ""
            cur = key
            text += c.data or " "
        if text:
            parts.append(span(cur, text))
        lines.append("".join(parts))
    while lines and not lines[-1]:
        lines.pop()
    # An empty line would end the HTML block where a Markdown page holds the capture: an empty span keeps it one
    return [line or "<span></span>" for line in lines]


def span(key, text):
    cls, css = key
    if not cls and not css:
        return html.escape(text, quote=False)
    attrs = (f' class="{cls}"' if cls else "") + (f' style="{css}"' if css else "")
    return f"<span{attrs}>{html.escape(text, quote=False)}</span>"


def private(text):
    found = [what for rx, what in PRIVATE if rx.search(text)]
    for word, what in ((socket.gethostname(), "this PC's host name"), (getpass.getuser(), "the user name")):
        if re.search(rf"\b{re.escape(word)}\b", text):
            found.append(what)
    return found


def replay(file, at):
    """The bytes an asciicast v2 recording wrote up to second `at`, and its width and height."""
    lines = Path(file).read_text().splitlines()
    head = json.loads(lines[0])
    out = "".join(e[2] for e in map(json.loads, lines[1:]) if e[1] == "o" and e[0] <= at)
    return out.encode(), head["width"], head["height"]


def first_line(argv, cwd, env):
    r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
    return (r.stdout or r.stderr).strip().splitlines()[0]


def capture(c, bins, casts):
    if c.get("cast"):
        if c["id"] not in casts:
            sys.exit(f"{c['id']}: recorded on a bench, give the recording: --cast {c['id']}=FILE")
        raw, cols, rows = replay(casts[c["id"]], c["at"])
        return write(c, raw, cols, rows, c["version"], c["source"], tui=True)
    cwd = (ROOT / os.path.expanduser(c["cwd"])).resolve()
    env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor", CLICOLOR_FORCE="1", COLUMNS=str(c["cols"]),
               LINES=str(c.get("rows", 400)), **c.get("env", {}))
    env.pop("NO_COLOR", None)
    if c.get("remap"):
        # rustc's own --remap-path-prefix: a path under this home reads as it would on any machine
        sysroot = subprocess.run(["rustc", "--print", "sysroot"], capture_output=True, text=True).stdout.strip()
        commit = subprocess.run(["rustc", "-vV"], capture_output=True, text=True).stdout.split("commit-hash: ")[1].split()[0]
        fill = lambda s: s.replace("{sysroot}", sysroot).replace("{commit}", commit)  # noqa: E731
        env["RUSTFLAGS"] = " ".join(f"--remap-path-prefix={os.path.expanduser(fill(a))}={fill(b)}" for a, b in c["remap"])
    if c.get("target"):
        env["CARGO_TARGET_DIR"] = str(ROOT / c["target"])
    steps = c.get("steps") or [c["cmd"]]
    rows = c.get("rows", 400)
    raw = b""
    for i, step in enumerate(steps):
        exe = bins.get(step[0]) or shutil.which(step[0], path=env["PATH"] + ":" + os.path.expanduser("~/.local/bin"))
        if not exe:
            sys.exit(f"{c['id']}: {step[0]} not found (--bin {step[0]}=PATH)")
        if len(steps) > 1:  # each step on its own prompt line, as typed, a blank line before the next
            raw += (b"\r\n" if i else b"") + f"\x1b[32m$ \x1b[0m{' '.join(step)}\r\n".encode()
        raw += run([exe] + step[1:], cwd, env, c["cols"], rows, c.get("wait", 0), c.get("keys", "q"))
    exe = bins.get(steps[0][0]) or shutil.which(steps[0][0], path=env["PATH"] + ":" + os.path.expanduser("~/.local/bin"))
    version = first_line(c.get("version", [exe, "--version"]), cwd, env)
    commit = subprocess.run(["git", "-C", str(cwd), "describe", "--always", "--dirty", "--abbrev=8"],
                            capture_output=True, text=True).stdout.strip()
    source = c.get("source") or (f"{c['repo']} at {commit}" if commit else c["repo"])
    return write(c, raw, c["cols"], rows, version, source, tui=bool(c.get("wait")))


def write(c, raw, cols, rows, version, source, tui):
    """Feed the bytes to a terminal of cols x rows, check the screen for anything private and write it."""
    screen = Screen(cols, rows)
    pyte.ByteStream(screen).feed(raw)
    lines = render(screen, rows)
    meta = {
        "id": c["id"],
        "cmd": "; ".join(" ".join(step) for step in c.get("steps") or [c["cmd"]]),
        "version": version,
        "source": source,
        "size": f"{cols}×{rows if tui else len(lines)}",
        "recorded": datetime.date.today().isoformat(),
    }
    page = "\n".join(lines)
    text = re.sub(r"<[^>]+>", "", page) + "\n" + "\n".join(meta.values())
    if bad := private(text):
        sys.exit(f"{c['id']}: not written, it holds {', '.join(sorted(set(bad)))}")
    head = (f"<!-- tools/term_capture.py {c['id']}: `{meta['cmd']}`, {meta['version']}, {meta['source']}, "
            f"{meta['size']}, recorded {meta['recorded']}. Recorded, not edited: run it again to change it. -->\n")
    (OUT / f"{c['id']}.html").write_text(head + page + "\n")
    (OUT / f"{c['id']}.toml").write_text("".join(f'{k} = "{v}"\n' for k, v in meta.items()))
    print(f"{c['id']}: {len(lines)} lines, {meta['version']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--bin", action="append", default=[], help="NAME=PATH: run PATH for the command NAME")
    ap.add_argument("--cast", action="append", default=[], help="ID=FILE: the asciicast of a bench capture")
    a = ap.parse_args()
    bins = dict(b.split("=", 1) for b in a.bin)
    casts = dict(b.split("=", 1) for b in a.cast)
    caps = tomllib.loads((OUT / "captures.toml").read_text())["capture"]
    unknown = set(a.ids) - {c["id"] for c in caps}
    if unknown:
        sys.exit(f"no such capture: {', '.join(sorted(unknown))}")
    for c in caps:
        if not a.ids or c["id"] in a.ids:
            capture(c, bins, casts)


if __name__ == "__main__":
    main()
