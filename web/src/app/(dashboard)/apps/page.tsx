import type { Metadata } from 'next';
import { AppsListWidget } from '@/widgets/apps-list';

export const metadata: Metadata = { title: 'Apps' };

export default function AppsPage() {
    return <AppsListWidget />;
}
