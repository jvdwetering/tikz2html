r"""Scanning LaTeX sources for the parts that contain TikZ(iT) figures.

The scanner works on a token stream (see :func:`tokenize`) instead of plain string matching, so that it
understands escaped characters (``\$``, ``\\[2pt]``), comments, verbatim material, nested braces and nested
environments.

A *block* is a piece of the source that will be rendered as a single SVG image. Blocks are found as follows:

* A math environment (``equation``, ``align*``, ``\[ .. \]``, ``$ .. $``, ...) or a text container
  (``center`` by default) that contains a *trigger* (a TikZ macro like ``\tikzfig`` or an environment like
  ``tikzpicture``) becomes a block as a whole.
* A trigger that is not inside such a container (e.g. a ``\tikzfig{..}`` in running text, or a ``\ctikzfig``)
  becomes a block by itself.

Anything that is not inside a block is left untouched.
"""

import bisect
import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------------------------------------
# Low level helpers
# ---------------------------------------------------------------------------------------------------------

_LINE_COMMENT_RE = re.compile(r"\\verb\*?([^A-Za-z\s*]).*?\1|\\.|%", re.S)
_VERB_RE = r"\\verb\*?([^A-Za-z\s*]).*?\{n}"


def strip_comments(text: str, verbatim_environments=("verbatim", "verbatim*")) -> str:
    """Removes LaTeX comments.

    A line that consists only of a comment is dropped completely (TeX ignores it, including its newline).
    A comment after other content is replaced by a bare ``%``, so that TeX still ignores the line ending.
    ``\\%`` is not a comment, ``\\\\%`` is. Comment signs inside ``\\verb`` and inside verbatim environments
    are left alone.
    """
    out = []
    in_verbatim = None
    for line in text.split("\n"):
        if in_verbatim is not None:
            out.append(line)
            if re.search(r"\\end\s*\{" + re.escape(in_verbatim) + r"\}", line):
                in_verbatim = None
            continue
        cut = None
        for m in _LINE_COMMENT_RE.finditer(line):
            if m.group(0) == "%":
                cut = m.start()
                break
        if cut is not None:
            if line[:cut].strip() == "":
                continue  # The line is fully commented out
            line = line[:cut + 1]
        m = re.search(r"\\begin\s*\{(" + "|".join(re.escape(e) for e in verbatim_environments) + r")\}", line)
        if m and not re.search(r"\\end\s*\{" + re.escape(m.group(1)) + r"\}", line[m.end():]):
            in_verbatim = m.group(1)
        out.append(line)
    return "\n".join(out)


@dataclass
class Token:
    kind: str     # 'cs', 'begin', 'end', 'lbrace', 'rbrace', 'lbracket', 'rbracket', 'math', 'comment', 'verb', 'amp'
    value: str    # control sequence name (without backslash), environment name, or the matched text
    start: int
    end: int
    depth: int = 0  # brace depth at which this token appears (for '{' the depth outside of it)


_TOKEN_RE = re.compile(r"""
      (?P<comment>%[^\n]*)
    | (?P<verb>\\verb\*?(?P<vdelim>[^A-Za-z\s*]).*?(?P=vdelim))
    | \\begin\s*\{(?P<begin>[^{}\\]+)\}
    | \\end\s*\{(?P<end>[^{}\\]+)\}
    | \\(?P<cs>[A-Za-z]+|.)
    | (?P<math>\$\$?)
    | (?P<lbrace>\{)
    | (?P<rbrace>\})
    | (?P<lbracket>\[)
    | (?P<rbracket>\])
""", re.X | re.S)


def tokenize(text: str) -> list:
    """Splits LaTeX source into the tokens the scanner cares about. Plain text is skipped."""
    tokens = []
    depth = 0
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup
        if kind == "vdelim":
            kind = "verb"
        if kind in ("begin", "end", "cs"):
            value = m.group(kind)
        else:
            value = m.group(0)
        if kind == "rbrace":
            depth -= 1
        tokens.append(Token(kind, value, m.start(), m.end(), depth))
        if kind == "lbrace":
            depth += 1
    return tokens


