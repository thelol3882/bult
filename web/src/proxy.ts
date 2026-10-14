import { getIronSession } from 'iron-session';
import { NextResponse, type NextRequest } from 'next/server';
import { getSessionOptions, type SessionData } from '@/shared/auth/session';

const AUTH_PAGES = new Set(['/login', '/register']);

/** Optimistic redirects only; the dashboard layout and the API proxy enforce the session. */
export async function proxy(req: NextRequest) {
    const { pathname, search } = req.nextUrl;
    const response = NextResponse.next();
    const session = await getIronSession<SessionData>(req, response, getSessionOptions());

    if (AUTH_PAGES.has(pathname)) {
        return session.token ? NextResponse.redirect(new URL('/apps', req.url)) : response;
    }
    if (!session.token) {
        const login = new URL('/login', req.url);
        login.searchParams.set('next', `${pathname}${search}`);
        return NextResponse.redirect(login);
    }
    return response;
}

export const config = {
    matcher: ['/apps/:path*', '/new', '/login', '/register'],
};
