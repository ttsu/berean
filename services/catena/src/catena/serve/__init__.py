"""The request path: retrieve, generate, answer. Codename Catena.

Everything here is untrusted output. The gateway verifies every citation this
package emits against the database, so a plausible-looking citation is worse
than none — it fails verification and costs a regeneration (ADR-0010).

Three rules shape the whole package and none of them are local decisions:

* **No profile crosses the boundary.** A `FilterSpec` arrives, and it is a
  search policy rather than an identity. Nothing here learns which tradition
  asked (ADR-0015).
* **Nothing describes the model's own reasoning.** The generator is a thinking
  model and its thinking is discarded unread, never stored and never returned
  (CLAUDE.md constraint 5, ADR-0003).
* **`confidence` is Go's.** It is absent from the schema the decoder is
  constrained to, so it is unpopulatable rather than merely unpopulated
  (ADR-0020).

Phase 1 is deliberately naive: dense-only top-k, no reranking, no BM25, no
query rewriting, and no LangGraph — Phase 2 measures this baseline and Phase 3
has to beat it (TECHNICAL-SPEC, "Retrieval — deliberately naive").
"""

from __future__ import annotations


class ServeError(Exception):
    """The request could not be served. Go owns what the user sees."""
