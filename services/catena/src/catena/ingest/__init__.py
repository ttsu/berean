"""Corpus ingestion: make the database agree with the blessed staging directory.

Ingestion reads the staged records acquisition ended at, enriches, embeds, and
loads. It never parses an upstream format, never touches the network, and never
decides what a chunk is.

A database that is behind staging is behind staging, and it does not matter
why. A killed run, a re-bless under a corrected parser, a fresh clone, a
half-applied migration all produce the same disagreement, and one diff resolves
all of them — so there is no recovery path separate from the normal path.

See specs/001-phase-1-pca-baseline/INGESTION-DESIGN.md.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Ingestion stopped rather than making the database disagree with staging."""
