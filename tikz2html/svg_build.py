"""Compiling the TikZ blocks into svg files with latex and dvisvgm.

Compiled svgs are cached in ``<svg folder>/.cache``, keyed by a hash of everything that goes into them: the
generated tex file (which includes the template), the .tikz files it uses and the files listed in
``svg_dependencies``. The cache also records the labels that are referenced in the svg together with the
values (equation numbers etc.) they had, so that an svg is recompiled when a referenced number changes.
"""

import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from .config import Config
from .errors import Tikz2HtmlError
from .html_build import latex_errors, tex_env

# Definitions needed to read the .aux file written by tex4ht with xr (\externaldocument)
AUX_COMPAT = r"""\makeatletter
\providecommand\rEfLiNK[2]{#2}
\expandafter\providecommand\csname :autoref\endcsname[1]{}
\makeatother
\providecommand\qedhere{}

"""

# Stop when this many svgs fail before any succeeds: then something is wrong with all of them
STOP_AFTER_FAILURES = 8

RAW_REF_RE = re.compile(r"<(eqref|ref|hyperref)>([^<]*)")


@dataclass
class SvgJob:
    id: str
    source: str                 # The LaTeX to put in the preview environment
    figures: list
    blocks: list = field(default_factory=list)

    @property
    def description(self):
        b = self.blocks[0]
        return f"{self.id} ({b.file}.tex:{b.line})"


@dataclass
class SvgResult:
    job: SvgJob
    status: str                 # 'cached', 'built', 'failed', 'skipped'
    cache_file: str = ""
    errors: list = field(default_factory=list)
    message: str = ""


def collect_jobs(blocks):
    """One job per distinct svg: blocks sharing their content share an svg."""
    jobs = {}
    for block in blocks:
        if block.id not in jobs:
            jobs[block.id] = SvgJob(block.id, block.svg_source, list(block.figures))
        job = jobs[block.id]
        if block.kind == "inline" and all(b.kind != "inline" for b in job.blocks):
            # Compile shared svgs as inline when they are used inline somewhere, so that the baseline (needed to
            # align inline images with the text) is right. For the other uses the baseline doesn't matter.
            job.source = block.svg_source
        job.blocks.append(block)
    return jobs


