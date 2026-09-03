-- Corpus tables. Catena writes them; the gateway reads them and never the
-- reverse (SHARED §5). Owned by berean_owner, which neither service
-- authenticates as, so the disjoint write scope is a grant rather than a
-- convention.
--
-- Everything is schema-qualified, including `extensions.vector`. The migration
-- runs with `search_path=migration` so the tool's version table lands where it
-- should, which means nothing here may rely on a path.

-- The chunk metadata contract names a set of fields carried by every chunk.
-- They are stored where they are true rather than repeated on every row: most
-- describe the work, two describe an embedding, and only `corpus_id` and
-- `locator` belong to the chunk itself. `corpus.chunk_metadata` at the bottom
-- of this file puts them back together, so the contract's read surface is
-- unchanged while each fact has one place to be wrong.

-- `license` and `text_form` are enums so their domains are closed. A free-text
-- licence reduces verification check 4 to "the string is non-empty", which is a
-- check that reports success while evaluating nothing (ADR-0017). The same
-- argument gives `text_form` four values including `not-applicable`, rather
-- than five improvised spellings of "this is not Scripture".
CREATE TYPE corpus.license AS ENUM (
    'public-domain',
    'cc-by',
    'cc-by-sa',
    -- Acquired lawfully by the deployer for local use, with no redistribution
    -- claim made or available. Servable only under an explicit deployer opt-in;
    -- the default is deny, so nobody ships PCA text by accident (ADR-0017).
    'local-only',
    -- Examined and rejected. Never servable under any configuration. It exists
    -- so a corpus can be recorded as refused rather than merely absent, which
    -- keeps the reason available the next time someone asks.
    'refused'
);

CREATE TYPE corpus.text_form AS ENUM ('tr', 'critical', 'majority', 'not-applicable');

-- One row per corpus, and a corpus is an edition.
CREATE TABLE corpus.works (
    -- Edition-specific, always. The check rejects the bare `wcf` form that
    -- CLAUDE.md calls a bug; it cannot prove the remaining segments name an
    -- edition, and nothing in a database can. The manifest's `edition_check`
    -- and its human verifier are what establish that (ADR-0014).
    corpus_id text PRIMARY KEY
        CONSTRAINT works_corpus_id_not_bare
        CHECK (corpus_id ~ '^[a-z0-9]+(-[a-z0-9]+)+$'),

    work text NOT NULL CHECK (btrim(work) <> ''),
    -- The only nullable field in the contract: most of the Phase 1 corpus is
    -- corporate. NULL means "no author"; the check keeps the empty string from
    -- becoming a second way to say it.
    author text CHECK (author IS NULL OR btrim(author) <> ''),
    era text NOT NULL CHECK (btrim(era) <> ''),
    -- No originating-tradition column, deliberately. Which traditions hold a
    -- corpus, and how authoritatively, is the profile's N:M relation, and it is
    -- the one anybody actually means. Origination is a different and weaker
    -- claim, and it is unstatable for the two cases that matter most here:
    -- Scripture, which is ~90% of the index, and the ecumenical creeds, which
    -- every tradition claims as its own rather than as someone else's. See
    -- INTEGRATION-SPEC, "Chunk metadata contract".

    -- The language of the text as ingested; `en` for a translation.
    language text NOT NULL CHECK (language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
    -- The language of the work itself; `la` for the Institutes, and equal to
    -- `language` for an untranslated work. Split because one column carrying
    -- both means different things per row, and backfilling either means
    -- re-ingesting (ADR-0008).
    source_language text NOT NULL CHECK (source_language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),

    text_form corpus.text_form NOT NULL,
    -- What makes wcf-1788-american distinguishable from wcf-1646-original.
    edition text NOT NULL CHECK (btrim(edition) <> ''),

    license corpus.license NOT NULL,
    -- Drives mechanical generation of the attribution page, so an empty string
    -- is a missing attribution wearing a value's clothes.
    attribution text NOT NULL CHECK (btrim(attribution) <> ''),

    ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE corpus.chunks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    corpus_id text NOT NULL REFERENCES corpus.works (corpus_id) ON DELETE CASCADE,
    -- Canonical, resolvable, stable: `WCF 7.2`, `WSC Q&A 1`, `BCO 21-4`.
    locator text NOT NULL CHECK (btrim(locator) <> ''),

    -- Normalised at ingestion, per the normalisation contract. Verification
    -- substring-matches a quote against exactly this text, so what is stored is
    -- post-normalisation text and nothing else — storing the raw text beside it
    -- would give the check two candidates and no rule for choosing.
    text text NOT NULL CHECK (btrim(text) <> ''),

    -- sha256 of `text`, lowercase hex, the same value written into
    -- corpora/<corpus-id>/fingerprints.txt. Ingestion is idempotent on it.
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),

    -- Which version of the normalisation contract produced `text` and its hash.
    -- Not in the metadata contract, and recorded anyway: the hashes are over
    -- post-normalisation text, so a corpus ingested under one version and
    -- queried by a gateway running another produces quote-match failures on
    -- visually identical text. That is the symptom the contract exists to
    -- prevent and the one the spec calls extremely annoying to diagnose; this
    -- column is what makes it a lookup instead of an investigation.
    normalisation_version smallint NOT NULL CHECK (normalisation_version > 0),

    -- Check 1 is "{corpus_id, locator} resolves to exactly one chunk". That is
    -- a database constraint or it is a race, because two rows make the check
    -- ambiguous and no amount of care in Go notices.
    CONSTRAINT chunks_corpus_locator_unique UNIQUE (corpus_id, locator)
);

