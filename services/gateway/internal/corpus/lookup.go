package corpus

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
)

// License is the `corpus.license` enum, mirrored as a closed set.
//
// Closed on both sides deliberately. A free-text licence reduces verification
// check 4 to "the string is non-empty", which is a check that reports success
// while evaluating nothing (ADR-0017) — and a Go type that accepts any string
// reopens on the read side what the database closed on the write side.
type License string

const (
	PublicDomain License = "public-domain"
	CCBY         License = "cc-by"
	CCBYSA       License = "cc-by-sa"
	// Acquired lawfully by the deployer for local use, with no redistribution
	// claim. Servable only under an explicit opt-in; the default is deny.
	LocalOnly License = "local-only"
	// Examined and rejected. Never servable under any configuration.
	Refused License = "refused"
)

// Known reports whether this is a licence the enum defines.
//
// A value from outside the set means the database grew a licence this build
// does not know, and the only safe reading of an unknown licence is that it
// does not permit serving. Check 4 fails closed on it.
func (l License) Known() bool {
	switch l {
	case PublicDomain, CCBY, CCBYSA, LocalOnly, Refused:
		return true
	}
	return false
}

// Chunk is what verification needs of a chunk, and nothing else.
//
// `Text` is post-normalisation text, because that is what ingestion stored:
// the quote check is exact substring containment against exactly this string,
// and a raw copy stored beside it would give the check two candidates and no
// rule for choosing.
type Chunk struct {
	CorpusID string
	Locator  string
	Text     string
	License  License
}

// ErrNotFound is what check 1 records: `{corpus_id, locator}` named no chunk.
//
// A sentinel rather than a bare `false`, so a caller that forgets to look at
// the boolean gets a nil Chunk it has to handle rather than an empty one it
// can quietly verify a quote against — an empty text would make every quote
// fail with the wrong reason.
var ErrNotFound = errors.New("no chunk carries that corpus ID and locator")

// Lookup resolves `{corpus_id, locator}` to exactly one chunk.
//
// "Exactly one" is a database constraint — `chunks_corpus_locator_unique` —
// rather than something asserted here, because two rows make check 1 ambiguous
// and no amount of care in Go notices a race it cannot see. This reads the
// `chunks` table directly rather than the `chunk_metadata` view: the view
// inner-joins the embeddings, which is right for the profile loader's "is this
// corpus ingested" question and wrong for this one. A chunk whose vector has
// not landed is still real text at a real locator, and refusing to resolve it
// would report a fabricated citation where the truth is a half-finished
// ingestion.
func (r *Registry) Lookup(ctx context.Context, corpusID, locator string) (Chunk, error) {
	chunk := Chunk{CorpusID: corpusID, Locator: locator}
	var license string
	err := r.db.QueryRowContext(ctx,
		`SELECT c.text, w.license
		   FROM corpus.chunks c
		   JOIN corpus.works w USING (corpus_id)
		  WHERE c.corpus_id = $1 AND c.locator = $2`,
		corpusID, locator).Scan(&chunk.Text, &license)
	switch {
	case errors.Is(err, sql.ErrNoRows):
		return Chunk{}, fmt.Errorf("%s %s: %w", corpusID, locator, ErrNotFound)
	case err != nil:
		return Chunk{}, fmt.Errorf("corpus lookup %s %s: %w", corpusID, locator, err)
	}
	chunk.License = License(license)
	return chunk, nil
}
