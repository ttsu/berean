"""`CatenaService.Answer` — the one call, end to end.

Retrieve, generate, return. One model call per invocation, and Go invokes this
at most twice a turn (ADR-0002, ADR-0010). No LangGraph: TECHNICAL-SPEC defers
it to Phase 5 with the instruction to hit the wall first, and a linear path this
short would only be obscured by a graph.

**This service does not launder its own output.** The model's answer is parsed
into `AnswerObject` and returned as it came. If it flags a locus contested and
emits arguments anyway, that goes to Go and fails there — ADR-0019 says so
explicitly, and PLAN Task 7 calls the resulting regeneration "the intended
direction". Repairing it here would make the check unfireable and the failure
rate unmeasurable, which is exactly the measurement Phase 2 needs. The one thing
that cannot arrive is `confidence`, and that is handled by its absence from the
decoding schema rather than by scrubbing it afterwards (ADR-0020).
"""

from __future__ import annotations

import time
from typing import Any, Sequence

import grpc
from google.protobuf import json_format

from berean.v1 import answer_pb2, catena_pb2, catena_pb2_grpc, filter_pb2, trace_pb2
from catena.serve import ServeError, prompt, retrieval, schema

#: INTEGRATION-SPEC's default. Go configures `top_k` and `--top-k` overrides it,
#: so this is the floor for a request that carried none — a zero would retrieve
#: nothing and read as an empty corpus.
DEFAULT_TOP_K = 20

#: 1 on the first call, 2 on the regeneration. Nothing else is valid (ADR-0010).
VALID_ATTEMPTS = (1, 2)


class CatenaService(catena_pb2_grpc.CatenaServiceServicer):
    def __init__(self, embedder, generator, store_factory, observability) -> None:
        self._embedder = embedder
        self._generator = generator
        #: A context manager yielding a `CorpusStore`. One connection per
        #: request, closed however the request ends.
        self._store_factory = store_factory
        self._observability = observability

    def Answer(self, request: catena_pb2.AnswerRequest, context) -> catena_pb2.AnswerResponse:
        try:
            return self._answer(request)
        except ServeError as error:
            # Go owns what the user sees. A failed generation attempt is not a
            # degraded answer — degradation is a decision the trust boundary
            # makes after verification, and inventing one here would take it.
            context.abort(grpc.StatusCode.INTERNAL, str(error))
        except Exception as error:  # pragma: no cover - defensive
            context.abort(grpc.StatusCode.INTERNAL, f"catena failed: {error}")

    def _answer(self, request: catena_pb2.AnswerRequest) -> catena_pb2.AnswerResponse:
        attempt = request.attempt or 1
        if attempt not in VALID_ATTEMPTS:
            raise ServeError(
                f"attempt {attempt} is not valid; ADR-0010 fixes the retry at exactly "
                "one regeneration, so only 1 and 2 exist"
            )

        spec = request.filter_spec
        corpus_ids = [entry.corpus_id for entry in spec.corpora]
        if not corpus_ids:
            raise ServeError(
                "the filter spec names no corpora; there is nothing this request could "
                "cite, and an answer with no citable source is not one"
            )
        top_k = spec.top_k or DEFAULT_TOP_K

        with self._observability.request(
            request_id=request.request_id, query=request.query, attempt=attempt
        ) as span:
            embed_ms, vector = _timed(lambda: self._embedder.embed([request.query])[0])

            search_ms, (hits, pinned) = _timed(
                lambda: self._retrieve(vector, corpus_ids, top_k, request.contested_loci)
            )
            selection = retrieval.select(hits, spec, pinned=pinned)

            messages = prompt.build(
                query=request.query,
                passages=selection.passages,
                spec=spec,
                contested_loci=list(request.contested_loci),
                previous_failures=list(request.previous_failures),
                answer_failures=list(request.answer_failures),
                attempt=attempt,
            )

            with span.generation(model=self._generator.model, messages=messages) as observed:
                generate_ms, generation = _timed(
                    lambda: self._generator.generate(messages, schema.answer_schema())
                )
                observed.finish(
                    output=generation.payload,
                    usage={"input": generation.prompt_tokens,
                           "output": generation.completion_tokens},
                )

        return catena_pb2.AnswerResponse(
            answer=_parse(generation.payload),
            trace=trace_pb2.RetrievalTrace(
                # Phase 1 has no query rewriting, so this is the query. The
                # field exists so Phase 3 adds behaviour rather than breaking
                # the contract.
                rewritten_query=request.query,
                candidates=[trace_pb2.Candidate(**c) for c in selection.candidates],
                embedding_model=self._embedder.name,
                dim=self._embedder.dim,
                generation_model=generation.model,
                # The value actually used, never the configured default: with
                # Scripture at ~90% of the index and no tier weighting, this is
                # the only thing deciding whether a confessional chunk reached
                # the generator at all.
                top_k=top_k,
                timings=trace_pb2.Timings(
                    embed_ms=embed_ms, search_ms=search_ms, generate_ms=generate_ms
                ),
            ),
        )

    def _retrieve(
        self,
        vector: Sequence[float],
        corpus_ids: Sequence[str],
        top_k: int,
        contested_loci: Sequence[filter_pb2.ContestedLocus],
    ) -> tuple[list[retrieval.Hit], list[retrieval.Hit]]:
        """Ordinary top-k, plus each sent locus's ruling resolved by its pointer.

        Go sends a pointer and never the prose: Python owns retrieval, Go owns
        verification, and having Go fetch chunk text to build a request would
        invert that (ADR-0015). A ruling that does not resolve is dropped rather
        than fatal — the corpus may not be ingested, and Go's own load-time
        check is what refuses that case honestly.
        """
        with self._store_factory() as store:
            hits = store.search(vector, corpus_ids, top_k, self._embedder.name)
            pinned = []
            for locus in contested_loci:
                if not locus.ruling.corpus_id or not locus.ruling.locator:
                    continue
                ruling = store.by_locator(
                    locus.ruling.corpus_id, locus.ruling.locator, vector, self._embedder.name
                )
                if ruling is not None:
                    pinned.append(ruling)
        return hits, pinned


def _parse(payload: dict[str, Any]) -> answer_pb2.AnswerObject:
    """The model's JSON as an `AnswerObject`, unedited.

    Strict about unknown fields, which is what turns the schema's
    `additionalProperties: false` into an enforced guarantee on this side too:
    a `reasoning` key arriving anyway is a parse failure rather than something
    silently dropped.

    `confidence` needs its own check, because it is a *known* field — it is part
    of `AnswerObject` and Go fills it in — so the parser would accept it
    happily. It cannot reach here: the decoding schema omits it, which is what
    makes it unpopulatable rather than merely unpopulated. Its arrival therefore
    means `schema.py` stopped subtracting it, and that is a defect worth a loud
    failure rather than a quiet `ClearField` that would leave the derivation
    broken and every answer looking correct (ADR-0020).
    """
    if "confidence" in payload:
        raise ServeError(
            "the generation carried `confidence`, which the decoding schema omits. "
            "Go derives both halves from the verification result (ADR-0020), so this "
            "means the schema derivation stopped subtracting the field"
        )
    try:
        return json_format.ParseDict(payload, answer_pb2.AnswerObject())
    except json_format.ParseError as error:
        raise ServeError(
            f"the generation did not parse as an AnswerObject: {error}"
        ) from error


def _timed(work):
    started = time.monotonic()
    result = work()
    return int((time.monotonic() - started) * 1000), result
