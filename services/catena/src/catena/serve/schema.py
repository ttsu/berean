"""The JSON Schema the decoder is constrained to, walked out of the contract.

ADR-0018 requires `AnswerObject` validity to be a *decoding constraint* rather
than a request the prompt makes politely. That needs a JSON Schema, and the
schema is derived from `AnswerObject.DESCRIPTOR` rather than written beside it:
a hand-written copy is a second place the contract lives, drifting silently
whenever `proto/` changes, and CLAUDE.md names that outright — never
hand-maintain a struct on one side.

The walk departs from a naive translation in exactly two places, both below and
both deliberate.

## `confidence` is subtracted

Go derives `level` and `reason` from the verification result and overwrites
whatever arrives (ADR-0020). Removing the field from the schema makes it
*unpopulatable* rather than merely ignored, which is a stronger guarantee than
dropping it on parse — and `additionalProperties: false` is what closes the
door behind it. It is one visible line rather than an absence nobody notices.

## `required` follows the list-only rule

    Fields are required in messages reachable ONLY through a repeated field.
    Nothing is required in messages reachable as a singular field, or at the
    root.

This sorts the contract cleanly: `Citation`, `Argument`, `Description` and
`ContraryPosition` appear only as `repeated`; `Contested` is singular and
`AnswerObject` is the root.

The principle underneath is whether the message has a **meaningful empty
state**. A message reached only through a list does not: absence is expressed
by the list being empty, never by a half-filled element. A `Citation` carrying
no `{corpus_id, locator}` is not an absent citation — it is one that cannot
resolve to a chunk, which check 1 fails by construction.

A message reached as a singular field is the opposite, and `AnswerObject` and
`Contested` are precisely the messages whose emptiness the contract *reads as
meaning*: every slot empty is the honest non-answer, `is_contested: false` is
"not contested", and `position` MUST be empty when `arguments` is. A required
string cannot be absent — the decoder must emit something, and a model forced
to emit something narrates rather than emitting `""`.

None of this is reasoned from first principles alone. Probes against the pinned
generator produced, under a fully strict schema and a silent corpus,
`position: "no_position"` beside `arguments: []` — a straight violation of the
empty-when-descriptive rule, and a guaranteed regeneration on the cheapest case
in the system. Under a fully permissive schema and an answerable question, a
citation carrying only `tier` and `quote`. The rule above is the one that got
both cases right, and it also runs 3-4x cheaper in tokens than the strict form,
which on CPU is the difference between a 14-second answer and a 46-second one.

## No count constraints, anywhere

`minItems` *is* honoured by the decoder — and a probe forcing two citations
from one passage got a fabricated second quote for its trouble. An argument the
model cannot cite emits `citations: []`, which Go fails loudly on a path that
already exists for it; forcing a count buys an invented citation instead, which
is the failure class the trust boundary exists to catch. The constraint works,
and that is exactly why it is not used. `test_no_count_constraint_anywhere`
guards the reintroduction.

Field *meaning* is not expressed here either. That is the prompt's job — layer
2 of the three TECHNICAL-SPEC names — and mixing it in would put contract prose
back in a second file.
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor

from berean.v1 import answer_pb2

#: Derived by Go from the verification result, and overwritten whatever arrives
#: (ADR-0020). Subtracted by name so the act is greppable from the proto.
EXCLUDED_ROOT_FIELDS = frozenset({"confidence"})

_SCALARS: dict[int, dict[str, str]] = {
    descriptor.FieldDescriptor.TYPE_STRING: {"type": "string"},
    descriptor.FieldDescriptor.TYPE_BOOL: {"type": "boolean"},
    descriptor.FieldDescriptor.TYPE_INT32: {"type": "integer"},
    descriptor.FieldDescriptor.TYPE_INT64: {"type": "integer"},
    descriptor.FieldDescriptor.TYPE_UINT32: {"type": "integer"},
    descriptor.FieldDescriptor.TYPE_UINT64: {"type": "integer"},
    descriptor.FieldDescriptor.TYPE_FLOAT: {"type": "number"},
    descriptor.FieldDescriptor.TYPE_DOUBLE: {"type": "number"},
}


def answer_schema() -> dict[str, Any]:
    """`AnswerObject` as a JSON Schema, minus `confidence`.

    Returns a fresh dict each call: callers hand it to a request body, and a
    shared mutable schema is a bug waiting for the first caller that tweaks it.
    """
    root = answer_pb2.AnswerObject.DESCRIPTOR
    reachable = _reachable(root)
    list_only = _list_only(root, reachable)

    defs = {
        message.name: _object(message, list_only, excluded=frozenset())
        for message in reachable
        if message is not root
    }
    schema = _object(root, list_only, excluded=EXCLUDED_ROOT_FIELDS)
    schema["$defs"] = defs
    return schema


def _reachable(root: descriptor.Descriptor) -> list[descriptor.Descriptor]:
    """Every message the schema needs, in discovery order.

    Walked *after* the root exclusion, so `Confidence` never enters `$defs` —
    a definition nothing references would be dead weight the decoder still has
    to parse, and a reader would reasonably wonder whether it was reachable.
    """
    seen: dict[str, descriptor.Descriptor] = {root.full_name: root}
    order = [root]
    queue = [root]
    while queue:
        message = queue.pop(0)
        excluded = EXCLUDED_ROOT_FIELDS if message is root else frozenset()
        for field in message.fields:
            if field.name in excluded:
                continue
            target = field.message_type
            if target is not None and target.full_name not in seen:
                seen[target.full_name] = target
                order.append(target)
                queue.append(target)
    return order


def _list_only(
    root: descriptor.Descriptor, reachable: list[descriptor.Descriptor]
) -> frozenset[str]:
    """Messages every reference to which is a repeated field.

    The root is never list-only: nothing references it, and it is the one
    message whose total emptiness the contract reads as an honest non-answer.
    """
    repeated: dict[str, bool] = {}
    for message in reachable:
        excluded = EXCLUDED_ROOT_FIELDS if message is root else frozenset()
        for field in message.fields:
            if field.name in excluded or field.message_type is None:
                continue
            name = field.message_type.full_name
            is_repeated = field.is_repeated
            repeated[name] = repeated.get(name, True) and is_repeated
    return frozenset(name for name, only in repeated.items() if only)


def _object(
    message: descriptor.Descriptor,
    list_only: frozenset[str],
    *,
    excluded: frozenset[str],
) -> dict[str, Any]:
    properties = {
        field.name: _field(field)
        for field in message.fields
        if field.name not in excluded
    }
    return {
        "type": "object",
        "properties": properties,
        # The list-only rule. See the module docstring for the probe results
        # behind it; it is not a tuning knob.
        "required": list(properties) if message.full_name in list_only else [],
        # Closes the door behind the `confidence` subtraction, and stops the
        # model volunteering a key the contract does not have — `reasoning`
        # being the one it would reach for (CLAUDE.md constraint 5).
        "additionalProperties": False,
    }


def _field(field: descriptor.FieldDescriptor) -> dict[str, Any]:
    item = _item(field)
    if field.is_repeated:
        # No `minItems`. See the module docstring: the constraint is honoured,
        # and what it buys is a fabricated citation.
        return {"type": "array", "items": item}
    return item


def _item(field: descriptor.FieldDescriptor) -> dict[str, Any]:
    if field.message_type is not None:
        return {"$ref": f"#/$defs/{field.message_type.name}"}
    if field.enum_type is not None:
        # Proto3 JSON encodes an enum as its value *name*, which is what
        # `ParseDict` accepts on the way back. The zero value is included: it is
        # in the domain, and Go checks the tier against the resolved profile
        # rather than believing what arrives, so an unspecified tier fails
        # cleanly instead of needing the schema to pre-empt it.
        return {"type": "string", "enum": [v.name for v in field.enum_type.values]}
    try:
        return dict(_SCALARS[field.type])
    except KeyError:  # pragma: no cover - a contract change, not a runtime path
        raise NotImplementedError(
            f"{field.full_name} has no JSON Schema mapping. The contract grew a "
            f"type the decoder constraint cannot express (proto type {field.type})."
        ) from None
