"""Decide whether the Deploy workflow builds and ships the notify service (AGENTS.md "Notify service").

Usage: python3 tools/notify_plan.py [--force[=true|false]] [--got "CODE SHA"] [--repo DIR]

Standard library only: the deploy workflow runs it with the runner's python3, without uv.

It ships the service unless all of this holds, safety over speed:
- the run was not asked to ship it (--force, or --force=true from the workflow's input `notify`);
- https://vhrd.tech/api/notify answers the probe with 400 and a short sha in x-vhrd-release;
- that sha names one commit here (the full sha starts with it, so a tag or branch of that name can't stand in), and
  that commit is an ancestor of HEAD;
- nothing changed between the two outside SITE_ONLY, the paths that only the site uses. It is a list of what does
  not feed the service, so a new file anywhere else (and any change to the workflow) ships it.

--got takes the probe's answer as `CODE SHA` instead of asking the server (the tests). The decision goes to
$GITHUB_OUTPUT (`ship=true`, or `ship=false` and `git=SHA`) and a line to $GITHUB_STEP_SUMMARY when they are set, and
to stdout. The header is checked against its shape before git sees it or anything prints it.
"""

import argparse
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

URL = "https://vhrd.tech/api/notify"
HEADER = "x-vhrd-release"

# Paths nothing of the service, its tests, its settings, the setup files or their build reads. Everything else is
# an input. A file under server/ that reads one of these (include_str!, a symlink) makes it one: the tests check
# that none does.
SITE_ONLY = [
    "content",
    "templates",
    "static",
    "data",
    "tools",
    "scripts",
    "config.toml",
    "CHANGELOG.md",
    "FEATURES.md",
    "AGENTS.md",
    "README.md",
    "CLAUDE.md",
    "LICENSE-APACHE",
    "LICENSE-MIT",
    "justfile",
    "ship.toml",
    ".gitignore",
    ".github/deploy",
    "deploy/redirects.map",
    "deploy/old-urls.txt",
    "deploy/golden-links.txt",
    "deploy/nginx-notify.conf",
]


def probe(url):
    """The probe's answer as `CODE SHA`, or "" when the server can't be reached."""
    req = urllib.request.Request(
        url,
        data=b"probe=1",
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return f"{r.status} {r.headers.get(HEADER, '')}"
    except urllib.error.HTTPError as e:
        return f"{e.code} {e.headers.get(HEADER, '')}"
    except (urllib.error.URLError, OSError):
        return ""


def git(repo, *args):
    """git's exit code and its stdout."""
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def plan(repo, got, force):
    """(ship, live sha or None, why)"""
    if force:
        return True, None, "as the run was asked to"
    m = re.fullmatch(r"400 ([0-9a-f]{7,12})", got)
    if not m:
        return True, None, "as the live release is not known"
    live = m.group(1)
    code, commit = git(repo, "rev-parse", "--verify", "--quiet", f"{live}^{{commit}}")
    if code != 0 or not commit.startswith(live):
        return True, None, f"as the live release {live} is not one commit here"
    code, _ = git(repo, "merge-base", "--is-ancestor", commit, "HEAD")
    if code != 0:
        return True, None, f"as the live release {live} is not an ancestor of this commit"
    # 0: no change, 1: a change, anything else an error; only 0 skips
    code, _ = git(repo, "diff", "--quiet", "--no-ext-diff", commit, "HEAD", "--", ".", *(f":!{p}" for p in SITE_ONLY))
    if code != 0:
        return True, None, f"as it changed since the live release {live}"
    return False, live, f"unchanged since the live release {live}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", nargs="?", const="true", default="false", choices=["true", "false", ""])
    ap.add_argument("--got")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    got = a.got if a.got is not None else probe(URL)
    ship, live, why = plan(a.repo, got, a.force == "true")
    out = ["ship=true"] if ship else ["ship=false", f"git={live}"]
    line = f"### vhrd_notify: built and shipped, {why}" if ship else f"### vhrd_notify: {why}, not built or shipped"
    for name, text in (("GITHUB_OUTPUT", "\n".join(out)), ("GITHUB_STEP_SUMMARY", line)):
        if os.environ.get(name):
            with open(os.environ[name], "a") as f:
                f.write(text + "\n")
    print("\n".join(out))
    print(line)


if __name__ == "__main__":
    sys.exit(main())
