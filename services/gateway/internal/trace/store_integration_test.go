// Live-database assertions for the persistence path.
//
// What a fake store cannot answer is whether the transaction committed. Writes
// are visible to the session that made them whether or not they commit, so a
// store that never commits passes every in-process assertion and reports
// success over rows no other connection will ever see. That is what shipped
// once already in this repository, on the Python side, and it took a second
// connection to notice — so every readback here is on one.
//
// All invented content (ADR-0014). Nothing here reads the corpus tables, so
// unlike the corpus suite it borrows no real text and needs none.
//
// Catena's inability to write these tables is asserted where it belongs, in
// `tools/db/tests/catena_assertions.sql` under `make test-schema`: the role has
// no USAGE on the schema, so it fails on every trace table for one reason and
// no table grant can undo it. Migration 000004 adds columns to tables that
// already exist and grants nothing, so that assertion covers this task's
// change without restating it here.
//
// Skipped when BEREAN_DATABASE_URL is unset. Run it with `make test-gateway-db`.
package trace_test

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/trace"
	"github.com/ttsu/berean/services/gateway/internal/turn"
)

// The probe turns. Fixed rather than random so a run interrupted halfway leaves
// rows this suite can clear on its next start, and in a range the schema
// suite's own probes do not use.
const (
	verifiedID   = "00000000-0000-4000-8000-0000000009a1"
	degradedID   = "00000000-0000-4000-8000-0000000009a2"
	atomicID     = "00000000-0000-4000-8000-0000000009a3"
	probeVersion = "0.0.0-probe"
)

// connect opens a connection as the gateway role.
func connect(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("BEREAN_DATABASE_URL")
	if dsn == "" {
		t.Skip("BEREAN_DATABASE_URL unset; run `make test-gateway-db` against a live database")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}

// store is the subject, on its own pool — a real one, opened the way
// production opens it.
func store(t *testing.T) *trace.Store {
	t.Helper()
	dsn := os.Getenv("BEREAN_DATABASE_URL")
	if dsn == "" {
		t.Skip("BEREAN_DATABASE_URL unset; run `make test-gateway-db` against a live database")
	}
	subject, err := trace.Open(dsn, probeVersion)
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { subject.Close() })
	return subject
}

// reading is the second connection every readback goes through. A store that
// never commits is invisible to it, which is the whole point.
func reading(t *testing.T) *sql.DB { return connect(t) }

// clear removes a probe turn, before and after. The cascade takes the attempts,
// candidates, verification results and answer failures with it.
func clear(t *testing.T, requestID string) {
	t.Helper()
	db := connect(t)
	wipe := func() {
		if _, err := db.Exec(`DELETE FROM trace.responses WHERE request_id = $1`, requestID); err != nil {
			t.Fatalf("clear %s: %v", requestID, err)
		}
	}
	wipe()
	t.Cleanup(wipe)
}

func confidence(level bereanv1.ConfidenceLevel, reason string) *bereanv1.Confidence {
	return &bereanv1.Confidence{Level: level, Reason: reason}
}

// probeTrace is one attempt's retrieval trace, with candidates deliberately
// **not** in score order: rank is the order Python sent them in, and a store
// that re-sorted would be inventing a ranking nobody produced.
func probeTrace() *bereanv1.RetrievalTrace {
	return &bereanv1.RetrievalTrace{
		RewrittenQuery:  "An invented question about an invented locus?",
		EmbeddingModel:  "probe-embedder",
		Dim:             1024,
		GenerationModel: "probe-generator:tag",
		TopK:            20,
		Candidates: []*bereanv1.Candidate{
			{CorpusId: "probe-0000-invented", Locator: "Probe 1.1", Score: 0.91, Included: true},
			{CorpusId: "probe-0000-invented", Locator: "Probe 9.9", Score: 0.12, Included: false,
				ExclusionReason: "below the retrieval depth actually used"},
			{CorpusId: "probe-0001-invented", Locator: "Probe 2.4", Score: 0.55, Included: true},
		},
		Timings: &bereanv1.Timings{EmbedMs: 11, SearchMs: 22, GenerateMs: 333},
	}
}

