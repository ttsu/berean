// Package profile loads a tradition's profile document and resolves it into
// the filter sent to Catena.
//
// The profile is the tradition's doctrinal commitment: which corpora are in
// scope and what stance this tradition takes toward each. It is loaded and
// held by Go and **never crosses the boundary** — what crosses is the resolved
// filter, plus the loci the tradition holds open as pointers (ADR-0015).
//
// See INTEGRATION-SPEC, "Profile document schema".
package profile

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"

	"gopkg.in/yaml.v3"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
)

// CorpusRegistry answers the one question the loader asks of the corpus
// tables: is this corpus ingested? It is an interface so the profile tests
// need no database; the coupling is at wiring time.
type CorpusRegistry interface {
	Exists(ctx context.Context, corpusID string) (bool, error)
}

// document is the profile exactly as written. It is unexported because nothing
// outside this package should hold an unvalidated profile.
type document struct {
	Profile   string           `yaml:"profile"`
	Scripture scripture        `yaml:"scripture"`
	Corpora   []corpusEntry    `yaml:"corpora"`
	Contested []contestedEntry `yaml:"contested"`
}

type scripture struct {
	CorpusID string `yaml:"corpus_id"`
	Stance   string `yaml:"stance"`
}

type corpusEntry struct {
	ID     string `yaml:"id"`
	Stance string `yaml:"stance"`
	// Internal. Read by nothing and rendered nowhere — it is here so that a
	// note in the document parses under strict decoding, and so the reason for
	// a stance lives beside the stance.
	Note string `yaml:"note"`
	// Shown to the user beside every citation this corpus carries. Required at
	// `contrary` and `excluded`.
	Label string `yaml:"label"`
}

// contestedEntry asserts a status — this locus is open within this tradition —
// and points at the document that establishes it. It carries no prose of its
// own: every word shown to a user comes from the corpus and is verified
// verbatim like any other quote.
type contestedEntry struct {
	Locus        string    `yaml:"locus"`
	RulingSource rulingRef `yaml:"ruling_source"`
}

type rulingRef struct {
	CorpusID string `yaml:"corpus_id"`
	Locator  string `yaml:"locator"`
}

// Profile is a validated profile document.
type Profile struct {
	doc document
}

// tiers maps the stance a profile writes to the tier the contract carries.
// Unknown stances are not defaulted: see validation.
var tiers = map[string]bereanv1.Tier{
	"binding":   bereanv1.Tier_TIER_BINDING,
	"governing": bereanv1.Tier_TIER_GOVERNING,
	"advisory":  bereanv1.Tier_TIER_ADVISORY,
	"contrary":  bereanv1.Tier_TIER_CONTRARY,
	"excluded":  bereanv1.Tier_TIER_EXCLUDED,
}

// LoadFile reads and validates the profile document at path.
func LoadFile(ctx context.Context, path string, reg CorpusRegistry) (*Profile, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read profile: %w", err)
	}
	p, err := Load(ctx, data, reg)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return p, nil
}

// Load parses and validates a profile document.
func Load(ctx context.Context, data []byte, reg CorpusRegistry) (*Profile, error) {
	var doc document
	// Strict: an unrecognised key is an error rather than a silent omission. A
	// profile records doctrinal commitments, and a misspelled `stance` that
	// falls through to the engine's default is exactly the kind of failure
	// this document exists to make impossible.
	dec := yaml.NewDecoder(bytes.NewReader(data))
	dec.KnownFields(true)
	if err := dec.Decode(&doc); err != nil {
		return nil, fmt.Errorf("parse profile: %w", err)
	}
	if doc.Scripture.Stance == "" {
		doc.Scripture.Stance = "binding"
	}
	if err := validate(ctx, doc, reg); err != nil {
		return nil, err
	}
	return &Profile{doc: doc}, nil
}

