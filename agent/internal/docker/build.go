package docker

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"

	"github.com/moby/moby/api/types/jsonstream"
	"github.com/moby/moby/client"
)

// BuildOptions are the parameters of one image build.
type BuildOptions struct {
	Tag    string            // full reference: registry/app:deploy_id
	Labels map[string]string // provenance (OCI labels, bult.deploy_id)
}

// BuildImage builds an image from a tar build context and writes the build
// output to log. A build failure inside the stream is returned as an error.
func (c *Client) BuildImage(ctx context.Context, buildContext io.Reader, opts BuildOptions, log io.Writer) error {
	res, err := c.api.ImageBuild(ctx, buildContext, client.ImageBuildOptions{
		Tags:        []string{opts.Tag},
		Labels:      opts.Labels,
		Remove:      true,
		ForceRemove: true,
	})
	if err != nil {
		return dockerErr("build image", err)
	}
	defer res.Body.Close()

	dec := json.NewDecoder(res.Body)
	for {
		var msg jsonstream.Message
		if err := dec.Decode(&msg); err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			if ctxErr := ctx.Err(); ctxErr != nil {
				return dockerErr("build image stream", ctxErr)
			}
			return fmt.Errorf("decode build message: %w", err)
		}

		if msg.Stream != "" {
			if _, err := io.WriteString(log, msg.Stream); err != nil {
				return fmt.Errorf("write build log: %w", err)
			}
		}

		if msg.Error != nil {
			return fmt.Errorf("build: %s", msg.Error.Message)
		}
	}

	return nil
}

// PushImage pushes tag to its registry and returns the pushed manifest digest.
func (c *Client) PushImage(ctx context.Context, tag string) (string, error) {
	auth := base64.URLEncoding.EncodeToString([]byte("{}"))

	resp, err := c.api.ImagePush(ctx, tag, client.ImagePushOptions{
		RegistryAuth: auth,
	})
	if err != nil {
		return "", dockerErr("push image", err)
	}

	if err := resp.Wait(ctx); err != nil {
		return "", dockerErr("push image wait", err)
	}

	inspect, err := c.api.ImageInspect(ctx, tag)
	if err != nil {
		return "", dockerErr("inspect pushed image", err)
	}

	repo := tag
	if idx := strings.LastIndex(tag, ":"); idx != -1 {
		repo = tag[:idx]
	}

	prefix := repo + "@"
	for _, rd := range inspect.RepoDigests {
		if strings.HasPrefix(rd, prefix) {
			digest := strings.TrimPrefix(rd, prefix)
			if digest != "" {
				return digest, nil
			}
		}
	}

	return "", fmt.Errorf("push succeeded but image has no digest matching repo %q (repo digests: %v)", repo, inspect.RepoDigests)
}
