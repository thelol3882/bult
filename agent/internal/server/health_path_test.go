package server

import (
	"strings"
	"testing"

	agentv1 "github.com/thelol3882/bult/agent/gen/bult/agent/v1"
	"github.com/thelol3882/bult/agent/internal/docker"
)

func TestValidHealthPath(t *testing.T) {
	tests := []struct {
		path string
		want bool
	}{
		{"/healthz", true},
		{"/", true},
		{"/a/b?x=1", true},
		{"healthz", false},
		{"", false},
		{"/a b", false},
		{"/a\tb", false},
		{"/a\nb", false},
		{"/a\x00b", false},
		{"/" + strings.Repeat("a", maxHealthPath-1), true},
		{"/" + strings.Repeat("a", maxHealthPath), false},
	}
	for _, tc := range tests {
		if got := validHealthPath(tc.path); got != tc.want {
			t.Errorf("validHealthPath(%q) = %v, want %v", tc.path, got, tc.want)
		}
	}
}

func TestExtractHealthPath(t *testing.T) {
	env := []docker.EnvVar{{Name: "A", Value: "1"}, {Name: healthPathEnv, Value: "/healthz"}, {Name: "B", Value: "2"}}
	rest, path := extractHealthPath("r", env)
	if path != "/healthz" {
		t.Errorf("path = %q", path)
	}
	if len(rest) != 2 || rest[0].Name != "A" || rest[1].Name != "B" {
		t.Errorf("env = %v, the reserved variable must be removed", rest)
	}

	for _, bad := range []string{"healthz", "/a b", ""} {
		rest, path := extractHealthPath("r", []docker.EnvVar{{Name: healthPathEnv, Value: bad}})
		if path != "" || len(rest) != 0 {
			t.Errorf("value %q: path=%q env=%v, want TCP fallback and the variable removed", bad, path, rest)
		}
	}

	rest, path = extractHealthPath("r", []docker.EnvVar{{Name: "A", Value: "1"}})
	if path != "" || len(rest) != 1 {
		t.Errorf("no variable: path=%q env=%v", path, rest)
	}
}

func TestToSpecTakesHealthPathOutOfEnv(t *testing.T) {
	req := &agentv1.RunReplicaRequest{
		ReplicaId: "r", AppId: "a",
		Env: []*agentv1.EnvVar{{Name: "A", Value: "1"}, {Name: healthPathEnv, Value: "/up"}},
	}
	spec := toSpec(req)
	if spec.HealthPath != "/up" {
		t.Errorf("HealthPath = %q", spec.HealthPath)
	}
	for _, e := range spec.Env {
		if e.Name == healthPathEnv {
			t.Error("reserved variable leaked into the container env")
		}
	}
}
