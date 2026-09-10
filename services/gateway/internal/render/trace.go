package render

import (
	"fmt"
	"io"
	"strings"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/turn"
)

// Trace writes what happened, as a log.
//
// **A log, not a narrative.** Every line is a fact with a name on it: a
// setting, a candidate and its score, a check and its outcome, a duration. It
// contains no account of how the answer was arrived at, because no such account
// exists anywhere in this system and inventing one here would be the exact
// thing ADR-0003 forbids — post-hoc rationalisation, wearing a diagnostic's
// clothes.
//
// It prints no answer prose at all, from the attempt that won or from the one
// that did not. `--show-work` is provenance; a refused attempt's position
// reaching a reader through it is the same failure as rendering it directly,
// with a flag in front.
func Trace(w io.Writer, t turn.Turn, sources Sources, version string) error {
	out := &writer{w: w}

	out.field("request", t.RequestID)
	out.field("profile", t.Profile)
	out.field("query", t.Query)
	out.field("gateway", version)
	out.field("result", overall(t.Overall))

	for _, attempt := range t.Attempts {
		out.blank()
		out.line(fmt.Sprintf("attempt %d", attempt.Number))
		settings(out, attempt.Trace)
		// Beside the three stage timings Python reports rather than below the
		// candidate list, because together the four account for everything a
		// turn spends and a reader attributing a slow turn wants them adjacent.
		out.indented("verify", attempt.Verify.String())
		candidates(out, attempt.Trace, sources)
		checks(out, attempt.Results)
		answerFailures(out, attempt.Failures)
	}
	return out.err
}

// settings logs what this attempt ran under: the two numbers most likely to
// move a Phase 2 comparison silently, and the three stage timings.
func settings(out *writer, trace *bereanv1.RetrievalTrace) {
	if trace == nil {
		// Not skipped. A turn whose attempt carries no retrieval trace is a
		// turn that errored rather than one that degraded, and a log that
		// simply omitted the attempt would show two outcomes as one.
		out.indented("retrieval", "absent — catena returned no trace for this attempt")
		return
	}

	out.indented("rewritten_query", trace.GetRewrittenQuery())
	out.indented("embedding_model", fmt.Sprintf("%s (dim %d)", trace.GetEmbeddingModel(), trace.GetDim()))
	out.indented("generation_model", trace.GetGenerationModel())
	out.indented("top_k", fmt.Sprint(trace.GetTopK()))

	timings := trace.GetTimings()
	out.indented("timings", fmt.Sprintf("embed %dms, search %dms, generate %dms",
		timings.GetEmbedMs(), timings.GetSearchMs(), timings.GetGenerateMs()))
}

// candidates logs every chunk retrieval considered, included or not.
//
// The list is printed whole rather than sampled. It is the thing that makes a
// retrieval regression visible — Scripture is roughly 90% of the Phase 1 index
// and nothing balances corpus proportions — so a confessional question answered
// entirely from verses is a result only the full list shows.
func candidates(out *writer, trace *bereanv1.RetrievalTrace, sources Sources) {
	if trace == nil {
		return
	}
	found := trace.GetCandidates()
	out.indented("candidates", fmt.Sprintf("%d considered, %d included",
		len(found), included(found)))
	for rank, candidate := range found {
		// `rank` has no counterpart in the contract — a repeated field carries
		// its order positionally — and it is the whole of what recall@k means,
		// so it is printed here exactly as `trace.candidates` stores it.
		state := "dropped"
		if candidate.GetIncluded() {
			state = "included"
		}
		// The tier is joined on from the resolved profile rather than read
		// from the candidate, because nothing Catena sends carries one — tier
		// is a per-tradition stance, not a property of a chunk. It is here
		// because "which tiers did retrieval actually surface" is the first
		// question asked of a confessional question answered entirely from
		// verses, and Scripture is roughly 90% of the Phase 1 index.
		line := fmt.Sprintf("    %3d  %.4f  %-8s [%s] %s %s",
			rank+1, candidate.GetScore(), state,
			tier(sources[candidate.GetCorpusId()].Tier),
			candidate.GetCorpusId(), candidate.GetLocator())
		if reason := strings.TrimSpace(candidate.GetExclusionReason()); reason != "" {
			line += "  (" + reason + ")"
		}
		out.line(line)
	}
}

func included(candidates []*bereanv1.Candidate) int {
	n := 0
	for _, candidate := range candidates {
		if candidate.GetIncluded() {
			n++
		}
	}
	return n
}

// checks logs the four checks per citation.
//
// All four are named on every line, passing or failing. "The citation failed"
// without which check failed sends whoever reads it hunting, and a line that
// named only the failures would make a passing citation and an unchecked one
// look the same.
func checks(out *writer, results []*bereanv1.VerificationResult) {
	if len(results) == 0 {
		return
	}
	out.indented("citations", fmt.Sprintf("%d checked", len(results)))
	for _, result := range results {
		ref := result.GetCitationRef()
		verdict := "pass"
		if result.GetFailureDetail() != "" {
			verdict = "FAIL"
		}
		out.line(fmt.Sprintf("    %s  %s %s  locator=%s quote=%s tier=%s license=%s",
			verdict, ref.GetCorpusId(), ref.GetLocator(),
			yesno(result.GetLocatorResolved()), yesno(result.GetQuoteMatched()),
			yesno(result.GetTierPermitted()), yesno(result.GetLicensePermitted())))
		if detail := strings.TrimSpace(result.GetFailureDetail()); detail != "" {
			out.line("          " + detail)
		}
	}
}

// answerFailures logs the rules that are about a slot rather than a citation
// (ADR-0024). They are listed separately because they are: the omission check
// fires on an answer whose every citation passed all four checks, and folding
// it in beside them would print four passes next to a failure.
func answerFailures(out *writer, failures []*bereanv1.AnswerFailure) {
	if len(failures) == 0 {
		return
	}
	out.indented("answer failures", fmt.Sprint(len(failures)))
	for _, failure := range failures {
		out.line(fmt.Sprintf("    %s  %s", code(failure.GetCode()), failure.GetSlot()))
		if detail := strings.TrimSpace(failure.GetDetail()); detail != "" {
			out.line("      " + detail)
		}
		if ref := failure.GetCitationRef(); ref.GetCorpusId() != "" || ref.GetLocator() != "" {
			out.line(fmt.Sprintf("      %s %s", ref.GetCorpusId(), ref.GetLocator()))
		}
	}
}

func yesno(ok bool) string {
	if ok {
		return "yes"
	}
	return "no"
}

// overall and code name their enum values in the vocabulary the trace tables
// store, so a line on screen and a row in Postgres can be grepped for the same
// string. The same derivation as `tier` and `level`, for the same reason.
func overall(r bereanv1.OverallResult) string {
	return label(r.String(), "OVERALL_RESULT_")
}

func code(c bereanv1.AnswerFailureCode) string {
	return label(c.String(), "ANSWER_FAILURE_CODE_")
}

func label(constant, prefix string) string {
	return strings.ReplaceAll(strings.ToLower(strings.TrimPrefix(constant, prefix)), "_", "-")
}

// field and indented are the log's two shapes: a header fact about the turn,
// and a fact about the attempt currently being logged.
func (o *writer) field(name, value string) {
	o.line(fmt.Sprintf("%-10s %s", name, value))
}

func (o *writer) indented(name, value string) {
	o.line(fmt.Sprintf("  %-17s %s", name, value))
}