-- Ingestion is idempotent keyed on the per-chunk hash, so the re-run asks this
-- question once per chunk.
CREATE INDEX chunks_content_hash_idx ON corpus.chunks (content_hash);

CREATE TABLE corpus.chunk_embeddings (
    chunk_id bigint NOT NULL REFERENCES corpus.chunks (id) ON DELETE CASCADE,

    -- Keyed with chunk_id rather than replacing per chunk, so a re-index writes
    -- the new model's vectors beside the old ones and the swap is a change of
    -- which model retrieval asks for. That is what makes re-indexing a job
    -- rather than a migration (SHARED §10).
    embedding_model text NOT NULL CHECK (btrim(embedding_model) <> ''),

    -- 1024 is BGE-M3 (ADR-0006). The dimension is fixed in the column type
    -- because pgvector cannot index a vector of unconstrained width, so the
    -- index below — which is not optional — is what forces the choice. A model
    -- of the same width is a re-index; a model of a different width is a
    -- migration, and no schema over this extension avoids that.
    dim integer NOT NULL,
    embedding extensions.vector(1024) NOT NULL,

    -- `dim` is written into the trace, so it has to be the width that was
    -- actually stored rather than the width the caller believed it was storing.
    CONSTRAINT chunk_embeddings_dim_matches_vector
        CHECK (dim = extensions.vector_dims(embedding)),

    PRIMARY KEY (chunk_id, embedding_model)
);

-- HNSW rather than IVFFlat: IVFFlat's lists are trained from the rows present
-- when the index is built, and this index is built by a migration against an
-- empty table. Cosine distance, matching normalised BGE-M3 vectors.
--
-- One index over all models. Retrieval MUST filter on `embedding_model` — with
-- two models present the index spans two vector spaces, and HNSW post-filters,
-- so a re-index window trades recall until the old rows are dropped. Phase 1
-- has one model; if that stops being true, partitioning this table by model is
-- the fix, not a second index.
CREATE INDEX chunk_embeddings_hnsw_cosine_idx
    ON corpus.chunk_embeddings USING hnsw (embedding extensions.vector_cosine_ops);

-- The chunk metadata contract, as a read surface: every field it names, none of
-- them null. The join to chunk_embeddings is inner on purpose — a chunk with no
-- embedding has no `embedding_model` and no `dim`, so it does not yet carry the
-- whole contract, and it is a half-finished ingestion rather than a row this
-- view should paper over.
--
-- Keyed on `(chunk_id, embedding_model)`, not on `chunk_id`. Two of the fields
-- describe an embedding, and chunk_embeddings deliberately holds a row
-- per model so a re-index can write the new vectors beside the old ones — so
-- during a re-index window this view returns one row per chunk per model, and a
-- consumer reading it as one-row-per-chunk double counts. Constrain
-- `embedding_model`, which is the rule retrieval already follows for the single
-- HNSW index above, and for the same underlying reason.
CREATE VIEW corpus.chunk_metadata AS
SELECT c.id AS chunk_id,
       w.corpus_id,
       w.work,
       w.author,
       w.era,
       c.locator,
       w.language,
       w.source_language,
       w.text_form,
       w.edition,
       w.license,
       w.attribution,
       e.embedding_model,
       e.dim
  FROM corpus.chunks c
  JOIN corpus.works w USING (corpus_id)
  JOIN corpus.chunk_embeddings e ON e.chunk_id = c.id;

-- Re-asserted rather than left to the ALTER DEFAULT PRIVILEGES in the init
-- script, because a default privilege that silently did not apply is
-- indistinguishable from one that did.
GRANT SELECT, INSERT, UPDATE, DELETE
    ON corpus.works, corpus.chunks, corpus.chunk_embeddings TO catena;
GRANT SELECT ON corpus.chunk_metadata TO catena;

-- Read-only, deliberately, and not to be worked around
-- (services/gateway/AGENTS.md).
GRANT SELECT
    ON corpus.works, corpus.chunks, corpus.chunk_embeddings, corpus.chunk_metadata TO gateway;
