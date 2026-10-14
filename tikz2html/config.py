"""Configuration of the conversion, loaded from a JSON file (``html_config.json`` by default).

All keys are optional except ``main_name``. Relative paths are interpreted relative to the folder containing
the configuration file, which is also the folder in which LaTeX is run when compiling the SVGs.
See README.md for a description of all the keys.
"""

import difflib
import json
import os
from dataclasses import dataclass, field, fields

from .errors import Tikz2HtmlError
from .latex_scan import ScanConfig, DEFAULT_MATH_ENVIRONMENTS, DEFAULT_DEFINITION_MACROS

DEFAULT_HTML_TEMPLATES = {
    # {src}: path of the svg relative to the html, {name}: id of the diagram, {width}, {height}: size in px,
    # {size}: the width and height attributes, {ratio}: aspect ratio, {valign}: vertical alignment for inline
    # images, {object}: the rendered "object" template, {numbers}: the equation numbers,
    # {number}: a single equation number or tag.
    # Svgs are embedded with <object> (not <img>) so that the links inside them can be clicked.
    "object": '<object data="{src}" type="image/svg+xml" class="svg-diagram"{size} '
              'style="max-width: 100%; height: auto; aspect-ratio: {ratio}" aria-label="diagram {name}"></object>',
    "inline": '<img src="{src}" alt="diagram {name}" class="inline-diagram"{size} '
              'style="vertical-align: {valign}; max-width: 100%; height: auto" />',
    # Inline svgs that contain links
    "inline_linked": '<object data="{src}" type="image/svg+xml" class="inline-diagram"{size} '
                     'style="vertical-align: {valign}; max-width: 100%; height: auto; aspect-ratio: {ratio}" '
                     'aria-label="diagram {name}"></object>',
    "display": '<table class="equation"><tr><td>{object}</td><td class="eq-no">{numbers}</td></tr></table>',
    "display_unnumbered": '<table class="equation-star"><tr><td>{object}</td></tr></table>',
    "block": "{object}",
    "number": '<span class="eq-no-item">({number})</span>',
    "number_tag_star": '<span class="eq-no-item">{number}</span>',
}


