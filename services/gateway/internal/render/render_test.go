// Assertions for what a reader is shown.
//
// All invented text (ADR-0014). Nothing here is corpus text and nothing here
// needs a database: the renderer is handed a finished turn and a description of
// each corpus in scope, and everything under test is a property of the output.
package render_test

import (
	"strings"
	"testing"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/render"
	"github.com/ttsu/berean/services/gateway/internal/turn"
)

const (
	bindingID    = "alpha-1702-revised"
	contraryID   = "alpha-1650-original"
	advisoryID   = "gamma-study-1998"
	bindingQuote = "The assembly of elders shall meet on the first day of the fourth month."
	otherQuote   = "The elders of the older assembly met whenever the weather permitted them."
	rulingQuote  = "The assembly affirms that a diversity of views on this question is permitted."
)

func sources() render.Sources {
	return render.Sources{
		bindingID: {
			Work:    "The Book of Assembly Order",
			Edition: "1702 revision",
			Tier:    bereanv1.Tier_TIER_BINDING,
		},
		contraryID: {
			Work:    "The Book of Assembly Order",
			Edition: "1650 original",
			Tier:    bereanv1.Tier_TIER_CONTRARY,
			Label:   "the older assembly's text, not this one's",
		},
		advisoryID: {
			Work:    "Report of the Study Committee",
			Edition: "as adopted in 1998",
			Tier:    bereanv1.Tier_TIER_ADVISORY,
		},
	}
}

func verified(answer *bereanv1.AnswerObject) turn.Turn {
	return turn.Turn{
		RequestID: "00000000-0000-4000-8000-00000000000a",
		Query:     "when does the assembly meet?",
		Profile:   "example",
		Answer:    answer,
		Overall:   bereanv1.OverallResult_OVERALL_RESULT_VERIFIED,
		Attempts:  []turn.Attempt{{Number: 1}},
	}
}

func rendered(t *testing.T, turned turn.Turn) string {
	t.Helper()
	var out strings.Builder
	if err := render.Answer(&out, turned, sources()); err != nil {
		t.Fatalf("Answer: %v", err)
	}
	return out.String()
}

// The four things a reader needs to check a citation by hand: which corpus,
// which edition of it, where in it, and what standing this tradition gives it.
func TestACitationRendersWithCorpusEditionLocatorAndTier(t *testing.T) {
	out := rendered(t, verified(&bereanv1.AnswerObject{
		Position: "The assembly meets annually.",
		Arguments: []*bereanv1.Argument{{
			Claim:     "The assembly meets once a year.",
			Citations: []*bereanv1.Citation{{CorpusId: bindingID, Locator: "A 4.2", Quote: bindingQuote}},
		}},
		Confidence: &bereanv1.Confidence{
			Level: bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM, Reason: "one binding citation",
		},
	}))

	for _, want := range []string{
		"[binding] " + bindingID + " A 4.2",
		"The Book of Assembly Order (1702 revision)",
		bindingQuote,
	} {
		if !strings.Contains(out, want) {
			t.Errorf("rendered answer is missing %q\n---\n%s", want, out)
		}
	}
}

// UC-3 in one line: two editions of one work, and the reader must be able to
// tell which one answered.
func TestTwoEditionsOfOneWorkRenderDistinguishably(t *testing.T) {
	out := rendered(t, verified(&bereanv1.AnswerObject{
		Descriptions: []*bereanv1.Description{{
			Subject: "the older assembly",
			Content: "It met at need.",
			Citations: []*bereanv1.Citation{
				{CorpusId: bindingID, Locator: "A 4.2", Quote: bindingQuote},
				{CorpusId: contraryID, Locator: "A 4.2", Quote: otherQuote},
			},
		}},
		Confidence: &bereanv1.Confidence{
			Level: bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW, Reason: "descriptive only",
		},
	}))

	if !strings.Contains(out, "(1702 revision)") || !strings.Contains(out, "(1650 original)") {
		t.Errorf("the two editions do not both name themselves\n---\n%s", out)
	}
}

// Without the label a reader sees another tradition's position with nothing
// marking it as such, which is the failure the tier system exists to prevent.
func TestAContraryCitationRendersWithItsProfileLabel(t *testing.T) {
	out := rendered(t, verified(&bereanv1.AnswerObject{
		ContraryPositions: []*bereanv1.ContraryPosition{{
			Position:  "The older assembly met at need.",
			HeldBy:    []string{"the older assembly"},
			Citations: []*bereanv1.Citation{{CorpusId: contraryID, Locator: "A 4.2", Quote: otherQuote}},
		}},
		Confidence: &bereanv1.Confidence{
			Level: bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW, Reason: "descriptive only",
		},
	}))

	if !strings.Contains(out, "contrary: the older assembly's text, not this one's") {
		t.Errorf("the contrary citation carries no label\n---\n%s", out)
	}
}

// A tier that needs no label must not grow one, and the label line must not be
// printed empty — an empty label line reads as a source with an unstated
// caveat.
func TestATierWithNoLabelRendersNoLabelLine(t *testing.T) {
	out := rendered(t, verified(&bereanv1.AnswerObject{
		Arguments: []*bereanv1.Argument{{
			Claim:     "The assembly meets once a year.",
			Citations: []*bereanv1.Citation{{CorpusId: bindingID, Locator: "A 4.2", Quote: bindingQuote}},
		}},
		Confidence: &bereanv1.Confidence{
			Level: bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM, Reason: "one binding citation",
		},
	}))

	if strings.Contains(out, "binding:") {
		t.Errorf("a binding citation grew a label line\n---\n%s", out)
	}
}

