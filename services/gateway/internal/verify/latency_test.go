// Latency, against synthetic load.
//
// PLAN Task 8 is explicit that this must not be measured on the ten acceptance
// questions: ten hand-run queries do not produce a p95. What is measured here
// is the engine's own cost — normalisation and substring containment over
// chunk-sized text — with the store as a map. The chunk lookup's cost is
// measured separately, against a real index, in the live-database suite.
//
// SHARED §9 puts verification at ≤ 200 ms p95 and says that if it is slower
// than that, something is structurally wrong. This asserts exactly that, which
// makes it a regression test rather than a number in a report nobody re-runs.
package verify_test

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"testing"
	"time"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/corpus"
	"github.com/ttsu/berean/services/gateway/internal/verify"
)

// A turn's worth of citations. Three arguments carrying two citations each, two
// descriptions carrying one: eight resolutions, eight quote matches. Larger
// than the Phase 1 generator has produced, which is the direction an assertion
// about a ceiling should err in.
const (
	citationsPerTurn = 8
	// Chunk-sized. The Institutes paragraphs are the longest chunks in the
	// Phase 1 index, and the quote check is a scan over the whole chunk.
	chunkRunes = 4000
	turns      = 200
)

// syntheticLoad builds a turn's worth of chunks and an answer that cites all
// of them, passing every check.
func syntheticLoad() (store, *bereanv1.AnswerObject, *bereanv1.FilterSpec) {
	// Invented filler with enough variety that the substring scan cannot
	// short-circuit on the first byte of every window.
	var builder strings.Builder
	for builder.Len() < chunkRunes {
		fmt.Fprintf(&builder,
			"The court of the %dth circuit shall record its judgement, and the clerk shall attest it before the roll is read. ",
			builder.Len())
	}
	body := builder.String()

	chunks := store{}
	load := &bereanv1.FilterSpec{TopK: 20}
	answer := &bereanv1.AnswerObject{
		Position: "The synthetic tradition requires the roll to be read.",
	}
	for i := 0; i < citationsPerTurn; i++ {
		id := fmt.Sprintf("synthetic-%04d-invented", i)
		locator := fmt.Sprintf("S %d.1", i)
		chunks.put(id, locator, body, corpus.PublicDomain)
		load.Corpora = append(load.Corpora, &bereanv1.CorpusFilter{
			CorpusId: id, Tier: bereanv1.Tier_TIER_BINDING,
		})
		// Quote the tail, so containment cannot succeed on a prefix compare.
		answer.Arguments = append(answer.Arguments, &bereanv1.Argument{
			Claim:     fmt.Sprintf("Synthetic claim %d.", i),
			Warrant:   "The standard fixes the order of business.",
			Citations: []*bereanv1.Citation{cite(id, locator, body[len(body)-400:])},
		})
	}
	return chunks, answer, load
}

func TestVerificationStaysUnderTheLatencyTarget(t *testing.T) {
	if testing.Short() {
		t.Skip("timing assertion; skipped under -short")
	}
	chunks, object, load := syntheticLoad()
	engine := verify.New(chunks, false)
	var loci []*bereanv1.ContestedLocus

	// One warm pass, so the first measurement is not the one that faulted the
	// fixture into cache.
	if _, err := engine.Verify(context.Background(), object, load, loci); err != nil {
		t.Fatalf("Verify: %v", err)
	}

	samples := make([]time.Duration, 0, turns)
	for i := 0; i < turns; i++ {
		start := time.Now()
		out, err := engine.Verify(context.Background(), object, load, loci)
		samples = append(samples, time.Since(start))
		if err != nil {
			t.Fatalf("Verify: %v", err)
		}
		if !out.Passed() {
			t.Fatalf("the synthetic load does not verify: %v %v", out.Results, out.Failures)
		}
	}
	sort.Slice(samples, func(i, j int) bool { return samples[i] < samples[j] })

	p50 := samples[len(samples)/2]
	p95 := samples[(len(samples)*95)/100]
	t.Logf("%d turns x %d citations x %d-character chunks: p50 %v, p95 %v",
		turns, citationsPerTurn, chunkRunes, p50, p95)

	if p95 > 200*time.Millisecond {
		t.Errorf("p95 = %v, want <= 200ms; verification is string matching and indexed lookups, "+
			"and slower than this means something is structurally wrong (SHARED §9)", p95)
	}
}

func BenchmarkVerify(b *testing.B) {
	chunks, object, load := syntheticLoad()
	engine := verify.New(chunks, false)
	var loci []*bereanv1.ContestedLocus
	ctx := context.Background()

	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if _, err := engine.Verify(ctx, object, load, loci); err != nil {
			b.Fatal(err)
		}
	}
}
