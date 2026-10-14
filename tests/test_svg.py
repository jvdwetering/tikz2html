"""Tests of the svg generation (template, cache, metrics) and of the links in the svgs."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tikz2html.config import Config
from tikz2html.svg_build import SvgBuilder, SvgJob, is_empty_svg, svg_metrics, replace_outside_comments
from tikz2html.svg_links import parse_aux, link_svg, label_targets, anchor_files

def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


TEMPLATE = r"""% Template. MAIN_FILE and CONTENT_HERE in a comment are not replaced
\documentclass{article}
\usepackage{xr}
\externaldocument{MAIN_FILE}
\usepackage{tikz}
\usepackage[active,tightpage]{preview}
\PreviewEnvironment{PREVIEW_ENVIRONMENT}
\begin{document}
CONTENT_HERE
\end{document}
"""


class TempProject(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "figures"))
        with open(os.path.join(self.dir, "svgbase.tex"), "w") as f:
            f.write(TEMPLATE)
        with open(os.path.join(self.dir, "figures", "a.tikz"), "w") as f:
            f.write("\\begin{tikzpicture}\\draw (0,0) -- (1,1);\\end{tikzpicture}\n")
        self.config = Config(main_name="main", root=self.dir)
        self.config.normalize()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestTemplate(TempProject):
    def test_render(self):
        builder = SvgBuilder(self.config, {}, log=lambda *a: None)
        tex = builder.render_tex(SvgJob("x", "\\[\\tikzfig{a}\\]", ["a"]))
        self.assertIn("\\externaldocument{html/main}", tex)
        self.assertIn("\\begin{preview}\n\\[\\tikzfig{a}\\]\n\\end{preview}", tex)
        self.assertIn("MAIN_FILE and CONTENT_HERE in a comment", tex)
        self.assertNotIn("PREVIEW_ENVIRONMENT", tex)
        # Compatibility definitions for reading the tex4ht aux file come before \begin{document}
        self.assertLess(tex.index("\\rEfLiNK"), tex.index("\\begin{document}"))

    def test_preamble_extra(self):
        self.config.svg_preamble_extra = ["\\newcommand{\\foo}{bar}"]
        tex = SvgBuilder(self.config, {}, log=lambda *a: None).render_tex(SvgJob("x", "$\\foo$", []))
        self.assertLess(tex.index("\\newcommand{\\foo}{bar}"), tex.index("\\begin{document}"))

    def test_replace_outside_comments(self):
        self.assertEqual(replace_outside_comments("% X\nX", "X", "Y"), "% X\nY")


class TestCache(TempProject):
    def builder(self, labels=None):
        return SvgBuilder(self.config, labels or {}, log=lambda *a: None)

    def key(self, builder, job):
        return builder.key(job, builder.render_tex(job))

    def test_key_depends_on_figure_content(self):
        job = SvgJob("x", "\\[\\tikzfig{a}\\]", ["a"])
        k1 = self.key(self.builder(), job)
        with open(os.path.join(self.dir, "figures", "a.tikz"), "a") as f:
            f.write("% changed\n")
        self.assertNotEqual(k1, self.key(self.builder(), job))

    def test_key_depends_on_source_and_dependencies(self):
        b = self.builder()
        self.assertNotEqual(self.key(b, SvgJob("x", "$a$", [])), self.key(b, SvgJob("x", "$b$", [])))
        self.assertEqual(self.key(b, SvgJob("x", "$a$", [])), self.key(b, SvgJob("y", "$a$", [])))
        with open(os.path.join(self.dir, "styles.tikzstyles"), "w") as f:
            f.write("x")
        self.config.svg_dependencies = ["styles.tikzstyles"]
        self.assertNotEqual(self.key(b, SvgJob("x", "$a$", [])), self.key(self.builder(), SvgJob("x", "$a$", [])))

    def test_cache_invalid_when_referenced_number_changes(self):
        b = self.builder({"eq:a": "1.1"})
        os.makedirs(b.cache_dir)
        svg, meta = b.cache_paths("k")
        write(svg, "<svg/>")
        write(meta, json.dumps({"refs": {"eq:a": "1.1"}}))
        self.assertTrue(b.cache_valid("k"))
        self.assertFalse(self.builder({"eq:a": "1.2"}).cache_valid("k"))


class TestSvgFiles(unittest.TestCase):
    def test_empty(self):
        self.assertTrue(is_empty_svg("<svg width='0pt' height='0pt' viewBox='0 0 0 0'></svg>"))
        self.assertFalse(is_empty_svg("<svg width='10pt' height='5pt' viewBox='0 -4 10 5'></svg>"))
        self.assertTrue(is_empty_svg(""))

    def test_metrics(self):
        w, h, depth = svg_metrics("<svg width='23pt' height='11.7pt' viewBox='1.66 -8.36 23 11.7'>")
        self.assertAlmostEqual(depth, 3.34)


class TestLinks(unittest.TestCase):
    def test_parse_tex4ht_aux(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "main.aux"), "w") as f:
                f.write("\\newlabel{eq:a}{{\\rEfLiNK{x4-3001r1}{\\csname :autoref\\endcsname{equation}1.1}}"
                        "{\\rEfLiNK{x4-3001r1}{\\csname :autoref\\endcsname{equation}7}}{}{equation.1}{}}\n"
                        "\\@input{ch.aux}\n")
            with open(os.path.join(d, "ch.aux"), "w") as f:
                f.write("\\newlabel{sec:b}{{2.3}{12}{Title}{section.2.3}{}}\n")
            labels = parse_aux(os.path.join(d, "main.aux"))
        self.assertEqual(labels["eq:a"], ("1.1", "x4-3001r1"))
        self.assertEqual(labels["sec:b"], ("2.3", None))

    def test_anchor_files_and_targets(self):
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "ch1.html"), "<a id='x4-3001r1'></a><div id=\"other\">")
            anchors = anchor_files(d, ["ch1.html"])
        self.assertEqual(anchors, {"x4-3001r1": "ch1.html", "other": "ch1.html"})
        self.assertEqual(label_targets({"eq:a": ("1.1", "x4-3001r1"), "eq:b": ("2", None)}, anchors),
                         {"eq:a": "ch1.html#x4-3001r1"})

    def test_link_svg(self):
        svg = "<g><eqref>eq:a<text>(1.1)</text>\n</eqref><hyperref>fig:missing<text>r</text></hyperref></g>"
        out, missing = link_svg(svg, {"eq:a": "ch1.html#x1"})
        self.assertEqual(out, '<g><a target="_parent" href="../ch1.html#x1" data-info="eq:a"><text>(1.1)</text>\n</a>'
                              '<a target="_parent" data-info="fig:missing"><text>r</text></a></g>')
        self.assertEqual(missing, ["fig:missing"])

    def test_nested_markers_give_one_link(self):
        # \eqref uses \ref, so its marker contains a \ref marker. Browsers don't draw a link inside a link.
        svg = "<eqref>eq:a<text>(</text><ref>eq:a<text>3</text></ref><text>)</text></eqref> <ref>b<text>1</text></ref>"
        out, missing = link_svg(svg, {"eq:a": "p.html#1", "b": "p.html#2"})
        self.assertEqual(out, '<a target="_parent" href="../p.html#1" data-info="eq:a"><text>(</text><text>3</text>'
                              '<text>)</text></a> <a target="_parent" href="../p.html#2" data-info="b"><text>1</text></a>')

    def test_link_svg_is_idempotent(self):
        svg = "<eqref>eq:a<text>x</text></eqref>"
        once, _ = link_svg(svg, {"eq:a": "a.html#1"})
        twice, _ = link_svg(once, {"eq:a": "b.html#2"})
        self.assertEqual(twice, once.replace("a.html#1", "b.html#2"))


if __name__ == "__main__":
    unittest.main()
