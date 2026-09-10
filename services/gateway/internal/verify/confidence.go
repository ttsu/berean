package verify

import (
	"fmt"
	"strings"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
)

// Confidence derives both halves of the confidence field from what
// verification found.
//
// Python populates neither and Go overwrites whatever arrives. A model-authored
// `reason` is introspection wearing a structured field's clothes, and a
// model-authored `level` is the same thing compressed into an enum, able to
// contradict the reason computed beside it (ADR-0020).
//
// The rule is fixed in INTEGRATION-SPEC rather than left to this function, so
// the enum means the same thing across runs and Phase 2 can read it:
//
//	high    two or more binding or governing citations, first attempt, not contested
//	medium  one binding or governing citation, or a regeneration occurred
//	low     descriptive only, or contested, or `no_answer_reason` set
//
// `low` is tested first because its three conditions are about the *kind* of
// answer this is, and an answer of that kind has no confidence to raise however
// many citations it carries: a contested answer with four binding citations in
// `descriptions` is still an answer that settles nothing.
func Confidence(answer *bereanv1.AnswerObject, spec *bereanv1.FilterSpec, attempt int32) *bereanv1.Confidence {
	tiers := make(map[string]bereanv1.Tier, len(spec.GetCorpora()))
	for _, entry := range spec.GetCorpora() {
		tiers[entry.GetCorpusId()] = entry.GetTier()
	}

	// Counted over `arguments` only, and distinct by `{corpus_id, locator}`.
	// The slot is what makes a claim affirmative, so a binding citation inside
	// a description corroborates nothing; and one citation repeated is one
	// citation, not the corroboration "two or more" is asking about.
	authoritative := make(map[string]bool)
	for _, argument := range answer.GetArguments() {
		for _, citation := range argument.GetCitations() {
			switch tiers[citation.GetCorpusId()] {
			case bereanv1.Tier_TIER_BINDING, bereanv1.Tier_TIER_GOVERNING:
				authoritative[refKey(citation.GetCorpusId(), citation.GetLocator())] = true
			}
		}
	}
	count := len(authoritative)

	contested := answer.GetContested().GetIsContested()
	silent := strings.TrimSpace(answer.GetNoAnswerReason()) != ""

	level := bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_MEDIUM
	switch {
	case contested || silent || count == 0:
		level = bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW
	case count >= 2 && attempt == 1:
		level = bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_HIGH
	}

	clauses := []string{citationClause(count), attemptClause(attempt)}
	if contested {
		clauses = append(clauses, contestedClause(answer.GetContested().GetLocus()))
	} else {
		clauses = append(clauses, "not contested")
	}
	if silent {
		clauses = append(clauses, "no_answer_reason set")
	}

	return &bereanv1.Confidence{Level: level, Reason: strings.Join(clauses, ", ")}
}

// DegradedConfidence is the confidence of a turn that shipped nothing.
//
// It is not derived from the answer, because there is no answer: degradation
// is the verification system working, and what it found is that two attempts
// running could not be sourced.
func DegradedConfidence() *bereanv1.Confidence {
	return &bereanv1.Confidence{
		Level:  bereanv1.ConfidenceLevel_CONFIDENCE_LEVEL_LOW,
		Reason: "no content was verified on either attempt, so nothing was shown",
	}
}

func citationClause(count int) string {
	switch count {
	case 0:
		return "no binding or governing citations"
	case 1:
		return "1 binding or governing citation"
	default:
		return fmt.Sprintf("%d binding or governing citations", count)
	}
}

func attemptClause(attempt int32) string {
	if attempt > 1 {
		return "regenerated"
	}
	return "first attempt"
}

func contestedClause(locus string) string {
	if locus == "" {
		return "contested"
	}
	return fmt.Sprintf("contested locus %s", locus)
}
