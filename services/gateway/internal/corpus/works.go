package corpus

import (
	"context"
	"fmt"
)

// Work is how a corpus describes itself to a reader.
//
// It carries no tier and no label. Tier is a per-tradition stance held by the
// resolved profile, and the label is the profile's own words — neither is a
// property of the corpus, and a struct carrying all four would be the place
// the two ideas got confused.
type Work struct {
	CorpusID string
	// The work itself: "The Westminster Confession of Faith".
	Work string
	// What distinguishes this corpus from every other edition of that work:
	// "1788 American revision". UC-3 is a correctness claim about exactly this
	// field, and a corpus ID states it only to a reader who already knows the
	// naming convention.
	Edition string
}

// Works describes each of the given corpora.
//
// Corpora that name no row are omitted rather than reported. Every ID reaching
// this reader has already been through verification, which fails any citation
// to a corpus outside the sent FilterSpec, and the profile loader has already
// refused to start against a corpus that is not ingested — so an absent row
// means a corpus dropped between those checks and this read, and the honest
// rendering of that is the corpus ID the citation actually carries. Failing the
// whole turn here would discard an answer whose every citation verified, over a
// description.
//
// One statement rather than one per citation: an answer citing eight passages
// from three corpora would otherwise make eight lookups for three rows, on the
// render path of a turn that has already spent minutes generating.
func (r *Registry) Works(ctx context.Context, corpusIDs []string) (map[string]Work, error) {
	works := make(map[string]Work, len(corpusIDs))
	if len(corpusIDs) == 0 {
		return works, nil
	}

	rows, err := r.db.QueryContext(ctx,
		`SELECT corpus_id, work, edition
		   FROM corpus.works
		  WHERE corpus_id = ANY($1)`,
		corpusIDs)
	if err != nil {
		return nil, fmt.Errorf("corpus works: %w", err)
	}
	defer rows.Close()

	for rows.Next() {
		var w Work
		if err := rows.Scan(&w.CorpusID, &w.Work, &w.Edition); err != nil {
			return nil, fmt.Errorf("corpus works: %w", err)
		}
		works[w.CorpusID] = w
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("corpus works: %w", err)
	}
	return works, nil
}
