// Live-database assertions for the work descriptions a citation renders with.
//
// A fake would agree with whatever this package asked it for. What is under
// test is the statement — the schema qualification, the array parameter, and
// the grant on `corpus.works` — none of which a map can get wrong.
//
// Skipped when BEREAN_DATABASE_URL is unset. Run it with `make test-gateway-db`.
package corpus_test

import (
	"context"
	"testing"
)

// UC-3 is the reason this reader exists: a reader must be able to see that the
// answer came from the 1788 American revision rather than the 1646 original,
// and the corpus ID alone says that only to someone who already knows the
// naming convention.
func TestWorksDescribesTheEditionACitationCameFrom(t *testing.T) {
	reg := registry(t)

	works, err := reg.Works(context.Background(),
		[]string{"wcf-1788-american", "wcf-1646-epcew-modernised"})
	if err != nil {
		t.Fatalf("Works: %v", err)
	}

	american, ok := works["wcf-1788-american"]
	if !ok {
		t.Fatal("wcf-1788-american is missing from the result")
	}
	original, ok := works["wcf-1646-epcew-modernised"]
	if !ok {
		t.Fatal("wcf-1646-epcew-modernised is missing from the result")
	}

	if american.Work == "" || american.Edition == "" {
		t.Errorf("wcf-1788-american: work = %q, edition = %q; both are NOT NULL in the schema",
			american.Work, american.Edition)
	}
	// Two editions of one work. If their descriptions matched, the render
	// would carry the whole of UC-3's distinction in a corpus ID nobody reads.
	if american.Edition == original.Edition {
		t.Errorf("both editions describe themselves as %q; the render cannot distinguish them",
			american.Edition)
	}
}

// A citation only reaches the renderer once verification has accepted it, so
// its corpus is in scope by construction. An ID that names no row is therefore
// not a case to fail on — it is a case that returns nothing and lets the
// renderer fall back to the ID.
func TestWorksOmitsACorpusThatWasNeverIngested(t *testing.T) {
	reg := registry(t)

	works, err := reg.Works(context.Background(), []string{"wcf-1788-american", "wcf"})
	if err != nil {
		t.Fatalf("Works: %v", err)
	}
	if _, found := works["wcf"]; found {
		t.Error(`"wcf" is in the result; a bare work ID names no row`)
	}
	if len(works) != 1 {
		t.Errorf("len(works) = %d, want 1", len(works))
	}
}

// The turn resolves a profile that named no corpus only in a test, but the
// empty request is what a degraded turn makes: nothing was verified, so there
// is nothing to describe. A statement that cannot take an empty array would
// fail there and nowhere else.
func TestWorksTakesAnEmptyRequest(t *testing.T) {
	reg := registry(t)

	works, err := reg.Works(context.Background(), nil)
	if err != nil {
		t.Fatalf("Works: %v", err)
	}
	if len(works) != 0 {
		t.Errorf("len(works) = %d, want 0", len(works))
	}
}
