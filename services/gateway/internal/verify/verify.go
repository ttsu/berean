// Package verify is the trust boundary's whole job: deciding whether an answer
// from Catena may be shown to anyone.
//
// Everything it acts on is untrusted. A citation is a *claim* that a passage
// exists and says what it is quoted as saying, and this package turns that
// claim into a fact or a failure. It is ordinary software — indexed lookups
// and string matching — and if a change here starts to need a model call,
// something has gone wrong (services/gateway/AGENTS.md).
//
// Two kinds of finding come out, because there are two kinds of rule:
//
//   - `VerificationResult`, one per citation, carrying the four checks.
//   - `AnswerFailure`, for the rules that are about a *slot* rather than a
//     citation — an argument with nothing behind it, a locus flagged contested
//     and resolved anyway, the bounds on `no_answer_reason`. The omission check
//     is the sharpest of them: every one of the four checks passes and the
//     answer still fails (ADR-0024).
//
// **What the checks establish is that a citation is real, never that its quote
// supports the claim.** That limit, and the other uncited surfaces, are
// enumerated in INTEGRATION-SPEC and measured in Phase 2. Nothing here reads
// meaning: Go asks which slot a claim occupies and what tiers its citations
// carry (ADR-0016).
package verify

import (
	"context"
	"errors"
	"fmt"
	"strings"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/corpus"
	"github.com/ttsu/berean/services/gateway/internal/normalise"
)

// QuoteFloor is the minimum length of a quote, in characters after
// normalisation.
//
// It blocks the degenerate citation — a four-word fragment cited at `binding`
// behind a claim the source denies — without asking what any claim means. It
// is the only number in this package that is a judgement rather than a
// consequence, and ADR-0020 is where the judgement is argued.
const QuoteFloor = 40

// NoAnswerReasonCap bounds the one model-authored string that renders with no
// citation beside it.
const NoAnswerReasonCap = 200

// ChunkStore resolves a citation to the chunk it names. Narrow on purpose:
// verification asks the corpus tables exactly one question, and an interface
// this size is what lets the engine's tests be a map.
type ChunkStore interface {
	Lookup(ctx context.Context, corpusID, locator string) (corpus.Chunk, error)
}

// Engine applies the checks. It holds the deployer's serving opt-in because
// check 4 is a deployment policy question rather than an answer question
// (ADR-0017).
type Engine struct {
	store ChunkStore
	// Whether this deployment may serve `local-only` text. Default deny; the
	// opt-in is a recorded act rather than an omission.
	serveLocalOnly bool
}

// New builds an engine over a chunk store.
func New(store ChunkStore, serveLocalOnly bool) *Engine {
	return &Engine{store: store, serveLocalOnly: serveLocalOnly}
}

// Outcome is everything verification found about one answer.
//
// Both lists are complete rather than short-circuited: the regeneration
// carries them back, and telling the generator about the first of three bad
// citations buys a second attempt that fixes one third of the problem.
type Outcome struct {
	// One per citation, in the order the citations appear in the answer.
	Results []*bereanv1.VerificationResult
	// The answer-level rules that broke, in the order this package checks them.
	Failures []*bereanv1.AnswerFailure
}

// Passed reports whether the answer may be shown.
func (o Outcome) Passed() bool {
	if len(o.Failures) > 0 {
		return false
	}
	for _, result := range o.Results {
		if result.GetFailureDetail() != "" {
			return false
		}
	}
	return true
}

// slot is which part of the answer object a citation sits in. It is the whole
// of what check 3 knows about a claim: membership in `arguments` *is* what
// makes a claim affirmative, and nothing here reads what a claim says
// (ADR-0016).
type slot int

const (
	// An affirmative claim. `contrary` and `excluded` never appear here.
	inArgument slot = iota
	// A claim about a source rather than one resting on it. Any tier.
	descriptive
)

