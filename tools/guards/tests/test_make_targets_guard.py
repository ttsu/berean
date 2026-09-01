"""The README's clone-to-first-answer path is the project's acceptance test.

A `make <target>` named in documentation but absent from the Makefile breaks that
path silently, and only for someone running it for the first time.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import make_targets_guard as guard


class ReferencesInDocumentation(unittest.TestCase):
    def test_an_inline_code_reference_is_found(self):
        self.assertEqual(guard.referenced_targets("Run `make provision` first."), {"provision"})

    def test_prose_outside_code_markup_is_ignored(self):
        self.assertEqual(guard.referenced_targets("Please make sure you read the spec."), set())

    def test_a_fenced_block_contributes_every_target(self):
        doc = "```\nmake provision\ndocker compose up\nmake corpus-verify\n```\n"
        self.assertEqual(guard.referenced_targets(doc), {"provision", "corpus-verify"})

    def test_flags_are_skipped_and_the_target_is_taken(self):
        self.assertEqual(guard.referenced_targets("`make -j4 provision`"), {"provision"})

    def test_a_bare_make_with_no_target_contributes_nothing(self):
        self.assertEqual(guard.referenced_targets("`make`"), set())

    def test_a_variable_override_is_not_mistaken_for_a_target(self):
        self.assertEqual(guard.referenced_targets("`make TOP_K=5 dev`"), {"dev"})


class MakefileParsing(unittest.TestCase):
    def test_a_plain_rule_is_a_target(self):
        self.assertIn("provision", guard.makefile_targets("provision:\n\techo hi\n"))

    def test_phony_declarations_are_targets(self):
        self.assertEqual(guard.makefile_targets(".PHONY: dev check\n"), {"dev", "check"})

    def test_a_rule_with_prerequisites_is_a_target(self):
        self.assertIn("provision", guard.makefile_targets("provision: models corpus\n\t@true\n"))

    def test_prerequisites_are_not_themselves_targets(self):
        self.assertEqual(guard.makefile_targets("provision: models corpus\n\t@true\n"), {"provision"})

    def test_a_colon_equals_assignment_is_not_a_target(self):
        self.assertEqual(guard.makefile_targets("COMPOSE := docker compose\n"), set())

    def test_a_double_colon_equals_assignment_is_not_a_target(self):
        self.assertEqual(guard.makefile_targets("COMPOSE ::= docker compose\n"), set())

    def test_a_pattern_rule_is_not_a_target(self):
        self.assertEqual(guard.makefile_targets("%.o: %.c\n\t@true\n"), set())

    def test_an_indented_recipe_line_is_never_a_target(self):
        self.assertEqual(guard.makefile_targets("dev:\n\tcd x: y\n"), {"dev"})


class Reporting(unittest.TestCase):
    MAKEFILE = ".PHONY: provision\nprovision:\n\t@true\n"

    def test_a_documented_target_that_exists_is_not_reported(self):
        self.assertEqual(guard.missing({"README.md": "`make provision`"}, self.MAKEFILE), [])

    def test_a_documented_target_with_no_rule_is_reported_with_its_file(self):
        self.assertEqual(
            guard.missing({"README.md": "`make deploy`"}, self.MAKEFILE),
            [("README.md", "deploy")],
        )

    def test_every_missing_target_is_reported_not_just_the_first(self):
        found = guard.missing(
            {"README.md": "`make deploy`", "docs/OPS.md": "`make rollback` and `make provision`"},
            self.MAKEFILE,
        )
        self.assertEqual(set(found), {("README.md", "deploy"), ("docs/OPS.md", "rollback")})


if __name__ == "__main__":
    unittest.main()
