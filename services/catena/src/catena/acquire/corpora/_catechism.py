"""Q&A segmentation, shared by the Larger and Shorter Catechisms.

A helper rather than an adapter: the leading underscore keeps it out of the
`corpus_id` → module mapping, which can never produce a name starting with one.

It lives apart from `_opc` because the two describe different facts and fail
differently. `_opc` describes the shape of a publisher's markup, and its failure
is garbage text. This describes the structure of a catechism — a numbered
question, its answer, and nothing between them — and its failure is a wrong
locator set. That is the same split the pipeline draws between `extract` and
`segment`, drawn again one level down.

**Chunk text carries neither marker.** `Q. 1.` and `A.` are dropped and the
question and answer are joined. Check 2 substring-matches a quote against
exactly this text, so a marker left sitting on the boundary fails any quote
spanning it — and a model quotes prose, not markers. Dropping the number
matches the confession's adapter, which puts the section number in the locator
and not in the text. The boundary survives anyway: every question in both
catechisms ends in a question mark.
"""

from __future__ import annotations

import re
from typing import Iterator

from catena.acquire.record import AcquisitionError, Segment

#: A question opens with its number. The number is the locator's, and is not
#: carried into the text.
_QUESTION = re.compile(r"^Q\.\s*(\d+)\.\s*(\S.*)$")

#: An answer opens with a bare `A.` and must be the line after its question.
_ANSWER = re.compile(r"^A\.\s*(\S.*)$")


def _is_division(line: str) -> bool:
    """A division heading is an all-caps line between Q&As.

    Matched structurally rather than by its text, and not for tidiness:
    hard-coding the Larger Catechism's two headings would commit corpus text to
    this repository, which ADR-0014 forbids without exception. The rule holds on
    the real sources — those two are the only all-caps lines in either document,
    and every continuation line inside WLC 99 and WLC 151 carries lowercase.

    A count is asserted by the caller, so a source that grows or loses one is a
    failure rather than a silent drop.
    """
    return not any(character.islower() for character in line)


def _close(
    corpus_id: str, prefix: str, number: int, question: str, body: list[str] | None
) -> Segment:
    if body is None:
        raise AcquisitionError(
            f"{corpus_id}: Q&A {number} has a question and no answer. Never split a "
            "catechism answer from its question — a question reaching the next question "
            "with nothing between them means extraction dropped the answer, and a chunk "
            "holding only a question would verify clean forever after."
        )
    return Segment(f"{prefix} Q&A {number}", "\n".join([question, *body]))


def segment_qa(
    document: str,
    *,
    corpus_id: str,
    prefix: str,
    expected_questions: int,
    expected_divisions: int,
) -> Iterator[Segment]:
    """One chunk per question-and-answer pair: `WSC Q&A 1`.

    Structural, never fixed-token. The numbering is asserted contiguous from 1
    and the total against `expected_questions`, because a missed question and a
    dropped one both show up as a gap and neither shows up as an error anywhere
    else.
    """
    number: int | None = None
    question: str | None = None
    body: list[str] | None = None
    divisions = 0
    next_number = 1

    for raw in document.splitlines():
        line = raw.strip()
        if not line:
            continue

        opening = _QUESTION.match(line)
        if opening:
            if number is not None:
                yield _close(corpus_id, prefix, number, question, body)
            found = int(opening.group(1))
            if found != next_number:
                raise AcquisitionError(
                    f"{corpus_id}: Q&A {found} where Q&A {next_number} was expected; the "
                    "question numbering is not contiguous, so extraction dropped a pair "
                    "or the source is not this catechism"
                )
            number, question, body = found, opening.group(2), None
            next_number = found + 1
            continue

        answering = _ANSWER.match(line)
        if answering:
            if number is None:
                raise AcquisitionError(
                    f"{corpus_id}: an answer appears before any question: {line[:60]!r}…"
                )
            if body is not None:
                raise AcquisitionError(
                    f"{corpus_id}: Q&A {number} has a second answer. A locator resolves to "
                    "exactly one chunk, and two answers under one question means the "
                    "question between them was dropped."
                )
            body = [answering.group(1)]
            continue

        if _is_division(line):
            if number is not None and body is None:
                raise AcquisitionError(
                    f"{corpus_id}: a division heading interrupts Q&A {number} before its "
                    "answer, which means the answer was dropped"
                )
            if number is not None:
                yield _close(corpus_id, prefix, number, question, body)
                number, question, body = None, None, None
            divisions += 1
            continue

        if body is None:
            raise AcquisitionError(
                f"{corpus_id}: text outside any question and answer: {line[:60]!r}… — "
                "dropping it silently is how a chunk goes missing without anything failing"
            )
        body.append(line)

    if number is not None:
        yield _close(corpus_id, prefix, number, question, body)

    questions = next_number - 1
    if questions != expected_questions:
        raise AcquisitionError(
            f"{corpus_id}: {questions} questions, expected {expected_questions}. A "
            "different count is a different edition, and the divergence is structural "
            "where the edition diagnostic's is textual."
        )
    if divisions != expected_divisions:
        raise AcquisitionError(
            f"{corpus_id}: {divisions} division headings, expected {expected_divisions}. "
            "A heading is dropped rather than chunked, so a change in their number means "
            "text is being dropped that nothing else would report."
        )
