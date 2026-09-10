// Package trace writes a finished turn into the trace schema.
//
// These tables are simultaneously the audit log and the Phase 2 eval dataset,
// which is why they record the settings as well as the results and why the
// candidates are rows rather than a JSON array: recall@k is measured separately
// from answer faithfulness (SHARED §7), and it is a join over that table.
//
// The whole turn is one transaction, written after the turn ends, because
// `overall_result` and `confidence` are known only then. A crash mid-turn
// therefore persists nothing, which is the right trade: a partial trace enters
// the Phase 2 dataset as a turn that retrieved nothing, and a row that lies is
// worse than a row that is missing.
//
// **Persist before rendering.** A turn that reached a user and was never
// recorded is the one outcome this package exists to prevent, and the ordering
// is the whole of what prevents it. Verification refusing to ship is a recorded
// event; a write that failed after the answer was printed is not.
//
// This package writes and never reads back. Nothing here interprets an answer,
// re-derives a confidence, or decides an outcome — `internal/verify` and
// `internal/turn` did all of that, and a second opinion formed here could
// disagree with the one the user saw.
package trace

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"

	"google.golang.org/protobuf/encoding/protojson"

	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/ttsu/berean/services/gateway/internal/turn"
)

// ErrIncomplete is a turn that cannot be recorded as it stands.
//
// It is not a database failure and it is not a degraded answer. It means
// something upstream broke the contract — an attempt with no retrieval trace, a
// candidate marked included while carrying an exclusion reason, an outcome or a
// confidence level nobody set. Every one of those would otherwise surface as a
// Postgres constraint name at the end of a turn, naming a column rather than
// the attempt and the field that produced it.
//
// Distinguished from a database error because the two want opposite responses:
// an unreachable database is retried or reported as an outage, and this is a
// bug in the gateway or a Catena that is not honouring the contract.
var ErrIncomplete = errors.New("the turn is not complete enough to record")

// maxAttempts mirrors `internal/turn`: one generation plus at most one
// regeneration (ADR-0010), and the bound `trace.traces.attempt` holds.
const maxAttempts = 2

// answerJSON is how the answer object reaches `trace.responses.answer`.
//
// `UseProtoNames` because Phase 2 queries this column in the contract's own
// vocabulary — `answer->>'no_answer_reason'`, matching the proto, this schema
// and every document that discusses it. protojson's default would spell it
// `noAnswerReason` and make that a third spelling of one field.
//
// Unpopulated fields are omitted, which is what proto3 means by them, so the
// record stays the size of what the answer actually said. This column holds the
// **rendered** answer — the one the user saw, carrying Go's derived confidence
// rather than whatever Python sent — so it is not the place to look for which
// fields Python populated. The answers from attempts that failed are not stored
// at all, deliberately.
var answerJSON = protojson.MarshalOptions{UseProtoNames: true}

// Store writes turns. It holds the build identifier every row it writes carries.
type Store struct {
	db *sql.DB
	// The gateway build that produced the turn, from the linker-set version in
	// `cmd/berean`. The first question asked of a verification failure is which
	// build produced the answer, and Phase 2 compares a later retriever against
	// this phase's baseline out of one table.
	version string
}

// Open connects to Postgres as the gateway role.
//
// It does not verify the connection: the first write does, and a store that
// dialled eagerly would turn every unit test that constructs one into an
// integration test. The version must be non-empty — a store that cannot say
// which build it is recording writes rows Phase 2 cannot separate, and a
// default of "unknown" is a fabricated build identifier in an audit log.
func Open(dsn, version string) (*Store, error) {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, fmt.Errorf("open trace store: %w", err)
	}
	store, err := NewStore(db, version)
	if err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}

