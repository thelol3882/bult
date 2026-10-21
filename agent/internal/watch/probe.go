package watch

import (
	"context"
	"net"
	"net/http"
	"strconv"
)

// ProbeFunc reports whether the replica published on 127.0.0.1:hostPort is
// alive. An empty path means a TCP connect, otherwise an HTTP GET. The
// context carries the probe's timeout.
type ProbeFunc func(ctx context.Context, hostPort int, path string) bool

// probeClient never follows redirects (a 3xx counts as alive) and never keeps
// connections: a probe must not leave idle sockets behind.
var probeClient = &http.Client{
	Transport: &http.Transport{DisableKeepAlives: true},
	CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	},
}

// Probe is the default ProbeFunc.
func Probe(ctx context.Context, hostPort int, path string) bool {
	addr := net.JoinHostPort("127.0.0.1", strconv.Itoa(hostPort))
	if path == "" {
		var d net.Dialer
		conn, err := d.DialContext(ctx, "tcp", addr)
		if err != nil {
			return false
		}
		_ = conn.Close()
		return true
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://"+addr+path, nil)
	if err != nil {
		return false
	}
	resp, err := probeClient.Do(req)
	if err != nil {
		return false
	}
	_ = resp.Body.Close()
	return resp.StatusCode >= 200 && resp.StatusCode < 400
}
