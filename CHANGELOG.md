# Changelog

## 0.1.0 (October 2026)

First public version. tikz2html grew out of the scripts used to make the html version of the book
*Picturing Quantum Software* (https://zxcalc.github.io/book/html/main_html.html).

* Converting a LaTeX document with TikZ(iT) figures to html: the figures are compiled to svgs (in parallel, with a
  cache), the text is converted with make4ht, and references inside the svgs become links.
* Equation numbers, `\tag`s and `\label`s of equations that become svgs work in the html.
* `--init` sets up a document: it finds the included files, the macros that draw TikZ, the bibliography, etc.
* `--list`, `--only`, `--files` and `--draft` for working on a part of a document; `--clean` to remove all work files.
* Clear error messages, and a report of the problems of a conversion.
