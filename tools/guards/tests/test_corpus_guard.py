"""The corpus guard is the mechanical form of ADR-0014's bright line.

It denies by path and shape only. It never judges what a file *means*, because a
rule that needs per-corpus judgement is the rule ADR-0014 exists to avoid.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import corpus_guard


def reasons(paths, size_of=lambda _p: 0):
    return {v.path: v.reason for v in corpus_guard.violations(paths, size_of=size_of)}


class DataAndModelTrees(unittest.TestCase):
    def test_anything_under_data_is_denied(self):
        self.assertIn("data/wcf-1788-american/raw.xml", reasons(["data/wcf-1788-american/raw.xml"]))

    def test_anything_under_models_is_denied(self):
        self.assertIn("models/bge-m3/model.safetensors", reasons(["models/bge-m3/model.safetensors"]))

    def test_the_data_reason_names_adr_0014(self):
        self.assertIn("ADR-0014", reasons(["data/x.txt"])["data/x.txt"])


class CorporaTree(unittest.TestCase):
    def test_manifest_is_allowed(self):
        self.assertEqual(reasons(["corpora/wcf-1788-american/manifest.yaml"]), {})

    def test_fingerprints_is_allowed(self):
        self.assertEqual(reasons(["corpora/wcf-1788-american/fingerprints.txt"]), {})

    def test_any_other_file_under_a_corpus_is_denied(self):
        self.assertIn("corpora/wcf-1788-american/text.txt", reasons(["corpora/wcf-1788-american/text.txt"]))

    def test_a_stray_file_at_the_corpora_root_is_denied(self):
        self.assertIn("corpora/README.txt", reasons(["corpora/README.txt"]))


class TextBearingExtensions(unittest.TestCase):
    def test_a_txt_fixture_outside_the_allowlist_is_denied(self):
        self.assertIn("services/gateway/verify/fixture.txt", reasons(["services/gateway/verify/fixture.txt"]))

    def test_an_xml_file_is_denied(self):
        self.assertIn("tools/acquire/wcf.xml", reasons(["tools/acquire/wcf.xml"]))

    def test_markdown_is_allowed(self):
        self.assertEqual(reasons(["docs/adr/0014-no-corpus-text-in-the-repository.md"]), {})

    def test_source_files_are_allowed(self):
        self.assertEqual(reasons(["services/gateway/verify/verify.go", "tools/acquire/wcf.py"]), {})

    def test_extensionless_repo_files_are_allowed(self):
        self.assertEqual(reasons(["LICENSE", "NOTICE", "Makefile"]), {})

    def test_requirements_txt_is_allowed(self):
        self.assertEqual(reasons(["services/catena/requirements.txt"]), {})


class FixtureSizeCeiling(unittest.TestCase):
    def test_a_small_fixture_is_allowed(self):
        self.assertEqual(
            reasons(["services/catena/tests/testdata/normalisation.json"], size_of=lambda _p: 4096),
            {},
        )

    def test_an_oversized_fixture_is_denied(self):
        found = reasons(
            ["services/catena/tests/testdata/normalisation.json"],
            size_of=lambda _p: corpus_guard.FIXTURE_SIZE_CEILING + 1,
        )
        self.assertIn("services/catena/tests/testdata/normalisation.json", found)

    def test_the_ceiling_does_not_apply_outside_fixture_directories(self):
        self.assertEqual(
            reasons(["services/catena/src/catena/big_module.py"], size_of=lambda _p: 10_000_000),
            {},
        )


class Reporting(unittest.TestCase):
    def test_a_clean_changeset_yields_no_violations(self):
        self.assertEqual(reasons(["README.md", "compose.yaml", "services/gateway/main.go"]), {})

    def test_every_violating_path_is_reported_not_just_the_first(self):
        found = reasons(["data/a.xml", "corpora/x/text.txt", "README.md"])
        self.assertEqual(set(found), {"data/a.xml", "corpora/x/text.txt"})


if __name__ == "__main__":
    unittest.main()