// TestWriteRecordsAVerifiedTurn is the happy path, read back on a second
// connection.
func TestWriteRecordsAVerifiedTurn(t *testing.T) {
	clear(t, verifiedID)

	answer := &bereanv1.AnswerObject{
		Position: "An invented position.",
		Arguments: []*bereanv1.Argument{{
			Claim: "An invented claim.",
			Citations: []*bereanv1.Citation{{
				CorpusId: "probe-0000-invented",
				Locator:  "Probe 1.1",
				Quote:    "An invented quotation, long enough to clear the forty-character floor.",
			}},
		}},
		Confidence: confidence(bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM,
			"1 binding or governing citation, first attempt, not contested"),
	}

	subject := turn.Turn{
		RequestID: verifiedID,
		Query:     "An invented question about an invented locus?",
		Profile:   "probe",
		Answer:    answer,
		Overall:   bereanv1.OverallResult_OVERALL_RESULT_VERIFIED,
		Attempts: []turn.Attempt{{
			Number: 1,
			Answer: answer,
			Trace:  probeTrace(),
			Results: []*bereanv1.VerificationResult{{
				CitationRef: &bereanv1.CitationRef{
					CorpusId: "probe-0000-invented", Locator: "Probe 1.1"},
				LocatorResolved: true, QuoteMatched: true,
				TierPermitted: true, LicensePermitted: true,
			}},
			Verify: 7 * time.Millisecond,
		}},
	}

	if err := store(t).Write(context.Background(), subject); err != nil {
		t.Fatalf("write: %v", err)
	}

	db := reading(t)

	var (
		profile, overall, level, reason, version string
		attempts                                 int
		answerJSON                               []byte
	)
	err := db.QueryRow(
		`SELECT profile, overall_result, confidence_level, confidence_reason,
		        gateway_version, attempts, answer
		   FROM trace.responses WHERE request_id = $1`, verifiedID).
		Scan(&profile, &overall, &level, &reason, &version, &attempts, &answerJSON)
	if err != nil {
		t.Fatalf("the response is not visible to another connection: %v", err)
	}

	if profile != "probe" {
		t.Errorf("profile = %q", profile)
	}
	if overall != "verified" {
		t.Errorf("overall_result = %q", overall)
	}
	if level != "medium" {
		t.Errorf("confidence_level = %q", level)
	}
	if reason == "" {
		t.Error("confidence_reason is empty")
	}
	if attempts != 1 {
		t.Errorf("attempts = %d", attempts)
	}
	// The column migration 000004 adds. Without it, rows from two builds are
	// indistinguishable in the one table Phase 2 reads.
	if version != probeVersion {
		t.Errorf("gateway_version = %q, want %q", version, probeVersion)
	}

	// The answer survives as protojson the contract can read back, spelled the
	// way Phase 2 will query it.
	var decoded map[string]any
	if err := json.Unmarshal(answerJSON, &decoded); err != nil {
		t.Fatalf("the answer column is not JSON: %v", err)
	}
	if decoded["position"] != "An invented position." {
		t.Errorf("answer.position = %v", decoded["position"])
	}

	// Queried through jsonb by the contract's own field name, which is what
	// `UseProtoNames` buys and what UC-2's metric will be counted with.
	var silent sql.NullString
	if err := db.QueryRow(
		`SELECT answer->>'no_answer_reason' FROM trace.responses WHERE request_id = $1`,
		verifiedID).Scan(&silent); err != nil {
		t.Fatalf("querying the answer by proto field name: %v", err)
	}
	if silent.Valid {
		t.Errorf("no_answer_reason = %q on an answer that set none", silent.String)
	}

	assertAttemptRows(t, db, verifiedID, 1, 7)
}