// Verify checks an answer against the filter spec and contested loci that were
// actually sent for this turn.
//
// "In scope" means in scope *for this turn*, which is why the spec is the
// argument rather than the profile: a citation to a corpus the profile holds
// but the request did not carry is still a citation to something the generator
// was never shown.
func (e *Engine) Verify(
	ctx context.Context,
	answer *bereanv1.AnswerObject,
	spec *bereanv1.FilterSpec,
	loci []*bereanv1.ContestedLocus,
) (Outcome, error) {
	tiers := make(map[string]bereanv1.Tier, len(spec.GetCorpora()))
	for _, entry := range spec.GetCorpora() {
		tiers[entry.GetCorpusId()] = entry.GetTier()
	}
	rulings := make(map[string]string, len(loci))
	for _, locus := range loci {
		rulings[refKey(locus.GetRuling().GetCorpusId(), locus.GetRuling().GetLocator())] = locus.GetLocus()
	}

	var out Outcome
	// Every citation, in answer order, before any answer-level rule. The
	// omission check reads the results, so it has to run after them, and
	// keeping all of them in one place keeps the result order predictable for
	// anyone reading a trace.
	// A slice rather than a set, so the omission check reports failures in
	// citation order: a failure list that reshuffles between runs over the
	// same answer is a diff nobody can read.
	var verified []*bereanv1.CitationRef
	seen := make(map[string]bool)
	check := func(citation *bereanv1.Citation, kind slot, where string) error {
		result, err := e.checkCitation(ctx, citation, kind, tiers)
		if err != nil {
			return fmt.Errorf("%s: %w", where, err)
		}
		out.Results = append(out.Results, result)
		key := refKey(citation.GetCorpusId(), citation.GetLocator())
		if result.GetFailureDetail() == "" && !seen[key] {
			seen[key] = true
			verified = append(verified, result.GetCitationRef())
		}
		return nil
	}

	for i, argument := range answer.GetArguments() {
		where := fmt.Sprintf("arguments[%d]", i)
		for _, citation := range argument.GetCitations() {
			if err := check(citation, inArgument, where); err != nil {
				return Outcome{}, err
			}
		}
	}
	for i, description := range answer.GetDescriptions() {
		where := fmt.Sprintf("descriptions[%d]", i)
		for _, citation := range description.GetCitations() {
			if err := check(citation, descriptive, where); err != nil {
				return Outcome{}, err
			}
		}
	}
	for i, position := range answer.GetContraryPositions() {
		where := fmt.Sprintf("contrary_positions[%d]", i)
		for _, citation := range position.GetCitations() {
			if err := check(citation, descriptive, where); err != nil {
				return Outcome{}, err
			}
		}
	}
	for i, citation := range answer.GetContested().GetCitations() {
		where := fmt.Sprintf("contested.citations[%d]", i)
		if err := check(citation, descriptive, where); err != nil {
			return Outcome{}, err
		}
	}

	out.Failures = e.answerFailures(answer, tiers, loci, rulings, verified)
	return out, nil
}