class SvgBuilder:
    def __init__(self, config: Config, label_values: dict, log=print):
        self.config = config
        self.label_values = label_values   # label -> value (e.g. the equation number), from the aux file
        self.log = log
        self.svg_dir = config.svg_dir
        self.cache_dir = os.path.join(self.svg_dir, ".cache")
        self.build_dir = os.path.join(self.svg_dir, ".build")
        self.failed_dir = os.path.join(self.svg_dir, "_failed")
        template = config.path(config.svg_basefile)
        if not os.path.isfile(template):
            raise Tikz2HtmlError(f"The svg template {template} does not exist (from 'svg_basefile' in the "
                                 f"configuration). See example/svgbase.tex for an example.")
        with open(template, "r", encoding="utf-8") as f:
            self.template = f.read()
        if "CONTENT_HERE" not in self.template:
            raise Tikz2HtmlError(f"The svg template {template} must contain CONTENT_HERE (where the diagram goes)")
        self._file_hashes = {}
        self.common_hash = self._hash_files(config.svg_dependencies) + "|" + json.dumps(config.dvisvgm_cmd)

    # --- hashing ---

    def _hash_file(self, path):
        if path not in self._file_hashes:
            h = hashlib.sha256()
            try:
                with open(path, "rb") as f:
                    h.update(f.read())
                self._file_hashes[path] = h.hexdigest()
            except FileNotFoundError:
                self._file_hashes[path] = "missing"
        return self._file_hashes[path]

    def _hash_files(self, files):
        return ",".join(self._hash_file(self.config.path(f)) for f in files)

    def figure_path(self, name):
        return self.config.path(self.config.figure_folder, name + ".tikz")

    def key(self, job: SvgJob, tex: str) -> str:
        h = hashlib.sha256()
        h.update(tex.encode("utf-8"))
        h.update(self.common_hash.encode("utf-8"))
        for name in job.figures:
            h.update(self._hash_file(self.figure_path(name)).encode("utf-8"))
        return h.hexdigest()[:24]

    # --- tex generation ---

    def render_tex(self, job: SvgJob) -> str:
        tex = self.template
        tex = re.sub(r"\\PreviewEnvironment\{PREVIEW_ENVIRONMENT\}[^\n]*", "", tex)  # we use \begin{preview}
        aux = os.path.relpath(os.path.join(self.config.html_dir, self.config.main_name), self.config.root)
        tex = replace_outside_comments(tex, self.config.svg_basefile_main_placeholder, aux.replace(os.sep, "/"))
        body = "\\begin{preview}\n" + job.source.strip() + "\n\\end{preview}"
        tex = replace_outside_comments(tex, "CONTENT_HERE", body)
        preamble = AUX_COMPAT + "".join(line + "\n" for line in self.config.svg_preamble_extra)
        m = re.search(r"^[^%\n]*\\begin\s*\{document\}", tex, re.M)
        if not m:
            raise Tikz2HtmlError(f"The svg template {self.config.svg_basefile} has no \\begin{{document}}")
        pos = m.start() + m.group(0).index("\\begin")
        return tex[:pos] + preamble + tex[pos:]

    # --- cache ---

    def cache_paths(self, key):
        return os.path.join(self.cache_dir, key + ".svg"), os.path.join(self.cache_dir, key + ".json")

    def cache_valid(self, key):
        svg, meta = self.cache_paths(key)
        if not (os.path.exists(svg) and os.path.exists(meta)):
            return False
        data = self.cache_meta(key)
        return all(self.label_values.get(label) == value for label, value in data.get("refs", {}).items())

    def cache_meta(self, key):
        try:
            with open(self.cache_paths(key)[1], "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    # --- building ---

    def build(self, jobs, force=False, select=None, progress=True):
        """Builds the svgs of the given jobs. If select is given, only jobs for which select(job) is true are
        (re)built; others are only taken from the cache. Returns a list of SvgResult."""
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.build_dir, exist_ok=True)
        results, todo = [], []
        for job in jobs:
            tex = self.render_tex(job)
            key = self.key(job, tex)
            selected = select is None or select(job)
            if self.cache_valid(key) and not (force and selected):
                # The errors of the compilation are kept, so that they are reported again
                errors = self.cache_meta(key).get("errors") or []
                errors = errors if isinstance(errors, list) else []
                results.append(SvgResult(job, "cached", self.cache_paths(key)[0], errors))
            elif selected:
                todo.append((job, tex, key))
            else:
                results.append(SvgResult(job, "skipped", message="not in cache and not selected"))
        if todo:
            self.log(f"Compiling {len(todo)} svgs with {self.config.num_jobs} parallel jobs "
                     f"({len(results)} taken from the cache)")
        start = time.time()
        failed = 0
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.config.num_jobs)
        try:
            futures = [pool.submit(self.compile, job, tex, key) for job, tex, key in todo]
            for n, future in enumerate(concurrent.futures.as_completed(futures), 1):
                result = future.result()
                results.append(result)
                if result.status == "failed":
                    failed += 1
                    self.log(f"  FAILED {result.job.description}: {result.message}")
                    if failed == n == STOP_AFTER_FAILURES and len(todo) > STOP_AFTER_FAILURES:
                        raise Tikz2HtmlError(
                            f"The first {failed} svgs all failed, so the conversion was stopped. This usually means "
                            f"that something is wrong with the svg template ({self.config.svg_basefile}) or a file "
                            f"it loads, or with the LaTeX installation. The first error: {result.message}. The "
                            f".tex and .log files are in {self.failed_dir}")
                elif progress and (n % 50 == 0 or n == len(todo)):
                    self.log(f"  {n}/{len(todo)} svgs compiled ({time.time() - start:.0f}s)")
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        return results

    def compile(self, job: SvgJob, tex: str, key: str) -> SvgResult:
        name = job.id
        build = self.build_dir
        tex_file = os.path.join(build, name + ".tex")
        with open(tex_file, "w", encoding="utf-8") as f:
            f.write(tex)
        rel = lambda p: os.path.relpath(p, self.config.root).replace(os.sep, "/")
        env = tex_env(self.config)
        try:
            subprocess.run(self.config.latex_cmd + ["-output-directory=" + rel(build), rel(tex_file)],
                           cwd=self.config.root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=self.config.svg_timeout)
        except subprocess.TimeoutExpired:
            return self._fail(job, f"latex did not finish within {self.config.svg_timeout} seconds (svg_timeout)", [])
        except OSError as e:
            return self._fail(job, f"could not run {self.config.latex_cmd[0]}: {e}", [])
        log_file = os.path.join(build, name + ".log")
        errors = latex_errors(log_file)
        dvi = os.path.join(build, name + ".dvi")
        if not os.path.exists(dvi):
            return self._fail(job, "latex produced no output", errors)
        svg_tmp = os.path.join(build, name + ".svg")
        try:
            r = subprocess.run(self.config.dvisvgm_cmd + ["-o", rel(svg_tmp), rel(dvi)], cwd=self.config.root,
                               env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors="replace", timeout=self.config.svg_timeout)
        except subprocess.TimeoutExpired:
            return self._fail(job, f"dvisvgm did not finish within {self.config.svg_timeout} seconds (svg_timeout)",
                              errors)
        except OSError as e:
            return self._fail(job, f"could not run {self.config.dvisvgm_cmd[0]}: {e}", errors)
        if not os.path.exists(svg_tmp):
            return self._fail(job, "dvisvgm produced no svg: " + r.stdout.strip()[-300:], errors)
        with open(svg_tmp, "r", encoding="utf-8") as f:
            svg = f.read()
        if is_empty_svg(svg):
            return self._fail(job, "the svg is empty", errors)
        if errors:  # Keep the log, but use the svg
            self._keep_log(job, errors)
        refs = {label: self.label_values.get(label) for _, label in RAW_REF_RE.findall(svg) if label}
        svg_cache, meta = self.cache_paths(key)
        shutil.move(svg_tmp, svg_cache)
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({"id": name, "refs": refs, "errors": errors[:3]}, f)
        self._cleanup(name)
        if not errors:
            for ext in (".tex", ".log"):
                p = os.path.join(self.failed_dir, name + ext)
                if os.path.exists(p):
                    os.remove(p)
        return SvgResult(job, "built", svg_cache, errors, "compiled with errors" if errors else "")

    def _keep_log(self, job, errors):
        os.makedirs(self.failed_dir, exist_ok=True)
        for ext in (".tex", ".log"):
            p = os.path.join(self.build_dir, job.id + ext)
            if os.path.exists(p):
                shutil.copy(p, os.path.join(self.failed_dir, job.id + ext))

    def _fail(self, job, message, errors):
        self._keep_log(job, errors)
        self._cleanup(job.id)
        if errors:
            message += ". First error: " + errors[0].replace("\n", " | ")[:300]
        return SvgResult(job, "failed", errors=errors, message=message)

    def _cleanup(self, name):
        for ext in (".tex", ".log", ".aux", ".dvi", ".out", ".svg"):
            p = os.path.join(self.build_dir, name + ext)
            if os.path.exists(p):
                os.remove(p)

    def prune_cache(self, results):
        """Removes cache entries that are not used by any of the results."""
        used = {os.path.basename(r.cache_file)[:-4] for r in results if r.cache_file}
        removed = 0
        for f in os.listdir(self.cache_dir):
            if os.path.splitext(f)[0] not in used:
                os.remove(os.path.join(self.cache_dir, f))
                removed += 1
        return removed


