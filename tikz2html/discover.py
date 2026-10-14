r"""Finding out how a LaTeX project is put together: which files are included (\input, \include, \subfile,
\import), which macros and environments draw TikZ pictures, and which other files the document needs.

Used by ``--init`` to write a first configuration, and by the conversion to warn about included files that are
not in the configuration.
"""

import os
import re
from dataclasses import dataclass, field

from .latex_scan import strip_comments, parse_arguments, match_group

# \input{file}, \include{file}, \subfile{file}, \InputIfFileExists{file}, and \input file (the TeX primitive form)
_INCLUDE_RE = re.compile(r"\\(input|include|subfile|InputIfFileExists)\s*(?:\{([^{}]*)\}|\s([^\s{}\\%]+))")
# \import{dir}{file}, \subimport{dir}{file} (and the * versions) from the import package
_IMPORT_RE = re.compile(r"\\(sub)?(?:import|inputfrom|includefrom)\*?\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_DOCUMENTCLASS_RE = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
_USEPACKAGE_RE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
_BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\s*\{([^{}]*)\}")
_BIBSTYLE_RE = re.compile(r"\\bibliographystyle\s*\{([^{}]*)\}")
_ADDBIBRESOURCE_RE = re.compile(r"\\addbibresource\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
_GRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
_EXCLUDECOMMENT_RE = re.compile(r"\\excludecomment\s*\{([^{}]*)\}")
_DEFINITION_RE = re.compile(r"\\(newcommand|renewcommand|providecommand|DeclareRobustCommand|newkeycommand|"
                            r"renewkeycommand|NewDocumentCommand|RenewDocumentCommand|ProvideDocumentCommand|"
                            r"DeclareDocumentCommand|def|gdef|edef|xdef|newenvironment|renewenvironment)"
                            r"(?![A-Za-z])\*?")
# What makes a macro draw TikZ
_TIKZ_RE = re.compile(r"\\(?:tikz|tikzfig|ctikzfig)(?![A-Za-z])|\\begin\s*\{tikzpicture\}")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
BOOK_CLASSES = ("book", "report", "memoir", "scrbook", "scrreprt", "amsbook")


@dataclass
class Project:
    root: str
    main_name: str
    tex_files: list = field(default_factory=list)          # Included .tex files, without extension, in order
    other_inputs: list = field(default_factory=list)       # Other included files (e.g. .tikzstyles), with extension
    missing: list = field(default_factory=list)            # (included name, file it is included from)
    document_class: str = ""
    local_packages: list = field(default_factory=list)     # .sty/.cls/.bst files in the project
    bibliographies: list = field(default_factory=list)     # .bib files
    uses_biblatex: bool = False
    uses_fontspec: bool = False
    uses_tikzit: bool = False
    images: list = field(default_factory=list)
    tikz_macros: dict = field(default_factory=dict)        # name -> argument spec
    tikz_environments: list = field(default_factory=list)
    excluded_environments: list = field(default_factory=list)
    preamble: str = ""                                     # Of the main file, comments stripped

    @property
    def is_book(self):
        return self.document_class in BOOK_CLASSES


def _read(path):
    for encoding in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue


def _resolve(root, base_dir, name, extensions=(".tex",)):
    """The project file that \\input{name} refers to (relative to the project root, or to the including file for
    \\subfile and \\import), or None."""
    name = name.strip().strip('"')
    if not name:
        return None
    candidates = [name] if os.path.splitext(name)[1] else []
    candidates += [name + ext for ext in extensions]
    for folder in (root, base_dir):
        for c in candidates:
            path = os.path.normpath(os.path.join(folder, c))
            if os.path.isfile(path):
                return path
    return None


def _rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def find_includes(text, root, base_dir):
    """The files included by a (comment-free) text: a list of (name as written, resolved path or None)."""
    found = []
    for m in _INCLUDE_RE.finditer(text):
        name = m.group(2) if m.group(2) is not None else m.group(3)
        found.append((name, _resolve(root, base_dir, name)))
    for m in _IMPORT_RE.finditer(text):
        folder = m.group(2) if not m.group(1) else os.path.join(os.path.relpath(base_dir, root), m.group(2))
        name = os.path.join(folder, m.group(3))
        found.append((name, _resolve(root, root, name)))
    return found


def analyse_project(main_file):
    """Analyses the LaTeX project with the given main file."""
    main_file = os.path.abspath(main_file)
    root = os.path.dirname(main_file)
    main_name = os.path.splitext(os.path.basename(main_file))[0]
    project = Project(root=root, main_name=main_name)
    texts = {}  # path -> comment-free text, in the order in which they are included
    todo = [main_file]
    while todo:
        path = todo.pop(0)
        if path in texts:
            continue
        texts[path] = strip_comments(_read(path) or "")
        for name, target in find_includes(texts[path], root, os.path.dirname(path)):
            if target is None:
                project.missing.append((name, _rel(root, path)))
            elif target not in texts and target not in todo:
                todo.append(target)
    for path in texts:
        rel = _rel(root, path)
        if path == main_file:
            continue
        if rel.endswith(".tex"):
            project.tex_files.append(rel[:-4])
        else:
            project.other_inputs.append(rel)

    main_text = texts[main_file]
    m = _DOCUMENTCLASS_RE.search(main_text)
    if m:
        project.document_class = m.group(1).strip()
        cls = _resolve(root, root, project.document_class, (".cls",))
        if cls:
            project.local_packages.append(_rel(root, cls))
    begin = main_text.find("\\begin{document}")
    project.preamble = main_text[:begin] if begin != -1 else ""

    all_text = "\n".join(texts.values())
    for m in _USEPACKAGE_RE.finditer(all_text):
        for package in m.group(1).split(","):
            package = package.strip()
            project.uses_tikzit |= package == "tikzit"
            project.uses_fontspec |= package in ("fontspec", "unicode-math")
            project.uses_biblatex |= package == "biblatex"
            sty = _resolve(root, root, package, (".sty",))
            if sty and _rel(root, sty) not in project.local_packages:
                project.local_packages.append(_rel(root, sty))
    for m in _BIBSTYLE_RE.finditer(all_text):
        bst = _resolve(root, root, m.group(1).strip(), (".bst",))
        if bst and _rel(root, bst) not in project.local_packages:
            project.local_packages.append(_rel(root, bst))
    for regex in (_BIBLIOGRAPHY_RE, _ADDBIBRESOURCE_RE):
        for m in regex.finditer(all_text):
            for name in m.group(1).split(","):
                bib = _resolve(root, root, name.strip(), (".bib",))
                if bib and _rel(root, bib) not in project.bibliographies:
                    project.bibliographies.append(_rel(root, bib))
    for m in _GRAPHICS_RE.finditer(all_text):
        image = _resolve(root, root, m.group(1).strip(), IMAGE_EXTENSIONS)
        if image and _rel(root, image) not in project.images:
            project.images.append(_rel(root, image))
    for m in _EXCLUDECOMMENT_RE.finditer(all_text):
        project.excluded_environments.append(m.group(1).strip())
    project.tikz_macros, project.tikz_environments = find_tikz_definitions(all_text)
    return project


def macro_definitions(text):
    """Yields (kind, name, argument spec, body) for the macro and environment definitions in a text.
    kind is 'macro' or 'environment'."""
    for m in _DEFINITION_RE.finditer(text):
        command = m.group(1)
        pos = m.end()
        try:
            if command in ("def", "gdef", "edef", "xdef"):
                nm = re.compile(r"\s*\\([A-Za-z@]+)").match(text, pos)
                if not nm:
                    continue
                brace = text.find("{", nm.end())
                params = text[nm.end():brace]
                end = match_group(text, brace)
                yield "macro", nm.group(1), "m" * len(re.findall(r"#\d", params)), text[brace + 1:end - 1]
            elif command in ("newenvironment", "renewenvironment"):
                pos, (name,) = parse_arguments(text, pos, "m")
                pos, (n, default) = parse_arguments(text, pos, "oo")
                pos, (begin, end) = parse_arguments(text, pos, "mm")
                yield "environment", name.strip(), "", begin + end
            elif command.endswith("DocumentCommand"):
                pos, (name, spec, body) = parse_arguments(text, pos, "mmm")
                spec = re.sub(r"\s+", "", spec)
                if set(spec) <= set("mos"):
                    yield "macro", name.strip().lstrip("\\"), spec, body
            else:
                pos, (name,) = parse_arguments(text, pos, "m")
                pos, (first, second) = parse_arguments(text, pos, "oo")
                if command.endswith("keycommand"):  # \newkeycommand\name[keys][n]{body}
                    spec = "o" + "m" * int(second or 0)
                else:  # \newcommand\name[n][default]{body}
                    n = int(first or 0)
                    spec = ("o" + "m" * (n - 1)) if second is not None and n > 0 else "m" * n
                pos, (body,) = parse_arguments(text, pos, "m")
                yield "macro", name.strip().lstrip("\\"), spec, body
        except (ValueError, IndexError):
            continue


def find_tikz_definitions(text):
    """The macros and environments defined in text that draw TikZ, directly or through other such macros.
    Returns (dict name -> argument spec, list of environment names)."""
    definitions = list(macro_definitions(text))
    macros, environments = {}, []
    changed = True
    while changed:
        changed = False
        names = [re.escape(n) for n in macros]
        uses = re.compile(r"\\(?:" + "|".join(names) + r")(?![A-Za-z])") if names else None
        for kind, name, spec, body in definitions:
            if (kind == "macro" and name in macros) or (kind == "environment" and name in environments):
                continue
            if _TIKZ_RE.search(body) or (uses and uses.search(body)):
                if kind == "macro":
                    macros[name] = spec
                else:
                    environments.append(name)
                changed = True
    return macros, environments
