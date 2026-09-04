"""Corpus acquisition — fetch, extract, segment, normalise, verify, stage.

The repository carries no corpus text (ADR-0014). It carries evidence *about*
text: a manifest, a fingerprint file, and the code that reconstructs the text
from an upstream source. Acquisition is what turns an upstream document into
staged records whose per-chunk hashes match what a human once verified by hand.

Acquisition is messy, one-time, and human-supervised; ingestion is
deterministic and repeatable. The seam between them is a directory of staged
records under `/data`, and ingestion never crosses back over it to parse an
upstream format or touch the network.
"""

from __future__ import annotations

from catena.acquire.record import (
    AcquisitionError,
    Segment,
    StagedRecord,
    WorkFacts,
)

__all__ = ["AcquisitionError", "Segment", "StagedRecord", "WorkFacts"]
