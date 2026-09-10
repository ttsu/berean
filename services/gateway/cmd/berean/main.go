// Command berean is the Phase 1 CLI and the system's trust boundary.
//
// One turn per invocation: resolve the profile, make one gRPC call into Catena,
// verify every citation that comes back, persist the whole turn, and print. The
// decisions live in `internal/` — this file wires them together in that order,
// and the order is load-bearing.
//
// No CLI framework, one command, standard-library flags. TECHNICAL-SPEC calls
// scope discipline the thing that keeps Phase 1 affordable, and a dependency
// that parses arguments is the first place that discipline usually goes.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/catena"
	"github.com/ttsu/berean/services/gateway/internal/config"
	"github.com/ttsu/berean/services/gateway/internal/corpus"
	"github.com/ttsu/berean/services/gateway/internal/profile"
	"github.com/ttsu/berean/services/gateway/internal/render"
	"github.com/ttsu/berean/services/gateway/internal/trace"
	"github.com/ttsu/berean/services/gateway/internal/turn"
	"github.com/ttsu/berean/services/gateway/internal/verify"
)

// Set by the linker. Traces record it, because "which build produced this
// answer" is the first question asked of a verification failure. The trace
// store refuses to open without one, so the default below is what makes an
// un-flagged `go build` usable rather than a value anything relies on.
var version = "0.0.0-dev"

// sysexits, as `catena` uses them. A caller distinguishing "I typed it wrong"
// from "the stack is down" reads the same numbers from either binary.
const (
	exitOK      = 0
	exitFail    = 1
	exitUsage   = 64
	exitUnavail = 69
)

