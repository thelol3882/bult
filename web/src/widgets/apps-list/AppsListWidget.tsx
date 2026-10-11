'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Button, Skeleton, Stack } from '@mantine/core';
import { IconPlus, IconRefresh } from '@tabler/icons-react';
import { AppsTable, useDeleteApp, useGetAppsQuery } from '@/features/apps';
import { BackendUnavailablePage } from '@/features/error';
import { useStartDeploy } from '@/features/deploys';
import { normalizeError } from '@/shared/api';
import { EmptyState, PageHeader } from '@/shared/components';

export function AppsListWidget() {
    const router = useRouter();
    const { data: apps, error, isLoading, refetch } = useGetAppsQuery();
    const { deploy } = useStartDeploy();
    const confirmDelete = useDeleteApp();

    const handleDeploy = async (name: string) => {
        const id = await deploy(name);
        if (id) router.push(`/apps/${name}?deploy=${id}`);
    };

    const apiError = error ? normalizeError(error) : undefined;

    const newAppButton = (
        <Button component={Link} href="/new" leftSection={<IconPlus size={16} />}>
            New app
        </Button>
    );

    return (
        <>
            <PageHeader title="Apps" actions={newAppButton} />

            {isLoading && (
                <Stack gap="xs">
                    {Array.from({ length: 3 }, (_, i) => (
                        <Skeleton key={i} height={56} radius="md" />
                    ))}
                </Stack>
            )}

            {error && apiError?.status === 'network' && (
                <BackendUnavailablePage onRetry={refetch} />
            )}

            {error && apiError?.status !== 'network' && (
                <EmptyState
                    tone="error"
                    title={apiError?.message ?? 'Request failed'}
                    description="Could not load apps."
                    action={
                        <Button
                            variant="default"
                            leftSection={<IconRefresh size={16} />}
                            onClick={() => refetch()}
                        >
                            Try again
                        </Button>
                    }
                />
            )}

            {apps?.length === 0 && (
                <EmptyState
                    title="No apps yet"
                    description="Connect a repo to get a URL."
                    action={
                        <Button
                            component={Link}
                            href="/new"
                            size="md"
                            leftSection={<IconPlus size={16} />}
                        >
                            Create your first app
                        </Button>
                    }
                />
            )}

            {apps && apps.length > 0 && (
                <AppsTable apps={apps} onDeploy={handleDeploy} onDelete={confirmDelete} />
            )}
        </>
    );
}
