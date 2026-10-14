"""Tests of --init and the discovery of the structure of a LaTeX project (discover.py)."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tikz2html.config import Config
from tikz2html.discover import analyse_project, find_tikz_definitions, macro_definitions
from tikz2html.errors import Tikz2HtmlError
from tikz2html.init import init_project
from tikz2html.pipeline import Pipeline

MAIN = r"""\documentclass[11pt]{book}
\usepackage{amsmath}
\usepackage{tikzit}
\usepackage{mystyle}
\input{styles.tikzstyles}
\newcommand{\spider}[2][Z]{\tikz{\node[style=#1 dot] {$#2$};}}
\newcommand\twospiders[1]{\spider{#1}\spider{#1}}
\def\arrowdiagram#1#2{\begin{tikzpicture}\draw (0,0) -- (1,0);\end{tikzpicture}}
\NewDocumentCommand{\boxed}{om}{\tikz \node[draw] {#2};}
\newcommand{\notikz}[1]{\textbf{#1}}
\newenvironment{diagram}{\begin{tikzpicture}}{\end{tikzpicture}}
\usepackage{comment}
\excludecomment{solution}
\bibliographystyle{mystyle}
\begin{document}
% \input{commented-out}
\include{chapters/one}
\input{chapters/two.tex}
\input{missing-file}
\includegraphics{logo}
\bibliography{refs}
\end{document}
"""


class TempProject(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        files = {
            "main.tex": MAIN,
            "chapters/one.tex": "\\chapter{One}\\[\\tikzfig{a}\\]\n\\subfile{three}\n",
            "chapters/three.tex": "\\section{Three} $\\spider{\\alpha}$\n\\subimport{../parts/}{four}\n",
            "chapters/two.tex": "\\chapter{Two} \\input styles2.tikzdefs\n",
            "parts/four.tex": "\\section{Four} \\ctikzfig{b}\n",
            "styles.tikzstyles": "", "styles2.tikzdefs": "", "mystyle.sty": "", "mystyle.bst": "",
            "refs.bib": "", "logo.png": "", "figures/a.tikz": "", "figures/b.tikz": "",
        }
        for name, text in files.items():
            path = os.path.join(self.dir, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        self.main = os.path.join(self.dir, "main.tex")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestDiscovery(TempProject):
    def test_included_files(self):
        p = analyse_project(self.main)
        self.assertEqual(p.main_name, "main")
        self.assertEqual(p.tex_files, ["chapters/one", "chapters/two", "chapters/three", "parts/four"])
        self.assertEqual(sorted(p.other_inputs), ["styles.tikzstyles", "styles2.tikzdefs"])
        self.assertEqual(p.missing, [("missing-file", "main.tex")])

    def test_other_files(self):
        p = analyse_project(self.main)
        self.assertEqual(p.document_class, "book")
        self.assertTrue(p.is_book)
        self.assertTrue(p.uses_tikzit)
        self.assertFalse(p.uses_biblatex)
        self.assertEqual(sorted(p.local_packages), ["mystyle.bst", "mystyle.sty"])
        self.assertEqual(p.bibliographies, ["refs.bib"])
        self.assertEqual(p.images, ["logo.png"])
        self.assertEqual(p.excluded_environments, ["solution"])

    def test_tikz_macros_and_their_arguments(self):
        p = analyse_project(self.main)
        self.assertEqual(p.tikz_macros, {"spider": "om", "arrowdiagram": "mm", "boxed": "om", "twospiders": "m"})
        self.assertEqual(p.tikz_environments, ["diagram"])

    def test_macro_definitions(self):
        defs = list(macro_definitions(r"\newcommand*{\a}[3][x]{A}\renewcommand\b{B}\newkeycommand\c[k=][2]{C}"
                                      r"\gdef\d#1{D}\newenvironment{e}[1]{E1}{E2}"))
        self.assertEqual(defs, [("macro", "a", "omm", "A"), ("macro", "b", "", "B"), ("macro", "c", "omm", "C"),
                                ("macro", "d", "m", "D"), ("environment", "e", "", "E1E2")])

    def test_indirect_tikz_macros(self):
        macros, _ = find_tikz_definitions(r"\newcommand\c{\b}\newcommand\b{\a}\newcommand\a{\tikzfig{x}}")
        self.assertEqual(set(macros), {"a", "b", "c"})

    def test_biblatex(self):
        with open(self.main, "a", encoding="utf-8") as f:
            pass
        text = MAIN.replace("\\usepackage{amsmath}", "\\usepackage{amsmath}\\usepackage{biblatex}"
                            "\\addbibresource{refs.bib}")
        with open(self.main, "w", encoding="utf-8") as f:
            f.write(text)
        p = analyse_project(self.main)
        self.assertTrue(p.uses_biblatex)
        self.assertEqual(p.bibliographies, ["refs.bib"])


class TestInit(TempProject):
    def test_writes_working_configuration(self):
        log = []
        path = init_project(self.main, log=log.append)
        self.assertEqual(path, os.path.join(self.dir, "html_config.json"))
        for name in ("html_config.json", "svgbase.tex", "tikz2html.cfg"):
            self.assertTrue(os.path.exists(os.path.join(self.dir, name)), name)
        config = Config.from_json(path)
        self.assertEqual(config.warnings, [])
        self.assertEqual(config.main_name, "main")
        self.assertEqual(config.other_tex_files, ["chapters/one", "chapters/two", "chapters/three", "parts/four"])
        self.assertEqual(config.tikz_macros["spider"], "om")
        self.assertEqual(config.tikz_macros["tikz"], "ot")
        self.assertIn("tikzfig", config.tikz_macros)
        self.assertIn("diagram", config.tikz_environments)
        self.assertIn("solution", config.skip_environments)
        self.assertEqual(config.make4ht_options, "mathml,mathjax,next,2")
        self.assertEqual(config.bibtex, "bibtex")
        self.assertIn("refs.bib", config.files_to_copy)
        self.assertTrue(any("missing-file" in line for line in log))

    def test_template_contains_the_preamble(self):
        init_project(self.main, log=lambda *a: None)
        with open(os.path.join(self.dir, "svgbase.tex"), encoding="utf-8") as f:
            template = f.read()
        self.assertTrue(template.split("\n")[6].startswith("\\documentclass[11pt]{book}") or
                        "\\documentclass[11pt]{book}" in template)
        self.assertIn("\\newcommand{\\spider}[2][Z]", template)
        self.assertIn("\\externaldocument{MAIN_FILE}", template)
        self.assertEqual(template.count("CONTENT_HERE"), 1)
        self.assertLess(template.index("\\usepackage{xr}"), template.index("\\usepackage{tikzit}"))
        self.assertLess(template.rindex("begindocument/end"), template.rindex("\\begin{document}"))

    def test_the_project_can_be_scanned(self):
        config = Config.from_json(init_project(self.main, log=lambda *a: None))
        pipeline = Pipeline(config, log=lambda *a: None)
        pipeline.run(skip_svgs=True, skip_html=True)
        self.assertEqual(pipeline.report, [])

    def test_article_is_one_page(self):
        with open(self.main, "w", encoding="utf-8") as f:
            f.write(MAIN.replace("{book}", "{article}"))
        config = Config.from_json(init_project(self.main, log=lambda *a: None))
        self.assertEqual(config.make4ht_options, "mathml,mathjax")

    def test_does_not_overwrite(self):
        init_project(self.main, log=lambda *a: None)
        with self.assertRaisesRegex(Tikz2HtmlError, "exist already.*--overwrite"):
            init_project(self.main, log=lambda *a: None)
        init_project(self.main, overwrite=True, log=lambda *a: None)

    def test_missing_main_file(self):
        with self.assertRaisesRegex(Tikz2HtmlError, "does not exist"):
            init_project(os.path.join(self.dir, "nope.tex"), log=lambda *a: None)

    def test_not_a_main_file(self):
        with self.assertRaisesRegex(Tikz2HtmlError, "no \\\\documentclass"):
            init_project(os.path.join(self.dir, "chapters", "one.tex"), log=lambda *a: None)

    def test_warning_for_unlisted_included_file(self):
        config = Config.from_json(init_project(self.main, log=lambda *a: None))
        config.other_tex_files = [f for f in config.other_tex_files if f != "parts/four"]
        pipeline = Pipeline(config, log=lambda *a: None)
        pipeline.run(skip_svgs=True, skip_html=True)
        self.assertEqual(len(pipeline.report), 1)
        self.assertIn("parts/four.tex is included in chapters/three.tex and contains 1 TikZ blocks", pipeline.report[0])


if __name__ == "__main__":
    unittest.main()
