// Unit assertions for the verification engine.
//
// **Every string of source text in this file is invented.** Substring
// containment and NFC normalisation are indifferent to provenance, so a real
// passage would buy the tests nothing and would put corpus text in the
// repository, which is the ADR-0014 violation the policy specifically warns
// about. The corpus IDs are invented too, and shaped like real ones so the
// edition-specific rule is not quietly unlearned here.
package verify_test

import (
	"context"
	"strings"
	"testing"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/corpus"
	"github.com/ttsu/berean/services/gateway/internal/normalise"
	"github.com/ttsu/berean/services/gateway/internal/verify"
)

// Invented, and comfortably over the 40-character floor so that a test about
// something else does not fail on the floor by accident.
const (
	bindingText   = "The assembly of elders shall meet on the first day of the fourth month, and shall not adjourn until the roll is read."
	governingText = "A commission of the court shall keep a full record of its proceedings and shall present that record at the next stated meeting."
	advisoryText  = "The committee observed that the practice varies between the northern and southern congregations, and did not recommend a change."
	contraryText  = "The convention of the year following resolved that no such requirement binds the conscience of any member congregation."
	rulingText    = "The assembly affirms that a diversity of views on this question is permitted among its teaching elders and ruling elders."
)

const (
	bindingID   = "alpha-1702-revised"
	governingID = "beta-order-2011"
	advisoryID  = "gamma-study-1998"
	contraryID  = "delta-1702-original"
	rulingID    = "gamma-study-1998"
	rulingLoc   = "GS98 Rec.4"
)

// store is a map, because the four checks are string matching and a map lookup
// is exactly what the database contributes to them. What a map cannot be wrong
// about — the schema qualification, the unique constraint, the grant — is
// asserted in the live-database suite instead.
type store map[string]corpus.Chunk

func (s store) Lookup(_ context.Context, corpusID, locator string) (corpus.Chunk, error) {
	chunk, ok := s[corpusID+"\x00"+locator]
	if !ok {
		return corpus.Chunk{}, corpus.ErrNotFound
	}
	return chunk, nil
}

func (s store) put(corpusID, locator, text string, license corpus.License) store {
	s[corpusID+"\x00"+locator] = corpus.Chunk{
		CorpusID: corpusID, Locator: locator, Text: text, License: license,
		// What ingestion would have written. A zero here would make every
		// quote mismatch in this file report a contract skew that is not there.
		NormalisationVersion: normalise.Version,
	}
	return s
}

func corpora() store {
	return store{}.
		put(bindingID, "A 4.2", bindingText, corpus.PublicDomain).
		put(governingID, "B 21-4", governingText, corpus.LocalOnly).
		put(advisoryID, "GS98 3.1", advisoryText, corpus.PublicDomain).
		put(contraryID, "D 4.2", contraryText, corpus.CCBY).
		put(rulingID, rulingLoc, rulingText, corpus.PublicDomain)
}

func spec() *bereanv1.FilterSpec {
	return &bereanv1.FilterSpec{
		TopK: 20,
		Corpora: []*bereanv1.CorpusFilter{
			{CorpusId: bindingID, Tier: bereanv1.Tier_TIER_BINDING},
			{CorpusId: governingID, Tier: bereanv1.Tier_TIER_GOVERNING},
			{CorpusId: advisoryID, Tier: bereanv1.Tier_TIER_ADVISORY},
			{CorpusId: contraryID, Tier: bereanv1.Tier_TIER_CONTRARY},
		},
	}
}

func loci() []*bereanv1.ContestedLocus {
	return []*bereanv1.ContestedLocus{{
		Locus:  "creation-days",
		Ruling: &bereanv1.CitationRef{CorpusId: rulingID, Locator: rulingLoc},
	}}
}

func cite(corpusID, locator, quote string) *bereanv1.Citation {
	return &bereanv1.Citation{CorpusId: corpusID, Locator: locator, Quote: quote}
}

