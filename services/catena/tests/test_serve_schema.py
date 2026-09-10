"""The decoding constraint is derived from the contract, never hand-written.

`AnswerObject` is deep, and a hand-written JSON Schema beside it is a second
copy of the contract that drifts silently — the thing CLAUDE.md names outright.
So the schema is walked out of the descriptor, and this suite asserts the two
places the walk deliberately departs from a naive translation:

* `confidence` is subtracted, because Go derives both halves (ADR-0020). The
  subtraction is asserted here so it stays a visible act rather than an absence
  nobody notices.
* `required` follows the list-only rule. See `catena.serve.schema` for why; the
  cases below are what a live probe against the pinned generator actually
  produced under each alternative.
"""

from __future__ import annotations

import unittest

from berean.v1 import answer_pb2, common_pb2
from catena.serve import schema as schema_module


def objects(node, path="$"):
    """Every JSON Schema object node, so a rule can be asserted over all of them."""
    out = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            out.append((path, node))
        for key, value in node.items():
            out.extend(objects(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out.extend(objects(value, f"{path}[{i}]"))
    return out


class DerivedFromTheContract(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = schema_module.answer_schema()

    def test_every_answer_object_field_appears_except_confidence(self) -> None:
        expected = set(answer_pb2.AnswerObject.DESCRIPTOR.fields_by_name) - {"confidence"}
        self.assertEqual(set(self.schema["properties"]), expected)

    def test_confidence_is_absent_from_properties_and_defs(self) -> None:
        """Go derives level and reason and overwrites whatever arrives.

        Absent from the schema means the constrained decoder cannot emit it at
        all, which is a stronger guarantee than ignoring it on parse.
        """
        self.assertNotIn("confidence", self.schema["properties"])
        self.assertNotIn("Confidence", self.schema["$defs"])

    def test_additional_properties_false_everywhere(self) -> None:
        """What makes the confidence subtraction enforced rather than merely omitted."""
        for name, obj in objects(self.schema):
            self.assertIs(obj.get("additionalProperties"), False, name)

    def test_tier_enum_carries_every_value_name(self) -> None:
        citation = self.schema["$defs"]["Citation"]
        expected = [v.name for v in common_pb2.Tier.DESCRIPTOR.values]
        self.assertEqual(citation["properties"]["tier"]["enum"], expected)


class TheListOnlyRequiredRule(unittest.TestCase):
    """Required where a message has no meaningful empty state, and nowhere else.

    A message reached only through a repeated field is emitted whole or not at
    all: absence is the list being empty, never a half-filled element. A
    `Citation` without `{corpus_id, locator}` is not an absent citation, it is
    one that cannot resolve to a chunk — which check 1 fails by construction.

    A message reached as a singular field is the opposite. `AnswerObject` and
    `Contested` are exactly the messages whose *emptiness* the contract reads as
    meaning — the honest non-answer, `is_contested: false` — and a required
    string cannot be absent, so requiring them makes the decoder narrate into a
    slot whose correct value is nothing.
    """

    def setUp(self) -> None:
        self.schema = schema_module.answer_schema()

    def test_nothing_is_required_on_the_root(self) -> None:
        self.assertEqual(self.schema["required"], [])

    def test_nothing_is_required_on_contested(self) -> None:
        self.assertEqual(self.schema["$defs"]["Contested"]["required"], [])

    def test_every_field_is_required_inside_list_only_messages(self) -> None:
        for name in ("Citation", "Argument", "Description", "ContraryPosition"):
            with self.subTest(message=name):
                obj = self.schema["$defs"][name]
                self.assertEqual(sorted(obj["required"]), sorted(obj["properties"]))

    def test_no_count_constraint_anywhere(self) -> None:
        """A probe showed `minItems` is honoured — by padding a fabricated citation.

        An argument the model cannot cite emits `citations: []`, which Go fails
        loudly on a path that already exists. Forcing a count instead buys an
        invented citation, which is the failure the trust boundary exists to
        catch. The constraint works; that is precisely why it must not be used.
        """
        found = []
        self._walk_for(self.schema, ("minItems", "maxItems", "minLength", "maxLength"), found)
        self.assertEqual(found, [])

    def _walk_for(self, node, keys, found, path="") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys:
                    found.append(f"{path}.{key}")
                self._walk_for(value, keys, found, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                self._walk_for(value, keys, found, f"{path}[{i}]")


class TheSchemaAndTheParserAgree(unittest.TestCase):
    """Absent means default, in the schema and in `ParseDict` alike.

    This is the property that makes the permissive rule safe: a slot the model
    omits parses to the proto3 default, which is the same state the contract
    reads as empty. Nothing has to translate between them.
    """

    def test_an_omitted_slot_parses_to_the_proto3_default(self) -> None:
        from google.protobuf import json_format

        answer = json_format.ParseDict(
            {"no_answer_reason": "The sources do not address it."},
            answer_pb2.AnswerObject(),
        )
        self.assertEqual(answer.position, "")
        self.assertEqual(list(answer.arguments), [])
        self.assertFalse(answer.contested.is_contested)

    def test_a_fully_populated_payload_round_trips(self) -> None:
        from google.protobuf import json_format

        payload = {
            "position": "Invented, per ADR-0014.",
            "arguments": [{
                "claim": "A claim.",
                "warrant": "A warrant.",
                "citations": [{
                    "corpus_id": "aaa-1111-alpha",
                    "locator": "AAA 1.1",
                    "tier": "TIER_BINDING",
                    "quote": "Invented text standing in for a real passage here.",
                }],
            }],
        }
        answer = json_format.ParseDict(payload, answer_pb2.AnswerObject())
        self.assertEqual(answer.arguments[0].citations[0].tier, common_pb2.TIER_BINDING)


if __name__ == "__main__":
    unittest.main()
