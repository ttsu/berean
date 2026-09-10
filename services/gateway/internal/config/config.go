// Package config reads the gateway's deployment settings from the environment.
//
// Two of them, and both belong here rather than in a profile: they are
// deployment policy and retrieval tuning, neither of which is a doctrinal
// commitment. A profile records what a tradition holds; it does not record how
// deep this deployment searches or which licences this deployer may serve.
package config

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// Environment variable names, as compose sets them.
const (
	ServeLocalOnlyEnv = "BEREAN_SERVE_LOCAL_ONLY"
	TopKEnv           = "BEREAN_TOP_K"
	CatenaAddrEnv     = "BEREAN_CATENA_ADDR"
	DatabaseURLEnv    = "BEREAN_DATABASE_URL"
)

// DefaultTopK is INTEGRATION-SPEC's retrieval depth. Catena carries the same
// number as its own floor for a request that named none.
const DefaultTopK = 20

// affirmatives is exactly the set Catena's own reader accepts. Written out on
// both sides rather than shared, for the reason the normalisation contract is:
// two standard libraries' idea of "truthy" is two different functions, and the
// one thing that must not vary between them is whether this deployment may
// serve `local-only` text.
var affirmatives = map[string]bool{"1": true, "true": true, "yes": true, "on": true}

// ServeLocalOnly reports whether the deployer has opted in to serving
// `local-only` text.
//
// Anything but an affirmative is a no, and an unset variable is a no. The
// default is deny so that nobody serves restricted text by accident, and the
// opt-in is a recorded act rather than an omission (ADR-0017).
func ServeLocalOnly(lookup func(string) string) bool {
	return affirmatives[strings.ToLower(strings.TrimSpace(lookup(ServeLocalOnlyEnv)))]
}

// TopK reads the configured retrieval depth, falling back to the default when
// unset.
//
// A malformed value is an error rather than a fallback: `top_k` is recorded in
// every trace and is one of the two settings most likely to move the Phase 2
// baseline silently, so a typo that quietly becomes 20 is exactly the failure
// the trace column exists to prevent.
func TopK(lookup func(string) string) (int32, error) {
	raw := strings.TrimSpace(lookup(TopKEnv))
	if raw == "" {
		return DefaultTopK, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil {
		return 0, fmt.Errorf("%s=%q is not a number", TopKEnv, raw)
	}
	if value <= 0 {
		return 0, fmt.Errorf("%s=%d: a depth of zero or less retrieves nothing, which reads as an empty corpus", TopKEnv, value)
	}
	// `Atoi` returns a 64-bit int and the contract's depth is an int32, so the
	// conversion below narrows. Without this the guard above passes and the
	// narrowing wraps: 2147483648 becomes -2147483648, which survives all the
	// way to `trace.traces.top_k CHECK (top_k > 0)` and fails the insert a
	// whole turn away from the typo that caused it — the exact distance this
	// function exists to close.
	if value > math.MaxInt32 {
		return 0, fmt.Errorf("%s=%d is beyond the contract's int32 depth", TopKEnv, value)
	}
	return int32(value), nil
}
