import type { Metadata } from 'next';
import { safeNext } from '@/shared/auth/forward';
import { AuthPage } from '@/widgets/auth-form';

export const metadata: Metadata = { title: 'Create account' };

type Props = { searchParams: Promise<{ next?: string | string[] }> };

export default async function RegisterPage({ searchParams }: Props) {
    const { next } = await searchParams;
    const raw = typeof next === 'string' ? next : undefined;
    const target = safeNext(raw);
    return <AuthPage mode="register" next={target} nextParam={raw ? target : undefined} />;
}