// answered is the shape of a passing answer: one argument, one binding
// citation, nothing contested.
func answered() *bereanv1.AnswerObject {
	return &bereanv1.AnswerObject{
		Position: "The tradition requires the roll to be read before adjournment.",
		Arguments: []*bereanv1.Argument{{
			Claim:     "The roll is read before the court adjourns.",
			Warrant:   "The standard fixes the order of business.",
			Citations: []*bereanv1.Citation{cite(bindingID, "A 4.2", bindingText)},
		}},
	}
}

func engine(t *testing.T, s store, serveLocalOnly bool) *verify.Engine {
	t.Helper()
	return verify.New(s, serveLocalOnly)
}

func run(t *testing.T, e *verify.Engine, answer *bereanv1.AnswerObject) verify.Outcome {
	t.Helper()
	out, err := e.Verify(context.Background(), answer, spec(), loci())
	if err != nil {
		t.Fatalf("Verify: %v", err)
	}
	return out
}

// codes lists the answer-level failures, for assertions that care which rule
// broke rather than how it was worded.
func codes(out verify.Outcome) []bereanv1.AnswerFailureCode {
	got := make([]bereanv1.AnswerFailureCode, 0, len(out.Failures))
	for _, f := range out.Failures {
		got = append(got, f.GetCode())
	}
	return got
}

func hasCode(out verify.Outcome, want bereanv1.AnswerFailureCode) bool {
	for _, code := range codes(out) {
		if code == want {
			return true
		}
	}
	return false
}

func onlyResult(t *testing.T, out verify.Outcome) *bereanv1.VerificationResult {
	t.Helper()
	if len(out.Results) != 1 {
		t.Fatalf("results = %d, want exactly 1", len(out.Results))
	}
	return out.Results[0]
}

// --- the passing case ------------------------------------------------------

func TestAnAnswerWhoseCitationResolvesAndQuotesVerbatimPasses(t *testing.T) {
	out := run(t, engine(t, corpora(), false), answered())

	if !out.Passed() {
		t.Fatalf("Passed() = false, want true: results=%v failures=%v", out.Results, out.Failures)
	}
	result := onlyResult(t, out)
	if !result.GetLocatorResolved() || !result.GetQuoteMatched() ||
		!result.GetTierPermitted() || !result.GetLicensePermitted() {
		t.Errorf("checks = %v, want all true", result)
	}
	if result.GetFailureDetail() != "" {
		t.Errorf("failure_detail = %q, want empty when every check passed", result.GetFailureDetail())
	}
}

// --- check 1: the locator resolves ----------------------------------------

func TestALocatorThatNamesNoChunkFailsCheckOne(t *testing.T) {
	answer := answered()
	answer.Arguments[0].Citations[0].Locator = "A 99.9"

	out := run(t, engine(t, corpora(), false), answer)

	if out.Passed() {
		t.Fatal("Passed() = true, want false")
	}
	result := onlyResult(t, out)
	if result.GetLocatorResolved() {
		t.Error("locator_resolved = true for a locator no chunk carries")
	}
	if result.GetQuoteMatched() {
		t.Error("quote_matched = true against a chunk that does not exist")
	}
	if result.GetFailureDetail() == "" {
		t.Error("failure_detail is empty on a failed check")
	}
}

func TestALocatorIsCheckedAgainstItsOwnEditionRatherThanTheWorkAlone(t *testing.T) {
	// The same locator in two editions carries different text. This is the
	// whole reason CitationRef is a pair.
	answer := answered()
	answer.Arguments[0].Citations = []*bereanv1.Citation{cite(contraryID, "D 4.2", bindingText)}

	out := run(t, engine(t, corpora(), false), answer)

	result := onlyResult(t, out)
	if !result.GetLocatorResolved() {
		t.Error("locator_resolved = false; D 4.2 exists in that edition")
	}
	if result.GetQuoteMatched() {
		t.Error("quote_matched = true: the other edition's text was quoted at this locator")
	}
}

// --- check 2: the quote matches -------------------------------------------

