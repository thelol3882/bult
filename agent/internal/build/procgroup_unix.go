//go:build unix

package build

import (
	"errors"
	"os/exec"
	"syscall"
	"time"
)

// waitDelay bounds how long Wait lingers after the process is killed: a
// grandchild that survived could still hold the output pipe open.
const waitDelay = 2 * time.Second

// ownProcessGroup puts cmd in its own process group and makes cancellation
// kill the whole group. Killing only git leaves its helpers
// (git-remote-https, index-pack) alive, and they keep the pipes open.
func ownProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		// A negative pid addresses the group whose id is the leader's pid.
		err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		if errors.Is(err, syscall.ESRCH) {
			return nil
		}
		return err
	}
	cmd.WaitDelay = waitDelay
}
