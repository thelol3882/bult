'use client';

import { useRouter } from 'next/navigation';
import { useQueryState } from 'nuqs';
import { Button, Loader } from '@mantine/core';
import { IconCloudUpload, IconExternalLink, IconRefresh, IconTrash } from '@tabler/icons-react';
import { AppDetailsCard, useDeleteApp, useGetAppQuery } from '@/features/apps';
import { BackendUnavailablePage, NotFoundPage } from '@/features/error';
import { DeployCard, useDeployPolling, useStartDeploy } from '@/features/deploys';
import { normalizeError } from '@/shared/api';
import { EmptyState, Mono, PageHeader } from '@/shared/components';
import classes from './AppDetailWidget.module.css';

export function AppDetailWidget({ name }: { name: string }) {
    const router = useRouter();
    const { data: app, error, isLoading, refetch } = useGetAppQuery(name);
    const [deployId, setDeployId] = useQueryState('deploy');
    const { deploy, isStarting } = useStartDeploy();
    const polling = useDeployPolling(name, deployId);
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
                {deployId ? (
                    <DeployCard
                        deploy={polling.deploy}
                        error={polling.error}
                        isLoading={polling.isLoading}
                    />
                ) : (
                    <EmptyState
                        title="No deploy yet"
                        description="Press Deploy to build and run this app."
                    />
                )}
            </div>
        </>
    );
}
