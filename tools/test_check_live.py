"""Tests of tools/check_live.py's redirect checks: a golden link may redirect, and its #fragment must exist on the
page it lands on.

Usage: python3 tools/test_check_live.py (in `just test`)

Each case writes a small build folder, a redirect map and a golden-links file into a temp folder, then runs
`redirects` on them. The last test checks this repo's own files: /donguru/ and /donguru/#notify lead to /portwright/.
"""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import check_live  # noqa: E402

MAP = """map $uri $vhrd_redirect {
    default "";
    ~^/old/?$   /new/;
}
"""


class Golden(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.build = root / "build"
        for page, html in {"": "<p>home</p>", "new/": '<section id="notify">x</section>'}.items():
            (self.build / page).mkdir(parents=True, exist_ok=True)
            (self.build / page / "index.html").write_text(html)
        self.saved = check_live.MAP, check_live.OLD, check_live.GOLDEN
        check_live.MAP, check_live.OLD, check_live.GOLDEN = root / "map", root / "old", root / "golden"
        check_live.MAP.write_text(MAP)
        check_live.OLD.write_text("")

    def tearDown(self):
        check_live.MAP, check_live.OLD, check_live.GOLDEN = self.saved
        self.tmp.cleanup()

    def problems(self, *golden):
        check_live.GOLDEN.write_text("# promised\n" + "".join(f"{g}\n" for g in golden))
        return check_live.redirects(self.build)

    def test_page_and_redirect_pass(self):
        self.assertEqual(self.problems("/", "/new/", "/old/", "/old"), [])

    def test_fragment_on_the_page_it_lands_on(self):
        self.assertEqual(self.problems("/new/#notify", "/old/#notify"), [])

    def test_missing_fragment_fails(self):
        got = self.problems("/old/#gone", "/new/#gone")
        self.assertEqual(len(got), 2, got)
        self.assertIn("no id 'gone'", got[0])

    def test_broken_link_fails(self):
        got = self.problems("/nowhere/", "/nowhere/#notify")
        self.assertEqual(len(got), 2, got)
        self.assertIn("breaks it", got[0])

    def test_site_fetches_the_path_only(self):
        rules = check_live.redirect_map()
        golden = [link.partition("#")[0] for link in ["/old/#notify", "/new/"]]
        self.assertEqual(check_live.one_per_rule(golden, rules), ["/old/"])


class Repo(unittest.TestCase):
    def test_old_product_page_redirects(self):
        rules = check_live.redirect_map()
        for path in ("/donguru/", "/donguru"):
            self.assertEqual(check_live.redirect_for(path, rules), "/portwright/")
        golden = check_live.golden_paths()
        self.assertIn("/donguru/", golden)
        self.assertIn("/donguru/#notify", golden)


if __name__ == "__main__":
    unittest.main()