def match_group(text: str, pos: int, open_char="{", close_char="}") -> int:
    """Given that ``text[pos] == open_char``, returns the index just after the matching ``close_char``.
    Escaped characters (``\\{``) are skipped; for brackets, brackets inside braces are skipped."""
    assert text[pos] == open_char
    depth = 0
    brace_depth = 0
    i = pos
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if open_char != "{":
            if c == "{":
                brace_depth += 1
            elif c == "}":
                brace_depth -= 1
        if brace_depth == 0:
            if c == open_char:
                depth += 1
            elif c == close_char:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    raise ValueError(f"Unbalanced {open_char}{close_char} starting at position {pos}: {text[pos:pos + 80]!r}")


def _skip_space(text: str, pos: int) -> int:
    n = len(text)
    while pos < n:
        if text[pos] in " \t\n\r":
            pos += 1
        elif text[pos] == "%":
            j = text.find("\n", pos)
            pos = n if j == -1 else j + 1
        else:
            break
    return pos


def parse_arguments(text: str, pos: int, spec: str):
    """Parses macro arguments starting at ``pos`` according to an xparse-like ``spec``:
    ``m`` is a mandatory argument (a braced group or a single token), ``o`` an optional ``[...]`` argument,
    ``s`` an optional star, ``t`` the body of a \\tikz command ({...} or up to the next ;).
    Returns ``(end_position, [arguments])`` where missing optional arguments are None.
    """
    args = []
    for c in spec:
        p = _skip_space(text, pos)
        if c == "m":
            if p >= len(text):
                raise ValueError(f"Missing argument at position {pos}")
            if text[p] == "{":
                e = match_group(text, p)
                args.append(text[p + 1:e - 1])
            elif text[p] == "\\":
                m = re.compile(r"\\(?:[A-Za-z]+|.)").match(text, p)
                e = m.end()
                args.append(text[p:e])
            else:
                e = p + 1
                args.append(text[p])
            pos = e
        elif c == "o":
            if p < len(text) and text[p] == "[":
                e = match_group(text, p, "[", "]")
                args.append(text[p + 1:e - 1])
                pos = e
            else:
                args.append(None)
        elif c == "s":
            if p < len(text) and text[p] == "*":
                args.append(True)
                pos = p + 1
            else:
                args.append(False)
        elif c == "t":  # The body of \tikz: a braced group, or a single path command up to the next ;
            if p < len(text) and text[p] == "{":
                e = match_group(text, p)
                args.append(text[p + 1:e - 1])
            else:
                e = p
                while e < len(text) and text[e] != ";":
                    if text[e] == "{":
                        e = match_group(text, e)
                    elif text[e] == "\\":
                        e += 2
                    else:
                        e += 1
                if e >= len(text):
                    raise ValueError(f"No ; found after the \\tikz command at position {pos}")
                e += 1
                args.append(text[p:e])
            pos = e
        else:
            raise ValueError(f"Unknown argument specifier {c!r} in {spec!r}")
    return pos, args


def clean_label(label: str) -> str:
    """Turns a LaTeX label (or figure name) into something that can be safely used as a file name."""
    label = re.sub(r"\\[A-Za-z]+", "", label)
    label = re.sub(r"[^A-Za-z0-9._+-]+", "-", label.replace(":", "-"))
    return label.strip("-.") or "diagram"


# ---------------------------------------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------------------------------------

@dataclass
class EquationNumber:
    """One equation number that a display block produces in the original document."""
    label: Optional[str] = None   # The \label attached to it, if any
    tag: Optional[str] = None     # Contents of \tag{..}, if the number is replaced by a tag
    tag_star: bool = False        # \tag*{..}: no parentheses