func TestAQuoteThatIsNotInTheChunkFailsCheckTwo(t *testing.T) {
	answer := answered()
	answer.Arguments[0].Citations[0].Quote =
		"The assembly of elders shall meet on the second day of the fourth month, and shall not adjourn."

	out := run(t, engine(t, corpora(), false), answer)

	if onlyResult(t, out).GetQuoteMatched() {
		t.Error("quote_matched = true for text that is not in the chunk")
	}
}

func TestAQuoteMatchesAsASubstringRatherThanAsTheWholeChunk(t *testing.T) {
	answer := answered()
	answer.Arguments[0].Citations[0].Quote = bindingText[:60]

	out := run(t, engine(t, corpora(), false), answer)

	if !onlyResult(t, out).GetQuoteMatched() {
		t.Error("quote_matched = false for a genuine substring of the chunk")
	}
}

func TestAQuoteUnderTheFortyCharacterFloorFails(t *testing.T) {
	short := "The assembly of elders shall meet." // 34 characters, and genuinely present
	if len([]rune(short)) >= verify.QuoteFloor {
		t.Fatalf("fixture is %d characters; it must be under the floor to test it", len([]rune(short)))
	}
	answer := answered()
	answer.Arguments[0].Citations[0].Quote = short

	out := run(t, engine(t, corpora(), false), answer)

	result := onlyResult(t, out)
	if result.GetQuoteMatched() {
		t.Error("quote_matched = true under the floor; the degenerate citation is exactly what it blocks")
	}
	if !strings.Contains(result.GetFailureDetail(), "40") {
		t.Errorf("failure_detail = %q, want it to name the floor", result.GetFailureDetail())
	}
}

func TestTheFloorCountsCharactersRatherThanBytes(t *testing.T) {
	// Forty-one characters, seventy-odd bytes. A byte count would pass this
	// where a character count fails it, and the spec says characters.
	const multibyte = "Ægypтos ἀρχή שלום 平和 миръ ☩ ὁμολογία ἓν"
	if runes := len([]rune(multibyte)); runes >= verify.QuoteFloor {
		t.Fatalf("fixture is %d characters; it must be under the floor", runes)
	}
	if len(multibyte) < verify.QuoteFloor {
		t.Fatal("fixture must be over the floor in bytes, or it tests nothing")
	}
	s := corpora().put(bindingID, "A 9.1", "Preface. "+multibyte+" And so it stands.", corpus.PublicDomain)
	answer := answered()
	answer.Arguments[0].Citations[0] = cite(bindingID, "A 9.1", multibyte)

	out := run(t, engine(t, s, false), answer)

	if onlyResult(t, out).GetQuoteMatched() {
		t.Error("quote_matched = true: the floor counted bytes, not characters")
	}
}

func TestAQuoteDifferingOnlyInNormalisableWhitespaceMatches(t *testing.T) {
	// A no-break space, a soft hyphen and a doubled newline are what ordinary
	// PDF and HTML extraction produces. The normalisation contract exists so
	// that a quote carrying them still matches the passage it is plainly in.
	answer := answered()
	answer.Arguments[0].Citations[0].Quote =
		// Written as escapes: these characters are invisible by definition, and a
		// fixture of them written literally cannot be reviewed.
		"The assembly of elders shall\u00A0meet on the first day\n\nof the fourth month, and shall not ad\u00ADjourn"

	out := run(t, engine(t, corpora(), false), answer)

	if !onlyResult(t, out).GetQuoteMatched() {
		t.Error("quote_matched = false; normalisation should have made these identical")
	}
}

func TestAQuoteMissUnderAContractSkewSaysSo(t *testing.T) {
	// Bump `normalise.Version` without re-ingesting and every citation to that
	// corpus fails check 2 at once, with a message that reads exactly like a
	// fabricating model. `chunks.normalisation_version` exists so that this is
	// a lookup rather than an investigation.
	s := corpora()
	stale := s[bindingID+"\x00"+"A 4.2"]
	stale.NormalisationVersion = normalise.Version + 1
	s[bindingID+"\x00"+"A 4.2"] = stale

	answer := answered()
	answer.Arguments[0].Citations[0].Quote =
		"The assembly of elders shall meet on the second day of the fourth month, and shall not adjourn."

	out := run(t, engine(t, s, false), answer)

	detail := onlyResult(t, out).GetFailureDetail()
	if !strings.Contains(detail, "normalisation contract version") {
		t.Errorf("failure_detail = %q, want it to name the contract skew", detail)
	}
}

