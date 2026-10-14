import { redirect } from 'next/navigation';
import { getSession } from '@/shared/auth/session';
import { DashboardShell } from '@/widgets/dashboard-shell';

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
    const session = await getSession();
    if (!session.token || !session.user) redirect('/login');

    return <DashboardShell email={session.user.email}>{children}</DashboardShell>;
}
