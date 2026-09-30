// The ledger of every CHECK constraint on the `trace` schema, and what stands
// between each one and a turn nobody can record.
//
// The failure this exists for: a schema CHECK that the write path can violate
// from a value Catena sent. The turn then fails at INSERT, after two
// generations, as a raw constraint error that reads like a database outage --
// when it is a contract violation by a service, which wants the opposite
// response (ErrIncomplete). Task 9's review found one by hand. This holds the
// rest to a rule: a constraint is either **mirrored** by `validate()`, proved by
// a mutation that must be refused, or **derived**, meaning the gateway computes
// the value itself and the entry says where.
//
// Two halves. This file needs no database and runs in `make check`; the other
// half, in constraints_integration_test.go, asserts the ledger names exactly the
// constraints the live schema has, so a new CHECK in a migration fails there
// until someone classifies it here.
//
// All invented content (ADR-0014).
package trace

import (
	"errors"
	"testing"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/turn"
)

type constraint struct {
	// Set for a mirrored constraint: turns a well-formed turn into one that
	// breaches it, and validate() must refuse the result with ErrIncomplete.
	breach func(*turn.Turn)
	// The turn to breach. verifiedTurn when nil.
	base func() turn.Turn
	// Set for a derived constraint: where the value is computed, so that no
	// input from outside the gateway can reach it.
	derived string
}

func breaksTrace(mutate func(*bereanv1.RetrievalTrace)) func(*turn.Turn) {
	return func(t *turn.Turn) { mutate(t.Attempts[0].Trace) }
}

func breaksFailure(mutate func(*bereanv1.GenerationFailure)) func(*turn.Turn) {
	return func(t *turn.Turn) { mutate(t.Attempts[0].Failure) }
}

const (
	byRunner   = "turn.Runner sets Overall and the attempt count together, in one place"
	byVerifier = "produced by the verify engine, the gateway's own judgement, not by Catena"
)

// Keyed by constraint name as Postgres reports it. Inline column CHECKs carry
// the name Postgres gave them, `<table>_<column>_check`.
var constraintLedger = map[string]constraint{
	// trace.responses
	"responses_answer_absent_iff_generation_failed": {breach: func(t *turn.Turn) { t.Answer = nil }},
	"responses_attempts_check": {breach: func(t *turn.Turn) {
		t.Attempts = append(t.Attempts, turn.Attempt{Number: 3, Trace: retrievalTrace()})
	}},
	"responses_confidence_absent_iff_generation_failed": {derived: "confidence is derived by verify.Confidence, and enumValue refuses an unset level"},
	"responses_confidence_reason_not_blank":             {derived: "verify.Confidence always joins at least two clauses"},
	"responses_degraded_is_second_attempt":              {derived: byRunner},
	"responses_gateway_version_present":                 {derived: "NewStore refuses a blank build version (TestBothConstructorsRefuseAnUnnamedBuild)"},
	"responses_generation_failed_is_second_attempt":     {derived: byRunner},
	"responses_profile_check":                           {breach: func(t *turn.Turn) { t.Profile = "  " }},
	"responses_query_check":                             {breach: func(t *turn.Turn) { t.Query = "  " }},
	"responses_regenerated_is_second_attempt":           {derived: byRunner},
	"responses_verified_is_first_attempt":               {derived: byRunner},

	// trace.traces -- everything but verify_us arrives from Catena
	"traces_attempt_check": {breach: func(t *turn.Turn) { t.Attempts[0].Number = 3 }},
	"traces_dim_check":     {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) { r.Dim = 0 })},
	"traces_embed_ms_check": {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) {
		r.Timings.EmbedMs = -1
	})},
	"traces_embedding_model_check": {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) { r.EmbeddingModel = " " })},
	"traces_generate_ms_check": {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) {
		r.Timings.GenerateMs = -1
	})},
	"traces_generation_model_check": {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) { r.GenerationModel = " " })},
	"traces_rewritten_query_check":  {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) { r.RewrittenQuery = " " })},
	"traces_search_ms_check": {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) {
		r.Timings.SearchMs = -1
	})},
	"traces_top_k_check":            {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) { r.TopK = 0 })},
	"traces_verify_us_non_negative": {derived: "measured by turn.Runner with a monotonic clock, so never negative"},

	// trace.candidates -- Catena's retrieval trace, in the order it sent it
	"candidates_corpus_id_check": {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) { r.Candidates[0].CorpusId = " " })},
	"candidates_locator_check":   {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) { r.Candidates[0].Locator = " " })},
	"candidates_rank_check":      {derived: "rank is the candidate's position plus one (writeAttempt)"},
	"candidates_reason_iff_excluded": {breach: breaksTrace(func(r *bereanv1.RetrievalTrace) {
		r.Candidates[0].Included = false
	})},

	// trace.verification_results, trace.answer_failures
	"verification_results_detail_iff_failure": {derived: byVerifier},
	"answer_failures_detail_check":            {derived: byVerifier},
	"answer_failures_ref_is_whole_or_absent":  {derived: byVerifier},
	"answer_failures_slot_check":              {derived: byVerifier},

	// trace.generation_failures -- Catena's, and so untrusted
	"generation_failures_completion_tokens_check": {
		base: generationFailedTurn,
		breach: breaksFailure(func(f *bereanv1.GenerationFailure) {
			f.CompletionTokens = -1
		}),
	},
	"generation_failures_detail_check": {
		base:   generationFailedTurn,
		breach: breaksFailure(func(f *bereanv1.GenerationFailure) { f.Detail = " " }),
	},
}

func (c constraint) turn() turn.Turn {
	if c.base != nil {
		return c.base()
	}
	return verifiedTurn()
}

// An entry that does neither is an unclassified constraint with a name on it,
// and one that does both says two different things about the same column.
func TestEveryLedgerEntryIsMirroredOrDerived(t *testing.T) {
	for name, entry := range constraintLedger {
		mirrored, derived := entry.breach != nil, entry.derived != ""
		if mirrored == derived {
			t.Errorf("%s: want exactly one of breach or derived (breach=%t derived=%t)", name, mirrored, derived)
		}
	}
}

// The mutation must be the only thing wrong with the turn. Without this the
// refusals below could all be passing on an unrelated defect in the base turns.
func TestTheBaseTurnsAreWellFormed(t *testing.T) {
	for name, base := range map[string]func() turn.Turn{
		"verified":          verifiedTurn,
		"generation-failed": generationFailedTurn,
	} {
		if err := validate(base()); err != nil {
			t.Errorf("%s base turn was refused: %v", name, err)
		}
	}
}

func TestValidateRefusesABreachOfEveryMirroredConstraint(t *testing.T) {
	for name, entry := range constraintLedger {
		if entry.breach == nil {
			continue
		}
		t.Run(name, func(t *testing.T) {
			breached := entry.turn()
			entry.breach(&breached)

			err := validate(breached)
			if !errors.Is(err, ErrIncomplete) {
				t.Fatalf("validate() = %v, want ErrIncomplete: the write would reach %s instead", err, name)
			}
		})
	}
}
