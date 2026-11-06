"""Tests of tools/notify_plan.py, the Deploy workflow's choice to build and ship the notify service or not.

Usage: python3 tools/test_notify_plan.py (in `just test`)

Each case makes a small git repo in a temp folder: a commit standing for the live release, then the change, and asks
the plan with a fake probe answer. The last test checks this repo itself: nothing under server/ reads a site-only
path, since a change there would not ship.
"""

import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import notify_plan  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

FILES = {
    "Cargo.toml": "[workspace]\n",
    "Cargo.lock": "version = 4\n",
    "server/vhrd_notify/src/lib.rs": "pub fn f() {}\n",
    "deploy/notify.toml": "listen = 1\n",
    "deploy/vhrd-notify.service": "[Service]\n",
    ".github/workflows/deploy.yml": 'env:\n  RUST_TOOLCHAIN: "1.99.1"\n',
    "content/donguru.md": "Donguru\n",
    "CHANGELOG.md": "# Changelog\n",
    "config.toml": "title = 1\n",
}


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.git("init", "-q", "-b", "main")
        for path, text in FILES.items():
            self.write(path, text)
        self.live = self.commit("live")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def write(self, path, text, append=False):
        p = pathlib.Path(self.repo, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a" if append else "w") as f:
            f.write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def plan(self, got=None, force=False):
        if got is None:
            got = f"400 {self.live[:7]}"
        return notify_plan.plan(self.repo, got, force)

    def assertShips(self, got=None, force=False):
        ship, live, why = self.plan(got, force)
        self.assertTrue(ship, why)
        self.assertIsNone(live)

    def assertSkips(self):
        ship, live, why = self.plan()
        self.assertFalse(ship, why)
        self.assertEqual(live, self.live[:7])

    def test_unchanged(self):
        self.assertSkips()

    def test_site_only_change(self):
        self.write("content/donguru.md", "more\n", append=True)
        self.write("CHANGELOG.md", "- a line\n", append=True)
        self.write("config.toml", "x = 2\n", append=True)
        self.commit("site")
        self.assertSkips()

    def test_formatting_only(self):
        self.write("server/vhrd_notify/src/lib.rs", "pub fn f() {\n}\n")
        self.commit("fmt")
        self.assertShips()

    def test_rustfmt_settings(self):
        self.write("rustfmt.toml", "max_width = 120\n")
        self.commit("rustfmt")
        self.assertShips()

    def test_new_top_file(self):
        self.write("build-helper.txt", "x\n")
        self.commit("new")
        self.assertShips()

    def test_notify_toml(self):
        self.write("deploy/notify.toml", "consent = 2\n", append=True)
        self.commit("consent")
        self.assertShips()

    def test_unit(self):
        self.write("deploy/vhrd-notify.service", "Restart=no\n", append=True)
        self.commit("unit")
        self.assertShips()

    def test_cargo_lock(self):
        self.write("Cargo.lock", "[[package]]\n", append=True)
        self.commit("lock")
        self.assertShips()

    def test_toolchain_in_workflow(self):
        self.write(".github/workflows/deploy.yml", 'env:\n  RUST_TOOLCHAIN: "1.99.2"\n')
        self.commit("toolchain")
        self.assertShips()

    def test_toolchain_file(self):
        self.write("rust-toolchain.toml", '[toolchain]\nchannel = "1.99.1"\n')
        self.commit("toolchain file")
        self.assertShips()

    def test_live_newer_than_head(self):
        self.write("server/vhrd_notify/src/lib.rs", "pub fn g() {}\n")
        newer = self.commit("newer")
        self.git("checkout", "-q", "HEAD~1")
        self.assertShips(got=f"400 {newer[:7]}")

    def test_live_on_another_branch(self):
        self.git("checkout", "-q", "-b", "side")
        self.write("server/vhrd_notify/src/lib.rs", "pub fn side() {}\n")
        side = self.commit("side")
        self.git("checkout", "-q", "main")
        self.commit("main goes on")
        self.assertShips(got=f"400 {side[:7]}")

    def test_unknown_commit(self):
        self.assertShips(got="400 0123abc")

    def test_tag_named_like_the_live_sha(self):
        # a tag of that name pointing at HEAD must not make it look unchanged
        self.write("deploy/notify.toml", "consent = 2\n", append=True)
        head = self.commit("consent")
        self.git("tag", self.live[:7], head)
        self.assertShips()

    def test_no_header(self):
        self.assertShips(got="400 ")

    def test_fetch_failure(self):
        self.assertShips(got="")

    def test_other_status(self):
        self.assertShips(got=f"502 {self.live[:7]}")

    def test_bad_header(self):
        for got in (f"400 {self.live[:7]}-dirty", f"400 {self.live[:7]}, {self.live[:7]}", "400 --output=x", "400 HEAD"):
            self.assertShips(got=got)

    def test_force(self):
        self.assertShips(force=True)

    def test_not_a_repo(self):
        self.repo = self.tmp.name + "/nothing"
        self.assertShips()


class Inputs(unittest.TestCase):
    def test_server_reads_no_site_only_path(self):
        """No symlink under server/, and no path a source there names leaves it for a site-only path."""
        site_only = [ROOT / p for p in notify_plan.SITE_ONLY]
        for f in (ROOT / "server").rglob("*"):
            self.assertFalse(f.is_symlink(), f"{f} is a symlink")
            if f.suffix not in (".rs", ".toml") or "target" in f.parts:
                continue
            # relative to the file (include_str!) or to its crate (CARGO_MANIFEST_DIR)
            crate = next(d for d in f.parents if (d / "Cargo.toml").exists())
            for rel in re.findall(r'"((?:\.\./)+[^"]*)"', f.read_text()):
                for target in ((f.parent / rel).resolve(), (crate / rel).resolve()):
                    for p in site_only:
                        self.assertFalse(target == p or p in target.parents, f"{f} reads {rel}, a site-only path")


if __name__ == "__main__":
    unittest.main()
