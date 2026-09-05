"""Blessing from the browser: the one write path this tool has.

Blessing records that a human read the edition diagnostic and approved it. It is
the step nothing automates, and this module does not automate it -- it moves the
reading somewhere a 1,200-character passage can actually be read, and keeps every
condition `pipeline.bless` imposes. The TTY check was always a proxy for "a human
is present and read the text", never the requirement itself, which is why
`bless()` takes `prompt` and `interactive` as injectable seams. ADR-0021 records
the amendment.

What is preserved, and why each one matters:

* **The text is shown in full before anything is written.** Not a summary, not
  the locator, not a checkbox. The passage itself.
* **A name is typed, per bless.** `bless()` refuses a name passed as a flag
  because that records that someone typed a name rather than that anyone read
  the text; a form field a person fills in is the same act as the prompt.
* **What was read is what gets blessed.** This is the condition the terminal
  gets for free and a web form does not. An unblessed corpus has no manifest, so
  there is no `expected_digest` and `fetch` re-downloads rather than reading its
  cache -- meaning the acquisition behind the POST is not the one behind the GET.
  The form carries the sha256 of the passage that was displayed, and the bless
  is refused unless the freshly acquired diagnostic still hashes to it. A refusal
  stages what it just acquired, so the reload the refusal asks for shows the text
  that is upstream *now* rather than the one whose hash was rejected -- otherwise
  the refusal is permanent and the corpus can only be blessed from a terminal.

**Unblessed corpora only.** Re-blessing replaces a verification someone already
made and demands a typed confirmation against a fingerprint diff nobody should
skim in a browser; drift especially is where "never bless your way past a
mismatch you have not understood" bites hardest. Both stay at the terminal.
"""

from __future__ import annotations

import datetime
import io
import pathlib
import secrets
from dataclasses import dataclass

from catena.acquire import corpora
from catena.acquire import fetch as fetching
from catena.acquire import fingerprints as fp
from catena.acquire import manifest as mf
from catena.acquire import pipeline
from catena.acquire.record import AcquisitionError
from catena.browse import staged


def new_token() -> str:
    """A per-run token, embedded in the form and required on the POST.

    A localhost HTTP server is reachable from every page the browser has open, so
    a write endpoint without this is one any website can trigger. The token is
    the defence that does not depend on header hygiene; the origin check in the
    handler is the second one.
    """
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Verification:
    """What a human must read before the form will accept anything."""

    corpus_id: str
    diagnostic: str
    text: str
    content_hash: str
    source_url: str


class NotVerifiable(Exception):
    """Why this corpus cannot be blessed from here. Shown, never swallowed."""


def offer(corpus: staged.Corpus) -> Verification:
    """The edition verification to put in front of a human, or why there is none.

    Reads the diagnostic's text from the staged records rather than re-acquiring,
    so displaying the page costs no network. `apply` re-checks the hash, which is
    what makes that safe.
    """
    if corpus.overlay_error is not None:
        # An unreadable overlay leaves `fingerprint_status` at UNBLESSED, which
        # is the one status this path accepts. Blessing over it would overwrite
        # committed evidence nobody has been able to read.
        raise NotVerifiable(
            f"{corpus.corpus_id}: {corpus.overlay_error} Until that is understood there is "
            "no way to tell an unblessed corpus from one whose blessing cannot be read, and "
            "blessing would overwrite it. Nothing is offered here."
        )

    if corpus.fingerprint_status != staged.UNBLESSED:
        raise NotVerifiable(
            f"{corpus.corpus_id} is already blessed. Re-blessing replaces a verification "
            "someone already made, and is deliberately only available at a terminal: "
            f"`make bless CORPUS={corpus.corpus_id}`."
        )

    adapter = _adapter(corpus.corpus_id)
    record = next(
        (chunk for chunk in corpus.chunks if chunk.locator == adapter.diagnostic), None
    )
    if record is None:
        raise NotVerifiable(
            f"{corpus.corpus_id}: the edition diagnostic {adapter.diagnostic!r} is not among "
            f"the {len(corpus.chunks)} staged locators. Nothing can be verified until "
            "segmentation produces it."
        )

    return Verification(
        corpus_id=corpus.corpus_id,
        diagnostic=adapter.diagnostic,
        text=record.text,
        content_hash=record.content_hash,
        source_url=adapter.fetch_plan().source_url,
    )


