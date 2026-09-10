// Unit assertions for the persistence path: what it refuses, and the one
// correspondence between the contract and the schema that nothing else holds.
//
// All invented content (ADR-0014). Nothing here needs a database — the live
// assertions are in store_integration_test.go and run under
// `make test-gateway-db`.
package trace

import (
	"os"
	"regexp"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/turn"
)

// migrations is the repository root's db/migrations, from this package.
const migrations = "../../../../db/migrations/"

// declaredLabels reads the labels a Postgres enum is created with.
//
// The migration is the source of truth for what the column accepts, and reading
// it is what lets this correspondence be asserted with nothing running. A hand-
// copied list here would be a third place for the proto, the schema and the
// test to disagree.
func declaredLabels(t *testing.T, file, typeName string) map[string]bool {
	t.Helper()
	source, err := os.ReadFile(migrations + file)
	if err != nil {
		t.Fatalf("read %s: %v", file, err)
	}
	// The body of `CREATE TYPE trace.<name> AS ENUM (...)`, whose quoted
	// labels are what the column accepts.
	pattern := regexp.MustCompile(`(?s)CREATE TYPE trace\.` + typeName + ` AS ENUM \((.*?)\);`)
	match := pattern.FindSubmatch(source)
	if match == nil {
		t.Fatalf("%s declares no trace.%s", file, typeName)
	}
	// Comments first. Every label in this schema is documented, and the prose
	// is full of apostrophes — "the corpus being silent is a pass", "I can't
	// source this adequately" — each of which pairs with the next quote and
	// swallows a real label. Dropping the comments is what makes the quoted
	// strings that remain exactly the enum's labels.
	body := regexp.MustCompile(`--[^\n]*`).ReplaceAllString(string(match[1]), "")

	labels := map[string]bool{}
	for _, quoted := range regexp.MustCompile(`'([^']+)'`).FindAllStringSubmatch(body, -1) {
		labels[quoted[1]] = true
	}
	if len(labels) == 0 {
		t.Fatalf("trace.%s declares no labels", typeName)
	}
	return labels
}

// TestEnumValuesMatchTheSchema is the assertion that keeps `enumValue`'s
// derivation honest.
//
// It runs in both directions on purpose. A proto value with no Postgres label
// is an insert that fails at the end of a turn, having already spent two
// generations; a Postgres label no proto value produces is a rule the schema
// thinks it can record and the contract can never emit — a `GROUP BY code` that
// silently reports zero for a rule nobody can raise.
func TestEnumValuesMatchTheSchema(t *testing.T) {
	cases := []struct {
		name     string
		file     string
		typeName string
		prefix   string
		constant map[int32]string
	}{
		{"overall result", "000002_trace_schema.up.sql", "overall_result",
			"OVERALL_RESULT_", bereanv1.OverallResult_name},
		{"confidence level", "000002_trace_schema.up.sql", "confidence_level",
			"CONFIDENCE_LEVEL_", bereanv1.ConfidenceLevel_name},
		{"answer failure code", "000003_answer_failures.up.sql", "answer_failure_code",
			"ANSWER_FAILURE_CODE_", bereanv1.AnswerFailureCode_name},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			declared := declaredLabels(t, testCase.file, testCase.typeName)
			produced := map[string]bool{}

			for _, constant := range testCase.constant {
				label, err := enumValue(testCase.prefix, constant)
				if strings.HasSuffix(constant, "UNSPECIFIED") {
					// Proto3's zero value, which is what an unset field looks
					// like. It has no label and must not acquire one.
					if err == nil {
						t.Errorf("%s translated to %q; unset must be refused", constant, label)
					}
					continue
				}
				if err != nil {
					t.Fatalf("%s: %v", constant, err)
				}
				if !declared[label] {
					t.Errorf("%s derives %q, which trace.%s does not declare",
						constant, label, testCase.typeName)
				}
				produced[label] = true
			}

			for label := range declared {
				if !produced[label] {
					t.Errorf("trace.%s declares %q, which no %s value produces",
						testCase.typeName, label, testCase.prefix)
				}
			}
		})
	}
}

// TestEnumValueRefusesAForeignConstant guards the derivation against being
// handed a constant from the wrong enum, which would otherwise be lowercased
// and sent to Postgres as a plausible-looking label.
func TestEnumValueRefusesAForeignConstant(t *testing.T) {
	if _, err := enumValue("OVERALL_RESULT_", "CONFIDENCE_LEVEL_HIGH"); err == nil {
		t.Fatal("a confidence level was accepted as an overall result")
	}
}

// answerObject is a minimal rendered answer: enough to be recordable, and
// invented throughout.
func answerObject() *bereanv1.AnswerObject {
	return &bereanv1.AnswerObject{
		Confidence: &bereanv1.Confidence{
			Level:  bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM,
			Reason: "1 binding or governing citation, first attempt, not contested",
		},
	}
}

// retrievalTrace is a well-formed trace with one included candidate.
func retrievalTrace() *bereanv1.RetrievalTrace {
	return &bereanv1.RetrievalTrace{
		RewrittenQuery:  "An invented question?",
		EmbeddingModel:  "probe-embedder",
		Dim:             1024,
		GenerationModel: "probe-generator:tag",
		TopK:            20,
		Candidates: []*bereanv1.Candidate{
			{CorpusId: "probe-0000-invented", Locator: "Probe 1.1", Score: 0.9, Included: true},
		},
		Timings: &bereanv1.Timings{EmbedMs: 1, SearchMs: 2, GenerateMs: 3},
	}
}

