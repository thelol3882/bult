'use client';

import { useRouter } from 'next/navigation';
import { parseAsStringLiteral, useQueryState } from 'nuqs';
import { Button, Loader, Tabs, Tooltip } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
    IconCloudUpload,
    IconExternalLink,
    IconPencil,
    IconPlayerPlay,
    IconPlayerStop,
    IconRefresh,
    IconTrash,
} from '@tabler/icons-react';
import {
    AppDetailsCard,
    EditAppModal,
    EnvCard,
    RoutesCard,
    useDeleteApp,
    useGetAppQuery,
} from '@/features/apps';
import { BackendUnavailablePage, ForbiddenPage, NotFoundPage } from '@/features/error';
import {
    DeployCard,
    DeployHistory,
    LogsPanel,
    ReplicasCard,
    scaleBlockedReason,
    useDeployHistory,
    useDeployPolling,
    useCancelDeploy,
    useRollback,
    useSetReplicas,
    useStartApp,
    useStartDeploy,
    useStopApp,
} from '@/features/deploys';
import { normalizeError } from '@/shared/api';
import { isDeployActive } from '@/shared/types';
import { EmptyState, Mono, PageHeader } from '@/shared/components';
import classes from './AppDetailWidget.module.css';

const TABS = ['overview', 'logs'] as const;

export function AppDetailWidget({ name }: { name: string }) {
    const router = useRouter();
    const { data: app, error, isLoading, refetch } = useGetAppQuery(name);
    const [deployId, setDeployId] = useQueryState('deploy');
    const [tab, setTab] = useQueryState('tab', parseAsStringLiteral(TABS).withDefault('overview'));
    const { deploy, isStarting } = useStartDeploy();
    const { startApp, isStarting: isRestarting } = useStartApp();
    const confirmStop = useStopApp();
    const { scale, isScaling } = useSetReplicas();
    const history = useDeployHistory(name);
    // Without ?deploy= show the newest deploy, so the card survives a page refresh.
    const selectedId = deployId ?? history.deploys[0]?.id ?? null;
    const polling = useDeployPolling(name, selectedId);
    // The polled deploy is fresher than the cached history row.
    const deploys = history.deploys.map((d) => (d.id === polling.deploy?.id ? polling.deploy : d));
    // The newest deploy decides: the API accepts one active deploy per app.
    const deployInProgress = deploys[0] !== undefined && isDeployActive(deploys[0].status);
    const [editOpened, editHandlers] = useDisclosure(false);
    const confirmDelete = useDeleteApp(() => router.push('/apps'));
    const confirmRollback = useRollback((id) => void setDeployId(id));
    const confirmCancel = useCancelDeploy();

    const handleDeploy = async () => {
        const id = await deploy(name);
        if (id) await setDeployId(id);
    };

    const handleStart = async () => {
        const id = await startApp(name);
        if (id) await setDeployId(id);
    };

    // Start needs an image from a deploy that ran; more history pages may still hold one.
    const hasImageToStart = deploys.some((d) => d.restorable) || history.hasMore;
    // Indices can have gaps after a failed replica, so the highest index sets the selector's size.
    const runningReplicas = Math.max(
        1,
        ...(deploys.find((d) => d.status === 'running')?.replicas ?? []).map((r) => r.index + 1),
    );

    const handleScale = async (replicas: number) => {
        const id = await scale(name, replicas);
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
        if (apiError.status === 403) return <ForbiddenPage />;
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
                        {app.replicas === 0 ? (
                            <Tooltip
                                label="Deploy the app first: there is no image to start."
                                disabled={history.isLoading || hasImageToStart}
                            >
                                <span>
                                    <Button
                                        variant="default"
                                        leftSection={<IconPlayerPlay size={16} />}
                                        loading={isRestarting}
                                        disabled={
                                            deployInProgress ||
                                            history.isLoading ||
                                            !hasImageToStart
                                        }
                                        onClick={handleStart}
                                    >
                                        Start
                                    </Button>
                                </span>
                            </Tooltip>
                        ) : (
                            <Button
                                variant="default"
                                leftSection={<IconPlayerStop size={16} />}
                                disabled={deploys[0]?.status !== 'running'}
                                onClick={() => confirmStop(app.name)}
                            >
                                Stop
                            </Button>
                        )}
                        <Button
                            leftSection={<IconCloudUpload size={16} />}
                            loading={isStarting}
                            disabled={deployInProgress}
                            onClick={handleDeploy}
                        >
                            Deploy
                        </Button>
                    </>
                }
            />
            <Tabs
                value={tab}
                onChange={(value) => void setTab(value as (typeof TABS)[number])}
                keepMounted={false}
            >
                <Tabs.List mb="lg">
                    <Tabs.Tab value="overview">Overview</Tabs.Tab>
                    <Tabs.Tab value="logs">Logs</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="overview">
                    <div className={classes.grid}>
                        <div className={classes.stack}>
                            <AppDetailsCard app={app} />
                            <ReplicasCard
                                name={app.name}
                                replicas={app.replicas}
                                blockedReason={
                                    history.isLoading
                                        ? 'Loading deploys…'
                                        : scaleBlockedReason({
                                              newestStatus: deploys[0]?.status,
                                              current: app.replicas,
                                              hasImageToStart,
                                          })
                                }
                                isScaling={isScaling}
                                onApply={handleScale}
                            />
                            <EnvCard app={app} />
                            <RoutesCard app={app} />
                        </div>
                        {selectedId || history.isLoading ? (
                            <DeployCard
                                deploy={polling.deploy}
                                error={polling.error}
                                isLoading={polling.isLoading || history.isLoading}
                                appUrl={app.url}
                                onCancel={confirmCancel}
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
                                onRollback={confirmRollback}
                                rollbackDisabled={deployInProgress}
                                onCancel={confirmCancel}
                            />
                        </div>
                    </div>
                </Tabs.Panel>

                <Tabs.Panel value="logs">
                    <LogsPanel name={app.name} replicaCount={runningReplicas} />
                </Tabs.Panel>
            </Tabs>
            <EditAppModal app={app} opened={editOpened} onClose={editHandlers.close} />
        </>
    );
}
