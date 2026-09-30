// The live half of the constraint ledger: it names exactly the CHECK
// constraints the schema has.
//
// Skipped when BEREAN_DATABASE_URL is unset. Run it with `make test-gateway-db`.
package trace

import (
	"database/sql"
	"os"
	"sort"
	"testing"

	_ "github.com/jackc/pgx/v5/stdlib"
)

func TestTheLedgerNamesEveryCheckConstraintInTheSchema(t *testing.T) {
	dsn := os.Getenv("BEREAN_DATABASE_URL")
	if dsn == "" {
		t.Skip("BEREAN_DATABASE_URL unset; run `make test-gateway-db` against a live database")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer func() { _ = db.Close() }()

	rows, err := db.Query(
		`SELECT c.conname
		   FROM pg_constraint c
		   JOIN pg_namespace n ON n.oid = c.connamespace
		  WHERE n.nspname = 'trace' AND c.contype = 'c'`)
	if err != nil {
		t.Fatalf("listing constraints: %v", err)
	}
	defer func() { _ = rows.Close() }()

	live := map[string]bool{}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			t.Fatalf("scan: %v", err)
		}
		live[name] = true
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("listing constraints: %v", err)
	}
	if len(live) == 0 {
		t.Fatal("the schema reports no CHECK constraints, so the query is wrong or the migrations did not run")
	}

	var unclassified, stale []string
	for name := range live {
		if _, found := constraintLedger[name]; !found {
			unclassified = append(unclassified, name)
		}
	}
	for name := range constraintLedger {
		if !live[name] {
			stale = append(stale, name)
		}
	}
	sort.Strings(unclassified)
	sort.Strings(stale)

	for _, name := range unclassified {
		t.Errorf("%s is a CHECK in the schema with no entry in constraintLedger: mirror it in validate() "+
			"with a breach, or say where the gateway derives the value", name)
	}
	for _, name := range stale {
		t.Errorf("%s is in constraintLedger but not in the schema: renamed or dropped by a migration", name)
	}
}