// NewStore wraps an existing pool. Open is the constructor production uses;
// this one exists for a caller that already holds a connection to the same
// database under the same role.
//
// It carries the version guard rather than leaving it to Open, because the
// empty string is the easiest value to arrive here by accident: `go build`
// without the linker flag leaves `cmd/berean`'s version at its default, and a
// store that accepted it would construct cleanly and then fail at the end of
// every turn — on the turn it had just spent two generations producing.
func NewStore(db *sql.DB, version string) (*Store, error) {
	if strings.TrimSpace(version) == "" {
		return nil, fmt.Errorf("trace store: no build version to record")
	}
	return &Store{db: db, version: version}, nil
}

// Close releases the pool.
func (s *Store) Close() error { return s.db.Close() }

// Write records one finished turn, including a degraded one.
//
// Degraded turns are recorded in full: the answer object that carries only the
// derived confidence, both attempts' retrieval traces, every citation the four
// checks rejected and every answer-level rule that broke. A degradation nobody
// can inspect afterwards is indistinguishable from a system that never
// answered, and the two mean opposite things.
//
// What is *not* recorded is a turn that errored — an unreachable Catena, an
// unreachable database. That is a failure of the system rather than an outcome
// of the verification system, and `internal/turn` returns it as an error
// without producing a Turn at all.
func (s *Store) Write(ctx context.Context, t turn.Turn) error {
	if err := validate(t); err != nil {
		return err
	}

	answer, err := answerJSON.Marshal(t.Answer)
	if err != nil {
		return fmt.Errorf("trace %s: marshalling the answer object: %w", t.RequestID, err)
	}

	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("trace %s: begin: %w", t.RequestID, err)
	}
	// Rolls back everything if any statement below fails or the caller's
	// context is cancelled. A no-op after a successful Commit.
	defer func() { _ = tx.Rollback() }()

	if err := writeResponse(ctx, tx, t, answer, s.version); err != nil {
		return err
	}
	for _, attempt := range t.Attempts {
		if err := writeAttempt(ctx, tx, t.RequestID, attempt); err != nil {
			return err
		}
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("trace %s: commit: %w", t.RequestID, err)
	}
	return nil
}

