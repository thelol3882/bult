import { loginAndSeal, rejectCrossOrigin } from '@/shared/auth/api';
import { readCredentials } from '@/shared/auth/credentials';

export async function POST(req: Request): Promise<Response> {
    const rejected = rejectCrossOrigin(req);
    if (rejected) return rejected;

    const credentials = await readCredentials(req);
    if (!credentials)
        return Response.json({ detail: 'Invalid request', code: 'bad_request' }, { status: 400 });
    return loginAndSeal(credentials.email, credentials.password);
}
