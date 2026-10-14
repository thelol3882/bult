import { normalizeError, type ApiError } from '@/shared/api';

export type BffResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };

/** Calls a Next.js BFF route; errors are normalized like RTK Query ones. */
export async function bffRequest<T>(
    path: string,
    method: 'GET' | 'POST',
    body?: unknown,
): Promise<BffResult<T>> {
    let res: Response;
    try {
        res = await fetch(`/bff/auth/${path}`, {
            method,
            headers: body === undefined ? undefined : { 'content-type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
    } catch {
        return { ok: false, error: normalizeError({ status: 'FETCH_ERROR' }) };
    }

    const text = await res.text();
    let data: unknown;
    try {
        data = text ? JSON.parse(text) : undefined;
    } catch {
        return {
            ok: false,
            error: normalizeError({ status: 'PARSING_ERROR', originalStatus: res.status }),
        };
    }
    if (!res.ok) return { ok: false, error: normalizeError({ status: res.status, data }) };
    return { ok: true, data: data as T };
}
