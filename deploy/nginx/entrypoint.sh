#!/bin/sh
# Ingress container entrypoint: the route sidecar in the background, nginx in the foreground.
# Runs under `init: true` (tini is PID 1: forwards signals, reaps orphans).

set -eu

sh /etc/nginx/bult/ingress-sync.sh &

exec nginx -c /etc/nginx/bult/nginx.conf -g 'daemon off;'
