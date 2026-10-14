r"""End-to-end test: converts a tiny document with TikZiT figures, running latex, dvisvgm and make4ht.

Skipped when these programs are not installed, or when the environment variable TIKZ2HTML_SKIP_SLOW is set.
Takes about half a minute.
"""

import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tikz2html.config import Config
from tikz2html.pipeline import Pipeline

MAIN = r"""\documentclass{book}
\usepackage{amsmath,amsthm}
\usepackage{tikzit}
\usepackage{hyperref}
\newtheorem{theorem}{Theorem}
\begin{document}
\chapter{One}
A numbered equation:
\begin{equation}\label{eq:a}
  \tikzfig{dot} = \tikzfig{dot}
\end{equation}
A tagged equation:
\begin{equation}\label{eq:t}
  \tikzfig{dot}\tag{T}
\end{equation}
An align with two numbers:
\begin{align}
\label{eq:b}
\tikzfig{dot} &= x \\[2mm]
\label{eq:c}
&= \tikzfig{dot}
\end{align}
Inline: $\tikzfig{dot}$, a centered one:
\ctikzfig{dot}
and one referring to another chapter:
\[ \tikzfig{dot} \overset{\eqref{eq:d}}{=} \tikzfig{dot} \]
In a table: \begin{tabular}{cc} a & \tikzfig{dot} \\[0cm] b & c \end{tabular}
\begin{theorem}
  \[ x = \tikzfig{dot} \qedhere \]
\end{theorem}
\chapter{Two}
\begin{equation}\label{eq:d}
  y = \tikzfig{dot} = z
\end{equation}
See \eqref{eq:a}, \eqref{eq:t}, \eqref{eq:b}, \eqref{eq:c}, \eqref{eq:d}.
\end{document}
"""

TEMPLATE = r"""\documentclass{article}
\usepackage{xr}
\externaldocument{MAIN_FILE}
\usepackage{amsmath}
\usepackage{hyperref}
\let\originaleqref\eqref
\renewcommand{\eqref}[1]{\special{dvisvgm:raw <eqref>#1}\originaleqref{#1}\special{dvisvgm:raw </eqref>}}
\usepackage{tikzit}
\usepackage[active,tightpage]{preview}
\begin{document}
CONTENT_HERE
\end{document}
"""

FIGURE = r"""\begin{tikzpicture}
	\begin{pgfonlayer}{nodelayer}
		\node [circle, draw, fill=green] (0) at (0, 0) {};
	\end{pgfonlayer}
\end{tikzpicture}
"""


def have_tools():
    return all(shutil.which(t) for t in ("latex", "dvisvgm", "make4ht"))


@unittest.skipIf(os.environ.get("TIKZ2HTML_SKIP_SLOW"), "slow tests disabled")
@unittest.skipUnless(have_tools(), "latex, dvisvgm or make4ht not installed")
class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        d = cls.dir
        os.makedirs(os.path.join(d, "figures"))
        shutil.copy(os.path.join(ROOT, "examples", "book", "tikzit.sty"), d)
        for name, text in [("main.tex", MAIN), ("svgbase.tex", TEMPLATE), ("figures/dot.tikz", FIGURE)]:
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(text)
        cls.config = Config(main_name="main", root=d, bibtex="", jobs=4, svg_dependencies=["tikzit.sty"])
        cls.config.normalize()
        cls.logs = []
        cls.results = Pipeline(cls.config, log=cls.logs.append).run()
        with open(os.path.join(d, "html", "mainch1.html"), encoding="utf-8") as f:
            cls.ch1 = f.read()
        with open(os.path.join(d, "html", "mainch2.html"), encoding="utf-8") as f:
            cls.ch2 = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_all_svgs_built(self):
        self.assertTrue(self.results)
        self.assertEqual([r for r in self.results if r.status == "failed"], [], "\n".join(self.logs))
        for r in self.results:
            self.assertTrue(os.path.exists(os.path.join(self.config.svg_dir, r.job.id + ".svg")))

    def test_no_tex_errors(self):
        self.assertTrue([line for line in self.logs if line.endswith("exit code 0") or "exit code 0 in" in line
                         and line.endswith(", 0 TeX errors")], self.logs)
        self.assertIn("Theorem", self.ch1)

    def test_shared_svgs(self):
        # \tikzfig{dot} in the tagged equation, inline, \ctikzfig and in the table all show the same picture,
        # which is named after its first occurrence (with label eq:t)
        used = re.findall(r"svgs/([\w.-]+)\.svg", self.ch1)
        self.assertEqual(used.count("eq-t"), 4)
        self.assertEqual(len({r.job.id for r in self.results}), len(self.results))

    def test_no_tikz_left_in_html(self):
        self.assertNotIn("tikzfig", self.ch1)
        self.assertNotIn("TikzSvg", self.ch1)

    def test_equation_numbers_and_tags(self):
        nums = re.findall(r"<span class='eq-no-item'>(.*?)</span>", self.ch1)
        self.assertEqual(nums, ["(1.1)", "(T)", "(1.2)", "(1.3)"])

    def test_references_in_html(self):
        refs = re.findall(r"<a href='([^']*)'>([^<]*)<!-- tex4ht:ref: (\S+)", self.ch2)
        values = {label: text for _, text, label in refs}
        self.assertEqual(values, {"eq:a": "1.1", "eq:t": "T", "eq:b": "1.2", "eq:c": "1.3", "eq:d": "2.1"})
        for href, _, label in refs:
            if label != "eq:d":
                anchor = href.split("#")[1]
                self.assertIn(f"id='{anchor}'", self.ch1)

    def test_inline_image_is_aligned(self):
        # The shared svg is compiled inline, so it has a non-zero depth below the baseline
        self.assertRegex(self.ch1, r"<img alt='diagram eq-t' class='inline-diagram' height='[\d.]+' src='svgs/eq-t.svg' "
                                   r"style='vertical-align: -[\d.]*[1-9][\d.]*px; max-width: 100%; height: auto' "
                                   r"width='[\d.]+' />")

    def test_display_svg_has_size(self):
        self.assertRegex(self.ch1, r"<object aria-label='diagram eq-a' class='svg-diagram' data='svgs/eq-a.svg' "
                                   r"height='[\d.]+' style='max-width: 100%; height: auto; aspect-ratio: [\d.]+ / [\d.]+' "
                                   r"type='image/svg\+xml' width='[\d.]+'></object>")

    def test_link_in_svg(self):
        linked = [r.job.id for r in self.results if "eqref" in r.job.source]
        self.assertEqual(len(linked), 1)
        with open(os.path.join(self.config.svg_dir, linked[0] + ".svg"), encoding="utf-8") as f:
            svg = f.read()
        m = re.search(r'<a target="_parent" href="\.\./mainch2\.html#([^"]+)" data-info="eq:d">', svg)
        self.assertTrue(m, svg[:3000])
        self.assertIn(f"id='{m.group(1)}'", self.ch2)
        self.assertIn("2.1", svg)  # The number from the html run

    def test_rerun_uses_cache(self):
        logs = []
        results = Pipeline(self.config, log=logs.append).run(skip_html=True)
        self.assertTrue(all(r.status == "cached" for r in results), logs)


