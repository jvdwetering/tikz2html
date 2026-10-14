# tikz2html

Converts a LaTeX document with many TikZ figures, in particular figures made with [TikZiT](https://tikzit.github.io/),
to html. [make4ht](https://github.com/michal-h21/make4ht) (tex4ht) converts the text well, but on its own it does a
poor job with TikZ pictures, especially inside equations. tikz2html takes care of the figures:

1. It **finds** every equation, `center` environment, etc. that contains a TikZ figure.
2. It **compiles** each of these into an svg with `latex` and `dvisvgm`, in parallel and with a cache, so that a
   rerun only recompiles what changed.
3. It **replaces** them with placeholders in a copy of the sources, and runs **make4ht** on that copy. The
   placeholders produce the svg images directly in the html, so equation numbers, `\tag`s, `\label`s and cross
   references keep working.
4. It **links** the references (`\ref`, `\eqref`, `\hyperref`) inside the svgs to the right place in the html.

This package was written for the html version of the book
[*Picturing Quantum Software*](https://zxcalc.github.io/book/html/main_html.html), which has more than a thousand
diagrams though it should work just as well for a paper.
The code is based on an initial (quite buggy) human-made conversion script, and then transformed into a hopefully more reliable reusable package by Claude Code. Use at your own risk.

## Installation

You need:

* a TeX distribution (TeX Live or MiKTeX) with `latex`, `dvisvgm`, `make4ht`, and `bibtex` or `biber`;
* Python 3.9 or later. tikz2html has no other Python dependencies.

Then install tikz2html with

```
pip install git+https://github.com/<user>/tikz2html
```

or clone the repository and run `pip install .` in it. This gives the command `tikz2html`. Without installing,
`python -m tikz2html` works from the folder that contains the `tikz2html` package.

## Getting started with your own document

1. **Set up the configuration.** In the folder of your document, run

   ```
   tikz2html --init main.tex
   ```

   with the tex file that you compile (the one with `\documentclass`). This analyses the document and writes
   three files next to it:

   * **`html_config.json`**: the configuration. It contains:
     * the included tex files, found by following `\input`, `\include`, `\subfile` and `\import`;
     * the macros that draw TikZ, with their arguments, found from their definitions;
     * environments left out with `\excludecomment`;
     * the bibliography;
     * the files that need to be copied.
   * **`svgbase.tex`**: the template in which every diagram is compiled. It contains a copy of your preamble, so
     that your macros, colours and TikZ styles are available.
   * **`tikz2html.cfg`**: a tex4ht configuration to start from.

   `--init` doesn't overwrite existing files, unless you add `--overwrite`.

2. **Check the configuration.** In particular `tikz_macros`: every equation using one of these macros becomes an
   svg. Remove macros that you would rather have converted by tex4ht (see the next section). New tex files are not
   added automatically: add them to `other_tex_files` (tikz2html warns when an included file with figures is
   missing from it).
3. **See what will become an svg:** `tikz2html --list` prints every block with its file, line and svg name.
4. **Convert:** `tikz2html`. The html is in `html/` (open `html/<main>.html`). A first run compiles all the svgs;
   later runs only recompile what changed. Problems in the conversion are listed at the end, and in `html/tikz2html-report.txt`.
5. **Publish:** `tikz2html --clean` removes all the work files from `html/`, so that the folder can be uploaded
   as it is.

### Adapting the result

* **A diagram doesn't compile.** Its `.tex` and `.log` are in `html/svgs/_failed/`. The cause is usually a package
  in the preamble copied into `svgbase.tex` that doesn't work in dvi mode, or a macro that isn't defined there.
  Edit `svgbase.tex`; it is yours to change. Rebuild a single diagram with `tikz2html --skip-html --only <name>`.
* **Something in the text looks wrong.** That part is converted by tex4ht. Macros that tex4ht handles badly can
  get an html-friendly definition, which only tex4ht sees:

  ```latex
  \begin{document}
  \ifdefined\HCode
    \renewcommand{\mymacro}[1]{...}   % e.g. with \HCode{<mrow>...</mrow>} to produce MathML directly
  \fi
  ```

  Put such definitions **after** `\begin{document}`: tex4ht loses sub- and superscripts in macros defined in the
  preamble. If you do this for a macro that draws TikZ, also remove it from `tikz_macros`.

* **Layout and style.** Add your own css and javascript with `additional_css` and `extra_js`. Change the size of the
  diagrams with `svg_scale`. Change the html of the diagrams with `html_templates`. Use more tex4ht settings in
  `tikz2html.cfg`, e.g. one page per section with `make4ht_options` `"mathml,mathjax,next,3"`.
* **Working on a big document.** `tikz2html --files chapter3 --draft` converts one chapter in a single LaTeX pass;
  `--only` rebuilds a few svgs.

The folder [`examples/`](examples) contains two complete projects: [a book](examples/book) with a hand-made
configuration, and [a paper](examples/article) that was set up with `--init` alone.

## Usage

```
tikz2html [--config html_config.json] [options]
```

| Option | Meaning |
|---|---|
| `--init MAIN.tex` | Set up a document: write `html_config.json`, `svgbase.tex` and `tikz2html.cfg` next to the main file. Add `--overwrite` to replace existing files. |
| `--list` | List the blocks found (file:line, kind, environment, svg name, labels), then exit. |
| `--only a,eq:b,spider-*` | Only (re)build the svgs with these names, labels or figure names (wildcards allowed). Other svgs come from the cache. |
| `--files intro,ch2` | Only put these source files in the html (the other `\subfile`/`\include`/`\input`s are commented out). Good for quick tests. |
| `--draft` | Run make4ht in draft mode: one LaTeX pass, no bibtex. |
| `--skip-svgs`, `--skip-html` | Skip a stage. |
| `--force` | Recompile the selected svgs even when they are cached. |
| `--jobs N` | Number of parallel svg compilations (default: number of CPUs). |
| `--prune` | After the conversion, delete cache entries and svgs that are no longer used. Keeps everything needed for a fast rerun. |
| `--clean` | Only delete everything in the html folder that is not needed to view the html, then exit (see below). |
| `--clean --dry-run` | Only list what `--clean` would delete. |
| `--clean --keep-cache` | Clean, but keep the svg cache, so that a later conversion doesn't have to recompile all svgs. |

**Cleaning up.** `--clean` is meant for publishing the html, after a complete conversion. It follows the references
from the main html page: links, stylesheets, scripts, images, svg objects, `url(...)` in css, and links in svgs.
Every file directly in the html folder or in the svg folder that is not reached this way is deleted. That covers
the tex, aux and log files, the generated configuration, the svg cache and build folders, and pages or svgs of
earlier runs. Other subfolders of the html folder are left alone. Files that are only loaded by javascript can't be
found this way; list them in `clean_keep` (glob patterns relative to the html folder, e.g. `["data/*.json"]`).
After `--clean`, the next conversion recompiles all svgs, unless `--keep-cache` was used, and reruns all LaTeX
passes.

Problems are printed at the end and written to `<html folder>/tikz2html-report.txt`. They include failed svgs, TeX
errors, missing figures, bibtex problems and references that could not be linked. The `.tex` and `.log` of svgs
that failed or had errors are kept in `<svg folder>/_failed/`.

**Errors and exit codes.** When the conversion can't be done, tikz2html prints one line starting with
`tikz2html: error:` and stops. This happens when the configuration or a file it names is missing or invalid, a
source file can't be scanned, latex, dvisvgm, make4ht or bibtex is not installed (checked before the step that
needs it), make4ht produces no html, or the first 8 svgs all fail (a sign of a problem with the svg template).
Unknown configuration keys give a warning, with a suggestion for a misspelled key. The exit code is:

| Code | Meaning |
|---|---|
| 0 | Success. The report may still list warnings, such as svgs compiled with LaTeX errors. |
| 1 | The conversion finished, but the result is incomplete: svgs failed, figures are missing, or make4ht reported errors. |
| 2 | The conversion could not be done (see the error message). |
| 130 | Interrupted (Ctrl+C). |

## How a figure ends up in the html

| In the source | Becomes |
|---|---|
| A math environment containing a trigger (`equation`, `align`, `gather`, `multline`, `eqnarray`, `alignat`, `flalign`, starred versions, `displaymath`, `\[..\]`, `$$..$$`) | One svg `<object>` in a table, with the equation numbers (one per numbered row) next to it |
| Inline math containing a trigger (`$..$`, `\(..\)`, `math`) | An `<img>`, aligned with the baseline of the text |
| A `center` environment containing a trigger, or a `\ctikzfig` | An `<object>` in a centered `div` |
| A trigger outside of all of these (e.g. `\tikzfig` in a table cell or a figure) | An `<img>` (or as configured with `standalone_kinds`) |

A *trigger* is one of the `tikz_macros` (e.g. `\tikzfig`) or `tikz_environments` (e.g. `tikzpicture`).

Details:

* The svg is compiled from the original LaTeX, with `\label`, `\tag`, `\nonumber` and `\notag` removed, and numbered
  environments made unnumbered (the numbers are put in the html instead).
* In the html, numbered environments step the `equation` counter as in the pdf, so all later equation numbers
  agree with the pdf. `\label`s and `\tag`s work as usual, also in `align`s with several labels.
* Blocks with the same content share one svg, so a figure that is used several times is only compiled once.
  `\ctikzfig{x}` and `\tikzfig{x}` count as the same content (see `dedupe_aliases`).
* The svg is named after the first `\label` in the block, otherwise after the first figure. Blocks with different
  content but the same name get a suffix `-1`, `-2`, ...
* Comments, `verbatim`, `\verb`, macro definitions (`\newcommand` etc.) and the `skip_environments` are not scanned.
  The `skip_environments` are also removed from the html.
* Display svgs are embedded with `<object>`, so that the links inside them work. Inline svgs use `<img>`, unless
  they contain links: those use `<object>` too.

## Configuration

The configuration is a JSON file. Only `main_name` is required. Paths are relative to the configuration file.
LaTeX is run in that folder when compiling the svgs, so `\tikzfig` finds `./figures`. Keys starting with `_`
are comments.

**Sources**

* `main_name`: the main tex file (without `.tex`).
* `other_tex_files`: the other tex files that are part of the document (included with `\subfile`, `\input`, ...),
  without `.tex`, relative to the configuration file.
* `html_folder` (`"html"`), `svg_subfolder` (`"svgs"`), `figure_folder` (`"figures"`).

**Scanning**

* `tikz_macros`: the macros that produce TikZ pictures, mapped to their arguments in xparse style: `m` is a
  mandatory argument, `o` an optional `[..]` argument, `s` an optional star, `t` the body of a `\tikz` command, and
  `""` means no arguments. For example `{"tikzfig": "m", "state": "om", "emptydiag": "", "tikz": "ot"}`. A plain
  list means one mandatory argument each.
* `tikz_environments` (`["tikzpicture"]`): environments that produce TikZ pictures, or that should be rendered as an svg.
* `math_environments`: additions or changes to the environments that are turned into one svg as a whole, as
  `name: [kind, numbering]` with kind `display`, `inline` or `block`, and numbering `null`, `"single"` or `"rows"`.
  `name: null` removes an environment.
* `standalone_kinds` (`{"ctikzfig": "block"}`): the kind of a trigger that is not inside a math environment (default `inline`).
* `skip_environments` (`["comment"]`): environments that are removed (e.g. `solution` when solutions are hidden).
* `verbatim_environments`, `definition_macros`: what is not scanned.
* `ref_macros`, `figure_macros`, `dedupe_aliases`: see `config.py`.
* `preprocess_replacements`: list of `[regex, replacement]`, applied to the sources before scanning, so to both the
  svgs and the html. The replacement is inserted literally.

**Svgs**

* `svg_basefile` (`"svgbase.tex"`): the LaTeX template. `CONTENT_HERE` is replaced by the block, in a `preview`
  environment, and `MAIN_FILE` by the path of the `.aux` file of the html run, for use with
  `\externaldocument{MAIN_FILE}` from the `xr` package. That way references in the svgs show the same numbers as the
  html. To make them into links, the template wraps them in raw dvisvgm specials, like
  `\special{dvisvgm:raw <eqref>#1}...\special{dvisvgm:raw </eqref>}`. See the template that `--init` writes.
* `svg_preamble_extra`: lines added to the template before `\begin{document}`.
* `svg_dependencies`: files that all svgs depend on, such as styles and macros. A change in them invalidates the cache.
* `latex_cmd` (`["latex", "-interaction=nonstopmode"]`), `dvisvgm_cmd`, `svg_timeout` (seconds per svg, `300`),
  `jobs`. The first element of a command can be a full path, if the program is not on the `PATH`.

The cache is in `<svg folder>/.cache`. An svg is recompiled when the generated tex, a `.tikz` file it uses or one of
the `svg_dependencies` changes, or when the number of a label it refers to changes.

**Html**

* `make4ht_config`: your tex4ht configuration file. The placeholder definitions, css and javascript are added to a
  copy of it.
* `make4ht_options` (default `"mathml,mathjax,next,<split_depth>"`), `split_depth`, `make4ht_format` (`"html5"`),
  `make4ht_extensions` (e.g. `["common_domfilters"]`), `make4ht_flags`.
* `make4ht_cmd` (`"make4ht"`), `make4ht_timeout` (`3600` seconds, `0` for no limit). A timeout stops a TeX run
  that is in an endless loop.
* `bibtex` (`"bibtex"`; `"biber"` for biblatex; `""` to disable), `latex_passes` (`2`): the build without
  `--draft` runs latex, bibtex, then `latex_passes` more times.
* `additional_css`: css files, linked from every page after the tex4ht css.
* `extra_js`: javascript files, loaded (deferred) by every page.
* `additional_html`: an html file that is inserted at the end of every page.
* `files_to_copy`: other files the html run or the pages need (images, input files, ...).
* `html_templates`: changes to the html generated for the placeholders. The keys are `object`, `inline`,
  `inline_linked`, `display`, `display_unnumbered`, `block`, `number` and `number_tag_star`. The fields are
  `{src}`, `{name}`, `{width}`, `{height}`, `{size}`, `{ratio}`, `{valign}`, `{object}`, `{numbers}` and `{number}`.
  See `config.py` for the defaults.
* `svg_link_target` (`"_parent"`): the `target` of links in the svgs.
* `clean_keep`: glob patterns (relative to the html folder) of files that `--clean` must keep.
* `svg_scale`, `inline_svg_scale` (`1.0`): size of the display and inline svgs relative to the pdf. The size is
  written into the html as width and height attributes. Don't scale the diagrams with a css `transform` or put them
  behind the text with a negative `z-index`. Either makes them overlap or be covered by the surrounding text, and then
  the links inside them can't be clicked.

## Known limitations

* **tex4ht and preamble macros.** tex4ht loses sub- and superscripts in macros that are defined in the preamble and
  used in math. Define such macros after `\begin{document}`, or give them html-friendly versions there (see
  "Adapting the result").
* **Blocks are converted whole.** A block containing a trigger is converted as a whole: a `center` environment with
  a lot of text and one small figure becomes one image.
* **`$$` after inline math.** A `$$` directly after inline math (`$a$$b$`) is read as display math, like TeX does.
* **Clicking links.** Links inside svgs can only be clicked where the text of the reference is, not between the
  characters.
* **Testing.** tikz2html has mostly been used on Windows with TeX Live. The GitHub workflow runs the tests on Linux
  and macOS too, but the complete conversion has been used less there, and not yet with MiKTeX.

## Future work

* **Speed.** Every diagram is compiled with its own LaTeX run, about 4 seconds each. With many CPUs a thousand
  diagrams take about 10 minutes the first time. Compiling many diagrams in one LaTeX run (the preview package puts
  each on its own page), and splitting the result with dvisvgm, could make this 10 to 50 times faster. Reporting
  errors per diagram would then need more work.
* **XeLaTeX and LuaLaTeX.** The svgs are compiled with `latex` in dvi mode, so documents that need `fontspec` or
  `unicode-math` don't work yet. `dvilualatex`, or `xelatex` with `dvisvgm --pdf`, could be supported through
  `latex_cmd` and `dvisvgm_cmd`. The cache and the check of the output would need small changes.
* **More kinds of references in svgs.** `\eqref`, `\ref` and `\hyperref` inside diagrams become links; `\cref`,
  `\autoref` and `\pageref` show the right text, but are not links yet.
* **Following changes in the document structure.** `--init` finds the included files and TikZ macros once. A
  conversion warns about included files that are missing from the configuration, but doesn't add them, and it
  doesn't notice new TikZ macros.
* **Warning about tex4ht problems.** A check could warn about preamble macros with sub- or superscripts that are
  used in math, since tex4ht renders those wrongly.
* **Accessibility.** The alternative text of a diagram is only its name. It could use the text in the diagram, or a
  description given in the LaTeX source.
* **Dark mode.** Diagrams have a white background in the default css; svgs that adapt their colours would look
  better in dark mode.

## Tests

```
python -m unittest discover tests
```

The tests in `tests/test_end_to_end.py` run latex, dvisvgm and make4ht on a small document and on the examples,
which takes about a minute. Set `TIKZ2HTML_SKIP_SLOW=1` to skip them.

## Contributing

Bug reports and pull requests are welcome. [`CLAUDE.md`](CLAUDE.md) describes how the code works and how to change
it, for people and AI assistants alike. Please add a test for every change in the scanner (`tests/test_latex_scan.py`
runs in milliseconds).

## Licence

All code provived under the MIT license, see [LICENSE](LICENSE). The copies of `tikzit.sty` in the examples are part of TikZiT, and are under TikZiT's own licence.
