# Example: a paper

A short paper in the `article` class, set up for tikz2html with `--init` alone: the three configuration files
in this folder (`html_config.json`, `svgbase.tex` and `tikz2html.cfg`) were generated with

```
tikz2html --init paper.tex
```

and not changed afterwards. To convert the paper, run this in this folder:

```
tikz2html
```

(or `python -m tikz2html --config examples/article/html_config.json` from the root of the repository). The result is
`html/paper.html`, a single page. The conversion takes about 20 seconds. The first run of biber can take a few
minutes longer, because biber unpacks itself on its first use.

## What it shows

* Sections in separate files in a subfolder (`sections/`), found by `--init` by following the `\input`s.
* A macro that draws a TikZ picture, with an optional argument (`\spider[X]{\beta}`). `--init` finds it in the
  preamble, including its arguments, so it is added to `tikz_macros`.
* Figures made with TikZiT (`\tikzfig`, with the styles in `zx.tikzstyles`), and with plain TikZ: a `tikzpicture` in a
  figure, and an inline `\tikz` in its caption.
* Numbered equations, a proposition containing an equation, and an `align*` whose references (`\eqref` and `\ref`)
  are links in the svg.
* A bibliography with biblatex and biber.

If you change the preamble of `paper.tex`, also change `svgbase.tex`, which contains a copy of it. Or regenerate
the three files with `tikz2html --init paper.tex --overwrite`; any changes you made to them are then lost.

The figures in `figures/` and `zx.tikzstyles` come from the book *Picturing Quantum Software* by Aleks Kissinger and
John van de Wetering, and are included under the MIT licence of this repository. `tikzit.sty` is part of
[TikZiT](https://tikzit.github.io) and is included unchanged, under TikZiT's own licence.