@unittest.skipIf(os.environ.get("TIKZ2HTML_SKIP_SLOW"), "slow tests disabled")
@unittest.skipUnless(have_tools() and shutil.which("bibtex"), "latex, dvisvgm, make4ht or bibtex not installed")
class TestExample(unittest.TestCase):
    """Converts the example project in examples/book (in a copy, so the example folder stays clean)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        src = os.path.join(ROOT, "examples", "book")
        shutil.copytree(src, cls.dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns("html"))
        cls.config = Config.from_json(os.path.join(cls.dir, "html_config.json"))
        cls.config.jobs = 4
        cls.logs = []
        cls.pipeline = Pipeline(cls.config, log=cls.logs.append)
        cls.results = cls.pipeline.run()
        cls.pages = {}
        for name in os.listdir(cls.config.html_dir):
            if name.endswith(".html"):
                with open(os.path.join(cls.config.html_dir, name), encoding="utf-8") as f:
                    cls.pages[name] = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_no_problems(self):
        self.assertEqual(self.pipeline.report, [], "\n".join(self.logs))

    def test_pages(self):
        self.assertTrue({"main.html", "mainch1.html", "mainch2.html"} <= set(self.pages))

    def test_numbers(self):
        nums = re.findall(r"<span class='eq-no-item'>(.*?)</span>", self.pages["mainch2.html"])
        self.assertEqual(nums, ["(2.1)", "(2.2)", "(2.3)", "(gf)"])

    def test_inline_figure_in_caption(self):
        caption = re.search(r"<figcaption.*?</figcaption>", self.pages["mainch1.html"], re.S).group(0)
        self.assertIn("class='inline-diagram'", caption)

    def test_solution_is_left_out(self):
        self.assertNotIn("does-not-exist", "".join(self.pages.values()))

    def test_bibliography(self):
        self.assertRegex("".join(self.pages.values()), r"Interacting\s+quantum\s+observables")

    def test_all_links_in_svgs_resolved(self):
        for r in self.results:
            with open(os.path.join(self.config.svg_dir, r.job.id + ".svg"), encoding="utf-8") as f:
                for tag in re.findall(r"<a [^>]*>", f.read()):
                    self.assertIn("href=", tag, r.job.id)


@unittest.skipIf(os.environ.get("TIKZ2HTML_SKIP_SLOW"), "slow tests disabled")
@unittest.skipUnless(have_tools() and shutil.which("biber"), "latex, dvisvgm, make4ht or biber not installed")
class TestArticleExample(unittest.TestCase):
    """Sets up the example paper in examples/article with --init (in a copy), and converts it."""

    @classmethod
    def setUpClass(cls):
        from tikz2html.init import init_project
        cls.dir = tempfile.mkdtemp()
        src = os.path.join(ROOT, "examples", "article")
        shutil.copytree(src, cls.dir, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("html", "html_config.json", "svgbase.tex", "tikz2html.cfg"))
        cls.config = Config.from_json(init_project(os.path.join(cls.dir, "paper.tex"), log=lambda *a: None))
        cls.config.jobs = 4
        cls.logs = []
        cls.pipeline = Pipeline(cls.config, log=cls.logs.append)
        cls.results = cls.pipeline.run()
        with open(os.path.join(cls.config.html_dir, "paper.html"), encoding="utf-8") as f:
            cls.page = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_no_problems(self):
        self.assertEqual(self.pipeline.report, [], "\n".join(self.logs))
        self.assertFalse(self.pipeline.failed)

    def test_one_page_with_all_diagrams(self):
        html_pages = [f for f in os.listdir(self.config.html_dir) if f.endswith(".html")]
        self.assertEqual(html_pages, ["paper.html"])
        self.assertEqual(len(set(re.findall(r"svgs/([\w.-]+)\.svg", self.page))), len(self.results))

    def test_references_in_svgs(self):
        svg = os.path.join(self.config.svg_dir, "phase-gadget-reduced.svg")
        with open(svg, encoding="utf-8") as f:
            links = re.findall(r'<a [^>]*data-info="([^"]*)"', f.read())
        self.assertEqual(links, ["eq:gadget-fusion", "prop:gadgets"])  # \eqref and \ref, not nested


if __name__ == "__main__":
    unittest.main()
