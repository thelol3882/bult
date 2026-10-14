import Image from 'next/image';
import Link from 'next/link';
import { Card } from '@mantine/core';
import { AuthForm } from '@/features/auth';
import { Logo } from '@/shared/components';
import classes from './AuthPage.module.css';

interface AuthPageProps {
    mode: 'login' | 'register';
    next: string;
    /** Preserves the post-login target when switching between the two pages. */
    nextParam?: string;
}

export function AuthPage({ mode, next, nextParam }: AuthPageProps) {
    const isRegister = mode === 'register';
    const suffix = nextParam ? `?next=${encodeURIComponent(nextParam)}` : '';

    return (
        <main className={classes.root}>
            <div className={classes.sky} aria-hidden="true">
                <Image
                    src="/images/sky-hero.jpg"
                    alt=""
                    fill
                    priority
                    sizes="100vw"
                    className={classes.photo}
                />
            </div>
            <Link href="/" className={classes.brand}>
                <Logo />
                bult
            </Link>
            <Card className={classes.card} padding="xl">
                <h1 className={classes.title}>
                    {isRegister ? 'Create your account' : 'Welcome back'}
                </h1>
                <p className={classes.subtitle}>
                    {isRegister ? 'Deploy your first app in minutes.' : 'Log in to your dashboard.'}
                </p>
                <AuthForm mode={mode} next={next} />
                <p className={classes.switch}>
                    {isRegister ? 'Already have an account? ' : 'New to bult? '}
                    <Link href={`${isRegister ? '/login' : '/register'}${suffix}`}>
                        {isRegister ? 'Log in' : 'Create an account'}
                    </Link>
                </p>
            </Card>
        </main>
    );
}
