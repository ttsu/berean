// Package normalise implements the normalisation contract, Go side.
//
// Verification normalises here; ingestion normalises in Python. There is no
// shared function and the specs must not ask for one -- what is shared is this
// ordered list of steps and the vectors in testdata/normalisation/vectors.json,
// which both suites read.
//
// Fingerprints are hashes of post-normalisation text, so changing anything in
// this file invalidates every committed fingerprint file and forces a re-bless
// of every corpus. Bump Version when that happens; the manifests record which
// contract version they were blessed under, so the re-bless is visible rather
// than silent.
//
// Every code point below is written as an escape. These characters are
// invisible by definition, and a table of them written literally cannot be
// reviewed.
//
// See INTEGRATION-SPEC, "Normalisation contract".
package normalise

import (
	"strings"

	"golang.org/x/text/unicode/norm"
)

// Version is the contract version, not a version of this file. Bumping it
// re-blesses every corpus.
const Version = 1

// Step 0. Invisible, and whitespace in neither language's standard library, so
// they survive every later step intact and produce a quote mismatch on text
// that is visually identical. They arrive from ordinary PDF and HTML
// extraction, which is the whole reason this step exists.
var formatCharactersRemoved = map[rune]struct{}{
	'\uFEFF': {}, // zero width no-break space, used as a byte order mark
	'\u200B': {}, // zero width space
	'\u200C': {}, // zero width non-joiner
	'\u200D': {}, // zero width joiner
	'\u00AD': {}, // soft hyphen
}

// Step 2. Exactly the Unicode White_Space property, enumerated rather than
// tested for.
//
// Naming the set is load-bearing, and unicode.IsSpace is not a shortcut to it
// even though it happens to agree today: Python's \s and str.isspace also match
// U+001C-U+001F, so "collapse whitespace" written against either standard
// library is two different functions. Writing the set out is what makes the two
// implementations answerable to the same list rather than to their own
// libraries.
var whitespace = map[rune]struct{}{
	'\u0009': {}, // character tabulation
	'\u000A': {}, // line feed
	'\u000B': {}, // line tabulation
	'\u000C': {}, // form feed
	'\u000D': {}, // carriage return
	'\u0020': {}, // space
	'\u0085': {}, // next line
	'\u00A0': {}, // no-break space
	'\u1680': {}, // ogham space mark
	'\u2000': {}, // en quad
	'\u2001': {}, // em quad
	'\u2002': {}, // en space
	'\u2003': {}, // em space
	'\u2004': {}, // three-per-em space
	'\u2005': {}, // four-per-em space
	'\u2006': {}, // six-per-em space
	'\u2007': {}, // figure space
	'\u2008': {}, // punctuation space
	'\u2009': {}, // thin space
	'\u200A': {}, // hair space
	'\u2028': {}, // line separator
	'\u2029': {}, // paragraph separator
	'\u202F': {}, // narrow no-break space
	'\u205F': {}, // medium mathematical space
	'\u3000': {}, // ideographic space
}

// Normalise applies the contract's steps, in order.
//
//  0. Remove the format characters above.
//  1. Unicode NFC -- never NFKC, which would rewrite ligatures and fullwidth
//     forms into different text.
//  2. Collapse runs of whitespace to a single U+0020.
//  3. Trim the ends.
//  4. Nothing else. No case folding, no quote or dash folding, no punctuation
//     stripping: a quote differing from its source by a curly apostrophe is a
//     genuine mismatch and must fail.
//
// Step 0 runs before step 1 rather than after, and the order is the decision
// rather than an accident. A zero width joiner sitting between a base letter
// and its combining mark blocks composition, so normalising first leaves a
// decomposed sequence that stripping afterwards cannot repair.
func Normalise(text string) string {
	var stripped strings.Builder
	stripped.Grow(len(text))
	for _, r := range text {
		if _, drop := formatCharactersRemoved[r]; drop {
			continue
		}
		stripped.WriteRune(r)
	}

	composed := norm.NFC.String(stripped.String())

	// Steps 2 and 3 in one pass. A leading run finds nothing written yet and a
	// trailing run is never flushed, which is the trim.
	var out strings.Builder
	out.Grow(len(composed))
	pendingSpace := false
	for _, r := range composed {
		if _, isSpace := whitespace[r]; isSpace {
			pendingSpace = true
			continue
		}
		if pendingSpace && out.Len() > 0 {
			out.WriteByte(' ')
		}
		pendingSpace = false
		out.WriteRune(r)
	}
	return out.String()
}
