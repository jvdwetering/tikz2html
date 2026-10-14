"""The complete conversion: scanning the sources, building the svgs, running make4ht, linking the svgs."""

import fnmatch
import os
import re
import time
from dataclasses import dataclass, field

from . import html_build, svg_links
from .config import Config
from .discover import find_includes
from .errors import Tikz2HtmlError, require_program
from .latex_scan import scan, strip_comments, assign_ids, LatexScanError
from .svg_build import SvgBuilder, collect_jobs, svg_info


@dataclass
class SourceFile:
    name: str           # Name without the .tex extension
    text: str           # Preprocessed text (comments stripped, replacements applied)
    encoding: str
    blocks: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def read_text(path):
    """Reads a source file as utf-8, falling back to latin-1 (which can decode anything)."""
    for encoding in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, newline="") as f:
                return f.read(), encoding
        except UnicodeDecodeError:
            continue


def preprocess(text: str, config: Config) -> str:
    text = text.replace("\r\n", "\n")
    text = strip_comments(text, config.verbatim_environments)
    for pattern, replacement in config.preprocess_replacements:
        text = re.sub(pattern, lambda m: replacement, text)
    return text


def load_sources(config: Config):
    """Reads and scans all source files, and assigns an id (svg file name) to every block."""
    sources = []
    scan_config = config.scan_config
    for name in config.tex_files:
        path = config.path(name + ".tex")
        if not os.path.isfile(path):
            key = "main_name" if name == config.main_name else "other_tex_files"
            raise Tikz2HtmlError(f"The source file {path} does not exist (from '{key}' in the configuration; "
                                 f"give the names without .tex, relative to the folder of the configuration)")
        text, encoding = read_text(path)
        try:
            text = preprocess(text, config)
        except re.error as e:
            raise Tikz2HtmlError(f"Invalid regular expression in preprocess_replacements: {e}")
        try:
            blocks, skipped = scan(text, scan_config, filename=name)
        except LatexScanError as e:
            message = str(e).replace(f"{name}:", f"{name}.tex:", 1)
            raise Tikz2HtmlError(f"Could not scan the LaTeX source: {message} (line numbers are counted after "
                                 f"removing comment lines, so the actual line can be a bit further down)")
        sources.append(SourceFile(name, text, encoding, blocks, skipped))
    assign_ids([b for s in sources for b in s.blocks], scan_config)
    return sources


def unlisted_includes(config: Config, sources):
    """Included .tex files that are not in the configuration but contain TikZ: their figures would not be
    converted. Returns a list of (file name without .tex, including file, number of blocks)."""
    listed = {os.path.normcase(config.path(name + ".tex")) for name in config.tex_files}
    found, seen = [], set()
    for source in sources:
        base = os.path.dirname(config.path(source.name + ".tex"))
        for _, path in find_includes(source.text, config.root, base):
            if not path or not path.endswith(".tex") or os.path.normcase(path) in listed | seen:
                continue
            seen.add(os.path.normcase(path))
            text, _ = read_text(path)
            try:
                blocks, _ = scan(preprocess(text, config), config.scan_config, filename=path)
            except (LatexScanError, re.error):
                continue
            if blocks:
                name = os.path.relpath(path, config.root).replace(os.sep, "/")[:-4]
                found.append((name, source.name, len(blocks)))
    return found


def make_selector(only=None, files=None):
    """A predicate on svg jobs selecting those matching one of the patterns in `only` (on the id, the labels or
    the figure names) and appearing in one of `files`."""
    if not only and not files:
        return None

    def select(job):
        if files and not any(b.file in files for b in job.blocks):
            return False
        if only:
            names = {job.id} | {label for b in job.blocks for label in b.labels} | set(job.figures)
            return any(fnmatch.fnmatchcase(n, p) for p in only for n in names)
        return True
    return select