// checkCitation runs the four checks.
//
// Each check records what it actually found, and a check that could not run
// records the reason it could not rather than borrowing another check's
// failure. That costs a chunk lookup on a citation already doomed by its tier,
// and it buys a regeneration that is told the truth: a citation to an
// out-of-scope corpus whose locator and quote are both real is a different
// mistake from a fabricated locator, and a result that failed all four would
// send the generator hunting for the wrong one.
func (e *Engine) checkCitation(
	ctx context.Context,
	citation *bereanv1.Citation,
	kind slot,
	tiers map[string]bereanv1.Tier,
) (*bereanv1.VerificationResult, error) {
	corpusID, locator := citation.GetCorpusId(), citation.GetLocator()
	result := &bereanv1.VerificationResult{
		CitationRef: &bereanv1.CitationRef{CorpusId: corpusID, Locator: locator},
	}
	var details []string

	// Check 1. Exactly one chunk is the database's `chunks_corpus_locator_unique`
	// rather than something counted here: two rows make the check ambiguous, and
	// no amount of care in Go notices a race it cannot see.
	chunk, err := e.store.Lookup(ctx, corpusID, locator)
	switch {
	case errors.Is(err, corpus.ErrNotFound):
		details = append(details, fmt.Sprintf("no chunk carries %q at %q", corpusID, locator))
	case err != nil:
		return nil, fmt.Errorf("resolving %s %s: %w", corpusID, locator, err)
	default:
		result.LocatorResolved = true
	}

	// Check 2. Exact substring containment after normalisation — never fuzzy,
	// never partial. The chunk was normalised at ingestion and is normalised
	// again here, which is idempotent and costs one pass: what it buys is that
	// a corpus ingested under an older contract version fails visibly on the
	// quote rather than invisibly on a code point nobody can see.
	quote := normalise.Normalise(citation.GetQuote())
	switch length := len([]rune(quote)); {
	case !result.GetLocatorResolved():
		details = append(details, "the quote could not be checked: the locator resolved to no chunk")
	case length < QuoteFloor:
		details = append(details, fmt.Sprintf(
			"the quote is %d characters after normalisation and the floor is %d", length, QuoteFloor))
	case !strings.Contains(normalise.Normalise(chunk.Text), quote):
		details = append(details, quoteMissDetail(chunk.NormalisationVersion))
	default:
		result.QuoteMatched = true
	}

	// Check 3. Against the tier the resolved profile assigns, never the tier
	// Python claimed — `citation.tier` is read nowhere in this function, and
	// that is the point of it.
	tier, inScope := tiers[corpusID]
	switch {
	case !inScope:
		details = append(details, fmt.Sprintf(
			"%q was not in the filter spec sent for this turn", corpusID))
	case kind == inArgument && !permittedInArgument(tier):
		details = append(details, fmt.Sprintf(
			"%q sits at %s under the resolved profile, and an affirmative claim never rests on it",
			corpusID, tierLabel(tier)))
	default:
		result.TierPermitted = true
	}

	// Check 4.
	switch reason := servingRefusal(chunk.License, e.serveLocalOnly); {
	case !result.GetLocatorResolved():
		details = append(details, "the licence could not be checked: the locator resolved to no chunk")
	case reason != "":
		details = append(details, reason)
	default:
		result.LicensePermitted = true
	}

	// Empty exactly when all four passed, which is the shape the trace
	// constraint holds and the shape Python's retry prompt reads.
	result.FailureDetail = strings.Join(details, "; ")
	return result, nil
}

