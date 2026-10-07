// Package build turns a user's repository into a Docker build context:
// validate the source, shallow-clone it, and stream it as a tar archive.
// ImageBuild as a job on the build node.
package build