def replace_outside_comments(tex: str, placeholder: str, value: str) -> str:
    """Replaces placeholder by value, except on lines that are comments."""
    return re.sub(r"^(?!\s*%).*$", lambda m: m.group(0).replace(placeholder, value), tex, flags=re.M)


def is_empty_svg(svg: str) -> bool:
    m = re.search(r"<svg[^>]*>", svg)
    if not m:
        return True
    header = m.group(0)
    if re.search(r"width=['\"]0(?:pt)?['\"]", header):
        return True
    vb = re.search(r"viewBox=['\"]([^'\"]*)['\"]", header)
    if vb:
        parts = vb.group(1).split()
        if len(parts) == 4 and (float(parts[2]) == 0 or float(parts[3]) == 0):
            return True
    return False


def svg_metrics(svg: str):
    """Returns (width, height, depth) in pt, where depth is the distance from the baseline to the bottom."""
    m = re.search(r"viewBox=['\"]([^'\"]*)['\"]", svg[:2000])
    if not m:
        return None
    try:
        x, y, w, h = (float(v) for v in m.group(1).split())
    except ValueError:
        return None
    return w, h, h + y


def svg_info(svg_file: str) -> dict:
    """Information about an svg needed for the html: its width, height and depth below the baseline (in pt),
    and whether it contains links. Empty if the svg does not exist."""
    try:
        with open(svg_file, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return {}
    info = {"linked": bool(RAW_REF_RE.search(svg) or "<a " in svg)}
    metrics = svg_metrics(svg)
    if metrics is not None:
        info.update(width=metrics[0], height=metrics[1], depth=metrics[2])
    return info
