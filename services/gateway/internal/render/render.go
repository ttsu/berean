// Package render turns a finished turn into what a reader sees.
//
// It decides nothing. Every judgement was made before it runs — `internal/turn`
// settled what may be shown, `internal/verify` derived the confidence, and
// `internal/trace` has already recorded all of it. This package is given a
// `turn.Turn` and prints exactly the answer object that turn nominated, which
// is why the answers from refused attempts are unreachable from here: they hang
// off `Attempt`, and nothing in `Answer` reads an attempt.
//
// **It never composes prose about an answer.** The one Go-authored string a
// reader sees is `Confidence.reason`, derived in `internal/verify`; the section
// labels below are furniture, and the three fixed sentences — the refusal, the
// silence, and the contested heading — are statements of which outcome occurred
// rather than descriptions of the answer. Nothing here summarises, hedges,
// softens, or explains a model's reasoning (ADR-0003).
package render

import (
	"fmt"
	"io"
	"strings"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/turn"
)

// Refusal is what a degraded turn prints, and the whole of what it prints.
//
// Fixed here rather than reached for at the call site: PRODUCT-SPEC states this
// sentence, and a renderer free to phrase it is a renderer that can soften it
// into a warning attached to content it should not be showing at all.
const Refusal = "I can't source this adequately."

// Silence heads an honest non-answer, above the model's own brief statement of
// why. It shares no words with Refusal on purpose — UC-2 and UC-5 mean opposite
// things, and a reader must be able to tell them apart at a glance.
const Silence = "The sources in scope are silent on this question."

// Corpus is what a citation's source is called, and what standing this
// tradition gives it. Everything here comes from outside the answer: the work
// and edition from `corpus.works`, the tier and label from the resolved
// profile. None of it is read from the citation, which claims a tier the
// gateway does not believe.
type Corpus struct {
	Work    string
	Edition string
	Tier    bereanv1.Tier
	// The profile's own words for a corpus it does not hold. Empty at every
	// tier that needs none.
	Label string
}

// Sources describes each corpus in scope, keyed by corpus ID.
type Sources map[string]Corpus

// Answer writes the turn's answer.
//
// It reads `t.Answer` and nothing else about the turn, so a degraded turn's
// refused attempts cannot leak into the output by any path through this
// function.
func Answer(w io.Writer, t turn.Turn, sources Sources) error {
	out := &writer{w: w}

	if t.Overall == bereanv1.OverallResult_OVERALL_RESULT_DEGRADED {
		out.line(Refusal)
		out.blank()
		confidence(out, t.Answer.GetConfidence())
		return out.err
	}

	answer := t.Answer
	if reason := strings.TrimSpace(answer.GetNoAnswerReason()); reason != "" {
		out.line(Silence)
		out.line("  " + reason)
		out.blank()
		confidence(out, answer.GetConfidence())
		return out.err
	}

	if position := strings.TrimSpace(answer.GetPosition()); position != "" {
		out.line("position")
		out.line("  " + position)
		out.blank()
	}

	if len(answer.GetArguments()) > 0 {
		out.line("arguments")
		for i, argument := range answer.GetArguments() {
			out.line(item(i, argument.GetClaim()))
			out.optional(continuation, argument.GetWarrant())
			citations(out, argument.GetCitations(), sources)
		}
		out.blank()
	}

	if len(answer.GetDescriptions()) > 0 {
		out.line("descriptions")
		for i, description := range answer.GetDescriptions() {
			out.line(item(i, description.GetSubject()))
			out.optional(continuation, description.GetContent())
			citations(out, description.GetCitations(), sources)
		}
		out.blank()
	}

	if len(answer.GetContraryPositions()) > 0 {
		out.line("contrary positions")
		for i, contrary := range answer.GetContraryPositions() {
			out.line(item(i, contrary.GetPosition()))
			if held := heldBy(contrary.GetHeldBy()); held != "" {
				out.line(continuation + "held by: " + held)
			}
			citations(out, contrary.GetCitations(), sources)
		}
		out.blank()
	}

	// The locus is the profile's own identifier for the question being held
	// open, so naming it is how a reader gets from the answer to the document
	// that establishes it.
	if contested := answer.GetContested(); contested.GetIsContested() {
		out.line("contested: " + contested.GetLocus())
		out.optional("  ", contested.GetStateOfDebate())
		citations(out, contested.GetCitations(), sources)
		out.blank()
	}

	confidence(out, answer.GetConfidence())
	return out.err
}