func writeResponse(ctx context.Context, tx *sql.Tx, t turn.Turn, answer []byte, version string) error {
	overall, err := enumValue("OVERALL_RESULT_", t.Overall.String())
	if err != nil {
		return fmt.Errorf("trace %s: overall_result: %w", t.RequestID, err)
	}
	level, err := enumValue("CONFIDENCE_LEVEL_", t.Answer.GetConfidence().GetLevel().String())
	if err != nil {
		return fmt.Errorf("trace %s: confidence.level: %w", t.RequestID, err)
	}

	_, err = tx.ExecContext(ctx,
		`INSERT INTO trace.responses
		     (request_id, profile, query, answer, overall_result,
		      confidence_level, confidence_reason, attempts, gateway_version)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
		t.RequestID, t.Profile, t.Query, string(answer), overall,
		level, t.Answer.GetConfidence().GetReason(), len(t.Attempts), version)
	if err != nil {
		return fmt.Errorf("trace %s: response: %w", t.RequestID, err)
	}
	return nil
}

func writeAttempt(ctx context.Context, tx *sql.Tx, requestID string, attempt turn.Attempt) error {
	trace := attempt.Trace
	timings := trace.GetTimings()

	// Microseconds, unlike the three stage timings Python reports beside it.
	// Those measure work taking tens to hundreds of milliseconds; verification
	// is string matching and indexed lookups, and Task 8 measured its p95 at
	// 0.68 ms. In milliseconds this column would read `0` for very nearly every
	// turn.
	_, err := tx.ExecContext(ctx,
		`INSERT INTO trace.traces
		     (request_id, attempt, rewritten_query, embedding_model, dim,
		      generation_model, top_k, embed_ms, search_ms, generate_ms, verify_us)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
		requestID, attempt.Number, trace.GetRewrittenQuery(), trace.GetEmbeddingModel(),
		trace.GetDim(), trace.GetGenerationModel(), trace.GetTopK(),
		timings.GetEmbedMs(), timings.GetSearchMs(), timings.GetGenerateMs(),
		attempt.Verify.Microseconds())
	if err != nil {
		return fmt.Errorf("trace %s attempt %d: %w", requestID, attempt.Number, err)
	}

	// `rank` has no counterpart in the proto: a repeated field carries its
	// order positionally, a table has no order without a column, and the order
	// is the whole of what @k means. It is therefore the position Python sent
	// them in, and nothing here re-sorts by score.
	for index, candidate := range trace.GetCandidates() {
		_, err := tx.ExecContext(ctx,
			`INSERT INTO trace.candidates
			     (request_id, attempt, rank, corpus_id, locator, score, included, exclusion_reason)
			 VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
			requestID, attempt.Number, index+1, candidate.GetCorpusId(), candidate.GetLocator(),
			candidate.GetScore(), candidate.GetIncluded(), candidate.GetExclusionReason())
		if err != nil {
			return fmt.Errorf("trace %s attempt %d candidate %d: %w",
				requestID, attempt.Number, index+1, err)
		}
	}

	for _, result := range attempt.Results {
		ref := result.GetCitationRef()
		_, err := tx.ExecContext(ctx,
			`INSERT INTO trace.verification_results
			     (request_id, attempt, corpus_id, locator,
			      locator_resolved, quote_matched, tier_permitted, license_permitted, failure_detail)
			 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
			requestID, attempt.Number, ref.GetCorpusId(), ref.GetLocator(),
			result.GetLocatorResolved(), result.GetQuoteMatched(), result.GetTierPermitted(),
			result.GetLicensePermitted(), result.GetFailureDetail())
		if err != nil {
			return fmt.Errorf("trace %s attempt %d verification result %s %s: %w",
				requestID, attempt.Number, ref.GetCorpusId(), ref.GetLocator(), err)
		}
	}

	// Written from the same attempt as the verification results, and inside the
	// same transaction: the two together are the whole of what the trust
	// boundary found, and a regeneration that carried one back without the
	// other would be reconstructible from only half of this record (ADR-0024).
	for _, failure := range attempt.Failures {
		code, err := enumValue("ANSWER_FAILURE_CODE_", failure.GetCode().String())
		if err != nil {
			return fmt.Errorf("trace %s attempt %d answer failure at %s: %w",
				requestID, attempt.Number, failure.GetSlot(), err)
		}
		ref := failure.GetCitationRef()
		_, err = tx.ExecContext(ctx,
			`INSERT INTO trace.answer_failures
			     (request_id, attempt, code, slot, corpus_id, locator, detail)
			 VALUES ($1, $2, $3, $4, $5, $6, $7)`,
			requestID, attempt.Number, code, failure.GetSlot(),
			ref.GetCorpusId(), ref.GetLocator(), failure.GetDetail())
		if err != nil {
			return fmt.Errorf("trace %s attempt %d answer failure %s at %s: %w",
				requestID, attempt.Number, code, failure.GetSlot(), err)
		}
	}

	return nil
}

// enumValue turns a proto enum constant into the Postgres enum label.
//
// Derived rather than mapped by hand. The Postgres types were written as the
// proto's values without their prefix, so the derivation *is* the rule, and a
// twelve-entry table restating it is a second place for the two to disagree.
// What holds the two together is a unit test that reads the migrations and
// asserts the correspondence in both directions, which needs no database and
// so runs in `make check`.
//
// UNSPECIFIED is refused rather than translated: it is proto3's zero value, so
// it is what an unset field looks like, and every one of these fields is set by
// Go itself. A row recording an outcome nobody decided is worse than a turn
// that failed to record.
func enumValue(prefix, constant string) (string, error) {
	name, found := strings.CutPrefix(constant, prefix)
	if !found {
		return "", fmt.Errorf("%w: %q is not a %s value", ErrIncomplete, constant, prefix)
	}
	if name == "UNSPECIFIED" {
		return "", fmt.Errorf("%w: unset", ErrIncomplete)
	}
	return strings.ReplaceAll(strings.ToLower(name), "_", "-"), nil
}

