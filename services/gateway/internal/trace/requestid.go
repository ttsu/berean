package trace

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
)

// NewRequestID mints the key that correlates one turn across everything that
// records it: `trace.responses`, both attempts' `trace.traces` rows, every
// verification result, the `AnswerRequest` Catena receives, and the Langfuse
// span.
//
// It lives beside the writer because the *format* constraint comes from here —
// `trace.responses.request_id` is a `uuid`, chosen so the column everything
// else in the schema keys on is constrained at the one place that can. A
// generator that produced a plain random string would compile, run a whole
// turn, and fail its insert at the end of it.
//
// Version 4 from `crypto/rand` rather than a dependency: sixteen bytes and two
// masked nibbles is the whole of the specification, and `github.com/google/uuid`
// would be a module in `go.mod` for the one function below.
//
// A read failure is returned rather than swallowed. `crypto/rand.Read` does not
// fail in practice, and the alternative to reporting it is a request ID with
// predictable bytes in an audit log.
func NewRequestID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("request id: %w", err)
	}
	// Version 4 in the high nibble of byte 6, and the RFC 4122 variant in the
	// top two bits of byte 8. Postgres accepts any 128 bits as a `uuid`, so
	// nothing downstream would notice these being wrong — which is exactly why
	// they are set here and asserted in the test.
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80

	h := hex.EncodeToString(b[:])
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:32], nil
}
