// Live-database assertions for the corpus registry.
//
// A fake cannot answer the question this package exists to ask. `Exists` is
// one SQL statement against tables the gateway role is deliberately read-only
// on, so what is being tested is the statement, the schema qualification, and
// the grant — none of which a map can be wrong about.
//
// Skipped when BEREAN_DATABASE_URL is unset, exactly as the Python ingestion
// suite skips without CATENA_DATABASE_URL. Run it with `make test-gateway-db`.
package corpus_test

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"os"
	"testing"

	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/ttsu/berean/services/gateway/internal/corpus"
	"github.com/ttsu/berean/services/gateway/internal/profile"
)

func registry(t *testing.T) *corpus.Registry {
	t.Helper()
	dsn := os.Getenv("BEREAN_DATABASE_URL")
	if dsn == "" {
		t.Skip("BEREAN_DATABASE_URL unset; run `make test-gateway-db` against a live database")
	}
	reg, err := corpus.Open(dsn)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { reg.Close() })
	return reg
}

func TestExistsFindsAnIngestedCorpus(t *testing.T) {
	reg := registry(t)

	exists, err := reg.Exists(context.Background(), "wcf-1788-american")
	if err != nil {
		t.Fatalf("Exists: %v", err)
	}
	if !exists {
		t.Error("wcf-1788-american: exists = false, want true — the Phase 1 corpus is ingested")
	}
}

func TestExistsDoesNotFindACorpusThatWasNeverIngested(t *testing.T) {
	reg := registry(t)

	// A bare work ID is the mistake the edition-specific rule exists to catch,
	// so it is the right thing to be absent.
	exists, err := reg.Exists(context.Background(), "wcf")
	if err != nil {
		t.Fatalf("Exists: %v", err)
	}
	if exists {
		t.Error(`"wcf": exists = true, want false`)
	}
}

// The committed profile is only honest if every corpus it names is really in
// the database. Against a fake this is a tautology; against Postgres it is the
// check that ADR-0015 rests on.
func TestTheCommittedPCAProfileLoadsAgainstTheDatabase(t *testing.T) {
	reg := registry(t)

	if _, err := profile.LoadFile(context.Background(), "../../../../profiles/pca.yaml", reg); err != nil {
		t.Fatalf("LoadFile: %v", err)
	}
}

// Ingestion commits in two phases: text first, embeddings second (see
// services/catena/src/catena/ingest/apply.py). A corpus interrupted between
// them has rows in `corpus.chunks` and none in `corpus.chunk_embeddings`, and
// it retrieves nothing — `corpus.chunk_metadata` inner-joins the vectors, so
// nothing half-ingested reaches the gateway's read surface at all.
//
// A registry that answered from `chunks` would load such a corpus into the
// filter spec and turn a load-time refusal into a thin answer at query time,
// which is the failure this check exists to prevent.
func TestExistsIgnoresACorpusWhoseEmbeddingsNeverLanded(t *testing.T) {
	reg := registry(t)
	const corpusID = "half-ingested-fixture"
	// Invented text, never corpus text (ADR-0014), and hashed here rather than
	// pasted so the fixture cannot drift from its own fingerprint.
	const invented = "A fixture sentence that no tradition has ever confessed."
	sum := sha256.Sum256([]byte(invented))

	writer := ingestion(t)
	t.Cleanup(func() {
		if _, err := writer.Exec(`DELETE FROM corpus.works WHERE corpus_id = $1`, corpusID); err != nil {
			t.Errorf("cleanup: %v", err)
		}
	})
	if _, err := writer.Exec(
		`INSERT INTO corpus.works
		    (corpus_id, work, era, language, source_language, text_form, edition, license, attribution)
		 VALUES ($1, 'Fixture', 'test', 'en', 'en', 'not-applicable', 'test', 'public-domain', 'invented for this test')`,
		corpusID); err != nil {
		t.Fatalf("insert work: %v", err)
	}
	if _, err := writer.Exec(
		`INSERT INTO corpus.chunks (corpus_id, locator, text, content_hash, normalisation_version)
		 VALUES ($1, 'Fixture 1', $2, $3, 1)`,
		corpusID, invented, hex.EncodeToString(sum[:])); err != nil {
		t.Fatalf("insert chunk: %v", err)
	}

	exists, err := reg.Exists(context.Background(), corpusID)
	if err != nil {
		t.Fatalf("Exists: %v", err)
	}
	if exists {
		t.Error("exists = true for a corpus whose text landed and whose vectors did not: " +
			"it would ship in the filter spec and retrieve nothing")
	}
}

// A second connection, as the role that owns the corpus tables. The gateway
// role is read-only on them, deliberately, so the fixture cannot be written
// through the registry under test.
func ingestion(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("CATENA_DATABASE_URL")
	if dsn == "" {
		t.Skip("CATENA_DATABASE_URL unset; run `make test-gateway-db` against a live database")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open ingestion connection: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}
