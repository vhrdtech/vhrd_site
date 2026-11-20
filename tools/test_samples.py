"""Tests of tools/samples.py's `source` check: README, examples/NAME and a README inside the repo by its path.

Usage: python3 tools/test_samples.py (in `just test`)

Each case writes a small repo into a temp folder, points $VHRD_REPOS at it and checks an entry against it.
"""

import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import samples  # noqa: E402

README = "# demo\n\n```rust\n# fn main() {\nlet q = parse(\"4.7 uF\")?;\nassert_eq!(q.unit, Farad);\n# }\n```\n"
EXAMPLE = "fn main() {\n    let q = parse(\"1 V\");\n}\n"


class Source(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        repo = pathlib.Path(self.tmp.name) / "demo"
        for path, text in {"README.md": README, "crates/core/README.md": README, "examples/one.rs": EXAMPLE}.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text)
        self.saved = os.environ.get("VHRD_REPOS")
        os.environ["VHRD_REPOS"] = self.tmp.name

    def tearDown(self):
        if self.saved is None:
            del os.environ["VHRD_REPOS"]
        else:
            os.environ["VHRD_REPOS"] = self.saved
        self.tmp.cleanup()

    def check(self, source, code):
        return samples.check_source({"name": "demo", "source": source, "code": code})

    def test_readme_and_example(self):
        self.assertEqual(self.check("README", 'let q = parse("4.7 uF")?;'), ([], None))
        self.assertEqual(self.check("examples/one.rs", 'let q = parse("1 V");'), ([], None))

    def test_readme_inside_the_repo(self):
        code = 'let q = parse("4.7 uF")?;\nassert_eq!(\n    q.unit, Farad\n);'
        self.assertEqual(self.check("crates/core/README.md", code), ([], None))
        out, _ = self.check("crates/core/README.md", 'let q = parse("10 V")?;')
        self.assertEqual(len(out), 1)
        self.assertIn("not taken as it is", out[0])

    def test_missing_file_is_a_note(self):
        out, note = self.check("crates/other/README.md", "x")
        self.assertEqual(out, [])
        self.assertIn("not checked", note)

    def test_bad_sources_refused(self):
        for source in ("../other/README.md", "/etc/README.md", "crates/core/lib.rs", "examples", "docs/README.txt"):
            out, _ = self.check(source, "x")
            self.assertEqual(len(out), 1, source)
            self.assertIn("source must be", out[0])


if __name__ == "__main__":
    unittest.main()