// answerFailures applies the rules that no citation can carry.
func (e *Engine) answerFailures(
	answer *bereanv1.AnswerObject,
	tiers map[string]bereanv1.Tier,
	loci []*bereanv1.ContestedLocus,
	rulings map[string]string,
	verified []*bereanv1.CitationRef,
) []*bereanv1.AnswerFailure {
	var failures []*bereanv1.AnswerFailure
	fail := func(code bereanv1.AnswerFailureCode, where string, ref *bereanv1.CitationRef, detail string) {
		failures = append(failures, &bereanv1.AnswerFailure{
			Code: code, Slot: where, CitationRef: ref, Detail: detail,
		})
	}

	for i, argument := range answer.GetArguments() {
		where := fmt.Sprintf("arguments[%d]", i)
		if len(argument.GetCitations()) == 0 {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CITATIONS_REQUIRED, where, nil,
				"an argument carries no citations, and a claim without one is not shown")
			continue
		}
		// The authority floor is answer-level rather than per-citation
		// because it is a property of the argument, not of any citation in
		// it: an advisory citation beside a binding one is permitted, and
		// only becomes a failure when it is the whole support.
		if !carriesAuthority(argument.GetCitations(), tiers) {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_ARGUMENT_LACKS_AUTHORITY, where, nil,
				"no citation in this argument sits at binding or governing under the resolved profile; advisory corroborates and never establishes")
		}
	}
	for i, description := range answer.GetDescriptions() {
		if len(description.GetCitations()) == 0 {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CITATIONS_REQUIRED,
				fmt.Sprintf("descriptions[%d]", i), nil,
				"a description carries no citations, and a claim about a source is a cited claim")
		}
	}
	for i, position := range answer.GetContraryPositions() {
		if len(position.GetCitations()) == 0 {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CITATIONS_REQUIRED,
				fmt.Sprintf("contrary_positions[%d]", i), nil,
				"a contrary position carries no citations, and another tradition's position is argued from its own sources or not at all")
		}
	}

	if strings.TrimSpace(answer.GetPosition()) != "" && len(answer.GetArguments()) == 0 {
		fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_POSITION_WITHOUT_ARGUMENTS, "position", nil,
			"a position is stated while no affirmative claim is argued; a descriptive answer reports what sources say and states none of its own")
	}

	contested := answer.GetContested()
	if contested.GetIsContested() {
		if len(answer.GetArguments()) > 0 {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CONTESTED_WITH_ARGUMENTS, "arguments", nil,
				fmt.Sprintf("the answer flags %q contested and argues %d affirmative claim(s); a contested answer is a descriptive one",
					contested.GetLocus(), len(answer.GetArguments())))
		}
		if ruling, known := rulingFor(loci, contested.GetLocus()); !known {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CONTESTED_LOCUS_UNKNOWN, "contested.locus", nil,
				fmt.Sprintf("%q is not one of the %d loci sent for this turn", contested.GetLocus(), len(loci)))
		} else if cited := citationTo(contested.GetCitations(), ruling); cited == nil {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CONTESTED_RULING_UNCITED, "contested.citations", ruling,
				"the ruling that establishes this locus is not among the contested citations")
		} else if !strings.Contains(
			normalise.Normalise(contested.GetStateOfDebate()),
			normalise.Normalise(cited.GetQuote()),
		) {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CONTESTED_RULING_UNQUOTED, "contested.state_of_debate", ruling,
				"state_of_debate does not contain the ruling's quote verbatim after normalisation")
		}
	} else if strings.TrimSpace(contested.GetStateOfDebate()) != "" {
		// Without this, `state_of_debate` is uncited prose whenever the flag
		// is unset, and INTEGRATION-SPEC's enumeration of exactly four uncited
		// surfaces stops being true.
		fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_STATE_OF_DEBATE_WITHOUT_CONTEST, "contested.state_of_debate", nil,
			"state_of_debate is populated while is_contested is false, where nothing binds it to a quote")
	}

	// The omission check. It fires on *verified* citations only: a fabricated
	// quote at a ruling's locator has already failed check 2, and firing here
	// as well would report one mistake as two rules broken.
	if !contested.GetIsContested() {
		for _, ref := range verified {
			if locus, isRuling := rulings[refKey(ref.GetCorpusId(), ref.GetLocator())]; isRuling {
				fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_RULING_CITED_WHILE_UNCONTESTED,
					"contested.is_contested", ref,
					fmt.Sprintf("this citation is the ruling that holds %q open, and the answer does not flag it contested", locus))
			}
		}
	}

	reason := answer.GetNoAnswerReason()
	hasContent := len(answer.GetArguments()) > 0 ||
		len(answer.GetDescriptions()) > 0 ||
		len(answer.GetContraryPositions()) > 0
	switch {
	case strings.TrimSpace(reason) != "":
		if length := len([]rune(reason)); length > NoAnswerReasonCap {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_NO_ANSWER_REASON_TOO_LONG, "no_answer_reason", nil,
				fmt.Sprintf("no_answer_reason is %d characters and the cap is %d", length, NoAnswerReasonCap))
		}
		if hasContent || contested.GetIsContested() {
			fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_NO_ANSWER_REASON_NOT_ALONE, "no_answer_reason", nil,
				"no_answer_reason is given beside content; the corpus is silent or it is not")
		}
	case !hasContent && !contested.GetIsContested():
		fail(bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_EMPTY_ANSWER, "no_answer_reason", nil,
			"every content slot is empty and no reason was given; a truncated generation must not render as considered silence")
	}

	return failures
}