func TestAQuoteMissAtTheCurrentContractVersionSaysNothingAboutVersions(t *testing.T) {
	// The skew note must not appear on an ordinary fabrication, or it becomes
	// noise on the message that matters most.
	answer := answered()
	answer.Arguments[0].Citations[0].Quote =
		"The assembly of elders shall meet on the second day of the fourth month, and shall not adjourn."

	out := run(t, engine(t, corpora(), false), answer)

	if detail := onlyResult(t, out).GetFailureDetail(); strings.Contains(detail, "version") {
		t.Errorf("failure_detail = %q, want no version note when the versions agree", detail)
	}
}

func TestAQuoteThatMatchesAcrossAContractSkewStillPasses(t *testing.T) {
	// A skew is a diagnosis, never a check. Failing on the version number would
	// refuse citations whose text is genuinely there.
	s := corpora()
	stale := s[bindingID+"\x00"+"A 4.2"]
	stale.NormalisationVersion = normalise.Version + 1
	s[bindingID+"\x00"+"A 4.2"] = stale

	out := run(t, engine(t, s, false), answered())

	if !out.Passed() {
		t.Errorf("Passed() = false under a contract skew whose text still matches: %v", out.Results)
	}
}

func TestAQuoteDifferingInPunctuationDoesNotMatch(t *testing.T) {
	// The contract folds no quotes and no dashes, deliberately: a curly
	// apostrophe against a straight one is a genuine mismatch.
	s := corpora().put(bindingID, "A 5.5",
		"It is the court’s duty to record every dissent entered by any member present.", corpus.PublicDomain)
	answer := answered()
	answer.Arguments[0].Citations[0] = cite(bindingID, "A 5.5",
		"It is the court's duty to record every dissent entered by any member present.")

	out := run(t, engine(t, s, false), answer)

	if onlyResult(t, out).GetQuoteMatched() {
		t.Error("quote_matched = true across a straight/curly apostrophe; the contract folds neither")
	}
}

// --- check 3: the tier is permitted in the slot ---------------------------

func TestACitationToACorpusThatWasNotSentFails(t *testing.T) {
	s := corpora().put("epsilon-1999-unsent", "E 1.1", advisoryText, corpus.PublicDomain)
	answer := answered()
	answer.Arguments[0].Citations = []*bereanv1.Citation{
		cite("epsilon-1999-unsent", "E 1.1", advisoryText),
	}

	out := run(t, engine(t, s, false), answer)

	result := onlyResult(t, out)
	if result.GetTierPermitted() {
		t.Error("tier_permitted = true for a corpus the filter spec never named")
	}
	// The corpus exists and the quote is genuinely in it. Recording those two
	// checks as failures would tell the regeneration the locator was wrong.
	if !result.GetLocatorResolved() || !result.GetQuoteMatched() {
		t.Error("the other checks should record what they actually found")
	}
}

func TestTheProfilesTierIsUsedRatherThanTheOnePythonClaimed(t *testing.T) {
	answer := answered()
	// Python claims binding for a corpus this profile holds at contrary.
	answer.Arguments[0].Citations = []*bereanv1.Citation{{
		CorpusId: contraryID, Locator: "D 4.2", Quote: contraryText,
		Tier: bereanv1.Tier_TIER_BINDING,
	}}

	out := run(t, engine(t, corpora(), false), answer)

	if onlyResult(t, out).GetTierPermitted() {
		t.Error("tier_permitted = true: the claimed tier was believed instead of the resolved profile's")
	}
}

