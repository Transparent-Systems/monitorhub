"""Unit tests for the diagram update utility (utils/update_diagram.py)."""

import contextlib
import io
import unittest

from utils.update_diagram import (
    DIAGRAMS,
    DiagramUpdateError,
    build_block,
    main,
    replace_block,
)

SPEC = DIAGRAMS["actionhandler"]
DIAGRAM = "classDiagram\n  class Widget {\n  }"


class TestBuildBlock(unittest.TestCase):
    def test_wraps_the_diagram_in_markers_and_a_mermaid_fence(self):
        block = build_block(SPEC, DIAGRAM)

        self.assertTrue(block.startswith(f"{SPEC.start_marker}\n```mermaid\n"))
        self.assertTrue(block.endswith(f"```\n{SPEC.end_marker}"))
        self.assertIn(DIAGRAM, block)

    def test_has_no_trailing_newline(self):
        self.assertFalse(build_block(SPEC, DIAGRAM).endswith("\n"))

    def test_strips_trailing_newlines_from_the_generated_diagram(self):
        block = build_block(SPEC, f"{DIAGRAM}\n\n\n")

        self.assertTrue(block.endswith(f"```\n{SPEC.end_marker}"))


class TestReplaceBlock(unittest.TestCase):
    def setUp(self):
        self.original = (
            "# Architecture Overview\n"
            "\n"
            f"{SPEC.start_marker}\n"
            "```mermaid\n"
            "classDiagram\n"
            "  class Old\n"
            "```\n"
            f"{SPEC.end_marker}\n"
            "\n"
            "\n"
            "\n"
            "## Commands UML Diagram\n"
            "\n"
            "text\n"
        )

    def test_replaces_only_the_marked_block(self):
        updated = replace_block(self.original, SPEC, build_block(SPEC, DIAGRAM))

        self.assertIn(DIAGRAM, updated)
        self.assertNotIn("class Old", updated)
        self.assertTrue(updated.startswith("# Architecture Overview\n\n"))
        self.assertTrue(updated.endswith("\n\n\n\n## Commands UML Diagram\n\ntext\n"))

    def test_is_a_no_op_when_the_block_is_unchanged(self):
        unchanged = replace_block(
            self.original, SPEC, build_block(SPEC, "classDiagram\n  class Old")
        )

        self.assertEqual(unchanged, self.original)

    def test_applying_twice_is_a_no_op(self):
        block = build_block(SPEC, DIAGRAM)
        once = replace_block(self.original, SPEC, block)
        twice = replace_block(once, SPEC, block)

        self.assertEqual(once, twice)

    def test_missing_markers_raise(self):
        with self.assertRaises(DiagramUpdateError):
            replace_block("# no markers here\n", SPEC, build_block(SPEC, DIAGRAM))

    def test_missing_end_marker_raises(self):
        with self.assertRaises(DiagramUpdateError):
            replace_block(f"{SPEC.start_marker}\n", SPEC, build_block(SPEC, DIAGRAM))


class TestCommandLine(unittest.TestCase):
    def test_unknown_diagram_is_rejected(self):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            main(["not-a-diagram"])

        self.assertEqual(cm.exception.code, 2)

    def test_every_diagram_spec_is_well_formed(self):
        for name, spec in DIAGRAMS.items():
            self.assertTrue(spec.source_path, name)
            self.assertTrue(spec.start_marker.startswith("<!--"), name)
            self.assertTrue(spec.end_marker.startswith("<!--"), name)


if __name__ == "__main__":
    unittest.main()
