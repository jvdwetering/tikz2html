r"""Making the references (\ref, \eqref, \hyperref) inside the svgs into links to the right place in the html.

The svg template wraps references in raw dvisvgm specials, so that the compiled svg contains
``<eqref>label ... </eqref>``. Here these are replaced by ``<a href="../file.html#anchor">``, where the anchor
of a label is read from the .aux file written by tex4ht, and the html file containing that anchor is found by
scanning the generated html files.
"""

import html
import os
import re

from .latex_scan import match_group

_NEWLABEL_RE = re.compile(r"^\\newlabel\{(.*?)\}\{", re.M)
_INPUT_RE = re.compile(r"\\@input\{([^}]*)\}")
_REFLINK_RE = re.compile(r"^\\rEfLiNK\{([^}]*)\}\{(.*)\}$", re.S)
_AUTOREF_RE = re.compile(r"\\csname\s*:autoref\\endcsname\{[^}]*\}")


def parse_aux(path, _seen=None):
    """Reads the labels of a LaTeX .aux file (following \\@input of other aux files).
    Returns a dict label -> (value, anchor) where anchor is None if the aux was not written by tex4ht."""
    _seen = _seen if _seen is not None else set()
    labels = {}
    if path in _seen or not os.path.exists(path):
        return labels
    _seen.add(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    for m in _NEWLABEL_RE.finditer(text):
        label = m.group(1)
        if text[m.end():m.end() + 1] != "{":  # \newlabel{label}{{value}{page}...}
            continue
        try:
            first = text[m.end() + 1:match_group(text, m.end()) - 1]
        except ValueError:
            continue
        value, anchor = first, None
        r = _REFLINK_RE.match(first.strip())
        if r:
            anchor, value = r.group(1), _AUTOREF_RE.sub("", r.group(2))
        labels[label] = (value.strip(), anchor)
    folder = os.path.dirname(path)
    for m in _INPUT_RE.finditer(text):
        labels.update(parse_aux(os.path.join(folder, m.group(1)), _seen))
    return labels


_ID_RE = re.compile(r"""\sid\s*=\s*(?:'([^']*)'|"([^"]*)")""")


def anchor_files(html_dir, files):
    """A dict anchor id -> name of the html file that contains it."""
    anchors = {}
    for name in files:
        with open(os.path.join(html_dir, name), "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        for m in _ID_RE.finditer(text):
            anchors.setdefault(m.group(1) if m.group(1) is not None else m.group(2), name)
    return anchors


def label_targets(aux_labels, anchors):
    """A dict label -> 'file.html#anchor' for all labels whose anchor could be found."""
    targets = {}
    for label, (_, anchor) in aux_labels.items():
        if anchor and anchor in anchors:
            targets[label] = f"{anchors[anchor]}#{anchor}"
    return targets


_RAW_MARKER_RE = re.compile(r"<(eqref|ref|hyperref)>([^<]*)|</(?:eqref|ref|hyperref)>")
# Links of an earlier run of this script (or of the old version of this script)
_DONE_RE = re.compile(r"""<a\b[^>]*\bdata-info=(?:"([^"]*)"|'([^']*)')[^>]*>""")


def link_svg(svg: str, targets: dict, prefix="../", target="_parent"):
    """Replaces the reference markers in an svg by links. Returns (new svg, list of unresolved labels)."""
    missing = []

    def anchor(label):
        label = html.unescape(label.strip())
        attr_label = html.escape(label, quote=True)
        t = f' target="{target}"' if target else ""
        if label in targets:
            return f'<a{t} href="{html.escape(prefix + targets[label], quote=True)}" data-info="{attr_label}">'
        if label:
            missing.append(label)
        return f'<a{t} data-info="{attr_label}">'

    svg = _DONE_RE.sub(lambda m: anchor(m.group(1) if m.group(1) is not None else m.group(2)), svg)

    # Markers can be nested: \eqref uses \ref, and \hyperref can contain a \ref. Browsers don't draw the contents
    # of a link inside a link, so only the outermost marker becomes a link.
    depth = 0

    def replace(m):
        nonlocal depth
        if m.group(0).startswith("</"):
            depth = max(depth - 1, 0)
            return "</a>" if depth == 0 else ""
        depth += 1
        return anchor(m.group(2)) if depth == 1 else ""

    svg = _RAW_MARKER_RE.sub(replace, svg)
    return svg, missing
