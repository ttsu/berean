// Assertions for `--show-work`: that it is a log of what happened, and that it
// is not a second place a refused answer can reach a reader.
//
// All invented text (ADR-0014).
package render_test

import (
	"strings"
	"testing"
	"time"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/render"
	"github.com/ttsu/berean/services/gateway/internal/turn"
)

// A turn that failed once and verified on the regeneration: two attempts, one
// of them carrying every kind of finding the trace records.
func regenerated() turn.Turn {
	failed := turn.Attempt{
		Number: 1,
		// The prose verification refused. Reachable from here and from
		// nowhere else, which is the point of the assertion below.
		Answer: &bereanv1.AnswerObject{Position: "The assembly meets on the fourth Tuesday."},
		Trace: &bereanv1.RetrievalTrace{
			RewrittenQuery:  "when does the assembly meet?",
			EmbeddingModel:  "invented-embedder",
			Dim:             8,
			GenerationModel: "invented-generator:1b",
			TopK:            2,
			Timings:         &bereanv1.Timings{EmbedMs: 40, SearchMs: 9, GenerateMs: 12000},
			Candidates: []*bereanv1.Candidate{
				{CorpusId: bindingID, Locator: "A 4.2", Score: 0.8125, Included: true},
				{CorpusId: contraryID, Locator: "A 4.2", Score: 0.6250,
					ExclusionReason: "below the retrieval depth"},
			},
		},
		Results: []*bereanv1.VerificationResult{{
			CitationRef:      &bereanv1.CitationRef{CorpusId: bindingID, Locator: "A 9.9"},
			LocatorResolved:  false,
			QuoteMatched:     false,
			TierPermitted:    true,
			LicensePermitted: true,
			FailureDetail:    "no chunk carries that corpus ID and locator",
		}},
		Failures: []*bereanv1.AnswerFailure{{
			Code:   bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_ARGUMENT_LACKS_AUTHORITY,
			Slot:   "arguments[0]",
			Detail: "no citation at binding or governing",
		}},
		Verify: 2 * time.Millisecond,
	}
	passed := turn.Attempt{
		Number: 2,
		Answer: &bereanv1.AnswerObject{Position: "The assembly meets annually."},
		Trace: &bereanv1.RetrievalTrace{
			RewrittenQuery:  "when does the assembly meet?",
			EmbeddingModel:  "invented-embedder",
			Dim:             8,
			GenerationModel: "invented-generator:1b",
			TopK:            2,
			Timings:         &bereanv1.Timings{EmbedMs: 38, SearchMs: 8, GenerateMs: 11400},
			Candidates: []*bereanv1.Candidate{
				{CorpusId: bindingID, Locator: "A 4.2", Score: 0.8125, Included: true},
			},
		},
		Results: []*bereanv1.VerificationResult{{
			CitationRef:      &bereanv1.CitationRef{CorpusId: bindingID, Locator: "A 4.2"},
			LocatorResolved:  true,
			QuoteMatched:     true,
			TierPermitted:    true,
			LicensePermitted: true,
		}},
		Verify: 1 * time.Millisecond,
	}

	return turn.Turn{
		RequestID: "00000000-0000-4000-8000-00000000000c",
		Query:     "when does the assembly meet?",
		Profile:   "example",
		Answer:    passed.Answer,
		Overall:   bereanv1.OverallResult_OVERALL_RESULT_REGENERATED,
		Attempts:  []turn.Attempt{failed, passed},
	}
}

func work(t *testing.T, turned turn.Turn) string {
	t.Helper()
	var out strings.Builder
	if err := render.Trace(&out, turned, sources(), "1.2.3-test"); err != nil {
		t.Fatalf("Trace: %v", err)
	}
	return out.String()
}

// What retrieval did, per attempt: the settings it ran under and every
// candidate it considered, included or not. This is the list that makes a
// retrieval regression visible, so a summary of it is not a substitute.
func TestTheTraceLogsEveryCandidateAndTheSettingsItRanUnder(t *testing.T) {
	out := work(t, regenerated())

	for _, want := range []string{
		"invented-embedder",
		"invented-generator:1b",
		"0.8125",
		bindingID + " A 4.2",
		"below the retrieval depth",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("the trace is missing %q\n---\n%s", want, out)
		}
	}
}

