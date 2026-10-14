# Example: a book

A small book with figures made in [TikZiT](https://tikzit.github.io/) (taken from the book
*Picturing Quantum Software*), which shows most of what tikz2html can do. Unlike the [example paper](../article),
its configuration was written by hand, with comments that explain the options. To convert it, run this in this
folder:

```
tikz2html
```

(or `python -m tikz2html --config examples/book/html_config.json` from the root of the repository). This takes about
30 seconds. The result is in `html/`; open `html/main.html` in a browser. To see the pdf version, compile `main.tex`
as usual.

## What is in here

| File | Purpose |
|---|---|
| `main.tex`, `diagrams.tex`, `rules.tex` | The document: the main file and two chapters, included with `\input` |
| `preamble.tex` | The preamble, shared by the pdf and the html |
| `figures/*.tikz` | The TikZiT figures, included with `\tikzfig{name}` |
| `example.tikzstyles`, `example.tikzdefs` | Node and edge styles, colours and macros used by the figures |
| `tikzit.sty` | The TikZiT LaTeX package (defines `\tikzfig` and `\ctikzfig`) |
| `references.bib` | Bibliography, to show the bibtex run |
| `html_config.json` | The tikz2html configuration |
| `svgbase.tex` | The template in which each diagram is compiled to an svg |
| `myconfig.cfg` | The tex4ht configuration (links between chapters) |
| `example.css`, `example.js` | Added to every html page |

## What it shows

`diagrams.tex`:

* inline figures, a macro drawing a TikZ picture with an argument (`\Zscalar`) and without (`\emptydiag`),
  and a `tikzpicture` environment in the text;
* `\ctikzfig`, and a `center` environment with text and a figure;
* a numbered equation with a label, an unnumbered display, and a numbered equation without a label;
* a large figure in a `figure` environment, whose rule names (defined in `example.tikzdefs`) link back to the
  figure, with an inline figure in its caption;
* figures in table cells;
* an exercise, and a `solution` that is left out (`skip_environments`);
* a commented-out figure, which is ignored.

`rules.tex`:

* an `align` with two labels (two equation numbers), and a `gather` with a `\nonumber`;
* an equation with a `\tag`;
* an `align*` whose figures contain `\eqref` and `\hyperref`, which become links in the svg, also to the other
  chapter;
* a figure that is used several times, so it is converted only once;
* a theorem with `\qedhere` in a display.

Try changing a figure in `figures/`, and run the conversion again: only the svgs using that figure are rebuilt.
Run with `--list` to see all the blocks that become svgs.
