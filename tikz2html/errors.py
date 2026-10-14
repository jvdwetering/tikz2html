"""Errors that stop the conversion. The command line prints their message without a traceback."""

import shutil


class Tikz2HtmlError(Exception):
    pass


def require_program(command, config_key: str):
    """Raises a Tikz2HtmlError if the program of a command (a string or a list) can't be found."""
    program = command[0] if isinstance(command, (list, tuple)) else command
    if not program or shutil.which(program) is None:
        raise Tikz2HtmlError(
            f"The program '{program}' was not found. tikz2html needs a TeX distribution (TeX Live or MiKTeX) "
            f"with latex, dvisvgm, make4ht and bibtex. Check that it is installed and that its bin folder is on the "
            f"PATH, or set the full path of the program with '{config_key}' in the configuration.")