// Both attempts, in order, each numbered. A trace showing only the attempt that
// won cannot answer the question ADR-0010 exists to keep answerable: how often
// the first attempt fails.
func TestTheTraceLogsBothAttempts(t *testing.T) {
	out := work(t, regenerated())

	first := strings.Index(out, "attempt 1")
	second := strings.Index(out, "attempt 2")
	if first < 0 || second < 0 {
		t.Fatalf("the trace does not log both attempts\n---\n%s", out)
	}
	if second < first {
		t.Errorf("attempt 2 is logged before attempt 1\n---\n%s", out)
	}
}

// Each of the four checks, per citation, and the factual detail beside the ones
// that failed. "The citation failed" without which check failed sends whoever
// reads it hunting.
func TestTheTraceLogsEachCheckAndWhatFailed(t *testing.T) {
	out := work(t, regenerated())

	for _, want := range []string{
		"locator",
		"quote",
		"tier",
		"license",
		"no chunk carries that corpus ID and locator",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("the trace is missing %q\n---\n%s", want, out)
		}
	}
}

// The answer-level rules have no citation to hang off, so they are logged in
// their own right — code, slot, and what broke (ADR-0024).
func TestTheTraceLogsAnswerLevelFailures(t *testing.T) {
	out := work(t, regenerated())

	for _, want := range []string{
		"argument-lacks-authority",
		"arguments[0]",
		"no citation at binding or governing",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("the trace is missing %q\n---\n%s", want, out)
		}
	}
}

// The trace is provenance, not content. A refused attempt's prose reaching a
// reader through `--show-work` is the same failure as rendering it directly,
// with a flag in front of it.
func TestTheTraceNeverPrintsARefusedAttemptsProse(t *testing.T) {
	out := work(t, regenerated())

	if strings.Contains(out, "fourth Tuesday") {
		t.Errorf("a refused attempt's prose reached the trace\n---\n%s", out)
	}
}

// Verification is the trust boundary's own cost, and it is the timing the three
// stages Python reports cannot account for. Without it a slow turn cannot be
// attributed.
func TestTheTraceLogsWhatVerificationCost(t *testing.T) {
	out := work(t, regenerated())

	if !strings.Contains(out, "verify") {
		t.Errorf("the trace does not say what verification cost\n---\n%s", out)
	}
}

// The first question asked of a verification failure is which build produced
// the answer, and the trace on screen should answer it as the trace table does.
func TestTheTraceNamesTheBuildAndTheOutcome(t *testing.T) {
	out := work(t, regenerated())

	for _, want := range []string{"1.2.3-test", "regenerated", "example"} {
		if !strings.Contains(out, want) {
			t.Errorf("the trace is missing %q\n---\n%s", want, out)
		}
	}
}

// A degraded turn's trace is the one most worth reading, and both its attempts
// carry findings. An attempt Catena never answered for is a turn that errored,
// not a turn that degraded, so a missing retrieval trace is logged as absent
// rather than skipped.
func TestTheTraceOfATurnWithNoRetrievalTraceStillLogsTheAttempt(t *testing.T) {
	bare := turn.Turn{
		RequestID: "00000000-0000-4000-8000-00000000000d",
		Query:     "when does the assembly meet?",
		Profile:   "example",
		Answer:    &bereanv1.AnswerObject{},
		Overall:   bereanv1.OverallResult_OVERALL_RESULT_DEGRADED,
		Attempts:  []turn.Attempt{{Number: 1}, {Number: 2}},
	}

	out := work(t, bare)

	if !strings.Contains(out, "attempt 1") || !strings.Contains(out, "attempt 2") {
		t.Errorf("an attempt with no retrieval trace was not logged\n---\n%s", out)
	}
}

// Scripture is roughly 90% of the Phase 1 index and nothing balances corpus
// proportions, so "which tiers did retrieval actually surface" is the first
// question asked of a confessional question answered entirely from verses. It
// is a property of the resolved profile rather than of the candidate, so
// nothing Catena sends carries it and the log has to join it on.
func TestTheTraceNamesTheTierOfEveryCandidate(t *testing.T) {
	out := work(t, regenerated())

	for _, want := range []string{"[binding]", "[contrary]"} {
		if !strings.Contains(out, want) {
			t.Errorf("the candidate list does not carry %s\n---\n%s", want, out)
		}
	}
}