class Pipeline:
    def __init__(self, config: Config, log=print):
        self.config = config
        self.log = log
        self.report = []
        self.failed = False   # Set when the result is incomplete: svgs failed, or make4ht failed

    def aux_labels(self):
        return svg_links.parse_aux(os.path.join(self.config.html_dir, self.config.main_name + ".aux"))

    def build_svgs(self, jobs, force=False, select=None):
        labels = self.aux_labels()
        builder = SvgBuilder(self.config, {k: v for k, (v, _) in labels.items()}, self.log)
        return builder, builder.build(jobs, force=force, select=select)

    def run(self, only=None, files=None, force=False, skip_svgs=False, skip_html=False, draft=False,
            prune=False):
        config = self.config
        t0 = time.time()
        os.makedirs(config.svg_dir, exist_ok=True)
        sources = load_sources(config)
        blocks = [b for s in sources for b in s.blocks]
        jobs = collect_jobs(blocks)
        self.log(f"Found {len(blocks)} TikZ blocks in {len(sources)} files, giving {len(jobs)} distinct svgs")
        for name, parent, count in unlisted_includes(config, sources):
            self.report.append(f"{name}.tex is included in {parent}.tex and contains {count} TikZ blocks, but it is "
                               f"not in other_tex_files, so they are not converted")
        if files:
            unknown = [f for f in files if f not in config.tex_files]
            if unknown:
                raise Tikz2HtmlError(f"Unknown files {', '.join(unknown)} for --files; the files in the configuration "
                                     f"are {', '.join(config.tex_files)}")
        select = make_selector(only, files)
        selected_jobs = [j for j in jobs.values() if select is None or select(j)]
        if only:
            self.log(f"Selected {len(selected_jobs)} svgs: " + ", ".join(j.id for j in selected_jobs[:20]) +
                     (" ..." if len(selected_jobs) > 20 else ""))
            if not selected_jobs:
                self.log("Warning: --only matches no svg. It matches svg names, labels and figure names (use "
                         "--list to see them); wildcards like 'spider-*' are allowed.")
        self.check_figures(selected_jobs)

        # 1. Svgs, using the labels of the previous make4ht run for the references
        results = []
        if not skip_svgs:
            require_program(config.latex_cmd, "latex_cmd")
            require_program(config.dvisvgm_cmd, "dvisvgm_cmd")
            builder, results = self.build_svgs(selected_jobs if only else list(jobs.values()), force, select)

        # 2. The html
        if not skip_html:
            require_program(config.make4ht_cmd, "make4ht_cmd")
            if config.bibtex and not draft:
                require_program(config.bibtex.split(), "bibtex")
            cache_files = {r.job.id: r.cache_file for r in results if r.cache_file}
            info = {svg_id: svg_info(cache_files.get(svg_id) or os.path.join(config.svg_dir, svg_id + ".svg"))
                    for svg_id in jobs}
            self.write_html_sources(sources, info, files)
            html_build.copy_files(config)
            self.log("Running make4ht" + (" (draft mode)" if draft else "") + ", this can take a while...")
            t1 = time.time()
            code = html_build.run_make4ht(config, draft=draft, log=self.log)
            errors = html_build.latex_errors(os.path.join(config.html_dir, config.main_name + ".log"))
            self.log(f"make4ht finished with exit code {code} in {time.time() - t1:.0f}s, {len(errors)} TeX errors")
            for e in errors[:10]:
                self.report.append("TeX error in the html run: " + e.replace("\n", " | "))
            self.report += html_build.bibtex_problems(config)
            main_html = os.path.join(config.html_dir, config.main_name + ".html")
            produced = os.path.exists(main_html) and os.path.getmtime(main_html) >= t1 - 1
            if code != 0 or not produced:
                self.failed = True
                problem = f"make4ht failed (exit code {code})" if produced else "make4ht did not produce the html"
                self.report.append(f"{problem}; see {config.main_name}.log and {config.main_name}-make4ht.log in "
                                   f"{config.html_dir}")
                if not produced:
                    self.summarize(results, time.time() - t0)
                    raise Tikz2HtmlError(problem + ". " + ("The first TeX error: " + errors[0].replace("\n", " | ")
                                         if errors else f"See {config.main_name}-make4ht.log in {config.html_dir}"))

            # 3. Rebuild the svgs whose references changed in this run
            if not skip_svgs:
                builder, results = self.build_svgs(selected_jobs if only else list(jobs.values()), False, select)

        # 4. Links in the svgs
        if results:
            self.write_linked_svgs(results)
            if prune and not only and not files:
                self.prune(builder, results, jobs)
        self.summarize(results, time.time() - t0)
        return results

    def write_html_sources(self, sources, svg_info, files=None):
        config = self.config
        os.makedirs(config.html_dir, exist_ok=True)
        fragments = html_build.Fragments(config)
        for source in sources:
            text = html_build.replace_blocks(source.text, source.blocks, source.skipped, config, svg_info, fragments)
            if source.name == config.main_name and files:
                text = html_build.restrict_subfiles(text, set(files) | {config.main_name}, config.tex_files)
            path = os.path.join(config.html_dir, source.name + ".tex")
            os.makedirs(os.path.dirname(path), exist_ok=True)  # For files in subfolders (sections/intro.tex)
            with open(path, "w", encoding=source.encoding, newline="\n") as f:
                f.write(text)
        with open(os.path.join(config.html_dir, html_build.fragments_file_name(config)), "w", encoding="utf-8") as f:
            f.write(fragments.definitions())
        self.log(f"Written {len(sources)} tex files to {config.html_dir}")

    def check_figures(self, jobs):
        """Reports figures that don't exist (TikZiT then draws a red box with the name of the figure), or whose
        file name differs in case (works on Windows and macOS, but not on Linux)."""
        folder = self.config.path(self.config.figure_folder)
        existing = {f[:-5] for f in os.listdir(folder) if f.endswith(".tikz")} if os.path.isdir(folder) else set()
        lower = {f.lower(): f for f in existing}
        uses = {}  # missing figure -> places where it is used
        for job in jobs:
            for name in job.figures:
                if name not in existing:
                    uses.setdefault(name, [])
                    uses[name] += [f"{b.file}.tex:{b.line}" for b in job.blocks if name in b.figures]
        for name, places in uses.items():
            where = ", ".join(sorted(set(places), key=places.index)[:5]) + (", ..." if len(set(places)) > 5 else "")
            if name.lower() in lower:
                self.report.append(f"Figure '{name}' (used in {where}) is called '{lower[name.lower()]}.tikz'; this "
                                   f"only works on a case-insensitive file system (Windows, macOS)")
            else:
                self.failed = True
                self.report.append(f"Figure '{name}' (used in {where}) not found: {os.path.join(folder, name)}.tikz "
                                   f"does not exist, so the svg shows a red box with its name instead")

    def write_linked_svgs(self, results):
        config = self.config
        files = html_build.html_files(config)
        if not files:
            self.log("The html has not been generated yet; the links in the svgs are added when it is")
        anchors = svg_links.anchor_files(config.html_dir, files) if files else {}
        targets = svg_links.label_targets(self.aux_labels(), anchors)
        missing = set()
        for r in results:
            if not r.cache_file:
                continue
            with open(r.cache_file, "r", encoding="utf-8") as f:
                svg = f.read()
            svg, unresolved = svg_links.link_svg(svg, targets, target=config.svg_link_target)
            missing.update(unresolved)
            with open(os.path.join(config.svg_dir, r.job.id + ".svg"), "w", encoding="utf-8") as f:
                f.write(svg)
        if missing and files:
            self.report.append(f"{len(missing)} labels referenced in svgs could not be linked: " +
                               ", ".join(sorted(missing)[:30]))

    def prune(self, builder, results, jobs):
        removed = builder.prune_cache(results)
        stale = [f for f in os.listdir(self.config.svg_dir) if f.endswith(".svg") and f[:-4] not in jobs]
        for f in stale:
            os.remove(os.path.join(self.config.svg_dir, f))
        self.log(f"Pruned {removed} cache entries and {len(stale)} unused svgs")

    def summarize(self, results, seconds):
        counts = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        svgs = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
        self.log(f"Done in {seconds:.0f}s." + (f" Svgs: {svgs}" if svgs else ""))
        if any(r.status == "failed" for r in results):
            self.failed = True
        for r in results:
            if r.status == "failed":
                self.report.append(f"svg FAILED: {r.job.description}: {r.message}")
            elif r.errors:
                self.report.append(f"svg compiled with {len(r.errors)} errors: {r.job.description}: " +
                                   r.errors[0].replace("\n", " | ")[:200])
        path = os.path.join(self.config.html_dir, "tikz2html-report.txt")
        if not self.report and os.path.exists(path):
            os.remove(path)  # The report of an earlier run
        if self.report:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.report) + "\n")
            self.log(f"{len(self.report)} problems, see {path}:")
            for line in self.report[:15]:
                self.log("  " + line[:250])