func TestAnExcludedCitationNeverAppearsInAnArgument(t *testing.T) {
	s := spec()
	s.Corpora = append(s.Corpora, &bereanv1.CorpusFilter{
		CorpusId: "zeta-2007-repudiated", Tier: bereanv1.Tier_TIER_EXCLUDED,
	})
	chunks := corpora().put("zeta-2007-repudiated", "Z 1.1", advisoryText, corpus.PublicDomain)
	answer := answered()
	answer.Arguments[0].Citations = []*bereanv1.Citation{
		cite("zeta-2007-repudiated", "Z 1.1", advisoryText),
	}

	out, err := verify.New(chunks, false).Verify(context.Background(), answer, s, loci())
	if err != nil {
		t.Fatalf("Verify: %v", err)
	}
	if onlyResult(t, out).GetTierPermitted() {
		t.Error("tier_permitted = true for an excluded citation inside an argument")
	}
}

func TestAContraryCitationIsPermittedInADescription(t *testing.T) {
	answer := &bereanv1.AnswerObject{
		Descriptions: []*bereanv1.Description{{
			Subject:   "The 1702 original",
			Content:   "The original text placed no such requirement on the congregations.",
			Citations: []*bereanv1.Citation{cite(contraryID, "D 4.2", contraryText)},
		}},
	}

	out := run(t, engine(t, corpora(), false), answer)

	if !out.Passed() {
		t.Fatalf("Passed() = false: results=%v failures=%v", out.Results, out.Failures)
	}
}

func TestAnAdvisoryCitationMayCorroborateInsideAnArgumentItDoesNotCarryAlone(t *testing.T) {
	answer := answered()
	answer.Arguments[0].Citations = append(answer.Arguments[0].Citations,
		cite(advisoryID, "GS98 3.1", advisoryText))

	out := run(t, engine(t, corpora(), false), answer)

	if !out.Passed() {
		t.Fatalf("Passed() = false: %v %v", out.Results, out.Failures)
	}
	for _, r := range out.Results {
		if !r.GetTierPermitted() {
			t.Errorf("%s %s: tier_permitted = false; advisory corroborates inside an argument",
				r.GetCitationRef().GetCorpusId(), r.GetCitationRef().GetLocator())
		}
	}
}

func TestAnArgumentRestingOnlyOnAdvisoryFails(t *testing.T) {
	answer := answered()
	answer.Arguments[0].Citations = []*bereanv1.Citation{cite(advisoryID, "GS98 3.1", advisoryText)}

	out := run(t, engine(t, corpora(), false), answer)

	if out.Passed() {
		t.Fatal("Passed() = true; advisory corroborates, it never establishes")
	}
	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_ARGUMENT_LACKS_AUTHORITY) {
		t.Errorf("codes = %v, want ARGUMENT_LACKS_AUTHORITY", codes(out))
	}
	// The citation itself is fine. Marking it failed would send the
	// regeneration looking for a bad quote that is not there.
	if !onlyResult(t, out).GetTierPermitted() {
		t.Error("tier_permitted = false on a citation that is permitted in the slot it occupies")
	}
}

// --- check 4: the licence permits serving ---------------------------------

func TestALocalOnlyChunkIsRefusedWithoutTheDeployerOptIn(t *testing.T) {
	answer := answered()
	answer.Arguments[0].Citations = []*bereanv1.Citation{cite(governingID, "B 21-4", governingText)}

	out := run(t, engine(t, corpora(), false), answer)

	if onlyResult(t, out).GetLicensePermitted() {
		t.Error("license_permitted = true for local-only with the opt-in unset; the default is deny")
	}
}

func TestALocalOnlyChunkIsServedUnderTheDeployerOptIn(t *testing.T) {
	answer := answered()
	answer.Arguments[0].Citations = []*bereanv1.Citation{cite(governingID, "B 21-4", governingText)}

	out := run(t, engine(t, corpora(), true), answer)

	if !out.Passed() {
		t.Fatalf("Passed() = false under the opt-in: %v %v", out.Results, out.Failures)
	}
}