// validate rejects a profile the engine cannot honour. Every rule here fails
// the load rather than defaulting: a profile is a doctrinal commitment, and
// guessing at one is worse than refusing to start.
func validate(ctx context.Context, doc document, reg CorpusRegistry) error {
	if doc.Profile == "" {
		return errors.New("profile: a name is required — it is how `--profile` selects this document")
	}
	if doc.Scripture.CorpusID == "" {
		return errors.New("scripture.corpus_id is required: with no translation in scope, every proof text in the Standards is unverifiable")
	}
	switch doc.Scripture.Stance {
	case "binding", "governing", "advisory":
	default:
		return fmt.Errorf(
			"scripture.stance %q: no tradition in scope repudiates Scripture, so `contrary` and `excluded` are rejected; want binding, governing or advisory (ADR-0011)",
			doc.Scripture.Stance)
	}

	// Scripture is appended to this list at resolution, so it shares the
	// namespace: one corpus at two stances has no resolution, and a filter
	// spec carrying both would leave Python to pick.
	seen := map[string]struct{}{doc.Scripture.CorpusID: {}}
	declared := make(map[string]struct{}, len(doc.Corpora))
	for i, c := range doc.Corpora {
		if c.ID == "" {
			return fmt.Errorf("corpora[%d]: id is required", i)
		}
		if _, duplicate := seen[c.ID]; duplicate {
			return fmt.Errorf("corpus %q is named twice", c.ID)
		}
		seen[c.ID] = struct{}{}
		declared[c.ID] = struct{}{}
		if _, ok := tiers[c.Stance]; !ok {
			return fmt.Errorf("corpus %q: unknown stance %q; want binding, governing, advisory, contrary or excluded",
				c.ID, c.Stance)
		}
		// A `contrary` or `excluded` citation renders with its label. Without
		// one the reader sees another tradition's position with nothing
		// marking it as such, which is the failure the tier system exists to
		// prevent.
		if (c.Stance == "contrary" || c.Stance == "excluded") && c.Label == "" {
			return fmt.Errorf("corpus %q: stance %q requires a label", c.ID, c.Stance)
		}
	}

	for _, c := range doc.Contested {
		if c.Locus == "" {
			return fmt.Errorf("contested entry with ruling %q: locus is required",
				c.RulingSource.Locator)
		}
		if c.RulingSource.Locator == "" {
			return fmt.Errorf("contested locus %q: ruling_source.locator is required, or the ruling resolves to no chunk",
				c.Locus)
		}
		// A locus the profile cannot cite is a locus it cannot defend.
		if _, ok := declared[c.RulingSource.CorpusID]; !ok {
			return fmt.Errorf("contested locus %q: ruling_source.corpus_id %q is absent from `corpora`",
				c.Locus, c.RulingSource.CorpusID)
		}
	}

	// Validation reaches the database. Checking only that an ID appears in the
	// profile's own list proves internal consistency and nothing more: what
	// matters is whether the corpus is ingested, because a profile naming one
	// that is not can cite nothing.
	for _, id := range append([]string{doc.Scripture.CorpusID}, corpusIDs(doc)...) {
		exists, err := reg.Exists(ctx, id)
		if err != nil {
			return fmt.Errorf("corpus registry: checking %q: %w", id, err)
		}
		if !exists {
			return fmt.Errorf("corpus %q is named by the profile but is not ingested", id)
		}
	}
	return nil
}

func corpusIDs(doc document) []string {
	ids := make([]string, 0, len(doc.Corpora))
	for _, c := range doc.Corpora {
		ids = append(ids, c.ID)
	}
	return ids
}

// ContestedLoci resolves the loci this tradition holds open. A sibling of the
// filter spec, never part of it: the filter is retrieval policy and these are
// generation context, and mixing them would make the filter mean two things.
func (p *Profile) ContestedLoci() []*bereanv1.ContestedLocus {
	loci := make([]*bereanv1.ContestedLocus, 0, len(p.doc.Contested))
	for _, c := range p.doc.Contested {
		loci = append(loci, &bereanv1.ContestedLocus{
			Locus: c.Locus,
			Ruling: &bereanv1.CitationRef{
				CorpusId: c.RulingSource.CorpusID,
				Locator:  c.RulingSource.Locator,
			},
		})
	}
	return loci
}

// FilterSpec resolves the profile into the filter sent to Catena: corpus IDs,
// the stance this tradition assigns each, and the gateway's retrieval depth.
// Nothing else — no profile name, no identity, no session state.
func (p *Profile) FilterSpec(topK int32) *bereanv1.FilterSpec {
	spec := &bereanv1.FilterSpec{TopK: topK}
	// Scripture is appended to the corpora list at its resolved stance rather
	// than carried as a parallel channel: a verse citation is verified by the
	// same checks as a confessional one, and a corpus absent from this list is
	// treated as a fabrication.
	spec.Corpora = append(spec.Corpora, &bereanv1.CorpusFilter{
		CorpusId: p.doc.Scripture.CorpusID,
		Tier:     tiers[p.doc.Scripture.Stance],
	})
	for _, c := range p.doc.Corpora {
		spec.Corpora = append(spec.Corpora, &bereanv1.CorpusFilter{
			CorpusId: c.ID,
			Tier:     tiers[c.Stance],
		})
	}
	return spec
}
