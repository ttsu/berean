// The Go half of the normalisation contract.
//
// Verification normalises here and ingestion normalises in Python, so there is
// no shared function and the specs must not ask for one. What is shared is the
// contract and the vectors in testdata/normalisation/vectors.json, which this
// suite and services/catena/tests/test_normalisation.py both read.
//
// The tests below deliberately mirror that Python suite. Two suites asserting
// different things against the same file would leave exactly the gap the file
// exists to close.

package normalise

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

type fixture struct {
	NormalisationVersion int      `json:"normalisation_version"`
	FormatCharacters     []string `json:"format_characters_removed"`
	Whitespace           []string `json:"whitespace"`
	Vectors              []vector `json:"vectors"`
}

type vector struct {
	Name     string `json:"name"`
	Input    string `json:"input"`
	Expected string `json:"expected"`
	Why      string `json:"why"`
}

// repoRoot walks up to the directory holding go.mod. The fixture is shared with
// Python and so cannot live in this package's own testdata directory.
func repoRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("working directory: %v", err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("no go.mod above the working directory; cannot locate the shared fixture")
		}
		dir = parent
	}
}

func loadFixture(t *testing.T) fixture {
	t.Helper()
	path := filepath.Join(repoRoot(t), "testdata", "normalisation", "vectors.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}
	var f fixture
	if err := json.Unmarshal(raw, &f); err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	return f
}

// codePoints turns ["U+00A0", ...] into the set the implementation should hold.
func codePoints(t *testing.T, labels []string) map[rune]struct{} {
	t.Helper()
	set := make(map[rune]struct{}, len(labels))
	for _, label := range labels {
		value, err := strconv.ParseUint(strings.TrimPrefix(label, "U+"), 16, 32)
		if err != nil {
			t.Fatalf("malformed code point %q in the fixture: %v", label, err)
		}
		set[rune(value)] = struct{}{}
	}
	return set
}

func assertSameSet(t *testing.T, name string, got, want map[rune]struct{}) {
	t.Helper()
	for r := range want {
		if _, ok := got[r]; !ok {
			t.Errorf("%s is missing U+%04X, which the contract names", name, r)
		}
	}
	for r := range got {
		if _, ok := want[r]; !ok {
			t.Errorf("%s carries U+%04X, which the contract does not name", name, r)
		}
	}
}

// The sets are asserted directly, not only through the vectors. "Collapse runs
// of whitespace" is two different functions in the two languages -- Go's
// unicode.IsSpace does not match U+001C-U+001F and Python's \s does -- so an
// implementation reaching for the standard library instead of the named set
// passes almost every vector in the file.
func TestVersionMatchesTheFixture(t *testing.T) {
	if got, want := Version, loadFixture(t).NormalisationVersion; got != want {
		t.Errorf("implementation is version %d, vectors are version %d; a bump "+
			"re-blesses every corpus and must be deliberate", got, want)
	}
}

func TestFormatCharactersMatchTheFixture(t *testing.T) {
	f := loadFixture(t)
	assertSameSet(t, "formatCharactersRemoved", formatCharactersRemoved, codePoints(t, f.FormatCharacters))
}

func TestWhitespaceMatchesTheFixture(t *testing.T) {
	f := loadFixture(t)
	assertSameSet(t, "whitespace", whitespace, codePoints(t, f.Whitespace))
}

// Every failure message below escapes to ASCII. The strings this suite
// compares differ by characters that are invisible by construction, and %q
// leaves most of them printable -- a report of `"M\u00e1laga" != "Ma\u0301laga"`
// rendered as two identical words is how this becomes a day of debugging.
func TestEveryVector(t *testing.T) {
	f := loadFixture(t)
	if len(f.Vectors) == 0 {
		t.Fatal("the fixture carries no vectors")
	}
	for _, v := range f.Vectors {
		t.Run(v.Name, func(t *testing.T) {
			if got := Normalise(v.Input); got != v.Expected {
				t.Errorf("Normalise(%s) = %s, want %s\n  %s",
					strconv.QuoteToASCII(v.Input),
					strconv.QuoteToASCII(got),
					strconv.QuoteToASCII(v.Expected),
					v.Why)
			}
		})
	}
}

// Chunks are re-normalised on re-ingestion, and a quote is normalised on every
// verification. A second pass that changed anything would make a fingerprint
// depend on how many times the text had been through the pipeline.
func TestNormalisingTwiceChangesNothing(t *testing.T) {
	for _, v := range loadFixture(t).Vectors {
		t.Run(v.Name, func(t *testing.T) {
			once := Normalise(v.Input)
			if twice := Normalise(once); twice != once {
				t.Errorf("Normalise(%s) = %s, want %s",
					strconv.QuoteToASCII(once),
					strconv.QuoteToASCII(twice),
					strconv.QuoteToASCII(once))
			}
		})
	}
}

// A code point added to a set without a vector beside it is a silent hole: both
// implementations would agree about a character neither had been tested on.
func TestEveryNamedCodePointAppearsInAVector(t *testing.T) {
	f := loadFixture(t)
	var inputs strings.Builder
	for _, v := range f.Vectors {
		inputs.WriteString(v.Input)
	}
	corpus := inputs.String()

	for _, labels := range [][]string{f.Whitespace, f.FormatCharacters} {
		for r := range codePoints(t, labels) {
			if !strings.ContainsRune(corpus, r) {
				t.Errorf("U+%04X is named by the contract but appears in no vector", r)
			}
		}
	}
}
