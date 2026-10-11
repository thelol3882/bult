'use client';

import { AppForm } from '@/features/apps';
import { PageHeader } from '@/shared/components';

export function NewAppWidget() {
    return (
        <>
            <PageHeader title="New app" subtitle="Deploy a GitHub repository to bult." />
            <AppForm />
        </>
    );
}