def apply(
    corpus_id: str,
    *,
    name: str,
    read_hash: str,
    data_dir: pathlib.Path,
    corpora_dir: pathlib.Path,
    today: datetime.date | None = None,
    downloader: fetching.Downloader = fetching.download,
) -> mf.Manifest:
    """Acquire, check the text is the one that was read, and bless.

    `read_hash` is the sha256 of the passage the form displayed. Everything else
    here is `catena acquire --bless` with the two prompts already answered.
    """
    name = name.strip()
    if not name:
        raise NotVerifiable(
            "No verifier name given; nothing written. The name records who read the "
            "text, so there is no default and no anonymous bless."
        )

    # Before the network, and before any comparison. `secrets.compare_digest`
    # raises on non-ASCII `str` operands, and the request body is decoded with
    # errors="replace" -- so a garbled submission arrives holding U+FFFD and
    # would crash the handler after a pointless re-fetch rather than be refused.
    if not fp.HASH.match(read_hash):
        raise NotVerifiable(
            "The submitted hash is not a sha256 as this project writes one (64 lower-case "
            "hex digits), so it cannot be the hash of the passage the page displayed. "
            "Nothing written — reload the corpus page and submit the form there."
        )

    adapter = _adapter(corpus_id)
    committed_dir = corpora_dir / corpus_id
    try:
        committed = mf.read(committed_dir / mf.FILENAME)
    except AcquisitionError as error:
        # `mf.read` raises on a manifest it cannot parse. Reaching past that to
        # bless would overwrite a provenance record nobody has read.
        raise NotVerifiable(
            f"{corpus_id}: the committed manifest cannot be read — {error}. Nothing "
            "written; repair or remove it at a terminal before blessing over it."
        )
    if committed is not None:
        raise NotVerifiable(
            f"{corpus_id} acquired a manifest since the page was rendered. Re-blessing "
            "is a terminal act; nothing written."
        )

    try:
        acquired = pipeline.acquire(
            adapter,
            data_dir=data_dir,
            manifest=None,
            from_file=None,
            refetch=False,
            # Injected rather than defaulted, the way `cli.run_one` injects it:
            # `pipeline.acquire` binds its default at definition, so a caller that
            # does not pass one cannot be tested without reaching the network.
            downloader=downloader,
        )
    except AcquisitionError as error:
        raise NotVerifiable(f"{corpus_id}: acquisition failed, nothing written — {error}")

    record = acquired.record_at(adapter.diagnostic)
    if record is None:
        raise NotVerifiable(
            f"{corpus_id}: the edition diagnostic {adapter.diagnostic!r} is not among the "
            f"{len(acquired.records)} locators acquired. Nothing written."
        )
    if not secrets.compare_digest(record.content_hash, read_hash):
        # Stage what was just acquired before refusing. `acquire` has already
        # rewritten segment/ and normalise/ from this fetch; leaving stage/ on
        # the previous one makes the refusal permanent, because the page would go
        # on rendering the passage whose hash was just rejected and every
        # resubmission would carry that same stale hash. Staging is what makes
        # "read the text again" a thing the reader can actually do -- and the
        # corpus is unblessed, so there are no committed records to disturb.
        pipeline.write_stage(acquired, data_dir=data_dir)
        raise NotVerifiable(
            f"{corpus_id}: {adapter.diagnostic} now hashes to {record.content_hash}, not to "
            f"the {read_hash} shown on the page you submitted. An unblessed corpus carries "
            "no upstream digest, so acquisition re-fetched and the source has changed since "
            "you read it. Nothing written — the passage below is the one that is upstream "
            "now, so read the text again and resubmit if it is the right edition."
        )

    day = (today or datetime.date.today()).isoformat()
    # bless() prints the diagnostic's text to its stream. Acquisition keeps corpus
    # text out of terminals and logs on purpose, and a server log is the worst
    # place of all for it, so the transcript is captured and dropped. The page
    # already showed the human what they were approving.
    transcript = io.StringIO()
    try:
        manifest = pipeline.bless(
            adapter,
            acquired,
            corpora_dir=corpora_dir,
            retrieved=day,
            verified=day,
            existing=fp.read(committed_dir / mf.FINGERPRINTS_FILENAME),
            stream=transcript,
            prompt=_answers([name]),
            # The human is at the other end of this request. `bless()` refuses a
            # non-TTY because unattended CI must not bless; a person who has just
            # read the passage in a browser is not that.
            interactive=True,
        )
    except AcquisitionError as error:
        raise NotVerifiable(f"{corpus_id}: {error}")

    pipeline.write_stage(acquired, data_dir=data_dir)
    return manifest


def _adapter(corpus_id: str):
    try:
        return corpora.load(corpus_id)
    except (KeyError, ValueError) as error:
        raise NotVerifiable(
            f"{corpus_id} has staged output but no registered adapter, so there is nothing "
            f"to re-acquire and verify against: {error}"
        )


def _answers(queued: list[str]):
    """Answer `bless()`'s prompts from the form, in the order it asks them.

    Only the name is queued, because this path refuses a corpus that has been
    blessed before -- which is the one case that asks a second question.
    """
    remaining = iter(queued)

    def prompt(_message: str) -> str:
        try:
            return next(remaining)
        except StopIteration:  # pragma: no cover - guarded by the re-bless refusal
            raise AcquisitionError(
                "bless asked a question this form has no answer for; nothing written"
            )

    return prompt
