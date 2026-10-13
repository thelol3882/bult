import { Suspense } from 'react';
import type { Metadata } from 'next';
import { AppsListWidget } from '@/widgets/apps-list';

export const metadata: Metadata = { title: 'Apps' };

export default function AppsPage() {
    // The list reads ?page= (useSearchParams), which needs a Suspense boundary.
    return (
        <Suspense>
            <AppsListWidget />
        </Suspense>
    );
}
