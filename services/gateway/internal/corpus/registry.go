// Package corpus reads the corpus tables the gateway is allowed to read.
//
// The gateway role is read-only on everything in the `corpus` schema, and that
// is deliberate: Catena owns those tables. Nothing here writes.
package corpus

import (
	"context"
	"database/sql"
	"fmt"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// Registry answers whether a corpus is ingested. It is the database-backed
// implementation of the interface the profile loader takes, and it exists so
// that a profile naming a corpus nobody ingested fails at load rather than at
// the first citation nobody can resolve.
type Registry struct {
	db *sql.DB
}

// Open connects to Postgres. It does not verify the connection: the first
// query does, and a registry that dials eagerly turns every unit test that
// constructs one into an integration test.
func Open(dsn string) (*Registry, error) {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, fmt.Errorf("open corpus registry: %w", err)
	}
	return &Registry{db: db}, nil
}

// Close releases the pool.
func (r *Registry) Close() error {
	return r.db.Close()
}

// Exists reports whether any chunk carries this corpus ID.
//
// It asks `chunk_metadata` rather than `chunks` or `works`, and the choice is
// the whole point of the check. Ingestion commits in two phases — text, then
// embeddings — so a corpus interrupted between them has rows in `chunks` and
// no vectors, and `chunk_metadata` inner-joins the vectors precisely so that
// nothing half-ingested reaches the gateway's read surface. Asking `chunks`
// would load such a corpus into the filter spec and turn a refusal at load
// into a thin answer at query time.
//
// The view returns a row per chunk per embedding model during a re-index, which
// EXISTS does not care about.
func (r *Registry) Exists(ctx context.Context, corpusID string) (bool, error) {
	var exists bool
	err := r.db.QueryRowContext(ctx,
		`SELECT EXISTS (SELECT 1 FROM corpus.chunk_metadata WHERE corpus_id = $1)`,
		corpusID).Scan(&exists)
	if err != nil {
		return false, fmt.Errorf("corpus registry: %w", err)
	}
	return exists, nil
}
