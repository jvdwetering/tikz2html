"""Tests of the error handling: problems with the configuration, the sources, the figures and the programs should
give a clear message (a Tikz2HtmlError, printed by the command line without a traceback)."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tikz2html.cli import main
from tikz2html.config import Config
from tikz2html.errors import Tikz2HtmlError, require_program
from tikz2html.pipeline import Pipeline, load_sources, read_text

MAIN = "\\documentclass{article}\n\\begin{document}\n" + "".join(
    f"\\[ \\tikzfig{{fig{i}}} \\]\n" for i in range(12)) + "\\end{document}\n"


class Project(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "figures"))
        for i in range(12):
            self.write(f"figures/fig{i}.tikz", "\\begin{tikzpicture}\\end{tikzpicture}")
        self.write("main.tex", MAIN)
        self.write("svgbase.tex", "\\documentclass{article}\n\\begin{document}\nCONTENT_HERE\n\\end{document}\n")
        self.write_config({"main_name": "main"})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def write_config(self, data):
        self.write("html_config.json", json.dumps(data) if isinstance(data, dict) else data)

    def load(self):
        return Config.from_json(os.path.join(self.dir, "html_config.json"))

    def assertError(self, pattern, func, *args, **kwargs):
        with self.assertRaisesRegex(Tikz2HtmlError, pattern):
            func(*args, **kwargs)


class TestConfigErrors(Project):
    def test_missing_file(self):
        self.assertError("does not exist", Config.from_json, os.path.join(self.dir, "nope.json"))

    def test_invalid_json(self):
        self.write_config('{"main_name": "main",}')
        self.assertError("not valid JSON.*line 1", self.load)

    def test_not_an_object(self):
        self.write_config('["main"]')
        self.assertError("JSON object", self.load)

    def test_missing_main_name(self):
        self.write_config({"other_tex_files": []})
        self.assertError("main_name", self.load)

    def test_wrong_type(self):
        self.write_config({"main_name": "main", "other_tex_files": "intro"})
        self.assertError("'other_tex_files'.*must be a list", self.load)
        self.write_config({"main_name": "main", "jobs": "4"})
        self.assertError("'jobs'.*must be a number", self.load)

    def test_alternative_types_are_accepted(self):
        self.write_config({"main_name": "main", "tikz_macros": ["tikzfig"], "latex_cmd": "latex -x",
                           "svg_scale": 2})
        config = self.load()
        self.assertEqual(config.tikz_macros, {"tikzfig": "m"})
        self.assertEqual(config.latex_cmd, ["latex", "-x"])

    def test_invalid_macro_spec(self):
        self.write_config({"main_name": "main", "tikz_macros": {"tikzfig": "x"}})
        self.assertError("argument specification 'x'", self.load)

    def test_unknown_key_suggests_the_right_one(self):
        self.write_config({"main_name": "main", "tikz_macro": {}, "_comment": "ignored"})
        config = self.load()
        self.assertEqual(len(config.warnings), 1)
        self.assertIn("did you mean 'tikz_macros'", config.warnings[0])

    def test_internal_fields_are_not_keys(self):
        self.write_config({"main_name": "main", "root": "/", "warnings": []})
        config = self.load()
        self.assertEqual(config.root, self.dir)
        self.assertEqual(len(config.warnings), 2)


class TestSourceErrors(Project):
    def test_missing_source_file(self):
        self.write_config({"main_name": "main", "other_tex_files": ["chapter1"]})
        self.assertError("chapter1.tex does not exist.*other_tex_files", load_sources, self.load())

    def test_scan_error_names_the_file(self):
        self.write("main.tex", "a\n\\begin{equation}\\tikzfig{a}\n")
        self.assertError(r"main\.tex:2: \\begin\{equation\} is never closed", load_sources, self.load())

    def test_invalid_replacement_regex(self):
        self.write_config({"main_name": "main", "preprocess_replacements": [["(unclosed", ""]]})
        self.assertError("regular expression", load_sources, self.load())

    def test_latin1_source(self):
        with open(os.path.join(self.dir, "main.tex"), "wb") as f:
            f.write(b"caf\xe9 \\tikzfig{fig0}\n")
        self.assertEqual(read_text(os.path.join(self.dir, "main.tex")), ("caf\u00e9 \\tikzfig{fig0}\n", "latin-1"))
        self.assertEqual(len(load_sources(self.load())[0].blocks), 1)

    def test_unknown_files_option(self):
        self.assertError("Unknown files nope", Pipeline(self.load(), log=lambda *a: None).run,
                         files=["nope"], skip_svgs=True, skip_html=True)


class TestFigureChecks(Project):
    def run_checks(self):
        pipeline = Pipeline(self.load(), log=lambda *a: None)
        pipeline.run(skip_svgs=True, skip_html=True)
        return pipeline

    def test_missing_figure(self):
        os.remove(os.path.join(self.dir, "figures", "fig3.tikz"))
        pipeline = self.run_checks()
        self.assertTrue(pipeline.failed)
        self.assertEqual(len(pipeline.report), 1)
        self.assertRegex(pipeline.report[0], r"Figure 'fig3' \(used in main\.tex:6\) not found")

    def test_figure_name_differs_in_case(self):
        os.rename(os.path.join(self.dir, "figures", "fig3.tikz"), os.path.join(self.dir, "figures", "Fig3.tikz"))
        pipeline = self.run_checks()
        self.assertFalse(pipeline.failed)
        self.assertIn("is called 'Fig3.tikz'", pipeline.report[0])

    def test_all_figures_present(self):
        self.assertEqual(self.run_checks().report, [])


class TestProgramErrors(Project):
    def test_require_program(self):
        self.assertError("'no-such-program-xyz' was not found.*latex_cmd", require_program,
                         ["no-such-program-xyz", "-x"], "latex_cmd")
        require_program([sys.executable], "latex_cmd")  # exists: no error

    def test_missing_latex(self):
        self.write_config({"main_name": "main", "latex_cmd": ["no-such-latex"]})
        self.assertError("'no-such-latex' was not found", Pipeline(self.load(), log=lambda *a: None).run,
                         skip_html=True)

    def test_missing_make4ht(self):
        self.write_config({"main_name": "main", "make4ht_cmd": "no-such-make4ht"})
        self.assertError("'no-such-make4ht' was not found", Pipeline(self.load(), log=lambda *a: None).run,
                         skip_svgs=True)

    def test_missing_bibtex_only_matters_when_not_in_draft_mode(self):
        self.write_config({"main_name": "main", "bibtex": "no-such-bibtex", "make4ht_cmd": "no-such-make4ht"})
        # In draft mode bibtex isn't run, so the first missing program is make4ht
        self.assertError("no-such-make4ht", Pipeline(self.load(), log=lambda *a: None).run,
                         skip_svgs=True, draft=True)

    def test_stops_when_all_svgs_fail(self):
        # A "latex" that exists but produces nothing: every svg fails, which means something is wrong in general
        self.write_config({"main_name": "main", "latex_cmd": [sys.executable, "-c", "pass"],
                           "dvisvgm_cmd": [sys.executable, "-c", "pass"], "jobs": 2})
        logs = []
        self.assertError("first 8 svgs all failed", Pipeline(self.load(), log=logs.append).run, skip_html=True)
        self.assertLess(len([line for line in logs if "FAILED" in line]), 12)

    def test_missing_template(self):
        self.write_config({"main_name": "main", "svg_basefile": "nope.tex",
                           "latex_cmd": [sys.executable], "dvisvgm_cmd": [sys.executable]})
        self.assertError("svg template .*nope.tex does not exist", Pipeline(self.load(), log=lambda *a: None).run,
                         skip_html=True)

    def test_template_without_content_placeholder(self):
        self.write("svgbase.tex", "\\documentclass{article}\\begin{document}\\end{document}")
        self.write_config({"main_name": "main", "latex_cmd": [sys.executable], "dvisvgm_cmd": [sys.executable]})
        self.assertError("must contain CONTENT_HERE", Pipeline(self.load(), log=lambda *a: None).run, skip_html=True)


class TestCommandLine(Project):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", os.path.join(self.dir, "html_config.json")] + list(args))
        return code, out.getvalue(), err.getvalue()

    def test_error_is_one_line_without_traceback(self):
        self.write_config({"main_name": "main", "latex_cmd": ["no-such-latex"]})
        code, out, err = self.run_cli("--skip-html")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("tikz2html: error: The program 'no-such-latex' was not found"), err)
        self.assertNotIn("Traceback", err)

    def test_warnings_are_printed(self):
        self.write_config({"main_name": "main", "tikz_macro": {}})
        code, out, err = self.run_cli("--list")
        self.assertEqual(code, 0)
        self.assertIn("tikz2html: warning: Unknown configuration key 'tikz_macro'", err)

    def test_missing_figure_gives_exit_code_1(self):
        os.remove(os.path.join(self.dir, "figures", "fig0.tikz"))
        code, out, err = self.run_cli("--skip-svgs", "--skip-html")
        self.assertEqual(code, 1)
        self.assertIn("Figure 'fig0'", out)

    def test_clean_before_conversion(self):
        code, out, err = self.run_cli("--clean")
        self.assertEqual(code, 2)
        self.assertIn("convert the document before cleaning", err)


if __name__ == "__main__":
    unittest.main()