func TestARefusedChunkIsNeverServed(t *testing.T) {
	s := corpora().put(bindingID, "A 4.2", bindingText, corpus.Refused)
	answer := answered()

	for _, optIn := range []bool{false, true} {
		out := run(t, engine(t, s, optIn), answer)
		if onlyResult(t, out).GetLicensePermitted() {
			t.Errorf("serveLocalOnly=%v: license_permitted = true for a refused licence", optIn)
		}
	}
}

func TestALicenceThisBuildDoesNotKnowIsRefused(t *testing.T) {
	s := corpora().put(bindingID, "A 4.2", bindingText, corpus.License("cc-by-nc"))
	answer := answered()

	out := run(t, engine(t, s, true), answer)

	if onlyResult(t, out).GetLicensePermitted() {
		t.Error("license_permitted = true for a licence outside the enum; check 4 must fail closed")
	}
}

// --- answer-level rules ---------------------------------------------------

func TestAnArgumentWithNoCitationsFailsTheAnswer(t *testing.T) {
	answer := answered()
	answer.Arguments[0].Citations = nil

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CITATIONS_REQUIRED) {
		t.Errorf("codes = %v, want CITATIONS_REQUIRED", codes(out))
	}
	if got := out.Failures[0].GetSlot(); got != "arguments[0]" {
		t.Errorf("slot = %q, want arguments[0]", got)
	}
}

func TestADescriptionWithNoCitationsFailsTheAnswer(t *testing.T) {
	answer := answered()
	answer.Descriptions = []*bereanv1.Description{{Subject: "A study committee", Content: "It reported."}}

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CITATIONS_REQUIRED) {
		t.Errorf("codes = %v, want CITATIONS_REQUIRED", codes(out))
	}
}

func TestAContraryPositionWithNoCitationsFailsTheAnswer(t *testing.T) {
	answer := answered()
	answer.ContraryPositions = []*bereanv1.ContraryPosition{{
		Position: "Another tradition holds otherwise.", HeldBy: []string{"a neighbouring communion"},
	}}

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CITATIONS_REQUIRED) {
		t.Errorf("codes = %v, want CITATIONS_REQUIRED", codes(out))
	}
}

func TestAPositionStatedWithNoArgumentsFails(t *testing.T) {
	answer := &bereanv1.AnswerObject{
		Position: "The tradition requires the roll to be read.",
		Descriptions: []*bereanv1.Description{{
			Subject:   "The order of business",
			Content:   "The standard fixes it.",
			Citations: []*bereanv1.Citation{cite(bindingID, "A 4.2", bindingText)},
		}},
	}

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_POSITION_WITHOUT_ARGUMENTS) {
		t.Errorf("codes = %v, want POSITION_WITHOUT_ARGUMENTS", codes(out))
	}
}

// --- contested ------------------------------------------------------------

func contestedAnswer() *bereanv1.AnswerObject {
	return &bereanv1.AnswerObject{
		Contested: &bereanv1.Contested{
			IsContested:   true,
			Locus:         "creation-days",
			Citations:     []*bereanv1.Citation{cite(rulingID, rulingLoc, rulingText)},
			StateOfDebate: "The courts hold this open. " + rulingText,
		},
	}
}

func TestAContestedAnswerCitingAndQuotingItsRulingPasses(t *testing.T) {
	out := run(t, engine(t, corpora(), false), contestedAnswer())

	if !out.Passed() {
		t.Fatalf("Passed() = false: results=%v failures=%v", out.Results, out.Failures)
	}
}

func TestAContestedAnswerCarryingArgumentsFails(t *testing.T) {
	answer := contestedAnswer()
	answer.Arguments = answered().Arguments

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CONTESTED_WITH_ARGUMENTS) {
		t.Errorf("codes = %v, want CONTESTED_WITH_ARGUMENTS", codes(out))
	}
}

func TestALocusThatWasNotSentFails(t *testing.T) {
	answer := contestedAnswer()
	answer.Contested.Locus = "church-government"

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CONTESTED_LOCUS_UNKNOWN) {
		t.Errorf("codes = %v, want CONTESTED_LOCUS_UNKNOWN", codes(out))
	}
}