const usage = `berean — tradition-aware theology and ecclesiology Q&A

Usage:
  berean ask --profile <name> [--top-k N] [--show-work] "question"
  berean version

Flags come before the question: the question is the one positional argument,
and it must be quoted.

Environment:
  BEREAN_DATABASE_URL     Postgres, as the gateway role. Required.
  BEREAN_CATENA_ADDR      host:port of the Catena gRPC service. Required.
  BEREAN_PROFILE_DIR      Where <name>.yaml lives. Default: profiles
  BEREAN_TOP_K            Retrieval depth. Default: 20
  BEREAN_SERVE_LOCAL_ONLY Opt in to serving local-only corpora. Default: false
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(exitUsage)
	}

	switch os.Args[1] {
	case "version":
		fmt.Println(version)
	case "ask":
		os.Exit(ask(os.Args[2:]))
	default:
		fmt.Fprintf(os.Stderr, "berean: unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(exitUsage)
	}
}

// options is what the command line said.
type options struct {
	profile  string
	question string
	showWork bool
	// Zero when no override was given, which is what `depth` reads.
	topK int32
}

// depth is the retrieval depth this turn actually runs at. The flag wins over
// the configured default, and the value that wins is the one recorded in the
// trace — a depth nobody logged cannot be held constant across a comparison.
func (o options) depth(configured int32) int32 {
	if o.topK > 0 {
		return o.topK
	}
	return configured
}

// parseAsk reads the flags and the one positional argument.
//
// A usage error rather than a default at every turn. There is no default
// tradition: `--profile` selects which corpora are authoritative, and guessing
// at that is guessing at the answer.
func parseAsk(args []string) (options, error) {
	var opts options
	var topK int

	fs := flag.NewFlagSet("ask", flag.ContinueOnError)
	fs.SetOutput(io.Discard) // The error is returned and printed once, with usage.
	fs.StringVar(&opts.profile, "profile", "", "the tradition to answer as")
	fs.BoolVar(&opts.showWork, "show-work", false, "print the trace after the answer")
	fs.IntVar(&topK, "top-k", 0, "retrieval depth, overriding the configured default")
	if err := fs.Parse(args); err != nil {
		return options{}, err
	}

	if opts.profile == "" {
		return options{}, errors.New("--profile is required: which corpora are authoritative is the question's first half")
	}
	switch fs.NArg() {
	case 1:
		opts.question = fs.Arg(0)
	case 0:
		return options{}, errors.New("no question given")
	default:
		// Almost always an unquoted question, and the first word of one is not
		// a question. Answering it would spend two generations on a query
		// nobody asked.
		return options{}, fmt.Errorf("%d positional arguments; the question is one argument and must be quoted", fs.NArg())
	}

	// The same rule `internal/config` applies to `BEREAN_TOP_K`, because it is
	// the same value arriving by a different route.
	if visited(fs, "top-k") && topK <= 0 {
		return options{}, fmt.Errorf("--top-k %d: a depth of zero or less retrieves nothing, which reads as an empty corpus", topK)
	}
	opts.topK = int32(topK)
	return opts, nil
}

func visited(fs *flag.FlagSet, name string) bool {
	found := false
	fs.Visit(func(f *flag.Flag) {
		if f.Name == name {
			found = true
		}
	})
	return found
}

// recorder is the trace store, as this file needs it. An interface so the
// ordering rule below can be asserted against a store that refuses.
type recorderStore interface {
	Write(ctx context.Context, t turn.Turn) error
}

// deliver persists the turn and then prints it. **In that order, always.**
//
// A turn that reached a user and was never recorded is the one outcome the
// trace tables exist to prevent (INTEGRATION-SPEC, `internal/trace`).
// Verification refusing to ship is a recorded event; a write that failed after
// the answer was printed is not. So a failed write costs the user an answer
// that was already generated and already verified — which is the trade, taken
// deliberately, because the alternative is an audit log with holes in it and no
// way to know where.
func deliver(ctx context.Context, store recorderStore, out io.Writer,
	t turn.Turn, sources render.Sources, opts options, build string) error {
	if err := store.Write(ctx, t); err != nil {
		return fmt.Errorf("recording turn %s: %w", t.RequestID, err)
	}
	if err := render.Answer(out, t, sources); err != nil {
		return err
	}
	if !opts.showWork {
		return nil
	}
	if _, err := io.WriteString(out, "\n"); err != nil {
		return err
	}
	return render.Trace(out, t, sources, build)
}

// ask runs one turn, and returns the process's exit status.
//
// A degraded answer exits 0. Degradation is a *successful* outcome of the
// verification system rather than an error — the user was told the sources
// could not carry the answer, which is the product working — and an exit code
// saying otherwise would invite a caller to read the degradation rate off it.
// That rate lives in `trace.responses.overall_result`, where it can be counted
// against the turns that verified.
func ask(args []string) int {
	opts, err := parseAsk(args)
	if err != nil {
		fmt.Fprintf(os.Stderr, "berean ask: %v\n\n%s", err, usage)
		return exitUsage
	}

	ctx := context.Background()
	if err := run(ctx, opts); err != nil {
		fmt.Fprintf(os.Stderr, "berean ask: %v\n", err)
		if errors.Is(err, errUnavailable) {
			return exitUnavail
		}
		return exitFail
	}
	return exitOK
}

// errUnavailable marks the failures that are about the stack rather than about
// the request: an unreachable database, an unreachable Catena, a profile that
// is not installed. They are what `docker compose up` not being finished looks
// like, and they are worth a different exit code from a turn that ran and
// failed.
var errUnavailable = errors.New("the stack is not ready")

func run(ctx context.Context, opts options) error {
	dsn := os.Getenv(config.DatabaseURLEnv)
	if dsn == "" {
		return fmt.Errorf("%w: %s is unset", errUnavailable, config.DatabaseURLEnv)
	}
	address := os.Getenv(config.CatenaAddrEnv)
	if address == "" {
		return fmt.Errorf("%w: %s is unset", errUnavailable, config.CatenaAddrEnv)
	}
	configuredTopK, err := config.TopK(os.Getenv)
	if err != nil {
		return err
	}

	registry, err := corpus.Open(dsn)
	if err != nil {
		return fmt.Errorf("%w: %w", errUnavailable, err)
	}
	defer registry.Close()

	// The profile is validated against what is actually ingested, so this is
	// also where a half-provisioned stack is caught — before a question is sent
	// to a model that would spend minutes answering it from a corpus that is
	// not there. It is also the first statement anything here runs, which is
	// what proves the database is reachable before a generation is spent on a
	// turn that could not be recorded afterwards.
	document, err := profile.LoadFile(ctx,
		filepath.Join(config.ProfileDir(os.Getenv), opts.profile+".yaml"), registry)
	if err != nil {
		return fmt.Errorf("%w: %w", errUnavailable, err)
	}

	client, err := catena.Dial(address)
	if err != nil {
		return fmt.Errorf("%w: %w", errUnavailable, err)
	}
	defer client.Close()

	// A second pool to the same database under the same role. `trace.NewStore`
	// would take the registry's, and the cost of reaching it is an accessor on
	// `corpus.Registry` handing out its `*sql.DB` — which is a wider seam than
	// one extra connection on a process that makes one turn and exits.
	store, err := trace.Open(dsn, version)
	if err != nil {
		return fmt.Errorf("%w: %w", errUnavailable, err)
	}
	defer store.Close()

	requestID, err := trace.NewRequestID()
	if err != nil {
		return err
	}

	spec := document.FilterSpec(opts.depth(configuredTopK))
	runner := turn.NewRunner(client, verify.New(registry, config.ServeLocalOnly(os.Getenv)))
	result, err := runner.Ask(ctx, turn.Question{
		RequestID: requestID,
		Query:     opts.question,
		Profile:   document.Name(),
		Spec:      spec,
		Loci:      document.ContestedLoci(),
	})
	if err != nil {
		return err
	}

	sources, err := describe(ctx, registry, document, spec)
	if err != nil {
		return err
	}
	return deliver(ctx, store, os.Stdout, result, sources, opts, version)
}

// describe assembles what renders beside a citation, from the two places that
// hold it: the corpus tables know what a work is called and which edition this
// is, and the resolved profile knows what standing this tradition gives it and
// what to call a corpus it does not hold.
//
// Keyed on the FilterSpec rather than on the answer's citations, so it is the
// same set for every turn against one profile — and so a corpus that renders
// with no description is a missing row rather than a lookup this function
// forgot to make.
func describe(ctx context.Context, registry *corpus.Registry,
	document *profile.Profile, spec *bereanv1.FilterSpec) (render.Sources, error) {
	ids := make([]string, 0, len(spec.GetCorpora()))
	for _, entry := range spec.GetCorpora() {
		ids = append(ids, entry.GetCorpusId())
	}
	works, err := registry.Works(ctx, ids)
	if err != nil {
		return nil, err
	}

	sources := make(render.Sources, len(ids))
	for _, entry := range spec.GetCorpora() {
		id := entry.GetCorpusId()
		sources[id] = render.Corpus{
			Work:    works[id].Work,
			Edition: works[id].Edition,
			// From the resolved profile, never from the citation: the tier
			// Python claimed is not the tier this tradition assigns, and
			// rendering the claim would show a reader the one number the
			// gateway spent a check refusing to believe.
			Tier:  entry.GetTier(),
			Label: document.Label(id),
		}
	}
	return sources, nil
}