@dataclass
class Block:
    kind: str                # 'display', 'inline' or 'block' (see ScanConfig.block_kinds)
    env: str                 # environment name, or '\\[', '$', '$$', '\\(' or the name of a bare trigger macro
    start: int               # span of the block in the scanned text
    end: int
    source: str              # the original LaTeX source of the block (comments stripped)
    svg_source: str          # LaTeX to compile into the SVG: \label, \tag, \nonumber removed, env made unnumbered
    inner: str               # the svg source without the delimiters; used to detect duplicate figures
    numbers: list = field(default_factory=list)      # list of EquationNumber (only for display blocks)
    labels: list = field(default_factory=list)       # all \label{..} in the block, in order
    figures: list = field(default_factory=list)      # names of the \tikzfig{..} figures used
    refs: list = field(default_factory=list)         # labels referenced with \ref, \eqref, ... inside the block
    file: str = ""
    line: int = 0
    id: str = ""             # name of the SVG file (without extension); assigned by assign_ids
    dedupe_aliases: dict = field(default_factory=dict, repr=False)

    @property
    def anchor_labels(self):
        """Labels that are not attached to an equation number."""
        numbered = {n.label for n in self.numbers if n.label}
        return [label for label in self.labels if label not in numbered]

    @property
    def content_hash(self) -> str:
        """Blocks with the same hash show the same picture, and share their svg."""
        inner = normalize_source(self.inner)
        for macro, alias in self.dedupe_aliases.items():
            inner = re.sub(r"\\" + re.escape(macro) + r"(?![A-Za-z])", lambda m: "\\" + alias, inner)
        return hashlib.sha1(inner.encode("utf-8")).hexdigest()


def normalize_source(source: str) -> str:
    """Normalizes whitespace, so that two blocks that differ only in formatting are seen as the same."""
    source = re.sub(r"%[^\n]*", "", source)
    return re.sub(r"\s+", " ", source).strip()


# ---------------------------------------------------------------------------------------------------------
# Scanner configuration
# ---------------------------------------------------------------------------------------------------------

DEFAULT_MATH_ENVIRONMENTS = {
    # name: (kind, numbering) where numbering is None, 'single' or 'rows'
    "equation": ("display", "single"),
    "equation*": ("display", None),
    "align": ("display", "rows"),
    "align*": ("display", None),
    "alignat": ("display", "rows"),
    "alignat*": ("display", None),
    "flalign": ("display", "rows"),
    "flalign*": ("display", None),
    "gather": ("display", "rows"),
    "gather*": ("display", None),
    "multline": ("display", "single"),
    "multline*": ("display", None),
    "eqnarray": ("display", "rows"),
    "eqnarray*": ("display", None),
    "displaymath": ("display", None),
    "math": ("inline", None),
    "center": ("block", None),
}

DEFAULT_DEFINITION_MACROS = {
    # name: number of arguments to skip (a control sequence directly following counts as one argument).
    # 'def' means: a control sequence, a parameter text, and a braced body.
    "newcommand": 2, "renewcommand": 2, "providecommand": 2, "DeclareRobustCommand": 2,
    "newenvironment": 3, "renewenvironment": 3,
    "NewDocumentCommand": 3, "RenewDocumentCommand": 3, "ProvideDocumentCommand": 3,
    "DeclareDocumentCommand": 3, "NewDocumentEnvironment": 4, "RenewDocumentEnvironment": 4,
    "newkeycommand": 2, "renewkeycommand": 2,
    "def": "def", "gdef": "def", "edef": "def", "xdef": "def",
}


@dataclass
class ScanConfig:
    # Macros that produce TikZ pictures, with their argument specification (see parse_arguments).
    tikz_macros: dict = field(default_factory=lambda: {"tikzfig": "m", "ctikzfig": "m", "tikz": "ot"})
    # Environments that produce TikZ pictures (or otherwise need to be rendered as an SVG)
    tikz_environments: list = field(default_factory=lambda: ["tikzpicture"])
    # The environments that are turned into an SVG as a whole when they contain a trigger.
    math_environments: dict = field(default_factory=lambda: dict(DEFAULT_MATH_ENVIRONMENTS))
    # Kind of a trigger that is not inside one of the math_environments. Default: 'inline'.
    standalone_kinds: dict = field(default_factory=lambda: {"ctikzfig": "block"})
    # Environments whose content is removed completely (e.g. 'comment', or 'solution' when solutions are hidden)
    skip_environments: list = field(default_factory=lambda: ["comment"])
    # Environments whose content is not scanned at all
    verbatim_environments: list = field(default_factory=lambda: ["verbatim", "verbatim*", "lstlisting", "minted"])
    # Macros defining other macros; their arguments are not scanned.
    definition_macros: dict = field(default_factory=lambda: dict(DEFAULT_DEFINITION_MACROS))
    # Macros referencing labels, which are made into hyperlinks in the SVGs
    ref_macros: list = field(default_factory=lambda: ["ref", "eqref", "hyperref", "autoref", "cref", "Cref", "pageref"])
    # Macros whose (first mandatory) argument is a figure name
    figure_macros: list = field(default_factory=lambda: ["tikzfig", "ctikzfig"])
    # Macros that give the same picture, so that blocks using them can share an svg
    dedupe_aliases: dict = field(default_factory=lambda: {"ctikzfig": "tikzfig"})


