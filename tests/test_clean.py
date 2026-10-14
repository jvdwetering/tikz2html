"""Tests of --clean: removing everything from the html folder that is not needed to view the html."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tikz2html.clean import clean, needed_files, local_target
from tikz2html.config import Config
from tikz2html.errors import Tikz2HtmlError

MAIN = """<html><head><link href='main.css' rel='stylesheet' /><link href="extra.css" rel="stylesheet" />
<script src='menu.js' defer='defer'></script>
<script src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/mml-chtml.js'></script></head>
<body><a href='mainch1.html#x1-2'>Chapter 1</a> <a href='#top'>top</a> <a href='mailto:a@b.c'>mail</a>
<img src='logo%20small.png' /></body></html>"""
CH1 = """<html><body><object data='svgs/a.svg' type='image/svg+xml'></object>
<img src="svgs/b.svg" style="background: url('bg.png')" /><a href='main.html'>up</a></body></html>"""
SVG_A = """<svg><a target="_parent" href="../mainch2.html#x2-1" data-info="eq:x"><text>(2.1)</text></a></svg>"""
CSS = "@import 'fonts.css'; body { background: url(paper.jpg); }"


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestClean(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.html = os.path.join(self.root, "html")
        files = {
            "main.html": MAIN, "mainch1.html": CH1, "mainch2.html": "<html></html>", "main.css": "",
            "extra.css": CSS, "fonts.css": "", "paper.jpg": "", "menu.js": "", "logo small.png": "", "bg.png": "",
            "svgs/a.svg": SVG_A, "svgs/b.svg": "<svg/>",
            # Not needed:
            "mainch3.html": "<html>an old page that is no longer linked</html>", "main.tex": "", "main.aux": "",
            "main.log": "", "main-tikz2html.cfg": "", "svgs/old.svg": "<svg/>", "svgs/.cache/123.svg": "<svg/>",
            "svgs/.cache/123.json": "{}", "svgs/.build/x.tex": "", "svgs/_failed/y.log": "",
            # Not made by tikz2html, so left alone:
            "backup/a.svg": "<svg/>",
        }
        for name, text in files.items():
            write(os.path.join(self.html, name), text)
        self.config = Config(main_name="main", root=self.root)
        self.config.normalize()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def remaining(self):
        out = set()
        for folder, _, files in os.walk(self.html):
            for f in files:
                out.add(os.path.relpath(os.path.join(folder, f), self.html).replace(os.sep, "/"))
        return out

    def test_needed_files(self):
        needed = {os.path.relpath(p, self.html).replace(os.sep, "/") for p in needed_files(self.html, ["main.html"])}
        self.assertEqual(needed, {"main.html", "mainch1.html", "mainch2.html", "main.css", "extra.css", "fonts.css",
                                  "paper.jpg", "menu.js", "logo small.png", "bg.png", "svgs/a.svg", "svgs/b.svg"})

    def test_clean(self):
        log = []
        clean(self.config, log=log.append)
        self.assertEqual(self.remaining(), {
            "main.html", "mainch1.html", "mainch2.html", "main.css", "extra.css", "fonts.css", "paper.jpg",
            "menu.js", "logo small.png", "bg.png", "svgs/a.svg", "svgs/b.svg", "backup/a.svg"})
        self.assertFalse(os.path.exists(os.path.join(self.html, "svgs", ".cache")))
        self.assertIn("backup", log[-1])

    def test_dry_run(self):
        before = self.remaining()
        removed = clean(self.config, dry_run=True, log=lambda *a: None)
        self.assertEqual(self.remaining(), before)
        self.assertEqual(len(removed), 10)

    def test_keep_cache(self):
        clean(self.config, keep_cache=True, log=lambda *a: None)
        self.assertIn("svgs/.cache/123.svg", self.remaining())
        self.assertNotIn("svgs/.build/x.tex", self.remaining())

    def test_keep_patterns(self):
        self.config.clean_keep = ["*.log", "svgs/old.svg"]
        clean(self.config, log=lambda *a: None)
        self.assertTrue({"main.log", "svgs/old.svg"} <= self.remaining())

    def test_refuses_without_main_page(self):
        os.remove(os.path.join(self.html, "main.html"))
        with self.assertRaises(Tikz2HtmlError):
            clean(self.config, log=lambda *a: None)
        self.assertIn("main.tex", self.remaining())

    def test_refuses_to_clean_the_project_folder(self):
        self.config.html_folder = "."
        with self.assertRaises(Tikz2HtmlError):
            clean(self.config, log=lambda *a: None)

    def test_local_target(self):
        self.assertIsNone(local_target("https://example.com/x.js", self.html, self.html))
        self.assertIsNone(local_target("#anchor", self.html, self.html))
        self.assertIsNone(local_target("data:image/png;base64,xx", self.html, self.html))
        self.assertIsNone(local_target("../../outside.html", self.html, self.html))
        self.assertEqual(local_target("a%20b.html?x=1#y", self.html, self.html), os.path.join(self.html, "a b.html"))


if __name__ == "__main__":
    unittest.main()
