import type { Metadata } from 'next';
import { safeNext } from '@/shared/auth/forward';
import { AuthPage } from '@/widgets/auth-form';

export const metadata: Metadata = { title: 'Log in' };

type Props = { searchParams: Promise<{ next?: string | string[] }> };

export default async function LoginPage({ searchParams }: Props) {
    const { next } = await searchParams;
    const raw = typeof next === 'string' ? next : undefined;
    const target = safeNext(raw);
    return <AuthPage mode="login" next={target} nextParam={raw ? target : undefined} />;
}
