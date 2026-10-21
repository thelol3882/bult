package docker

import (
	"context"
	"io"

	"github.com/moby/moby/client"
)

// ReplicaEvents streams the replica ids of bult containers that started,
// died, were OOM-killed or were destroyed. An event only says "look again":
// the caller re-reads the container. Both channels are done when the stream
// ends; the error (also on ctx cancellation) is sent before ids is closed.
func (c *Client) ReplicaEvents(ctx context.Context) (<-chan string, <-chan error) {
	filters := make(client.Filters).
		Add("type", "container").
		Add("label", labelManaged+"=true").
		Add("event", "start", "die", "oom", "destroy")
	res := c.api.Events(ctx, client.EventsListOptions{Filters: filters})

	ids := make(chan string)
	errs := make(chan error, 1)
	go func() {
		defer close(ids)
		for {
			select {
			case <-ctx.Done():
				errs <- ctx.Err()
				return
			case err := <-res.Err:
				if err == nil {
					err = io.EOF
				}
				errs <- err
				return
			case m := <-res.Messages:
				id := m.Actor.Attributes[labelReplicaID]
				if id == "" {
					continue
				}
				select {
				case ids <- id:
				case <-ctx.Done():
					errs <- ctx.Err()
					return
				}
			}
		}
	}()
	return ids, errs
}
