"""pgvector's text form, which both the batch path and the request path need.

Ingestion writes vectors and retrieval compares against them, so this belongs
to neither module. It is written by hand rather than through pgvector's own
psycopg adapter, which would be a dependency for one string.
"""

from __future__ import annotations

from typing import Sequence


def literal(vector: Sequence[float]) -> str:
    """A vector as pgvector parses it.

    `repr` of a Python float round-trips exactly, and the values arrive as
    float32 from the encoder, so nothing is lost on the way to the database.
    """
    return "[" + ",".join(repr(float(component)) for component in vector) + "]"
