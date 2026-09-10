// The request ID is a uuid because `trace.responses.request_id` is, and this
// is where that constraint is enforced in Go rather than discovered in a
// Postgres error at the end of a turn.
package trace

import (
	"regexp"
	"testing"
)

// The canonical form Postgres accepts, with the version nibble and the variant
// bits pinned: a hex string of the right length is not a uuid, and `uuid` is
// the one column type in this schema that will say so only at insert time.
var canonicalV4 = regexp.MustCompile(
	`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func TestARequestIDIsACanonicalVersion4UUID(t *testing.T) {
	id, err := NewRequestID()
	if err != nil {
		t.Fatalf("NewRequestID: %v", err)
	}
	if !canonicalV4.MatchString(id) {
		t.Errorf("NewRequestID = %q, which trace.responses.request_id would refuse", id)
	}
}

// The request ID is the primary key correlating the response, both attempts'
// traces and every verification result. Two turns sharing one is not a
// collision the database papers over — it is the second turn failing its
// insert on a key the first already holds.
func TestRequestIDsAreDistinct(t *testing.T) {
	seen := make(map[string]struct{}, 1000)
	for i := 0; i < 1000; i++ {
		id, err := NewRequestID()
		if err != nil {
			t.Fatalf("NewRequestID: %v", err)
		}
		if _, repeat := seen[id]; repeat {
			t.Fatalf("NewRequestID returned %q twice in %d draws", id, i+1)
		}
		seen[id] = struct{}{}
	}
}
