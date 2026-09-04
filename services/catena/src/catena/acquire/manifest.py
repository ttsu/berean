"""`corpora/<corpus-id>/manifest.yaml` — the committed provenance record.

The manifest is evidence about a corpus, never the corpus (ADR-0014). It says
where the bytes came from, under what terms, how many chunks the blessed text
segmented into, and — the field that carries the most weight — what a human
read at the edition diagnostic and approved.

`edition_check` records *that* a human verified the edition and *what they
verified against*, and commits none of the text (ADR-0021). `expected_sha256` is
the hash of the diagnostic locator's normalised text as the verifier read it; on
every run after, it asserts that what was acquired now still hashes to what was
approved then.

What replaces the quoted text is not a checkbox but a command —
`catena acquire --corpus <id> --show-diagnostic` prints the diagnostic locator's
text on demand, which is what the quoted text was for, without the repository
distributing it.

The hash is over **normalised** text, because normalised text is what is on disk
and what every other fingerprint in this system is taken over.
"""

from __future__ import annotations

import datetime
import pathlib
import re
from dataclasses import dataclass
from typing import Any

import yaml

from catena.acquire.record import LICENSES, AcquisitionError, write_text

FILENAME = "manifest.yaml"
FINGERPRINTS_FILENAME = "fingerprints.txt"

#: Edition-specific, always. `wcf` is a bug, not a shorthand — the same shape
#: `corpus.works` constrains.
CORPUS_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EditionCheck:
    diagnostic: str
    expected_sha256: str
    verified_by: str
    verified: str


@dataclass(frozen=True)
class Manifest:
    corpus_id: str
    source_url: str
    archive_url: str
    retrieved: str
    upstream_sha256: str
    license: str
    license_terms: str
    attribution: str
    normalisation_version: int
    chunk_count: int
    edition_check: EditionCheck

    def to_yaml(self) -> str:
        return _dump(
            {
                "corpus_id": self.corpus_id,
                "source_url": self.source_url,
                "archive_url": self.archive_url,
                "retrieved": self.retrieved,
                "upstream_sha256": self.upstream_sha256,
                "license": self.license,
                "license_terms": self.license_terms,
                "attribution": self.attribution,
                "normalisation_version": self.normalisation_version,
                "chunk_count": self.chunk_count,
                "edition_check": {
                    "diagnostic": self.edition_check.diagnostic,
                    "expected_sha256": self.edition_check.expected_sha256,
                    "verified_by": self.edition_check.verified_by,
                    "verified": self.edition_check.verified,
                },
            }
        )


_STRINGS = (
    "corpus_id",
    "source_url",
    "archive_url",
    "retrieved",
    "upstream_sha256",
    "license",
    "license_terms",
    "attribution",
)
_INTS = ("normalisation_version", "chunk_count")
_CHECK_FIELDS = ("diagnostic", "expected_sha256", "verified_by", "verified")


def parse(raw: Any, *, where: str = "manifest") -> Manifest:
    """Load a manifest, rejecting anything the contract does not name.

    Unknown keys are rejected rather than ignored. A misspelled field that
    loads clean is a provenance record with a hole in it, and the hole is
    invisible for exactly as long as nobody looks.
    """
    if not isinstance(raw, dict):
        raise AcquisitionError(f"{where}: expected a mapping")

    expected_keys = set(_STRINGS) | set(_INTS) | {"edition_check"}
    missing = expected_keys - raw.keys()
    if missing:
        raise AcquisitionError(f"{where}: missing required field(s) {sorted(missing)}")
    unknown = raw.keys() - expected_keys
    if unknown:
        raise AcquisitionError(f"{where}: unknown field(s) {sorted(unknown)}")

    for key in _STRINGS:
        value = raw[key]
        if not isinstance(value, str) or not value.strip():
            raise AcquisitionError(f"{where}: {key} must be a non-empty string")
    for key in _INTS:
        value = raw[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise AcquisitionError(f"{where}: {key} must be a positive integer")

    if not CORPUS_ID.match(raw["corpus_id"]):
        raise AcquisitionError(
            f"{where}: corpus_id {raw['corpus_id']!r} is not edition-specific — "
            "`wcf` is a bug, `wcf-1788-american` is the form"
        )
    if raw["license"] not in LICENSES:
        raise AcquisitionError(
            f"{where}: license {raw['license']!r} is not one of {sorted(LICENSES)} — "
            "the domain is closed (ADR-0017)"
        )
    if not _SHA256.match(raw["upstream_sha256"]):
        raise AcquisitionError(f"{where}: upstream_sha256 must be 64 lowercase hex characters")
    _require_date(raw["retrieved"], f"{where}: retrieved")

    check = raw["edition_check"]
    if not isinstance(check, dict):
        raise AcquisitionError(f"{where}: edition_check must be a mapping")
    check_missing = set(_CHECK_FIELDS) - check.keys()
    if check_missing:
        raise AcquisitionError(f"{where}: edition_check missing {sorted(check_missing)}")
    check_unknown = check.keys() - set(_CHECK_FIELDS)
    if check_unknown:
        raise AcquisitionError(
            f"{where}: edition_check has unknown field(s) {sorted(check_unknown)}"
        )
    for key in _CHECK_FIELDS:
        if not isinstance(check[key], str) or not check[key].strip():
            raise AcquisitionError(f"{where}: edition_check.{key} must be a non-empty string")
    if not _SHA256.match(check["expected_sha256"]):
        raise AcquisitionError(
            f"{where}: edition_check.expected_sha256 must be 64 lowercase hex characters. "
            "It is a hash of the diagnostic's normalised text and never the text itself "
            "(ADR-0021)"
        )
    _require_date(check["verified"], f"{where}: edition_check.verified")

    return Manifest(
        **{key: raw[key] for key in _STRINGS},
        **{key: raw[key] for key in _INTS},
        edition_check=EditionCheck(**{key: check[key] for key in _CHECK_FIELDS}),
    )


def read(path: pathlib.Path) -> Manifest | None:
    """The committed manifest, or None when the corpus has never been blessed."""
    if not path.exists():
        return None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise AcquisitionError(f"{path}: not valid YAML — {error}") from error
    return parse(loaded, where=str(path))


def write(path: pathlib.Path, manifest: Manifest) -> None:
    write_text(path, manifest.to_yaml())


def _require_date(value: str, where: str) -> None:
    if not _DATE.match(value):
        raise AcquisitionError(f"{where}: expected YYYY-MM-DD, got {value!r}")
    try:
        datetime.date.fromisoformat(value)
    except ValueError as error:
        raise AcquisitionError(f"{where}: {error}") from error


class _Dumper(yaml.SafeDumper):
    """A dumper that keeps the manifest reviewable.

    Two behaviours matter. Multi-line strings become literal blocks, because
    `license_terms` is terms quoted verbatim and a folded copy is no longer
    verbatim in any way a reader can check. And nothing is line-wrapped, so a
    one-word change to a long quote is a one-line diff.
    """


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _represent_str)


def _dump(payload: dict[str, Any]) -> str:
    return yaml.dump(
        payload,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1 << 30,
    )