func TestAContestedAnswerThatDoesNotCiteItsRulingFails(t *testing.T) {
	answer := contestedAnswer()
	answer.Contested.Citations = []*bereanv1.Citation{cite(advisoryID, "GS98 3.1", advisoryText)}
	answer.Contested.StateOfDebate = "The courts hold this open. " + advisoryText

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CONTESTED_RULING_UNCITED) {
		t.Errorf("codes = %v, want CONTESTED_RULING_UNCITED", codes(out))
	}
}

func TestAContestedAnswerThatDoesNotQuoteItsRulingVerbatimFails(t *testing.T) {
	answer := contestedAnswer()
	answer.Contested.StateOfDebate = "The courts hold this open, and the assembly said a range of views is fine."

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CONTESTED_RULING_UNQUOTED) {
		t.Errorf("codes = %v, want CONTESTED_RULING_UNQUOTED", codes(out))
	}
}

func TestTheRulingQuoteIsFoundInStateOfDebateAcrossNormalisableWhitespace(t *testing.T) {
	answer := contestedAnswer()
	answer.Contested.StateOfDebate = "The courts hold this open.\n\n" +
		strings.ReplaceAll(rulingText, " ", "\u00A0")

	out := run(t, engine(t, corpora(), false), answer)

	if hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CONTESTED_RULING_UNQUOTED) {
		t.Error("the ruling quote should be found after normalisation")
	}
}

func TestCitingARulingWhileNotFlaggingTheLocusContestedFails(t *testing.T) {
	// The system's only omission check, and the only rule that fires on an
	// answer whose every citation passed all four checks.
	answer := answered()
	answer.Arguments[0].Citations = append(answer.Arguments[0].Citations,
		cite(rulingID, rulingLoc, rulingText))

	out := run(t, engine(t, corpora(), false), answer)

	if out.Passed() {
		t.Fatal("Passed() = true while resolving a locus the tradition holds open")
	}
	for _, r := range out.Results {
		if r.GetFailureDetail() != "" {
			t.Errorf("%v: a per-citation check failed; every citation here is real", r)
		}
	}
	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_RULING_CITED_WHILE_UNCONTESTED) {
		t.Errorf("codes = %v, want RULING_CITED_WHILE_UNCONTESTED", codes(out))
	}
}

func TestAnUnverifiedCitationToTheRulingDoesNotFireTheOmissionCheck(t *testing.T) {
	// The check reads "a *verified* citation resolving to a locus's ruling".
	// A fabricated quote at the ruling's locator has already failed check 2,
	// and firing here too would report one fabrication as two rules broken.
	answer := answered()
	answer.Arguments[0].Citations = append(answer.Arguments[0].Citations,
		cite(rulingID, rulingLoc, "The assembly forbids any diversity of views upon this question whatsoever."))

	out := run(t, engine(t, corpora(), false), answer)

	if hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_RULING_CITED_WHILE_UNCONTESTED) {
		t.Errorf("codes = %v, want no RULING_CITED_WHILE_UNCONTESTED for an unverified citation", codes(out))
	}
}

func TestStateOfDebateWithoutTheContestedFlagFails(t *testing.T) {
	answer := answered()
	answer.Contested = &bereanv1.Contested{
		StateOfDebate: "Some hold one view and some another, and the courts have not spoken.",
	}

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_STATE_OF_DEBATE_WITHOUT_CONTEST) {
		t.Errorf("codes = %v, want STATE_OF_DEBATE_WITHOUT_CONTEST", codes(out))
	}
}

// --- no_answer_reason -----------------------------------------------------

func TestAnHonestNonAnswerPasses(t *testing.T) {
	answer := &bereanv1.AnswerObject{
		NoAnswerReason: "The corpora in scope do not address the question.",
	}

	out := run(t, engine(t, corpora(), false), answer)

	if !out.Passed() {
		t.Fatalf("Passed() = false: %v", out.Failures)
	}
}

func TestANonAnswerBesideContentFails(t *testing.T) {
	answer := answered()
	answer.NoAnswerReason = "The corpora in scope do not address the question."

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_NO_ANSWER_REASON_NOT_ALONE) {
		t.Errorf("codes = %v, want NO_ANSWER_REASON_NOT_ALONE", codes(out))
	}
}

