// Assertions for the turn: one call, at most one regeneration, then degrade.
//
// The generator is a script of canned responses rather than a real Catena, so
// what is under test is the boundary's own decisions — how many calls it makes,
// what it carries back, and what it lets through. All text is invented
// (ADR-0014).
package turn_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/corpus"
	"github.com/ttsu/berean/services/gateway/internal/turn"
	"github.com/ttsu/berean/services/gateway/internal/verify"
)

const (
	bindingID   = "alpha-1702-revised"
	advisoryID  = "gamma-study-1998"
	bindingLoc  = "A 4.2"
	bindingText = "The assembly of elders shall meet on the first day of the fourth month, and shall not adjourn until the roll is read."
	rulingLoc   = "GS98 Rec.4"
	rulingText  = "The assembly affirms that a diversity of views on this question is permitted among its teaching elders and ruling elders."
)

type store map[string]corpus.Chunk

func (s store) Lookup(_ context.Context, corpusID, locator string) (corpus.Chunk, error) {
	chunk, ok := s[corpusID+"|"+locator]
	if !ok {
		return corpus.Chunk{}, corpus.ErrNotFound
	}
	return chunk, nil
}

func corpora() store {
	return store{
		bindingID + "|" + bindingLoc: {CorpusID: bindingID, Locator: bindingLoc,
			Text: bindingText, License: corpus.PublicDomain},
		advisoryID + "|" + rulingLoc: {CorpusID: advisoryID, Locator: rulingLoc,
			Text: rulingText, License: corpus.PublicDomain},
	}
}

// script is a generator that answers from a fixed list, recording what it was
// asked. A turn that makes a third call runs off the end of it, which is the
// assertion ADR-0002 and ADR-0010 most want made.
type script struct {
	answers  []*bereanv1.AnswerObject
	err      error
	requests []*bereanv1.AnswerRequest
}

func (s *script) Answer(_ context.Context, req *bereanv1.AnswerRequest) (*bereanv1.AnswerResponse, error) {
	s.requests = append(s.requests, req)
	if s.err != nil {
		return nil, s.err
	}
	if len(s.requests) > len(s.answers) {
		return nil, errors.New("the turn made more calls than the seam permits")
	}
	return &bereanv1.AnswerResponse{
		Answer: s.answers[len(s.requests)-1],
		Trace:  &bereanv1.RetrievalTrace{RewrittenQuery: req.GetQuery(), TopK: req.GetFilterSpec().GetTopK()},
	}, nil
}

func spec() *bereanv1.FilterSpec {
	return &bereanv1.FilterSpec{
		TopK: 20,
		Corpora: []*bereanv1.CorpusFilter{
			{CorpusId: bindingID, Tier: bereanv1.Tier_TIER_BINDING},
			{CorpusId: advisoryID, Tier: bereanv1.Tier_TIER_ADVISORY},
		},
	}
}

func loci() []*bereanv1.ContestedLocus {
	return []*bereanv1.ContestedLocus{{
		Locus:  "creation-days",
		Ruling: &bereanv1.CitationRef{CorpusId: advisoryID, Locator: rulingLoc},
	}}
}

func good() *bereanv1.AnswerObject {
	return &bereanv1.AnswerObject{
		Position: "The roll is read before adjournment.",
		Arguments: []*bereanv1.Argument{{
			Claim:   "The roll is read before the court adjourns.",
			Warrant: "The standard fixes the order of business.",
			Citations: []*bereanv1.Citation{{
				CorpusId: bindingID, Locator: bindingLoc, Quote: bindingText,
			}},
		}},
	}
}

func fabricated() *bereanv1.AnswerObject {
	answer := good()
	answer.Arguments[0].Citations[0].Locator = "A 99.9"
	return answer
}

func ask(t *testing.T, gen *script, chunks store) (turn.Turn, error) {
	t.Helper()
	runner := turn.NewRunner(gen, verify.New(chunks, false))
	return runner.Ask(context.Background(), turn.Question{
		RequestID: "6f1a0b6e-9f3a-4a2e-9a8b-2d1f0c3b4a55",
		Query:     "When must the roll be read?",
		Profile:   "pca",
		Spec:      spec(),
		Loci:      loci(),
	})
}

func TestAVerifiedFirstAttemptMakesOneCall(t *testing.T) {
	gen := &script{answers: []*bereanv1.AnswerObject{good()}}

	got, err := ask(t, gen, corpora())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}

	if len(gen.requests) != 1 {
		t.Errorf("calls = %d, want 1", len(gen.requests))
	}
	if got.Overall != bereanv1.OverallResult_OVERALL_RESULT_VERIFIED {
		t.Errorf("overall = %v, want VERIFIED", got.Overall)
	}
	if len(got.Attempts) != 1 {
		t.Errorf("attempts = %d, want 1", len(got.Attempts))
	}
	if got.Answer.GetPosition() == "" {
		t.Error("the verified answer did not survive to the outcome")
	}
}

