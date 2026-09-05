"""Per-corpus adapters, one module each.

The module name is the corpus ID with hyphens replaced by underscores, because
`wcf-1788-american` is not an importable module name and the corpus ID is
edition-specific and therefore not negotiable.

Adapters live here rather than under `tools/` for three reasons, and the first
is fatal on its own: the catena image copies only `services/catena/src`, so a
script under `tools/` is not present in the container `make provision-corpus`
runs. A hyphenated filename is not importable. And an adapter imports
`catena.normalise` and the pipeline's types, which makes it package code, where
everything under `tools/` is host-side operational scripting the service never
imports.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from catena.acquire.pipeline import Adapter

#: Registered corpora, in acquisition order. Enumerated rather than discovered
#: by scanning the package: `--all` is what `make provision-corpus` runs, and a
#: corpus that appears in the set because a file was dropped in a directory is a
#: corpus nobody reviewed.
CORPUS_IDS = (
    "wcf-1788-american",
    "wlc-1788-american",
    "wsc-1788-american",
    "calvin-institutes-1559-beveridge",
    "wcf-1646-epcew-modernised",
    "pca-ga28-2000-creation-study",
    "web-2020",
    "pca-bco-2026",
)


def module_name(corpus_id: str) -> str:
    return f"catena.acquire.corpora.{corpus_id.replace('-', '_')}"


def load(corpus_id: str) -> "Adapter":
    if corpus_id not in CORPUS_IDS:
        known = ", ".join(CORPUS_IDS)
        raise KeyError(f"unknown corpus {corpus_id!r}; registered: {known}")
    try:
        adapter = importlib.import_module(module_name(corpus_id))
    except ImportError as error:
        raise ValueError(
            f"{corpus_id} is registered in CORPUS_IDS but {module_name(corpus_id)} "
            f"does not import: {error}"
        ) from error
    if adapter.corpus_id != corpus_id:
        raise ValueError(
            f"{module_name(corpus_id)} declares corpus_id {adapter.corpus_id!r}, "
            f"registered as {corpus_id!r}"
        )
    return adapter  # type: ignore[return-value]


def load_all() -> list["Adapter"]:
    return [load(corpus_id) for corpus_id in CORPUS_IDS]
