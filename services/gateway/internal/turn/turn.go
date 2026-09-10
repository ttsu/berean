// Package turn runs one user turn across the trust boundary.
//
// It owns the shape ADR-0002 and ADR-0010 fix between them: **one gRPC call
// per generation attempt**, a verification failure buys exactly one
// regeneration carrying the failures back, and a second failure degrades. A
// turn therefore makes at most two calls, and only ever two. If this file ever
// grows a third, the seam is in the wrong place — raise it rather than working
// around it.
//
// What it does not own: retrieval, generation, rendering, and persistence.
// The outcome it returns is the whole of what Task 9 writes and Task 10 prints,
// which is why it carries every attempt rather than only the one that won.
package turn

import (
	"context"
	"fmt"
	"time"

	"google.golang.org/protobuf/proto"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/verify"
)

// maxAttempts is one generation plus at most one regeneration (ADR-0010). A
// third is not a tuning question.
const maxAttempts = 2

// Generator is the one call into Catena. An interface so the turn's own
// decisions can be asserted against a script of canned answers rather than
// against a model.
type Generator interface {
	Answer(ctx context.Context, request *bereanv1.AnswerRequest) (*bereanv1.AnswerResponse, error)
}

// Verifier is the trust boundary's judgement. Satisfied by *verify.Engine.
type Verifier interface {
	Verify(ctx context.Context, answer *bereanv1.AnswerObject,
		spec *bereanv1.FilterSpec, loci []*bereanv1.ContestedLocus) (verify.Outcome, error)
}

// Question is everything a turn needs that came from outside it.
//
// The spec and loci arrive already resolved rather than as a profile, so the
// rule that no identity crosses the boundary is settled before this package
// runs and cannot be undone by anything in it.
type Question struct {
	// Correlates the trace, the response and the Langfuse span.
	RequestID string
	Query     string
	// The resolved profile's name. Recorded in the trace; never sent.
	Profile string
	Spec    *bereanv1.FilterSpec
	Loci    []*bereanv1.ContestedLocus
}

// Attempt is one generation and what verification found in it.
//
// `Answer` is exactly what Python sent, unmodified — the derived confidence is
// written onto the rendered answer instead. An attempt record that had been
// rewritten could not show that Python populated a field it must not populate.
type Attempt struct {
	Number   int32
	Answer   *bereanv1.AnswerObject
	Trace    *bereanv1.RetrievalTrace
	Results  []*bereanv1.VerificationResult
	Failures []*bereanv1.AnswerFailure

	// How long verification took on this attempt.
	//
	// Measured here rather than inside the engine because it is the trust
	// boundary's cost for this attempt, and the engine has no attempt to
	// attribute it to. It joins the three stage timings Python already
	// reports (`RetrievalTrace.timings`), which between them account for
	// everything a turn spends: with this one missing, the trace tables
	// cannot say where a slow turn went. SHARED §9 puts the floor at 200 ms
	// p95, and a floor held only against synthetic load is a floor nobody is
	// measuring in production.
	Verify time.Duration
}

// Turn is the outcome: what may render, what happened, and every attempt.
type Turn struct {
	RequestID string
	Query     string
	Profile   string

	// What may be shown. Empty of content when `Overall` is DEGRADED — a
	// degraded turn ships no partial unverified content, and never a warning
	// attached to some of it.
	Answer  *bereanv1.AnswerObject
	Overall bereanv1.OverallResult

	// Both attempts when there were two, in order.
	Attempts []Attempt
}

// Runner holds the two collaborators a turn needs.
type Runner struct {
	generator Generator
	verifier  Verifier
}

// NewRunner wires a generator to a verifier.
func NewRunner(generator Generator, verifier Verifier) *Runner {
	return &Runner{generator: generator, verifier: verifier}
}

// Ask runs the turn.
//
// A generator or verifier error is returned as an error rather than degraded.
// DEGRADED means the user saw "I can't source this adequately" — a *successful*
// outcome of the verification system, which metrics must not read as a failure
// rate. An unreachable Catena or an unreachable database is a failure of the
// system, and folding one into the other makes the degradation rate ADR-0010
// needs kept clean unreadable. Degradation therefore always follows exactly two
// generation attempts.
func (r *Runner) Ask(ctx context.Context, question Question) (Turn, error) {
	result := Turn{
		RequestID: question.RequestID,
		Query:     question.Query,
		Profile:   question.Profile,
	}

	var previousResults []*bereanv1.VerificationResult
	var previousFailures []*bereanv1.AnswerFailure

	for number := int32(1); number <= maxAttempts; number++ {
		response, err := r.generator.Answer(ctx, &bereanv1.AnswerRequest{
			Query:         question.Query,
			FilterSpec:    question.Spec,
			ContestedLoci: question.Loci,
			RequestId:     question.RequestID,
			Attempt:       number,
			// Only what actually failed. A regeneration told about the
			// citations that passed is a regeneration spending its context on
			// nothing.
			PreviousFailures: previousResults,
			AnswerFailures:   previousFailures,
		})
		if err != nil {
			return Turn{}, fmt.Errorf("catena attempt %d: %w", number, err)
		}

		answer := response.GetAnswer()
		started := time.Now()
		outcome, err := r.verifier.Verify(ctx, answer, question.Spec, question.Loci)
		verified := time.Since(started)
		if err != nil {
			return Turn{}, fmt.Errorf("verifying attempt %d: %w", number, err)
		}

		result.Attempts = append(result.Attempts, Attempt{
			Number:   number,
			Answer:   answer,
			Trace:    response.GetTrace(),
			Results:  outcome.Results,
			Failures: outcome.Failures,
			Verify:   verified,
		})

		if outcome.Passed() {
			// A clone, so the audit record of what arrived stays what
			// arrived. Both halves of the confidence are overwritten here
			// whatever Python sent (ADR-0020).
			rendered, _ := proto.Clone(answer).(*bereanv1.AnswerObject)
			if rendered == nil {
				rendered = &bereanv1.AnswerObject{}
			}
			rendered.Confidence = verify.Confidence(rendered, question.Spec, number)
			result.Answer = rendered
			result.Overall = bereanv1.OverallResult_OVERALL_RESULT_VERIFIED
			if number > 1 {
				result.Overall = bereanv1.OverallResult_OVERALL_RESULT_REGENERATED
			}
			return result, nil
		}

		previousResults = failedResults(outcome.Results)
		previousFailures = outcome.Failures
	}

	// Degraded. Nothing from either attempt survives into what renders: not a
	// partial answer, not a warning beside one, and specifically not
	// `no_answer_reason`, which is the honest non-answer and means the
	// opposite thing.
	result.Answer = &bereanv1.AnswerObject{Confidence: verify.DegradedConfidence()}
	result.Overall = bereanv1.OverallResult_OVERALL_RESULT_DEGRADED
	return result, nil
}

func failedResults(results []*bereanv1.VerificationResult) []*bereanv1.VerificationResult {
	var failed []*bereanv1.VerificationResult
	for _, result := range results {
		if result.GetFailureDetail() != "" {
			failed = append(failed, result)
		}
	}
	return failed
}
