package profile_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"google.golang.org/protobuf/encoding/prototext"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/profile"
)

// registry is a CorpusRegistry over a fixed set of corpus IDs. The interface
// exists so these tests need no database: what the loader asks of the corpus
// tables is one question, and a map answers it exactly as Postgres does.
type registry map[string]struct{}

func (r registry) Exists(_ context.Context, corpusID string) (bool, error) {
	_, ok := r[corpusID]
	return ok, nil
}

func ingested(ids ...string) registry {
	r := make(registry, len(ids))
	for _, id := range ids {
		r[id] = struct{}{}
	}
	return r
}

const minimal = `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - id: wcf-1788-american
    stance: binding
`

func TestResolvedFilterSpecCarriesEveryCorpusAtItsStance(t *testing.T) {
	p, err := profile.Load(context.Background(), []byte(minimal),
		ingested("web-2020", "wcf-1788-american"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	got := map[string]bereanv1.Tier{}
	for _, c := range p.FilterSpec(20).GetCorpora() {
		got[c.GetCorpusId()] = c.GetTier()
	}

	if tier := got["wcf-1788-american"]; tier != bereanv1.Tier_TIER_BINDING {
		t.Errorf("wcf-1788-american: tier = %v, want TIER_BINDING", tier)
	}
}

func TestScriptureIsAppendedToTheCorporaListAtBindingByDefault(t *testing.T) {
	p, err := profile.Load(context.Background(), []byte(minimal),
		ingested("web-2020", "wcf-1788-american"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	tier, ok := corporaByID(p.FilterSpec(20))["web-2020"]
	if !ok {
		t.Fatal("web-2020 absent from the filter spec: every verse citation would fail as a fabrication")
	}
	if tier != bereanv1.Tier_TIER_BINDING {
		t.Errorf("web-2020: tier = %v, want TIER_BINDING", tier)
	}
}

func TestScriptureCarriesItsDeclaredStance(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
  stance: advisory
corpora:
  - id: wcf-1788-american
    stance: binding
`
	p, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "wcf-1788-american"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	if tier := corporaByID(p.FilterSpec(20))["web-2020"]; tier != bereanv1.Tier_TIER_ADVISORY {
		t.Errorf("web-2020: tier = %v, want TIER_ADVISORY", tier)
	}
}

func TestScriptureAtContraryIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
  stance: contrary
corpora:
  - id: wcf-1788-american
    stance: binding
`
	_, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "wcf-1788-american"))
	if err == nil {
		t.Fatal("Load succeeded: no tradition in scope repudiates Scripture, so this profile is wrong (ADR-0011)")
	}
}

func corporaByID(spec *bereanv1.FilterSpec) map[string]bereanv1.Tier {
	byID := make(map[string]bereanv1.Tier, len(spec.GetCorpora()))
	for _, c := range spec.GetCorpora() {
		byID[c.GetCorpusId()] = c.GetTier()
	}
	return byID
}

func TestUnknownStanceIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - id: wcf-1788-american
    stance: authoritative
`
	_, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "wcf-1788-american"))
	if err == nil {
		t.Fatal("Load succeeded: an unknown stance is an error, never a default")
	}
}

func TestContraryWithoutALabelIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - id: wcf-1646-epcew-modernised
    stance: contrary
`
	_, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "wcf-1646-epcew-modernised"))
	if err == nil {
		t.Fatal("Load succeeded: an unlabelled contrary citation is the failure the tier system exists to prevent")
	}
}

func TestExcludedWithoutALabelIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - id: pca-fv-2007
    stance: excluded
`
	_, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "pca-fv-2007"))
	if err == nil {
		t.Fatal("Load succeeded: an unlabelled excluded citation renders with no way to tell the reader what it is")
	}
}

func TestACorpusThatIsNotIngestedIsALoadError(t *testing.T) {
	_, err := profile.Load(context.Background(), []byte(minimal),
		ingested("web-2020"))
	if err == nil {
		t.Fatal("Load succeeded: a profile naming an un-ingested corpus must fail at load")
	}
}

func TestScriptureThatIsNotIngestedIsALoadError(t *testing.T) {
	_, err := profile.Load(context.Background(), []byte(minimal),
		ingested("wcf-1788-american"))
	if err == nil {
		t.Fatal("Load succeeded: an un-ingested translation makes every verse citation fail as a fabrication")
	}
}

func TestAnUnreadableRegistryFailsTheLoad(t *testing.T) {
	_, err := profile.Load(context.Background(), []byte(minimal), brokenRegistry{})
	if err == nil {
		t.Fatal("Load succeeded: a registry that cannot answer is not an answer of `absent`, and must not load a profile it could not check")
	}
}

type brokenRegistry struct{}

func (brokenRegistry) Exists(context.Context, string) (bool, error) {
	return false, errors.New("dial tcp: connection refused")
}

const withContested = `
profile: sentinel-tradition
scripture:
  corpus_id: web-2020