// assertAttemptRows checks the per-attempt tables for one attempt.
func assertAttemptRows(t *testing.T, db *sql.DB, requestID string, attempt, verifyMS int64) {
	t.Helper()

	var (
		rewritten, embedding, generation string
		dim, topK                        int
		embedMS, searchMS, generateMS    int64
		storedVerifyMS                   int64
	)
	err := db.QueryRow(
		`SELECT rewritten_query, embedding_model, dim, generation_model, top_k,
		        embed_ms, search_ms, generate_ms, verify_ms
		   FROM trace.traces WHERE request_id = $1 AND attempt = $2`, requestID, attempt).
		Scan(&rewritten, &embedding, &dim, &generation, &topK,
			&embedMS, &searchMS, &generateMS, &storedVerifyMS)
	if err != nil {
		t.Fatalf("attempt %d trace: %v", attempt, err)
	}

	if generation != "probe-generator:tag" || topK != 20 {
		t.Errorf("attempt %d recorded generation_model=%q top_k=%d — the two settings"+
			" most likely to move a baseline silently", attempt, generation, topK)
	}
	if dim != 1024 || embedding != "probe-embedder" {
		t.Errorf("attempt %d recorded embedding %s/%d", attempt, embedding, dim)
	}
	if embedMS != 11 || searchMS != 22 || generateMS != 333 {
		t.Errorf("attempt %d stage timings = %d/%d/%d", attempt, embedMS, searchMS, generateMS)
	}
	// The column migration 000004 adds. A turn's wall clock is the sum of the
	// four, and with one missing the trace tables cannot say where it went.
	if storedVerifyMS != verifyMS {
		t.Errorf("attempt %d verify_ms = %d, want %d", attempt, storedVerifyMS, verifyMS)
	}

	// Rank is the order Python sent, not score order. The middle candidate is
	// the excluded one and scores lowest; a store that sorted would put it
	// last, and @k would then mean something nobody measured.
	rows, err := db.Query(
		`SELECT rank, locator, included, exclusion_reason
		   FROM trace.candidates WHERE request_id = $1 AND attempt = $2 ORDER BY rank`,
		requestID, attempt)
	if err != nil {
		t.Fatalf("attempt %d candidates: %v", attempt, err)
	}
	defer rows.Close()

	type row struct {
		rank      int
		locator   string
		included  bool
		exclusion string
	}
	var got []row
	for rows.Next() {
		var r row
		if err := rows.Scan(&r.rank, &r.locator, &r.included, &r.exclusion); err != nil {
			t.Fatalf("scan candidate: %v", err)
		}
		got = append(got, r)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("candidates: %v", err)
	}

	want := []row{
		{1, "Probe 1.1", true, ""},
		{2, "Probe 9.9", false, "below the retrieval depth actually used"},
		{3, "Probe 2.4", true, ""},
	}
	if len(got) != len(want) {
		t.Fatalf("attempt %d wrote %d candidates, want %d", attempt, len(got), len(want))
	}
	for index, candidate := range got {
		if candidate != want[index] {
			t.Errorf("attempt %d candidate %d = %+v, want %+v",
				attempt, index+1, candidate, want[index])
		}
	}
}

// TestWriteRecordsADegradedTurn is the checkbox the plan states first: a trace
// for every response, including the ones that shipped nothing.
//
// It also holds the two records ADR-0024 split apart together. The answer-level
// failures and the per-citation results are written from the same attempt, in
// the same transaction, and a degradation reconstructible from only half of
// that record is one nobody can diagnose.
func TestWriteRecordsADegradedTurn(t *testing.T) {
	clear(t, degradedID)

	// What Python sent on each failed attempt, kept as it arrived.
	rejected := &bereanv1.AnswerObject{
		Arguments: []*bereanv1.Argument{{Claim: "An invented claim with nothing behind it."}},
	}

	attempt := func(number int32) turn.Attempt {
		return turn.Attempt{
			Number: number,
			Answer: rejected,
			Trace:  probeTrace(),
			Results: []*bereanv1.VerificationResult{{
				CitationRef: &bereanv1.CitationRef{
					CorpusId: "no-such-corpus-invented", Locator: "Nowhere 1.1"},
				LocatorResolved: false, QuoteMatched: false,
				TierPermitted: false, LicensePermitted: false,
				FailureDetail: "no chunk carries that corpus ID and locator",
			}},
			Failures: []*bereanv1.AnswerFailure{{
				Code:   bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CITATIONS_REQUIRED,
				Slot:   "arguments[0]",
				Detail: "an argument carries no citations",
			}, {
				Code: bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_ARGUMENT_LACKS_AUTHORITY,
				Slot: "arguments[0]",
				CitationRef: &bereanv1.CitationRef{
					CorpusId: "probe-0001-invented", Locator: "Probe 2.4"},
				Detail: "no citation in this argument is binding or governing",
			}},
			Verify: 3 * time.Millisecond,
		}
	}

	// Exactly what internal/turn produces on degradation: no content, and the
	// derived confidence alone.
	subject := turn.Turn{
		RequestID: degradedID,
		Query:     "An invented question about an invented locus?",
		Profile:   "probe",
		Answer: &bereanv1.AnswerObject{
			Confidence: confidence(bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW,
				"no content was verified on either attempt, so nothing was shown"),
		},
		Overall:  bereanv1.OverallResult_OVERALL_RESULT_DEGRADED,
		Attempts: []turn.Attempt{attempt(1), attempt(2)},
	}

	if err := store(t).Write(context.Background(), subject); err != nil {
		t.Fatalf("a degraded turn was not persisted: %v", err)
	}

	db := reading(t)

	var overall string
	var attempts int
	if err := db.QueryRow(
		`SELECT overall_result, attempts FROM trace.responses WHERE request_id = $1`,
		degradedID).Scan(&overall, &attempts); err != nil {
		t.Fatalf("the degraded response is not visible to another connection: %v", err)
	}
	if overall != "degraded" || attempts != 2 {
		t.Errorf("overall_result=%q attempts=%d; degradation always follows exactly two"+
			" generation attempts (ADR-0024)", overall, attempts)
	}

	// Both attempts' traces, and both records, from each attempt.
	for _, number := range []int64{1, 2} {
		assertAttemptRows(t, db, degradedID, number, 3)

		var results, failures int
		if err := db.QueryRow(
			`SELECT (SELECT count(*) FROM trace.verification_results
			          WHERE request_id = $1 AND attempt = $2),
			        (SELECT count(*) FROM trace.answer_failures
			          WHERE request_id = $1 AND attempt = $2)`,
			degradedID, number).Scan(&results, &failures); err != nil {
			t.Fatalf("attempt %d counts: %v", number, err)
		}
		if results != 1 {
			t.Errorf("attempt %d wrote %d verification results, want 1", number, results)
		}
		if failures != 2 {
			t.Errorf("attempt %d wrote %d answer failures, want 2 — the two records"+
				" ADR-0024 split apart are written from the same attempt", number, failures)
		}
	}

	// The enum is what makes "which rule does this generator break most often"
	// a GROUP BY rather than a LIKE, and the derivation is what puts the
	// contract's codes in it.
	var code, slot, corpusID, locator string
	if err := db.QueryRow(
		`SELECT code, slot, corpus_id, locator FROM trace.answer_failures
		  WHERE request_id = $1 AND attempt = 1 AND code = 'argument-lacks-authority'`,
		degradedID).Scan(&code, &slot, &corpusID, &locator); err != nil {
		t.Fatalf("the derived failure code did not reach the enum column: %v", err)
	}
	if slot != "arguments[0]" || corpusID != "probe-0001-invented" || locator != "Probe 2.4" {
		t.Errorf("failure recorded slot=%q ref=%s %s", slot, corpusID, locator)
	}

	// A citation to a corpus that does not exist is precisely what check 1
	// records. No foreign key stands in the way of recording the fabrication.
	var fabricated int
	if err := db.QueryRow(
		`SELECT count(*) FROM trace.verification_results
		  WHERE request_id = $1 AND corpus_id = 'no-such-corpus-invented'`,
		degradedID).Scan(&fabricated); err != nil {
		t.Fatalf("count fabricated citations: %v", err)
	}
	if fabricated != 2 {
		t.Errorf("the fabricated citation was recorded %d times across two attempts", fabricated)
	}
}

