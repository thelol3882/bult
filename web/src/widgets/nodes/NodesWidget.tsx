'use client';

import { Button, Skeleton, Stack } from '@mantine/core';
import { IconRefresh } from '@tabler/icons-react';
import { BackendUnavailablePage } from '@/features/error';
import { NodesTable, useNodes } from '@/features/nodes';
import { EmptyState, PageHeader } from '@/shared/components';

export function NodesWidget() {
    const { nodes, error, isLoading, refetch } = useNodes();

    return (
        <>
            <PageHeader
                title="Nodes"
                subtitle="Machines that build and run apps; updates every 5 s."
            />

            {isLoading && (
                <Stack gap="xs">
                    {Array.from({ length: 3 }, (_, i) => (
                        <Skeleton key={i} height={56} radius="md" />
                    ))}
                </Stack>
            )}

            {error && !nodes && error.status === 'network' && (
                <BackendUnavailablePage onRetry={refetch} />
            )}

            {error && !nodes && error.status !== 'network' && (
                <EmptyState
                    tone="error"
                    title={error.message}
                    description="Could not load nodes."
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

            {nodes && nodes.length === 0 && (
                <EmptyState
                    title="No nodes have reported yet"
                    description="Start bultd with --control-plane-url and a node token; the node appears here after its first heartbeat."
                />
            )}

            {nodes && nodes.length > 0 && <NodesTable nodes={nodes} />}
        </>
    );
}