corpora:
  - id: wcf-1788-american
    stance: binding
  - id: pca-ga28-2000-creation-study
    stance: advisory
contested:
  - locus: creation-days
    ruling_source:
      corpus_id: pca-ga28-2000-creation-study
      locator: "Recommendations 1"
`

func TestContestedLociResolveToPointersBesideTheFilterSpec(t *testing.T) {
	p, err := profile.Load(context.Background(), []byte(withContested),
		ingested("web-2020", "wcf-1788-american", "pca-ga28-2000-creation-study"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	loci := p.ContestedLoci()
	if len(loci) != 1 {
		t.Fatalf("ContestedLoci() returned %d loci, want 1", len(loci))
	}
	if got := loci[0].GetLocus(); got != "creation-days" {
		t.Errorf("locus = %q, want %q", got, "creation-days")
	}
	if got := loci[0].GetRuling().GetCorpusId(); got != "pca-ga28-2000-creation-study" {
		t.Errorf("ruling corpus_id = %q, want %q", got, "pca-ga28-2000-creation-study")
	}
	if got := loci[0].GetRuling().GetLocator(); got != "Recommendations 1" {
		t.Errorf("ruling locator = %q, want %q", got, "Recommendations 1")
	}
}

func TestAContestedRulingSourceOutsideTheCorporaListIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - id: wcf-1788-american
    stance: binding
contested:
  - locus: creation-days
    ruling_source:
      corpus_id: pca-ga28-2000-creation-study
      locator: "Recommendations 1"
`
	_, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "wcf-1788-american", "pca-ga28-2000-creation-study"))
	if err == nil {
		t.Fatal("Load succeeded: a locus the profile cannot cite is a locus it cannot defend")
	}
}

func TestAContestedRulingSourceThatIsNotIngestedIsALoadError(t *testing.T) {
	_, err := profile.Load(context.Background(), []byte(withContested),
		ingested("web-2020", "wcf-1788-american"))
	if err == nil {
		t.Fatal("Load succeeded: an un-ingested ruling is what ADR-0015 requires be said honestly, not invented")
	}
}

func TestAContestedEntryWithoutALocatorIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - id: pca-ga28-2000-creation-study
    stance: advisory
contested:
  - locus: creation-days
    ruling_source:
      corpus_id: pca-ga28-2000-creation-study
`
	_, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "pca-ga28-2000-creation-study"))
	if err == nil {
		t.Fatal("Load succeeded: a ruling without a locator resolves to no chunk")
	}
}

func TestTheFilterSpecCarriesNoProfileIdentity(t *testing.T) {
	p, err := profile.Load(context.Background(), []byte(withContested),
		ingested("web-2020", "wcf-1788-american", "pca-ga28-2000-creation-study"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	// Python must be able to serve the request knowing nothing about who asked
	// or which tradition it is (ADR-0015). The profile name is a sentinel that
	// cannot occur in a corpus ID, so any occurrence is a leak.
	sent, err := prototext.Marshal(&bereanv1.AnswerRequest{
		FilterSpec:    p.FilterSpec(20),
		ContestedLoci: p.ContestedLoci(),
	})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if strings.Contains(string(sent), "sentinel-tradition") {
		t.Errorf("the profile name crossed the boundary:\n%s", sent)
	}
}

func TestAnUnknownFieldIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - id: wcf-1788-american
    stance: binding
    notes: American revision
`
	_, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "wcf-1788-american"))
	if err == nil {
		t.Fatal("Load succeeded: a misspelled key silently takes the engine's default, which is the one thing a profile must never do")
	}
	if !strings.Contains(err.Error(), "notes") {
		t.Errorf("error does not name the offending field: %v", err)
	}
}

func TestACorpusNamedTwiceIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - id: wcf-1788-american
    stance: binding
  - id: wcf-1788-american
    stance: advisory
