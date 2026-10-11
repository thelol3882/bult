#!/bin/sh
# Route sidecar: brings nginx to the desired routes written by the control plane.

set -u

ROUTES_DIR=${ROUTES_DIR:-/routes}
NGINX_CONF=${NGINX_CONF:-/etc/nginx/bult/nginx.conf}
POLL_INTERVAL=${POLL_INTERVAL:-1}

DESIRED="$ROUTES_DIR/desired"
CURRENT="$ROUTES_DIR/current"
STATUS="$ROUTES_DIR/status.json"

log() { echo "ingress-sync: $*" >&2; }

applied=""
if [ -L "$CURRENT" ]; then
    target=$(readlink "$CURRENT")
    applied=${target##*/}
fi
last_tried="$applied"

write_status() {
    err=$(printf '%s' "$3" | tr -d '"\\' | tr '\n\r\t' '   ')
    printf '{"generation": %s, "ok": %s, "error": "%s", "applied_at": "%s"}\n' \
        "$1" "$2" "$err" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATUS.tmp"
    mv "$STATUS.tmp" "$STATUS"
}

point_current() {
    if [ -z "$1" ]; then
        rm -f "$CURRENT"
        return
    fi
    ln -sfn "$1" "$CURRENT.new"
    mv -T "$CURRENT.new" "$CURRENT"
}

apply() {
    gen=$1

    prev=""
    if [ -L "$CURRENT" ]; then
        prev=$(readlink "$CURRENT")
    fi

    point_current "desired/$gen"

    if ! out=$(nginx -c "$NGINX_CONF" -t 2>&1); then
        point_current "$prev"
        msg=$(printf '%s\n' "$out" | grep emerg | head -n 1)
        [ -n "$msg" ] || msg=$(printf '%s\n' "$out" | tail -n 1)
        log "generation $gen rejected: $msg"
        write_status "$gen" false "$msg"
        return
    fi

    if ! out=$(nginx -c "$NGINX_CONF" -s reload 2>&1); then
        point_current "$prev"
        log "generation $gen: reload failed: $out"
        write_status "$gen" false "nginx reload failed: $out"
        return
    fi

    applied=$gen
    log "generation $gen applied"
    write_status "$gen" true ""
}

while [ ! -s /run/nginx.pid ]; do
    sleep 0.2
done

while :; do
    latest=$(cat "$DESIRED/LATEST" 2>/dev/null) || latest=""
    case $latest in
        '' | *[!0-9]*) ;;
        *)
            if [ "$latest" != "$applied" ] && [ "$latest" != "$last_tried" ] \
                && [ -d "$DESIRED/$latest" ]; then
                last_tried=$latest
                apply "$latest"
            fi
            ;;
    esac
    sleep "$POLL_INTERVAL"
done
