package watch

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"
)

func portOf(t *testing.T, addr string) int {
	t.Helper()
	_, p, err := net.SplitHostPort(addr)
	if err != nil {
		t.Fatal(err)
	}
	n, err := strconv.Atoi(p)
	if err != nil {
		t.Fatal(err)
	}
	return n
}

func probeWith(timeout time.Duration, port int, path string) bool {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	return Probe(ctx, port, path)
}

func TestProbeHTTP(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/ok":
			w.WriteHeader(http.StatusOK)
		case "/redirect":
			http.Redirect(w, r, "/broken", http.StatusFound) // must not be followed
		case "/broken":
			w.WriteHeader(http.StatusInternalServerError)
		case "/slow":
			select {
			case <-time.After(2 * time.Second):
			case <-r.Context().Done():
			}
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	port := portOf(t, srv.Listener.Addr().String())

	tests := []struct {
		path string
		want bool
	}{
		{"/ok", true},
		{"/redirect", true},
		{"/broken", false},
		{"/missing", false},
		{"/slow", false},
	}
	for _, tc := range tests {
		t.Run(tc.path, func(t *testing.T) {
			if got := probeWith(100*time.Millisecond, port, tc.path); got != tc.want {
				t.Errorf("Probe(%s) = %v, want %v", tc.path, got, tc.want)
			}
		})
	}
}

func TestProbeTCP(t *testing.T) {
	// An empty path is a plain connect: a server that answers 500 to every
	// request is still alive for a TCP probe.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	port := portOf(t, srv.Listener.Addr().String())
	if !probeWith(time.Second, port, "") {
		t.Error("TCP probe of a listening port must succeed")
	}
	srv.Close()
	if probeWith(time.Second, port, "") {
		t.Error("TCP probe of a closed port must fail")
	}
}