// quoteMissDetail states that the quote was not found, and names a
// normalisation contract skew when there is one.
//
// A skew does not *fail* the citation on its own — the quote may still match
// across versions, and a check that failed on the version number would refuse
// citations that are perfectly good. What it does is answer the question a bare
// "the quote does not appear verbatim" leaves open. Under a skew that message is
// indistinguishable from a fabricating model, and it would arrive on every
// citation to that corpus at once; `chunks.normalisation_version` exists so that
// this is a lookup rather than an investigation, and saying so here is what
// spends it.
func quoteMissDetail(ingestedUnder int) string {
	if ingestedUnder != normalise.Version {
		return fmt.Sprintf(
			"the quote does not appear verbatim in that chunk after normalisation; "+
				"the chunk was ingested under normalisation contract version %d and this build "+
				"normalises at version %d, which is the likelier cause than the quote",
			ingestedUnder, normalise.Version)
	}
	return "the quote does not appear verbatim in that chunk after normalisation"
}

// permittedInArgument reports whether a tier may appear in an affirmative
// claim at all. Advisory may: it corroborates inside an argument that another
// citation carries. `contrary` and `excluded` may not, at any strength.
func permittedInArgument(tier bereanv1.Tier) bool {
	switch tier {
	case bereanv1.Tier_TIER_BINDING, bereanv1.Tier_TIER_GOVERNING, bereanv1.Tier_TIER_ADVISORY:
		return true
	}
	return false
}

// carriesAuthority reports whether any citation sits at a tier that can
// establish a claim on its own.
func carriesAuthority(citations []*bereanv1.Citation, tiers map[string]bereanv1.Tier) bool {
	for _, citation := range citations {
		switch tiers[citation.GetCorpusId()] {
		case bereanv1.Tier_TIER_BINDING, bereanv1.Tier_TIER_GOVERNING:
			return true
		}
	}
	return false
}

// servingRefusal states why this licence may not be served, or "" if it may.
func servingRefusal(license corpus.License, serveLocalOnly bool) string {
	switch {
	case !license.Known():
		return fmt.Sprintf(
			"licence %q is not one this build knows, and an unknown licence cannot be read as permitting anything", license)
	case license == corpus.Refused:
		return "the licence is `refused`, which permits serving under no configuration"
	case license == corpus.LocalOnly && !serveLocalOnly:
		return "the licence is `local-only` and the deployer opt-in is unset, so the default deny applies"
	}
	return ""
}

func tierLabel(tier bereanv1.Tier) string {
	switch tier {
	case bereanv1.Tier_TIER_BINDING:
		return "binding"
	case bereanv1.Tier_TIER_GOVERNING:
		return "governing"
	case bereanv1.Tier_TIER_ADVISORY:
		return "advisory"
	case bereanv1.Tier_TIER_CONTRARY:
		return "contrary"
	case bereanv1.Tier_TIER_EXCLUDED:
		return "excluded"
	}
	return "no tier"
}

func rulingFor(loci []*bereanv1.ContestedLocus, locus string) (*bereanv1.CitationRef, bool) {
	for _, candidate := range loci {
		if candidate.GetLocus() == locus {
			return candidate.GetRuling(), true
		}
	}
	return nil, false
}

func citationTo(citations []*bereanv1.Citation, ref *bereanv1.CitationRef) *bereanv1.Citation {
	for _, citation := range citations {
		if citation.GetCorpusId() == ref.GetCorpusId() && citation.GetLocator() == ref.GetLocator() {
			return citation
		}
	}
	return nil
}

// refKey packs a citation ref into a map key. NUL rather than a colon or a
// space: locators contain both, corpus IDs are a closed alphabet that excludes
// it, and a separator a locator can contain makes two different citations
// share a key.
func refKey(corpusID, locator string) string { return corpusID + "\x00" + locator }
