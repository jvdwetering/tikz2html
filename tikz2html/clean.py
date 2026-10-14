"""Removing everything from the html folder that is not needed to view the html.

The files that are needed are found by following references, starting at the main html page: links, stylesheets,
scripts, images and svg objects in html pages, url(...) and @import in css files, and links in svgs. All other
files directly in the html folder and in the svg folder are removed: the tex files, aux files, logs, the svg cache
and build folders, and pages or svgs of earlier runs that are no longer linked. Other subfolders of the html
folder are not touched, since tikz2html doesn't create them (they could be backups, for instance).
"""

import fnmatch
import os
import re
from urllib.parse import unquote, urlsplit

from .config import Config
from .errors import Tikz2HtmlError

_ATTR_RE = re.compile(r"""\b(?:href|src|data|xlink:href|poster)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
_CSS_URL_RE = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)'"]*))\s*\)|@import\s+(?:"([^"]*)"|'([^']*)')""", re.I)

CACHE_FOLDER = ".cache"


def references(path: str):
    """The (relative) urls that a file refers to."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".html", ".htm", ".xhtml", ".css", ".svg"):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    regex = _CSS_URL_RE if ext == ".css" else _ATTR_RE
    urls = [next(g for g in m.groups() if g is not None) for m in regex.finditer(text)]
    if ext != ".css":  # Style elements and attributes
        urls += [next(g for g in m.groups() if g is not None) for m in _CSS_URL_RE.finditer(text)]
    return urls


def local_target(url: str, base_dir: str, root: str):
    """The file in root that a url (relative to base_dir) refers to, or None for external urls."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or url.startswith(("#", "//")) or not parts.path:
        return None  # External (http:, data:, mailto:, ...) or a link within the same page
    path = os.path.normpath(os.path.join(base_dir, unquote(parts.path)))
    if os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) != os.path.abspath(root):
        return None  # Outside of the html folder
    return path


def needed_files(html_dir: str, start_files):
    """All files in html_dir reachable from the start files by following references."""
    needed, todo = set(), [os.path.normpath(os.path.join(html_dir, f)) for f in start_files]
    while todo:
        path = todo.pop()
        if path in needed or not os.path.isfile(path):
            continue
        needed.add(path)
        for url in references(path):
            target = local_target(url, os.path.dirname(path), html_dir)
            if target and target not in needed:
                todo.append(target)
    return needed


def check_html_dir(config: Config):
    """Refuses to clean a folder that is not a subfolder of the project (e.g. by a mistake in the config)."""
    html_dir, root = os.path.abspath(config.html_dir), os.path.abspath(config.root)
    if html_dir == root or os.path.commonpath([html_dir, root]) != root:
        raise Tikz2HtmlError(f"Refusing to clean {html_dir}: the html folder must be a subfolder of {root}")
    main = os.path.join(html_dir, config.main_name + ".html")
    if not os.path.isfile(main):
        raise Tikz2HtmlError(f"{main} does not exist; convert the document before cleaning")
    return html_dir, main


def clean(config: Config, dry_run=False, keep_cache=False, log=print):
    """Removes the files in the html folder that are not needed to view the html. Returns the removed files."""
    html_dir, main = check_html_dir(config)
    needed = needed_files(html_dir, [main])
    keep_patterns = list(config.clean_keep)
    svg_dir = os.path.normpath(config.svg_dir)
    candidates = [os.path.join(html_dir, f) for f in os.listdir(html_dir) if os.path.isfile(os.path.join(html_dir, f))]
    if os.path.isdir(svg_dir):
        for folder, dirs, files in os.walk(svg_dir, topdown=True):
            if keep_cache and os.path.normpath(folder) == svg_dir:
                dirs[:] = [d for d in dirs if d != CACHE_FOLDER]
            candidates += [os.path.join(folder, f) for f in files]
    # The copies of source files in subfolders (e.g. html/sections/intro.tex for sections/intro.tex)
    source_dirs = set()
    for name in config.tex_files:
        path = os.path.normpath(os.path.join(html_dir, name + ".tex"))
        if os.path.dirname(path) != html_dir and os.path.isfile(path):
            candidates.append(path)
            source_dirs.add(os.path.dirname(path))
    removed, size = [], 0
    for path in sorted(os.path.normpath(p) for p in candidates):
        rel = os.path.relpath(path, html_dir).replace(os.sep, "/")
        if path in needed or any(fnmatch.fnmatch(rel, p) for p in keep_patterns):
            continue
        removed.append(path)
        size += os.path.getsize(path)
        if not dry_run:
            os.remove(path)
    if not dry_run and os.path.isdir(svg_dir):  # Remove the folders that became empty (.build, _failed, ...)
        for folder, dirs, files in os.walk(svg_dir, topdown=False):
            if os.path.normpath(folder) != svg_dir and not os.listdir(folder):
                os.rmdir(folder)
    if not dry_run:  # And the subfolders of the source copies, when they became empty
        for folder in sorted(source_dirs, key=len, reverse=True):
            while folder != html_dir and os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
                folder = os.path.dirname(folder)
    verb = "Would remove" if dry_run else "Removed"
    log(f"{verb} {len(removed)} files ({size / 1e6:.1f} MB); {len(needed)} files are needed for the html")
    ours = {svg_dir} | {d for d in source_dirs}
    others = sorted(d for d in os.listdir(html_dir) if os.path.isdir(os.path.join(html_dir, d))
                    and os.path.normpath(os.path.join(html_dir, d)) not in ours)
    if others:
        log("Left alone (not made by tikz2html): " + ", ".join(others))
    return removed