// item numbers a claim. The number is how a citation block below it is known to
// belong to it, and how `arguments[2]` in a trace maps onto what was printed.
func item(index int, text string) string {
	return fmt.Sprintf("  %d. %s", index+1, strings.TrimSpace(text))
}

// continuation aligns under the text of a numbered item rather than under its
// number, so the claim and its warrant read as one block.
const continuation = "     "

func heldBy(traditions []string) string {
	var kept []string
	for _, t := range traditions {
		if t = strings.TrimSpace(t); t != "" {
			kept = append(kept, t)
		}
	}
	return strings.Join(kept, ", ")
}

// citations prints each citation as three or four lines: what it is, what it
// came from, the profile's caveat where there is one, and the quote.
//
// The quote is printed whole and unwrapped. Truncating it would undercut the
// only claim the four checks actually establish — that this text appears
// verbatim in that passage — by showing the reader something they cannot go and
// find; and wrapping it to a terminal width would put a line break inside text
// the reader may want to paste back.
func citations(out *writer, cites []*bereanv1.Citation, sources Sources) {
	for _, citation := range cites {
		source := sources[citation.GetCorpusId()]
		out.line(fmt.Sprintf("%s[%s] %s %s",
			continuation, tier(source.Tier), citation.GetCorpusId(), citation.GetLocator()))

		// Absent for a corpus the renderer was given no description of, which
		// verification makes unreachable: the ID on the line above is then the
		// whole of what is known, and it is true.
		if work := describe(source); work != "" {
			out.line(continuation + "  " + work)
		}
		if label := strings.TrimSpace(source.Label); label != "" {
			out.line(fmt.Sprintf("%s  %s: %s", continuation, tier(source.Tier), label))
		}
		out.line(continuation + `  "` + strings.TrimSpace(citation.GetQuote()) + `"`)
	}
}

func describe(source Corpus) string {
	work, edition := strings.TrimSpace(source.Work), strings.TrimSpace(source.Edition)
	switch {
	case work == "":
		return ""
	case edition == "":
		return work
	default:
		return work + " (" + edition + ")"
	}
}

func confidence(out *writer, c *bereanv1.Confidence) {
	out.line("confidence")
	out.line("  " + level(c.GetLevel()) + " — " + c.GetReason())
}

// tier and level name an enum value in the vocabulary everything else in the
// system already uses: the profile writes `binding`, the trace tables store
// `high`, and this is the same derivation Task 9's schema correspondence rests
// on. Derived rather than mapped, so a value added to the contract cannot
// render as a blank.
func tier(t bereanv1.Tier) string {
	return strings.ToLower(strings.TrimPrefix(t.String(), "TIER_"))
}

func level(l bereanv1.ConfidenceLevel) string {
	return strings.ToLower(strings.TrimPrefix(l.String(), "CONFIDENCE_LEVEL_"))
}

// writer is an io.Writer that remembers its first error, so the body of a
// renderer reads as the shape of the output rather than as error handling.
// Nothing downstream can act on a partial write to a terminal or a pipe, and
// the one place it matters — a closed stdout — is reported once at the end.
type writer struct {
	w   io.Writer
	err error
}

func (o *writer) line(s string) {
	if o.err != nil {
		return
	}
	_, o.err = io.WriteString(o.w, strings.TrimRight(s, " ")+"\n")
}

func (o *writer) blank() { o.line("") }

// optional prints a field the contract permits to be empty, and prints nothing
// when it is. An empty line under a claim reads as a warrant nobody wrote.
func (o *writer) optional(indent, text string) {
	if text = strings.TrimSpace(text); text != "" {
		o.line(indent + text)
	}
}
