//go:build !unix

package build

import (
	"os/exec"
	"time"
)

const waitDelay = 2 * time.Second

// ownProcessGroup: no process groups here (nodes are Linux); the default
// cancellation kills only the process itself.
func ownProcessGroup(cmd *exec.Cmd) {
	cmd.WaitDelay = waitDelay
}