@dataclass
class Config:
    main_name: str
    root: str = "."                       # Folder of the config file; set automatically
    other_tex_files: list = field(default_factory=list)
    html_folder: str = "html"
    svg_subfolder: str = "svgs"
    figure_folder: str = "figures"

    # --- scanning ---
    tikz_macros: dict = field(default_factory=lambda: {"tikzfig": "m", "ctikzfig": "m", "tikz": "ot"})
    tikz_environments: list = field(default_factory=lambda: ["tikzpicture"])
    math_environments: dict = field(default_factory=dict)        # Additions/overrides of the defaults
    standalone_kinds: dict = field(default_factory=lambda: {"ctikzfig": "block"})
    skip_environments: list = field(default_factory=lambda: ["comment"])
    verbatim_environments: list = field(default_factory=lambda: ["verbatim", "verbatim*", "lstlisting", "minted"])
    definition_macros: dict = field(default_factory=dict)        # Additions/overrides of the defaults
    ref_macros: list = field(default_factory=lambda: ["ref", "eqref", "hyperref", "autoref", "cref", "Cref", "pageref"])
    figure_macros: list = field(default_factory=lambda: ["tikzfig", "ctikzfig"])
    dedupe_aliases: dict = field(default_factory=lambda: {"ctikzfig": "tikzfig"})
    preprocess_replacements: list = field(default_factory=list)  # [[regex, literal replacement], ...]

    # --- svg generation ---
    svg_basefile: str = "svgbase.tex"
    svg_preamble_extra: list = field(default_factory=list)        # Lines added before \begin{document}
    svg_dependencies: list = field(default_factory=list)          # Files that all svgs depend on (styles, macros)
    latex_cmd: list = field(default_factory=lambda: ["latex", "-interaction=nonstopmode"])
    dvisvgm_cmd: list = field(default_factory=lambda: ["dvisvgm", "--font-format=woff", "--linkmark=box", "-O"])
    svg_timeout: int = 300
    jobs: int = 0                                                 # 0: number of CPUs

    # --- html generation ---
    make4ht_config: str = ""                                      # The user's tex4ht .cfg file (optional)
    make4ht_options: str = ""                                     # tex4ht options; default "mathml,mathjax,next,<split_depth>"
    split_depth: int = 2
    make4ht_format: str = "html5"
    make4ht_extensions: list = field(default_factory=list)       # e.g. ["common_domfilters"]
    make4ht_flags: list = field(default_factory=list)            # Additional command line flags for make4ht
    bibtex: str = "bibtex"                                        # Empty to disable
    latex_passes: int = 2                                         # Number of make4ht latex passes after bibtex
    additional_css: list = field(default_factory=list)           # css files, linked from every html page
    additional_html: str = ""                                     # html file, inserted at the end of every body
    extra_js: list = field(default_factory=list)                 # js files, loaded at the end of every body
    files_to_copy: list = field(default_factory=list)            # Files that the html needs (images, js, ...)
    html_templates: dict = field(default_factory=dict)           # Overrides of DEFAULT_HTML_TEMPLATES
    svg_link_target: str = "_parent"
    clean_keep: list = field(default_factory=list)               # Patterns of files that --clean must keep
    svg_scale: float = 1.0                                       # Size of the display svgs relative to the pdf
    inline_svg_scale: float = 1.0                                 # Size of the inline svgs relative to the pdf

    make4ht_cmd: str = "make4ht"
    make4ht_timeout: int = 3600                                   # Seconds; 0 for no limit
    warnings: list = field(default_factory=list, repr=False)      # Set by from_json, not a configuration key

    # Legacy keys
    also_process_with_svg: list = field(default_factory=list)
    svg_basefile_main_placeholder: str = "MAIN_FILE"

    @staticmethod
    def from_json(fname):
        """Loads and checks a configuration file. Problems that make the conversion impossible raise a
        Tikz2HtmlError; others (like unknown keys) are collected in config.warnings."""
        try:
            with open(fname, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            raise Tikz2HtmlError(f"The configuration file {os.path.abspath(fname)} does not exist. Run tikz2html "
                                 f"in the folder of your document, or give the file with --config.")
        except json.JSONDecodeError as e:
            raise Tikz2HtmlError(f"The configuration file {fname} is not valid JSON: {e.msg} at line {e.lineno}, "
                                 f"column {e.colno}. (Note that JSON doesn't allow trailing commas, and that "
                                 f"backslashes must be doubled.)")
        if not isinstance(data, dict):
            raise Tikz2HtmlError(f"The configuration file {fname} must contain a JSON object ({{...}})")
        if "main_name" not in data:
            raise Tikz2HtmlError(f"The configuration file {fname} must give 'main_name': the name of the main tex "
                                 f"file, without .tex")
        types = {f.name: f.type for f in fields(Config)}
        alternatives = {"tikz_macros": (dict, list), "latex_cmd": (list, str), "dvisvgm_cmd": (list, str),
                        "additional_css": (list, str), "svg_scale": (float, int), "inline_svg_scale": (float, int)}
        warnings = []
        for key in list(data):
            if key.startswith("_") or key.startswith("//"):  # comments
                del data[key]
            elif key not in types or key in ("root", "warnings"):
                close = difflib.get_close_matches(key, [k for k in types if k not in ("root", "warnings")], n=1)
                warnings.append(f"Unknown configuration key {key!r} (ignored)" +
                                (f"; did you mean {close[0]!r}?" if close else ""))
                del data[key]
            else:
                expected = alternatives.get(key, (types[key],))
                if not isinstance(data[key], expected) or (isinstance(data[key], bool) and bool not in expected):
                    names = " or ".join({dict: "an object", list: "a list", str: "a string", int: "a number",
                                         float: "a number", bool: "true/false"}[t] for t in expected)
                    raise Tikz2HtmlError(f"The configuration key {key!r} in {fname} must be {names}, "
                                         f"not {json.dumps(data[key])}")
        data["root"] = os.path.dirname(os.path.abspath(fname))
        config = Config(**data, warnings=warnings)
        config.normalize()
        return config

    def normalize(self):
        """Converts legacy formats of options into the current ones."""
        if isinstance(self.tikz_macros, list):
            self.tikz_macros = {name: "m" for name in self.tikz_macros}
        self.tikz_macros = {name.lstrip("\\"): spec for name, spec in self.tikz_macros.items()}
        for item in self.also_process_with_svg:
            item = item.strip()
            if item.startswith("begin{") or item.startswith("\\begin{"):
                env = item[item.index("{") + 1:item.rindex("}")]
                if env not in self.tikz_environments:
                    self.tikz_environments.append(env)
            elif item.startswith("\\"):
                self.tikz_macros.setdefault(item[1:], "")
            else:
                self.warnings.append(f"Don't know how to interpret {item!r} in also_process_with_svg (ignored)")
        self.also_process_with_svg = []
        if isinstance(self.additional_css, str):
            self.additional_css = [self.additional_css] if self.additional_css else []
        if not self.make4ht_options:
            self.make4ht_options = f"mathml,mathjax,next,{self.split_depth}"
        if isinstance(self.latex_cmd, str):
            self.latex_cmd = self.latex_cmd.split()
        if isinstance(self.dvisvgm_cmd, str):
            self.dvisvgm_cmd = self.dvisvgm_cmd.split()
        for name, spec in self.tikz_macros.items():
            if not isinstance(spec, str) or set(spec) - set("most"):
                raise Tikz2HtmlError(f"Invalid argument specification {spec!r} for the macro {name!r} in "
                                     f"tikz_macros: use a string of m (mandatory argument), o (optional [...] "
                                     f"argument), s (optional star) and t (the body of \\tikz), e.g. \"om\", "
                                     f"or \"\" for no arguments")

    # --- derived values ---

    def path(self, *parts):
        return os.path.normpath(os.path.join(self.root, *parts))

    @property
    def html_dir(self):
        return self.path(self.html_folder)

    @property
    def svg_dir(self):
        return self.path(self.html_folder, self.svg_subfolder)

    @property
    def tex_files(self):
        """The source files (without extension), main file first."""
        return [self.main_name] + [f for f in self.other_tex_files if f != self.main_name]

    @property
    def templates(self):
        t = dict(DEFAULT_HTML_TEMPLATES)
        t.update(self.html_templates)
        return t

    @property
    def scan_config(self) -> ScanConfig:
        math_envs = dict(DEFAULT_MATH_ENVIRONMENTS)
        for name, value in self.math_environments.items():
            if value is None:
                math_envs.pop(name, None)
            else:
                math_envs[name] = tuple(value) if isinstance(value, list) else (value, None)
        definition_macros = dict(DEFAULT_DEFINITION_MACROS)
        definition_macros.update(self.definition_macros)
        return ScanConfig(
            tikz_macros=dict(self.tikz_macros),
            tikz_environments=list(self.tikz_environments),
            math_environments=math_envs,
            standalone_kinds=dict(self.standalone_kinds),
            skip_environments=list(self.skip_environments),
            verbatim_environments=list(self.verbatim_environments),
            definition_macros=definition_macros,
            ref_macros=list(self.ref_macros),
            figure_macros=list(self.figure_macros),
            dedupe_aliases=dict(self.dedupe_aliases),
        )

    @property
    def num_jobs(self):
        return self.jobs if self.jobs > 0 else (os.cpu_count() or 1)
