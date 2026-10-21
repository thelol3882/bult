package watch

import "testing"

func TestHealthStateMachine(t *testing.T) {
	h := newHealth()
	if !h.healthy {
		t.Fatal("a new replica must start healthy")
	}

	h.observe(false)
	h.observe(false)
	if !h.healthy {
		t.Fatal("2 failures must not make the replica unhealthy")
	}
	h.observe(false)
	if h.healthy {
		t.Fatal("the 3rd failure in a row must make it unhealthy")
	}
	h.observe(false)
	if h.healthy {
		t.Fatal("more failures keep it unhealthy")
	}

	h.observe(true)
	if !h.healthy {
		t.Fatal("one success must make it healthy again")
	}
}

func TestHealthSuccessResetsFailureCount(t *testing.T) {
	h := newHealth()
	h.observe(false)
	h.observe(false)
	h.observe(true)
	h.observe(false)
	h.observe(false)
	if !h.healthy {
		t.Fatal("failures separated by a success are not consecutive")
	}
}
