"""tikz2html: convert LaTeX documents with many TikZ(iT) figures to html, using make4ht for the text and
latex + dvisvgm for the figures."""

from .config import Config
from .pipeline import Pipeline, load_sources

__all__ = ["Config", "Pipeline", "load_sources"]
