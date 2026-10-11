import type { Metadata } from 'next';
import { NewAppWidget } from '@/widgets/new-app';

export const metadata: Metadata = { title: 'New app' };

export default function NewAppPage() {
    return <NewAppWidget />;
}