# ---------------------------------------------------------------------------------------------------------
# The scanner
# ---------------------------------------------------------------------------------------------------------

class LatexScanError(ValueError):
    pass


class _Scanner:
    def __init__(self, text: str, config: ScanConfig, filename=""):
        self.text = text
        self.config = config
        self.filename = filename
        self.tokens = tokenize(text)
        self.starts = [t.start for t in self.tokens]

    def line_of(self, pos):
        return self.text.count("\n", 0, pos) + 1

    def error(self, msg, pos):
        return LatexScanError(f"{self.filename}:{self.line_of(pos)}: {msg}")

    def index_at(self, pos):
        """Index of the first token starting at or after pos."""
        return bisect.bisect_left(self.starts, pos)

    # --- matching delimiters ---

    def find_env_end(self, i):
        """Token index of the \\end matching the \\begin at index i."""
        name = self.tokens[i].value
        depth = 0
        for j in range(i, len(self.tokens)):
            t = self.tokens[j]
            if t.kind == "begin" and t.value == name:
                depth += 1
            elif t.kind == "end" and t.value == name:
                depth -= 1
                if depth == 0:
                    return j
        raise self.error(f"\\begin{{{name}}} is never closed", self.tokens[i].start)

    def find_math_end(self, i):
        """Token index of the closing delimiter for the math opener at index i."""
        t = self.tokens[i]
        if t.kind == "math":
            for j in range(i + 1, len(self.tokens)):
                u = self.tokens[j]
                if u.kind == "math" and u.depth == t.depth:
                    if u.value == t.value:
                        return j
                    if t.value == "$$":
                        continue
                    # A '$$' while looking for '$' closes the inline math and opens a new one: not supported
                    raise self.error("Found '$$' while looking for the end of '$'", u.start)
                if u.kind == "rbrace" and u.depth < t.depth:
                    break
            raise self.error(f"Math opened with {t.value} is never closed", t.start)
        closer = {"[": "]", "(": ")"}[t.value]
        for j in range(i + 1, len(self.tokens)):
            u = self.tokens[j]
            if u.kind == "cs" and u.value == closer:
                return j
        raise self.error(f"\\{t.value} is never closed", t.start)

    # --- triggers ---

    def is_trigger(self, t: Token):
        return (t.kind == "cs" and t.value in self.config.tikz_macros) or \
               (t.kind == "begin" and t.value in self.config.tikz_environments)

    def contains_trigger(self, i, j):
        return any(self.is_trigger(self.tokens[k]) for k in range(i, j))

    def skip_definition(self, i):
        """Returns the text position after a macro definition starting at token i."""
        t = self.tokens[i]
        spec = self.config.definition_macros[t.value]
        pos = t.end
        if spec == "def":
            pos, _ = parse_arguments(self.text, pos, "m")  # the control sequence being defined
            j = self.text.find("{", pos)
            if j == -1:
                raise self.error(f"\\{t.value} without body", t.start)
            return match_group(self.text, j)
        remaining = spec
        while remaining:
            p = _skip_space(self.text, pos)
            if p < len(self.text) and self.text[p] == "*":
                pos = p + 1
            elif p < len(self.text) and self.text[p] == "[":
                pos = match_group(self.text, p, "[", "]")
            else:
                pos, _ = parse_arguments(self.text, pos, "m")
                remaining -= 1
        return pos

    # --- main loop ---

    def scan(self):
        """Returns (blocks, skipped) where skipped is a list of (start, end) spans to remove from the text."""
        blocks, skipped = [], []
        tokens = self.tokens
        cfg = self.config
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t.kind == "begin" and (t.value in cfg.skip_environments or t.value in cfg.verbatim_environments):
                j = self.find_env_end(i)
                if t.value in cfg.skip_environments:
                    skipped.append((t.start, tokens[j].end))
                i = j + 1
                continue
            if t.kind == "cs" and t.value in cfg.definition_macros:
                i = self.index_at(self.skip_definition(i))
                continue
            opener = None
            if t.kind == "begin" and t.value in cfg.math_environments:
                opener = (self.find_env_end(i), t.value, cfg.math_environments[t.value][0])
            elif t.kind == "math":
                opener = (self.find_math_end(i), t.value, "display" if t.value == "$$" else "inline")
            elif t.kind == "cs" and t.value in ("[", "("):
                opener = (self.find_math_end(i), "\\" + t.value, "display" if t.value == "[" else "inline")
            if opener is not None:
                j, env, kind = opener
                if self.contains_trigger(i + 1, j):
                    blocks.append(self.make_block(kind, env, t.start, tokens[j].end, t.end, tokens[j].start))
                i = j + 1
                continue
            if self.is_trigger(t):
                if t.kind == "begin":
                    j = self.find_env_end(i)
                    end = tokens[j].end
                    name = t.value
                else:
                    try:
                        end, _ = parse_arguments(self.text, t.end, cfg.tikz_macros[t.value])
                    except ValueError as e:
                        raise self.error(str(e), t.start)
                    name = t.value
                kind = cfg.standalone_kinds.get(name, "inline")
                blocks.append(self.make_block(kind, name, t.start, end, t.start, end))
                i = self.index_at(end)
                continue
            i += 1
        return blocks, skipped

    # --- constructing a block ---

    def make_block(self, kind, env, start, end, inner_start, inner_end):
        source = self.text[start:end]
        inner = self.text[inner_start:inner_end]
        numbering = None
        if env in self.config.math_environments:
            numbering = self.config.math_environments[env][1]
        labels, numbers, inner_clean = analyse_equation(inner, numbering)
        if kind in ("display", "inline") and inner_start != start:
            # Blank lines are not allowed in math, but can appear after removing a \label on its own line
            inner_clean = re.sub(r"\n[ \t]*(?=\n)", "", inner_clean)
        if inner_start == start:  # Bare trigger: no delimiters
            svg_source = inner_clean
        else:
            open_delim = self.text[start:inner_start]
            close_delim = self.text[inner_end:end]
            if numbering is not None:  # Make the environment unnumbered: the numbers are added in the html
                star = env + "*" if env + "*" in self.config.math_environments else env
                open_delim = re.sub(r"\\begin\s*\{" + re.escape(env) + r"\}", lambda m: "\\begin{" + star + "}", open_delim, count=1)
                close_delim = re.sub(r"\\end\s*\{" + re.escape(env) + r"\}", lambda m: "\\end{" + star + "}", close_delim, count=1)
            # Environment arguments (like the column count of alignat) stay with the opening delimiter
            if env in self.config.math_environments and env.startswith("alignat"):
                p, _ = parse_arguments(inner_clean, 0, "m")
                open_delim, inner_clean = open_delim + inner_clean[:p], inner_clean[p:]
            svg_source = open_delim + inner_clean + close_delim
        figures = [arg for name, arg in iter_macro_args(inner, self.config.figure_macros)]
        refs = [arg for name, arg in iter_macro_args(inner, self.config.ref_macros, optional_first=("hyperref",))]
        return Block(kind=kind, env=env, start=start, end=end, source=source, svg_source=svg_source,
                     inner=inner_clean.strip(), numbers=numbers, labels=labels, figures=figures, refs=refs,
                     file=self.filename, line=self.line_of(start), dedupe_aliases=self.config.dedupe_aliases)