func verifiedTurn() turn.Turn {
	return turn.Turn{
		RequestID: "00000000-0000-4000-8000-00000000000a",
		Query:     "An invented question?",
		Profile:   "probe",
		Answer:    answerObject(),
		Overall:   bereanv1.OverallResult_OVERALL_RESULT_VERIFIED,
		Attempts: []turn.Attempt{
			{Number: 1, Answer: answerObject(), Trace: retrievalTrace(), Verify: 4 * time.Millisecond},
		},
	}
}

// TestValidateAcceptsAWellFormedTurn keeps the refusals below meaningful: a
// validator that rejected everything would pass every one of them.
func TestValidateAcceptsAWellFormedTurn(t *testing.T) {
	if err := validate(verifiedTurn()); err != nil {
		t.Fatalf("a well-formed turn was refused: %v", err)
	}
}

func TestValidateRefusals(t *testing.T) {
	cases := []struct {
		name string
		// Mutates a well-formed turn into the shape under test.
		breaks func(*turn.Turn)
		// A fragment the message must carry, so the refusal points at the
		// thing that broke rather than at a column name.
		says string
	}{
		{
			name:   "no request ID",
			breaks: func(t *turn.Turn) { t.RequestID = "  " },
			says:   "request ID",
		},
		{
			name:   "no answer object",
			breaks: func(t *turn.Turn) { t.Answer = nil },
			says:   "answer object",
		},
		{
			name:   "no attempts",
			breaks: func(t *turn.Turn) { t.Attempts = nil },
			says:   "no attempts",
		},
		{
			// Catena always sends one. A response without it is a contract
			// violation, and the message must name Catena rather than the
			// `rewritten_query` column a constraint would name.
			name:   "an attempt with no retrieval trace",
			breaks: func(t *turn.Turn) { t.Attempts[0].Trace = nil },
			says:   "catena returned no retrieval trace",
		},
		{
			name: "a candidate excluded without a reason",
			breaks: func(t *turn.Turn) {
				t.Attempts[0].Trace.Candidates[0].Included = false
			},
			says: "exclusion_reason",
		},
		{
			name: "a candidate included with a reason",
			breaks: func(t *turn.Turn) {
				t.Attempts[0].Trace.Candidates[0].ExclusionReason = "below the retrieval depth"
			},
			says: "exclusion_reason",
		},
		{
			// A reason of three spaces satisfies `<> ''` while recording
			// exactly the unexplained exclusion the constraint exists to
			// prevent, which is why both sides trim.
			name: "a candidate excluded with a blank reason",
			breaks: func(t *turn.Turn) {
				t.Attempts[0].Trace.Candidates[0].Included = false
				t.Attempts[0].Trace.Candidates[0].ExclusionReason = "   "
			},
			says: "exclusion_reason",
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			subject := verifiedTurn()
			testCase.breaks(&subject)

			err := validate(subject)
			if err == nil {
				t.Fatal("the turn was accepted")
			}
			if !strings.Contains(err.Error(), testCase.says) {
				t.Errorf("message %q does not mention %q", err, testCase.says)
			}
		})
	}
}

// TestAnswerJSONUsesProtoNames pins the spelling Phase 2 queries this column
// by. protojson's default would write `noAnswerReason`, making it a third
// spelling of a field the proto and every document call `no_answer_reason`.
func TestAnswerJSONUsesProtoNames(t *testing.T) {
	answer := answerObject()
	answer.NoAnswerReason = "The corpora this profile treats as authoritative do not address it."

	encoded, err := answerJSON.Marshal(answer)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if !strings.Contains(string(encoded), `"no_answer_reason"`) {
		t.Errorf("answer JSON does not spell the field as the contract does: %s", encoded)
	}
}

// TestAnswerJSONOmitsUnsetFields holds the other half of the choice. One of the
// things this row is for is showing which fields Python populated, and emitting
// proto3 defaults would fill it with fields nobody sent — including a
// `confidence` on an attempt record where the contract says Python must send
// none.
func TestAnswerJSONOmitsUnsetFields(t *testing.T) {
	encoded, err := answerJSON.Marshal(&bereanv1.AnswerObject{})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if strings.TrimSpace(string(encoded)) != "{}" {
		t.Errorf("an empty answer encoded as %s", encoded)
	}
}

// TestAnswerJSONRoundTrips guards the column against holding something the
// contract cannot read back. The eval dataset is only useful if Phase 2 can
// parse it with the same generated code that wrote it.
func TestAnswerJSONRoundTrips(t *testing.T) {
	original := answerObject()
	original.Position = "An invented position."
	original.Arguments = []*bereanv1.Argument{{
		Claim: "An invented claim.",
		Citations: []*bereanv1.Citation{{
			CorpusId: "probe-0000-invented",
			Locator:  "Probe 1.1",
			Quote:    "An invented quotation, long enough to clear the forty-character floor.",
		}},
	}}

	encoded, err := answerJSON.Marshal(original)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var decoded bereanv1.AnswerObject
	if err := protojson.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if decoded.GetArguments()[0].GetCitations()[0].GetQuote() !=
		original.GetArguments()[0].GetCitations()[0].GetQuote() {
		t.Error("the citation did not survive the round trip")
	}
}

// TestOpenRefusesAnUnnamedBuild. A store that cannot say which build it is
// recording writes rows Phase 2 cannot separate, and the alternative — a
// default of "unknown" — is a fabricated build identifier in an audit log.
func TestOpenRefusesAnUnnamedBuild(t *testing.T) {
	if _, err := Open("postgres://invented/probe", "   "); err == nil {
		t.Fatal("a store with no build version was opened")
	}
}