// TestWriteIsAtomic. A crash mid-turn must persist nothing: a partial trace
// enters the Phase 2 dataset as a turn that retrieved nothing, and a row that
// lies is worse than a row that is missing.
//
// The failure is induced with two attempts carrying the same number, which the
// `trace.traces` primary key rejects on the second insert — after the response
// row and the first attempt's rows have already been written inside the
// transaction.
func TestWriteIsAtomic(t *testing.T) {
	clear(t, atomicID)

	answer := &bereanv1.AnswerObject{
		Confidence: confidence(bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW, "a probe"),
	}
	collides := turn.Attempt{
		Number: 1,
		Answer: answer,
		Trace:  probeTrace(),
		Verify: time.Millisecond,
	}

	subject := turn.Turn{
		RequestID: atomicID,
		Query:     "An invented question about an invented locus?",
		Profile:   "probe",
		Answer:    answer,
		Overall:   bereanv1.OverallResult_OVERALL_RESULT_DEGRADED,
		Attempts:  []turn.Attempt{collides, collides},
	}

	if err := store(t).Write(context.Background(), subject); err == nil {
		t.Fatal("a turn with two attempts numbered 1 was accepted")
	}

	db := reading(t)
	for _, table := range []string{
		"trace.responses", "trace.traces", "trace.candidates",
		"trace.verification_results", "trace.answer_failures",
	} {
		var count int
		if err := db.QueryRow(
			`SELECT count(*) FROM `+table+` WHERE request_id = $1`, atomicID).Scan(&count); err != nil {
			t.Fatalf("count %s: %v", table, err)
		}
		if count != 0 {
			t.Errorf("%s kept %d rows from a turn that failed to write", table, count)
		}
	}
}

// TestWriteRefusesAnIncompleteTurn asserts the refusal is typed, so a caller
// can tell a contract violation from an outage. The two want opposite
// responses: one is a bug, the other is a retry.
func TestWriteRefusesAnIncompleteTurn(t *testing.T) {
	subject := turn.Turn{
		RequestID: atomicID,
		Query:     "An invented question?",
		Profile:   "probe",
		Answer: &bereanv1.AnswerObject{
			Confidence: confidence(bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW, "a probe"),
		},
		Overall:  bereanv1.OverallResult_OVERALL_RESULT_DEGRADED,
		Attempts: []turn.Attempt{{Number: 1, Trace: nil}},
	}

	err := store(t).Write(context.Background(), subject)
	if !errors.Is(err, trace.ErrIncomplete) {
		t.Fatalf("err = %v, want ErrIncomplete", err)
	}
}
