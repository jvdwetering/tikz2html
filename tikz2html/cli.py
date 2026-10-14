"""Command line interface. Run ``python -m tikz2html --help`` (or ``python generate_html.py --help``)."""

import argparse
import os
import sys

from .clean import clean
from .config import Config
from .errors import Tikz2HtmlError
from .init import init_project
from .pipeline import Pipeline, load_sources
from .svg_build import collect_jobs


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="tikz2html",
        description="Convert a LaTeX document with many TikZ(iT) figures to html: the figures are compiled to svg "
                    "images, the rest of the document is converted with make4ht.")
    p.add_argument("--init", metavar="MAIN.tex",
                   help="set up a document: analyse the given main tex file (and the files it includes), write a "
                        "first html_config.json, svgbase.tex and tikz2html.cfg next to it, and exit")
    p.add_argument("--overwrite", action="store_true", help="with --init: replace existing files")
    p.add_argument("--config", default="html_config.json", help="configuration file (default: %(default)s)")
    p.add_argument("--list", action="store_true", help="only list the TikZ blocks that were found, and exit")
    p.add_argument("--only", help="comma separated list of svg names, labels or figure names (wildcards allowed) "
                                  "to (re)build; other svgs are only taken from the cache")
    p.add_argument("--files", help="comma separated list of tex files (without .tex) to convert; the other "
                                   "chapters are left out of the html. Useful for quick tests")
    p.add_argument("--force", action="store_true", help="rebuild the (selected) svgs even if they are cached")
    p.add_argument("--skip-svgs", action="store_true", help="don't build svgs")
    p.add_argument("--skip-html", action="store_true", help="don't run make4ht")
    p.add_argument("--draft", action="store_true", help="run make4ht in draft mode (one latex pass, no bibtex)")
    p.add_argument("--jobs", type=int, help="number of svgs to compile in parallel (default: number of cpus)")
    p.add_argument("--prune", action="store_true", help="after the conversion, remove cached and generated svgs that "
                                                        "are no longer used (keeps everything needed for a fast rerun)")
    p.add_argument("--clean", action="store_true",
                   help="only remove everything from the html folder that is not needed to view the html (tex, aux "
                        "and log files, the svg cache, pages of earlier runs, ...), and exit. A later conversion "
                        "then has to recompile all svgs, unless --keep-cache is given")
    p.add_argument("--keep-cache", action="store_true", help="with --clean: keep the svg cache")
    p.add_argument("--dry-run", action="store_true", help="with --clean: only list what would be removed")
    return p.parse_args(argv)


def split_list(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def list_blocks(config):
    sources = load_sources(config)
    blocks = [b for s in sources for b in s.blocks]
    seen = set()
    for b in blocks:
        extra = []
        if b.labels:
            extra.append("labels=" + ",".join(b.labels))
        if b.numbers:
            extra.append("numbers=" + ",".join(f"({n.tag})" if n.tag else "#" for n in b.numbers))
        if b.id in seen:
            extra.append("(shared svg)")
        seen.add(b.id)
        print(f"{b.file}.tex:{b.line}\t{b.kind}\t{b.env}\t{b.id}\t{' '.join(extra)}")
    print(f"{len(blocks)} blocks, {len(collect_jobs(blocks))} distinct svgs", file=sys.stderr)


def main(argv=None):
    """Runs the command line. Exit codes: 0 success, 1 the conversion finished but svgs or the html run failed,
    2 the conversion could not be done (the error is printed), 130 interrupted."""
    args = parse_args(argv)
    try:
        return run(args)
    except Tikz2HtmlError as e:
        print(f"tikz2html: error: {e}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("tikz2html: interrupted", file=sys.stderr, flush=True)
        return 130


def run(args):
    if args.init:
        init_project(args.init, os.path.basename(args.config), overwrite=args.overwrite)
        return 0
    config = Config.from_json(args.config)
    for warning in config.warnings:
        print(f"tikz2html: warning: {warning}", file=sys.stderr, flush=True)
    if args.jobs:
        config.jobs = args.jobs
    if args.list:
        list_blocks(config)
        return 0
    if args.clean:
        removed = clean(config, dry_run=args.dry_run, keep_cache=args.keep_cache)
        if args.dry_run:
            for path in removed:
                print("  " + os.path.relpath(path, config.html_dir))
        return 0
    pipeline = Pipeline(config, log=lambda message: print(message, flush=True))
    results = pipeline.run(only=split_list(args.only), files=split_list(args.files), force=args.force,
                           skip_svgs=args.skip_svgs, skip_html=args.skip_html, draft=args.draft, prune=args.prune)
    return 1 if pipeline.failed else 0
