"""Tests of the placeholders that replace the TikZ blocks in the tex given to make4ht, and of the generated
tex4ht configuration."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tikz2html.config import Config
from tikz2html.html_build import (hcode_escape, fill_template, placeholder, replace_blocks, restrict_subfiles,
                                  tex4ht_config, make4ht_build_file, Fragments)
from tikz2html.latex_scan import scan, strip_comments, assign_ids


def make_config(**kwargs):
    config = Config(main_name="main", root=tempfile.gettempdir(), **kwargs)
    config.normalize()
    return config


def blocks_of(text, config):
    blocks, skipped = scan(strip_comments(text), config.scan_config)
    return assign_ids(blocks, config.scan_config), skipped


class TestEscaping(unittest.TestCase):
    def test_plain_html_is_unchanged(self):
        self.assertEqual(hcode_escape('<img src="svgs/a-b.svg" alt="x" />'), '<img src="svgs/a-b.svg" alt="x" />')

    def test_special_characters(self):
        escaped = hcode_escape("a#b%c&d{e}f_g^h$i~j\\k")
        for c in "#%&{}_^$~":
            self.assertNotIn(c, escaped.replace("\\" + c, "").replace("\\string" + c, "")
                             .replace("\\TikzSvgPercent ", "").replace("\\TikzSvgLbrace ", "")
                             .replace("\\TikzSvgRbrace ", "").replace("\\string\\\\", ""),
                             f"{c} not escaped in {escaped}")

    def test_no_empty_groups(self):
        # \HCode writes {} literally into the html
        self.assertNotIn("{}", hcode_escape("100% {x}"))

    def test_braces_stay_balanced(self):
        escaped = hcode_escape("{{{")
        depth = 0
        for c in escaped:
            depth += {"{": 1, "}": -1}.get(c, 0)
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)

    def test_fill_template_leaves_unknown_braces(self):
        self.assertEqual(fill_template("{a} {b} {{c}}", a=1), "1 {b} {{c}}")


class TestPlaceholders(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def ph(self, text, svg_info=None):
        """The placeholder, followed by the html of the fragments it uses (one per line)."""
        blocks, _ = blocks_of(text, self.config)
        self.assertEqual(len(blocks), 1)
        fragments = Fragments(self.config)
        p = placeholder(blocks[0], self.config, svg_info or {}, fragments)
        used = [html for key, html in fragments.html.items() if not key.startswith("number") and key != "empty"]
        return p + "\n" + "\n".join(used)

    def test_numbered_equation(self):
        p = self.ph("\\begin{equation}\\label{eq:a}\\tikzfig{a}\\end{equation}")
        self.assertTrue(p.startswith("\\TikzSvgDisplay{display:eq-a:before}{\\TikzSvgEq{eq:a}}"
                                     "{display:eq-a:after}\n"), p)
        self.assertIn('<table class="equation">', p)
        self.assertIn("svgs/eq-a.svg", p)

    def test_unnumbered_equation(self):
        p = self.ph("\\[\\tikzfig{a}\\]")
        self.assertTrue(p.startswith("\\TikzSvgDisplay{display:a}{}{empty}\n"), p)
        self.assertIn("equation-star", p)

    def test_unlabeled_numbered_equation_still_steps_the_counter(self):
        # Otherwise the numbers of all later equations would differ from the pdf
        p = self.ph("\\begin{equation}\\tikzfig{a}\\end{equation}")
        self.assertIn("\\TikzSvgEq{}", p)

    def test_align_with_two_numbers(self):
        p = self.ph("\\begin{align}\\tikzfig{a}\\label{eq:a} \\\\ \\tikzfig{b}\\label{eq:b}\\end{align}")
        self.assertIn("{\\TikzSvgEq{eq:a}\\TikzSvgEq{eq:b}}", p)

    def test_tag(self):
        p = self.ph("\\begin{equation}\\label{eq:s}\\tikzfig{a}\\tag{S4}\\end{equation}")
        self.assertIn("{\\TikzSvgTag{S4}{eq:s}}", p)

    def test_tag_star(self):
        p = self.ph("\\begin{equation}\\tikzfig{a}\\tag*{S4}\\end{equation}")
        self.assertIn("{\\TikzSvgTagStar{S4}{}}", p)

    def test_inline(self):
        p = self.ph("text $\\tikzfig{a}$ text", {"a": {"width": 30, "height": 12, "depth": 3, "linked": False}})
        self.assertTrue(p.startswith('\\TikzSvgHtml{inline:a}\n<img src="svgs/a.svg"'), p)
        self.assertIn("vertical-align: -4.00px", p)  # 3pt = 4px
        self.assertIn('width="40.00" height="16.00"', p)

    def test_inline_with_links_is_an_object(self):
        # The links in an <img> can't be clicked
        p = self.ph("text $\\tikzfig{a}$ text", {"a": {"width": 30, "height": 12, "depth": 3, "linked": True}})
        self.assertIn('\n<object data="svgs/a.svg"', p)
        self.assertIn("vertical-align: -4.00px", p)

    def test_display_size_is_scaled(self):
        # The size is set explicitly instead of with a css transform, which made the diagrams overlap the text
        self.config.svg_scale = 1.5
        p = self.ph("\\[\\tikzfig{a}\\]", {"a": {"width": 30, "height": 12, "depth": 0}})
        self.assertIn('width="60.00" height="24.00"', p)
        self.assertIn("aspect-ratio: 60.00 / 24.00", p)

    def test_missing_svg_has_no_size(self):
        p = self.ph("\\[\\tikzfig{a}\\]")
        self.assertNotIn("width=", p)

    def test_center(self):
        p = self.ph("\\begin{center}\\tikzfig{a}\\label{fig:x}\\end{center}")
        self.assertTrue(p.startswith("\\begin{center}\\TikzSvgHtml{block:fig-x}\\label{fig:x}\\end{center}\n<object"), p)

    def test_ctikzfig(self):
        p = self.ph("\\ctikzfig{a}")
        self.assertTrue(p.startswith("\\begin{center}\\TikzSvgHtml{block:a}\\end{center}\n<object"), p)

    def test_custom_templates(self):
        self.config.html_templates = {"inline": '<img class="mine" src="{src}">'}
        self.assertIn('<img class="mine" src="svgs/a.svg">', self.ph("$\\tikzfig{a}$"))

    def test_placeholders_only_contain_safe_characters(self):
        # A placeholder in a caption is also written to the .lof file, where escaped html characters (like %)
        # would break the run. So the placeholders only refer to the html by key.
        info = {"a": {"width": 30, "height": 12, "depth": 3}}
        for text in ("$\\tikzfig{a}$", "\\[\\tikzfig{a}\\]", "\\begin{equation}\\tikzfig{a}\\end{equation}",
                     "\\ctikzfig{a}"):
            p = self.ph(text, info).split("\n")[0]
            self.assertNotRegex(p, r'[%#&<>"_^~$]')

    def test_fragment_definitions_are_escaped(self):
        fragments = Fragments(self.config)
        fragments.add("x", '<span style="width: 100%">#</span>')
        defs = fragments.definitions()
        self.assertIn('\\TikzSvgDefine{x}{<span style="width: 100\\TikzSvgPercent ">\\#</span>}', defs)
        self.assertIn("\\TikzSvgDefine{number:before}{<span class=\"eq-no-item\">(}", defs)

    def test_replace_blocks(self):
        text = strip_comments("A $\\tikzfig{a}$ B \\begin{solution}\\tikzfig{s}\\end{solution} C \\[\\tikzfig{b}\\] D")
        self.config.skip_environments = ["solution"]
        blocks, skipped = blocks_of(text, self.config)
        out = replace_blocks(text, blocks, skipped, self.config, {}, Fragments(self.config))
        self.assertEqual(out, "A \\TikzSvgHtml{inline:a} B  C \\TikzSvgDisplay{display:b}{}{empty} D")

    def test_restrict_subfiles(self):
        text = "\\subfile{intro}\n\\subfile{zx}\n% \\subfile{old}\n\\include{phasefree}\n"
        out = restrict_subfiles(text, {"zx"}, ["main", "intro", "zx", "phasefree"])
        self.assertIn("% (skipped by tikz2html) \\subfile{intro}", out)
        self.assertIn("\n\\subfile{zx}\n", out)
        self.assertIn("% (skipped by tikz2html) \\include{phasefree}", out)


class TestTex4htConfig(unittest.TestCase):
    def test_injected_before_begin_document(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "my.cfg"), "w") as f:
                f.write("\\Preamble{xhtml}\n\\Configure{crosslinks}{a}{b}\n\\begin{document}\n\\EndPreamble\n")
            config = Config(main_name="main", root=d, make4ht_config="my.cfg", additional_css=["extra.css"],
                            extra_js=["js/menu.js"])
            config.normalize()
            cfg = tex4ht_config(config)
        self.assertLess(cfg.index("\\Configure{crosslinks}"), cfg.index("\\TikzSvgDisplay"))
        self.assertLess(cfg.index("\\TikzSvgDisplay"), cfg.index("\\begin{document}"))
        self.assertIn("\\Configure{AddCss}{extra.css}", cfg)
        self.assertIn('src="menu.js"', cfg)

    def test_default_config(self):
        config = make_config()
        cfg = tex4ht_config(config)
        self.assertTrue(cfg.startswith("\\Preamble{xhtml}"))
        self.assertIn("\\EndPreamble", cfg)

    def test_build_file(self):
        mk4 = make4ht_build_file(make_config(bibtex="bibtex", latex_passes=2))
        self.assertIn("Make:tikz2html_bibtex", mk4)
        self.assertEqual(mk4.count("Make:htlatex"), 4)  # 1 in draft mode, 3 otherwise
        self.assertNotIn("bibtex", make4ht_build_file(make_config(bibtex="")))


class TestConfig(unittest.TestCase):
    def test_legacy_formats(self):
        config = make_config(tikz_macros=["tikzfig", "\\Zscalar"],
                             also_process_with_svg=["begin{tabu}", "begin{tikzpicture}", "\\emptydiag"],
                             additional_css="a.css")
        self.assertEqual(config.tikz_macros, {"tikzfig": "m", "Zscalar": "m", "emptydiag": ""})
        self.assertIn("tabu", config.tikz_environments)
        self.assertEqual(config.additional_css, ["a.css"])
        self.assertEqual(config.make4ht_options, "mathml,mathjax,next,2")

    def test_math_environment_overrides(self):
        config = make_config(math_environments={"center": None, "dmath": ["display", "single"]})
        envs = config.scan_config.math_environments
        self.assertNotIn("center", envs)
        self.assertEqual(envs["dmath"], ("display", "single"))

    def test_example_configs_load(self):
        examples = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
        for name in os.listdir(examples):
            path = os.path.join(examples, name, "html_config.json")
            if os.path.exists(path):
                config = Config.from_json(path)
                self.assertEqual(config.root, os.path.dirname(path))
                self.assertEqual(config.warnings, [], path)
                self.assertIn("tikzfig", config.tikz_macros)


if __name__ == "__main__":
    unittest.main()
