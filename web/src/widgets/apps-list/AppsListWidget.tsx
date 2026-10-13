'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { parseAsInteger, useQueryState } from 'nuqs';
import { Button, Group, Pagination, Skeleton, Stack } from '@mantine/core';
import { IconPlus, IconRefresh } from '@tabler/icons-react';
import { APPS_PAGE_SIZE, AppsTable, useDeleteApp, useGetAppsQuery } from '@/features/apps';
import { BackendUnavailablePage } from '@/features/error';
import { useStartDeploy } from '@/features/deploys';
import { normalizeError } from '@/shared/api';
import { EmptyState, PageHeader } from '@/shared/components';

export function AppsListWidget() {
    const router = useRouter();
    const [page, setPage] = useQueryState('page', parseAsInteger.withDefault(1));
    const { data, error, isLoading, refetch } = useGetAppsQuery(Math.max(page, 1));
    const apps = data?.results;
    const totalPages = data ? Math.ceil(data.count / APPS_PAGE_SIZE) : 0;
    const { deploy } = useStartDeploy();
    const confirmDelete = useDeleteApp();

    const handleDeploy = async (name: string) => {
        const id = await deploy(name);
        if (id) router.push(`/apps/${name}?deploy=${id}`);
    };

    // The page may be gone (last item deleted, stale URL): the API points to the last one.
    useEffect(() => {
        if (data && data.results.length === 0 && data.count > 0 && data.previous !== null) {
            void setPage(data.previous === 1 ? null : data.previous);
        }
    }, [data, setPage]);

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

            {data?.count === 0 && (
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
                <Stack gap="md">
                    <AppsTable apps={apps} onDeploy={handleDeploy} onDelete={confirmDelete} />
                    {data && data.count > APPS_PAGE_SIZE && (
                        <Group justify="flex-end">
                            <Pagination
                                total={totalPages}
                                value={page}
                                onChange={(value) => setPage(value === 1 ? null : value)}
                            />
                        </Group>
                    )}
                </Stack>
            )}
        </>
    );
}
