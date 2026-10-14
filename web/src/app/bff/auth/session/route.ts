import { fetchMe } from '@/shared/auth/api';
import { shouldDestroySession } from '@/shared/auth/forward';
import { getSession } from '@/shared/auth/session';

const NOT_AUTHENTICATED = { detail: 'Not authenticated', code: 'not_authenticated' };

export async function GET(): Promise<Response> {
    const session = await getSession();
    if (!session.token) return Response.json(NOT_AUTHENTICATED, { status: 401 });

    const me = await fetchMe(session.token);
    if (!me.ok) {
        if (shouldDestroySession(me.response.status)) session.destroy();
        return me.response;
    }
    return Response.json({ user: me.user });
}
