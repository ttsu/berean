"""Reading acquired corpora back: the inspection half of the acquisition seam.

`catena browse` serves the staged output of `catena acquire` as a local web
page -- the text as ingestion will load it, where the segmenter cut it, and what
normalisation did to it.

This is a developer tool, not the product's answer surface. See
`services/catena/src/catena/browse/server.py` for why that distinction is load
bearing.
"""

from catena.browse.staged import Chunk, Corpus, discover, load, text_withheld_reason

__all__ = ["Chunk", "Corpus", "discover", "load", "text_withheld_reason"]
