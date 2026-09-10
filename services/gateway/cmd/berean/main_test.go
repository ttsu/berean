// Assertions for the command line and for the one ordering rule this file
// owns: the turn is persisted before anything is printed.
//
// All invented text (ADR-0014). Nothing here dials Catena or a database —
// what is under test is what the flags mean and what happens when the write
// fails, and neither needs either.
package main

import (
	"context"
	"errors"
	"strings"
	"testing"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/render"
	"github.com/ttsu/berean/services/gateway/internal/turn"
)

func TestAskTakesAProfileAndAQuestion(t *testing.T) {
	got, err := parseAsk([]string{"--profile", "pca", "when does the assembly meet?"})
	if err != nil {
		t.Fatalf("parseAsk: %v", err)
	}
	if got.profile != "pca" {
		t.Errorf("profile = %q, want %q", got.profile, "pca")
	}
	if got.question != "when does the assembly meet?" {
		t.Errorf("question = %q", got.question)
	}
	if got.showWork {
		t.Error("showWork = true with no --show-work")
	}
}

// `top_k` is recorded in every trace and is one of the two settings most likely
// to move the Phase 2 baseline invisibly, so an override has to reach the
// request rather than sit in a struct nobody read.
func TestTopKOverridesTheConfiguredDefault(t *testing.T) {
	got, err := parseAsk([]string{"--profile", "pca", "--top-k", "40", "a question"})
	if err != nil {
		t.Fatalf("parseAsk: %v", err)
	}
	if depth := got.depth(20); depth != 40 {
		t.Errorf("depth(20) = %d, want 40 — the override did not reach the request", depth)
	}
}

func TestTheConfiguredDefaultStandsWithoutAnOverride(t *testing.T) {
	got, err := parseAsk([]string{"--profile", "pca", "a question"})
	if err != nil {
		t.Fatalf("parseAsk: %v", err)
	}
	if depth := got.depth(20); depth != 20 {
		t.Errorf("depth(20) = %d, want 20", depth)
	}
}

// A depth of zero or less retrieves nothing, which reads as an empty corpus.
// `internal/config` refuses it from the environment for that reason, and the
// flag is the same value arriving by a different route.
func TestADepthOfZeroOrLessIsAUsageError(t *testing.T) {
	for _, value := range []string{"0", "-1"} {
		if _, err := parseAsk([]string{"--profile", "pca", "--top-k", value, "a question"}); err == nil {
			t.Errorf("--top-k %s was accepted", value)
		}
	}
}

func TestAskWithoutAProfileIsAUsageError(t *testing.T) {
	if _, err := parseAsk([]string{"a question"}); err == nil {
		t.Error("a question with no --profile was accepted; there is no default tradition")
	}
}

func TestAskWithoutAQuestionIsAUsageError(t *testing.T) {
	if _, err := parseAsk([]string{"--profile", "pca"}); err == nil {
		t.Error("a profile with no question was accepted")
	}
}

// Two positional arguments mean an unquoted question, and the first word of one
// is not a question. Answering it would spend two generations on a query the
// user did not ask.
func TestAnUnquotedQuestionIsAUsageError(t *testing.T) {
	if _, err := parseAsk([]string{"--profile", "pca", "when", "does", "it", "meet"}); err == nil {
		t.Error("an unquoted question was accepted")
	}
}

// recorder is a trace store that either accepts a turn or refuses it.
type recorder struct {
	err     error
	written []turn.Turn
}

func (r *recorder) Write(_ context.Context, t turn.Turn) error {
	if r.err != nil {
		return r.err
	}
	r.written = append(r.written, t)
	return nil
}

func answered() turn.Turn {
	return turn.Turn{
		RequestID: "00000000-0000-4000-8000-00000000000e",
		Query:     "when does the assembly meet?",
		Profile:   "example",
		Answer: &bereanv1.AnswerObject{
			Position: "The assembly meets annually.",
			Confidence: &bereanv1.Confidence{
				Level:  bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW,
				Reason: "no binding or governing citations, first attempt, not contested",
			},
		},
		Overall:  bereanv1.OverallResult_OVERALL_RESULT_VERIFIED,
		Attempts: []turn.Attempt{{Number: 1}},
	}
}

// The rule this whole ordering exists for: verification refusing to ship is a
// recorded event, and a write that failed after the answer was printed is not.
// A turn that reached a user without being recorded is the one outcome the
// trace tables exist to prevent.
func TestNothingIsPrintedWhenTheTurnCannotBeRecorded(t *testing.T) {
	store := &recorder{err: errors.New("the database is unreachable")}
	var out strings.Builder

	err := deliver(context.Background(), store, &out, answered(), render.Sources{},
		options{}, "1.2.3-test")

	if err == nil {
		t.Fatal("deliver returned no error though the turn was never recorded")
	}
	if out.Len() != 0 {
		t.Errorf("an unrecorded turn reached the user:\n%s", out.String())
	}
}

func TestTheAnswerIsPrintedOnceTheTurnIsRecorded(t *testing.T) {
	store := &recorder{}
	var out strings.Builder

	if err := deliver(context.Background(), store, &out, answered(), render.Sources{},
		options{}, "1.2.3-test"); err != nil {
		t.Fatalf("deliver: %v", err)
	}

	if len(store.written) != 1 {
		t.Fatalf("the store recorded %d turns, want 1", len(store.written))
	}
	if !strings.Contains(out.String(), "The assembly meets annually.") {
		t.Errorf("the answer was not printed:\n%s", out.String())
	}
}

func TestTheTraceIsPrintedOnlyUnderShowWork(t *testing.T) {
	quiet, loud := &strings.Builder{}, &strings.Builder{}

	if err := deliver(context.Background(), &recorder{}, quiet, answered(), render.Sources{},
		options{}, "1.2.3-test"); err != nil {
		t.Fatalf("deliver: %v", err)
	}
	if err := deliver(context.Background(), &recorder{}, loud, answered(), render.Sources{},
		options{showWork: true}, "1.2.3-test"); err != nil {
		t.Fatalf("deliver: %v", err)
	}

	if strings.Contains(quiet.String(), "attempt 1") {
		t.Errorf("the trace was printed without --show-work:\n%s", quiet.String())
	}
	if !strings.Contains(loud.String(), "attempt 1") {
		t.Errorf("--show-work printed no trace:\n%s", loud.String())
	}
}
