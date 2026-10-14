import { rejectCrossOrigin } from '@/shared/auth/api';
import { getSession } from '@/shared/auth/session';

export async function POST(req: Request): Promise<Response> {
    const rejected = rejectCrossOrigin(req);
    if (rejected) return rejected;

    const session = await getSession();
    session.destroy();
    return new Response(null, { status: 204 });
}