def iter_macro_args(text, macros, optional_first=()):
    """Yields (macro, first argument) for all occurrences of the given macros in text.
    For the macros in optional_first, the first optional argument is used instead (like \\hyperref[label]{text})."""
    if not macros:
        return
    pattern = re.compile(r"\\(" + "|".join(re.escape(m) for m in macros) + r")(?![A-Za-z])\*?")
    for m in pattern.finditer(text):
        name = m.group(1)
        try:
            if name in optional_first:
                _, args = parse_arguments(text, m.end(), "o")
            else:
                _, args = parse_arguments(text, m.end(), "m")
        except ValueError:
            continue
        if args[0] is not None:
            yield name, args[0].strip()


_EQN_META_RE = re.compile(r"\\(label|tag|nonumber|notag)(?![A-Za-z])(\*?)")


def split_rows(text: str):
    """Splits the body of an align-like environment into rows at top-level ``\\\\``
    (not inside braces or nested environments)."""
    rows, last = [], 0
    depth = 0
    env_depth = 0
    for t in tokenize(text):
        if t.kind == "begin":
            env_depth += 1
        elif t.kind == "end":
            env_depth -= 1
        elif t.kind == "cs" and t.value == "\\" and t.depth == 0 and env_depth == 0:
            rows.append(text[last:t.start])
            last = t.end
    rows.append(text[last:])
    return rows