// "I can't source this adequately" is the whole of a degraded answer. Nothing
// from either attempt survives into it — not a partial answer, not a warning
// beside one.
func TestADegradedTurnRendersTheRefusalAndNothingElse(t *testing.T) {
	degraded := turn.Turn{
		RequestID: "00000000-0000-4000-8000-00000000000b",
		Query:     "when does the assembly meet?",
		Profile:   "example",
		Answer: &bereanv1.AnswerObject{Confidence: &bereanv1.Confidence{
			Level:  bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW,
			Reason: "no content was verified on either attempt, so nothing was shown",
		}},
		Overall: bereanv1.OverallResult_OVERALL_RESULT_DEGRADED,
		// Both attempts carry the answers verification refused. A renderer
		// that reads them is the one bug this test exists to catch.
		Attempts: []turn.Attempt{
			{Number: 1, Answer: &bereanv1.AnswerObject{Position: "The assembly meets on the fourth Tuesday."}},
			{Number: 2, Answer: &bereanv1.AnswerObject{Position: "The assembly meets on the fourth Tuesday."}},
		},
	}

	out := rendered(t, degraded)

	if !strings.Contains(out, "I can't source this adequately") {
		t.Errorf("a degraded turn does not say so\n---\n%s", out)
	}
	if strings.Contains(out, "fourth Tuesday") {
		t.Errorf("a refused attempt's prose reached the output\n---\n%s", out)
	}
}

// UC-2 and UC-5 mean opposite things. A reader must be able to tell "the
// corpus is silent" from "I could not source this" without reading a trace.
func TestAnHonestNonAnswerRendersDistinctlyFromARefusal(t *testing.T) {
	const reason = "No document in scope addresses the question."
	silent := rendered(t, verified(&bereanv1.AnswerObject{
		NoAnswerReason: reason,
		Confidence: &bereanv1.Confidence{
			Level: bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW, Reason: "no_answer_reason set",
		},
	}))

	if !strings.Contains(silent, reason) {
		t.Errorf("the model's own statement of why is not shown\n---\n%s", silent)
	}
	if strings.Contains(silent, "I can't source this adequately") {
		t.Errorf("silence rendered as a refusal\n---\n%s", silent)
	}
	if !strings.Contains(silent, "silent") {
		t.Errorf("nothing in the output names the event as silence\n---\n%s", silent)
	}
}

// The confidence is the one Go-authored string a reader sees, and both halves
// of it are derived. A level with no reason beside it is the self-assessment
// the derivation exists to replace.
func TestTheConfidenceRendersBothHalves(t *testing.T) {
	out := rendered(t, verified(&bereanv1.AnswerObject{
		Arguments: []*bereanv1.Argument{{
			Claim:     "The assembly meets once a year.",
			Citations: []*bereanv1.Citation{{CorpusId: bindingID, Locator: "A 4.2", Quote: bindingQuote}},
		}},
		Confidence: &bereanv1.Confidence{
			Level:  bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM,
			Reason: "one binding or governing citation, first attempt, not contested",
		},
	}))

	if !strings.Contains(out, "medium") ||
		!strings.Contains(out, "one binding or governing citation, first attempt, not contested") {
		t.Errorf("the confidence is not rendered in full\n---\n%s", out)
	}
}

// A contested answer reports the state of the debate and picks no side. The
// locus is named because it is the profile's own identifier for the question
// being held open.
func TestAContestedAnswerNamesTheLocusAndTheStateOfDebate(t *testing.T) {
	out := rendered(t, verified(&bereanv1.AnswerObject{
		Contested: &bereanv1.Contested{
			IsContested:   true,
			Locus:         "meeting-frequency",
			StateOfDebate: "The committee reported: " + rulingQuote,
			Citations: []*bereanv1.Citation{
				{CorpusId: advisoryID, Locator: "GS98 Rec.4", Quote: rulingQuote},
			},
		},
		Confidence: &bereanv1.Confidence{
			Level: bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW, Reason: "contested: meeting-frequency",
		},
	}))

	for _, want := range []string{"contested", "meeting-frequency", rulingQuote} {
		if !strings.Contains(out, want) {
			t.Errorf("rendered answer is missing %q\n---\n%s", want, out)
		}
	}
}

// A corpus the renderer was given no description for still renders. Every
// citation reaching here has passed verification, so this cannot happen without
// a row disappearing mid-turn — and the honest rendering of that is the corpus
// ID the citation actually carries, not a discarded answer.
func TestACitationToAnUndescribedCorpusStillRenders(t *testing.T) {
	out := rendered(t, verified(&bereanv1.AnswerObject{
		Descriptions: []*bereanv1.Description{{
			Subject:   "an undescribed source",
			Content:   "It says something.",
			Citations: []*bereanv1.Citation{{CorpusId: "delta-1899-unknown", Locator: "D 1", Quote: otherQuote}},
		}},
		Confidence: &bereanv1.Confidence{
			Level: bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW, Reason: "descriptive only",
		},
	}))

	if !strings.Contains(out, "delta-1899-unknown D 1") {
		t.Errorf("an undescribed corpus did not render\n---\n%s", out)
	}
}
