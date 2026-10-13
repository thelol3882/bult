'use client';

import { useRouter } from 'next/navigation';
import { useQueryState } from 'nuqs';
import { Button, Loader } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
    IconCloudUpload,
    IconExternalLink,
    IconPencil,
    IconRefresh,
    IconTrash,
} from '@tabler/icons-react';
import { AppDetailsCard, EditAppModal, useDeleteApp, useGetAppQuery } from '@/features/apps';
import { BackendUnavailablePage, NotFoundPage } from '@/features/error';
import {
    DeployCard,
    DeployHistory,
    useDeployHistory,
    useDeployPolling,
    useStartDeploy,
} from '@/features/deploys';
import { normalizeError } from '@/shared/api';
import { EmptyState, Mono, PageHeader } from '@/shared/components';
import classes from './AppDetailWidget.module.css';

export function AppDetailWidget({ name }: { name: string }) {
    const router = useRouter();
    const { data: app, error, isLoading, refetch } = useGetAppQuery(name);
    const [deployId, setDeployId] = useQueryState('deploy');
    const { deploy, isStarting } = useStartDeploy();
    const history = useDeployHistory(name);
    // Without ?deploy= show the newest deploy, so the card survives a page refresh.
    const selectedId = deployId ?? history.deploys[0]?.id ?? null;
    const polling = useDeployPolling(name, selectedId);
    // The polled deploy is fresher than the cached history row.
    const deploys = history.deploys.map((d) => (d.id === polling.deploy?.id ? polling.deploy : d));
    const [editOpened, editHandlers] = useDisclosure(false);
    const confirmDelete = useDeleteApp(() => router.push('/apps'));

    const handleDeploy = async () => {
        const id = await deploy(name);
        if (id) await setDeployId(id);
    };

    if (isLoading) {
        return (
            <div className={classes.center}>
                <Loader size="sm" />
            </div>
        );
    }

    if (error || !app) {
        const apiError = normalizeError(error);
        if (apiError.status === 404) return <NotFoundPage />;
        if (apiError.status === 'network') return <BackendUnavailablePage onRetry={refetch} />;
        return (
            <EmptyState
                tone="error"
                title={apiError.message}
                description="Could not load the app."
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
        );
    }

    return (
        <>
            <PageHeader
                title={app.name}
                subtitle={
                    <a
                        href={app.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={classes.link}
                    >
                        <Mono>{app.url}</Mono>
                        <IconExternalLink size={13} />
                    </a>
                }
                actions={
                    <>
                        <Button
                            variant="default"
                            leftSection={<IconPencil size={16} />}
                            onClick={editHandlers.open}
                        >
                            Edit
                        </Button>
                        <Button
                            variant="subtle"
                            color="red"
                            leftSection={<IconTrash size={16} />}
                            onClick={() => confirmDelete(app.name)}
                        >
                            Delete
                        </Button>
                        <Button
                            leftSection={<IconCloudUpload size={16} />}
                            loading={isStarting}
                            onClick={handleDeploy}
                        >
                            Deploy
                        </Button>
                    </>
                }
            />
            <div className={classes.grid}>
                <AppDetailsCard app={app} />
                {selectedId || history.isLoading ? (
                    <DeployCard
                        deploy={polling.deploy}
                        error={polling.error}
                        isLoading={polling.isLoading || history.isLoading}
                        appUrl={app.url}
                    />
                ) : (
                    <EmptyState
                        title="No deploy yet"
                        description="Press Deploy to build and run this app."
                    />
                )}
                <div className={classes.history}>
                    <DeployHistory
                        deploys={deploys}
                        selectedId={selectedId ?? undefined}
                        onSelect={(id) => void setDeployId(id)}
                        isLoading={history.isLoading}
                        error={history.error}
                        hasMore={history.hasMore}
                        isLoadingMore={history.isLoadingMore}
                        onLoadMore={history.loadMore}
                        onRetry={history.refetch}
                    />
                </div>
            </div>
            <EditAppModal app={app} opened={editOpened} onClose={editHandlers.close} />
        </>
    );
}