func TestANonAnswerBesideAContestedFlagFails(t *testing.T) {
	answer := contestedAnswer()
	answer.NoAnswerReason = "The corpora in scope do not address the question."

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_NO_ANSWER_REASON_NOT_ALONE) {
		t.Errorf("codes = %v, want NO_ANSWER_REASON_NOT_ALONE", codes(out))
	}
}

func TestANonAnswerOverTwoHundredCharactersFails(t *testing.T) {
	answer := &bereanv1.AnswerObject{NoAnswerReason: strings.Repeat("a", 201)}

	out := run(t, engine(t, corpora(), false), answer)

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_NO_ANSWER_REASON_TOO_LONG) {
		t.Errorf("codes = %v, want NO_ANSWER_REASON_TOO_LONG", codes(out))
	}
}

func TestATwoHundredCharacterNonAnswerIsWithinTheCap(t *testing.T) {
	answer := &bereanv1.AnswerObject{NoAnswerReason: strings.Repeat("a", 200)}

	out := run(t, engine(t, corpora(), false), answer)

	if !out.Passed() {
		t.Errorf("Passed() = false at exactly 200 characters: %v", out.Failures)
	}
}

func TestAnEmptyAnswerWithNoReasonFails(t *testing.T) {
	// A truncated generation must not render as considered silence.
	out := run(t, engine(t, corpora(), false), &bereanv1.AnswerObject{})

	if !hasCode(out, bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_EMPTY_ANSWER) {
		t.Errorf("codes = %v, want EMPTY_ANSWER", codes(out))
	}
}

// --- every failure is reported, not just the first ------------------------

func TestEveryFailingCitationIsReportedSoTheRegenerationSeesThemAll(t *testing.T) {
	answer := answered()
	answer.Arguments[0].Citations = []*bereanv1.Citation{
		cite(bindingID, "A 4.2", bindingText),
		cite(bindingID, "A 77.7", bindingText),
		cite(bindingID, "A 4.2", "The assembly of elders shall meet on the ninth day of the fourth month, and shall not adjourn."),
	}

	out := run(t, engine(t, corpora(), false), answer)

	if len(out.Results) != 3 {
		t.Fatalf("results = %d, want 3 — one per citation", len(out.Results))
	}
	failed := 0
	for _, r := range out.Results {
		if r.GetFailureDetail() != "" {
			failed++
		}
	}
	if failed != 2 {
		t.Errorf("failed results = %d, want 2; verification must not stop at the first", failed)
	}
}

func TestEveryResultCarriesTheCitationItIsAbout(t *testing.T) {
	out := run(t, engine(t, corpora(), false), answered())

	ref := onlyResult(t, out).GetCitationRef()
	if ref.GetCorpusId() != bindingID || ref.GetLocator() != "A 4.2" {
		t.Errorf("citation_ref = %v, want the citation it is about", ref)
	}
}

func TestEveryAnswerFailureCarriesADetail(t *testing.T) {
	// The trace constraint is detail-iff-failure, and a failure nobody can act
	// on is a failure that was not really recorded.
	answer := answered()
	answer.Arguments[0].Citations = nil
	answer.Contested = &bereanv1.Contested{StateOfDebate: "Unflagged prose."}
	answer.NoAnswerReason = strings.Repeat("a", 201)

	out := run(t, engine(t, corpora(), false), answer)

	if len(out.Failures) < 3 {
		t.Fatalf("failures = %d, want every broken rule reported: %v", len(out.Failures), codes(out))
	}
	for _, f := range out.Failures {
		if f.GetDetail() == "" {
			t.Errorf("%v: detail is empty", f.GetCode())
		}
		if f.GetSlot() == "" {
			t.Errorf("%v: slot is empty", f.GetCode())
		}
		if f.GetCode() == bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_UNSPECIFIED {
			t.Error("a failure was reported with an unspecified code")
		}
	}
}