def analyse_equation(inner: str, numbering):
    """Extracts \\label, \\tag, \\nonumber and \\notag from the body of an equation.
    Returns (labels, numbers, cleaned body)."""
    labels = []
    numbers = []
    rows = split_rows(inner) if numbering == "rows" else [inner]
    for row in rows:
        row_labels, tag, tag_star, nonumber = [], None, False, False
        for m in _EQN_META_RE.finditer(row):
            if m.group(1) == "label":
                _, args = parse_arguments(row, m.end(), "m")
                row_labels.append(args[0].strip())
            elif m.group(1) == "tag":
                _, args = parse_arguments(row, m.end(), "m")
                tag, tag_star = args[0].strip(), bool(m.group(2))
            else:
                nonumber = True
        labels.extend(row_labels)
        if tag is not None:
            numbers.append(EquationNumber(row_labels[0] if row_labels else None, tag, tag_star))
        elif numbering is not None and not nonumber:
            numbers.append(EquationNumber(row_labels[0] if row_labels else None))
    return labels, numbers, remove_equation_meta(inner)


def remove_equation_meta(text: str) -> str:
    """Removes \\label{..}, \\tag{..}, \\tag*{..}, \\nonumber and \\notag."""
    out, pos = [], 0
    for m in _EQN_META_RE.finditer(text):
        if m.start() < pos:
            continue
        out.append(text[pos:m.start()])
        if m.group(1) in ("label", "tag"):
            pos, _ = parse_arguments(text, m.end(), "m")
        else:
            pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def scan(text: str, config: ScanConfig = None, filename=""):
    """Scans comment-free LaTeX source for blocks containing TikZ. Returns (blocks, skipped_spans)."""
    return _Scanner(text, config or ScanConfig(), filename).scan()


# ---------------------------------------------------------------------------------------------------------
# Naming blocks
# ---------------------------------------------------------------------------------------------------------

def base_name(block: Block, config: ScanConfig = None) -> str:
    """The name a block would get: its first label, otherwise the first figure, otherwise the first trigger."""
    config = config or ScanConfig()
    if block.labels:
        return clean_label(block.labels[0])
    if block.figures:
        return clean_label(block.figures[0])
    for name, arg in iter_macro_args(block.inner, list(config.tikz_macros)):
        if len(arg) > 1 and clean_label(arg) != "diagram":  # e.g. \Zscalar{\alpha} gives no useful name
            return clean_label(arg)
    m = re.search(r"\\(" + "|".join(re.escape(m) for m in config.tikz_macros) + r")(?![A-Za-z])", block.source)
    if m:
        return clean_label(m.group(1))
    return clean_label(block.env)


def assign_ids(blocks, config: ScanConfig = None):
    """Gives every block an id, which is the name of its SVG file.

    Blocks with the same figure content share their SVG (so the same figure is only converted once).
    Different content with the same name gets a numbered suffix (name, name-1, name-2, ...).
    """
    by_content = {}   # content hash -> id
    used = set()
    for block in blocks:
        h = block.content_hash
        if h in by_content:
            block.id = by_content[h]
            continue
        name = base_name(block, config)
        candidate, j = name, 0
        while candidate.lower() in used:  # lower(): file names are case-insensitive on Windows and macOS
            j += 1
            candidate = f"{name}-{j}"
        used.add(candidate.lower())
        block.id = by_content[h] = candidate
    return blocks