`
	_, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "wcf-1788-american"))
	if err == nil {
		t.Fatal("Load succeeded: one corpus at two stances has no resolution, and the filter spec would carry both")
	}
}

func TestScriptureRepeatedInTheCorporaListIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - id: web-2020
    stance: advisory
`
	_, err := profile.Load(context.Background(), []byte(doc), ingested("web-2020"))
	if err == nil {
		t.Fatal("Load succeeded: Scripture is appended to the corpora list, so naming it twice is the same collision")
	}
}

func TestAProfileWithoutANameIsALoadError(t *testing.T) {
	doc := `
scripture:
  corpus_id: web-2020
corpora:
  - id: wcf-1788-american
    stance: binding
`
	_, err := profile.Load(context.Background(), []byte(doc),
		ingested("web-2020", "wcf-1788-american"))
	if err == nil {
		t.Fatal("Load succeeded: the name is how `--profile` selects this document")
	}
}

func TestAProfileWithoutScriptureIsALoadError(t *testing.T) {
	doc := `
profile: pca
corpora:
  - id: wcf-1788-american
    stance: binding
`
	_, err := profile.Load(context.Background(), []byte(doc), ingested("wcf-1788-american"))
	if err == nil {
		t.Fatal("Load succeeded: with no translation in scope every proof text in the Standards is unverifiable")
	}
	if !strings.Contains(err.Error(), "scripture.corpus_id") {
		t.Errorf("error does not name the missing field, so it reads as an ingestion problem: %v", err)
	}
}

func TestACorpusEntryWithoutAnIDIsALoadError(t *testing.T) {
	doc := `
profile: pca
scripture:
  corpus_id: web-2020
corpora:
  - stance: binding
`
	_, err := profile.Load(context.Background(), []byte(doc), ingested("web-2020"))
	if err == nil {
		t.Fatal("Load succeeded: an entry with no id names no corpus")
	}
	if !strings.Contains(err.Error(), "id is required") {
		t.Errorf("error does not name the missing field, so it reads as an ingestion problem: %v", err)
	}
}

// The committed PCA profile is the Phase 1 tradition, and what it says is a
// doctrinal claim rather than a fixture. Asserting it here means a stance
// edited by hand shows up as a failing test rather than as a changed answer.
func TestTheCommittedPCAProfileResolvesAsWritten(t *testing.T) {
	p, err := profile.LoadFile(context.Background(), "../../../../profiles/pca.yaml", ingested(
		"web-2020",
		"wcf-1788-american",
		"wlc-1788-american",
		"wsc-1788-american",
		"pca-bco-2026",
		"wcf-1646-epcew-modernised",
		"pca-ga28-2000-creation-study",
		"calvin-institutes-1559-beveridge",
	))
	if err != nil {
		t.Fatalf("LoadFile: %v", err)
	}

	want := map[string]bereanv1.Tier{
		"web-2020":                         bereanv1.Tier_TIER_BINDING,
		"wcf-1788-american":                bereanv1.Tier_TIER_BINDING,
		"wlc-1788-american":                bereanv1.Tier_TIER_BINDING,
		"wsc-1788-american":                bereanv1.Tier_TIER_BINDING,
		"pca-bco-2026":                     bereanv1.Tier_TIER_GOVERNING,
		"wcf-1646-epcew-modernised":        bereanv1.Tier_TIER_CONTRARY,
		"pca-ga28-2000-creation-study":     bereanv1.Tier_TIER_ADVISORY,
		"calvin-institutes-1559-beveridge": bereanv1.Tier_TIER_ADVISORY,
	}
	got := corporaByID(p.FilterSpec(20))
	if len(got) != len(want) {
		t.Errorf("filter spec carries %d corpora, want %d", len(got), len(want))
	}
	for id, tier := range want {
		if got[id] != tier {
			t.Errorf("%s: tier = %v, want %v", id, got[id], tier)
		}
	}

	loci := p.ContestedLoci()
	if len(loci) != 1 || loci[0].GetLocus() != "creation-days" {
		t.Fatalf("contested loci = %v, want exactly creation-days", loci)
	}
	if got := loci[0].GetRuling().GetCorpusId(); got != "pca-ga28-2000-creation-study" {
		t.Errorf("creation-days ruling corpus = %q, want the 2000 study report", got)
	}
}
