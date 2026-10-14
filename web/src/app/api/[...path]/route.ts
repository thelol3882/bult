import { apiUrl, rejectCrossOrigin, UNREACHABLE_BODY } from '@/shared/auth/api';
import {
    buildClientHeaders,
    buildUpstreamHeaders,
    buildUpstreamUrl,
    shouldDestroySession,
} from '@/shared/auth/forward';
import { getSession } from '@/shared/auth/session';

type Context = { params: Promise<{ path: string[] }> };

async function proxy(req: Request, { params }: Context): Promise<Response> {
    const rejected = rejectCrossOrigin(req);
    if (rejected) return rejected;

    const session = await getSession();
    if (!session.token) {
        return Response.json(
            { detail: 'Not authenticated', code: 'not_authenticated' },
            { status: 401 },
        );
    }

    const { path } = await params;
    const url = buildUpstreamUrl(apiUrl(), path, new URL(req.url).search);
    if (!url) return Response.json({ detail: 'Not found', code: 'not_found' }, { status: 404 });

    const hasBody = req.method !== 'GET' && req.method !== 'HEAD';
    let upstream: Response;
    try {
        upstream = await fetch(url, {
            method: req.method,
            headers: buildUpstreamHeaders(req.headers, session.token),
            body: hasBody ? await req.arrayBuffer() : undefined,
            cache: 'no-store',
            redirect: 'manual',
        });
    } catch {
        // Plain text on purpose: the client maps unparsable 502s to "API is unreachable".
        return new Response(UNREACHABLE_BODY.detail, { status: 502 });
    }

    if (shouldDestroySession(upstream.status)) session.destroy();

    const noBody = upstream.status === 204 || upstream.status === 304;
    return new Response(noBody ? null : await upstream.arrayBuffer(), {
        status: upstream.status,
        headers: buildClientHeaders(upstream.headers),
    });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