// validate refuses a turn whose shape the tables would reject anyway.
//
// It deliberately does not restate every constraint in the schema — the
// database is the backstop and it is the one that cannot be bypassed. What it
// covers is exactly the contract Catena is meant to honour, because those
// violations must reach the caller as ErrIncomplete: a bug in a service and an
// unreachable database want opposite responses, and a raw constraint violation
// is indistinguishable from an outage to a caller deciding whether to retry.
// A message reading `null value in column "rewritten_query"` also sends
// whoever reads it to the wrong service.
//
// What it does **not** refuse is an empty `corpus_id` or `locator` on a
// verification result. That is a citation the model emitted and check 1
// rejected, the table is where fabrications are recorded, and migration 000005
// removed the constraint that made this particular one unrecordable.
func validate(t turn.Turn) error {
	if strings.TrimSpace(t.RequestID) == "" {
		return fmt.Errorf("%w: no request ID", ErrIncomplete)
	}
	if t.Answer == nil {
		// Including a degraded turn, which carries the derived confidence and
		// nothing else. A nil answer here means the turn never finished.
		return fmt.Errorf("trace %s: %w: no answer object", t.RequestID, ErrIncomplete)
	}
	if len(t.Attempts) == 0 {
		return fmt.Errorf("trace %s: %w: no attempts", t.RequestID, ErrIncomplete)
	}

	for _, attempt := range t.Attempts {
		if attempt.Number < 1 || attempt.Number > maxAttempts {
			return fmt.Errorf("trace %s: %w: attempt %d, and ADR-0010 fixes the retry at"+
				" exactly one regeneration", t.RequestID, ErrIncomplete, attempt.Number)
		}
		if attempt.Trace == nil {
			return fmt.Errorf("trace %s attempt %d: %w: catena returned no retrieval trace",
				t.RequestID, attempt.Number, ErrIncomplete)
		}

		// The fields `trace.traces` requires. A trace that arrives half-filled
		// is the same contract violation as one that does not arrive, and the
		// two must not reach the caller as different kinds of error.
		for _, field := range []struct {
			name  string
			value string
		}{
			{"rewritten_query", attempt.Trace.GetRewrittenQuery()},
			{"embedding_model", attempt.Trace.GetEmbeddingModel()},
			{"generation_model", attempt.Trace.GetGenerationModel()},
		} {
			if strings.TrimSpace(field.value) == "" {
				return fmt.Errorf("trace %s attempt %d: %w: catena's retrieval trace carries no %s",
					t.RequestID, attempt.Number, ErrIncomplete, field.name)
			}
		}
		// Both are recorded so a Phase 2 comparison can hold them constant, and
		// both are meaningless at zero: a search of depth zero retrieves
		// nothing, which reads in the trace exactly like an empty corpus.
		if attempt.Trace.GetDim() <= 0 || attempt.Trace.GetTopK() <= 0 {
			return fmt.Errorf("trace %s attempt %d: %w: catena's retrieval trace reports dim=%d top_k=%d",
				t.RequestID, attempt.Number, ErrIncomplete,
				attempt.Trace.GetDim(), attempt.Trace.GetTopK())
		}

		for index, candidate := range attempt.Trace.GetCandidates() {
			// The proto says the reason is empty exactly when the candidate was
			// included. Held here as well as in the schema because an excluded
			// candidate with no reason is the retrieval regression the table
			// exists to make visible, arriving silently unexplained.
			if candidate.GetIncluded() == (strings.TrimSpace(candidate.GetExclusionReason()) != "") {
				return fmt.Errorf(
					"trace %s attempt %d candidate %d (%s %s): %w: included=%t with exclusion_reason=%q",
					t.RequestID, attempt.Number, index+1,
					candidate.GetCorpusId(), candidate.GetLocator(), ErrIncomplete,
					candidate.GetIncluded(), candidate.GetExclusionReason())
			}
		}
	}
	return nil
}
