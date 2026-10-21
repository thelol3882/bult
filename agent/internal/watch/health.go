package watch

// A replica turns unhealthy after this many failed probes in a row and healthy
// again after a single success.
const unhealthyAfter = 3

// health is the probe state machine of one running replica. The zero value is
// not ready; use newHealth.
type health struct {
	healthy bool
	fails   int
}

// newHealth is the state of a replica that has just (re)started: healthy,
// until the probes say otherwise.
func newHealth() health { return health{healthy: true} }

// observe records one probe result.
func (h *health) observe(ok bool) {
	if ok {
		h.healthy = true
		h.fails = 0
		return
	}
	h.fails++
	if h.fails >= unhealthyAfter {
		h.healthy = false
	}
}
