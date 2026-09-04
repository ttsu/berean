"""Work facts, segments, and staged records — the seam acquisition ends at.

Acquisition is messy, one-time, and human-supervised; ingestion is
deterministic and repeatable. The seam between them is a directory of staged
records, and ingestion never crosses back over it to parse an upstream format
or touch the network.

Staging writes the work-level facts beside the records so ingestion reads them
from here rather than re-deriving them from a source it is forbidden to parse.
The fields are exactly the ones INTEGRATION-SPEC stores on `corpus.works`; the
two enums are closed for the reason the database closes them, which is that a
free-text licence reduces verification check 4 to "the string is non-empty"
(ADR-0017).

Nothing in this module knows what any corpus says. See ADR-0014.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pathlib
import re
import tempfile
from dataclasses import dataclass
from typing import Any, Iterable, Iterator


class AcquisitionError(Exception):
    """Acquisition stopped rather than producing something unverified."""


#: `corpus.text_form`. The TR-versus-critical distinction exists only for
#: biblical text, so a confession says `not-applicable` rather than inventing a
#: value.
TEXT_FORMS = frozenset({"tr", "critical", "majority", "not-applicable"})

#: `corpus.license`. Confirmed per source and recorded, never assumed.
LICENSES = frozenset({"public-domain", "cc-by", "cc-by-sa", "local-only", "refused"})


@dataclass(frozen=True)
class WorkFacts:
    """The work-level half of the chunk metadata contract.

    `author` is the only nullable field, because most of the Phase 1 corpus is
    corporate. `language` is the language of the text as ingested and
    `source_language` is the work's own — they differ for a translation, and
    backfilling either means re-ingesting (ADR-0008).
    """

    work: str
    author: str | None
    era: str
    language: str
    source_language: str
    text_form: str
    edition: str
    license: str
    attribution: str

    def __post_init__(self) -> None:
        for field in ("work", "era", "language", "source_language", "edition", "attribution"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise AcquisitionError(f"work facts: {field} is required and must be non-empty")
        if self.author is not None and not self.author.strip():
            raise AcquisitionError(
                "work facts: author is either a name or null — the empty string is a "
                "second way to say 'no author' and the database rejects it"
            )
        if self.text_form not in TEXT_FORMS:
            raise AcquisitionError(
                f"work facts: text_form {self.text_form!r} is not one of "
                f"{sorted(TEXT_FORMS)} — the domain is closed"
            )
        if self.license not in LICENSES:
            raise AcquisitionError(
                f"work facts: license {self.license!r} is not one of {sorted(LICENSES)} — "
                "the domain is closed, and a free-text licence is a check that reports "
                "success while evaluating nothing (ADR-0017)"
            )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WorkFacts":
        fields = {f.name for f in dataclasses.fields(cls)}
        missing = fields - raw.keys()
        if missing:
            raise AcquisitionError(f"work facts: missing {sorted(missing)}")
        unknown = raw.keys() - fields
        if unknown:
            raise AcquisitionError(f"work facts: unknown {sorted(unknown)}")
        return cls(**{name: raw[name] for name in fields})


@dataclass(frozen=True)
class Segment:
    """One structural unit, before normalisation.

    What the adapter's `segment` yields. The text is whatever the source had;
    normalisation is applied by the pipeline, never by the adapter.
    """

    locator: str
    text: str


@dataclass(frozen=True)
class StagedRecord:
    """One structural unit, after normalisation, with its fingerprint.

    `text` is post-normalisation text and nothing else — the same rule
    `corpus.chunks.text` follows, and for the same reason: verification
    substring-matches against exactly that text, and a raw copy beside it would
    give the check two candidates and no rule for choosing.
    """

    locator: str
    text: str
    content_hash: str


def fingerprint(text: str) -> str:
    """The committed per-chunk hash: sha256 of normalised text, lowercase hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: A locator has to survive the round trip through `fingerprints.txt`, which is
#: one `<locator>  <sha256>` per line. A locator carrying a newline, or a run of
#: two spaces, writes a file the parser rejects on the next run — and a bless
#: that reported success is what put it there. Single internal spaces are fine
#: and load-bearing: `WSC Q&A 1`.
LOCATOR = re.compile(r"^\S+( \S+)*$")


def stage(locator: str, normalised_text: str) -> StagedRecord:
    if not LOCATOR.match(locator):
        raise AcquisitionError(
            f"locator {locator!r} cannot be written to a fingerprints file, which is one "
            "'<locator>  <sha256>' per line. A locator is non-empty and carries no newline, "
            "tab, or doubled space."
        )
    if not normalised_text:
        raise AcquisitionError(
            f"{locator}: normalised to the empty string — a segment that survives "
            "extraction but not normalisation is a broken parser, not a chunk"
        )
    return StagedRecord(locator, normalised_text, fingerprint(normalised_text))


def write_jsonl(path: pathlib.Path, rows: Iterable[Any]) -> None:
    """Write dataclass rows as JSON lines, temp-then-rename.

    Every stage writes this way. An interrupted run must leave the previous
    output intact rather than a half-file the next run reads as complete.
    """
    payload = "".join(
        json.dumps(dataclasses.asdict(row), ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    )
    write_text(path, payload)


def read_jsonl(path: pathlib.Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_text(path: pathlib.Path, text: str) -> None:
    """Atomic within a directory: write a sibling temp file, then rename."""
    write_bytes(path, text.encode("utf-8"))


def write_bytes(path: pathlib.Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        # A rename that never happened leaves the temp file behind, and the next
        # run would not know to reuse it. Unlink rather than accumulate.
        pathlib.Path(handle.name).unlink(missing_ok=True)
        raise
