'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { AppShell } from '@mantine/core';
import { IconApps, IconChevronRight, IconLogout, IconServer } from '@tabler/icons-react';
import { useLogout } from '@/features/auth';
import { Logo } from '@/shared/components';
import classes from './DashboardShell.module.css';

function crumbsFor(pathname: string): string[] {
    const [, section, rest] = pathname.split('/');
    if (section === 'new') return ['Apps', 'New app'];
    if (section === 'nodes') return ['Nodes'];
    if (section !== 'apps' || !rest) return ['Apps'];
    return ['Apps', decodeURIComponent(rest)];
}

export function DashboardShell({ children, email }: { children: ReactNode; email: string }) {
    const logout = useLogout();
    const pathname = usePathname();
    const crumbs = crumbsFor(pathname);
    const isApps = pathname.startsWith('/apps') || pathname === '/new';

    return (
        <AppShell
            layout="alt"
            header={{ height: 56 }}
            navbar={{ width: 240, breakpoint: 'sm' }}
            padding={0}
        >
            <AppShell.Navbar className={classes.navbar}>
                <Link href="/" className={classes.brand}>
                    <Logo size={30} />
                    bult
                </Link>
                <nav className={classes.nav} aria-label="Dashboard">
                    <Link href="/apps" className={classes.link} data-active={isApps || undefined}>
                        <IconApps size={18} stroke={1.75} />
                        Apps
                    </Link>
                    <Link
                        href="/nodes"
                        className={classes.link}
                        data-active={pathname.startsWith('/nodes') || undefined}
                    >
                        <IconServer size={18} stroke={1.75} />
                        Nodes
                    </Link>
                </nav>
                <div className={classes.user}>
                    <span className={classes.email} title={email}>
                        {email}
                    </span>
                    <button
                        type="button"
                        className={classes.logout}
                        onClick={() => void logout()}
                        aria-label="Log out"
                        title="Log out"
                    >
                        <IconLogout size={18} stroke={1.75} />
                    </button>
                </div>
            </AppShell.Navbar>

            <AppShell.Header className={classes.header}>
                <div className={classes.crumbs}>
                    {crumbs.map((crumb, i) => (
                        <span key={crumb} className={classes.crumb}>
                            {i > 0 && <IconChevronRight size={14} />}
                            {i === crumbs.length - 1 ? <b>{crumb}</b> : crumb}
                        </span>
                    ))}
                </div>
            </AppShell.Header>

            <AppShell.Main className={classes.main}>
                <div className={classes.content}>{children}</div>
            </AppShell.Main>
        </AppShell>
    );
}
