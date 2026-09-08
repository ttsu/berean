"""BGE-M3, in-process from `/models/`.

Not served by Ollama: Ollama's `bge-m3` exposes dense vectors only, and the
learned sparse representation is the one advantage the model was chosen for
(TECHNICAL-SPEC, ADR-0006). Phase 1 stores the dense vector alone — dense-only
top-k is the requirement — and loading the real model here is what keeps the
sparse half available to Phase 3 without a second acquisition of weights.

About 2.3 GB, loaded once per invocation regardless of backlog size. That is
what makes the marginal cost of resuming fixed and small against a multi-hour
run, and why there is no argument here for large batches: bound the crash loss,
because the restart is cheap.
"""

from __future__ import annotations

import os
import pathlib
from typing import Sequence

from catena.ingest import IngestionError

MODELS_DIR_ENV = "CATENA_MODELS_DIR"

#: Written to `corpus.chunk_embeddings.embedding_model`, and the predicate the
#: resume query and retrieval both filter on. Not a path and not a version — a
#: model identity, stable across re-provisioning of the same weights.
MODEL_NAME = "bge-m3"

#: The column type is `extensions.vector(1024)`, so this is asserted rather than
#: discovered: a model of another width is a migration, not a re-index.
DIM = 1024

DIRNAME = "bge-m3"


def load(models_dir: pathlib.Path | None = None) -> "BgeM3Embedder":
    """Load the pinned weights. Raises rather than downloading anything."""
    root = models_dir or pathlib.Path(os.environ.get(MODELS_DIR_ENV, "/models"))
    path = root / DIRNAME
    if not (path / "config.json").is_file():
        raise IngestionError(
            f"no BGE-M3 weights at {path}. Weights are pinned and mounted, never baked "
            "into the image or fetched at run time — run `make provision-models`."
        )

    try:
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as error:  # pragma: no cover - a broken image
        raise IngestionError(
            "sentence-transformers is not installed. Ingestion runs in the catena "
            "image, which installs it from the lockfile — run it through `make ingest`."
        ) from error

    # `local_files_only` so a missing file is an error here rather than a silent
    # download from the Hub: the acceptance test is `docker compose up` with no
    # external accounts, and a run that reaches the network for weights has
    # already broken it.
    model = SentenceTransformer(str(path), local_files_only=True)
    return BgeM3Embedder(model)


class BgeM3Embedder:
    def __init__(self, model) -> None:
        self._model = model
        self.name = MODEL_NAME
        self.dim = DIM
        # From the model's own `sentence_bert_config.json` rather than a
        # constant here. A longer chunk does not fail — the encoder truncates
        # and returns a vector, and nothing downstream can tell — so the plan
        # refuses on this number and the value has to be the model's.
        self.max_tokens = int(model.max_seq_length)

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        """Token counts under BGE-M3's own tokeniser, never an estimate.

        Special tokens included, because they occupy the window too. Unpadded:
        the caller wants each sequence's own length, and padding would report
        the longest one for every text.
        """
        encoded = self._model.tokenizer(
            list(texts), add_special_tokens=True, padding=False, truncation=False
        )
        return [len(ids) for ids in encoded["input_ids"]]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, L2-normalised, in the order given.

        `batch_size` is the whole batch: the caller already filled it to a token
        budget and owns the commit boundary, so letting `encode` re-batch
        underneath would give back the granularity that batching exists to take.

        Normalised because the HNSW index is `vector_cosine_ops`.
        """
        vectors = self._model.encode(
            list(texts),
            batch_size=len(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [[float(component) for component in vector] for vector in vectors]
