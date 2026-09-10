package config_test

import (
	"testing"

	"github.com/ttsu/berean/services/gateway/internal/config"
)

func env(values map[string]string) func(string) string {
	return func(key string) string { return values[key] }
}

func TestTheServingOptInDefaultsToDeny(t *testing.T) {
	if config.ServeLocalOnly(env(nil)) {
		t.Error("ServeLocalOnly = true with the variable unset; the default is deny")
	}
}

func TestTheServingOptInAcceptsExactlyWhatCatenaAccepts(t *testing.T) {
	for _, value := range []string{"1", "true", "TRUE", " yes ", "on"} {
		if !config.ServeLocalOnly(env(map[string]string{config.ServeLocalOnlyEnv: value})) {
			t.Errorf("%q: ServeLocalOnly = false, want true", value)
		}
	}
	for _, value := range []string{"", "0", "false", "no", "off", "y", "sure"} {
		if config.ServeLocalOnly(env(map[string]string{config.ServeLocalOnlyEnv: value})) {
			t.Errorf("%q: ServeLocalOnly = true; anything but an affirmative is a no", value)
		}
	}
}

func TestTopKDefaultsWhenUnset(t *testing.T) {
	got, err := config.TopK(env(nil))
	if err != nil {
		t.Fatalf("TopK: %v", err)
	}
	if got != config.DefaultTopK {
		t.Errorf("TopK = %d, want %d", got, config.DefaultTopK)
	}
}

func TestTopKReadsAConfiguredDepth(t *testing.T) {
	got, err := config.TopK(env(map[string]string{config.TopKEnv: "40"}))
	if err != nil {
		t.Fatalf("TopK: %v", err)
	}
	if got != 40 {
		t.Errorf("TopK = %d, want 40", got)
	}
}

func TestAMalformedDepthIsAnErrorRatherThanTheDefault(t *testing.T) {
	for _, value := range []string{"twenty", "20.5", "0", "-1"} {
		if _, err := config.TopK(env(map[string]string{config.TopKEnv: value})); err == nil {
			t.Errorf("%q: TopK returned no error; a typo must not become the default silently", value)
		}
	}
}

func TestADepthBeyondTheContractsWidthIsAnErrorRatherThanAWrappedNumber(t *testing.T) {
	// The contract carries `top_k` as an int32 and `Atoi` returns a 64-bit int,
	// so the conversion narrows. 2147483648 wraps to -2147483648 and 4294967296
	// wraps to 0; both would reach Postgres as a `top_k > 0` violation on the
	// trace insert, a whole turn away from the typo.
	for _, value := range []string{"2147483648", "4294967296", "99999999999999999999"} {
		got, err := config.TopK(env(map[string]string{config.TopKEnv: value}))
		if err == nil {
			t.Errorf("%q: TopK = %d with no error", value, got)
		}
	}
}

func TestTheProfileDirectoryDefaultsToTheRepositoryLayout(t *testing.T) {
	if got := config.ProfileDir(env(nil)); got != config.DefaultProfileDir {
		t.Errorf("ProfileDir = %q, want %q", got, config.DefaultProfileDir)
	}
}

func TestTheProfileDirectoryIsWhereTheDeploymentPutIt(t *testing.T) {
	got := config.ProfileDir(env(map[string]string{config.ProfileDirEnv: " /etc/berean/profiles "}))
	if want := "/etc/berean/profiles"; got != want {
		t.Errorf("ProfileDir = %q, want %q", got, want)
	}
}