func TestTheFirstCallCarriesNoFailuresAndAttemptOne(t *testing.T) {
	gen := &script{answers: []*bereanv1.AnswerObject{good()}}

	if _, err := ask(t, gen, corpora()); err != nil {
		t.Fatalf("Ask: %v", err)
	}

	first := gen.requests[0]
	if first.GetAttempt() != 1 {
		t.Errorf("attempt = %d, want 1", first.GetAttempt())
	}
	if len(first.GetPreviousFailures()) != 0 || len(first.GetAnswerFailures()) != 0 {
		t.Error("the first attempt carried failures from nowhere")
	}
	if first.GetRequestId() == "" || first.GetQuery() == "" {
		t.Error("the request is missing its correlation id or its query")
	}
}

func TestNoProfileIdentityCrossesTheBoundary(t *testing.T) {
	gen := &script{answers: []*bereanv1.AnswerObject{good()}}

	if _, err := ask(t, gen, corpora()); err != nil {
		t.Fatalf("Ask: %v", err)
	}

	// The FilterSpec resolution rule has its own test in the profile package.
	// What is asserted here is that the turn adds nothing to it: Python is
	// handed a search policy and never learns which tradition asked.
	rendered := gen.requests[0].String()
	if strings.Contains(rendered, "pca") {
		t.Errorf("the profile name reached the request: %s", rendered)
	}
}

func TestAFailedFirstAttemptRegeneratesOnceAndCarriesTheFailuresBack(t *testing.T) {
	gen := &script{answers: []*bereanv1.AnswerObject{fabricated(), good()}}

	got, err := ask(t, gen, corpora())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}

	if len(gen.requests) != 2 {
		t.Fatalf("calls = %d, want 2", len(gen.requests))
	}
	second := gen.requests[1]
	if second.GetAttempt() != 2 {
		t.Errorf("attempt = %d, want 2", second.GetAttempt())
	}
	if len(second.GetPreviousFailures()) != 1 {
		t.Fatalf("previous_failures = %d, want the one citation that failed", len(second.GetPreviousFailures()))
	}
	if ref := second.GetPreviousFailures()[0].GetCitationRef(); ref.GetLocator() != "A 99.9" {
		t.Errorf("previous_failures names %v, want the citation that failed", ref)
	}
	if got.Overall != bereanv1.OverallResult_OVERALL_RESULT_REGENERATED {
		t.Errorf("overall = %v, want REGENERATED", got.Overall)
	}
	if len(got.Attempts) != 2 {
		t.Errorf("attempts recorded = %d, want 2", len(got.Attempts))
	}
}

func TestOnlyFailingResultsAreCarriedBack(t *testing.T) {
	answer := good()
	answer.Arguments[0].Citations = append(answer.Arguments[0].Citations,
		&bereanv1.Citation{CorpusId: bindingID, Locator: "A 99.9", Quote: bindingText})
	gen := &script{answers: []*bereanv1.AnswerObject{answer, good()}}

	if _, err := ask(t, gen, corpora()); err != nil {
		t.Fatalf("Ask: %v", err)
	}

	if got := len(gen.requests[1].GetPreviousFailures()); got != 1 {
		t.Errorf("previous_failures = %d, want only what failed", got)
	}
}

func TestAnAnswerLevelFailureIsCarriedBackInItsOwnField(t *testing.T) {
	// An argument with no citations has no VerificationResult to travel in,
	// which is the whole reason the second field exists (ADR-0024).
	answer := good()
	answer.Arguments[0].Citations = nil
	gen := &script{answers: []*bereanv1.AnswerObject{answer, good()}}

	if _, err := ask(t, gen, corpora()); err != nil {
		t.Fatalf("Ask: %v", err)
	}

	second := gen.requests[1]
	if len(second.GetPreviousFailures()) != 0 {
		t.Errorf("previous_failures = %d, want 0: there was no citation to fail",
			len(second.GetPreviousFailures()))
	}
	if len(second.GetAnswerFailures()) == 0 {
		t.Fatal("answer_failures is empty; the regeneration was told nothing")
	}
	if got := second.GetAnswerFailures()[0].GetCode(); got != bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CITATIONS_REQUIRED {
		t.Errorf("code = %v, want CITATIONS_REQUIRED", got)
	}
}

func TestTwoFailedAttemptsDegradeAndMakeNoThirdCall(t *testing.T) {
	gen := &script{answers: []*bereanv1.AnswerObject{fabricated(), fabricated()}}

	got, err := ask(t, gen, corpora())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}

	if len(gen.requests) != 2 {
		t.Errorf("calls = %d, want exactly 2; the retry is bounded at one", len(gen.requests))
	}
	if got.Overall != bereanv1.OverallResult_OVERALL_RESULT_DEGRADED {
		t.Errorf("overall = %v, want DEGRADED", got.Overall)
	}
}

