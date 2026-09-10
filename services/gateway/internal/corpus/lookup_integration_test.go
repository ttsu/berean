// Live-database assertions for the chunk lookup, and the half of the latency
// target a map cannot measure.
//
// Nothing here hardcodes a locator or a line of corpus text. Every fixture is
// read out of the database at run time and stays in memory: a test that named a
// real passage would put that passage in the repository, which is the ADR-0014
// violation the policy exists to prevent. What is asserted instead is that the
// row the lookup returns is the row the tables hold.
//
// Skipped when BEREAN_DATABASE_URL is unset. Run it with `make test-gateway-db`.
package corpus_test

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"sort"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/corpus"
	"github.com/ttsu/berean/services/gateway/internal/verify"
)

// ref is a citation reference borrowed from the database.
type ref struct{ corpusID, locator string }

// reading is a second connection, as the gateway role, used only to *choose*
// fixtures. The Registry under test must not grow a `Sample` method it exists
// only to be tested with: production code that carries test affordances is
// production code the tests have started designing.
func reading(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("BEREAN_DATABASE_URL")
	if dsn == "" {
		t.Skip("BEREAN_DATABASE_URL unset; run `make test-gateway-db` against a live database")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open reading connection: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}

// sample borrows real chunk references, ordered so the choice is the same
// between runs and a flake is reproducible.
func sample(t *testing.T, limit int) []ref {
	t.Helper()
	rows, err := reading(t).Query(
		`SELECT corpus_id, locator FROM corpus.chunks ORDER BY corpus_id, locator LIMIT $1`, limit)
	if err != nil {
		t.Fatalf("sample: %v", err)
	}
	defer rows.Close()
	var refs []ref
	for rows.Next() {
		var r ref
		if err := rows.Scan(&r.corpusID, &r.locator); err != nil {
			t.Fatalf("scan: %v", err)
		}
		refs = append(refs, r)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("sample: %v", err)
	}
	return refs
}

// aChunk borrows one real chunk.
func aChunk(t *testing.T) (string, string) {
	t.Helper()
	refs := sample(t, 1)
	if len(refs) == 0 {
		t.Skip("no chunks ingested; run `make ingest-all APPLY=1`")
	}
	return refs[0].corpusID, refs[0].locator
}

func TestLookupReturnsTheChunkTheTablesHold(t *testing.T) {
	reg := registry(t)
	corpusID, locator := aChunk(t)

	chunk, err := reg.Lookup(context.Background(), corpusID, locator)
	if err != nil {
		t.Fatalf("Lookup: %v", err)
	}

	if chunk.CorpusID != corpusID || chunk.Locator != locator {
		t.Errorf("Lookup returned %s %s, want %s %s", chunk.CorpusID, chunk.Locator, corpusID, locator)
	}
	if chunk.Text == "" {
		t.Error("the chunk came back with no text; the quote check would fail on everything")
	}
	if !chunk.License.Known() {
		t.Errorf("license = %q, which check 4 must fail closed on — is the enum wider than this build?",
			chunk.License)
	}
}

func TestLookupResolvesNothingForAFabricatedLocator(t *testing.T) {
	reg := registry(t)
	corpusID, _ := aChunk(t)

	_, err := reg.Lookup(context.Background(), corpusID, "Invented 99.99")

	if !errors.Is(err, corpus.ErrNotFound) {
		t.Errorf("err = %v, want ErrNotFound: this is what check 1 records", err)
	}
}

func TestLookupIsReadOnlyOnTheCorpusTables(t *testing.T) {
	// The gateway role is read-only on the corpus schema by design. A lookup
	// that needed a write would be the design being worked around.
	reg := registry(t)
	corpusID, locator := aChunk(t)

	for i := 0; i < 3; i++ {
		if _, err := reg.Lookup(context.Background(), corpusID, locator); err != nil {
			t.Fatalf("Lookup %d: %v", i, err)
		}
	}
}

func TestTheSameLocatorInTwoEditionsResolvesToDifferentText(t *testing.T) {
	// The whole reason `CitationRef` is a pair rather than a locator. If this
	// skips, the ingested corpora happen to share no locator spelling, and the
	// assertion that matters is still made in the engine's unit suite.
	reg := registry(t)
	var locator, firstID, secondID string
	err := reading(t).QueryRow(
		`SELECT locator, min(corpus_id), max(corpus_id)
		   FROM corpus.chunks
		  GROUP BY locator
		 HAVING count(DISTINCT corpus_id) > 1
		  ORDER BY locator
		  LIMIT 1`).Scan(&locator, &firstID, &secondID)
	if errors.Is(err, sql.ErrNoRows) {
		t.Skip("no locator is carried by two ingested corpora")
	}
	if err != nil {
		t.Fatalf("shared locator: %v", err)
	}

	first, err := reg.Lookup(context.Background(), firstID, locator)
	if err != nil {
		t.Fatalf("Lookup: %v", err)
	}
	second, err := reg.Lookup(context.Background(), secondID, locator)
	if err != nil {
		t.Fatalf("Lookup: %v", err)
	}
	if first.Text == second.Text {
		t.Errorf("%s and %s carry identical text at %q; a locator alone would have been enough",
			firstID, secondID, locator)
	}
}

// TestVerificationStaysUnderTheLatencyTargetAgainstTheIndex measures the half
// the unit suite deliberately fakes: the chunk lookups.
//
// SHARED §9 puts verification at ≤ 200 ms p95 over the whole act, and the unit
// suite measures only the string matching. This runs the same engine over real
// rows through the real index, on synthetic load rather than on the acceptance
// questions — ten hand-run queries do not produce a p95 (PLAN Task 8).
func TestVerificationStaysUnderTheLatencyTargetAgainstTheIndex(t *testing.T) {
	if testing.Short() {
		t.Skip("timing assertion; skipped under -short")
	}
	reg := registry(t)
	rows := sample(t, 8)
	if len(rows) < 8 {
		t.Skip("fewer than eight chunks ingested; run `make ingest-all APPLY=1`")
	}

	spec := &bereanv1.FilterSpec{TopK: 20}
	answer := &bereanv1.AnswerObject{Position: "A synthetic position."}
	seen := map[string]bool{}
	for i, row := range rows {
		chunk, err := reg.Lookup(context.Background(), row.corpusID, row.locator)
		if err != nil {
			t.Fatalf("Lookup: %v", err)
		}
		runes := []rune(chunk.Text)
		if len(runes) < verify.QuoteFloor {
			t.Skipf("%s %s is under the quote floor; the sample cannot be quoted",
				row.corpusID, row.locator)
		}
		if !seen[row.corpusID] {
			seen[row.corpusID] = true
			spec.Corpora = append(spec.Corpora, &bereanv1.CorpusFilter{
				CorpusId: row.corpusID, Tier: bereanv1.Tier_TIER_BINDING,
			})
		}
		answer.Arguments = append(answer.Arguments, &bereanv1.Argument{
			Claim:   fmt.Sprintf("Synthetic claim %d.", i),
			Warrant: "A synthetic warrant.",
			Citations: []*bereanv1.Citation{{
				CorpusId: row.corpusID, Locator: row.locator,
				// The chunk's own text, held in memory and never written down.
				Quote: string(runes),
			}},
		})
	}

	// The opt-in is on, because the sample may include a `local-only` corpus
	// and this test is about latency rather than about check 4.
	engine := verify.New(reg, true)
	if _, err := engine.Verify(context.Background(), answer, spec, nil); err != nil {
		t.Fatalf("Verify: %v", err)
	}

	const turns = 50
	samples := make([]time.Duration, 0, turns)
	for i := 0; i < turns; i++ {
		start := time.Now()
		out, err := engine.Verify(context.Background(), answer, spec, nil)
		samples = append(samples, time.Since(start))
		if err != nil {
			t.Fatalf("Verify: %v", err)
		}
		if !out.Passed() {
			t.Fatalf("real chunks quoted whole did not verify: %v %v", out.Results, out.Failures)
		}
	}
	sort.Slice(samples, func(i, j int) bool { return samples[i] < samples[j] })

	p95 := samples[(len(samples)*95)/100]
	t.Logf("%d turns x %d citations against the index: p50 %v, p95 %v",
		turns, len(answer.GetArguments()), samples[len(samples)/2], p95)

	if p95 > 200*time.Millisecond {
		t.Errorf("p95 = %v, want <= 200ms (SHARED §9)", p95)
	}
}
