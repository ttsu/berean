package verify_test

import (
	"strings"
	"testing"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/verify"
)

func argument(citations ...*bereanv1.Citation) *bereanv1.Argument {
	return &bereanv1.Argument{
		Claim: "A claim.", Warrant: "A warrant.", Citations: citations,
	}
}

func TestTwoAuthoritativeCitationsOnTheFirstAttemptAreHigh(t *testing.T) {
	answer := &bereanv1.AnswerObject{Arguments: []*bereanv1.Argument{argument(
		cite(bindingID, "A 4.2", bindingText),
		cite(governingID, "B 21-4", governingText),
	)}}

	got := verify.Confidence(answer, spec(), 1)

	if got.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_HIGH {
		t.Errorf("level = %v, want HIGH", got.GetLevel())
	}
}

func TestOneAuthoritativeCitationIsMedium(t *testing.T) {
	answer := &bereanv1.AnswerObject{Arguments: []*bereanv1.Argument{argument(
		cite(bindingID, "A 4.2", bindingText),
		cite(advisoryID, "GS98 3.1", advisoryText),
	)}}

	got := verify.Confidence(answer, spec(), 1)

	if got.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM {
		t.Errorf("level = %v, want MEDIUM: advisory corroborates but does not count", got.GetLevel())
	}
}

func TestARegenerationIsNeverHigh(t *testing.T) {
	answer := &bereanv1.AnswerObject{Arguments: []*bereanv1.Argument{argument(
		cite(bindingID, "A 4.2", bindingText),
		cite(governingID, "B 21-4", governingText),
	)}}

	got := verify.Confidence(answer, spec(), 2)

	if got.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM {
		t.Errorf("level = %v, want MEDIUM after a regeneration", got.GetLevel())
	}
}

func TestTheSameCitationTwiceCountsOnce(t *testing.T) {
	// Otherwise "two or more" is satisfiable by repeating one citation, which
	// is a corroboration nobody performed.
	answer := &bereanv1.AnswerObject{Arguments: []*bereanv1.Argument{
		argument(cite(bindingID, "A 4.2", bindingText)),
		argument(cite(bindingID, "A 4.2", bindingText)),
	}}

	got := verify.Confidence(answer, spec(), 1)

	if got.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM {
		t.Errorf("level = %v, want MEDIUM: one citation cited twice is one citation", got.GetLevel())
	}
}

func TestADescriptiveAnswerIsLow(t *testing.T) {
	answer := &bereanv1.AnswerObject{Descriptions: []*bereanv1.Description{{
		Subject: "A study committee", Content: "It reported.",
		Citations: []*bereanv1.Citation{cite(bindingID, "A 4.2", bindingText)},
	}}}

	got := verify.Confidence(answer, spec(), 1)

	if got.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW {
		t.Errorf("level = %v, want LOW: a binding citation in a description rests on no authority", got.GetLevel())
	}
}

func TestAContestedAnswerIsLow(t *testing.T) {
	got := verify.Confidence(contestedAnswer(), spec(), 1)

	if got.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW {
		t.Errorf("level = %v, want LOW", got.GetLevel())
	}
	if !strings.Contains(got.GetReason(), "creation-days") {
		t.Errorf("reason = %q, want it to name the contested locus", got.GetReason())
	}
}

func TestAnHonestNonAnswerIsLow(t *testing.T) {
	answer := &bereanv1.AnswerObject{NoAnswerReason: "The corpora in scope do not address it."}

	got := verify.Confidence(answer, spec(), 1)

	if got.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW {
		t.Errorf("level = %v, want LOW", got.GetLevel())
	}
}

func TestTheReasonStatesTheCountsTheAttemptAndWhetherItWasContested(t *testing.T) {
	answer := &bereanv1.AnswerObject{Arguments: []*bereanv1.Argument{argument(
		cite(bindingID, "A 4.2", bindingText),
		cite(governingID, "B 21-4", governingText),
	)}}

	reason := verify.Confidence(answer, spec(), 1).GetReason()

	for _, want := range []string{"2 binding or governing", "first attempt", "not contested"} {
		if !strings.Contains(reason, want) {
			t.Errorf("reason = %q, want it to contain %q", reason, want)
		}
	}
}

func TestTheReasonIsNeverEmpty(t *testing.T) {
	// The trace column is NOT NULL with a non-blank check, and a confidence
	// with no stated finding is the introspection this field replaced.
	cases := map[string]*bereanv1.AnswerObject{
		"empty":       {},
		"contested":   contestedAnswer(),
		"non-answer":  {NoAnswerReason: "Silent."},
		"argued":      {Arguments: []*bereanv1.Argument{argument(cite(bindingID, "A 4.2", bindingText))}},
		"descriptive": {Descriptions: []*bereanv1.Description{{Subject: "s", Content: "c"}}},
	}
	for name, answer := range cases {
		for _, attempt := range []int32{1, 2} {
			if got := verify.Confidence(answer, spec(), attempt).GetReason(); strings.TrimSpace(got) == "" {
				t.Errorf("%s attempt %d: reason is empty", name, attempt)
			}
		}
	}
	if got := verify.DegradedConfidence().GetReason(); strings.TrimSpace(got) == "" {
		t.Error("degraded: reason is empty")
	}
}

func TestADegradedTurnIsLow(t *testing.T) {
	got := verify.DegradedConfidence()

	if got.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW {
		t.Errorf("level = %v, want LOW", got.GetLevel())
	}
}

func TestTheClaimedTierIsIgnoredWhenCounting(t *testing.T) {
	// Python claims binding on a corpus the profile holds at contrary. If the
	// count believed it, a fabricated tier would buy a HIGH confidence.
	answer := &bereanv1.AnswerObject{Arguments: []*bereanv1.Argument{argument(
		&bereanv1.Citation{CorpusId: contraryID, Locator: "D 4.2", Quote: contraryText,
			Tier: bereanv1.Tier_TIER_BINDING},
		&bereanv1.Citation{CorpusId: advisoryID, Locator: "GS98 3.1", Quote: advisoryText,
			Tier: bereanv1.Tier_TIER_BINDING},
	)}}

	got := verify.Confidence(answer, spec(), 1)

	if got.GetLevel() != bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW {
		t.Errorf("level = %v, want LOW; the claimed tiers were believed", got.GetLevel())
	}
}
