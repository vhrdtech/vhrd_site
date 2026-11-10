"""Tests of tools/page_stats.py's metric functions, on small HTML fixtures (no zola build, no network).

Usage: python3 tools/test_page_stats.py (in `just test`)
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import page_stats as ps  # noqa: E402

PAGE = '<html lang="en"><head></head><body><main id="main">{}</main></body></html>'


def analyze(main_html, budgets=None):
    return ps.analyze_html(PAGE.format(main_html), "vhrd.tech", budgets or ps.DEFAULT_BUDGETS)


class Words(unittest.TestCase):
    def test_counts_paragraph_text(self):
        m = analyze("<p>Four short words here.</p>")
        self.assertEqual(m["word_count"], 4)
        self.assertEqual(m["paragraph_max_words"], 4)
        self.assertEqual(m["paragraph_median_words"], 4)

    def test_heading_counted_separately_not_mixed_into_prose(self):
        m = analyze("<h2>Two Words</h2><p>One paragraph of five whole words.</p>")
        self.assertEqual(m["headings"], 1)
        self.assertEqual(m["heading_list"], [(2, 2)])
        self.assertEqual(m["word_count"], 2 + 6)
        self.assertEqual(m["paragraph_max_words"], 6)  # the heading's words never land in a paragraph

    def test_header_footer_nav_outside_main_are_never_read(self):
        html = ('<html lang="en"><body><header><p>Ignore me and every other word here too.</p></header>'
                '<main id="main"><p>Count me.</p></main>'
                '<footer><p>Ignore me as well, several words long.</p></footer></body></html>')
        m = ps.analyze_html(html, "vhrd.tech", ps.DEFAULT_BUDGETS)
        self.assertEqual(m["word_count"], 2)


class NestedParagraphs(unittest.TestCase):
    """Regression: a list of cards (<li> wrapping its own <h3> and <p>) must not merge every card's text
    into one giant paragraph attributed to the outer <li>."""

    def test_list_of_cards_keeps_each_paragraph_separate(self):
        html = (
            "<ul>"
            "<li><h3>Card one</h3><p>Five short words make this one.</p></li>"
            "<li><h3>Card two</h3><p>A different sentence of seven little words indeed.</p></li>"
            "</ul>"
        )
        m = analyze(html)
        self.assertEqual(m["headings"], 2)
        # Each <li>'s own paragraph is 6 and 8 words; the outer <li> contributes nothing extra.
        self.assertEqual(sorted(m["heading_list"]), [(3, 2), (3, 2)])
        self.assertEqual(m["paragraph_max_words"], 8)
        self.assertEqual(m["word_count"], 2 + 2 + 6 + 8)

    def test_skip_region_inside_an_open_paragraph_is_excluded(self):
        # A <li> opens a paragraph accumulator; a <table> nested inside it must still be excluded from that
        # paragraph's text even though the <li> around it is still "open".
        html = "<li>Before the table. <table><tr><td>cell words here</td></tr></table> After it.</li>"
        m = analyze(html)
        self.assertEqual(m["word_count"], len("Before the table.".split()) + len("After it.".split()))


class Runs(unittest.TestCase):
    def test_breaks_reset_the_run(self):
        html = "<p>one two three</p><h2>Break</h2><p>one two three four five</p>"
        m = analyze(html)
        self.assertEqual(m["runs"], [3, 5])
        self.assertEqual(m["longest_run_words"], 5)

    def test_figure_table_video_and_cta_are_breaks(self):
        html = (
            "<p>a b c</p>"
            '<figure class="fig"><img src="x.webp" alt="x"></figure>'
            "<p>d e</p>"
            "<table><tr><td>x</td></tr></table>"
            "<p>f g h i</p>"
            "<video src='x.mp4'></video>"
            "<p>j</p>"
            '<a class="v-btn" href="/x/">Go</a>'
            "<p>k l</p>"
        )
        m = analyze(html)
        self.assertEqual(m["runs"], [3, 2, 4, 1, 2])
        self.assertEqual(m["images"], 1)
        self.assertEqual(m["ctas"], 1)

    def test_runs_over_budget(self):
        words = " ".join(["word"] * 300)
        m = analyze(f"<p>{words}</p>")
        self.assertEqual(m["runs_over_budget"], 1)
        self.assertEqual(m["longest_run_words"], 300)


class Figures(unittest.TestCase):
    def test_image_figure_counts_and_alt_check(self):
        html = (
            '<figure class="fig"><img src="a.webp" alt="A board"></figure>'
            '<figure class="fig"><img src="b.webp"></figure>'
        )
        m = analyze(html)
        self.assertEqual(m["images"], 2)
        self.assertEqual(m["images_without_alt"], 1)

    def test_empty_alt_is_not_without_alt(self):
        html = '<figure class="fig"><img src="icon.webp" alt=""></figure>'
        m = analyze(html)
        self.assertEqual(m["images_without_alt"], 0)

    def test_terminal_capture_is_not_counted_as_an_image(self):
        html = '<figure class="fig term-fig"><pre class="term-screen">$ cnt tui</pre></figure>'
        m = analyze(html)
        self.assertEqual(m["images"], 0)
        self.assertEqual(m["terminal_captures"], 1)
        self.assertEqual(m["code_blocks"], 0)  # the <pre> inside a term-fig is not a separate code block

    def test_decorative_icon_outside_a_figure_does_not_count(self):
        html = "<h3><img class='card-icon' src='i.webp' alt=''> Title</h3><p>Some words of prose here now.</p>"
        m = analyze(html)
        self.assertEqual(m["images"], 0)


class CodeAndLinksAndCtas(unittest.TestCase):
    def test_code_block_outside_a_figure_is_counted(self):
        html = '<div class="code-tabs"><pre><code>fn main() {}</code></pre></div>'
        m = analyze(html)
        self.assertEqual(m["code_blocks"], 1)
        self.assertEqual(m["word_count"], 0)  # code is never prose

    def test_inline_code_in_prose_is_not_a_break_and_is_not_a_code_block(self):
        m = analyze("<p>Run <code>dg</code> to see the version.</p>")
        self.assertEqual(m["code_blocks"], 0)
        self.assertEqual(len(m["runs"]), 1)
        self.assertEqual(m["word_count"], 6)  # inline code text still reads as prose

    def test_links_classified_internal_and_external(self):
        html = ('<p><a href="/donguru/">a</a> <a href="#notify">b</a> '
                '<a href="https://vhrd.tech/software/">c</a> <a href="https://github.com/vhrdtech/x">d</a></p>')
        m = analyze(html)
        self.assertEqual(m["links_internal"], 3)
        self.assertEqual(m["links_external"], 1)

    def test_cta_button_and_cta_link_both_count(self):
        html = '<button class="v-btn v-primary" type="submit">Go</button><a class="v-btn" href="/x/">Go</a>'
        m = analyze(html)
        self.assertEqual(m["ctas"], 2)
        self.assertEqual(m["links_internal"], 1)  # the button has no href

    def test_mail_link_without_href_is_not_counted(self):
        m = analyze('<a data-mail="contact" data-d="vhrd.tech">contact at vhrd.tech</a>')
        self.assertEqual(m["links_internal"], 0)
        self.assertEqual(m["links_external"], 0)


class SyllablesSentencesFlesch(unittest.TestCase):
    def test_syllables_common_words(self):
        self.assertEqual(ps.syllables("the"), 1)
        self.assertEqual(ps.syllables("hello"), 2)
        self.assertEqual(ps.syllables("code"), 1)
        self.assertEqual(ps.syllables("table"), 2)

    def test_split_sentences_basic(self):
        s = ps.split_sentences("One sentence here. And a second one! Is this a third?")
        self.assertEqual(len(s), 3)

    def test_split_sentences_empty(self):
        self.assertEqual(ps.split_sentences("   "), [])

    def test_flesch_reading_ease_known_shape(self):
        # Harder text (longer words and sentences) must score lower than easier text.
        easy = analyze("<p>The cat sat on the mat. It was a good day.</p>")
        hard = analyze("<p>Extraordinarily complicated administrative documentation requires considerable "
                        "comprehension before implementation proceeds successfully.</p>")
        self.assertIsNotNone(easy["flesch_reading_ease"])
        self.assertIsNotNone(hard["flesch_reading_ease"])
        self.assertGreater(easy["flesch_reading_ease"], hard["flesch_reading_ease"])

    def test_flesch_is_none_without_sentences(self):
        m = analyze("")
        self.assertIsNone(m["flesch_reading_ease"])

    def test_flesch_is_none_for_a_non_english_page(self):
        html = PAGE.format("<p>Dette er en side med nok ord til en setning.</p>").replace('lang="en"', 'lang="nb"')
        m = ps.analyze_html(html, "vhrd.tech", ps.DEFAULT_BUDGETS)
        self.assertIsNone(m["flesch_reading_ease"])


class ReadingTime(unittest.TestCase):
    def test_words_only(self):
        budgets = dict(ps.DEFAULT_BUDGETS, wpm=200)
        self.assertAlmostEqual(ps.reading_minutes(400, 0, budgets), 2.0)

    def test_image_falloff_matches_medium_shape(self):
        budgets = dict(ps.DEFAULT_BUDGETS, wpm=200, image_first_seconds=12, image_min_seconds=3,
                        image_falloff_count=10)
        # images 1..10 cost 12, 11, ..., 3 seconds; the 11th costs the floor (3s) too.
        costs = [ps.image_cost(i, budgets) for i in range(1, 12)]
        self.assertEqual(costs, [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 3])

    def test_single_image_uses_the_floor_when_falloff_count_is_one(self):
        budgets = dict(ps.DEFAULT_BUDGETS, image_falloff_count=1, image_min_seconds=3, image_first_seconds=12)
        self.assertEqual(ps.image_cost(1, budgets), 3)


if __name__ == "__main__":
    unittest.main()
