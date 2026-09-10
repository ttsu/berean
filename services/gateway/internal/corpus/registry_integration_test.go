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
	"os"
	"testing"

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
