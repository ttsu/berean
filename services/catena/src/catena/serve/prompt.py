"""Layer 2 of three, and the layer that decides whether quoting works.

TECHNICAL-SPEC: "Prompting is layer 2 of 3 and is not trusted on its own; layer
3 is what makes it real." So nothing here is a guarantee. What it *is* is the
cheapest place to prevent the failure ADR-0018 names as the live risk to Phase 1
producing anything at all — a model that paraphrases early modern English by one
curly apostrophe fails every citation it emits, and the response to that must be
better prompting, never a looser check 2.

The single most valuable thing in this file is the passage delimiter. A probe
that wrapped passage text in double quotes got the quotation marks back *inside*
the quote, which against a real chunk fails exact substring containment while
looking exactly like a paraphrase failure. The delimiters are therefore whole
lines that cannot be mistaken for content, a passage containing one is refused
rather than escaped, and the rules say in as many words not to add quotation
marks.

Field *meaning* lives here rather than in the JSON Schema. The schema is layer
1 and enforces shape; describing what `position` is for is prompt work, and
putting it in the schema would make the contract live in two files again.
"""

from __future__ import annotations

from typing import Any, Sequence

from berean.v1 import common_pb2, filter_pb2, verification_pb2
from catena.serve import ServeError
from catena.serve.retrieval import Passage

#: Whole lines, so there is nothing inline for the model to copy into a quote.
TEXT_BEGIN = "-----BEGIN PASSAGE TEXT-----"
TEXT_END = "-----END PASSAGE TEXT-----"

RULES = f"""You answer questions about theology and church order using ONLY the passages
supplied below. You are one half of a system: everything you produce is checked
against the source database before any of it is shown to anyone. A citation that
does not resolve, or a quote that is not character-for-character present in its
passage, fails the whole answer.

CITATIONS ARE STRUCTURED FIELDS, NEVER PROSE
- Never name or describe a source inside claim, warrant, position, content or
  state_of_debate. Do not write "the Confession says", "WSC Q&A 9 states", or
  "the committee affirms". A source named in prose cannot be checked, which is
  the whole reason the citation fields exist.
- Put the source in a citations entry and let the prose make the point.

QUOTING
- Copy each quote character for character from between the {TEXT_BEGIN} and
  {TEXT_END} lines. Do not add quotation marks around it. Do not modernise
  spelling, straighten apostrophes, change dashes, or fix what looks like a typo.
- A quote must be at least 40 characters. A shorter one supports nothing and fails.
- Every citation carries the corpus_id and locator exactly as given with its passage.

WHERE A CLAIM GOES
- arguments: what the tradition affirms. Each needs at least one citation whose
  tier is TIER_BINDING or TIER_GOVERNING. Never cite TIER_CONTRARY or
  TIER_EXCLUDED here.
- descriptions: what a source says, rather than whether it is true. Any tier.
  This is where a repudiated or opposing source belongs.
- contrary_positions: a position that DIFFERS from the one the passages support,
  held by some other tradition and argued from its own sources. held_by names
  traditions or groups of people, never corpus_ids. If a passage says the same
  thing as one you already used in arguments, it does not belong here — a
  restatement is not a contrary position.
- position: the tradition's position in prose, and ONLY when arguments is
  non-empty. It is a sentence, not a label.
- warrant: the theological link from the citation to the claim. It is NOT an
  account of your own reasoning, and you must never describe how you arrived at
  anything.

LENGTH — every field is short
- claim: ONE sentence.
- warrant: ONE or TWO sentences saying why that citation carries that claim. It
  is not a summary of the passages and not a list of what each source says. If
  you find yourself naming several sources in a warrant, you wanted several
  arguments, each with its own citation.
- position: two or three sentences. state_of_debate: three or four.
- At most three arguments and at most three descriptions in the whole answer.
- A long answer is not a better one here. Everything is checked citation by
  citation, and an answer that runs past the token budget is discarded whole
  rather than shown in part.

WHEN THE PASSAGES DO NOT ANSWER THE QUESTION
- Emit no arguments, no descriptions and no contrary_positions, and set
  no_answer_reason to at most 200 characters saying the sources are silent.
- Say only THAT they are silent. Never say what the answer might have been.
- Do not fill a slot to be helpful. Leave it out entirely."""


