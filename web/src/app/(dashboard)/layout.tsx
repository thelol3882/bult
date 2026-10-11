import { DashboardShell } from '@/widgets/dashboard-shell';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
    return <DashboardShell>{children}</DashboardShell>;
}
