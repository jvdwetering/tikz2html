r"""Tests of the LaTeX scanner: all the ways a TikZ figure can appear in a document, in all the different
equation environments, and the LaTeX constructions that should *not* be mistaken for math or for figures.

Run with ``python -m unittest discover tests`` (or ``pytest tests``) from the project folder.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tikz2html.latex_scan import (ScanConfig, scan, strip_comments, tokenize, parse_arguments, match_group,
                                  clean_label, assign_ids, split_rows, LatexScanError)

CONFIG = ScanConfig(
    tikz_macros={"tikzfig": "m", "ctikzfig": "m", "tikz": "om", "namedeq": "m", "state": "om",
                 "emptydiag": "", "eulerboxes": "mmm"},
    tikz_environments=["tikzpicture", "tabu"],
    standalone_kinds={"ctikzfig": "block", "tabu": "block"},
    skip_environments=["comment", "solution"],
)


def blocks_of(text, config=CONFIG):
    blocks, _ = scan(strip_comments(text), config)
    return blocks


def one_block(test, text, config=CONFIG):
    blocks = blocks_of(text, config)
    test.assertEqual(len(blocks), 1, f"expected exactly one block in {text!r}, got {blocks}")
    return blocks[0]


class TestCommentStripping(unittest.TestCase):
    def test_full_line_comment_is_dropped(self):
        self.assertEqual(strip_comments("a\n% comment\nb"), "a\nb")
        self.assertEqual(strip_comments("a\n   % indented comment\nb"), "a\nb")

    def test_trailing_comment_keeps_percent(self):
        # The % is kept, so that TeX still ignores the line ending
        self.assertEqual(strip_comments("a % comment\nb"), "a %\nb")

    def test_escaped_percent_is_not_a_comment(self):
        self.assertEqual(strip_comments(r"50\% of the time"), r"50\% of the time")

    def test_escaped_backslash_before_percent_is_a_comment(self):
        self.assertEqual(strip_comments(r"line break \\% comment"), r"line break \\%")

    def test_commented_line_ending_in_double_backslash(self):
        # This used to break the old scanner (the comment check looked at the last character of the line)
        self.assertEqual(strip_comments("% a & b \\\\\nc"), "c")

    def test_commented_out_tikzfig_is_ignored(self):
        self.assertEqual(blocks_of("text\n% \\tikzfig{a}\n%\\[ \\tikzfig{b} \\]\nmore"), [])

    def test_percent_in_verb(self):
        self.assertEqual(strip_comments(r"\verb|50%| done"), r"\verb|50%| done")

    def test_verbatim_environment_untouched(self):
        text = "\\begin{verbatim}\n% not a comment\n\\end{verbatim}\n% comment"
        self.assertEqual(strip_comments(text), "\\begin{verbatim}\n% not a comment\n\\end{verbatim}")


class TestTokenizer(unittest.TestCase):
    def kinds(self, text):
        return [(t.kind, t.value) for t in tokenize(text)]

    def test_line_break_with_spacing_is_not_display_math(self):
        # \\[2pt] is a line break with extra space, not \[
        self.assertEqual(self.kinds(r"a \\[2pt] b"), [("cs", "\\"), ("lbracket", "["), ("rbracket", "]")])

    def test_escaped_dollar(self):
        self.assertEqual(self.kinds(r"costs \$5"), [("cs", "$")])

    def test_double_dollar(self):
        self.assertEqual(self.kinds("$$x$$"), [("math", "$$"), ("math", "$$")])

    def test_begin_end(self):
        self.assertEqual(self.kinds(r"\begin{align*}x\end{align*}"), [("begin", "align*"), ("end", "align*")])

    def test_brace_depth(self):
        toks = tokenize("{a{b}}")
        self.assertEqual([t.depth for t in toks], [0, 1, 1, 0])


class TestArguments(unittest.TestCase):
    def test_mandatory(self):
        self.assertEqual(parse_arguments(r"{a{b}c} rest", 0, "m"), (7, ["a{b}c"]))

    def test_single_token_argument(self):
        self.assertEqual(parse_arguments(r"\alpha rest", 0, "m")[1], ["\\alpha"])
        self.assertEqual(parse_arguments(r"x rest", 0, "m")[1], ["x"])

    def test_optional(self):
        self.assertEqual(parse_arguments(r"[type=X]{a}", 0, "om")[1], ["type=X", "a"])
        self.assertEqual(parse_arguments(r"{a}", 0, "om")[1], [None, "a"])

    def test_optional_with_brackets_in_braces(self):
        self.assertEqual(parse_arguments(r"[a={[x]}]{b}", 0, "om")[1], ["a={[x]}", "b"])

    def test_escaped_braces(self):
        self.assertEqual(match_group(r"{a\}b}", 0), 6)

    def test_unbalanced(self):
        with self.assertRaises(ValueError):
            match_group("{a{b}", 0)


class TestEquationEnvironments(unittest.TestCase):
    """A TikZ figure inside every kind of math environment makes the environment one display block."""

    def check_display(self, env, numbered):
        b = one_block(self, f"Text\n\\begin{{{env}}}\n\\tikzfig{{fig}} = \\tikzfig{{fig2}}\n\\end{{{env}}}\nmore")
        self.assertEqual(b.kind, "display")
        self.assertEqual(b.env, env)
        self.assertEqual(b.figures, ["fig", "fig2"])
        self.assertEqual(len(b.numbers), 1 if numbered else 0)
        # The svg is always compiled unnumbered: numbers are added in the html
        unnumbered = env if env.endswith("*") or env == "displaymath" else env + "*"
        self.assertTrue(b.svg_source.startswith(f"\\begin{{{unnumbered}}}"), b.svg_source)
        self.assertTrue(b.svg_source.endswith(f"\\end{{{unnumbered}}}"), b.svg_source)
        return b

    def test_equation(self):
        self.check_display("equation", True)

    def test_equation_star(self):
        self.check_display("equation*", False)

    def test_align(self):
        self.check_display("align", True)

    def test_align_star(self):
        self.check_display("align*", False)

    def test_gather(self):
        self.check_display("gather", True)

    def test_gather_star(self):
        self.check_display("gather*", False)

    def test_multline(self):
        self.check_display("multline", True)

    def test_flalign(self):
        self.check_display("flalign", True)

    def test_eqnarray(self):
        self.check_display("eqnarray", True)

    def test_displaymath(self):
        self.check_display("displaymath", False)

    def test_alignat_keeps_its_argument(self):
        b = one_block(self, "\\begin{alignat}{2}\n\\tikzfig{a} &= x & y\n\\end{alignat}")
        self.assertTrue(b.svg_source.startswith("\\begin{alignat*}{2}"), b.svg_source)
        self.assertEqual(len(b.numbers), 1)

    def test_bracket_display(self):
        b = one_block(self, "a\n\\[\n  \\tikzfig{fig}\n\\]\nb")
        self.assertEqual((b.kind, b.env, b.numbers), ("display", "\\[", []))
        self.assertEqual(b.svg_source, "\\[\n  \\tikzfig{fig}\n\\]")

    def test_double_dollar_display(self):
        b = one_block(self, "a $$\\tikzfig{fig}$$ b")
        self.assertEqual((b.kind, b.env), ("display", "$$"))

    def test_inline_dollar(self):
        b = one_block(self, "the state $\\tikzfig{fig}$ is")
        self.assertEqual((b.kind, b.env, b.svg_source), ("inline", "$", "$\\tikzfig{fig}$"))

    def test_inline_paren(self):
        b = one_block(self, "the state \\(\\tikzfig{fig}\\) is")
        self.assertEqual((b.kind, b.env), ("inline", "\\("))

    def test_math_environment(self):
        b = one_block(self, "the state \\begin{math}\\tikzfig{fig}\\end{math} is")
        self.assertEqual(b.kind, "inline")

    def test_math_without_tikz_is_not_a_block(self):
        self.assertEqual(blocks_of("$x$ and \\[ y \\] and \\begin{align} a &= b \\end{align}"), [])

    def test_block_span_is_exact(self):
        text = "before \\[\\tikzfig{a}\\] after"
        b = one_block(self, text)
        self.assertEqual(text[b.start:b.end], "\\[\\tikzfig{a}\\]")

    def test_several_blocks(self):
        blocks = blocks_of("$\\tikzfig{a}$ text \\[\\tikzfig{b}\\] $x$ \\begin{equation}\\tikzfig{c}\\end{equation}")
        self.assertEqual([b.figures for b in blocks], [["a"], ["b"], ["c"]])

    def test_nested_inline_math_in_text(self):
        # The $ inside \text{..} does not end the inline math
        b = one_block(self, "$\\tikzfig{a} \\text{ for all $x$} $ rest")
        self.assertTrue(b.source.endswith("} $"))

    def test_nested_environments(self):
        b = one_block(self, "\\begin{equation}\\begin{pmatrix} \\tikzfig{a} \\\\ b \\end{pmatrix}\\end{equation}")
        self.assertEqual(b.env, "equation")

    def test_left_right_braces(self):
        b = one_block(self, "\\[ \\left\\{ \\tikzfig{a} \\right\\} \\]")
        self.assertIn("\\left\\{", b.svg_source)

    def test_line_break_with_spacing_in_align(self):
        b = one_block(self, "\\begin{align*}\\tikzfig{a} \\\\[5mm] \\tikzfig{b}\\end{align*}")
        self.assertEqual(b.figures, ["a", "b"])

    def test_line_break_with_spacing_in_text_is_not_display_math(self):
        # In the cheatsheets, \\[0cm] in tables was mistaken for display math by the old scanner
        text = "\\begin{tabular}{cc} a & b \\\\[0cm] \\hline c & d \\end{tabular} \\[\\tikzfig{x}\\]"
        b = one_block(self, text)
        self.assertEqual(b.source, "\\[\\tikzfig{x}\\]")

    def test_escaped_dollar_is_not_math(self):
        b = one_block(self, "costs \\$5, and $\\tikzfig{a}$")
        self.assertEqual(b.source, "$\\tikzfig{a}$")

    def test_unclosed_environment_reports_line(self):
        with self.assertRaisesRegex(LatexScanError, "f.tex:2"):
            scan("a\n\\begin{equation}\\tikzfig{a}\n", CONFIG, filename="f.tex")

    def test_unclosed_inline_math(self):
        with self.assertRaises(LatexScanError):
            scan("a $\\tikzfig{a} b", CONFIG)


class TestLabelsAndNumbers(unittest.TestCase):
    def test_label_in_equation(self):
        b = one_block(self, "\\begin{equation}\\label{eq:a}\\tikzfig{a}\\end{equation}")
        self.assertEqual(b.labels, ["eq:a"])
        self.assertEqual([(n.label, n.tag) for n in b.numbers], [("eq:a", None)])
        self.assertNotIn("\\label", b.svg_source)

    def test_label_on_own_line_leaves_no_blank_line(self):
        # A blank line in an align is a paragraph break, which is an error
        b = one_block(self, "\\begin{align}\n\\label{eq:a}\n\\tikzfig{a} &= b\n\\end{align}")
        self.assertNotRegex(b.svg_source, r"\n\s*\n")

    def test_tikzfig_at_end_of_align_leaves_no_blank_line(self):
        # The old version expanded \tikzfig with an extra newline, which broke such aligns
        b = one_block(self, "\\begin{align*}\nx &= \\tikzfig{a}\n\\end{align*}")
        self.assertNotRegex(b.svg_source, r"\n\s*\n")

    def test_align_with_two_labels(self):
        b = one_block(self, "\\begin{align}\n\\label{eq:a}\n\\tikzfig{a} &= x \\\\\n\\label{eq:b}\n\\tikzfig{b} &= y\n\\end{align}")
        self.assertEqual(b.labels, ["eq:a", "eq:b"])
        self.assertEqual([n.label for n in b.numbers], ["eq:a", "eq:b"])

    def test_align_rows_without_labels_are_numbered(self):
        b = one_block(self, "\\begin{align}\\tikzfig{a} &= x \\\\ &= y \\\\ &= z\\end{align}")
        self.assertEqual(len(b.numbers), 3)

    def test_nonumber_and_notag(self):
        b = one_block(self, "\\begin{align}\\tikzfig{a} &= x \\nonumber\\\\ &= y \\notag \\\\ &= z\\label{eq:z}\\end{align}")
        self.assertEqual([n.label for n in b.numbers], ["eq:z"])
        self.assertNotIn("nonumber", b.svg_source)
        self.assertNotIn("notag", b.svg_source)

    def test_rows_of_nested_matrix_are_not_split(self):
        self.assertEqual(len(split_rows("\\begin{pmatrix}a\\\\b\\end{pmatrix} \\\\ c")), 2)
        self.assertEqual(len(split_rows("\\text{a \\\\ b} \\\\ c")), 2)

    def test_tag(self):
        b = one_block(self, "\\begin{equation}\\label{eq:gf}\\tikzfig{a}\\tag{\\gflabel}\\end{equation}")
        self.assertEqual([(n.label, n.tag, n.tag_star) for n in b.numbers], [("eq:gf", "\\gflabel", False)])
        self.assertNotIn("\\tag", b.svg_source)

    def test_tag_star(self):
        b = one_block(self, "\\begin{equation}\\tikzfig{a}\\tag*{S4}\\end{equation}")
        self.assertEqual([(n.tag, n.tag_star) for n in b.numbers], [("S4", True)])

    def test_tag_in_unnumbered_environment(self):
        b = one_block(self, "\\[\\tikzfig{a}\\tag{x}\\]")
        self.assertEqual([n.tag for n in b.numbers], ["x"])

    def test_label_in_center_is_an_anchor(self):
        b = one_block(self, "\\begin{center}\\tikzfig{a}\\label{fig:a}\\end{center}")
        self.assertEqual(b.numbers, [])
        self.assertEqual(b.anchor_labels, ["fig:a"])

    def test_references_are_recorded(self):
        b = one_block(self, "\\[\\tikzfig{a} \\namedeq{\\eqref{eq:x}} \\tikzfig{b} \\overset{\\ref{thm}}{=} \\hyperref[fig:r]{(r)}\\]")
        self.assertEqual(b.refs, ["eq:x", "thm", "fig:r"])


class TestWaysToIncludeTikz(unittest.TestCase):
    def test_bare_tikzfig_in_text(self):
        b = one_block(self, "As shown in \\tikzfig{fig} we see")
        self.assertEqual((b.kind, b.env, b.source), ("inline", "tikzfig", "\\tikzfig{fig}"))

    def test_bare_tikzfig_in_table_cell(self):
        blocks = blocks_of("\\begin{tabular}{cc} Spider & \\tikzfig{spider} \\\\ Hadamard & \\tikzfig{had} \\end{tabular}")
        self.assertEqual([(b.kind, b.figures) for b in blocks], [("inline", ["spider"]), ("inline", ["had"])])

    def test_bare_tikzfig_in_figure(self):
        b = one_block(self, "\\begin{figure}\\centering\\tikzfig{rules}\\caption{Rules}\\label{fig:rules}\\end{figure}")
        self.assertEqual((b.kind, b.source), ("inline", "\\tikzfig{rules}"))

    def test_adjacent_tikzfigs(self):
        # The old scanner skipped the second one
        blocks = blocks_of("\\tikzfig{a}\\tikzfig{b}")
        self.assertEqual([b.figures for b in blocks], [["a"], ["b"]])

    def test_ctikzfig(self):
        b = one_block(self, "text\n\\ctikzfig{fig}\nmore")
        self.assertEqual((b.kind, b.env, b.source), ("block", "ctikzfig", "\\ctikzfig{fig}"))

    def test_center_environment(self):
        b = one_block(self, "\\begin{center}\n\\tikzfig{fig}\n\\end{center}")
        self.assertEqual((b.kind, b.env), ("block", "center"))
        self.assertEqual(b.svg_source, "\\begin{center}\n\\tikzfig{fig}\n\\end{center}")

    def test_center_without_tikz_is_not_a_block(self):
        self.assertEqual(blocks_of("\\begin{center}\\url{x}\\end{center}"), [])

    def test_tikzpicture_environment(self):
        b = one_block(self, "a \\begin{tikzpicture}\\draw (0,0) -- (1,1);\\end{tikzpicture} b")
        self.assertEqual((b.kind, b.env), ("inline", "tikzpicture"))
        self.assertTrue(b.source.endswith("\\end{tikzpicture}"))

    def test_tikzpicture_in_equation(self):
        b = one_block(self, "\\begin{equation}\\begin{tikzpicture}\\node{};\\end{tikzpicture}\\end{equation}")
        self.assertEqual(b.env, "equation")

    def test_tikz_macro_with_optional_argument(self):
        b = one_block(self, "a \\tikz[baseline]{\\node {x};} b")
        self.assertEqual(b.source, "\\tikz[baseline]{\\node {x};}")

    def test_trigger_environment_configured_as_block(self):
        b = one_block(self, "\\begin{tabu}{c} \\tikzfig{a} \\end{tabu}")
        self.assertEqual((b.kind, b.env), ("block", "tabu"))

    def test_macro_without_arguments(self):
        b = one_block(self, "the empty diagram \\emptydiag{} is")
        self.assertEqual(b.source, "\\emptydiag")

    def test_macro_without_arguments_in_math(self):
        b = one_block(self, "$\\emptydiag$")
        self.assertEqual(b.env, "$")

    def test_macro_with_optional_argument(self):
        b = one_block(self, "a \\state[type=X]{\\alpha} b")
        self.assertEqual(b.source, "\\state[type=X]{\\alpha}")

    def test_macro_with_three_arguments(self):
        b = one_block(self, "a \\eulerboxes{a}{b}{c} b")
        self.assertEqual(b.source, "\\eulerboxes{a}{b}{c}")

    def test_macro_name_must_match_exactly(self):
        # \statevector is not \state
        self.assertEqual(blocks_of("$\\statevector{x}$ and \\tikzfigure"), [])

    def test_namedeq_in_display(self):
        b = one_block(self, "\\[\\tikzfig{a} \\namedeq{\\eqref{eq:b}} \\tikzfig{c}\\]")
        self.assertEqual(b.figures, ["a", "c"])

    def test_inline_figure_in_caption(self):
        b = one_block(self, "\\begin{figure}\\caption{The state $\\tikzfig{s}$.}\\end{figure}")
        self.assertEqual((b.kind, b.source), ("inline", "$\\tikzfig{s}$"))

    def test_figure_in_item(self):
        blocks = blocks_of("\\begin{itemize}\\item a: $\\tikzfig{a}$\n\\item b: \\[\\tikzfig{b}\\]\\end{itemize}")
        self.assertEqual([b.kind for b in blocks], ["inline", "display"])

    def test_figure_in_theorem_and_proof(self):
        blocks = blocks_of("\\begin{theorem}\\[\\tikzfig{a}\\]\\end{theorem}\\begin{proof}\\ctikzfig{b}\\end{proof}")
        self.assertEqual([b.figures for b in blocks], [["a"], ["b"]])


class TestThingsToSkip(unittest.TestCase):
    def test_skipped_environment(self):
        text = "a \\begin{solution} $\\tikzfig{a}$ \\end{solution} b"
        blocks, skipped = scan(text, CONFIG)
        self.assertEqual(blocks, [])
        self.assertEqual(text[skipped[0][0]:skipped[0][1]], "\\begin{solution} $\\tikzfig{a}$ \\end{solution}")

    def test_comment_environment(self):
        self.assertEqual(blocks_of("\\begin{comment}\n\\tikzfig{a}\n\\end{comment}"), [])

    def test_verbatim(self):
        self.assertEqual(blocks_of("\\begin{verbatim}\n$\\tikzfig{a}$ $\n\\end{verbatim}"), [])

    def test_verb(self):
        self.assertEqual(blocks_of("\\verb|$\\tikzfig{a}| and \\verb+\\[+"), [])

    def test_macro_definitions(self):
        text = ("\\newcommand{\\myfig}{\\tikzfig{a}}\n\\renewcommand\\other[1]{$\\tikzfig{#1}$}\n"
                "\\def\\x#1{\\[\\tikzfig{#1}\\]}\n\\newenvironment{e}{\\tikzfig{b}}{}\n$\\tikzfig{c}$")
        blocks = blocks_of(text)
        self.assertEqual([b.figures for b in blocks], [["c"]])


class TestIds(unittest.TestCase):
    def ids(self, text):
        return [b.id for b in assign_ids(blocks_of(text), CONFIG)]

    def test_label_gives_the_name(self):
        self.assertEqual(self.ids("\\begin{equation}\\tikzfig{a}\\label{eq:my-label}\\end{equation}"), ["eq-my-label"])

    def test_figure_gives_the_name(self):
        self.assertEqual(self.ids("\\[\\tikzfig{fig-a} = \\tikzfig{fig-b}\\]"), ["fig-a"])

    def test_macro_argument_gives_the_name(self):
        self.assertEqual(self.ids("$\\state{psi}$"), ["psi"])

    def test_same_content_shares_the_svg(self):
        # The same figure used several times, in different environments, is only converted once
        self.assertEqual(self.ids("\\[\\tikzfig{a}\\] text $\\tikzfig{a}$ \\begin{center}\\tikzfig{a}\\end{center} \\ctikzfig{a}"),
                         ["a", "a", "a", "a"])

    def test_different_content_gets_a_suffix(self):
        self.assertEqual(self.ids("\\[\\tikzfig{a}\\] \\[\\tikzfig{a} = \\tikzfig{b}\\] \\[\\tikzfig{a} = x\\]"),
                         ["a", "a-1", "a-2"])

    def test_names_differing_in_case_do_not_collide(self):
        # File names are case-insensitive on Windows and macOS
        self.assertEqual(self.ids("$\\tikzfig{S}$ $\\tikzfig{s} = x$"), ["S", "s-1"])

    def test_clean_label(self):
        self.assertEqual(clean_label("eq:a/b c"), "eq-a-b-c")
        self.assertEqual(clean_label(":x"), "x")
        self.assertEqual(clean_label("\\alpha"), "diagram")


if __name__ == "__main__":
    unittest.main()
