"""`corpora/<corpus-id>/fingerprints.txt` — read, write, and diff.

The fingerprints are the mechanism that replaces committing the text
(ADR-0014). A corpus is fetched, segmented, normalised, and hashed, and every
hash must match the committed value. That is a stronger guarantee than a
committed copy: it proves the text was reconstructed exactly as hand-verified
*and* that normalisation is deterministic across runs and machines.

Nothing here ever prints text. A diff that showed the differing passage would
put corpus text into CI logs and terminal scrollback, and the point of ADR-0014
is that text has exactly one home.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field
from typing import Mapping

from catena.acquire.record import AcquisitionError, write_text

#: Two spaces. Locators contain single spaces (`WCF 23.3`, `WSC Q&A 1`) and
#: hashes contain none, so the last whitespace run is the separator on read.
SEPARATOR = "  "

#: A sha256 as this project writes one: lower-case hex, exactly 64 digits.
#: Public because anything comparing a submitted hash against a committed one
#: has to agree on the shape before it compares -- see `browse/verify.py`.
HASH = re.compile(r"^[0-9a-f]{64}$")

#: Verify reports counts in full and locators by sample. A corpus whose every
#: locator moved would otherwise print thousands of lines, and the first ten say
#: the same thing.
SAMPLE = 10


def sort_key(locator: str) -> bytes:
    """Bytewise on the UTF-8 encoding of the locator.

    Not numeric-aware, so `WCF 10.1` sorts before `WCF 2.1`. A numeric-aware
    sort needs a locator grammar this file format does not have — the moment a
    locator is `Inst. 4.17.10` or `Gen 1:1`, "natural order" means a per-corpus
    parser living inside a corpus-agnostic format. The file's job is a diff
    that is stable across machines and locales; browsing it is not what it is
    for.
    """
    return locator.encode("utf-8")


def render(fingerprints: Mapping[str, str]) -> str:
    return "".join(
        f"{locator}{SEPARATOR}{fingerprints[locator]}\n"
        for locator in sorted(fingerprints, key=sort_key)
    )


def parse(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        locator, _, digest = line.rpartition(SEPARATOR)
        locator = locator.strip()
        digest = digest.strip()
        if not locator or not HASH.match(digest):
            raise AcquisitionError(
                f"fingerprints line {number}: expected '<locator>{SEPARATOR}<sha256>'"
            )
        if locator in parsed:
            raise AcquisitionError(
                f"fingerprints line {number}: {locator!r} appears twice — a locator "
                "resolves to exactly one chunk (verification check 1)"
            )
        parsed[locator] = digest
    return parsed


def read(path: pathlib.Path) -> dict[str, str] | None:
    """The committed fingerprints, or None when the corpus has never been blessed."""
    if not path.exists():
        return None
    return parse(path.read_text(encoding="utf-8"))


def write(path: pathlib.Path, fingerprints: Mapping[str, str]) -> None:
    write_text(path, render(fingerprints))


@dataclass(frozen=True)
class Diff:
    """The three classes, always reported together.

    Never one at a time: a run that short-circuits on the first missing locator
    hides the mismatches behind it, and the shape of the whole diff is what says
    whether the source moved a section or changed a word.
    """

    missing: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.missing or self.unexpected or self.mismatched)

    def summary(self) -> list[str]:
        """Counts, plus a bounded sample of locators only. Never text."""
        lines = []
        for label, locators, gloss in (
            ("missing", self.missing, "committed, not acquired"),
            ("unexpected", self.unexpected, "acquired, not committed"),
            ("mismatched", self.mismatched, "committed and acquired, different hash"),
        ):
            lines.append(f"  {label}: {len(locators)} ({gloss})")
            for locator in locators[:SAMPLE]:
                lines.append(f"      {locator}")
            if len(locators) > SAMPLE:
                lines.append(f"      … and {len(locators) - SAMPLE} more")
        return lines


def compare(committed: Mapping[str, str], acquired: Mapping[str, str]) -> Diff:
    return Diff(
        missing=sorted((committed.keys() - acquired.keys()), key=sort_key),
        unexpected=sorted((acquired.keys() - committed.keys()), key=sort_key),
        mismatched=sorted(
            (
                locator
                for locator in committed.keys() & acquired.keys()
                if committed[locator] != acquired[locator]
            ),
            key=sort_key,
        ),
    )
