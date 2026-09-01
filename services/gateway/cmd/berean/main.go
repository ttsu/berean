// Command berean is the Phase 1 CLI and the system's trust boundary.
//
// It will resolve the profile, make one gRPC call into Catena, verify every
// citation that comes back, persist a trace, and print. None of that exists
// yet: Task 1 builds the skeleton the acceptance test runs against, and the
// commands land in Tasks 6, 8, and 10.
package main

import (
	"fmt"
	"os"
)

// Set by the linker. Traces record it, because "which build produced this
// answer" is the first question asked of a verification failure.
var version = "0.0.0-dev"

const usage = `berean — tradition-aware theology and ecclesiology Q&A

Usage:
  berean ask --profile <name> "question"   (Task 10)
  berean version

Phase 1 is under construction. See specs/001-phase-1-pca-baseline/PLAN.md.
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}

	switch os.Args[1] {
	case "version":
		fmt.Println(version)
	case "ask":
		fmt.Fprintln(os.Stderr, "berean: `ask` is not implemented yet (PLAN Task 10)")
		os.Exit(69)
	default:
		fmt.Fprintf(os.Stderr, "berean: unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
}