def render_passages(passages: Sequence[Passage]) -> str:
    """The passage blocks, delimited by lines that cannot appear inside one."""
    blocks = []
    for index, passage in enumerate(passages, start=1):
        if TEXT_BEGIN in passage.text or TEXT_END in passage.text:
            # An escapable boundary is not a boundary. This should be
            # impossible — the delimiters are not text any corpus contains —
            # so it is a refusal rather than an escaping scheme.
            raise ServeError(
                f"chunk {passage.chunk_id} ({passage.corpus_id} {passage.locator}) "
                "contains a passage delimiter and cannot be framed safely"
            )
        blocks.append(
            f"PASSAGE {index}\n"
            f"corpus_id: {passage.corpus_id}\n"
            f"locator: {passage.locator}\n"
            f"tier: {passage.tier_name}\n"
            f"work: {passage.work}\n"
            f"{TEXT_BEGIN}\n{passage.text}\n{TEXT_END}"
        )
    return "\n\n".join(blocks)


def system_prompt(
    spec: filter_pb2.FilterSpec,
    contested_loci: Sequence[filter_pb2.ContestedLocus],
) -> str:
    """The rules, the corpora in scope, and the loci held open.

    The corpora and their tiers are the whole of what can be said here about who
    is asking. No profile name, no identity, no session — a search policy, not
    an identity (ADR-0015).
    """
    scope = "\n".join(
        f"- {entry.corpus_id} ({_tier_name(entry.tier)})" for entry in spec.corpora
    )
    parts = [RULES, f"CORPORA IN SCOPE, AND THE STANCE TAKEN TOWARD EACH\n{scope}"]

    if contested_loci:
        held_open = "\n".join(
            f"- {locus.locus}: established by {locus.ruling.corpus_id} "
            f"{locus.ruling.locator}"
            for locus in contested_loci
        )
        parts.append(
            "QUESTIONS THIS TRADITION HOLDS OPEN\n"
            f"{held_open}\n"
            "If the question falls under one of these loci, set contested.is_contested\n"
            "to true, set contested.locus to that exact identifier, cite the ruling\n"
            "named above, and quote it verbatim in state_of_debate. Then emit NO\n"
            "arguments at all: state briefly what is disputed and who holds what,\n"
            "and take no side. Keep state_of_debate to a few sentences built around\n"
            "the ruling's own words -- it is a citation, not an essay. Naming a locus\n"
            "that is not listed above fails the answer immediately."
        )

    return "\n\n".join(parts)


def render_failures(
    failures: Sequence[verification_pb2.VerificationResult], attempt: int
) -> str:
    """Last attempt's verification results, as facts.

    Go sends structured results and never composes prose telling this service
    how to fix an answer — `Confidence.reason` is the only Go-authored string in
    the system, and the first exception to that is the one that ends the
    guarantee (ADR-0010). The wording below is therefore Python's, written once,
    from fields Go filled in.
    """
    lines = []
    for result in failures:
        ref = result.citation_ref
        checks = []
        if not result.locator_resolved:
            checks.append("the locator did not resolve to a chunk")
        if not result.quote_matched:
            checks.append("the quote was not found verbatim in the chunk, or was under 40 characters")
        if not result.tier_permitted:
            checks.append("the tier is not permitted in the slot the citation occupied")
        if not result.license_permitted:
            checks.append("the licence does not permit serving that source")
        detail = f" ({result.failure_detail})" if result.failure_detail else ""
        lines.append(
            f"- {ref.corpus_id} {ref.locator}: " + "; ".join(checks or ["failed"]) + detail
        )

    return (
        f"THE PREVIOUS ATTEMPT FAILED VERIFICATION. This is attempt {attempt}.\n"
        + "\n".join(lines)
        + "\nProduce a fresh answer from the passages below. Cite only what you can "
        "quote character for character. If nothing supports an argument, emit no "
        "arguments and set no_answer_reason."
    )


def build(
    *,
    query: str,
    passages: Sequence[Passage],
    spec: filter_pb2.FilterSpec,
    contested_loci: Sequence[filter_pb2.ContestedLocus],
    previous_failures: Sequence[verification_pb2.VerificationResult],
    attempt: int,
) -> list[dict[str, Any]]:
    """The two turns sent to the generator."""
    user = []
    if previous_failures:
        user.append(render_failures(previous_failures, attempt))
    user.append(render_passages(passages) if passages
                else "No passages were retrieved for this question.")
    user.append(f"QUESTION\n{query.strip()}")

    return [
        {"role": "system", "content": system_prompt(spec, contested_loci)},
        {"role": "user", "content": "\n\n".join(user)},
    ]


def _tier_name(tier: int) -> str:
    return common_pb2.Tier.Name(tier)
