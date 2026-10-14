import 'server-only';

import { isSameOrigin } from './forward';
import { getSession, type SessionUser } from './session';

export const apiUrl = () =>
    (process.env.API_INTERNAL_URL ?? 'http://localhost:8000').replace(/\/+$/, '');

export const UNREACHABLE_BODY = { detail: 'API is unreachable', code: 'upstream_unavailable' };

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null;

/** POSTs JSON to the API; null when it cannot be reached. */
export async function postJson(path: string, body: unknown): Promise<Response | null> {
    try {
        return await fetch(`${apiUrl()}${path}`, {
            method: 'POST',
            headers: { 'content-type': 'application/json', accept: 'application/json' },
            body: JSON.stringify(body),
            cache: 'no-store',
        });
    } catch {
        return null;
    }
}

/** Relays an API error body as-is so the client reads the usual `{detail, code, ...}`. */
export async function relayError(upstream: Response): Promise<Response> {
    const text = await upstream.text();
    return new Response(text || null, {
        status: upstream.status,
        headers: { 'content-type': upstream.headers.get('content-type') ?? 'application/json' },
    });
}

export const unreachable = () => Response.json(UNREACHABLE_BODY, { status: 503 });

/** Logs in against the API, stores the token in the session and answers with the user only. */
export async function loginAndSeal(email: string, password: string): Promise<Response> {
    const login = await postJson('/auth/login', { email, password });
    if (!login) return unreachable();
    if (!login.ok) return relayError(login);

    const tokenBody: unknown = await login.json().catch(() => null);
    const token = isRecord(tokenBody) ? tokenBody.access_token : undefined;
    if (typeof token !== 'string') return unreachable();

    const me = await fetchMe(token);
    if (!me.ok) return me.response;

    const session = await getSession();
    session.token = token;
    session.user = me.user;
    await session.save();
    return Response.json({ user: me.user });
}

type MeResult = { ok: true; user: SessionUser } | { ok: false; response: Response };

export async function fetchMe(token: string): Promise<MeResult> {
    let res: Response;
    try {
        res = await fetch(`${apiUrl()}/auth/me`, {
            headers: { authorization: `Bearer ${token}`, accept: 'application/json' },
            cache: 'no-store',
        });
    } catch {
        return { ok: false, response: unreachable() };
    }
    if (!res.ok) return { ok: false, response: await relayError(res) };
    const body: unknown = await res.json().catch(() => null);
    if (!isRecord(body) || typeof body.email !== 'string') {
        return { ok: false, response: unreachable() };
    }
    const { id, email, created_at } = body;
    return { ok: true, user: { id: String(id), email, created_at: String(created_at) } };
}

/** Null when the request may proceed, a 403 response for cross-origin unsafe requests. */
export function rejectCrossOrigin(req: Request): Response | null {
    if (isSameOrigin(req)) return null;
    return Response.json(
        { detail: 'Cross-origin request rejected', code: 'forbidden' },
        { status: 403 },
    );
}
