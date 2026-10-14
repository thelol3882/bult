export interface Credentials {
    email: string;
    password: string;
}

export async function readCredentials(req: Request): Promise<Credentials | null> {
    const body: unknown = await req.json().catch(() => null);
    if (typeof body !== 'object' || body === null) return null;
    const { email, password } = body as Record<string, unknown>;
    if (typeof email !== 'string' || typeof password !== 'string') return null;
    return { email, password };
}
