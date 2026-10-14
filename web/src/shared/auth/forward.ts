const FORWARDED_REQUEST_HEADERS = ['accept', 'accept-language', 'content-type', 'x-request-id'];
const FORWARDED_RESPONSE_HEADERS = ['content-type', 'x-request-id'];

export const DEFAULT_AFTER_LOGIN = '/apps';

/** Joins the catch-all path onto the API base; null if a segment could escape the base. */
export function buildUpstreamUrl(base: string, segments: string[], search: string): string | null {
    if (segments.some((s) => s === '' || s === '.' || s === '..')) return null;
    const path = segments.map(encodeURIComponent).join('/');
    return `${base.replace(/\/+$/, '')}/${path}${search}`;
}

/** Copies a small allowlist of headers and sets the bearer token; cookies never go upstream. */
export function buildUpstreamHeaders(incoming: Headers, token: string): Headers {
    const headers = new Headers();
    for (const name of FORWARDED_REQUEST_HEADERS) {
        const value = incoming.get(name);
        if (value !== null) headers.set(name, value);
    }
    headers.set('authorization', `Bearer ${token}`);
    return headers;
}

export function buildClientHeaders(upstream: Headers): Headers {
    const headers = new Headers();
    for (const name of FORWARDED_RESPONSE_HEADERS) {
        const value = upstream.get(name);
        if (value !== null) headers.set(name, value);
    }
    return headers;
}

/** A 401 from the API means the token is dead, so the session cookie must go too. */
export function shouldDestroySession(upstreamStatus: number): boolean {
    return upstreamStatus === 401;
}

/** Only same-origin absolute paths; blocks open redirects like `//evil.com` or `/\evil.com`. */
export function safeNext(next: string | null | undefined, fallback = DEFAULT_AFTER_LOGIN): string {
    if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) {
        return fallback;
    }
    if (next === '/login' || next === '/register') return fallback;
    return next;
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/** The origin the browser used: forwarded headers win, then Host, then the request URL. */
function expectedOrigin(req: Request): string {
    const url = new URL(req.url);
    const first = (value: string | null) => value?.split(',')[0]?.trim() || null;
    const proto = first(req.headers.get('x-forwarded-proto')) ?? url.protocol.replace(':', '');
    const host = first(req.headers.get('x-forwarded-host')) ?? req.headers.get('host') ?? url.host;
    return `${proto}://${host}`;
}

/** Unsafe methods must carry an Origin (or Referer) equal to our own; safe methods always pass. */
export function isSameOrigin(req: Request): boolean {
    if (SAFE_METHODS.has(req.method)) return true;

    const origin = req.headers.get('origin');
    let sent: string | null = origin;
    if (!sent) {
        const referer = req.headers.get('referer');
        try {
            sent = referer ? new URL(referer).origin : null;
        } catch {
            sent = null;
        }
    }
    return sent !== null && sent === expectedOrigin(req);
}
