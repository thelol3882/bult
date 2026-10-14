import 'server-only';

import { getIronSession, type SessionOptions } from 'iron-session';
import { cookies } from 'next/headers';

export const SESSION_COOKIE = 'bult_session';
export const SESSION_TTL_SEC = 24 * 60 * 60;

export interface SessionUser {
    id: string;
    email: string;
    created_at: string;
}

export interface SessionData {
    /** The API access token. It lives only in this encrypted cookie, never in browser JS. */
    token?: string;
    user?: SessionUser;
}

/** Read per call: `next build` loads route modules without the runtime environment. */
export function getSessionOptions(): SessionOptions {
    const password = process.env.SESSION_SECRET;
    if (!password || password.length < 32) {
        throw new Error('SESSION_SECRET must be set to a string of at least 32 characters');
    }
    return {
        password,
        cookieName: SESSION_COOKIE,
        ttl: SESSION_TTL_SEC,
        cookieOptions: {
            httpOnly: true,
            sameSite: 'lax',
            secure: process.env.NODE_ENV === 'production',
            maxAge: SESSION_TTL_SEC,
            path: '/',
        },
    };
}

export async function getSession() {
    return getIronSession<SessionData>(await cookies(), getSessionOptions());
}