func TestADegradedTurnShipsNoPartialContent(t *testing.T) {
	gen := &script{answers: []*bereanv1.AnswerObject{fabricated(), fabricated()}}

	got, err := ask(t, gen, corpora())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}

	answer := got.Answer
	if len(answer.GetArguments()) != 0 || len(answer.GetDescriptions()) != 0 ||
		len(answer.GetContraryPositions()) != 0 || answer.GetPosition() != "" {
		t.Errorf("degraded answer carries content: %v", answer)
	}
	if answer.GetNoAnswerReason() != "" {
		t.Error("a degraded turn set no_answer_reason; that is the honest non-answer, and they mean opposite things")
	}
	if answer.GetConfidence().GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW {
		t.Errorf("degraded confidence = %v, want LOW", answer.GetConfidence().GetLevel())
	}
}

func TestTheFailedAttemptsAreStillRecordedWhenTheTurnDegrades(t *testing.T) {
	gen := &script{answers: []*bereanv1.AnswerObject{fabricated(), fabricated()}}

	got, err := ask(t, gen, corpora())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}

	if len(got.Attempts) != 2 {
		t.Fatalf("attempts = %d, want both recorded", len(got.Attempts))
	}
	for i, attempt := range got.Attempts {
		if attempt.Number != int32(i+1) {
			t.Errorf("attempt[%d].Number = %d", i, attempt.Number)
		}
		if len(attempt.Results) == 0 {
			t.Errorf("attempt[%d] recorded no verification results", i)
		}
		if attempt.Trace == nil {
			t.Errorf("attempt[%d] recorded no retrieval trace", i)
		}
	}
}

func TestAnHonestNonAnswerIsVerifiedRatherThanDegraded(t *testing.T) {
	gen := &script{answers: []*bereanv1.AnswerObject{{
		NoAnswerReason: "The corpora in scope do not address the question.",
	}}}

	got, err := ask(t, gen, corpora())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}

	if got.Overall != bereanv1.OverallResult_OVERALL_RESULT_VERIFIED {
		t.Errorf("overall = %v, want VERIFIED: the corpus being silent is a pass", got.Overall)
	}
	if got.Answer.GetNoAnswerReason() == "" {
		t.Error("the reason did not survive; UC-2 renders it and UC-5 must not")
	}
}

func TestGoOverwritesWhateverConfidenceArrived(t *testing.T) {
	answer := good()
	answer.Confidence = &bereanv1.Confidence{
		Level:  bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_HIGH,
		Reason: "I am quite sure about this one.",
	}
	gen := &script{answers: []*bereanv1.AnswerObject{answer}}

	got, err := ask(t, gen, corpora())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}

	confidence := got.Answer.GetConfidence()
	if confidence.GetReason() == "I am quite sure about this one." {
		t.Error("a model-authored confidence survived into the answer")
	}
	if confidence.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM {
		t.Errorf("level = %v, want MEDIUM derived from one binding citation", confidence.GetLevel())
	}
}

func TestARegeneratedAnswerIsNeverHighConfidence(t *testing.T) {
	answer := good()
	answer.Arguments[0].Citations = append(answer.Arguments[0].Citations,
		&bereanv1.Citation{CorpusId: bindingID, Locator: bindingLoc, Quote: bindingText[:80]})
	gen := &script{answers: []*bereanv1.AnswerObject{fabricated(), answer}}

	got, err := ask(t, gen, corpora())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}

	if got.Answer.GetConfidence().GetLevel() == bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_HIGH {
		t.Error("a regenerated answer was marked HIGH")
	}
}

func TestAGeneratorFailureIsAnErrorRatherThanADegradedAnswer(t *testing.T) {
	// DEGRADED means verification refused to ship. An outage is a failure of
	// the system, and laundering it into the degradation rate would make the
	// one metric ADR-0010 needs kept clean unreadable.
	gen := &script{err: errors.New("connection refused")}

	_, err := ask(t, gen, corpora())

	if err == nil {
		t.Fatal("Ask returned no error when the generator was unreachable")
	}
}

func TestAVerifiedAttemptDoesNotMutateWhatPythonSent(t *testing.T) {
	// The recorded attempt is the audit record of what arrived. Writing Go's
	// derived confidence into it would make the trace unable to show that
	// Python sent one.
	answer := good()
	answer.Confidence = &bereanv1.Confidence{Reason: "as sent"}
	gen := &script{answers: []*bereanv1.AnswerObject{answer}}

	got, err := ask(t, gen, corpora())
	if err != nil {
		t.Fatalf("Ask: %v", err)
	}

	if got.Attempts[0].Answer.GetConfidence().GetReason() != "as sent" {
		t.Errorf("the recorded attempt was rewritten: %v", got.Attempts[0].Answer.GetConfidence())
	}
}
